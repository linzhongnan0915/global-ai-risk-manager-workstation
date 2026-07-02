"""Tests for external refresh API bearer-token auth."""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_workstation_server import WorkstationHandler, resolve_server_bind
from src.market.refresh_auth import classify_refresh_request, parse_bearer_token
from src.market.intraday_config import load_intraday_config
from src.market.intraday_refresh_service import build_refresh_status_payload, refresh_lifecycle_status, run_intraday_refresh
from src.market.market_hours import MarketSessionInfo
from src.market.paper_portfolio_ledger import paper_portfolio_daily_path, paper_strategy_daily_path
from src.market.snapshot_store import read_latest_pointer, read_latest_snapshot


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _prepare_refresh_root(root: Path) -> None:
    _write_canonical_holdings(root, ["SPY"])
    config_dir = root / "data" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "intraday_refresh.yaml").write_text(
        (PROJECT_ROOT / "data" / "config" / "intraday_refresh.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )


def _write_canonical_holdings(root: Path, tickers: list[str] | None = None) -> None:
    canonical_dir = root / "dashboard" / "data"
    canonical_dir.mkdir(parents=True, exist_ok=True)
    tickers = tickers or ["SPY", "TLT"]
    canonical_dir.joinpath("canonical_operational.json").write_text(
        json.dumps(
            {
                "portfolio_summary": {"as_of_date": "2026-06-12", "nav": 1_000_000},
                "strategies": [
                    {
                        "internal_id": f"S{index + 1}",
                        "display_name": f"Paper Sleeve {index + 1}",
                        "membership_state": "executed",
                        "current_weight": 1 / len(tickers),
                    }
                    for index, _ in enumerate(tickers)
                ],
                "holdings": [
                    {
                        "date": "2026-06-12",
                        "strategy_id": f"S{index + 1}",
                        "ticker": ticker,
                        "target_weight": 1.0,
                    }
                    for index, ticker in enumerate(tickers)
                ],
            }
        ),
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


def test_intraday_refresh_status_defaults_to_controlled_30_minute_cadence(tmp_path: Path):
    cfg = dict(load_intraday_config())
    cfg["latest_pointer_path"] = str(tmp_path / "latest.json")
    cfg["status_path"] = str(tmp_path / "status.json")
    cfg["lock_path"] = str(tmp_path / "refresh.lock")
    payload = build_refresh_status_payload(cfg)

    assert payload["refresh_cadence_minutes"] == 30
    assert payload["selected_cadence_minutes"] == 30
    assert payload["refresh_lifecycle"]["refresh_interval_minutes"] == 30
    assert payload["scheduler_deployment_note"].startswith("In-process scheduler runs")


def test_market_open_missing_intraday_snapshot_exposes_refresh_needed(intraday_cfg):
    now = datetime(2026, 6, 22, 10, 0, tzinfo=ZoneInfo("America/New_York"))

    lifecycle = refresh_lifecycle_status(intraday_cfg, now=now)

    assert lifecycle["market_status"] == "Open"
    assert lifecycle["market_session_date"] == "2026-06-22"
    assert lifecycle["state"] == "refresh_needed"
    assert lifecycle["reason"] == "missing_current_day_intraday_snapshot"
    assert lifecycle["latest_snapshot_id"] is None


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
    assert payload["refresh_cadence_minutes"] == 30


def test_external_refresh_market_closed_returns_skipped(monkeypatch, intraday_cfg, minimal_artifact, tmp_path: Path):
    monkeypatch.setattr(
        "src.market.intraday_refresh_service.should_run_scheduled_refresh",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        "src.market.intraday_refresh_service.daily_shadow_return_exists",
        lambda *args, **kwargs: True,
    )
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(json.dumps(minimal_artifact), encoding="utf-8")
    result = run_intraday_refresh(force=False, artifact_path=artifact_path, config=intraday_cfg)
    assert result.get("ok") is True
    assert result.get("skipped") is True


def test_market_closed_refresh_fills_paper_daily_from_valid_daily_close_history(
    monkeypatch,
    intraday_cfg,
    minimal_artifact,
    tmp_path: Path,
):
    _write_canonical_holdings(tmp_path, ["SPY", "TLT"])
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(json.dumps(minimal_artifact), encoding="utf-8")

    def _mock_fetch_open(tickers, **kwargs):
        return {
            "provider": "yfinance",
            "bar_interval": "5m",
            "requested_tickers": tickers,
            "rows": [
                {
                    "source_ticker": ticker,
                    "observation_ts_et": "2026-06-17T15:55:00-04:00",
                    "session_date": "2026-06-17",
                    "open": 100.0,
                    "high": 102.0,
                    "low": 99.0,
                    "close": 101.0,
                    "volume": 1000.0,
                    "bar_interval": "5m",
                    "bar_completeness": "completed",
                    "intraday_return_from_open": 0.01,
                    "timezone": "America/New_York",
                }
                for ticker in tickers
            ],
            "missing_tickers": [],
            "stale_tickers": [],
            "ticker_count_requested": len(tickers),
            "ticker_count_successful": len(tickers),
            "latest_observation_ts_et": "2026-06-17T15:55:00-04:00",
            "latest_completed_bar_ts_et": "2026-06-17T15:55:00-04:00",
        }

    monkeypatch.setattr(
        "src.market.intraday_refresh_service.market_session_status",
        lambda *args, **kwargs: MarketSessionInfo("Open", "America/New_York", "2026-06-17", True, None),
    )
    first = run_intraday_refresh(force=True, artifact_path=artifact_path, config=intraday_cfg, fetch_fn=_mock_fetch_open)
    previous_pointer = read_latest_pointer(intraday_cfg)
    assert first["snapshot_id"] == previous_pointer["snapshot_id"]

    monkeypatch.setattr(
        "src.market.intraday_refresh_service.market_session_status",
        lambda *args, **kwargs: MarketSessionInfo("Closed", "America/New_York", "2026-06-18", True, None),
    )
    monkeypatch.setattr(
        "src.market.intraday_refresh_service.fetch_daily_price_history",
        lambda tickers, **kwargs: [
            {"date": "2026-06-17", "ticker": "SPY", "close": 100.0},
            {"date": "2026-06-17", "ticker": "TLT", "close": 200.0},
            {"date": "2026-06-18", "ticker": "SPY", "close": 101.0},
            {"date": "2026-06-18", "ticker": "TLT", "close": 202.0},
        ],
    )
    monkeypatch.setattr(
        "src.market.intraday_refresh_service.fetch_intraday_bars",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("intraday fetch must not run")),
    )
    result = run_intraday_refresh(
        force=True,
        artifact_path=artifact_path,
        config=intraday_cfg,
    )

    ledger = json.loads(paper_portfolio_daily_path(tmp_path).read_text(encoding="utf-8"))
    strategy_ledger = json.loads(paper_strategy_daily_path(tmp_path).read_text(encoding="utf-8"))
    assert result["ok"] is True
    assert result["skipped_intraday"] is True
    assert result["daily_close_catchup_attempted"] is True
    assert result["daily_close_catchup_updated"] is True
    assert result["paper_performance_update"]["reason"] == "market_closed_gap_filled_from_delayed_daily_close"
    assert result["paper_performance_update"]["gap_fill_dates"] == ["2026-06-18"]
    assert result["paper_performance_update"]["live_brokerage_execution"] is False
    assert result["paper_performance_update"]["is_official_ledger"] is False
    assert [row["date"] for row in ledger["rows"]] == ["2026-06-17", "2026-06-18"]
    assert any(row["date"] == "2026-06-18" for row in strategy_ledger["rows"])
    assert read_latest_pointer(intraday_cfg) == previous_pointer


def test_market_closed_refresh_without_daily_close_history_creates_no_fake_row(
    monkeypatch,
    intraday_cfg,
    minimal_artifact,
    tmp_path: Path,
):
    _write_canonical_holdings(tmp_path, ["SPY", "TLT"])
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(json.dumps(minimal_artifact), encoding="utf-8")

    def _mock_fetch_open(tickers, **kwargs):
        return {
            "provider": "yfinance",
            "bar_interval": "5m",
            "requested_tickers": tickers,
            "rows": [
                {
                    "source_ticker": ticker,
                    "observation_ts_et": "2026-06-17T15:55:00-04:00",
                    "session_date": "2026-06-17",
                    "open": 100.0,
                    "high": 102.0,
                    "low": 99.0,
                    "close": 101.0,
                    "volume": 1000.0,
                    "bar_interval": "5m",
                    "bar_completeness": "completed",
                    "intraday_return_from_open": 0.01,
                    "timezone": "America/New_York",
                }
                for ticker in tickers
            ],
            "missing_tickers": [],
            "stale_tickers": [],
            "ticker_count_requested": len(tickers),
            "ticker_count_successful": len(tickers),
            "latest_observation_ts_et": "2026-06-17T15:55:00-04:00",
            "latest_completed_bar_ts_et": "2026-06-17T15:55:00-04:00",
        }

    monkeypatch.setattr(
        "src.market.intraday_refresh_service.market_session_status",
        lambda *args, **kwargs: MarketSessionInfo("Open", "America/New_York", "2026-06-17", True, None),
    )
    run_intraday_refresh(force=True, artifact_path=artifact_path, config=intraday_cfg, fetch_fn=_mock_fetch_open)
    previous_pointer = read_latest_pointer(intraday_cfg)
    monkeypatch.setattr(
        "src.market.intraday_refresh_service.market_session_status",
        lambda *args, **kwargs: MarketSessionInfo("Closed", "America/New_York", "2026-06-18", True, None),
    )
    monkeypatch.setattr("src.market.intraday_refresh_service.fetch_daily_price_history", lambda tickers, **kwargs: [])
    monkeypatch.setattr(
        "src.market.intraday_refresh_service.fetch_intraday_bars",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("intraday fetch must not run")),
    )
    result = run_intraday_refresh(
        force=True,
        artifact_path=artifact_path,
        config=intraday_cfg,
    )

    ledger = json.loads(paper_portfolio_daily_path(tmp_path).read_text(encoding="utf-8"))
    assert result["ok"] is True
    assert result["skipped_intraday"] is True
    assert result["daily_close_catchup_attempted"] is True
    assert result["daily_close_catchup_updated"] is False
    assert result["paper_performance_update"]["reason"] == "daily_close_history_unavailable"
    assert [row["date"] for row in ledger["rows"]] == ["2026-06-17"]
    assert read_latest_pointer(intraday_cfg) == previous_pointer


def test_refresh_failure_preserves_last_valid_snapshot(intraday_cfg, minimal_artifact, tmp_path: Path):
    _write_canonical_holdings(tmp_path)
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


def test_refresh_recovers_stale_lock_and_running_status(intraday_cfg, minimal_artifact, tmp_path: Path):
    _write_canonical_holdings(tmp_path, ["SPY"])
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(json.dumps(minimal_artifact), encoding="utf-8")
    lock_path = Path(intraday_cfg["lock_path"])
    lock_path.write_text("stale", encoding="utf-8")
    old = datetime(2026, 6, 18, 2, 21, tzinfo=timezone.utc).timestamp()
    os.utime(lock_path, (old, old))
    Path(intraday_cfg["status_path"]).write_text(
        json.dumps(
            {
                "state": "running",
                "in_progress": True,
                "started_at": "2026-06-18T02:21:51+00:00",
                "selected_interval_minutes": 30,
            }
        ),
        encoding="utf-8",
    )

    def _mock_fetch_success(tickers, **kwargs):
        return {
            "provider": "yfinance",
            "bar_interval": "5m",
            "requested_tickers": tickers,
            "rows": [
                {
                    "source_ticker": "SPY",
                    "observation_ts_et": "2026-06-22T10:00:00-04:00",
                    "session_date": "2026-06-22",
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 101.0,
                    "volume": 1000.0,
                    "bar_interval": "5m",
                    "bar_completeness": "completed",
                    "intraday_return_from_open": 0.01,
                    "timezone": "America/New_York",
                }
            ],
            "missing_tickers": [],
            "stale_tickers": [],
            "ticker_count_requested": len(tickers),
            "ticker_count_successful": len(tickers),
            "latest_observation_ts_et": "2026-06-22T10:00:00-04:00",
            "latest_completed_bar_ts_et": "2026-06-22T10:00:00-04:00",
        }

    result = run_intraday_refresh(
        force=True,
        artifact_path=artifact_path,
        config=intraday_cfg,
        fetch_fn=_mock_fetch_success,
    )

    assert result["ok"] is True
    assert result["refresh_status"] == "success"
    assert lock_path.exists() is False


def test_refresh_uses_committed_shadow_holdings_when_shadow_db_unavailable(intraday_cfg, minimal_artifact, tmp_path: Path):
    root = tmp_path
    artifact_path = root / "output" / "dashboard_artifact.json"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text(json.dumps(minimal_artifact), encoding="utf-8")
    canonical_dir = root / "dashboard" / "data"
    canonical_dir.mkdir(parents=True)
    canonical_dir.joinpath("canonical_operational.json").write_text(
        json.dumps(
            {
                "holdings": [
                    {"date": "2026-06-10", "strategy_id": "S1", "ticker": "OLD", "target_weight": 1.0},
                    {"date": "2026-06-11", "strategy_id": "S1", "ticker": "SPY", "target_weight": 0.5},
                    {"date": "2026-06-11", "strategy_id": "S2", "ticker": "TLT", "target_weight": -0.5},
                ]
            }
        ),
        encoding="utf-8",
    )
    seen = {}

    def _mock_fetch_success(tickers, **kwargs):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        seen["tickers"] = list(tickers)
        now_et = datetime.now(tz=ZoneInfo("America/New_York")).isoformat()
        return {
            "provider": "yfinance",
            "bar_interval": "5m",
            "requested_tickers": tickers,
            "rows": [
                {
                    "source_ticker": ticker,
                    "observation_ts_et": now_et,
                    "session_date": now_et[:10],
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 101.0,
                    "volume": 1000.0,
                    "bar_interval": "5m",
                    "bar_completeness": "completed",
                    "intraday_return_from_open": 0.01,
                    "timezone": "America/New_York",
                }
                for ticker in tickers
            ],
            "missing_tickers": [],
            "stale_tickers": [],
            "ticker_count_requested": len(tickers),
            "ticker_count_successful": len(tickers),
            "latest_observation_ts_et": now_et,
            "latest_completed_bar_ts_et": now_et,
        }

    result = run_intraday_refresh(force=True, artifact_path=artifact_path, config=intraday_cfg, fetch_fn=_mock_fetch_success)

    assert result.get("ok") is True
    assert result["position_source"] == "committed_shadow_holdings"
    assert result["legacy_artifact_position_estimate_authoritative"] is False
    assert "no live brokerage positions or fills" in result["position_source_disclosure"]
    assert seen["tickers"] == ["SPY", "TLT"]
    snapshot = read_latest_snapshot(intraday_cfg)
    assert snapshot["position_source"] == "committed_shadow_holdings"
    assert snapshot["marks"]["position_source"] == "committed_shadow_holdings"
    assert snapshot["marks"]["legacy_artifact_position_estimate_authoritative"] is False
    assert "no live brokerage positions or fills" in snapshot["marks"]["position_source_disclosure"]


def test_refresh_uses_committed_holdings_without_creating_legacy_artifact(intraday_cfg, tmp_path: Path):
    root = tmp_path
    artifact_path = root / "output" / "dashboard_artifact.json"
    canonical_dir = root / "dashboard" / "data"
    canonical_dir.mkdir(parents=True)
    canonical_dir.joinpath("canonical_operational.json").write_text(
        json.dumps(
            {
                "portfolio_summary": {"as_of_date": "2026-06-12", "nav": 1_000_000},
                "strategies": [
                    {"internal_id": "S1", "display_name": "Paper Sleeve 1", "membership_state": "executed", "current_weight": 1.0}
                ],
                "holdings": [
                    {"date": "2026-06-12", "strategy_id": "S1", "ticker": "SPY", "target_weight": 1.0}
                ],
            }
        ),
        encoding="utf-8",
    )

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
                    "source_ticker": "SPY",
                    "observation_ts_et": now_et,
                    "session_date": now_et[:10],
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 101.0,
                    "volume": 1000.0,
                    "bar_interval": "5m",
                    "bar_completeness": "completed",
                    "intraday_return_from_open": 0.01,
                    "timezone": "America/New_York",
                }
            ],
            "missing_tickers": [],
            "stale_tickers": [],
            "ticker_count_requested": len(tickers),
            "ticker_count_successful": len(tickers),
            "latest_observation_ts_et": now_et,
            "latest_completed_bar_ts_et": now_et,
        }

    result = run_intraday_refresh(force=True, artifact_path=artifact_path, config=intraday_cfg, fetch_fn=_mock_fetch_success)

    assert result["ok"] is True
    assert result["position_source"] == "committed_shadow_holdings"
    assert result["paper_only"] is True
    assert result["live_brokerage_execution"] is False
    assert artifact_path.exists() is False


