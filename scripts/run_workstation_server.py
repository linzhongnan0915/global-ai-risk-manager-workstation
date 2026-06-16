"""Serve the local dashboard; default page load is committed operational data only."""

from __future__ import annotations

import gzip
import json
import logging
import mimetypes
import os
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from scripts.validate_deployment_artifact import DeploymentArtifactError, validate_deployment_artifact
from src.allocation.rebalance_simulation import simulate_rebalance
from src.market.artifact_bootstrap import build_bootstrap_artifact, build_research_extension, build_strategy_detail
from src.market.artifact_contract import ensure_dashboard_artifact
from src.market.demo_hosting import configure_yfinance_cache, demo_scheduler_label, intraday_scheduler_enabled, is_demo_hosting
from src.market.intraday_config import load_intraday_config, resolve_refresh_interval_minutes
from src.market.intraday_refresh_service import (
    build_refresh_status_payload,
    read_latest_snapshot_payload,
    run_intraday_refresh,
    set_background_scheduler_enabled,
    set_refresh_cadence,
)
from src.market.live_refresh import build_live_overlay, write_live_overlay
from src.market.refresh_auth import EXTERNAL_REFRESH_INTERVAL_MINUTES, classify_refresh_request
from src.market.snapshot_store import read_refresh_status
from src.portfolio.return_alignment import align_strategy_series
from src.reporting.operational_snapshot import (
    load_operational_snapshot_for_response,
    load_or_build_operational_snapshot,
    official_promotion_readiness,
    persist_decision,
    read_decisions,
    refresh_operational_snapshot,
)
from src.risk.limits import load_risk_limits
from src.strategies.shadow_mvp import initialize_database, platform_strategy_registry

logger = logging.getLogger(__name__)

GZIP_MIN_BYTES = 512
GZIP_EXTENSIONS = {".html", ".htm", ".js", ".css", ".json", ".svg"}
MANUAL_REFRESH_COOLDOWN_SECONDS = int(os.environ.get("MANUAL_REFRESH_COOLDOWN_SECONDS", "60"))


def resolve_server_bind(host: str | None = None, port: int | None = None) -> tuple[str, int]:
    resolved_host = host if host is not None else os.environ.get("HOST", "127.0.0.1")
    resolved_port = port if port is not None else int(os.environ.get("PORT", "8765"))
    return resolved_host, resolved_port


def _json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def _maybe_gzip(body: bytes, accept_encoding: str | None) -> tuple[bytes, str | None]:
    if len(body) < GZIP_MIN_BYTES:
        return body, None
    if not accept_encoding or "gzip" not in accept_encoding.lower():
        return body, None
    return gzip.compress(body), "gzip"


def ensure_deployment_artifact(root: Path = PROJECT_ROOT) -> dict:
    artifact_path = root / "output" / "dashboard_artifact.json"
    try:
        return validate_deployment_artifact(artifact_path)
    except DeploymentArtifactError as exc:
        raise SystemExit(f"Startup blocked: {exc}") from exc


def ensure_refresh_artifact(root: Path = PROJECT_ROOT) -> tuple[dict, dict]:
    """Return a legacy refresh artifact, initializing a safe one if Render has no output directory."""
    return ensure_dashboard_artifact(root)


