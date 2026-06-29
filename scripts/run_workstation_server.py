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
from src.automation import (
    build_automation_intelligence_manifest,
    build_candidate_strategy_identity_bridge,
    build_ml_intelligence_patch_manifest,
    build_strategy_factory_evidence_manifest,
    build_review_draft_eligibility,
    create_review_draft_from_allocation_recommendation,
    read_latest_daily_cycle_status,
    read_latest_allocation_recommendation_artifact,
    read_latest_daily_recommendation_artifact,
    run_daily_automation_cycle,
    write_allocation_recommendation_artifact,
    write_candidate_strategy_identity_bridge,
    write_daily_recommendation_artifact,
    write_ml_intelligence_patch_manifest,
    write_strategy_factory_evidence_manifest,
)
from src.market.artifact_bootstrap import build_bootstrap_artifact, build_research_extension, build_strategy_detail
from src.market.artifact_contract import ensure_dashboard_artifact
from src.market.demo_hosting import configure_yfinance_cache, demo_scheduler_label, intraday_scheduler_enabled, is_demo_hosting
from src.market.intraday_config import load_intraday_config, resolve_refresh_interval_minutes
from src.market.intraday_refresh_service import (
    build_refresh_status_payload,
    read_latest_snapshot_payload,
    refresh_lifecycle_status,
    run_intraday_refresh,
    set_background_scheduler_enabled,
    set_refresh_cadence,
)
from src.market.live_refresh import build_live_overlay, write_live_overlay
from src.market.approved_rebalance_plan import (
    apply_approved_rebalance_plan,
    apply_due_approved_rebalance_plan,
    create_approved_rebalance_plan,
)
from src.market.monthly_rebalance_proposal import (
    create_monthly_rebalance_proposal,
    create_review_draft_from_monthly_proposal,
)
from src.market.paper_rebalance import (
    accept_paper_rebalance_plan,
    apply_paper_rebalance_plan,
    generate_paper_rebalance_plan,
    paper_rebalance_snapshot_payload,
    reject_paper_rebalance_plan,
)
from src.market.recommendation_review_draft import create_recommendation_review_draft
from src.market.refresh_auth import EXTERNAL_REFRESH_INTERVAL_MINUTES, classify_refresh_request
from src.market.snapshot_store import read_refresh_status
from src.portfolio.return_alignment import align_strategy_series
from src.reporting.operational_snapshot import (
    load_operational_snapshot_for_response,
    load_snapshot_summary_for_response,
    load_or_build_operational_snapshot,
    official_promotion_readiness,
    persist_decision,
    read_decisions,
    refresh_operational_snapshot,
)
from src.risk.limits import load_risk_limits
from src.strategy_intelligence import build_strategy_intelligence_payload
from src.strategies.shadow_mvp import initialize_database, platform_strategy_registry
from src.strategies.strategy_factory_admission import (
    activate_portfolio_candidate as activate_variant_portfolio_candidate,
    add_candidate as add_variant_candidate,
    add_portfolio_candidate as add_variant_portfolio_candidate,
    add_to_paper_sandbox as add_variant_to_paper_sandbox,
    apply_to_paper as apply_variant_to_paper,
    generate_allocation_draft as generate_variant_allocation_draft,
    get_admission_status as strategy_factory_admission_status,
    get_portfolio_candidates_status as strategy_factory_portfolio_candidates_status,
    get_sandbox_status as strategy_factory_sandbox_status,
    run_risk_review as run_variant_risk_review,
)
from src.strategies.strategy_factory_plugin import (
    UploadedMaterial,
    add_to_candidate_portfolio,
    apply_to_paper_portfolio,
    base_state as strategy_factory_state,
    generate_allocation_draft,
    get_candidate as strategy_factory_candidate,
    list_candidates as strategy_factory_candidates,
    report_text as strategy_factory_report,
    remove_from_candidate_portfolio,
    run_current_run_backtest_ml,
    run_factory as run_strategy_factory,
    run_full_current_run,
    save_uploaded_materials,
)
from src.strategies.strategy_factory_data import PublicFallbackDataLoader, data_status, load_inventory
from src.universe.universe_refresh_service import (
    load_universe_quality,
    load_universe_snapshot,
    universe_members_payload,
    universe_summary_payload,
)

logger = logging.getLogger(__name__)

GZIP_MIN_BYTES = 512
GZIP_EXTENSIONS = {".html", ".htm", ".js", ".css", ".json", ".svg"}
MANUAL_REFRESH_COOLDOWN_SECONDS = int(os.environ.get("MANUAL_REFRESH_COOLDOWN_SECONDS", "60"))
BOOTSTRAP_REFRESH_COOLDOWN_SECONDS = int(os.environ.get("BOOTSTRAP_REFRESH_COOLDOWN_SECONDS", "60"))


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


def refresh_scheme_b_artifact_state(root: Path = PROJECT_ROOT) -> dict:
    canonical_path = root / "dashboard" / "data" / "canonical_operational.json"
    return {
        "state": "not_required",
        "reason": "refresh_scheme_b_committed_shadow_holdings",
        "legacy_artifact_position_estimate_authoritative": False,
        "canonical_operational_path": str(canonical_path),
    }


