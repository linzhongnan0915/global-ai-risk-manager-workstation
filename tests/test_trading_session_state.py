from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest

from src.market.trading_session import build_trading_session_state
from src.reporting.operational_snapshot import build_operational_snapshot, load_operational_snapshot_for_response


ROOT = Path(__file__).resolve().parents[1]


def _canonical() -> dict:
    return json.loads((ROOT / "dashboard/data/canonical_operational.json").read_text(encoding="utf-8"))


def _copy_root(tmp_path: Path) -> Path:
    target = tmp_path / "workstation"
    (target / "dashboard/data").mkdir(parents=True)
    (target / "dashboard/data/canonical_operational.json").write_text(json.dumps(_canonical()), encoding="utf-8")
    return target


def test_saturday_with_friday_quote_returns_weekend_state() -> None:
    state = build_trading_session_state(
        calendar_now=datetime.fromisoformat("2026-06-27T10:00:00-04:00"),
        latest_quote_asof="2026-06-26T15:45:00-04:00",
        daily_ledger_date="2026-06-26",
    )

    assert state["calendar_date"] == "2026-06-27"
    assert state["market_session_status"] == "MARKET_CLOSED_WEEKEND"
    assert state["is_trading_day"] is False
    assert state["current_intraday_session"] is None
    assert state["last_trading_session"] == "2026-06-26"
    assert state["next_trading_session"] == "2026-06-29"
    assert state["quote_freshness"] == "STALE_PRIOR_SESSION"
    assert state["intraday_estimate_status"] == "NO_CURRENT_SESSION_INTRADAY"
    assert state["daily_ledger_relation"] == "QUOTE_SESSION_ALREADY_RECORDED"


def test_trading_day_same_session_quote_is_current() -> None:
    state = build_trading_session_state(
        calendar_now=datetime.fromisoformat("2026-06-29T10:15:00-04:00"),
        latest_quote_asof="2026-06-29T10:10:00-04:00",
        daily_ledger_date="2026-06-26",
        market_session_status_hint="Open",
    )

    assert state["is_trading_day"] is True
    assert state["current_intraday_session"] == "2026-06-29"
    assert state["quote_freshness"] == "CURRENT_SESSION"
    assert state["intraday_estimate_status"] == "CURRENT_SESSION_INTRADAY"
    assert state["daily_ledger_relation"] == "QUOTE_SESSION_NOT_RECORDED"


def test_trading_day_prior_session_quote_is_stale() -> None:
    state = build_trading_session_state(
        calendar_now="2026-06-29T10:15:00-04:00",
        latest_quote_asof="2026-06-26T15:45:00-04:00",
        daily_ledger_date="2026-06-26",
    )

    assert state["is_trading_day"] is True
    assert state["quote_freshness"] == "STALE_PRIOR_SESSION"
    assert state["intraday_estimate_status"] == "STALE_PRIOR_SESSION"
    assert state["daily_ledger_relation"] == "QUOTE_SESSION_ALREADY_RECORDED"


def test_snapshot_exposes_session_state_without_mutating_accounting_fields() -> None:
    canonical = _canonical()
    before = deepcopy(canonical)
    snapshot = build_operational_snapshot(
        canonical,
        generated_at="2026-06-27T12:00:00-04:00",
        intraday={
            "provider": "fixture",
            "estimated_nav": 1_004_000.0,
            "estimated_pnl": 100.0,
            "market_data_as_of": "2026-06-26T15:45:00-04:00",
            "covered_tickers": 10,
            "total_tickers": 10,
            "missing_tickers": [],
            "stale_tickers": [],
            "refresh_meta": {"market_session_status": "Closed", "session_date": "2026-06-26"},
        },
    )

    assert canonical == before
    assert snapshot["session_state"]["market_session_status"] == "MARKET_CLOSED_WEEKEND"
    assert snapshot["session_state"]["current_intraday_session"] is None
    assert snapshot["session_state"]["quote_freshness"] == "STALE_PRIOR_SESSION"
    assert snapshot["intraday_estimate"]["written_to_official_ledger"] is False
    assert snapshot["portfolio_daily"] == build_operational_snapshot(before, generated_at="2026-06-27T12:00:00-04:00")["portfolio_daily"]


def test_response_session_state_uses_request_time_and_preserves_artifacts(tmp_path: Path) -> None:
    root = _copy_root(tmp_path)
    snapshot_path = root / "output/operational_snapshot.json"
    base = load_operational_snapshot_for_response(root, now=datetime.fromisoformat("2026-06-27T12:00:00-04:00"))
    before_snapshot = snapshot_path.read_text(encoding="utf-8")

    response = load_operational_snapshot_for_response(
        root,
        now=datetime.fromisoformat("2026-06-27T12:05:00-04:00"),
    )

    assert response["session_state"]["calendar_date"] == "2026-06-27"
    assert response["session_state"]["market_session_status"] == "MARKET_CLOSED_WEEKEND"
    assert response["session_state"]["current_intraday_session"] is None
    assert snapshot_path.read_text(encoding="utf-8") == before_snapshot
    assert response["portfolio_daily"] == base["portfolio_daily"]
    assert response["strategies"] == base["strategies"]


def test_trading_session_module_has_no_specific_weekend_date_literal() -> None:
    source = Path("src/market/trading_session.py").read_text(encoding="utf-8")
    assert "2026-06-27" not in source
