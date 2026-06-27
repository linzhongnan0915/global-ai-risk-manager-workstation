"""Tests for scheduled intraday proxy refresh pipeline."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src.market.intraday_config import (
    bar_interval_for_refresh,
    load_intraday_config,
    resolve_refresh_interval_minutes,
    stale_after_minutes_for,
)
from src.market.intraday_provider import _normalize_intraday_panel, partition_completed_bars
from src.market.intraday_refresh_service import (
    build_refresh_status_payload,
    collect_refresh_tickers,
    refresh_lock,
    run_intraday_refresh,
    set_background_scheduler_enabled,
    set_refresh_cadence,
)
from src.market.market_hours import MarketSessionInfo, market_session_status, should_run_scheduled_refresh
from src.market.snapshot_store import publish_snapshot, read_latest_pointer, read_latest_snapshot
from src.strategies.shadow_intraday import (
    COMPOSITE_ID,
    DAILY_LABEL,
    INTRADAY_LABEL,
    build_shadow_intraday_estimates,
    collect_shadow_position_tickers,
    finalize_daily_shadow_returns,
)


@pytest.fixture
def intraday_cfg(tmp_path: Path) -> dict:
    cfg = load_intraday_config()
    cfg = dict(cfg)
    cfg["snapshot_dir"] = str(tmp_path / "snapshots")
    cfg["latest_pointer_path"] = str(tmp_path / "latest.json")
    cfg["status_path"] = str(tmp_path / "status.json")
    cfg["lock_path"] = str(tmp_path / "refresh.lock")
    cfg["shadow_database_path"] = str(tmp_path / "shadow.db")
    cfg["allow_artifact_position_fallback"] = True
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


def _mock_fetch_success(tickers, **kwargs):
    now_et = datetime.now(tz=ZoneInfo("America/New_York")).isoformat()
    rows = []
    for ticker in tickers:
        rows.append(
            {
                "source_ticker": ticker,
                "observation_ts_et": now_et,
                "session_date": now_et[:10],
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 101.0,
                "volume": 1000.0,
                "bar_interval": kwargs.get("bar_interval", "15m"),
                "intraday_return_from_open": 0.01,
                "timezone": "America/New_York",
            }
        )
    return {
        "provider": "yfinance",
        "bar_interval": kwargs.get("bar_interval", "15m"),
        "requested_tickers": tickers,
        "rows": rows,
        "missing_tickers": [],
        "stale_tickers": [],
        "ticker_count_requested": len(tickers),
        "ticker_count_successful": len(tickers),
        "latest_observation_ts_et": now_et,
        "incomplete_bar_label": "incomplete_current_bar",
    }


def _mock_fetch_partial(tickers, **kwargs):
    payload = _mock_fetch_success(tickers[: max(1, len(tickers) // 2)], **kwargs)
    payload["missing_tickers"] = tickers[max(1, len(tickers) // 2) :]
    payload["ticker_count_requested"] = len(tickers)
    payload["ticker_count_successful"] = len(payload["rows"])
    return payload


def _mock_fetch_fail(tickers, **kwargs):
    raise RuntimeError("provider unavailable")


def test_bar_interval_mapping_for_five_ten_and_thirty_minutes(intraday_cfg):
    assert bar_interval_for_refresh(intraday_cfg, 5) == "5m"
    assert bar_interval_for_refresh(intraday_cfg, 10) == "5m"
    assert bar_interval_for_refresh(intraday_cfg, 30) == "15m"
    assert "10m" not in set((intraday_cfg.get("bar_interval_by_refresh") or {}).values())


def test_default_refresh_cadence_matches_current_config(intraday_cfg):
    assert intraday_cfg["default_interval_minutes"] == 30
    assert intraday_cfg["allowed_intervals_minutes"] == [5, 10, 30]
    assert resolve_refresh_interval_minutes(intraday_cfg) == 30
    assert stale_after_minutes_for(intraday_cfg, 5) == 10
    assert stale_after_minutes_for(intraday_cfg, 10) == 20
    assert stale_after_minutes_for(intraday_cfg, 30) == 45


def test_optional_five_minute_refresh_mode(intraday_cfg, minimal_artifact, tmp_path: Path):
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(json.dumps(minimal_artifact), encoding="utf-8")
    result = run_intraday_refresh(
        force=True,
        interval_minutes=5,
        artifact_path=artifact_path,
        config=intraday_cfg,
        fetch_fn=_mock_fetch_success,
    )
    assert result["ok"] is True
    assert result["refresh_cadence_minutes"] == 5
    snapshot = read_latest_snapshot(intraday_cfg)
    assert snapshot["requested_bar_interval"] == "5m"
    assert snapshot["refresh_interval_minutes"] == 5


def test_completed_bar_selection_ignores_incomplete_current_bar():
    tz = ZoneInfo("America/New_York")
    now = datetime(2026, 6, 5, 10, 7, tzinfo=tz)
    rows = [
        {
            "source_ticker": "SPY",
            "observation_ts_et": datetime(2026, 6, 5, 10, 0, tzinfo=tz).isoformat(),
            "open": 100.0,
            "close": 100.5,
        },
        {
            "source_ticker": "SPY",
            "observation_ts_et": datetime(2026, 6, 5, 10, 5, tzinfo=tz).isoformat(),
            "open": 100.5,
            "close": 101.0,
        },
    ]
    completed, incomplete, latest_completed = partition_completed_bars(
        rows,
        bar_interval="5m",
        now_et=now,
        incomplete_bar_label="incomplete_current_bar",
    )
    assert len(completed) == 1
    assert completed[0]["bar_completeness"] == "completed"
    assert "SPY" in incomplete
    assert incomplete["SPY"]["bar_completeness"] == "incomplete_current_bar"
    assert latest_completed == completed[0]["observation_ts_et"]


def test_set_refresh_cadence_persists_without_market_fetch(intraday_cfg):
    payload = set_refresh_cadence(5, config=intraday_cfg)
    assert payload["selected_cadence_minutes"] == 5
    assert payload["bar_interval"] == "5m"
    status_payload = build_refresh_status_payload(intraday_cfg)
    assert status_payload["refresh_cadence_minutes"] == 5


def test_build_refresh_status_does_not_fetch_market_data(intraday_cfg, monkeypatch):
    def fail_fetch(*args, **kwargs):
        raise AssertionError("status poll must not fetch market data")

    monkeypatch.setattr("src.market.intraday_refresh_service.fetch_intraday_bars", fail_fetch)
    payload = build_refresh_status_payload(intraday_cfg)
    assert payload["ok"] is True


def test_bar_interval_mapping_30_and_10_minutes(intraday_cfg):
    assert bar_interval_for_refresh(intraday_cfg, 30) == "15m"
    assert bar_interval_for_refresh(intraday_cfg, 10) == "5m"


def test_market_closed_skips_scheduled_refresh(intraday_cfg):
    closed = datetime(2026, 6, 6, 12, 0, tzinfo=ZoneInfo("America/New_York"))  # Saturday
    assert should_run_scheduled_refresh(
        closed,
        timezone=intraday_cfg["timezone"],
        holidays=intraday_cfg["market_holidays"],
        regular_session_only=True,
    ) is False
    info = market_session_status(closed, timezone=intraday_cfg["timezone"], holidays=intraday_cfg["market_holidays"])
    assert info.status == "Closed"


def test_market_open_allows_scheduled_refresh(intraday_cfg):
    open_time = datetime(2026, 6, 5, 11, 0, tzinfo=ZoneInfo("America/New_York"))
    assert should_run_scheduled_refresh(
        open_time,
        timezone=intraday_cfg["timezone"],
        holidays=intraday_cfg["market_holidays"],
        regular_session_only=True,
    ) is True


def test_duplicate_refresh_job_prevented(intraday_cfg, minimal_artifact, tmp_path: Path):
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(json.dumps(minimal_artifact), encoding="utf-8")
    lock_path = Path(intraday_cfg["lock_path"])
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    try:
        result = run_intraday_refresh(
            force=True,
            artifact_path=artifact_path,
            config=intraday_cfg,
            fetch_fn=_mock_fetch_success,
        )
        assert result["ok"] is False
        assert result["error"] == "refresh_already_in_progress"
    finally:
        lock_path.unlink(missing_ok=True)


def test_successful_refresh_publishes_snapshot(intraday_cfg, minimal_artifact, tmp_path: Path):
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(json.dumps(minimal_artifact), encoding="utf-8")
    open_time = datetime(2026, 6, 5, 11, 0, tzinfo=ZoneInfo("America/New_York"))
    result = run_intraday_refresh(
        force=True,
        artifact_path=artifact_path,
        config=intraday_cfg,
        fetch_fn=_mock_fetch_success,
    )
    assert result["ok"] is True
    assert result["snapshot_id"]
    pointer = read_latest_pointer(intraday_cfg)
    assert pointer["snapshot_id"] == result["snapshot_id"]
    snapshot = read_latest_snapshot(intraday_cfg)
    assert snapshot["refresh_status"] == "success"
    assert snapshot["latest_observation_ts_et"]
    assert snapshot["refresh_completed_at"] != snapshot["latest_observation_ts_et"]


def test_failed_refresh_preserves_previous_snapshot(intraday_cfg, minimal_artifact, tmp_path: Path):
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(json.dumps(minimal_artifact), encoding="utf-8")
    ok = run_intraday_refresh(force=True, artifact_path=artifact_path, config=intraday_cfg, fetch_fn=_mock_fetch_success)
    prior_id = ok["snapshot_id"]
    fail = run_intraday_refresh(force=True, artifact_path=artifact_path, config=intraday_cfg, fetch_fn=_mock_fetch_fail)
    assert fail["ok"] is False
    assert read_latest_pointer(intraday_cfg)["snapshot_id"] == prior_id


def test_partial_ticker_failure_below_threshold_fails(intraday_cfg, minimal_artifact, tmp_path: Path):
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(json.dumps(minimal_artifact), encoding="utf-8")
    intraday_cfg["min_success_ticker_ratio"] = 0.95
    result = run_intraday_refresh(
        force=True,
        artifact_path=artifact_path,
        config=intraday_cfg,
        fetch_fn=_mock_fetch_partial,
    )
    assert result["ok"] is False
    assert "insufficient ticker coverage" in result["error"]


def test_partial_ticker_failure_above_threshold_marks_delayed(intraday_cfg, minimal_artifact, tmp_path: Path):
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(json.dumps(minimal_artifact), encoding="utf-8")
    intraday_cfg["min_success_ticker_ratio"] = 0.3
    result = run_intraday_refresh(
        force=True,
        artifact_path=artifact_path,
        config=intraday_cfg,
        fetch_fn=_mock_fetch_partial,
    )
    assert result["ok"] is True
    snapshot = read_latest_snapshot(intraday_cfg)
    assert snapshot["marks"]["data_quality"]["freshness"] == "Delayed"
    status = build_refresh_status_payload(intraday_cfg)
    assert status["failed_ticker_count"] == len(snapshot["missing_tickers"])


def test_stale_ticker_classification():
    idx = pd.date_range("2026-06-05 09:30", periods=1, freq="15min", tz="UTC")
    data = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [101.0],
            "Low": [99.0],
            "Close": [100.5],
            "Volume": [1000.0],
        },
        index=idx,
    )
    rows, missing, stale = _normalize_intraday_panel(
        data,
        ["SPY"],
        bar_interval="15m",
        target_timezone="America/New_York",
        stale_after_minutes=0,
    )
    assert rows
    assert stale == ["SPY"]


def test_duplicate_bar_removal_and_timezone_normalization():
    idx = pd.to_datetime(["2026-06-05 09:30:00", "2026-06-05 09:30:00"], utc=True)
    data = pd.DataFrame(
        {
            "Open": [100.0, 100.0],
            "High": [101.0, 101.0],
            "Low": [99.0, 99.0],
            "Close": [100.5, 100.5],
            "Volume": [1000.0, 1000.0],
        },
        index=idx,
    )
    rows, missing, stale = _normalize_intraday_panel(
        data,
        ["SPY"],
        bar_interval="15m",
        target_timezone="America/New_York",
        stale_after_minutes=45,
    )
    assert len(rows) == 1
    assert "America/New_York" in rows[0]["observation_ts_et"] or "-04:00" in rows[0]["observation_ts_et"] or "-05:00" in rows[0]["observation_ts_et"]


def test_snapshot_atomic_publish(intraday_cfg):
    snapshot = {"snapshot_id": "snap-test-001", "refresh_status": "success", "marks": {}}
    publish_snapshot(snapshot, intraday_cfg)
    pointer = read_latest_pointer(intraday_cfg)
    stored = read_latest_snapshot(intraday_cfg)
    assert pointer["snapshot_id"] == "snap-test-001"
    assert stored["snapshot_id"] == "snap-test-001"
    assert Path(intraday_cfg["snapshot_dir"], "snap-test-001.json").exists()


def test_revaluation_updates_nav_not_allocation(intraday_cfg, minimal_artifact, tmp_path: Path):
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(json.dumps(minimal_artifact), encoding="utf-8")
    result = run_intraday_refresh(
        force=True,
        artifact_path=artifact_path,
        config=intraday_cfg,
        fetch_fn=_mock_fetch_success,
    )
    snapshot = read_latest_snapshot(intraday_cfg)
    marks = snapshot["marks"]
    assert marks["estimated_model_nav"] is None
    assert marks["estimated_intraday_pnl"] is None
    assert marks["shadow_intraday"]["available"] is False
    assert marks["evaluation_metadata"]["allocation_unchanged"] is True
    assert marks["evaluation_metadata"]["signals_unchanged"] is True
    assert snapshot["governance_preserved"]["allocation_weights_unchanged"] == minimal_artifact["allocation"]["current_weights"]
    assert snapshot["governance_preserved"]["signals_as_of_unchanged"] == "2026-06-04"


def test_scheduled_refresh_skipped_when_market_closed(intraday_cfg, minimal_artifact, tmp_path: Path, monkeypatch):
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(json.dumps(minimal_artifact), encoding="utf-8")
    monkeypatch.setattr(
        "src.market.intraday_refresh_service.should_run_scheduled_refresh",
        lambda *args, **kwargs: False,
    )
    result = run_intraday_refresh(force=False, artifact_path=artifact_path, config=intraday_cfg, fetch_fn=_mock_fetch_fail)
    assert result.get("skipped") is True
    assert read_latest_pointer(intraday_cfg) is None


def test_after_hours_runs_until_daily_shadow_is_finalized(intraday_cfg, minimal_artifact, tmp_path: Path, monkeypatch):
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(json.dumps(minimal_artifact), encoding="utf-8")
    monkeypatch.setattr("src.market.intraday_refresh_service.should_run_scheduled_refresh", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        "src.market.intraday_refresh_service.market_session_status",
        lambda *args, **kwargs: MarketSessionInfo("After-hours", "America/New_York", "2026-06-11", True, None),
    )
    result = run_intraday_refresh(
        force=False, interval_minutes=5, artifact_path=artifact_path, config=intraday_cfg, fetch_fn=_mock_fetch_success,
    )
    assert result["ok"] is True
    assert not result.get("skipped")


def test_manual_and_scheduled_share_pipeline(intraday_cfg, minimal_artifact, tmp_path: Path):
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(json.dumps(minimal_artifact), encoding="utf-8")
    manual = run_intraday_refresh(force=True, artifact_path=artifact_path, config=intraday_cfg, fetch_fn=_mock_fetch_success)
    scheduled = run_intraday_refresh(force=True, interval_minutes=10, artifact_path=artifact_path, config=intraday_cfg, fetch_fn=_mock_fetch_success)
    assert manual["ok"] and scheduled["ok"]
    assert read_latest_snapshot(intraday_cfg)["requested_bar_interval"] == "5m"


def test_build_refresh_status_payload_shape(intraday_cfg):
    payload = build_refresh_status_payload(intraday_cfg)
    assert payload["ok"] is True
    assert payload["refresh_cadence_minutes"] == 30
    assert payload["bar_interval"] == "15m"
    assert payload["scheduler_state"]
    assert payload["latest_completed_market_bar_at"] is None or isinstance(payload["latest_completed_market_bar_at"], str)
    assert "disclosure" in payload


def test_collect_refresh_tickers_includes_universe_and_positions(minimal_artifact):
    tickers = collect_refresh_tickers(minimal_artifact)
    assert "SPY" in tickers
    assert "TLT" in tickers
    assert len(tickers) > 2


def test_shadow_positions_drive_tickers_and_daily_finalization_is_idempotent(tmp_path):
    database = tmp_path / "shadow.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE daily_strategy_positions (
              strategy_id TEXT, date TEXT, ticker TEXT, data_label TEXT, target_weight REAL,
              PRIMARY KEY(strategy_id,date,ticker,data_label));
            CREATE TABLE daily_strategy_returns (
              strategy_id TEXT, date TEXT, data_label TEXT, net_return REAL,
              PRIMARY KEY(strategy_id,date,data_label));
            """
        )
        for strategy_id in ("C2A2_020", "C2B2_004"):
            connection.execute(
                "INSERT INTO daily_strategy_positions VALUES (?,?,?,?,?)",
                (strategy_id, "2026-06-11", "AAA", "SHADOW", 1.0),
            )
    rows = [
        {"source_ticker": "AAA", "session_date": "2026-06-11", "observation_ts_et": "2026-06-11T09:30:00-04:00",
         "open": 100.0, "close": 100.5, "bar_completeness": "completed"},
        {"source_ticker": "AAA", "session_date": "2026-06-11", "observation_ts_et": "2026-06-11T15:55:00-04:00",
         "open": 100.5, "close": 102.0, "bar_completeness": "completed"},
    ]
    assert collect_shadow_position_tickers(database) == ["AAA"]
    estimates = build_shadow_intraday_estimates(database, rows)
    assert estimates["data_label"] == INTRADAY_LABEL
    assert {row["strategy_id"] for row in estimates["strategies"]} == {"C2A2_020", "C2B2_004", COMPOSITE_ID}
    first = finalize_daily_shadow_returns(database, estimates, latest_completed_bar_ts=rows[-1]["observation_ts_et"], bar_minutes=5)
    second = finalize_daily_shadow_returns(database, estimates, latest_completed_bar_ts=rows[-1]["observation_ts_et"], bar_minutes=5)
    assert first["finalized"] and second["finalized"]
    with sqlite3.connect(database) as connection:
        rows_written = connection.execute("SELECT strategy_id,data_label,nav_value FROM daily_strategy_returns").fetchall()
    assert len(rows_written) == 3
    assert {row[1] for row in rows_written} == {DAILY_LABEL}