class WorkstationHandler(BaseHTTPRequestHandler):
    server_root = PROJECT_ROOT
    deployment_artifact: dict | None = None
    bootstrap_artifact_bytes: bytes | None = None
    research_extension_bytes: bytes | None = None
    operational_snapshot_bytes: bytes | None = None
    intraday_scheduler_enabled = False
    request_bootstrap_enabled = False
    last_manual_refresh_at = 0.0
    refresh_cooldown_lock = threading.Lock()
    bootstrap_refresh_lock = threading.Lock()
    daily_cycle_lock = threading.Lock()
    operational_snapshot_cache_lock = threading.Lock()
    bootstrap_refresh_in_progress = False
    last_bootstrap_refresh_at = 0.0
    daily_cycle_in_progress = False

    @classmethod
    def warm_artifact_caches(cls, artifact: dict) -> None:
        cls.deployment_artifact = artifact
        cls.bootstrap_artifact_bytes = _json_bytes(build_bootstrap_artifact(artifact))
        cls.research_extension_bytes = _json_bytes(build_research_extension(artifact))

    @classmethod
    def warm_operational_snapshot_cache(cls, root: Path, refresh_lifecycle: dict | None = None) -> None:
        scheduler_enabled = bool(getattr(cls, "intraday_scheduler_enabled", False))
        with cls.operational_snapshot_cache_lock:
            snapshot = load_operational_snapshot_for_response(
                root,
                scheduler_enabled=scheduler_enabled,
                refresh_lifecycle=refresh_lifecycle,
            )
            cls.operational_snapshot_bytes = _json_bytes(snapshot)

    @classmethod
    def snapshot_summary_payload(cls, root: Path) -> dict:
        return load_snapshot_summary_for_response(
            root,
            scheduler_enabled=bool(getattr(cls, "intraday_scheduler_enabled", False)),
        )

    @classmethod
    def _run_bootstrap_refresh(cls, root: Path, interval: int) -> None:
        try:
            cfg = load_intraday_config(root / "data/config/intraday_refresh.yaml")
            result = run_intraday_refresh(
                force=False,
                interval_minutes=interval,
                artifact_path=root / "output" / "dashboard_artifact.json",
                config=cfg,
            )
            try:
                cls.warm_operational_snapshot_cache(root)
            except Exception as cache_exc:
                logger.warning("Bootstrap refresh finished but snapshot cache warm failed: %s", cache_exc)
            if result.get("ok"):
                logger.info("Bootstrap intraday refresh finished: %s", result.get("snapshot_id") or result.get("reason"))
            else:
                logger.warning("Bootstrap intraday refresh failed: %s", result.get("error"))
        finally:
            with cls.bootstrap_refresh_lock:
                cls.bootstrap_refresh_in_progress = False

    @classmethod
    def maybe_start_intraday_bootstrap(cls, root: Path) -> dict:
        config_path = root / "data/config/intraday_refresh.yaml"
        if not config_path.exists():
            return {
                "state": "closed",
                "reason": "intraday_config_missing",
                "refresh_needed": False,
                "pending": False,
                "provider_failed": False,
                "refresh_interval_minutes": 30,
            }
        cfg = load_intraday_config(config_path)
        lifecycle = refresh_lifecycle_status(cfg)
        if not bool(cfg.get("enabled", True)):
            return {**lifecycle, "state": "closed", "reason": "intraday_refresh_disabled"}
        if lifecycle.get("state") not in {"refresh_needed", "stale"}:
            return lifecycle
        if not bool(getattr(cls, "request_bootstrap_enabled", False)):
            return lifecycle
        with cls.bootstrap_refresh_lock:
            now = time.monotonic()
            if cls.bootstrap_refresh_in_progress:
                return {**lifecycle, "state": "pending", "reason": "bootstrap_refresh_already_pending"}
            if now - cls.last_bootstrap_refresh_at < BOOTSTRAP_REFRESH_COOLDOWN_SECONDS:
                return {**lifecycle, "state": "pending", "reason": "bootstrap_refresh_cooldown"}
            cls.bootstrap_refresh_in_progress = True
            cls.last_bootstrap_refresh_at = now
            interval = max(int(lifecycle.get("refresh_interval_minutes") or 30), 30)
        threading.Thread(target=cls._run_bootstrap_refresh, args=(root, interval), daemon=True).start()
        return {
            **lifecycle,
            "state": "pending",
            "reason": "bootstrap_refresh_started",
            "requested_refresh_state": lifecycle.get("state"),
        }

    @classmethod
    def _run_daily_cycle_job(cls, root: Path) -> None:
        try:
            result = run_daily_automation_cycle(root, force=False)
            logger.info("Daily automation cycle finished: %s", result.get("status"))
        except Exception as exc:
            logger.warning("Daily automation cycle failed: %s", exc)
        finally:
            with cls.daily_cycle_lock:
                cls.daily_cycle_in_progress = False

    @classmethod
    def maybe_start_daily_cycle(cls, root: Path) -> dict:
        if os.environ.get("DISABLE_DAILY_AUTOMATION_CYCLE", "").strip().lower() in {"1", "true", "yes", "on"}:
            return {"state": "disabled", "reason": "daily_cycle_disabled_by_env", "pending": False}
        with cls.daily_cycle_lock:
            if cls.daily_cycle_in_progress:
                return {"state": "pending", "reason": "daily_cycle_already_pending", "pending": True}
            cls.daily_cycle_in_progress = True
        threading.Thread(target=cls._run_daily_cycle_job, args=(root,), daemon=True).start()
        return {"state": "pending", "reason": "daily_cycle_started", "pending": True}

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

    def _send_markdown_file(self, path: Path) -> None:
        if not path.is_file():
            self._send_json({"ok": False, "error": "strategy factory artifact not found"}, status=404)
            return
        self._write_response(
            path.read_bytes(),
            content_type="text/markdown; charset=utf-8",
            cache_control="no-store, no-cache, must-revalidate",
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

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def _read_upload_materials(self) -> list[UploadedMaterial]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            filename = self.headers.get("X-Filename", "upload.txt")
            return [UploadedMaterial(filename=filename, content=raw)]
        boundary_match = [part for part in content_type.split(";") if "boundary=" in part]
        if not boundary_match:
            raise ValueError("multipart boundary required")
        boundary = boundary_match[0].split("=", 1)[1].strip().strip('"').encode("utf-8")
        materials: list[UploadedMaterial] = []
        for part in raw.split(b"--" + boundary):
            if not part or part in {b"--\r\n", b"--"}:
                continue
            header_blob, _, body = part.partition(b"\r\n\r\n")
            headers = header_blob.decode("utf-8", errors="replace")
            if "filename=" not in headers:
                continue
            filename = headers.split("filename=", 1)[1].split(";", 1)[0].split("\r\n", 1)[0].strip().strip('"')
            body = body.rstrip(b"\r\n")
            if body.endswith(b"--"):
                body = body[:-2].rstrip(b"\r\n")
            materials.append(UploadedMaterial(filename=filename, content=body))
        if not materials:
            raise ValueError("no uploaded files found")
        return materials

    def _paper_rebalance_response(self, extra: dict | None = None) -> dict:
        payload = {
            "ok": True,
            "paper_rebalance": paper_rebalance_snapshot_payload(self.server_root),
            "snapshot": load_operational_snapshot_for_response(
                self.server_root,
                scheduler_enabled=bool(getattr(WorkstationHandler, "intraday_scheduler_enabled", False)),
            ),
        }
        if extra:
            payload.update(extra)
        return payload

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
        if parsed.path in {"/api/strategy-factory", "/api/strategy-factory/"}:
            try:
                state = strategy_factory_state(self.server_root)
                if "monitoring_portfolio" not in state:
                    monitoring = strategy_factory_sandbox_status(self.server_root)
                    sleeves = monitoring.get("sandboxes") or []
                    state["monitoring_portfolio"] = {
                        "schema_version": "strategy_factory_monitoring_portfolio_v1",
                        "state": monitoring.get("state") or "NOT_ADDED",
                        "sleeves": sleeves,
                        "strategy_count": len(sleeves),
                        "total_target_weight": sum(float(row.get("target_weight") or 0.0) for row in sleeves),
                        "latest_monitoring_refresh_status": "PENDING_FIRST_REFRESH"
                        if sleeves
                        else "NO_MONITORED_RESEARCH_STRATEGIES",
                        "live_trading": False,
                        "brokerage_execution": False,
                    }
                if "portfolio_candidates" not in state:
                    state["portfolio_candidates"] = strategy_factory_portfolio_candidates_status(self.server_root)
                self._send_json(state)
            except Exception as exc:
                self._send_safe_error(exc, context="strategy-factory")
            return
        if parsed.path in {"/api/strategy-factory/data/status", "/api/strategy-factory/data/status/"}:
            try:
                self._send_json(data_status())
            except Exception as exc:
                self._send_safe_error(exc, context="strategy-factory-data-status")
            return
        if parsed.path in {"/api/strategy-factory/data/inventory", "/api/strategy-factory/data/inventory/"}:
            try:
                self._send_json(load_inventory())
            except Exception as exc:
                self._send_safe_error(exc, context="strategy-factory-data-inventory")
            return
        if parsed.path in {"/api/strategy-factory/admission/status", "/api/strategy-factory/admission/status/"}:
            try:
                query = parse_qs(parsed.query)
                self._send_json(
                    strategy_factory_admission_status(
                        self.server_root,
                        run_id=(query.get("run_id") or [None])[0],
                        variant_id=(query.get("variant_id") or [None])[0],
                        candidate_id=(query.get("candidate_id") or [None])[0],
                    )
                )
            except Exception as exc:
                self._send_safe_error(exc, context="strategy-factory-admission-status")
            return
        if parsed.path in {"/api/strategy-factory/sandbox/status", "/api/strategy-factory/sandbox/status/"}:
            try:
                query = parse_qs(parsed.query)
                self._send_json(
                    strategy_factory_sandbox_status(
                        self.server_root,
                        run_id=(query.get("run_id") or [None])[0],
                        variant_id=(query.get("variant_id") or [None])[0],
                        sandbox_id=(query.get("sandbox_id") or [None])[0],
                    )
                )
            except Exception as exc:
                self._send_safe_error(exc, context="strategy-factory-sandbox-status")
            return
        if parsed.path in {"/api/strategy-factory/portfolio-candidates/status", "/api/strategy-factory/portfolio-candidates/status/"}:
            try:
                query = parse_qs(parsed.query)
                self._send_json(
                    strategy_factory_portfolio_candidates_status(
                        self.server_root,
                        run_id=(query.get("run_id") or [None])[0],
                        variant_id=(query.get("variant_id") or [None])[0],
                    )
                )
            except Exception as exc:
                self._send_safe_error(exc, context="strategy-factory-portfolio-candidates-status")
            return
        if parsed.path in {"/api/strategy-factory/variants/ranking-report", "/api/strategy-factory/variants/ranking-report/"}:
            try:
                query = parse_qs(parsed.query)
                run_id = (query.get("run_id") or [""])[0].strip()
                if not run_id:
                    state = strategy_factory_state(self.server_root)
                    run_id = ((state.get("variant_review") or {}).get("run_id") or "").strip()
                if not run_id:
                    self._send_json({"ok": False, "error": "run_id required"}, status=400)
                    return
                path = self.server_root / "output" / "strategy_factory" / "runs" / run_id / "variants" / "variant_ranking_report.md"
                self._send_markdown_file(path)
            except Exception as exc:
                self._send_safe_error(exc, context="strategy-factory-variant-ranking-report")
            return
        if parsed.path.startswith("/api/strategy-factory/variants/") and parsed.path.rstrip("/").endswith("/evidence"):
            try:
                parts = [unquote(part) for part in parsed.path.strip("/").split("/")]
                if len(parts) != 5:
                    self.send_error(404, "Not found")
                    return
                variant_id = parts[3]
                query = parse_qs(parsed.query)
                run_id = (query.get("run_id") or [""])[0].strip()
                if not run_id:
                    state = strategy_factory_state(self.server_root)
                    run_id = ((state.get("variant_review") or {}).get("run_id") or "").strip()
                if not run_id:
                    self._send_json({"ok": False, "error": "run_id required"}, status=400)
                    return
                path = self.server_root / "output" / "strategy_factory" / "runs" / run_id / "variants" / variant_id / "evaluation" / "variant_evidence_report.md"
                self._send_markdown_file(path)
            except Exception as exc:
                self._send_safe_error(exc, context="strategy-factory-variant-evidence")
            return
        if parsed.path in {"/api/strategy-factory/candidates", "/api/strategy-factory/candidates/"}:
            try:
                self._send_json({"ok": True, "candidates": strategy_factory_candidates(self.server_root)})
            except Exception as exc:
                self._send_safe_error(exc, context="strategy-factory-candidates")
            return
        if parsed.path.startswith("/api/strategy-factory/candidates/"):
            strategy_id = unquote(parsed.path.rstrip("/").split("/")[-1])
            try:
                candidate = strategy_factory_candidate(self.server_root, strategy_id)
                if candidate is None:
                    self._send_json({"ok": False, "error": "strategy candidate not found"}, status=404)
                    return
                self._send_json({"ok": True, "candidate": candidate})
            except Exception as exc:
                self._send_safe_error(exc, context="strategy-factory-candidate")
            return
        if parsed.path.startswith("/api/strategy-factory/report/"):
            strategy_id = unquote(parsed.path.rstrip("/").split("/")[-1])
            try:
                report = strategy_factory_report(self.server_root, strategy_id)
                if report is None:
                    self._send_json({"ok": False, "error": "strategy report not found"}, status=404)
                    return
                self._write_response(
                    report.encode("utf-8"),
                    content_type="text/markdown; charset=utf-8",
                    cache_control="no-store, no-cache, must-revalidate",
                    compress=True,
                )
            except Exception as exc:
                self._send_safe_error(exc, context="strategy-factory-report")
            return
        if parsed.path in {"/api/snapshot-summary", "/api/snapshot-summary/"}:
            try:
                self._send_json(self.snapshot_summary_payload(self.server_root))
            except Exception as exc:
                self._send_safe_error(exc, context="snapshot-summary")
            return
        if parsed.path in {"/api/strategy-intelligence", "/api/strategy-intelligence/"}:
            try:
                self._send_json(build_strategy_intelligence_payload(self.server_root))
            except Exception as exc:
                self._send_safe_error(exc, context="strategy-intelligence")
            return
        if parsed.path in {"/api/automation-intelligence/manifest", "/api/automation-intelligence/manifest/"}:
            try:
                self._send_json(build_automation_intelligence_manifest(self.server_root))
            except Exception as exc:
                self._send_safe_error(exc, context="automation-intelligence-manifest")
            return
        if parsed.path in {
            "/api/automation-intelligence/strategy-factory-evidence/manifest",
            "/api/automation-intelligence/strategy-factory-evidence/manifest/",
        }:
            try:
                self._send_json(build_strategy_factory_evidence_manifest(self.server_root))
            except Exception as exc:
                self._send_safe_error(exc, context="strategy-factory-evidence-manifest")
            return
        if parsed.path in {
            "/api/automation-intelligence/ml-intelligence-patch/manifest",
            "/api/automation-intelligence/ml-intelligence-patch/manifest/",
        }:
            try:
                strategy_payload = build_strategy_intelligence_payload(self.server_root)
                self._send_json(
                    build_ml_intelligence_patch_manifest(
                        self.server_root,
                        strategy_cards=strategy_payload.get("cards") or [],
                    )
                )
            except Exception as exc:
                self._send_safe_error(exc, context="ml-intelligence-patch-manifest")
            return
        if parsed.path in {
            "/api/automation-intelligence/identity-bridge/manifest",
            "/api/automation-intelligence/identity-bridge/manifest/",
        }:
            try:
                strategy_payload = build_strategy_intelligence_payload(self.server_root)
                self._send_json(
                    build_candidate_strategy_identity_bridge(
                        self.server_root,
                        strategy_cards=strategy_payload.get("cards") or [],
                    )
                )
            except Exception as exc:
                self._send_safe_error(exc, context="identity-bridge-manifest")
            return
        if parsed.path in {
            "/api/automation-intelligence/daily-recommendations/latest",
            "/api/automation-intelligence/daily-recommendations/latest/",
        }:
            try:
                latest = read_latest_daily_recommendation_artifact(self.server_root)
                self._send_json(latest, status=200 if latest.get("ok") else 404)
            except Exception as exc:
                self._send_safe_error(exc, context="daily-recommendations-latest")
            return
        if parsed.path in {
            "/api/automation-intelligence/allocation-recommendations/latest",
            "/api/automation-intelligence/allocation-recommendations/latest/",
        }:
            try:
                latest = read_latest_allocation_recommendation_artifact(self.server_root)
                self._send_json(latest, status=200 if latest.get("ok") else 404)
            except Exception as exc:
                self._send_safe_error(exc, context="allocation-recommendations-latest")
            return
        if parsed.path in {
            "/api/automation-intelligence/review-draft-eligibility/latest",
            "/api/automation-intelligence/review-draft-eligibility/latest/",
        }:
            try:
                self._send_json(
                    {
                        "ok": True,
                        "status": "AVAILABLE",
                        "review_draft_eligibility": build_review_draft_eligibility(self.server_root),
                        "paper_shadow_only": True,
                        "financial_state_mutated": False,
                    }
                )
            except Exception as exc:
                self._send_safe_error(exc, context="review-draft-eligibility-latest")
            return
        if parsed.path in {
            "/api/automation-intelligence/daily-cycle/latest",
            "/api/automation-intelligence/daily-cycle/latest/",
        }:
            try:
                latest = read_latest_daily_cycle_status(self.server_root)
                self._send_json(latest, status=200 if latest.get("ok") else 404)
            except Exception as exc:
                self._send_safe_error(exc, context="daily-cycle-latest")
            return
        if parsed.path in {"/api/operational-snapshot", "/api/operational-snapshot/"}:
            try:
                refresh_lifecycle = WorkstationHandler.maybe_start_intraday_bootstrap(self.server_root)
                self.warm_operational_snapshot_cache(self.server_root, refresh_lifecycle=refresh_lifecycle)
                body = self.operational_snapshot_bytes
                self._send_precomputed_json(body or b"{}")
            except Exception as exc:
                self._send_safe_error(exc, context="operational-snapshot")
            return
        if parsed.path in {"/api/universe/summary", "/api/universe/summary/"}:
            try:
                self._send_json(universe_summary_payload(self.server_root))
            except Exception as exc:
                self._send_safe_error(exc, context="universe-summary")
            return
        if parsed.path in {"/api/universe/snapshot", "/api/universe/snapshot/"}:
            try:
                self._send_json(load_universe_snapshot(self.server_root))
            except Exception as exc:
                self._send_safe_error(exc, context="universe-snapshot")
            return
        if parsed.path in {"/api/universe/quality", "/api/universe/quality/"}:
            try:
                self._send_json(load_universe_quality(self.server_root))
            except Exception as exc:
                self._send_safe_error(exc, context="universe-quality")
            return
        if parsed.path in {"/api/universe/members", "/api/universe/members/"}:
            try:
                query = parse_qs(parsed.query or "")
                universe_name = (query.get("universe") or [""])[0].strip()
                if not universe_name:
                    self._send_json({"ok": False, "error": "universe query parameter required"}, status=400)
                    return
                as_of_date = (query.get("as_of_date") or [None])[0]
                self._send_json(
                    universe_members_payload(
                        self.server_root,
                        universe_name=universe_name,
                        as_of_date=as_of_date,
                    )
                )
            except Exception as exc:
                self._send_safe_error(exc, context="universe-members")
            return
        if parsed.path in {"/api/decisions", "/api/decisions/"}:
            try:
                self._send_json({"ok": True, "decisions": read_decisions(self.server_root)})
            except Exception as exc:
                self._send_safe_error(exc, context="decisions")
            return
        if parsed.path in {"/api/paper-rebalance", "/api/paper-rebalance/"}:
            try:
                self._send_json({"ok": True, "paper_rebalance": paper_rebalance_snapshot_payload(self.server_root)})
            except Exception as exc:
                self._send_safe_error(exc, context="paper-rebalance")
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
        if parsed.path in {
            "/api/automation-intelligence/daily-recommendations/generate",
            "/api/automation-intelligence/daily-recommendations/generate/",
        }:
            try:
                self._send_json(write_daily_recommendation_artifact(self.server_root), status=201)
            except Exception as exc:
                self._send_safe_error(exc, context="daily-recommendations-generate")
            return
        if parsed.path in {
            "/api/automation-intelligence/allocation-recommendations/generate",
            "/api/automation-intelligence/allocation-recommendations/generate/",
        }:
            try:
                self._send_json(write_allocation_recommendation_artifact(self.server_root), status=201)
            except Exception as exc:
                self._send_safe_error(exc, context="allocation-recommendations-generate")
            return
        if parsed.path in {
            "/api/automation-intelligence/review-draft/from-allocation-recommendation",
            "/api/automation-intelligence/review-draft/from-allocation-recommendation/",
        }:
            try:
                result = create_review_draft_from_allocation_recommendation(self.server_root)
                if result.get("review_draft_created"):
                    self.warm_operational_snapshot_cache(self.server_root)
                self._send_json(result, status=201 if result.get("review_draft_created") else 409)
            except Exception as exc:
                self._send_safe_error(exc, context="review-draft-from-allocation-recommendation")
            return
        if parsed.path in {
            "/api/automation-intelligence/daily-cycle/generate",
            "/api/automation-intelligence/daily-cycle/generate/",
        }:
            try:
                body = self._read_json_body()
                result = run_daily_automation_cycle(self.server_root, force=bool(body.get("force")))
                self._send_json(result, status=201 if result.get("ok") else 500)
            except Exception as exc:
                self._send_safe_error(exc, context="daily-cycle-generate")
            return
        if parsed.path in {
            "/api/automation-intelligence/strategy-factory-evidence/refresh",
            "/api/automation-intelligence/strategy-factory-evidence/refresh/",
        }:
            try:
                path = write_strategy_factory_evidence_manifest(self.server_root)
                payload = build_strategy_factory_evidence_manifest(self.server_root)
                self._send_json({**payload, "artifact_path": str(path.relative_to(self.server_root)).replace("\\", "/")}, status=201)
            except Exception as exc:
                self._send_safe_error(exc, context="strategy-factory-evidence-refresh")
            return
        if parsed.path in {
            "/api/automation-intelligence/ml-intelligence-patch/refresh",
            "/api/automation-intelligence/ml-intelligence-patch/refresh/",
        }:
            try:
                strategy_payload = build_strategy_intelligence_payload(self.server_root)
                path = write_ml_intelligence_patch_manifest(
                    self.server_root,
                    strategy_cards=strategy_payload.get("cards") or [],
                )
                payload = build_ml_intelligence_patch_manifest(
                    self.server_root,
                    strategy_cards=strategy_payload.get("cards") or [],
                )
                self._send_json({**payload, "artifact_path": str(path.relative_to(self.server_root)).replace("\\", "/")}, status=201)
            except Exception as exc:
                self._send_safe_error(exc, context="ml-intelligence-patch-refresh")
            return
        if parsed.path in {
            "/api/automation-intelligence/identity-bridge/refresh",
            "/api/automation-intelligence/identity-bridge/refresh/",
        }:
            try:
                strategy_payload = build_strategy_intelligence_payload(self.server_root)
                path = write_candidate_strategy_identity_bridge(
                    self.server_root,
                    strategy_cards=strategy_payload.get("cards") or [],
                )
                payload = build_candidate_strategy_identity_bridge(
                    self.server_root,
                    strategy_cards=strategy_payload.get("cards") or [],
                )
                self._send_json({**payload, "artifact_path": str(path.relative_to(self.server_root)).replace("\\", "/")}, status=201)
            except Exception as exc:
                self._send_safe_error(exc, context="identity-bridge-refresh")
            return
        if parsed.path in {"/api/strategy-factory/data/refresh-proxies", "/api/strategy-factory/data/refresh-proxies/"}:
            try:
                body = self._read_json_body()
                symbols = body.get("symbols") if isinstance(body, dict) else None
                result = PublicFallbackDataLoader().refresh_proxies(
                    symbols=list(symbols) if symbols else None,
                    start=str(body.get("start") or "2018-01-01"),
                    end=body.get("end"),
                )
                self._send_json(result, status=201 if result.get("ok") else 503)
            except (ValueError, json.JSONDecodeError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            except Exception as exc:
                self._send_safe_error(exc, context="strategy-factory-refresh-proxies")
            return
        if parsed.path in {"/api/strategy-factory/upload", "/api/strategy-factory/upload/"}:
            try:
                self._send_json(save_uploaded_materials(self.server_root, self._read_upload_materials()), status=201)
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            except Exception as exc:
                self._send_safe_error(exc, context="strategy-factory-upload")
            return
        if parsed.path in {"/api/strategy-factory/run", "/api/strategy-factory/run/"}:
            try:
                body = self._read_json_body()
                self._send_json(
                    run_strategy_factory(
                        self.server_root,
                        selected_material_ids=list(body.get("selected_material_ids") or []),
                        batch_id=body.get("batch_id"),
                    ),
                    status=201,
                )
            except (ValueError, json.JSONDecodeError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            except Exception as exc:
                self._send_safe_error(exc, context="strategy-factory-run")
            return
        if parsed.path in {
            "/api/strategy-factory/backtest-current-run",
            "/api/strategy-factory/backtest-current-run/",
        }:
            try:
                body = self._read_json_body()
                self._send_json(
                    run_current_run_backtest_ml(self.server_root, run_id=body.get("run_id")),
                    status=201,
                )
            except (ValueError, json.JSONDecodeError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            except Exception as exc:
                self._send_safe_error(exc, context="strategy-factory-backtest-current-run")
            return
        if parsed.path in {
            "/api/strategy-factory/portfolio-candidates/add",
            "/api/strategy-factory/portfolio-candidates/add/",
            "/api/strategy-factory/portfolio-candidates/activate",
            "/api/strategy-factory/portfolio-candidates/activate/",
        }:
            try:
                body = self._read_json_body()
                run_id = str(body.get("run_id") or "").strip()
                variant_id = str(body.get("variant_id") or "").strip()
                if not run_id or not variant_id:
                    self._send_json({"ok": False, "error": "run_id and variant_id required"}, status=400)
                    return
                endpoint = parsed.path.rstrip("/").split("/")[-1]
                if endpoint == "add":
                    result = add_variant_portfolio_candidate(
                        self.server_root,
                        run_id,
                        variant_id,
                        user_confirmation=body.get("user_confirmation") is True,
                        user_action_id=body.get("user_action_id"),
                    )
                    self._send_json(result, status=201 if result.get("ok") else 400)
                    return
                if endpoint == "activate":
                    result = activate_variant_portfolio_candidate(
                        self.server_root,
                        run_id,
                        variant_id,
                        user_confirmation=body.get("user_confirmation") is True,
                        user_action_id=body.get("user_action_id"),
                        activation_source=str(body.get("activation_source") or "USER_UI"),
                        smoke_only=body.get("smoke_only") is True,
                    )
                    self._send_json(result, status=201 if result.get("ok") else 400)
                    return
                self.send_error(404, "Not found")
            except (ValueError, json.JSONDecodeError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            except Exception as exc:
                self._send_safe_error(exc, context="strategy-factory-portfolio-candidates-action")
            return
        if parsed.path in {
            "/api/strategy-factory/jobs/run-full-current-run",
            "/api/strategy-factory/jobs/run-full-current-run/",
        }:
            try:
                body = self._read_json_body()
                self._send_json(
                    run_full_current_run(self.server_root, run_id=body.get("run_id")),
                    status=201,
                )
            except (ValueError, json.JSONDecodeError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            except Exception as exc:
                self._send_safe_error(exc, context="strategy-factory-full-current-run")
            return
        if parsed.path in {
            "/api/strategy-factory/admission/add-candidate",
            "/api/strategy-factory/admission/add-candidate/",
            "/api/strategy-factory/admission/run-risk-review",
            "/api/strategy-factory/admission/run-risk-review/",
            "/api/strategy-factory/admission/generate-allocation-draft",
            "/api/strategy-factory/admission/generate-allocation-draft/",
            "/api/strategy-factory/admission/apply-to-paper",
            "/api/strategy-factory/admission/apply-to-paper/",
        }:
            try:
                body = self._read_json_body()
                run_id = str(body.get("run_id") or "").strip()
                variant_id = str(body.get("variant_id") or "").strip()
                target_weight = body.get("target_weight")
                if not run_id or not variant_id:
                    self._send_json({"ok": False, "error": "run_id and variant_id required"}, status=400)
                    return
                if target_weight is not None:
                    target_weight = float(target_weight)
                endpoint = parsed.path.rstrip("/").split("/")[-1]
                if endpoint == "add-candidate":
                    result = add_variant_candidate(self.server_root, run_id, variant_id, target_weight=target_weight)
                    self._send_json(result, status=201 if result.get("ok") else 400)
                    return
                if endpoint == "run-risk-review":
                    result = run_variant_risk_review(self.server_root, run_id, variant_id)
                    self._send_json(result, status=201 if result.get("ok") else 400)
                    return
                if endpoint == "generate-allocation-draft":
                    result = generate_variant_allocation_draft(
                        self.server_root,
                        run_id,
                        variant_id,
                        target_weight=target_weight,
                    )
                    self._send_json(result, status=201)
                    return
                if endpoint == "apply-to-paper":
                    result = apply_variant_to_paper(
                        self.server_root,
                        run_id,
                        variant_id,
                        user_confirmation=body.get("user_confirmation") is True,
                    )
                    self._send_json(result, status=201)
                    return
                self.send_error(404, "Not found")
            except (ValueError, json.JSONDecodeError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            except Exception as exc:
                self._send_safe_error(exc, context="strategy-factory-admission-action")
            return
        if parsed.path in {
            "/api/strategy-factory/sandbox/add",
            "/api/strategy-factory/sandbox/add/",
            "/api/strategy-factory/sandbox/add-to-paper-sandbox",
            "/api/strategy-factory/sandbox/add-to-paper-sandbox/",
        }:
            try:
                body = self._read_json_body()
                run_id = str(body.get("run_id") or "").strip()
                variant_id = str(body.get("variant_id") or "").strip()
                if not run_id or not variant_id:
                    self._send_json({"ok": False, "error": "run_id and variant_id required"}, status=400)
                    return
                target_weight = body.get("target_weight")
                result = add_variant_to_paper_sandbox(
                    self.server_root,
                    run_id,
                    variant_id,
                    user_confirmation=body.get("user_confirmation") is True,
                    override_reason=body.get("override_reason"),
                    target_weight=float(target_weight) if target_weight is not None else None,
                )
                self._send_json(result, status=201 if result.get("ok") else 400)
            except (ValueError, json.JSONDecodeError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            except Exception as exc:
                self._send_safe_error(exc, context="strategy-factory-sandbox-action")
            return
        if parsed.path.startswith("/api/strategy-factory/candidates/"):
            parts = [unquote(part) for part in parsed.path.strip("/").split("/")]
            if len(parts) != 5:
                self.send_error(404, "Not found")
                return
            strategy_id, action = parts[3], parts[4]
            try:
                body = self._read_json_body()
                if action == "add-to-candidate-portfolio":
                    self._send_json(add_to_candidate_portfolio(self.server_root, strategy_id), status=201)
                    return
                if action == "generate-allocation-draft":
                    self._send_json(generate_allocation_draft(self.server_root, strategy_id), status=201)
                    return
                if action == "remove-from-candidate-portfolio":
                    self._send_json(remove_from_candidate_portfolio(self.server_root, strategy_id))
                    return
                if action == "apply-to-paper-portfolio":
                    self._send_json(
                        apply_to_paper_portfolio(self.server_root, strategy_id, bool(body.get("confirmed"))),
                        status=201,
                    )
                    return
                self.send_error(404, "Not found")
            except (ValueError, json.JSONDecodeError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            except Exception as exc:
                self._send_safe_error(exc, context="strategy-factory-action")
            return
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
                body = self._read_json_body()
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
        if parsed.path in {
            "/api/paper-rebalance/plan",
            "/api/paper-rebalance/plan/",
            "/api/paper-rebalance/recommendation-review-draft",
            "/api/paper-rebalance/recommendation-review-draft/",
            "/api/paper-rebalance/monthly-proposal",
            "/api/paper-rebalance/monthly-proposal/",
            "/api/paper-rebalance/monthly-proposal/review-draft",
            "/api/paper-rebalance/monthly-proposal/review-draft/",
            "/api/paper-rebalance/approve-recommendation-draft",
            "/api/paper-rebalance/approve-recommendation-draft/",
            "/api/paper-rebalance/apply-due",
            "/api/paper-rebalance/apply-due/",
            "/api/paper-rebalance/apply-approved",
            "/api/paper-rebalance/apply-approved/",
            "/api/paper-rebalance/accept",
            "/api/paper-rebalance/accept/",
            "/api/paper-rebalance/apply",
            "/api/paper-rebalance/apply/",
            "/api/paper-rebalance/reject",
            "/api/paper-rebalance/reject/",
        }:
            try:
                body = self._read_json_body()
                if parsed.path.rstrip("/").endswith("/recommendation-review-draft"):
                    snapshot = load_operational_snapshot_for_response(
                        self.server_root,
                        scheduler_enabled=bool(getattr(WorkstationHandler, "intraday_scheduler_enabled", False)),
                    )
                    nav = body.get("portfolio_nav") or (snapshot.get("portfolio_summary") or {}).get("nav")
                    draft = create_recommendation_review_draft(
                        self.server_root,
                        body.get("recommendation_rows") or [],
                        portfolio_nav=nav,
                        source_recommendation_artifact=body.get("source_recommendation_artifact"),
                    )
                    self.warm_operational_snapshot_cache(self.server_root)
                    self._send_json(self._paper_rebalance_response({"recommendation_review_draft": draft}), status=201)
                    return
                if parsed.path.rstrip("/").endswith("/monthly-proposal"):
                    snapshot = load_operational_snapshot_for_response(
                        self.server_root,
                        scheduler_enabled=bool(getattr(WorkstationHandler, "intraday_scheduler_enabled", False)),
                    )
                    nav = body.get("portfolio_nav") or (snapshot.get("portfolio_summary") or {}).get("nav")
                    proposal = create_monthly_rebalance_proposal(
                        self.server_root,
                        body.get("recommendation_rows") or [],
                        portfolio_nav=nav,
                        session_state=snapshot.get("session_state") or body.get("session_state"),
                        source_recommendation_artifact=body.get("source_recommendation_artifact"),
                        source_strategy_universe_snapshot=body.get("source_strategy_universe_snapshot")
                        or snapshot.get("snapshot_id"),
                        force=bool(body.get("force")),
                    )
                    self.warm_operational_snapshot_cache(self.server_root)
                    self._send_json(self._paper_rebalance_response({"monthly_rebalance_proposal": proposal}), status=201)
                    return
                if parsed.path.rstrip("/").endswith("/monthly-proposal/review-draft"):
                    draft = create_review_draft_from_monthly_proposal(
                        self.server_root,
                        proposal_id=body.get("proposal_id"),
                    )
                    self.warm_operational_snapshot_cache(self.server_root)
                    self._send_json(self._paper_rebalance_response({"recommendation_review_draft": draft}), status=201)
                    return
                if parsed.path.rstrip("/").endswith("/approve-recommendation-draft"):
                    snapshot = load_operational_snapshot_for_response(
                        self.server_root,
                        scheduler_enabled=bool(getattr(WorkstationHandler, "intraday_scheduler_enabled", False)),
                    )
                    plan = create_approved_rebalance_plan(
                        self.server_root,
                        snapshot=snapshot,
                        draft_id=body.get("draft_id") or body.get("proposal_id"),
                    )
                    self.warm_operational_snapshot_cache(self.server_root)
                    self._send_json(self._paper_rebalance_response({"approved_rebalance_plan": plan}), status=201)
                    return
                if parsed.path.rstrip("/").endswith("/apply-due"):
                    snapshot = load_operational_snapshot_for_response(
                        self.server_root,
                        scheduler_enabled=bool(getattr(WorkstationHandler, "intraday_scheduler_enabled", False)),
                    )
                    result = apply_due_approved_rebalance_plan(
                        self.server_root,
                        snapshot=snapshot,
                    )
                    self.warm_operational_snapshot_cache(self.server_root)
                    self._send_json(self._paper_rebalance_response({"paper_apply_result": result}))
                    return
                if parsed.path.rstrip("/").endswith("/apply-approved"):
                    snapshot = load_operational_snapshot_for_response(
                        self.server_root,
                        scheduler_enabled=bool(getattr(WorkstationHandler, "intraday_scheduler_enabled", False)),
                    )
                    result = apply_approved_rebalance_plan(
                        self.server_root,
                        snapshot=snapshot,
                        plan_id=body.get("plan_id"),
                    )
                    self.warm_operational_snapshot_cache(self.server_root)
                    self._send_json(self._paper_rebalance_response({"paper_apply_result": result}))
                    return
                if parsed.path.rstrip("/").endswith("/plan"):
                    snapshot = load_operational_snapshot_for_response(
                        self.server_root,
                        scheduler_enabled=bool(getattr(WorkstationHandler, "intraday_scheduler_enabled", False)),
                    )
                    plan = generate_paper_rebalance_plan(
                        self.server_root,
                        snapshot,
                        body.get("target_weights") or {},
                        intended_effective_date=body.get("intended_effective_date"),
                    )
                    self.warm_operational_snapshot_cache(self.server_root)
                    self._send_json(self._paper_rebalance_response({"plan": plan}), status=201)
                    return
                plan_id = str(body.get("plan_id") or "").strip()
                if not plan_id:
                    self._send_json({"ok": False, "error": "plan_id required"}, status=400)
                    return
                if parsed.path.rstrip("/").endswith("/accept"):
                    plan = accept_paper_rebalance_plan(self.server_root, plan_id)
                    self.warm_operational_snapshot_cache(self.server_root)
                    self._send_json(self._paper_rebalance_response({"plan": plan}))
                    return
                if parsed.path.rstrip("/").endswith("/apply"):
                    result = apply_paper_rebalance_plan(self.server_root, plan_id)
                    self.warm_operational_snapshot_cache(self.server_root)
                    self._send_json(self._paper_rebalance_response(result))
                    return
                if parsed.path.rstrip("/").endswith("/reject"):
                    plan = reject_paper_rebalance_plan(self.server_root, plan_id)
                    self.warm_operational_snapshot_cache(self.server_root)
                    self._send_json(self._paper_rebalance_response({"plan": plan}))
                    return
            except (ValueError, json.JSONDecodeError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            except Exception as exc:
                self._send_safe_error(exc, context="paper-rebalance")
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
                artifact_state = refresh_scheme_b_artifact_state(self.server_root)
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
                if (
                    result.get("ok")
                    and result.get("snapshot_id")
                    and (self.server_root / "output" / "dashboard_artifact.json").exists()
                ):
                    artifact = self._load_artifact()
                    snapshot = read_latest_snapshot_payload(self._intraday_config())
                    overlay = self._overlay_from_intraday_snapshot(snapshot, artifact)
                    result = {**result, **overlay, "ok": True}
                result = {**result, "refresh_artifact": artifact_state}
                if result.get("ok"):
                    try:
                        self.warm_operational_snapshot_cache(self.server_root)
                    except Exception as cache_exc:
                        logger.warning("refresh-data succeeded but snapshot cache warm failed: %s", cache_exc)
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
        interval = 30
        try:
            cfg = load_intraday_config(root / "data/config/intraday_refresh.yaml")
            status = read_refresh_status(cfg)
            interval = resolve_refresh_interval_minutes(
                cfg,
                selected_interval_minutes=status.get("selected_interval_minutes"),
            )
            interval = max(interval, 30)
            if cfg.get("enabled", True):
                result = run_intraday_refresh(
                    force=False,
                    interval_minutes=interval,
                    artifact_path=root / "output" / "dashboard_artifact.json",
                    config=cfg,
                )
                automation_result = None
                try:
                    automation_snapshot = load_operational_snapshot_for_response(
                        root,
                        scheduler_enabled=bool(getattr(WorkstationHandler, "intraday_scheduler_enabled", False)),
                    )
                    automation_result = apply_due_approved_rebalance_plan(root, snapshot=automation_snapshot)
                    if automation_result.get("applied"):
                        logger.info("Due paper rebalance automation applied: %s", automation_result.get("plan_id"))
                    elif automation_result.get("already_applied"):
                        logger.info("Due paper rebalance automation already applied: %s", automation_result.get("plan_id"))
                except Exception as automation_exc:
                    logger.warning("Due paper rebalance automation check failed: %s", automation_exc)
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
    cfg = load_intraday_config(PROJECT_ROOT / "data/config/intraday_refresh.yaml")
    scheduler_enabled = intraday_scheduler_enabled(
        config_enabled=bool(cfg.get("enabled", True)),
        force_start=True if (intraday_scheduler is True or env_scheduler or bool(cfg.get("enabled", True))) else None,
        force_disable=no_intraday_scheduler,
    )
    set_background_scheduler_enabled(scheduler_enabled)
    WorkstationHandler.intraday_scheduler_enabled = scheduler_enabled
    WorkstationHandler.request_bootstrap_enabled = True
    if refresh_on_start:
        print("Startup official/live refresh is disabled for the Foundation dashboard.")
    WorkstationHandler.warm_operational_snapshot_cache(PROJECT_ROOT)
    daily_cycle_start = WorkstationHandler.maybe_start_daily_cycle(PROJECT_ROOT)
    server = ThreadingHTTPServer((bind_host, bind_port), WorkstationHandler)
    print(f"Risk Manager workstation server running at http://{bind_host}:{bind_port}/dashboard/index.html")
    print("Default page load: /api/operational-snapshot (official ledger plus separate intraday estimate)")
    print(f"Daily automation cycle: {daily_cycle_start.get('reason')}")
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
