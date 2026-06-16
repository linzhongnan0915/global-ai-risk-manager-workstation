"""Tests for external refresh API bearer-token auth."""

from __future__ import annotations

import json
import socket
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_workstation_server import WorkstationHandler, resolve_server_bind
from src.market.refresh_auth import classify_refresh_request, parse_bearer_token
from src.market.intraday_refresh_service import run_intraday_refresh
from src.market.snapshot_store import read_latest_pointer, read_latest_snapshot


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _prepare_refresh_root(root: Path) -> None:
    canonical_dir = root / "dashboard" / "data"
    canonical_dir.mkdir(parents=True)
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
            }
        ),
        encoding="utf-8",
    )
    config_dir = root / "data" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "intraday_refresh.yaml").write_text(
        (PROJECT_ROOT / "data" / "config" / "intraday_refresh.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )


def _start_server(port: int, root: Path) -> ThreadingHTTPServer:
    _prepare_refresh_root(root)
    WorkstationHandler.server_root = root
    WorkstationHandler.deployment_artifact = None
    host, _ = resolve_server_bind("127.0.0.1", port)
    server = ThreadingHTTPServer((host, port), WorkstationHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _fetch(url: str, *, method: str = "GET", data: bytes = b"", headers: dict | None = None):
    import urllib.error
    import urllib.request

    request = urllib.request.Request(url, data=data if method != "GET" else None, method=method)
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def test_parse_bearer_token():
    assert parse_bearer_token("Bearer secret-token") == "secret-token"
    assert parse_bearer_token("Basic abc") is None
    assert parse_bearer_token(None) is None


def test_classify_refresh_request_modes(monkeypatch):
    monkeypatch.setenv("REFRESH_API_TOKEN", "expected-token")
    assert classify_refresh_request("Bearer expected-token") == ("external", True)
    assert classify_refresh_request("Bearer wrong") == ("rejected", False)
    assert classify_refresh_request("Bearer ") == ("rejected", False)
    assert classify_refresh_request(None) == ("manual", True)


def test_external_refresh_valid_token_allowed(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("REFRESH_API_TOKEN", "test-token")
    monkeypatch.setattr(
        "scripts.run_workstation_server.run_intraday_refresh",
        lambda **kwargs: {"ok": True, "skipped": True, "message": "Scheduled intraday refresh skipped outside regular session."},
    )
    port = _free_port()
    server = _start_server(port, tmp_path)
    WorkstationHandler.last_manual_refresh_at = 0.0
    try:
        status, body = _fetch(
            f"http://127.0.0.1:{port}/api/refresh-data",
            method="POST",
            data=b'{"interval_minutes":10}',
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer test-token",
            },
        )
        payload = json.loads(body.decode("utf-8"))
        assert status == 200
        assert payload.get("ok") is True
    finally:
        server.shutdown()
        server.server_close()
        WorkstationHandler.server_root = PROJECT_ROOT


def test_external_refresh_invalid_token_returns_401(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("REFRESH_API_TOKEN", "test-token")
    port = _free_port()
    server = _start_server(port, tmp_path)
    try:
        status, body = _fetch(
            f"http://127.0.0.1:{port}/api/refresh-data",
            method="POST",
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer wrong-token",
            },
        )
        payload = json.loads(body.decode("utf-8"))
        assert status == 401
        assert payload.get("ok") is False
    finally:
        server.shutdown()
        server.server_close()
        WorkstationHandler.server_root = PROJECT_ROOT


def test_external_refresh_missing_token_on_bearer_returns_401(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("REFRESH_API_TOKEN", "test-token")
    port = _free_port()
    server = _start_server(port, tmp_path)
    try:
        status, _ = _fetch(
            f"http://127.0.0.1:{port}/api/refresh-data",
            method="POST",
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer ",
            },
        )
        assert status == 401
    finally:
        server.shutdown()
        server.server_close()
        WorkstationHandler.server_root = PROJECT_ROOT


def test_manual_refresh_without_token_still_allowed(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("REFRESH_API_TOKEN", "test-token")
    port = _free_port()
    server = _start_server(port, tmp_path)
    WorkstationHandler.last_manual_refresh_at = 0.0
    try:
        status, body = _fetch(
            f"http://127.0.0.1:{port}/api/refresh-data",
            method="POST",
            data=b"{}",
            headers={"Content-Type": "application/json"},
        )
        payload = json.loads(body.decode("utf-8"))
        assert status in {200, 409, 503}
        assert "Unauthorized" not in payload.get("error", "")
    finally:
        WorkstationHandler.last_manual_refresh_at = 0.0
        server.shutdown()
        server.server_close()
        WorkstationHandler.server_root = PROJECT_ROOT


def test_external_scheduler_status_payload(monkeypatch):
    monkeypatch.setenv("REFRESH_API_TOKEN", "configured")
    from src.market.intraday_refresh_service import build_refresh_status_payload

    payload = build_refresh_status_payload()
    assert payload["external_scheduler_active"] is True
    assert payload["scheduler_display"] == "External active"
    assert payload["refresh_cadence_minutes"] == 5


def test_external_refresh_market_closed_returns_skipped(monkeypatch, intraday_cfg, minimal_artifact, tmp_path: Path):
    monkeypatch.setattr(
        "src.market.intraday_refresh_service.should_run_scheduled_refresh",
        lambda *args, **kwargs: False,
    )
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(json.dumps(minimal_artifact), encoding="utf-8")
    result = run_intraday_refresh(force=False, artifact_path=artifact_path, config=intraday_cfg)
    assert result.get("ok") is True
    assert result.get("skipped") is True


def test_refresh_failure_preserves_last_valid_snapshot(intraday_cfg, minimal_artifact, tmp_path: Path):
    intraday_cfg["allow_artifact_position_fallback"] = True
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(json.dumps(minimal_artifact), encoding="utf-8")

    def _mock_fetch_success(tickers, **kwargs):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        now_et = datetime.now(tz=ZoneInfo("America/New_York")).isoformat()
        return {
            "provider": "yfinance",
            "bar_interval": "5m",
            "requested_tickers": tickers,
            "rows": [
                {
                    "source_ticker": tickers[0],
                    "observation_ts_et": now_et,
                    "session_date": now_et[:10],
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 101.0,
                    "volume": 1000.0,
                    "bar_interval": "5m",
                    "intraday_return_from_open": 0.01,
                    "timezone": "America/New_York",
                }
            ],
            "missing_tickers": [],
            "stale_tickers": [],
            "ticker_count_requested": len(tickers),
            "ticker_count_successful": len(tickers),
            "latest_observation_ts_et": now_et,
        }

    def _mock_fetch_fail(tickers, **kwargs):
        raise RuntimeError("provider unavailable")

    ok = run_intraday_refresh(force=True, artifact_path=artifact_path, config=intraday_cfg, fetch_fn=_mock_fetch_success)
    assert ok.get("ok") is True
    first_id = read_latest_pointer(intraday_cfg)["snapshot_id"]

    fail = run_intraday_refresh(force=True, artifact_path=artifact_path, config=intraday_cfg, fetch_fn=_mock_fetch_fail)
    assert fail.get("ok") is False
    assert read_latest_pointer(intraday_cfg)["snapshot_id"] == first_id
    assert read_latest_snapshot(intraday_cfg)["snapshot_id"] == first_id


@pytest.fixture
def intraday_cfg(tmp_path: Path) -> dict:
    from src.market.intraday_config import load_intraday_config

    cfg = load_intraday_config()
    cfg = dict(cfg)
    cfg["snapshot_dir"] = str(tmp_path / "snapshots")
    cfg["latest_pointer_path"] = str(tmp_path / "latest.json")
    cfg["status_path"] = str(tmp_path / "status.json")
    cfg["lock_path"] = str(tmp_path / "refresh.lock")
    return cfg


@pytest.fixture
def minimal_artifact() -> dict:
    return {
        "as_of_date": "2026-06-04",
        "initial_capital": 1_000_000,
        "allocation": {"current_weights": {"S1": 0.5, "S2": 0.5}},
        "strategies": [
            {
                "strategy_id": "S1",
                "name": "Alpha",
                "current_weight": 0.5,
                "daily_pnl": 1000.0,
                "position_packet": {"latest_positions": [{"source_ticker": "SPY", "weight": 1.0}]},
            },
            {
                "strategy_id": "S2",
                "name": "Macro",
                "current_weight": 0.5,
                "daily_pnl": -500.0,
                "position_packet": {"latest_positions": [{"source_ticker": "TLT", "weight": 1.0}]},
            },
        ],
        "factors": {"portfolio_factor_exposure_current": {"equity_beta": 0.3}},
        "risk_limits": {"checks": [], "factors": {"checks": []}},
        "operating_period_risk": {"pnl": {"cumulative_return": {"available": True, "value": 0.01}}},
        "build_metadata": {"artifact_generated_at": "2026-06-04T20:00:00Z"},
    }