def test_missing_position_mark_withholds_strategy_and_composite(tmp_path):
    database = tmp_path / "shadow.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE daily_strategy_positions (
              strategy_id TEXT, date TEXT, ticker TEXT, data_label TEXT, target_weight REAL,
              PRIMARY KEY(strategy_id,date,ticker,data_label));
            CREATE TABLE daily_strategy_returns (
              strategy_id TEXT, date TEXT, data_label TEXT, net_return REAL,
              PRIMARY KEY(strategy_id,date,data_label));
            """
        )
        for strategy_id in ("C2A2_020", "C2B2_004"):
            connection.execute("INSERT INTO daily_strategy_positions VALUES (?,?,?,?,?)", (strategy_id, "2026-06-11", "AAA", "SHADOW", 0.5))
            connection.execute("INSERT INTO daily_strategy_positions VALUES (?,?,?,?,?)", (strategy_id, "2026-06-11", "MISSING", "SHADOW", -0.5))
    rows = [{"source_ticker": "AAA", "session_date": "2026-06-11", "observation_ts_et": "2026-06-11T10:00:00-04:00",
             "open": 100.0, "close": 102.0, "bar_completeness": "completed"}]
    estimates = build_shadow_intraday_estimates(database, rows)
    lookup = {row["strategy_id"]: row for row in estimates["strategies"]}
    assert lookup["C2A2_020"]["status"] == "INCOMPLETE"
    assert lookup["C2A2_020"]["missing_tickers"] == ["MISSING"]
    assert lookup["C2A2_020"]["uncovered_gross_weight"] == pytest.approx(0.5)
    assert lookup["C2A2_020"]["estimated_pnl"] is None
    assert lookup[COMPOSITE_ID]["available"] is False
    assert lookup[COMPOSITE_ID]["estimated_pnl"] is None


def test_snapshot_kpi_uses_same_withheld_canonical_shadow_estimate(intraday_cfg, minimal_artifact, tmp_path):
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(json.dumps(minimal_artifact), encoding="utf-8")
    with sqlite3.connect(intraday_cfg["shadow_database_path"]) as connection:
        connection.executescript(
            """
            CREATE TABLE daily_strategy_positions (
              strategy_id TEXT, date TEXT, ticker TEXT, data_label TEXT, target_weight REAL,
              PRIMARY KEY(strategy_id,date,ticker,data_label));
            CREATE TABLE daily_strategy_returns (
              strategy_id TEXT, date TEXT, data_label TEXT, net_return REAL,
              PRIMARY KEY(strategy_id,date,data_label));
            """
        )
        for strategy_id in ("C2A2_020", "C2B2_004"):
            connection.execute("INSERT INTO daily_strategy_positions VALUES (?,?,?,?,?)", (strategy_id, "2026-06-11", "SPY", "SHADOW", 0.5))
            connection.execute("INSERT INTO daily_strategy_positions VALUES (?,?,?,?,?)", (strategy_id, "2026-06-11", "TLT", "SHADOW", -0.5))
    intraday_cfg["min_success_ticker_ratio"] = 0.3
    result = run_intraday_refresh(
        force=True, interval_minutes=5, artifact_path=artifact_path, config=intraday_cfg, fetch_fn=_mock_fetch_partial,
    )
    assert result["ok"] is True
    snapshot = read_latest_snapshot(intraday_cfg)
    assert snapshot["shadow_intraday"]["available"] is False
    assert snapshot["marks"]["estimated_intraday_pnl"] is None
    assert snapshot["marks"]["estimated_model_nav"] is None
    assert snapshot["marks"]["strategy_marks"] == snapshot["shadow_intraday"]["strategies"]


def test_short_position_rising_stock_has_negative_contribution(tmp_path):
    database = tmp_path / "shadow.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE daily_strategy_positions (
              strategy_id TEXT, date TEXT, ticker TEXT, data_label TEXT, target_weight REAL,
              PRIMARY KEY(strategy_id,date,ticker,data_label));
            CREATE TABLE daily_strategy_returns (
              strategy_id TEXT, date TEXT, data_label TEXT, net_return REAL,
              PRIMARY KEY(strategy_id,date,data_label));
            """
        )
        for strategy_id in ("C2A2_020", "C2B2_004"):
            connection.execute("INSERT INTO daily_strategy_positions VALUES (?,?,?,?,?)", (strategy_id, "2026-06-11", "AAA", "SHADOW", -0.5))
    rows = [{"source_ticker": "AAA", "session_date": "2026-06-11", "observation_ts_et": "2026-06-11T10:00:00-04:00",
             "open": 100.0, "close": 102.0, "bar_completeness": "completed"}]
    estimates = build_shadow_intraday_estimates(database, rows)
    lookup = {row["strategy_id"]: row for row in estimates["strategies"]}
    assert lookup["C2A2_020"]["estimated_return"] == pytest.approx(-0.01)