def test_refresh_prefers_committed_holdings_over_existing_legacy_artifact(intraday_cfg, tmp_path: Path):
    root = tmp_path
    artifact_path = root / "output" / "dashboard_artifact.json"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text(
        json.dumps(
            {
                "initial_capital": 1_000_000,
                "allocation": {"current_weights": {"LEGACY": 1.0}},
                "strategies": [
                    {
                        "strategy_id": "LEGACY",
                        "current_weight": 1.0,
                        "position_packet": {"latest_positions": [{"source_ticker": "OLD", "weight": 1.0}]},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    _write_canonical_holdings(root, ["SPY"])
    seen: dict[str, list[str]] = {}

    def _mock_fetch_success(tickers, **kwargs):
        seen["tickers"] = list(tickers)
        return {
            "provider": "yfinance",
            "bar_interval": "5m",
            "requested_tickers": tickers,
            "rows": [
                {
                    "source_ticker": "SPY",
                    "observation_ts_et": "2026-06-22T15:55:00-04:00",
                    "session_date": "2026-06-22",
                    "open": 100.0,
                    "high": 102.0,
                    "low": 99.0,
                    "close": 101.0,
                    "volume": 1000.0,
                    "bar_interval": "5m",
                    "bar_completeness": "completed",
                    "intraday_return_from_open": 0.01,
                    "timezone": "America/New_York",
                }
            ],
            "missing_tickers": [],
            "stale_tickers": [],
            "ticker_count_requested": len(tickers),
            "ticker_count_successful": len(tickers),
            "latest_observation_ts_et": "2026-06-22T15:55:00-04:00",
            "latest_completed_bar_ts_et": "2026-06-22T15:55:00-04:00",
        }

    result = run_intraday_refresh(force=True, artifact_path=artifact_path, config=intraday_cfg, fetch_fn=_mock_fetch_success)

    assert result["ok"] is True
    assert seen["tickers"] == ["SPY"]
    assert result["paper_performance_update"]["portfolio_row_updated"] is True
    ledger = json.loads(paper_portfolio_daily_path(tmp_path).read_text(encoding="utf-8"))
    assert ledger["rows"][0]["priced_tickers"] == ["SPY"]


def test_refresh_updates_portfolio_and_strategy_level_paper_performance(intraday_cfg, minimal_artifact, tmp_path: Path):
    _write_canonical_holdings(tmp_path, ["SPY", "TLT"])
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(json.dumps(minimal_artifact), encoding="utf-8")

    def _mock_fetch_success(rate: float, trading_date: str, ts: str):
        def _fetch(tickers, **kwargs):
            return {
                "provider": "yfinance",
                "bar_interval": "5m",
                "requested_tickers": tickers,
                "rows": [
                    {
                        "source_ticker": ticker,
                        "observation_ts_et": ts,
                        "session_date": trading_date,
                        "open": 100.0,
                        "high": 102.0,
                        "low": 99.0,
                        "close": 100.0 * (1.0 + rate),
                        "volume": 1000.0,
                        "bar_interval": "5m",
                        "bar_completeness": "completed",
                        "intraday_return_from_open": rate,
                        "timezone": "America/New_York",
                    }
                    for ticker in tickers
                ],
                "missing_tickers": [],
                "stale_tickers": [],
                "ticker_count_requested": len(tickers),
                "ticker_count_successful": len(tickers),
                "latest_observation_ts_et": ts,
                "latest_completed_bar_ts_et": ts,
            }
        return _fetch

    result = run_intraday_refresh(
        force=True,
        artifact_path=artifact_path,
        config=intraday_cfg,
        fetch_fn=_mock_fetch_success(0.01, "2026-06-17", "2026-06-17T15:50:00-04:00"),
    )

    update = result["paper_performance_update"]
    assert update["portfolio_row_updated"] is True
    assert update["strategy_rows_updated"] == 2
    assert update["trading_date"] == "2026-06-17"
    assert update["refresh_status"] == "fresh"
    ledger = json.loads(paper_portfolio_daily_path(tmp_path).read_text(encoding="utf-8"))
    assert ledger["metadata"]["is_official_ledger"] is False
    assert ledger["metadata"]["paper_only"] is True
    assert ledger["metadata"]["delayed_market_data"] is True
    assert len(ledger["rows"]) == 1
    row = ledger["rows"][0]
    assert row["date"] == "2026-06-17"
    assert row["position_source"] == "committed_shadow_holdings"
    assert row["daily_return"] == pytest.approx(0.01)
    assert row["daily_pnl"] == pytest.approx(10_000)
    assert row["is_official_ledger"] is False
    strategy_ledger = json.loads(paper_strategy_daily_path(tmp_path).read_text(encoding="utf-8"))
    assert strategy_ledger["metadata"]["is_official_ledger"] is False
    assert strategy_ledger["metadata"]["paper_only"] is True
    assert len(strategy_ledger["rows"]) == 2
    assert {row["strategy_id"] for row in strategy_ledger["rows"]} == {"S1", "S2"}
    assert all(row["date"] == "2026-06-17" for row in strategy_ledger["rows"])
    assert all(row["daily_return"] == pytest.approx(0.01) for row in strategy_ledger["rows"])
    second = run_intraday_refresh(
        force=True,
        artifact_path=artifact_path,
        config=intraday_cfg,
        fetch_fn=_mock_fetch_success(0.02, "2026-06-17", "2026-06-17T15:55:00-04:00"),
    )
    ledger = json.loads(paper_portfolio_daily_path(tmp_path).read_text(encoding="utf-8"))
    assert second["paper_performance_update"]["trading_date"] == "2026-06-17"
    assert len(ledger["rows"]) == 1
    assert ledger["rows"][0]["daily_return"] == pytest.approx(0.02)
    assert ledger["rows"][0]["daily_pnl"] == pytest.approx(20_000)
    strategy_ledger = json.loads(paper_strategy_daily_path(tmp_path).read_text(encoding="utf-8"))
    assert len(strategy_ledger["rows"]) == 2
    assert all(row["daily_return"] == pytest.approx(0.02) for row in strategy_ledger["rows"])
    third = run_intraday_refresh(
        force=True,
        artifact_path=artifact_path,
        config=intraday_cfg,
        fetch_fn=_mock_fetch_success(0.03, "2026-06-18", "2026-06-18T15:55:00-04:00"),
    )
    ledger = json.loads(paper_portfolio_daily_path(tmp_path).read_text(encoding="utf-8"))
    assert third["paper_performance_update"]["trading_date"] == "2026-06-18"
    assert [row["date"] for row in ledger["rows"]] == ["2026-06-17", "2026-06-18"]
    strategy_ledger = json.loads(paper_strategy_daily_path(tmp_path).read_text(encoding="utf-8"))
    assert sorted({(row["date"], row["strategy_id"]) for row in strategy_ledger["rows"]}) == [
        ("2026-06-17", "S1"),
        ("2026-06-17", "S2"),
        ("2026-06-18", "S1"),
        ("2026-06-18", "S2"),
    ]
    assert (tmp_path / "dashboard/data/performance/strategy_daily_performance.json").exists() is False


def test_refresh_stale_quote_labels_do_not_overwrite_paper_performance(intraday_cfg, minimal_artifact, tmp_path: Path):
    _write_canonical_holdings(tmp_path, ["SPY", "TLT"])
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(json.dumps(minimal_artifact), encoding="utf-8")

    def _mock_fetch(rate: float, ts: str, stale: bool = False):
        def _fetch(tickers, **kwargs):
            return {
                "provider": "yfinance",
                "bar_interval": "5m",
                "requested_tickers": tickers,
                "rows": [
                    {
                        "source_ticker": ticker,
                        "observation_ts_et": ts,
                        "session_date": ts[:10],
                        "open": 100.0,
                        "high": 102.0,
                        "low": 99.0,
                        "close": 100.0 * (1.0 + rate),
                        "volume": 1000.0,
                        "bar_interval": "5m",
                        "bar_completeness": "completed",
                        "intraday_return_from_open": rate,
                        "timezone": "America/New_York",
                    }
                    for ticker in tickers
                ],
                "missing_tickers": [],
                "stale_tickers": tickers if stale else [],
                "ticker_count_requested": len(tickers),
                "ticker_count_successful": len(tickers),
                "latest_observation_ts_et": ts,
                "latest_completed_bar_ts_et": ts,
            }
        return _fetch

    fresh = run_intraday_refresh(
        force=True,
        artifact_path=artifact_path,
        config=intraday_cfg,
        fetch_fn=_mock_fetch(0.01, "2026-06-17T15:50:00-04:00"),
    )
    ledger_before = json.loads(paper_portfolio_daily_path(tmp_path).read_text(encoding="utf-8"))

    stale = run_intraday_refresh(
        force=True,
        artifact_path=artifact_path,
        config=intraday_cfg,
        fetch_fn=_mock_fetch(0.20, "2026-06-17T15:55:00-04:00", stale=True),
    )
    ledger_after = json.loads(paper_portfolio_daily_path(tmp_path).read_text(encoding="utf-8"))

    assert fresh["paper_performance_update"]["portfolio_row_updated"] is True
    assert stale["paper_performance_update"]["portfolio_row_updated"] is False
    assert stale["paper_performance_update"]["reason"] == "stale_delayed_quotes_preserved_paper_ledger"
    assert ledger_after["rows"] == ledger_before["rows"]


def test_refresh_gap_fills_missing_paper_business_days_before_current_day(intraday_cfg, minimal_artifact, tmp_path: Path):
    _write_canonical_holdings(tmp_path, ["SPY", "TLT"])
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(json.dumps(minimal_artifact), encoding="utf-8")

    def _mock_fetch_success(rate: float, trading_date: str, ts: str, history: list[dict] | None = None):
        def _fetch(tickers, **kwargs):
            return {
                "provider": "yfinance",
                "bar_interval": "5m",
                "requested_tickers": tickers,
                "rows": [
                    {
                        "source_ticker": ticker,
                        "observation_ts_et": ts,
                        "session_date": trading_date,
                        "open": 100.0,
                        "high": 102.0,
                        "low": 99.0,
                        "close": 100.0 * (1.0 + rate),
                        "volume": 1000.0,
                        "bar_interval": "5m",
                        "bar_completeness": "completed",
                        "intraday_return_from_open": rate,
                        "timezone": "America/New_York",
                    }
                    for ticker in tickers
                ],
                "daily_price_history": history or [],
                "missing_tickers": [],
                "stale_tickers": [],
                "ticker_count_requested": len(tickers),
                "ticker_count_successful": len(tickers),
                "latest_observation_ts_et": ts,
                "latest_completed_bar_ts_et": ts,
            }
        return _fetch

    run_intraday_refresh(
        force=True,
        artifact_path=artifact_path,
        config=intraday_cfg,
        fetch_fn=_mock_fetch_success(0.01, "2026-06-17", "2026-06-17T15:55:00-04:00"),
    )
    stale_gap = run_intraday_refresh(
        force=True,
        artifact_path=artifact_path,
        config=intraday_cfg,
        fetch_fn=_mock_fetch_success(0.02, "2026-06-22", "2026-06-22T15:55:00-04:00"),
    )
    ledger = json.loads(paper_portfolio_daily_path(tmp_path).read_text(encoding="utf-8"))
    assert [row["date"] for row in ledger["rows"]] == ["2026-06-17", "2026-06-22"]
    assert stale_gap["paper_performance_update"]["gap_fill_missing_dates"] == ["2026-06-18"]
    assert stale_gap["paper_performance_update"]["gap_rows_updated"] == 0

    history = [
        {"date": "2026-06-17", "ticker": "SPY", "close": 100.0},
        {"date": "2026-06-17", "ticker": "TLT", "close": 200.0},
        {"date": "2026-06-18", "ticker": "SPY", "close": 101.0},
        {"date": "2026-06-18", "ticker": "TLT", "close": 202.0},
        {"date": "2026-06-22", "ticker": "SPY", "close": 103.0},
        {"date": "2026-06-22", "ticker": "TLT", "close": 206.0},
    ]
    filled = run_intraday_refresh(
        force=True,
        artifact_path=artifact_path,
        config=intraday_cfg,
        fetch_fn=_mock_fetch_success(0.025, "2026-06-22", "2026-06-22T15:58:00-04:00", history),
    )

    ledger = json.loads(paper_portfolio_daily_path(tmp_path).read_text(encoding="utf-8"))
    assert [row["date"] for row in ledger["rows"]] == ["2026-06-17", "2026-06-18", "2026-06-22"]
    assert "2026-06-19" not in [row["date"] for row in ledger["rows"]]
    assert filled["paper_performance_update"]["gap_fill_dates"] == ["2026-06-18"]
    assert filled["paper_performance_update"]["gap_rows_updated"] == 1
    gap_row = next(row for row in ledger["rows"] if row["date"] == "2026-06-18")
    assert gap_row["source"] == "Paper Portfolio Daily Gap Fill"
    assert gap_row["refresh_status"] == "gap_filled_from_delayed_daily_close"
    assert gap_row["prior_nav"] == pytest.approx(1_010_000)
    assert gap_row["daily_return"] == pytest.approx(0.01)
    assert gap_row["daily_pnl"] == pytest.approx(10_100)
    assert gap_row["is_official_ledger"] is False
    assert gap_row["paper_only"] is True
    current_row = next(row for row in ledger["rows"] if row["date"] == "2026-06-22")
    assert current_row["prior_nav"] == pytest.approx(gap_row["ending_nav"])
    assert current_row["ending_nav"] - current_row["prior_nav"] == pytest.approx(current_row["daily_pnl"])
    assert current_row["paper_nav_rebased_to_previous_paper_close"] is True


def test_stale_intraday_quotes_can_fill_paper_daily_from_valid_daily_close_history(
    intraday_cfg,
    minimal_artifact,
    tmp_path: Path,
):
    _write_canonical_holdings(tmp_path, ["SPY", "TLT"])
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(json.dumps(minimal_artifact), encoding="utf-8")

    def _mock_fetch(rate: float, trading_date: str, ts: str, *, stale: bool = False, history: list[dict] | None = None):
        def _fetch(tickers, **kwargs):
            return {
                "provider": "yfinance",
                "bar_interval": "5m",
                "requested_tickers": tickers,
                "rows": [
                    {
                        "source_ticker": ticker,
                        "observation_ts_et": ts,
                        "session_date": trading_date,
                        "open": 100.0,
                        "high": 103.0,
                        "low": 99.0,
                        "close": 100.0 * (1.0 + rate),
                        "volume": 1000.0,
                        "bar_interval": "5m",
                        "bar_completeness": "completed",
                        "intraday_return_from_open": rate,
                        "timezone": "America/New_York",
                    }
                    for ticker in tickers
                ],
                "daily_price_history": history or [],
                "daily_price_history_provider": "yfinance" if history else None,
                "missing_tickers": [],
                "stale_tickers": tickers if stale else [],
                "ticker_count_requested": len(tickers),
                "ticker_count_successful": len(tickers),
                "latest_observation_ts_et": ts,
                "latest_completed_bar_ts_et": ts,
            }
        return _fetch

    run_intraday_refresh(
        force=True,
        artifact_path=artifact_path,
        config=intraday_cfg,
        fetch_fn=_mock_fetch(0.01, "2026-06-17", "2026-06-17T15:55:00-04:00"),
    )
    history = [
        {"date": "2026-06-17", "ticker": "SPY", "close": 100.0},
        {"date": "2026-06-17", "ticker": "TLT", "close": 200.0},
        {"date": "2026-06-18", "ticker": "SPY", "close": 101.0},
        {"date": "2026-06-18", "ticker": "TLT", "close": 202.0},
    ]
    filled = run_intraday_refresh(
        force=True,
        artifact_path=artifact_path,
        config=intraday_cfg,
        fetch_fn=_mock_fetch(0.02, "2026-06-18", "2026-06-18T15:55:00-04:00", stale=True, history=history),
    )

    ledger = json.loads(paper_portfolio_daily_path(tmp_path).read_text(encoding="utf-8"))
    strategy_ledger = json.loads(paper_strategy_daily_path(tmp_path).read_text(encoding="utf-8"))
    assert [row["date"] for row in ledger["rows"]] == ["2026-06-17", "2026-06-18"]
    assert filled["paper_performance_update"]["reason"] == "stale_intraday_quotes_gap_filled_from_delayed_daily_close"
    assert filled["paper_performance_update"]["gap_fill_dates"] == ["2026-06-18"]
    assert filled["paper_performance_update"]["gap_rows_updated"] == 1
    assert filled["paper_performance_update"]["strategy_rows_updated"] == 2
    assert filled["paper_performance_update"]["is_official_ledger"] is False
    gap_row = ledger["rows"][-1]
    assert gap_row["source"] == "Paper Portfolio Daily Gap Fill"
    assert gap_row["refresh_status"] == "gap_filled_from_delayed_daily_close"
    assert gap_row["paper_only"] is True
    assert gap_row["is_official_ledger"] is False
    assert sorted(row["date"] for row in strategy_ledger["rows"] if row["date"] == "2026-06-18") == [
        "2026-06-18",
        "2026-06-18",
    ]
    assert all(row["source"] == "Paper Strategy Daily Gap Fill" for row in strategy_ledger["rows"] if row["date"] == "2026-06-18")


def test_refresh_includes_applied_paper_rebalance_costs_in_paper_only_rows(intraday_cfg, minimal_artifact, tmp_path: Path):
    _write_canonical_holdings(tmp_path, ["SPY", "TLT"])
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(json.dumps(minimal_artifact), encoding="utf-8")
    rebalance_dir = tmp_path / "data/paper_rebalance"
    rebalance_dir.mkdir(parents=True)
    (rebalance_dir / "current_paper_target_weights.json").write_text(
        json.dumps(
            {
                "schema_version": "paper_rebalance_v1",
                "applied_plan_id": "paper-rebalance-test",
                "intended_effective_date": "2026-06-17",
                "weights": {"S1": 0.6, "S2": 0.4},
                "paper_transaction_cost_total": 15.0,
                "paper_only": True,
            }
        ),
        encoding="utf-8",
    )
    (rebalance_dir / "paper_rebalance_plans.json").write_text(
        json.dumps(
            {
                "schema_version": "paper_rebalance_v1",
                "plans": [
                    {
                        "plan_id": "paper-rebalance-test",
                        "applied_status": "Applied to Paper Allocation",
                        "intended_effective_date": "2026-06-17",
                        "line_items": [
                            {"strategy_id": "S1", "estimated_transaction_cost": 10.0},
                            {"strategy_id": "S2", "estimated_transaction_cost": 5.0},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def _mock_fetch_success(tickers, **kwargs):
        return {
            "provider": "yfinance",
            "bar_interval": "5m",
            "requested_tickers": tickers,
            "rows": [
                {
                    "source_ticker": ticker,
                    "observation_ts_et": "2026-06-17T15:55:00-04:00",
                    "session_date": "2026-06-17",
                    "open": 100.0,
                    "high": 102.0,
                    "low": 99.0,
                    "close": 101.0,
                    "volume": 1000.0,
                    "bar_interval": "5m",
                    "bar_completeness": "completed",
                    "intraday_return_from_open": 0.01,
                    "timezone": "America/New_York",
                }
                for ticker in tickers
            ],
            "missing_tickers": [],
            "stale_tickers": [],
            "ticker_count_requested": len(tickers),
            "ticker_count_successful": len(tickers),
            "latest_observation_ts_et": "2026-06-17T15:55:00-04:00",
            "latest_completed_bar_ts_et": "2026-06-17T15:55:00-04:00",
        }

    result = run_intraday_refresh(
        force=True,
        artifact_path=artifact_path,
        config=intraday_cfg,
        fetch_fn=_mock_fetch_success,
    )

    assert result["paper_performance_update"]["paper_transaction_cost"] == pytest.approx(15.0)
    portfolio_rows = json.loads(paper_portfolio_daily_path(tmp_path).read_text(encoding="utf-8"))["rows"]
    assert portfolio_rows[0]["gross_pnl"] == pytest.approx(10_000)
    assert portfolio_rows[0]["daily_pnl"] == pytest.approx(9_985)
    assert portfolio_rows[0]["is_official_ledger"] is False
    strategy_rows = json.loads(paper_strategy_daily_path(tmp_path).read_text(encoding="utf-8"))["rows"]
    by_id = {row["strategy_id"]: row for row in strategy_rows}
    assert by_id["S1"]["paper_transaction_cost"] == pytest.approx(10.0)
    assert by_id["S1"]["gross_pnl"] == pytest.approx(6_000.0)
    assert by_id["S1"]["daily_pnl"] == pytest.approx(5_990.0)
    assert by_id["S1"]["applied_paper_target_weight"] == pytest.approx(0.6)
    assert by_id["S2"]["paper_transaction_cost"] == pytest.approx(5.0)
    assert by_id["S2"]["gross_pnl"] == pytest.approx(4_000.0)
    assert by_id["S2"]["daily_pnl"] == pytest.approx(3_995.0)
    assert by_id["S2"]["applied_paper_target_weight"] == pytest.approx(0.4)


def test_refresh_partial_provider_coverage_below_threshold_fails(intraday_cfg, minimal_artifact, tmp_path: Path):
    _write_canonical_holdings(tmp_path)
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(json.dumps(minimal_artifact), encoding="utf-8")

    def _mock_fetch_partial(tickers, **kwargs):
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
                    "bar_completeness": "completed",
                    "intraday_return_from_open": 0.01,
                    "timezone": "America/New_York",
                }
            ],
            "missing_tickers": tickers[1:],
            "stale_tickers": [],
            "ticker_count_requested": len(tickers),
            "ticker_count_successful": 1,
            "latest_observation_ts_et": now_et,
            "latest_completed_bar_ts_et": now_et,
        }

    result = run_intraday_refresh(force=True, artifact_path=artifact_path, config=intraday_cfg, fetch_fn=_mock_fetch_partial)

    assert result["ok"] is False
    assert "insufficient ticker coverage" in result["error"]
    update = result.get("paper_performance_update") or {}
    assert update.get("reason") == "refresh_failed"
    assert update.get("portfolio_row_updated") is False
    assert update.get("strategy_rows_updated") == 0


def test_refresh_rate_limit_returns_stale_cooldown_with_previous_snapshot(intraday_cfg, minimal_artifact, tmp_path: Path):
    _write_canonical_holdings(tmp_path)
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
                    "bar_completeness": "completed",
                    "intraday_return_from_open": 0.01,
                    "timezone": "America/New_York",
                }
            ],
            "missing_tickers": [],
            "stale_tickers": [],
            "ticker_count_requested": len(tickers),
            "ticker_count_successful": len(tickers),
            "latest_observation_ts_et": now_et,
            "latest_completed_bar_ts_et": now_et,
        }

    ok = run_intraday_refresh(force=True, artifact_path=artifact_path, config=intraday_cfg, fetch_fn=_mock_fetch_success)
    first_id = ok["snapshot_id"]
    ledger_before = json.loads(paper_portfolio_daily_path(tmp_path).read_text(encoding="utf-8"))
    assert len(ledger_before["rows"]) == 1

    def _mock_fetch_rate_limited(tickers, **kwargs):
        raise RuntimeError("yfinance 429 Too Many Requests")

    stale = run_intraday_refresh(force=True, artifact_path=artifact_path, config=intraday_cfg, fetch_fn=_mock_fetch_rate_limited)

    assert stale["ok"] is True
    assert stale["skipped"] is True
    assert stale["refresh_status"] == "stale_cooldown"
    assert stale["provider_cooldown"] is True
    assert stale["snapshot_id"] == first_id
    assert stale["paper_performance_update"]["portfolio_row_updated"] is False
    ledger_after = json.loads(paper_portfolio_daily_path(tmp_path).read_text(encoding="utf-8"))
    assert ledger_after["rows"] == ledger_before["rows"]


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