class WorkstationHandler(BaseHTTPRequestHandler):
    server_root = PROJECT_ROOT
    deployment_artifact: dict | None = None
    bootstrap_artifact_bytes: bytes | None = None
    research_extension_bytes: bytes | None = None
    operational_snapshot_bytes: bytes | None = None
    intraday_scheduler_enabled = False
    last_manual_refresh_at = 0.0
    refresh_cooldown_lock = threading.Lock()

    @classmethod
    def warm_artifact_caches(cls, artifact: dict) -> None:
        cls.deployment_artifact = artifact
        cls.bootstrap_artifact_bytes = _json_bytes(build_bootstrap_artifact(artifact))
        cls.research_extension_bytes = _json_bytes(build_research_extension(artifact))

    @classmethod
    def warm_operational_snapshot_cache(cls, root: Path) -> None:
        scheduler_enabled = bool(getattr(cls, "intraday_scheduler_enabled", False))
        snapshot = load_operational_snapshot_for_response(root, scheduler_enabled=scheduler_enabled)
        cls.operational_snapshot_bytes = _json_bytes(snapshot)

    def log_message(self, format: str, *args) -> None:
        return

    def _write_response(
        self,
        body: bytes,
        *,
        status: int = 200,
        content_type: str = "application/json",
        cache_control: str | None = None,
        compress: bool = True,
    ) -> None:
        payload = body
        encoding = None
        if compress:
            payload, encoding = _maybe_gzip(body, self.headers.get("Accept-Encoding"))
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        if encoding:
            self.send_header("Content-Encoding", encoding)
        if cache_control:
            self.send_header("Cache-Control", cache_control)
            self.send_header("Pragma", "no-cache")
        self.end_headers()
        self.wfile.write(payload)

    def _send_precomputed_json(self, body: bytes, *, status: int = 200) -> None:
        self._write_response(
            body,
            status=status,
            content_type="application/json",
            cache_control="no-store, no-cache, must-revalidate",
            compress=True,
        )

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = _json_bytes(payload)
        cache_control = None
        if status == 200:
            cache_control = "no-store, no-cache, must-revalidate"
        self._write_response(
            body,
            status=status,
            content_type="application/json",
            cache_control=cache_control,
            compress=True,
        )

    def _send_redirect(self, location: str, *, status: int = 302) -> None:
        self.send_response(status)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_safe_error(self, exc: Exception, *, status: int = 500, context: str = "request") -> None:
        logger.exception("%s failed", context)
        self._send_json({"ok": False, "error": "Internal server error"}, status=status)

    def _load_artifact(self) -> dict:
        if self.deployment_artifact is not None:
            return self.deployment_artifact
        artifact, _ = ensure_refresh_artifact(self.server_root)
        return artifact

    def _load_live_overlay(self) -> dict | None:
        path = self.server_root / "output" / "live_overlay.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _intraday_config(self) -> dict:
        return load_intraday_config(self.server_root / "data/config/intraday_refresh.yaml")

    def _live_summary_payload(self, refresh: bool = False) -> dict:
        artifact, artifact_state = ensure_refresh_artifact(self.server_root)
        if refresh:
            intraday = run_intraday_refresh(
                force=True,
                artifact_path=self.server_root / "output" / "dashboard_artifact.json",
                config=self._intraday_config(),
            )
            if intraday.get("ok"):
                snapshot = read_latest_snapshot_payload(self._intraday_config())
                overlay = self._overlay_from_intraday_snapshot(snapshot, artifact)
            else:
                overlay = write_live_overlay(artifact, refresh_market=True)
                overlay["intraday_refresh_error"] = intraday.get("error")
        else:
            snapshot_payload = read_latest_snapshot_payload(self._intraday_config())
            if snapshot_payload.get("ok"):
                overlay = self._overlay_from_intraday_snapshot(snapshot_payload, artifact)
            else:
                overlay = self._load_live_overlay()
                if overlay is None:
                    overlay = build_live_overlay(artifact)
        return {"ok": True, "refresh_artifact": artifact_state, **overlay}

    def _overlay_from_intraday_snapshot(self, snapshot_payload: dict, artifact: dict) -> dict:
        marks = snapshot_payload.get("marks") or {}
        return {
            "refreshed_at": marks.get("refreshed_at") or snapshot_payload.get("refresh_completed_at"),
            "data_mode": marks.get("data_mode") or "yfinance_intraday_proxy",
            "market_as_of": marks.get("data_quality", {}).get("latest_observation_ts_et"),
            "market_monitor": marks.get("market_monitor") or artifact.get("market_monitor", []),
            "news_risk": marks.get("news_risk") or artifact.get("news_risk", {}),
            "recommendations": marks.get("recommendations") or artifact.get("recommendations", []),
            "factor_exposure_current": marks.get("factor_exposure_current")
            or artifact.get("factors", {}).get("portfolio_factor_exposure_current", {}),
            "factor_alerts": artifact.get("factors", {}).get("human_review_alerts", []),
            "system_conclusion": artifact.get("decision_review", {}).get("final_decision"),
            "intraday_marks": marks,
            "snapshot_id": snapshot_payload.get("snapshot_id"),
            "evaluation_metadata": marks.get("evaluation_metadata"),
        }

    def _strategy_returns_from_artifact(self, artifact: dict) -> dict[str, list[float]]:
        series_by_id: dict[str, pd.Series] = {}
        for strategy in artifact.get("strategies", []):
            series = strategy.get("risk_packet", {}).get("chart_series", {})
            dates = series.get("dates", [])
            values = series.get("returns", [])
            if dates and values:
                series_by_id[strategy["strategy_id"]] = pd.Series(
                    [float(value) for value in values],
                    index=pd.to_datetime(dates),
                    dtype=float,
                )
        strategy_ids = [strategy["strategy_id"] for strategy in artifact.get("strategies", [])]
        return align_strategy_series(series_by_id, strategy_ids).as_dict()

    def _resolve_static_path(self, raw_path: str) -> Path | None:
        decoded = unquote(raw_path.split("?", 1)[0])
        relative = decoded.lstrip("/").replace("\\", "/")
        if not relative or ".." in relative.split("/"):
            return None
        root = self.server_root.resolve()
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return None
        if candidate.is_file():
            return candidate
        return None

    def _reserve_manual_refresh(self) -> tuple[bool, int]:
        with self.refresh_cooldown_lock:
            now = time.monotonic()
            elapsed = now - WorkstationHandler.last_manual_refresh_at
            if elapsed < MANUAL_REFRESH_COOLDOWN_SECONDS:
                return False, max(1, int(MANUAL_REFRESH_COOLDOWN_SECONDS - elapsed))
            WorkstationHandler.last_manual_refresh_at = now
            return True, 0

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/api/operational-snapshot", "/api/operational-snapshot/"}:
            try:
                body = self.operational_snapshot_bytes
                if body is None or b"official_promotion_readiness" not in body:
                    self.warm_operational_snapshot_cache(self.server_root)
                    body = self.operational_snapshot_bytes
                self._send_precomputed_json(body or b"{}")
            except Exception as exc:
                self._send_safe_error(exc, context="operational-snapshot")
            return
        if parsed.path in {"/api/decisions", "/api/decisions/"}:
            try:
                self._send_json({"ok": True, "decisions": read_decisions(self.server_root)})
            except Exception as exc:
                self._send_safe_error(exc, context="decisions")
            return
        if parsed.path in {"/api/health", "/api/health/"}:
            self._send_json(
                {
                    "status": "ok",
                    "service": "risk_manager_workstation",
                    "demo_hosting": is_demo_hosting(),
                }
            )
            return
        if parsed.path in {"/api/live-summary", "/api/live-summary/"}:
            try:
                self._send_json(self._live_summary_payload(refresh=False))
            except Exception as exc:
                self._send_safe_error(exc, context="live-summary")
            return
        if parsed.path in {"/api/strategy-shadow", "/api/strategy-shadow/"}:
            try:
                query = parse_qs(parsed.query or "")
                status_filter = (query.get("status") or ["ALL"])[0]
                strategies = platform_strategy_registry(
                    self.server_root / "output/research/strategy_factory_v1",
                    self.server_root / "output/research/strategy_21_research_composite_v1",
                    status_filter,
                )
                self._send_json({"ok": True, "status_filter": status_filter.upper(), "strategies": strategies})
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            except Exception as exc:
                self._send_safe_error(exc, context="strategy-shadow")
            return
        if parsed.path in {"/api/artifact/bootstrap", "/api/artifact/bootstrap/"}:
            body = self.bootstrap_artifact_bytes
            if body is None:
                body = _json_bytes(build_bootstrap_artifact(self._load_artifact()))
            self._send_precomputed_json(body)
            return
        if parsed.path in {"/api/artifact/research", "/api/artifact/research/"}:
            body = self.research_extension_bytes
            if body is None:
                body = _json_bytes(build_research_extension(self._load_artifact()))
            self._send_precomputed_json(body)
            return
        if parsed.path in {"/api/artifact/strategy-detail", "/api/artifact/strategy-detail/"}:
            query = parse_qs(parsed.query or "")
            strategy_id = (query.get("strategy_id") or [""])[0].strip()
            if not strategy_id:
                self._send_json({"ok": False, "error": "strategy_id required"}, status=400)
                return
            detail = build_strategy_detail(self._load_artifact(), strategy_id)
            if detail is None:
                self._send_json({"ok": False, "error": "strategy not found"}, status=404)
                return
            self._send_json({"ok": True, **detail})
            return
        if parsed.path in {"/api/refresh/status", "/api/refresh/status/"}:
            try:
                query = parse_qs(parsed.query or "")
                interval = query.get("interval_minutes", [None])[0]
                interval_minutes = int(interval) if interval else None
                self._send_json(build_refresh_status_payload(self._intraday_config(), interval_minutes=interval_minutes))
            except Exception as exc:
                self._send_safe_error(exc, context="refresh-status")
            return
        if parsed.path in {"/api/snapshot/latest", "/api/snapshot/latest/"}:
            try:
                payload = read_latest_snapshot_payload(self._intraday_config())
                status = 200 if payload.get("ok") else 404
                self._send_json(payload, status=status)
            except Exception as exc:
                self._send_safe_error(exc, context="snapshot-latest")
            return
        if parsed.path in {"/api/refresh/cadence", "/api/refresh/cadence/"}:
            self.send_error(405, "Method not allowed")
            return
        if parsed.path in {"", "/"}:
            self._send_redirect("/dashboard/index.html")
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/api/refresh", "/api/refresh/"}:
            try:
                result = refresh_operational_snapshot(self.server_root)
                self.warm_operational_snapshot_cache(self.server_root)
                status = 200 if result.get("ok") else 409 if result.get("error") == "refresh_already_in_progress" else 503
                self._send_json(result, status=status)
            except Exception as exc:
                self._send_safe_error(exc, context="operational-refresh")
            return
        if parsed.path in {"/api/decisions", "/api/decisions/"}:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length else b"{}"
                body = json.loads(raw.decode("utf-8") or "{}")
                decision = persist_decision(self.server_root, body)
                self.warm_operational_snapshot_cache(self.server_root)
                self._send_json(
                    {
                        "ok": True,
                        "decision": decision,
                        "snapshot": load_operational_snapshot_for_response(
                            self.server_root,
                            scheduler_enabled=bool(getattr(WorkstationHandler, "intraday_scheduler_enabled", False)),
                        ),
                    },
                    status=201,
                )
            except (ValueError, json.JSONDecodeError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            except Exception as exc:
                self._send_safe_error(exc, context="decision")
            return
        if parsed.path in {"/api/refresh-data", "/api/refresh-data/"}:
            mode, authorized = classify_refresh_request(self.headers.get("Authorization"))
            if not authorized:
                self._send_json({"ok": False, "error": "Unauthorized refresh token"}, status=401)
                return
            if mode == "manual":
                allowed, retry_after = self._reserve_manual_refresh()
                if not allowed:
                    self._send_json(
                        {
                            "ok": False,
                            "error": "Manual refresh cooldown active",
                            "retry_after_seconds": retry_after,
                        },
                        status=429,
                    )
                    return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length else b"{}"
                body = json.loads(raw.decode("utf-8") or "{}")
                _, artifact_state = ensure_refresh_artifact(self.server_root)
                interval = body.get("interval_minutes")
                if mode == "external":
                    interval = int(interval) if interval is not None else EXTERNAL_REFRESH_INTERVAL_MINUTES
                    force_refresh = False
                else:
                    force_refresh = True
                result = run_intraday_refresh(
                    force=force_refresh,
                    interval_minutes=int(interval) if interval is not None else None,
                    artifact_path=self.server_root / "output" / "dashboard_artifact.json",
                    config=self._intraday_config(),
                )
                if result.get("ok") and result.get("snapshot_id"):
                    artifact = self._load_artifact()
                    snapshot = read_latest_snapshot_payload(self._intraday_config())
                    overlay = self._overlay_from_intraday_snapshot(snapshot, artifact)
                    result = {**result, **overlay, "ok": True}
                result = {**result, "refresh_artifact": artifact_state}
                status = 200 if result.get("ok") else 409 if result.get("error") == "refresh_already_in_progress" else 503
                self._send_json(result, status=status)
            except Exception as exc:
                self._send_safe_error(exc, context="refresh")
            return
        if parsed.path in {"/api/refresh/cadence", "/api/refresh/cadence/"}:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length else b"{}"
                body = json.loads(raw.decode("utf-8") or "{}")
                interval = body.get("interval_minutes")
                if interval is None:
                    self._send_json({"ok": False, "error": "interval_minutes required"}, status=400)
                    return
                self._send_json(set_refresh_cadence(int(interval), config=self._intraday_config()))
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            except Exception as exc:
                self._send_safe_error(exc, context="refresh-cadence")
            return
        if parsed.path not in {"/api/simulate", "/api/simulate/"}:
            self.send_error(404, "Not found")
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json({"error": "Invalid JSON body", "ok": False}, status=400)
            return

        try:
            artifact = self._load_artifact()
            strategy_returns = self._strategy_returns_from_artifact(artifact)
            if not strategy_returns:
                self._send_json(
                    {
                        "ok": False,
                        "error": "No aligned strategy return window available for simulation.",
                    },
                    status=400,
                )
                return
            current_weights = payload.get("current_weights") or artifact.get("allocation", {}).get("current_weights", {})
            target_weights = payload.get("target_weights") or payload.get("simulated_weights") or current_weights
            capital = float(payload.get("capital") or artifact.get("initial_capital") or 1_000_000)
            result = simulate_rebalance(
                strategy_returns,
                artifact.get("strategies", []),
                current_weights,
                target_weights,
                capital,
                load_risk_limits(),
            )
            result["ok"] = True
            self._send_json(result)
        except Exception as exc:
            self._send_safe_error(exc, context="simulate")

    def _serve_static(self, path: str) -> None:
        file_path = self._resolve_static_path(path)
        if file_path is None:
            self.send_error(404, "File not found")
            return
        content = file_path.read_bytes()
        mime, _ = mimetypes.guess_type(str(file_path))
        relative = str(file_path.relative_to(self.server_root)).replace("\\", "/")
        cache_control = None
        if relative.startswith("dashboard/") or relative.startswith("output/"):
            cache_control = "no-store, no-cache, must-revalidate"
        compress = file_path.suffix.lower() in GZIP_EXTENSIONS
        self._write_response(
            content,
            status=200,
            content_type=mime or "application/octet-stream",
            cache_control=cache_control,
            compress=compress,
        )


def _startup_refresh() -> None:
    try:
        artifact, _ = ensure_refresh_artifact(PROJECT_ROOT)
        write_live_overlay(artifact, refresh_market=True)
        print("Live market/news overlay refreshed on startup.")
    except Exception as exc:
        print(f"Startup live refresh skipped: {exc}")


def _intraday_scheduler_loop(root: Path) -> None:
    official_promotion_enabled = os.environ.get("ENABLE_OFFICIAL_PROMOTION", "").strip().lower() in {"1", "true", "yes", "on"}
    while True:
        interval = 10
        try:
            cfg = load_intraday_config(root / "data/config/intraday_refresh.yaml")
            status = read_refresh_status(cfg)
            interval = resolve_refresh_interval_minutes(
                cfg,
                selected_interval_minutes=status.get("selected_interval_minutes"),
            )
            if cfg.get("enabled", True):
                result = refresh_operational_snapshot(root)
                if result.get("ok"):
                    WorkstationHandler.warm_operational_snapshot_cache(root)
                    logger.info("Operational intraday overlay refreshed: %s", result.get("snapshot_id"))
                else:
                    WorkstationHandler.warm_operational_snapshot_cache(root)
                    logger.warning("Operational intraday overlay refresh failed: %s", result.get("error"))
                readiness = official_promotion_readiness(result if isinstance(result, dict) else {})
                if readiness.get("readiness_state") == "READY_FOR_PROMOTION":
                    logger.info("Official promotion readiness: READY_FOR_PROMOTION")
                    if not official_promotion_enabled:
                        logger.info("Official promotion execution disabled; set ENABLE_OFFICIAL_PROMOTION=1 only after manual approval.")
                elif readiness.get("readiness_state") == "EOD_PENDING_OFFICIAL_PROMOTION":
                    logger.info("Official promotion readiness blocked: %s", (readiness.get("blockers") or ["N/A"])[0])
        except Exception as exc:
            logger.exception("Intraday scheduler error: %s", exc)
        time.sleep(max(interval, 1) * 60)


def main(
    host: str | None = None,
    port: int | None = None,
    refresh_on_start: bool = False,
    intraday_scheduler: bool | None = None,
    no_intraday_scheduler: bool = False,
) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    bind_host, bind_port = resolve_server_bind(host, port)
    env_scheduler = os.environ.get("ENABLE_INTRADAY_SCHEDULER", "").strip().lower() in {"1", "true", "yes", "on"}
    scheduler_enabled = bool(not no_intraday_scheduler and (intraday_scheduler is True or env_scheduler))
    set_background_scheduler_enabled(scheduler_enabled)
    WorkstationHandler.intraday_scheduler_enabled = scheduler_enabled
    if refresh_on_start:
        print("Startup official/live refresh is disabled for the Foundation dashboard.")
    WorkstationHandler.warm_operational_snapshot_cache(PROJECT_ROOT)
    server = ThreadingHTTPServer((bind_host, bind_port), WorkstationHandler)
    print(f"Risk Manager workstation server running at http://{bind_host}:{bind_port}/dashboard/index.html")
    print("Default page load: /api/operational-snapshot (official ledger plus separate intraday estimate)")
    if scheduler_enabled:
        threading.Thread(target=_intraday_scheduler_loop, args=(PROJECT_ROOT,), daemon=True).start()
        print("Operational intraday overlay scheduler enabled.")
    else:
        print("Operational intraday overlay scheduler disabled.")
    if os.environ.get("ENABLE_OFFICIAL_PROMOTION", "").strip().lower() in {"1", "true", "yes", "on"}:
        print("Official promotion readiness hook enabled; execute mode remains manual.")
    else:
        print("Official promotion execution disabled. Readiness is reported only.")
    server.serve_forever()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run the Risk Manager workstation server.")
    parser.add_argument("--host", default=None, help="Bind host (default: HOST env or 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="Bind port (default: PORT env or 8765)")
    parser.add_argument("--refresh-on-start", action="store_true", help="Refresh yfinance market/news overlay before serving.")
    parser.add_argument(
        "--intraday-scheduler",
        action="store_true",
        help="Force-start background intraday proxy scheduler (default: on when intraday_refresh.enabled).",
    )
    parser.add_argument(
        "--no-intraday-scheduler",
        action="store_true",
        help="Disable background intraday proxy scheduler.",
    )
    args = parser.parse_args()
    main(
        host=args.host,
        port=args.port,
        refresh_on_start=args.refresh_on_start,
        intraday_scheduler=True if args.intraday_scheduler else None,
        no_intraday_scheduler=args.no_intraday_scheduler,
    )
