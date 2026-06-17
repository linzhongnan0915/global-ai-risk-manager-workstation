"""HTTP contract tests for the workstation server."""

from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from scripts.run_workstation_server import WorkstationHandler
from src.market.artifact_contract import artifact_contract, ensure_dashboard_artifact, validate_runtime_bootstrap_artifact


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_server(port: int) -> ThreadingHTTPServer:
    WorkstationHandler.warm_operational_snapshot_cache(Path(__file__).resolve().parents[1])
    server = ThreadingHTTPServer(("127.0.0.1", port), WorkstationHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _fetch(url: str) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            headers = {key.lower(): value for key, value in response.headers.items()}
            body = response.read()
            return response.status, headers, body
    except urllib.error.HTTPError as exc:
        headers = {key.lower(): value for key, value in exc.headers.items()}
        body = exc.read()
        return exc.code, headers, body


def _post_json(url: str, payload: bytes = b"{}") -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "Accept-Encoding": "identity"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            headers = {key.lower(): value for key, value in response.headers.items()}
            body = response.read()
            return response.status, headers, body
    except urllib.error.HTTPError as exc:
        headers = {key.lower(): value for key, value in exc.headers.items()}
        body = exc.read()
        return exc.code, headers, body


def _fetch_no_redirect(url: str) -> tuple[int, dict[str, str], bytes]:
    class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(NoRedirectHandler)
    request = urllib.request.Request(url)
    try:
        with opener.open(request, timeout=10) as response:
            headers = {key.lower(): value for key, value in response.headers.items()}
            body = response.read()
            return response.status, headers, body
    except urllib.error.HTTPError as exc:
        headers = {key.lower(): value for key, value in exc.headers.items()}
        body = exc.read()
        return exc.code, headers, body


def test_resolve_static_path_blocks_traversal():
    handler = WorkstationHandler.__new__(WorkstationHandler)
    handler.server_root = Path(__file__).resolve().parents[1]

    blocked = handler._resolve_static_path("/../output/dashboard_artifact.json")
    assert blocked is None

    allowed = handler._resolve_static_path("/dashboard/index.html")
    assert allowed is not None
    assert allowed.name == "index.html"

    root = handler._resolve_static_path("/")
    assert root is None


def test_root_redirect_and_dashboard_assets():
    port = _free_port()
    server = _start_server(port)
    base = f"http://127.0.0.1:{port}"
    try:
        status, headers, body = _fetch_no_redirect(f"{base}/")
        assert status == 302
        assert headers.get("location") == "/dashboard/index.html"
        assert headers.get("content-length") == "0"
        assert body == b""

        status, headers, body = _fetch(f"{base}/dashboard/index.html")
        assert status == 200
        assert int(headers["content-length"]) == len(body)
        assert b"<!doctype html" in body.lower()

        for asset in (
            "/dashboard/foundation.css",
            "/dashboard/foundation-components.js",
            "/dashboard/foundation-app.js",
            "/dashboard/data/canonical_operational.json",
        ):
            asset_status, asset_headers, asset_body = _fetch(f"{base}{asset}")
            assert asset_status == 200
            assert int(asset_headers["content-length"]) == len(asset_body)
            assert len(asset_body) > 0
    finally:
        server.shutdown()
        server.server_close()


def test_health_and_refresh_status_content_length():
    port = _free_port()
    server = _start_server(port)
    try:
        for path in ("/api/health", "/api/refresh/status"):
            status, headers, body = _fetch(f"http://127.0.0.1:{port}{path}")
            assert status == 200
            assert int(headers["content-length"]) == len(body)
            payload = json.loads(body.decode("utf-8"))
            if path.endswith("/health"):
                assert payload["status"] == "ok"
            else:
                assert "market_status" in payload or "canonical_data_state" in payload
    finally:
        server.shutdown()
        server.server_close()


def test_operational_snapshot_endpoint_includes_intraday_runtime_fields():
    port = _free_port()
    server = _start_server(port)
    try:
        status, headers, body = _fetch(f"http://127.0.0.1:{port}/api/operational-snapshot")
        assert status == 200
        assert int(headers["content-length"]) == len(body)
        payload = json.loads(body.decode("utf-8"))
        assert payload["intraday_runtime_status"] in {"NOT_LOADED", "LOADED", "STALE", "ERROR"}
        assert "intraday_overlay_available" in payload
        assert "intraday_scheduler_enabled" in payload
        assert "intraday_refresh_message" in payload
        assert "official_promotion_readiness" in payload
        assert payload["official_promotion_readiness"]["execute_enabled"] is False
        assert payload["portfolio_daily"][-1]["date"] == "2026-06-11"
        assert not any(row["date"] == "2026-06-15" for row in payload["portfolio_daily"])
    finally:
        server.shutdown()
        server.server_close()


def test_generated_artifact_contract_documents_runtime_and_research_layers():
    contract = artifact_contract()
    runtime_names = {row["name"] for row in contract["runtime_artifacts"]}
    research_names = {row["name"] for row in contract["generated_research_artifacts"]}
    assert "dashboard_artifact" in runtime_names
    assert "strategy_factory_research" in research_names
    assert contract["rules"]["market_data"] == "Do not fabricate market, performance, brokerage, or live fill data."


def test_contract_bootstrap_artifact_is_safe_non_live(tmp_path):
    root = tmp_path
    canonical_dir = root / "dashboard" / "data"
    canonical_dir.mkdir(parents=True)
    (canonical_dir / "canonical_operational.json").write_text(
        json.dumps(
            {
                "portfolio_summary": {"as_of_date": "2026-06-12", "nav": 1_000_000},
                "strategies": [{"internal_id": "S1", "display_name": "Paper Sleeve 1", "current_weight": 1.0}],
            }
        ),
        encoding="utf-8",
    )
    artifact, state = ensure_dashboard_artifact(root)
    assert state["state"] == "initialized"
    assert validate_runtime_bootstrap_artifact(artifact) == []
    assert artifact["data_classification"]["is_live_portfolio_data"] is False
    assert artifact["data_classification"]["live_brokerage_fills_represented"] is False


def test_refresh_data_does_not_require_missing_dashboard_artifact(tmp_path, monkeypatch):
    root = tmp_path
    canonical_dir = root / "dashboard" / "data"
    canonical_dir.mkdir(parents=True)
    config_dir = root / "data" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "intraday_refresh.yaml").write_text(
        """
intraday_refresh:
  enabled: true
  default_interval_minutes: 5
  allowed_intervals_minutes: [5, 10, 30]
  provider: yfinance
  bar_interval_by_refresh:
    5: 5m
    10: 5m
    30: 15m
  timezone: America/New_York
  regular_session_only: true
  stale_after_minutes:
    5: 10
    10: 20
    30: 45
  request_timeout_seconds: 20
  retry_attempts: 1
  backoff_seconds: [1]
  min_success_ticker_ratio: 0.6
  incomplete_bar_label: incomplete_current_bar
  snapshot_dir: output/intraday_snapshots
  latest_pointer_path: output/intraday_latest.json
  status_path: output/intraday_refresh_status.json
  lock_path: output/intraday_refresh.lock
  shadow_database_path: output/shadow/strategy_shadow.db
  market_holidays: []
""".lstrip(),
        encoding="utf-8",
    )
    (canonical_dir / "canonical_operational.json").write_text(
        json.dumps(
            {
                "portfolio_summary": {"as_of_date": "2026-06-12", "nav": 1_000_000},
                "strategies": [
                    {
                        "internal_id": "S1",
                        "display_name": "Paper Sleeve 1",
                        "membership_state": "executed",
                        "current_weight": 1.0,
                    }
                ],
                "holdings": [
                    {"date": "2026-06-12", "strategy_id": "S1", "ticker": "SPY", "target_weight": 1.0}
                ],
            }
        ),
        encoding="utf-8",
    )
    calls = {}

    def _refresh_stub(**kwargs):
        artifact_path = Path(kwargs["artifact_path"])
        calls["artifact_exists"] = artifact_path.exists()
        return {
            "ok": True,
            "refresh_status": "success",
            "position_source": "committed_shadow_holdings",
            "legacy_artifact_position_estimate_authoritative": False,
        }

    monkeypatch.setattr("scripts.run_workstation_server.run_intraday_refresh", _refresh_stub)
    original_root = WorkstationHandler.server_root
    original_artifact = WorkstationHandler.deployment_artifact
    WorkstationHandler.server_root = root
    WorkstationHandler.deployment_artifact = None
    port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), WorkstationHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _, body = _post_json(f"http://127.0.0.1:{port}/api/refresh-data")
        payload = json.loads(body.decode("utf-8"))
        artifact_path = root / "output" / "dashboard_artifact.json"
        assert status == 200
        assert calls["artifact_exists"] is False
        assert artifact_path.exists() is False
        assert payload["ok"] is True
        assert payload["refresh_status"] == "success"
        assert payload["refresh_artifact"]["state"] == "not_required"
        assert payload["refresh_artifact"]["reason"] == "refresh_scheme_b_committed_shadow_holdings"
        assert payload["refresh_artifact"]["legacy_artifact_position_estimate_authoritative"] is False
    finally:
        server.shutdown()
        server.server_close()
        WorkstationHandler.server_root = original_root
        WorkstationHandler.deployment_artifact = original_artifact


def test_static_dashboard_written_once():
    port = _free_port()
    server = _start_server(port)
    try:
        status, headers, body = _fetch(f"http://127.0.0.1:{port}/dashboard/index.html")
        assert status == 200
        assert int(headers["content-length"]) == len(body)
        assert b"<!doctype html" in body.lower()
        assert body.count(b"<!doctype html") == 1
    finally:
        server.shutdown()
        server.server_close()
