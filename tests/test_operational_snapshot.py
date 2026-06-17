"""Focused operational snapshot, refresh, and decision tests."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.reporting.operational_snapshot import (
    build_operational_snapshot,
    classify_execution_provenance,
    load_operational_snapshot_for_response,
    official_promotion_readiness,
    persist_decision,
    read_operational_intraday_overlay,
    refresh_operational_snapshot,
    snapshot_refresh_lock,
)
from src.reporting.strategy_research_artifacts import load_strategy_research_artifacts


ROOT = Path(__file__).resolve().parents[1]


def _canonical() -> dict:
    return json.loads((ROOT / "dashboard/data/canonical_operational.json").read_text(encoding="utf-8"))


def _copy_root(tmp_path: Path) -> Path:
    target = tmp_path / "workstation"
    (target / "dashboard/data").mkdir(parents=True)
    (target / "dashboard/data/canonical_operational.json").write_text(
        json.dumps(_canonical()), encoding="utf-8"
    )
    return target


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_snapshot_fields_identity_costs_exposure_and_contributor_scale():
    canonical = _canonical()
    snapshot = build_operational_snapshot(canonical, generated_at="2026-06-14T12:00:00+00:00")
    assert snapshot["snapshot_version"] == "3.6.7"
    assert snapshot["official_daily"]["accounting_label"] == "OFFICIAL_DAILY"
    assert snapshot["official_daily"]["latest_official_close_date"] == "2026-06-12"
    assert snapshot["official_daily"]["missing_dates"] == []
    assert snapshot["official_daily"]["blocker"] is None
    assert snapshot["portfolio_daily"][-1]["official_close_date"] == "2026-06-12"
    assert snapshot["intraday_estimate"]["written_to_official_ledger"] is False
    assert snapshot["latest_official_ledger_date"] == "2026-06-11"
    assert snapshot["official_close_as_of"] == "2026-06-12"
    assert snapshot["delayed_estimate_as_of"] is None
    assert snapshot["current_trading_session_date"] is None
    assert snapshot["trading_session_lifecycle"]["state"] == "OFFICIAL_ONLY"
    assert snapshot["trading_session_lifecycle"]["accounting_convention"] == "NEXT_OPEN_TO_OPEN"
    assert snapshot["official_promotion_readiness"]["readiness_state"] == "OFFICIAL_ONLY"
    assert snapshot["official_promotion_readiness"]["can_promote"] is False
    assert snapshot["official_promotion_readiness"]["execute_enabled"] is False
    assert "No current delayed estimate is available" in snapshot["official_promotion_blockers"][0]
    assert snapshot["strategies"][0]["display_id"] == "#COMBINED"
    assert [row["display_id"] for row in snapshot["strategies"][1:-1]] == [f"#{i:06d}" for i in range(1, 17)]
    assert snapshot["strategies"][-1]["display_id"] == "#000018"
    assert all(row["display_name"] != row["internal_id"] for row in snapshot["strategies"])
    assert snapshot["strategies"][0]["display_name"] == "Combined"
    assert snapshot["strategies"][0]["sleeve_weight"] == pytest.approx(1 / 17)
    assert snapshot["strategies"][0]["constituent_count"] == 16
    assert snapshot["strategies"][0]["constituent_equal_weight"] == pytest.approx(1 / 16)
    assert snapshot["strategies"][0]["daily_pnl"] is not None
    assert snapshot["strategies"][0]["cumulative_pnl"] is not None
    assert snapshot["strategies"][0]["current_drawdown"] is not None
    assert snapshot["strategies"][0]["data_status"] == "DERIVED_COMPLETE"
    assert snapshot["strategies"][0]["data_state"] == "DERIVED_COMPLETE"
    assert snapshot["strategies"][0]["current_operational_label"] == "Derived Combined Strategy Ledger"
    assert snapshot["strategies"][0]["execution_type"] == "Derived Combined Strategy Ledger"
    assert snapshot["strategies"][0]["operational_data_source"] == "ordinary strategy operational daily ledgers"
    assert snapshot["strategies"][0]["separate_combined_trade_ledger"] is None
    assert snapshot["strategies"][0]["separate_combined_paper_fills"] is False
    assert snapshot["strategies"][0]["cost_double_count"] is False
    assert snapshot["strategies"][0]["cumulative_cost"] is None
    assert snapshot["strategies"][1]["display_name"] == "Relative Strength 12-1"
    assert snapshot["strategies"][1]["last_rebalance"] == "2026-06-10"
    assert snapshot["strategies"][-1]["daily_pnl"] is None
    assert snapshot["pending_membership"]["effective_from"] == "2026-06-15"
    assert len(snapshot["strategies"]) == 18
    assert sum(row["membership_state"] == "executed" for row in snapshot["strategies"]) == 17
    assert snapshot["strategies"][-1]["display_name"] == "Low Intraday Range & Open-Close Correlation"
    assert snapshot["operational_universe"]["held_ticker_count"] == 222
    assert snapshot["operational_universe"]["operational_pricing_universe_size"] is None
    assert snapshot["strategy_reconciliation"]["daily_pnl_residual"] == pytest.approx(0, abs=1e-8)
    assert snapshot["strategy_reconciliation"]["cumulative_pnl_residual"] == pytest.approx(0, abs=1e-8)
    assert snapshot["cost_reconciliation"]["trade_row_count"] == 1360
    assert snapshot["cost_reconciliation"]["trade_row_total"] == pytest.approx(666.2656485968412)
    assert snapshot["cost_reconciliation"]["strategy_daily_total"] == pytest.approx(666.2656485968412)
    assert snapshot["cost_reconciliation"]["portfolio_daily_total"] == pytest.approx(666.2656485968413)
    assert snapshot["cost_reconciliation"]["trade_to_portfolio_residual"] == pytest.approx(0, abs=1e-8)
    assert snapshot["cost_reconciliation"]["status"] == "RECONCILED"
    assert snapshot["cost_reconciliation"]["excluded_rows"] == 0
    assert snapshot["capital_reconciliation"]["starting_capital_per_sleeve"] == pytest.approx(1_000_000 / 17)
    assert snapshot["capital_reconciliation"]["top_level_active_sleeves"] == 17
    assert snapshot["strategy_entity_inventory"]["ordinary_entities"] == 16
    assert snapshot["strategy_entity_inventory"]["ordinary_operational_ledgers"] == 16
    assert snapshot["strategy_entity_inventory"]["combined"] == 1
    assert snapshot["strategy_entity_inventory"]["pending_candidates"] == 1
    assert snapshot["strategy_entity_inventory"]["total_registry_entities"] == 18
    assert snapshot["strategy_entity_inventory"]["missing_ordinary_ledger"] == []
    assert snapshot["strategy_entity_inventory"]["status"] == "PASS"
    assert snapshot["initial_execution_validation"]["status"] == "RECONSTRUCTED_PAPER_BACKFILL"
    assert snapshot["initial_execution_validation"]["signal_as_of_date"] is None
    selected = snapshot["strategy_cost_reconciliation"]["C3A1_002"]
    assert selected["selected_strategy_trade_rows"] < selected["portfolio_trade_rows"]
    assert selected["selected_strategy_trade_row_cost"] == pytest.approx(selected["selected_strategy_cumulative_cost"])

    for strategy in snapshot["strategies"][1:-1]:
        holdings = [row for row in snapshot["holdings"] if row["strategy_id"] == strategy["internal_id"]]
        trades = [row for row in snapshot["trades"] if row["strategy_id"] == strategy["internal_id"]]
        assert strategy["holdings_count"] == len(holdings)
        assert strategy["long_count"] == sum(float(row["target_weight"]) > 0 for row in holdings)
        assert strategy["short_count"] == sum(float(row["target_weight"]) < 0 for row in holdings)
        assert strategy["gross_exposure"] == pytest.approx(sum(abs(float(row["target_weight"])) for row in holdings))
        assert strategy["net_exposure"] == pytest.approx(sum(float(row["target_weight"]) for row in holdings))
        assert strategy["cumulative_cost"] == pytest.approx(sum(float(row["transaction_cost_amount"]) for row in trades))
        assert strategy["observation_count"] > 1
        assert len([row for row in snapshot["strategy_daily"] if row["strategy_id"] == strategy["internal_id"]]) == strategy["observation_count"]
        history = [row for row in snapshot["strategy_daily"] if row["strategy_id"] == strategy["internal_id"]]
        assert history[0]["beginning_sleeve_nav"] == pytest.approx(1_000_000 / 17)
        assert strategy["current_drawdown"] == pytest.approx(history[-1]["current_drawdown"])
        assert strategy["max_drawdown"] == pytest.approx(min(row["current_drawdown"] for row in history))

    visible = snapshot["top_contributors"] + snapshot["top_detractors"]
    denominator = max(abs(row["daily_pnl"]) for row in visible)
    assert max(row["bar_width_percent"] for row in visible) == pytest.approx(100)
    assert all(row["bar_width_percent"] == pytest.approx(abs(row["daily_pnl"]) / denominator * 100) for row in visible)


def test_paper_execution_fields_use_real_reference_price_and_five_bps_cost():
    snapshot = build_operational_snapshot(_canonical())
    trade = snapshot["trades"][0]
    assert trade["quantity"] == trade["simulated_quantity"]
    assert trade["reference_execution_price"] == trade["simulated_execution_price"]
    assert trade["notional"] == trade["simulated_notional"]
    assert trade["total_cost"] == pytest.approx(trade["notional"] * 0.0005)
    assert (trade["buy_cost"] is None) != (trade["sell_cost"] is None)
    assert trade["execution_provenance"] == "INVALID_EXECUTION_RECORD"
    assert trade["status"] == "Paper Provenance Pending"
    assert trade["fill_type"] == "No Verified Paper Fill"
    assert trade["brokerage_fill"] == "No Live Brokerage Fill"


def test_refresh_changes_snapshot_preserves_official_ledger_and_failure_keeps_good(tmp_path: Path):
    root = _copy_root(tmp_path)
    canonical_path = root / "dashboard/data/canonical_operational.json"
    before_hash = _digest(canonical_path)
    base = load_operational_snapshot_for_response(root)
    base_hash = _digest(root / "output/operational_snapshot.json")

    def fake_fetch(tickers, **kwargs):
        return {
            "provider": "test-delayed",
            "rows": [
                {
                    "ticker": ticker,
                    "source_ticker": ticker,
                    "close": 101.0,
                    "intraday_return_from_open": 0.01,
                    "observation_ts_et": "2026-06-14T12:00:00-04:00",
                }
                for ticker in tickers
            ],
            "missing_tickers": [],
            "stale_tickers": [],
            "latest_observation_ts_et": "2026-06-14T12:00:00-04:00",
        }

    first = refresh_operational_snapshot(root, fetch_fn=fake_fetch)
    assert first["ok"] is True
    assert first["data_freshness"] == "DELAYED"
    assert first["intraday_runtime_status"] == "LOADED"
    assert first["intraday_overlay_available"] is True
    assert read_operational_intraday_overlay(root)["schema_version"] == "intraday_overlay_v1"
    assert _digest(root / "output/operational_snapshot.json") == base_hash
    first_id = first["snapshot_id"]
    second = refresh_operational_snapshot(root, fetch_fn=fake_fetch)
    assert second["snapshot_id"] != first_id
    assert _digest(canonical_path) == before_hash

    def fail_fetch(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    failed = refresh_operational_snapshot(root, fetch_fn=fail_fetch)
    assert failed["ok"] is False
    assert failed["refresh_status"] == "ERROR"
    assert failed["snapshot_id"] == base["snapshot_id"]
    assert _digest(root / "output/operational_snapshot.json") == base_hash
    overlay = read_operational_intraday_overlay(root)
    assert overlay["status"] == "ERROR"
    assert "provider unavailable" in overlay["errors"][0]
    merged = load_operational_snapshot_for_response(root)
    assert merged["intraday_runtime_status"] == "ERROR"
    assert merged["portfolio_daily"] == base["portfolio_daily"]


def test_intraday_refresh_reprices_holdings_strategies_combined_and_contributors(tmp_path: Path):
    root = _copy_root(tmp_path)

    def fake_fetch(rate: float, ts: str):
        def _fetch(tickers, **kwargs):
            return {
                "provider": "test-delayed",
                "rows": [
                    {
                        "ticker": ticker,
                        "source_ticker": ticker,
                        "close": 100.0 * (1.0 + rate),
                        "intraday_return_from_open": rate,
                        "observation_ts_et": ts,
                    }
                    for ticker in tickers
                ],
                "missing_tickers": [],
                "stale_tickers": [],
                "latest_observation_ts_et": ts,
                "latest_completed_bar_ts_et": ts,
            }
        return _fetch

    first = refresh_operational_snapshot(root, fetch_fn=fake_fetch(0.001, "2026-06-15T10:00:00-04:00"))
    second = refresh_operational_snapshot(root, fetch_fn=fake_fetch(0.002, "2026-06-15T10:05:00-04:00"))
    assert first["ok"] is True
    assert second["ok"] is True
    assert second["snapshot_id"] != first["snapshot_id"]
    assert second["intraday_runtime_status"] == "LOADED"
    assert second["intraday_estimate"]["written_to_official_ledger"] is False
    assert second["portfolio_daily"] == first["portfolio_daily"]
    assert second["official_daily"]["latest_official_close_date"] == "2026-06-12"
    assert second["intraday_estimate"]["estimated_pnl"] == pytest.approx(first["intraday_estimate"]["estimated_pnl"] * 2)
    assert second["intraday_estimate"]["estimated_nav"] == pytest.approx(
        second["official_daily"]["nav"] + second["intraday_estimate"]["estimated_pnl"]
    )
    ordinary = [
        row for row in second["strategies"]
        if row["membership_state"] == "executed" and row["internal_id"] != "COMBINED_PORTFOLIO"
    ]
    combined = next(row for row in second["strategies"] if row["internal_id"] == "COMBINED_PORTFOLIO")
    wq = next(row for row in second["strategies"] if row["internal_id"] == "WQ_ALPHA_018")
    assert all(row["estimated_daily_pnl"] is not None for row in ordinary)
    assert all(row["intraday_estimated_pnl"] == row["estimated_daily_pnl"] for row in ordinary)
    assert all(row["intraday_estimated_nav"] == pytest.approx(row["ending_nav"] + row["intraday_estimated_pnl"]) for row in ordinary)
    assert all(row["intraday_estimate_unavailable_reason"] is None for row in ordinary)
    assert all(row["latest_delayed_price_as_of"] == "2026-06-15T10:05:00-04:00" for row in ordinary)
    assert all(row["price_coverage"]["status"] == "COMPLETE" for row in ordinary)
    assert combined["estimated_daily_pnl"] == pytest.approx(
        sum(row["estimated_daily_pnl"] for row in ordinary) / len(ordinary)
    )
    assert combined["estimated_strategy_nav"] == pytest.approx(combined["ending_nav"] + combined["estimated_daily_pnl"])
    assert combined["intraday_estimated_pnl"] == pytest.approx(combined["estimated_daily_pnl"])
    assert combined["intraday_estimated_nav"] == pytest.approx(combined["estimated_strategy_nav"])
    assert combined["data_state"] == "DERIVED_COMPLETE"
    assert combined["daily_pnl"] is not None
    assert combined["cumulative_pnl"] is not None
    assert combined["current_drawdown"] is not None
    assert wq["current_operational_status"] == "PRE_OPERATIONAL"
    assert wq["estimated_daily_pnl"] is None
    assert wq["intraday_estimated_pnl"] is None
    assert wq["intraday_estimated_nav"] is None
    assert wq["intraday_estimate_unavailable_reason"] == "Pre-operational"
    visible = second["top_contributors"] + second["top_detractors"]
    denominator = max(abs(row["daily_pnl"]) for row in visible)
    assert denominator > 0
    assert all(row["contribution_basis"] == "INTRADAY_ESTIMATE" for row in visible)
    assert all(row["bar_width_percent"] == pytest.approx(abs(row["daily_pnl"]) / denominator * 100) for row in visible)


def test_clean_base_snapshot_without_overlay_is_official_only_and_does_not_create_intraday_point(tmp_path: Path):
    root = _copy_root(tmp_path)
    snapshot = load_operational_snapshot_for_response(root, scheduler_enabled=False)
    assert snapshot["intraday_runtime_status"] == "NOT_LOADED"
    assert snapshot["intraday_overlay_available"] is False
    assert snapshot["intraday_scheduler_enabled"] is False
    assert snapshot["trading_session_lifecycle"]["state"] == "OFFICIAL_ONLY"
    assert snapshot["intraday_estimate"]["estimated_nav"] is None
    assert snapshot["portfolio_daily"][-1]["date"] == "2026-06-11"
    assert not any(row["date"] == "2026-06-15" for row in snapshot["portfolio_daily"])


def test_stale_intraday_overlay_is_not_merged_into_official_snapshot(tmp_path: Path):
    root = _copy_root(tmp_path)
    base = load_operational_snapshot_for_response(root)
    overlay_path = root / "output/operational_intraday_overlay.json"
    overlay_path.write_text(json.dumps({
        "schema_version": "intraday_overlay_v1",
        "generated_at": "2026-06-15T10:00:00+00:00",
        "status": "LOADED",
        "provider": "test-delayed",
        "current_trading_session_date": "2026-06-15",
        "market_session_status": "Open",
        "delayed_estimate_as_of": "2026-06-15T10:00:00-04:00",
        "estimated_nav": 1_004_500.0,
        "estimated_pnl": 40.0,
        "estimated_return": 0.00004,
        "price_coverage": {"covered": 222, "total": 222},
        "strategy_estimates": [],
        "top_contributors": [],
        "top_detractors": [],
        "errors": [],
        "stale_after_seconds": 60,
    }), encoding="utf-8")
    merged = load_operational_snapshot_for_response(
        root,
        now=datetime.fromisoformat("2026-06-15T10:05:00+00:00"),
    )
    assert merged["intraday_runtime_status"] == "STALE"
    assert merged["intraday_overlay_available"] is False
    assert merged["intraday_estimate"]["estimated_nav"] is None
    assert merged["portfolio_daily"] == base["portfolio_daily"]


def test_intraday_session_lifecycle_blocks_unpromoted_eod_estimate_without_fabricating_official_row():
    snapshot = build_operational_snapshot(
        _canonical(),
        intraday={
            "provider": "test-delayed",
            "estimated_nav": 1_004_500.0,
            "estimated_pnl": 40.0,
            "market_data_as_of": "2026-06-15T16:05:00-04:00",
            "covered_tickers": 222,
            "total_tickers": 222,
            "missing_tickers": [],
            "stale_tickers": [],
            "refresh_meta": {
                "data_freshness": "DELAYED",
                "market_session_status": "After-hours",
                "session_date": "2026-06-15",
            },
        },
    )
    lifecycle = snapshot["trading_session_lifecycle"]
    assert lifecycle["state"] == "EOD_PENDING_OFFICIAL_PROMOTION"
    assert lifecycle["state_label"] == "EOD estimate pending official ledger promotion"
    assert snapshot["latest_official_ledger_date"] == "2026-06-11"
    assert snapshot["official_close_as_of"] == "2026-06-12"
    assert snapshot["delayed_estimate_as_of"] == "2026-06-15T16:05:00-04:00"
    assert snapshot["current_trading_session_date"] == "2026-06-15"
    assert snapshot["intraday_estimate"]["written_to_official_ledger"] is False
    assert snapshot["portfolio_daily"][-1]["date"] == "2026-06-11"
    assert not any(row["date"] == "2026-06-15" for row in snapshot["portfolio_daily"])
    assert any("Official portfolio_daily row is not present" in item for item in lifecycle["official_promotion_blockers"])
    assert any("NEXT_OPEN_TO_OPEN requires the next-open return endpoint" in item for item in lifecycle["official_promotion_blockers"])
    assert any("Missing complete ordinary strategy daily rows" in item for item in lifecycle["official_promotion_blockers"])
    assert any("Missing paper fill rows" in item for item in lifecycle["official_promotion_blockers"])
    assert any("Missing position rows" in item for item in lifecycle["official_promotion_blockers"])
    assert "delayed estimates are never written to the official ledger" in lifecycle["promotion_condition"]
    readiness = snapshot["official_promotion_readiness"]
    assert readiness["readiness_state"] == "EOD_PENDING_OFFICIAL_PROMOTION"
    assert readiness["can_promote"] is False
    assert readiness["target_ledger_date"] == "2026-06-15"
    assert readiness["required_return_endpoint"] == "next trading open after 2026-06-15"
    assert readiness["accounting_convention"] == "NEXT_OPEN_TO_OPEN"
    assert any("NEXT_OPEN_TO_OPEN requires the next-open return endpoint" in item for item in readiness["blockers"])


def test_official_promotion_readiness_allows_ready_only_without_input_blockers():
    readiness = official_promotion_readiness(
        {
            "trading_session_lifecycle": {
                "state": "EOD_PENDING_OFFICIAL_PROMOTION",
                "latest_official_ledger_date": "2026-06-11",
                "official_close_as_of": "2026-06-12",
                "delayed_estimate_as_of": "2026-06-15T16:05:00-04:00",
                "current_trading_session_date": "2026-06-15",
                "market_session_status": "After-hours",
                "accounting_convention": "NEXT_OPEN_TO_OPEN",
                "official_promotion_blockers": [
                    "Official portfolio_daily row is not present for the current trading session.",
                    "Operational snapshot must be rebuilt after official ledger generation.",
                ],
            }
        }
    )
    assert readiness["readiness_state"] == "READY_FOR_PROMOTION"
    assert readiness["can_promote"] is True
    assert readiness["target_ledger_date"] == "2026-06-15"
    assert readiness["recommended_command"].endswith("--target-date 2026-06-15 --dry-run")
    assert readiness["execute_enabled"] is False


def test_official_promoted_readiness_does_not_duplicate_estimate():
    readiness = official_promotion_readiness(
        {
            "trading_session_lifecycle": {
                "state": "OFFICIAL_PROMOTED",
                "latest_official_ledger_date": "2026-06-15",
                "official_close_as_of": "2026-06-16",
                "delayed_estimate_as_of": "2026-06-15T16:05:00-04:00",
                "current_trading_session_date": "2026-06-15",
                "market_session_status": "After-hours",
                "accounting_convention": "NEXT_OPEN_TO_OPEN",
                "official_promotion_blockers": [],
            }
        }
    )
    assert readiness["readiness_state"] == "OFFICIAL_PROMOTED"
    assert readiness["can_promote"] is False
    app = (ROOT / "dashboard/foundation-app.js").read_text(encoding="utf-8")
    assert '["INTRADAY_ESTIMATE","EOD_PENDING_OFFICIAL_PROMOTION"].includes(lifecycle(c).state)' in app


def test_missing_delayed_prices_write_error_overlay_without_mutating_official_snapshot(tmp_path: Path):
    root = _copy_root(tmp_path)
    base = load_operational_snapshot_for_response(root)
    base_hash = _digest(root / "output/operational_snapshot.json")
    baseline = refresh_operational_snapshot(
        root,
        fetch_fn=lambda tickers, **kwargs: {
            "provider": "test-delayed",
            "rows": [
                {
                    "ticker": ticker,
                    "source_ticker": ticker,
                    "close": 101.0,
                    "intraday_return_from_open": 0.01,
                    "observation_ts_et": "2026-06-15T10:00:00-04:00",
                }
                for ticker in tickers
            ],
            "missing_tickers": [],
            "stale_tickers": [],
            "latest_observation_ts_et": "2026-06-15T10:00:00-04:00",
            "latest_completed_bar_ts_et": "2026-06-15T10:00:00-04:00",
        },
    )

    failed = refresh_operational_snapshot(
        root,
        fetch_fn=lambda tickers, **kwargs: {
            "provider": "test-delayed",
            "rows": [],
            "missing_tickers": tickers,
            "stale_tickers": [],
            "latest_observation_ts_et": None,
        },
    )
    snapshot = load_operational_snapshot_for_response(root)
    overlay = read_operational_intraday_overlay(root)
    assert failed["ok"] is False
    assert baseline["intraday_runtime_status"] == "LOADED"
    assert _digest(root / "output/operational_snapshot.json") == base_hash
    assert snapshot["snapshot_id"] == base["snapshot_id"]
    assert snapshot["intraday_runtime_status"] == "ERROR"
    assert snapshot["data_freshness"] == "OFFICIAL_CLOSE"
    assert snapshot["intraday_estimate"]["estimated_pnl"] is None
    assert overlay["status"] == "ERROR"
    assert overlay["estimated_pnl"] is None


def test_overlapping_refresh_is_blocked(tmp_path: Path):
    root = _copy_root(tmp_path)
    lock = root / "output/operational_snapshot.lock"
    with snapshot_refresh_lock(lock) as acquired:
        assert acquired
        blocked = refresh_operational_snapshot(root, fetch_fn=lambda *args, **kwargs: {})
        assert blocked["error"] == "refresh_already_in_progress"


def test_decisions_persist_without_rewriting_historical_ledger(tmp_path: Path):
    root = _copy_root(tmp_path)
    canonical_path = root / "dashboard/data/canonical_operational.json"
    before_hash = _digest(canonical_path)
    approve = persist_decision(root, {"action": "APPROVE", "reviewer": "RM", "rationale": "Reviewed"})
    assert approve["execution_authorized"] is False
    assert approve["environment"] == "OPERATIONAL"
    weights = {row["internal_id"]: 1 / 18 for row in _canonical()["strategies"]}
    modify = persist_decision(
        root,
        {"action": "MODIFY", "reviewer": "RM", "rationale": "Equal future sleeves", "new_proposed_weights": weights},
    )
    assert modify["action"] == "MODIFY"
    assert len(json.loads((root / "output/command_center_decisions.json").read_text())) == 2
    assert _digest(canonical_path) == before_hash


def test_strategy_monitor_snapshot_separates_held_coverage_and_full_universe():
    snapshot = build_operational_snapshot(
        _canonical(),
        operational_pricing_universe_size=301,
        generated_at="2026-06-14T12:00:00+00:00",
    )
    universe = snapshot["operational_universe"]
    assert universe["held_ticker_count"] == 222
    assert universe["current_price_covered_ticker_count"] is None
    assert universe["operational_pricing_universe_size"] == 301
    assert universe["held_ticker_coverage_scope"] != universe["pricing_universe_scope"]


def test_connected_historical_research_uses_deployable_series_without_leakage():
    evidence = load_strategy_research_artifacts(ROOT, _canonical()["strategies"])
    connected = evidence["C3A1_002"]
    neighbor = evidence["C3A1_003"]
    assert connected["research_status"] == "CONNECTED"
    assert connected["research_metrics"]["observation_count"] == 2120
    assert connected["research_metrics"]["rolling_63d_sharpe_latest"] is not None
    assert len(connected["research_series"]["net_equity"]) == 2120
    assert "D:/" not in connected["evidence_artifact"]
    assert neighbor["research_status"] == "CONNECTED"
    assert neighbor["research_metrics"]["observation_count"] == 2120
    assert neighbor["research_series"]["net_equity"] != connected["research_series"]["net_equity"]


def test_batch_research_mapping_covers_configured_strategies_and_combined_excludes_pending_wq():
    mapping = json.loads((ROOT / "data/config/strategy_research_mapping.json").read_text(encoding="utf-8"))
    configured = [row["internal_id"] for row in _canonical()["strategies"]]
    assert list(mapping["entries"]) == configured
    assert all(
        entry["research_summary_artifact"].startswith("data/research/canonical/")
        and entry["research_return_series_artifact"].startswith("data/research/canonical/")
        for entry in mapping["entries"].values()
    )
    assert mapping["entries"]["WQ_ALPHA_018"]["mapping_status"] == "CONNECTED_RESEARCH_ONLY"

    combined_provenance = json.loads(
        (ROOT / "data/research/canonical/COMBINED_PORTFOLIO/provenance.json").read_text(encoding="utf-8")
    )
    assert "COMBINED_PORTFOLIO" not in combined_provenance["member_internal_ids"]
    assert "WQ_ALPHA_018" not in combined_provenance["member_internal_ids"]
    assert len(combined_provenance["member_internal_ids"]) == 16
    assert combined_provenance["aligned_observations"] > 1000
    coverage = (ROOT / "docs/reviews/RESEARCH_ARTIFACT_COVERAGE.md").read_text(encoding="utf-8")
    assert "No backtests were rerun." in coverage
    assert "CONNECTED_COMPOSITE" in coverage


def test_execution_provenance_never_fabricates_missing_signal_dates():
    snapshot = build_operational_snapshot(_canonical())
    reconstructed = [
        row for row in snapshot["strategy_daily"]
        if row["execution_provenance"] == "RECONSTRUCTED_PAPER_BACKFILL"
    ]
    assert reconstructed
    assert all(row.get("signal_date") is None for row in reconstructed)
    assert all(row["execution_provenance_label"] == "Reconstructed Paper Record / Retrospective Paper Backfill" for row in reconstructed)
    assert snapshot["execution_provenance"]["strategy_record_counts"]["VERIFIED_SHADOW_EXECUTION"] == 0
    assert snapshot["execution_provenance"]["portfolio_record_counts"]["VERIFIED_SHADOW_EXECUTION"] == 0


def test_verified_execution_requires_complete_provenance():
    complete = {
        "signal_as_of_date": "2026-06-09",
        "data_cutoff": "2026-06-09",
        "target_effective_date": "2026-06-10",
        "execution_date": "2026-06-10",
        "execution_convention": "NEXT_OPEN_TO_OPEN",
        "execution_price_source": "PREDEFINED_OPEN_REFERENCE",
    }
    assert classify_execution_provenance(complete) == "VERIFIED_SHADOW_EXECUTION"
    for field in complete:
        incomplete = complete | {field: None}
        assert classify_execution_provenance(incomplete) == "INVALID_EXECUTION_RECORD"


def test_strategy_effective_dates_are_specific_and_pre_effective_rows_are_excluded():
    canonical = _canonical()
    canonical["strategy_daily"].append({
        "strategy_id": "WQ_ALPHA_018",
        "date": "2026-06-10",
        "gross_return": 0.0,
        "transaction_cost": 0.0,
        "record_label": "FORWARD_RAW_SHADOW_LIVE",
    })
    snapshot = build_operational_snapshot(canonical)
    active = next(row for row in snapshot["strategies"] if row["internal_id"] == "C3A1_002")
    pending = next(row for row in snapshot["strategies"] if row["internal_id"] == "WQ_ALPHA_018")
    assert active["strategy_effective_date"] == "2026-06-04"
    assert pending["strategy_effective_date"] == "2026-06-15"
    assert pending["current_operational_status"] == "PRE_OPERATIONAL"
    assert pending["current_operational_label"] == "APPROVED_PENDING / PRE_OPERATIONAL"
    assert pending["ending_nav"] is None
    assert pending["daily_pnl"] is None
    assert not any(row["strategy_id"] == "WQ_ALPHA_018" for row in snapshot["strategy_daily"])


def test_portfolio_start_dates_are_derived_and_accounting_is_unchanged():
    canonical = _canonical()
    canonical["portfolio_daily"][0]["date"] = "2026-06-03"
    snapshot = build_operational_snapshot(canonical)
    assert snapshot["portfolio_dates"]["reconstructed_portfolio_start_date"] == "2026-06-03"
    assert snapshot["portfolio_dates"]["verified_shadow_portfolio_start_date"] is None
    assert snapshot["portfolio_summary"]["verified_shadow_start_label"] == "Not Yet Established"
    assert snapshot["capital_reconciliation"]["starting_capital_per_sleeve"] == pytest.approx(1_000_000 / 17)
    assert snapshot["cost_reconciliation"]["portfolio_daily_total"] == pytest.approx(666.2656485968413)


def test_wq_admission_requires_canonical_execution_evidence_and_keeps_combined_n16():
    snapshot = build_operational_snapshot(_canonical())
    gate = snapshot["wq_admission_gate"]
    wq = next(row for row in snapshot["strategies"] if row["internal_id"] == "WQ_ALPHA_018")
    combined = next(row for row in snapshot["strategies"] if row["internal_id"] == "COMBINED_PORTFOLIO")

    assert gate["status"] == "APPROVED_PENDING"
    assert gate["current_operational_status"] == "PRE_OPERATIONAL"
    assert gate["admitted_to_combined"] is False
    assert gate["combined_rebalance_allowed"] is False
    assert gate["current_executed_count"] == 17
    assert gate["approved_pending_count"] == 1
    assert gate["combined_constituents"] == 16
    assert gate["evidence"]["approval_record"] is True
    assert gate["evidence"]["canonical_trade_rows"] == 0
    assert gate["evidence"]["canonical_position_rows"] == 0
    assert gate["evidence"]["verified_execution_rows"] == 0
    assert gate["blockers"] == [
        "Missing canonical signal date",
        "Missing target rows",
        "Missing paper fill rows",
        "Missing position rows",
        "Missing verified execution provenance",
    ]
    assert wq["admission_gate"]["exact_blocker"] == gate["exact_blocker"]
    assert wq["current_operational_status"] == "PRE_OPERATIONAL"
    assert wq["daily_pnl"] is None
    assert wq["ending_nav"] is None
    assert combined["constituent_count"] == 16


def test_risk_factor_big_table_is_data_driven_and_preserves_status_semantics():
    snapshot = build_operational_snapshot(_canonical())
    rows = snapshot["risk_factor_big_table"]
    by_id = {row["strategy_id"]: row for row in rows}

    assert len(rows) == len(snapshot["strategies"])
    assert {row["strategy_id"] for row in rows} == {row["internal_id"] for row in snapshot["strategies"]}
    assert by_id["COMBINED_PORTFOLIO"]["sleeve_type"] == "Composite"
    assert by_id["COMBINED_PORTFOLIO"]["primary_status"] == "Active Composite"
    assert by_id["COMBINED_PORTFOLIO"]["evidence_artifact_source"] == "ordinary strategy operational daily ledgers"
    assert by_id["WQ_ALPHA_018"]["sleeve_type"] == "Pending"
    assert by_id["WQ_ALPHA_018"]["primary_status"] == "APPROVED_PENDING / PRE_OPERATIONAL"
    assert by_id["WQ_ALPHA_018"]["nav"] is None
    assert by_id["WQ_ALPHA_018"]["daily_pnl"] is None
    assert by_id["WQ_ALPHA_018"]["daily_return"] is None


def test_risk_factor_big_table_missing_factor_metadata_is_not_zero_filled():
    snapshot = build_operational_snapshot(_canonical())

    for row in snapshot["risk_factor_big_table"]:
        assert row["factor_exposure_summary"] == "Missing Metadata"
        assert row["market_exposure"] == "Missing Metadata"
        assert row["size_exposure"] == "Missing Metadata"
        assert row["value_exposure"] == "Missing Metadata"
        assert row["momentum_exposure"] == "Missing Metadata"
        assert row["quality_exposure"] == "Missing Metadata"
        assert row["volatility_exposure"] == "Missing Metadata"
        assert row["liquidity_exposure"] == "Missing Metadata"
        assert "Factor metadata missing" in row["missing_data_warning"]
        assert row["position_source"] == "committed_shadow_holdings"
        assert row["legacy_artifact_position_estimate_authoritative"] is False
        assert "no live brokerage positions or fills" in row["position_source_disclosure"]


def test_risk_factor_market_proxy_table_is_snapshot_bound_without_live_market_fetch():
    snapshot = build_operational_snapshot(_canonical())
    rows = snapshot["risk_factor_market_proxy_table"]
    by_id = {row["strategy_id"]: row for row in rows}

    assert len(rows) == len(snapshot["strategies"])
    assert {row["strategy_id"] for row in rows} == {row["internal_id"] for row in snapshot["strategies"]}
    assert by_id["COMBINED_PORTFOLIO"]["sleeve_type"] == "Composite"
    assert by_id["COMBINED_PORTFOLIO"]["primary_status"] == "Active Composite"
    assert by_id["COMBINED_PORTFOLIO"]["proxy_status"] == "Constituent-Derived Pending"
    assert by_id["WQ_ALPHA_018"]["sleeve_type"] == "Pending"
    assert by_id["WQ_ALPHA_018"]["primary_status"] == "APPROVED_PENDING / PRE_OPERATIONAL"
    assert by_id["WQ_ALPHA_018"]["spy_beta"] == "Not Applicable"
    assert by_id["WQ_ALPHA_018"]["realized_vol_20d"] == "Not Applicable"
    assert by_id["WQ_ALPHA_018"]["current_weight"] is None
    assert "Delayed yfinance overlay" in by_id["COMBINED_PORTFOLIO"]["evidence_source"]
    assert "Not live brokerage" in by_id["COMBINED_PORTFOLIO"]["evidence_source"]
    assert "Not live real-time market data" in by_id["COMBINED_PORTFOLIO"]["evidence_source"]


def test_market_proxy_missing_values_are_statuses_not_zeroes():
    snapshot = build_operational_snapshot(_canonical())

    for row in snapshot["risk_factor_market_proxy_table"]:
        assert row["spy_beta"] != 0
        assert row["spy_correlation"] != 0
        assert row["realized_vol_20d"] != 0
        assert row["realized_vol_60d"] != 0
        assert row["spy_beta"] in {"Insufficient History", "Not Applicable"}
        assert row["spy_correlation"] in {"Insufficient History", "Not Applicable"}
        assert "Not a validated Barra / institutional factor model" in row["warnings"]


def test_new_strategy_gets_market_proxy_row_with_pending_data_without_frontend_hardcode():
    canonical = _canonical()
    new_strategy = deepcopy(canonical["strategies"][1])
    new_strategy.update(
        {
            "internal_id": "MOCK_NEW_STRATEGY",
            "display_id": "#009999",
            "name": "Mock New Strategy",
            "membership_state": "executed",
            "data_status": "DATA_PENDING",
            "current_weight": None,
        }
    )
    canonical["strategies"].append(new_strategy)

    snapshot = build_operational_snapshot(canonical)
    row = next(row for row in snapshot["risk_factor_market_proxy_table"] if row["strategy_id"] == "MOCK_NEW_STRATEGY")

    assert row["display_id"] == "#009999"
    assert row["history_observation_count"] == 0
    assert row["holdings_count"] == 0
    assert row["spy_beta"] == "Insufficient History"
    assert row["realized_vol_20d"] == "Insufficient History"
    assert row["top_holding_concentration"] == "Not Available"
    assert row["proxy_status"] == "Insufficient History"


def _market_proxy_cache_for_strategy(canonical: dict, strategy_id: str) -> dict:
    holdings = [
        row
        for row in canonical["holdings"]
        if row["strategy_id"] == strategy_id and row["date"] == max(item["date"] for item in canonical["holdings"])
    ]
    tickers = [row["ticker"] for row in holdings[:3]]
    return {
        "metadata": {
            "generated_at": "2026-06-16T20:00:00+00:00",
            "provider": "yfinance",
            "delayed_market_data": True,
            "not_live_market_data": True,
            "failed_tickers": [],
        },
        "benchmark": {
            "symbol": "SPY",
            "return_series": [
                {"date": (datetime(2026, 6, 1) + timedelta(days=i)).date().isoformat(), "return": 0.001 + i * 0.0001}
                for i in range(24)
            ],
            "return_count": 24,
            "latest_date": "2026-06-24",
            "status": "LOADED",
        },
        "holdings_market_proxy": [
            {
                "ticker": ticker,
                "price_history_coverage": 64,
                "latest_price": 100 + index,
                "avg_dollar_volume_20d": 25_000_000 + index * 1_000_000,
                "momentum_20d": 0.02 + index * 0.01,
                "momentum_63d": 0.05 + index * 0.01,
                "sector": "Technology" if index < 2 else "Industrials",
                "status": "LOADED",
            }
            for index, ticker in enumerate(tickers)
        ],
    }


def test_market_proxy_cache_populates_real_holding_metrics_without_live_yfinance():
    canonical = _canonical()
    strategy_id = next(
        row["internal_id"]
        for row in canonical["strategies"]
        if row["membership_state"] == "executed" and row["internal_id"] != "COMBINED_PORTFOLIO"
    )
    cache = _market_proxy_cache_for_strategy(canonical, strategy_id)

    snapshot = build_operational_snapshot(canonical, market_proxy_cache=cache)
    row = next(row for row in snapshot["risk_factor_market_proxy_table"] if row["strategy_id"] == strategy_id)

    assert row["momentum_20d"] is not None
    assert row["momentum_20d"] != "Coverage Missing"
    assert row["momentum_63d"] is not None
    assert row["liquidity_score"] == "Medium"
    assert row["weighted_avg_dollar_volume"] is not None
    assert row["sector_top_exposure"].startswith("Technology:")
    assert row["top_holding_concentration"] is not None


def test_spy_beta_and_correlation_require_overlap_and_load_from_cache_when_sufficient():
    canonical = _canonical()
    strategy_id = next(
        row["internal_id"]
        for row in canonical["strategies"]
        if row["membership_state"] == "executed" and row["internal_id"] != "COMBINED_PORTFOLIO"
    )
    canonical["strategy_daily"] = [row for row in canonical["strategy_daily"] if row["strategy_id"] != strategy_id]
    start = datetime(2026, 6, 1)
    for i in range(24):
        spy_return = 0.001 + i * 0.0001
        canonical["strategy_daily"].append(
            {
                "date": (start + timedelta(days=i)).date().isoformat(),
                "return_end_date": (start + timedelta(days=i)).date().isoformat(),
                "strategy_id": strategy_id,
                "strategy_name": strategy_id,
                "gross_return": spy_return * 1.5,
                "transaction_cost": 0.0,
                "turnover": 0.0,
                "record_label": "RETROSPECTIVE_PAPER_BACKFILL",
                "validation_status": "VALIDATED",
                "execution_enabled": False,
                "live_allocation_approved": False,
            }
        )
    cache = _market_proxy_cache_for_strategy(canonical, strategy_id)

    loaded = build_operational_snapshot(canonical, market_proxy_cache=cache)
    loaded_row = next(row for row in loaded["risk_factor_market_proxy_table"] if row["strategy_id"] == strategy_id)
    assert loaded_row["spy_beta"] == pytest.approx(1.5)
    assert loaded_row["spy_correlation"] == pytest.approx(1.0)
    assert loaded_row["realized_vol_20d"] != "Insufficient History"

    cache["benchmark"]["return_series"] = cache["benchmark"]["return_series"][:5]
    insufficient = build_operational_snapshot(canonical, market_proxy_cache=cache)
    insufficient_row = next(row for row in insufficient["risk_factor_market_proxy_table"] if row["strategy_id"] == strategy_id)
    assert insufficient_row["spy_beta"] == "Insufficient History"
    assert insufficient_row["spy_correlation"] == "Insufficient History"


def test_refresh_writes_optional_market_proxy_cache_from_mock_price_history(tmp_path: Path):
    root = _copy_root(tmp_path)
    price_dates = [(datetime(2026, 4, 1) + timedelta(days=i)).date().isoformat() for i in range(70)]

    def fake_fetch(tickers, **kwargs):
        history = [
            {
                "date": date,
                "ticker": ticker,
                "close": 100 + index + offset,
                "volume": 1_000_000 + offset,
                "sector": "Technology",
            }
            for ticker in [*tickers[:2], "SPY"]
            for offset, date in enumerate(price_dates)
            for index in [0 if ticker == "SPY" else 1]
        ]
        return {
            "provider": "yfinance",
            "rows": [
                {
                    "ticker": ticker,
                    "source_ticker": ticker,
                    "close": 101.0,
                    "intraday_return_from_open": 0.01,
                    "observation_ts_et": "2026-06-16T12:00:00-04:00",
                }
                for ticker in tickers
            ],
            "daily_price_history": history,
            "missing_tickers": [],
            "stale_tickers": [],
            "latest_observation_ts_et": "2026-06-16T12:00:00-04:00",
            "latest_completed_bar_ts_et": "2026-06-16T12:00:00-04:00",
        }

    result = refresh_operational_snapshot(root, fetch_fn=fake_fetch)
    cache_path = root / "dashboard/data/risk_factor_market_proxy_cache.json"

    assert result["ok"] is True
    assert cache_path.exists()
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cache["metadata"]["provider"] == "yfinance"
    assert cache["metadata"]["delayed_market_data"] is True
    assert cache["metadata"]["not_live_market_data"] is True
    assert cache["benchmark"]["symbol"] == "SPY"
    assert cache["benchmark"]["return_count"] >= 20