def test_no_valid_position_marks_are_unavailable(tmp_path):
    database = tmp_path / "shadow.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE daily_strategy_positions (
              strategy_id TEXT, date TEXT, ticker TEXT, data_label TEXT, target_weight REAL,
              PRIMARY KEY(strategy_id,date,ticker,data_label));
            CREATE TABLE daily_strategy_returns (
              strategy_id TEXT, date TEXT, data_label TEXT, net_return REAL,
              PRIMARY KEY(strategy_id,date,data_label));
            """
        )
    estimates = build_shadow_intraday_estimates(database, [])
    assert estimates["available"] is False
    assert estimates["estimated_pnl"] is None


def test_scheduler_disabled_is_exposed(intraday_cfg):
    set_background_scheduler_enabled(False)
    try:
        status = build_refresh_status_payload(intraday_cfg)
        assert status["scheduler_enabled"] is False
        assert status["scheduler_display"] == "idle"
        assert "scheduler runs while the service is awake" in status["scheduler_deployment_note"]
    finally:
        set_background_scheduler_enabled(None)


def test_refresh_lock_context_manager(intraday_cfg):
    lock_path = Path(intraday_cfg["lock_path"])
    with refresh_lock(lock_path) as first:
        assert first is True
        with refresh_lock(lock_path) as second:
            assert second is False


def test_retry_behavior_on_transient_provider_errors(monkeypatch):
    attempts = {"count": 0}

    def flaky_download(**kwargs):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ConnectionError("temporary outage")
        idx = pd.date_range("2026-06-05 10:00", periods=1, freq="15min", tz="UTC")
        return pd.DataFrame(
            {"Open": [100.0], "High": [101.0], "Low": [99.0], "Close": [100.5], "Volume": [1000.0]},
            index=idx,
        )

    monkeypatch.setattr("src.market.intraday_provider.yf.download", flaky_download)
    from src.market.intraday_provider import fetch_intraday_bars

    payload = fetch_intraday_bars(
        ["SPY"],
        bar_interval="15m",
        retry_attempts=3,
        backoff_seconds=[0, 0, 0],
    )
    assert attempts["count"] == 3
    assert payload["ticker_count_successful"] == 1


def test_yfinance_request_is_recent_five_minute_batch(monkeypatch):
    captured = {}

    def fake_download(**kwargs):
        captured.update(kwargs)
        idx = pd.date_range("2026-06-11 14:00", periods=2, freq="5min", tz="UTC")
        return pd.DataFrame(
            {"Open": [100.0, 100.5], "High": [101.0, 101.0], "Low": [99.0, 100.0],
             "Close": [100.5, 100.8], "Volume": [1000.0, 1200.0]},
            index=idx,
        )

    monkeypatch.setattr("src.market.intraday_provider.yf.download", fake_download)
    from src.market.intraday_provider import fetch_intraday_bars

    fetch_intraday_bars(["AAA"], bar_interval="5m", retry_attempts=1)
    assert captured["tickers"] == ["AAA"]
    assert captured["period"] == "1d"
    assert captured["interval"] == "5m"
    assert captured["auto_adjust"] is False


def test_intraday_fetch_maps_class_share_ticker_and_restores_source(monkeypatch):
    captured = {}

    def fake_download(**kwargs):
        captured.update(kwargs)
        idx = pd.date_range("2026-06-11 14:00", periods=2, freq="5min", tz="UTC")
        columns = pd.MultiIndex.from_product([["BRK-B"], ["Open", "High", "Low", "Close", "Volume"]])
        return pd.DataFrame([[100, 101, 99, 100.5, 1000], [100.5, 101, 100, 100.8, 1200]], index=idx, columns=columns)

    monkeypatch.setattr("src.market.intraday_provider.yf.download", fake_download)
    from src.market.intraday_provider import fetch_intraday_bars

    payload = fetch_intraday_bars(["BRK.B"], bar_interval="5m", retry_attempts=1)
    assert captured["tickers"] == ["BRK-B"]
    assert payload["requested_tickers"] == ["BRK.B"]
    assert {row["source_ticker"] for row in payload["rows"]} == {"BRK.B"}


def test_stale_response_does_not_overwrite_newer_snapshot(intraday_cfg, minimal_artifact, tmp_path):
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(json.dumps(minimal_artifact), encoding="utf-8")
    publish_snapshot(
        {
            "snapshot_id": "newer", "refresh_status": "success",
            "latest_completed_bar_ts_et": "2026-06-11T15:55:00-04:00",
            "latest_observation_ts_et": "2026-06-11T15:55:00-04:00",
            "refresh_completed_at": "2026-06-11T20:01:00+00:00", "marks": {"data_quality": {"freshness": "Current"}},
        },
        intraday_cfg,
    )

    def older_fetch(tickers, **kwargs):
        payload = _mock_fetch_success(tickers, **kwargs)
        payload["latest_completed_bar_ts_et"] = "2026-06-11T15:50:00-04:00"
        payload["latest_observation_ts_et"] = "2026-06-11T15:50:00-04:00"
        return payload

    result = run_intraday_refresh(force=True, artifact_path=artifact_path, config=intraday_cfg, fetch_fn=older_fetch)
    assert result["skipped"] is True
    assert read_latest_pointer(intraday_cfg)["snapshot_id"] == "newer"


def test_concurrent_refresh_threads_one_wins(intraday_cfg, minimal_artifact, tmp_path: Path):
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(json.dumps(minimal_artifact), encoding="utf-8")
    results: list[dict] = []

    def worker():
        results.append(
            run_intraday_refresh(
                force=True,
                artifact_path=artifact_path,
                config=intraday_cfg,
                fetch_fn=_mock_fetch_success,
            )
        )

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(1 for item in results if item.get("ok")) >= 1
    assert any(item.get("error") == "refresh_already_in_progress" for item in results)
