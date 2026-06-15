"""Focused tests for the Phase 1 canonical contract and shared UI shell."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.reporting.canonical_frontend_contract import (
    CanonicalContractError,
    build_canonical_frontend_contract,
    validate_canonical_frontend_contract,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "dashboard/data/shadow_live_bundle.json"
CONTRACT_PATH = ROOT / "dashboard/data/canonical_operational.json"


def source_bundle() -> dict:
    return json.loads(SOURCE_PATH.read_text(encoding="utf-8"))


def contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_committed_contract_matches_builder_and_has_required_sections():
    built = build_canonical_frontend_contract(source_bundle())
    assert built == contract()
    validate_canonical_frontend_contract(built)
    assert set(
        (
            "portfolio_summary",
            "membership_timeline",
            "strategies",
            "portfolio_daily",
            "strategy_daily",
            "holdings",
            "trades",
            "operational_status",
            "alerts",
            "pending_membership",
        )
    ).issubset(built)


def test_no_legacy_proxy_or_old_allocation_model_enters_contract():
    data = contract()
    serialized = json.dumps(data)
    internal_ids = {row["internal_id"] for row in data["strategies"]}
    assert not any(strategy_id.startswith(("STRAT_", "PROTO_", "CAND_")) for strategy_id in internal_ids)
    assert "dashboard_artifact.json" not in serialized
    assert "monitored_20" not in serialized.lower()
    assert "allocated_10" not in serialized.lower()
    assert "target_weight" not in data["strategies"][0]
    assert all(state["equal_weight"] != 0.10 for state in data["membership_timeline"])


def test_strategy_identifiers_are_stable_and_names_remain_separate():
    strategies = contract()["strategies"]
    assert strategies[0]["internal_id"] == "COMBINED_PORTFOLIO"
    assert strategies[0]["display_id"] == "#COMBINED"
    assert [row["display_id"] for row in strategies[1:-1]] == [f"#{index:06d}" for index in range(1, 17)]
    assert all(row["internal_id"] != row["name"] for row in strategies)
    assert strategies[-1]["internal_id"] == "WQ_ALPHA_018"
    assert strategies[-1]["display_id"] == "#000018"


def test_missing_values_remain_missing_and_display_only_normalizes_negative_zero():
    data = contract()
    pending = next(row for row in data["strategies"] if row["internal_id"] == "WQ_ALPHA_018")
    assert pending["daily_pnl"] is None
    assert pending["cumulative_return"] is None
    assert data["portfolio_daily"][-1]["current_drawdown"] is None

    components = (ROOT / "dashboard/foundation-components.js").read_text(encoding="utf-8")
    assert "Object.is(Number(value), -0) ? 0 : Number(value)" in components
    assert 'value == null || !Number.isFinite(Number(value))' in components


def test_membership_timeline_supports_combined_as_17th_then_wq_as_18th_sleeve():
    timeline = contract()["membership_timeline"]
    assert [state["n"] for state in timeline] == [17, 18]
    assert [state["state"] for state in timeline] == ["executed", "approved_pending"]
    for state in timeline:
        assert "COMBINED_PORTFOLIO" in state["member_internal_ids"]
        assert len(state["member_internal_ids"]) == state["n"]
        assert state["n"] * state["equal_weight"] == pytest.approx(1.0)
    combined = contract()["strategies"][0]
    assert combined["constituent_count"] == 16
    assert combined["constituent_equal_weight"] == pytest.approx(1 / 16)
    assert combined["approved_constituent_count"] == 17
    assert combined["approved_constituent_equal_weight"] == pytest.approx(1 / 17)


def test_strategy_monitor_binds_explicit_summary_and_intraday_row_fields():
    app = (ROOT / "dashboard/foundation-app.js").read_text(encoding="utf-8")
    assert "Total Registry Entities" in app
    assert "Ordinary Active" in app
    assert "Current Top-Level Active" in app
    assert "Pending Candidates" in app
    assert "Combined Constituents" in app
    assert "Top-Level Equal Sleeve" in app
    assert "Combined Internal Weight" in app
    assert "intraday_estimated_pnl" in app
    assert "intraday_estimated_nav" in app
    assert "intraday_estimate_unavailable_reason" in app
    assert "data_state||r.data_status" in app
    assert app.count("function strategyMonitorPage()") == 1


def test_complete_strategy_history_is_published_without_mixing_research():
    data = contract()
    active_ids = {row["internal_id"] for row in data["strategies"] if row["membership_state"] == "executed"}
    history = data["strategy_daily"]
    assert len(history) > len(active_ids)
    assert all(row["strategy_id"] != "COMBINED_PORTFOLIO" for row in history)
    assert max(sum(row["strategy_id"] == strategy_id for row in history) for strategy_id in active_ids) > 1
    assert all("research_metrics" not in row for row in history)


def test_invalid_legacy_contract_is_rejected():
    invalid = contract()
    invalid["strategies"][0]["internal_id"] = "STRAT_001"
    with pytest.raises(CanonicalContractError, match="legacy proxy"):
        validate_canonical_frontend_contract(invalid)


def test_application_shell_and_shared_components_are_wired():
    index = (ROOT / "dashboard/index.html").read_text(encoding="utf-8")
    app = (ROOT / "dashboard/foundation-app.js").read_text(encoding="utf-8")
    components = (ROOT / "dashboard/foundation-components.js").read_text(encoding="utf-8")
    css = (ROOT / "dashboard/foundation.css").read_text(encoding="utf-8")

    assert "foundation-components.js" in index
    assert "foundation-app.js" in index
    assert '<script src="app.js"></script>' not in index
    for component in (
        "PageHeader",
        "SectionHeader",
        "MetricCard",
        "StatusBadge",
        "DataTable",
        "ChartPanel",
        "EmptyState",
        "Tabs",
        "FilterBar",
        "DetailDrawer",
        "AlertBanner",
        "SplitPanel",
    ):
        assert component in components
    assert "detail-drawer open" not in app
    assert 'drawer.classList.add("open")' in app
    assert "--selected:" in css
    assert "--hover:" in css


def test_command_center_uses_operational_snapshot_polling_without_full_reload():
    index = (ROOT / "dashboard/index.html").read_text(encoding="utf-8")
    app = (ROOT / "dashboard/foundation-app.js").read_text(encoding="utf-8")
    server = (ROOT / "scripts/run_workstation_server.py").read_text(encoding="utf-8")
    assert "fetch(`/api/operational-snapshot?ts=${Date.now()}`" in app
    assert "fetch(`/api/refresh?ts=${Date.now()}`" in app
    assert 'fetch("/api/decisions"' in app
    assert "setInterval(()=>refreshOperational(false),POLL_INTERVAL_MS)" in app
    assert "window.__COMMAND_POLL_INTERVAL_MS||300000" in app
    assert "location.reload" not in app
    assert 'data-decision-action="APPROVE"' in app
    assert 'data-contributor-id="' in app
    assert "Math.abs(r[basis])/max*100" in app
    assert "/api/operational-snapshot?ts=" in app
    assert '"Cache-Control":"no-store"' in app
    for blocked in ("sec.gov", "/api/live-summary", "dashboard_artifact.json", "news"):
        assert blocked not in app.lower()
        assert blocked not in index.lower()
    assert "/api/operational-snapshot" in server
    assert "/api/decisions" in server


def test_strategy_monitor_dense_registry_filters_drawer_and_refresh_state():
    app = (ROOT / "dashboard/foundation-app.js").read_text(encoding="utf-8")
    css = (ROOT / "dashboard/foundation.css").read_text(encoding="utf-8")

    for required in (
        "COMBINED_PORTFOLIO",
        "monitorFiltered",
        "strategyFilter",
        "familyFilter",
        "membershipFilter",
        "dataFilter",
        "sortKey",
        "sortDir",
        "data-row-id",
        "data-view-id",
        "openDrawer",
        "drawerTab",
        "Risk & Evidence",
        "Technical Metadata",
    ):
        assert required in app
    assert "fetch(`/api/refresh?ts=${Date.now()}`" in app
    assert 'trigger:manual?"manual":"automatic_poll"' in app
    assert "location.reload" not in app
    assert ".monitor-table th{position:sticky" in css
    assert ".monitor-table tbody tr.selected" in css
    assert ".detail-drawer{width:min(560px,96vw)" in css
    assert "Array.isArray(values)&&values.length>1?commandSpark(values,tone)" in app
    assert "flat=[1,1,1,1,1]" not in app
    assert "Operational Records" in app
    assert "Verified Shadow-Live Start" in app
    assert "Execution Provenance Review" in app
    assert "Shadow-Live / Operational" not in app
    assert "Historical Research" in app
    assert "Completed Paper Fill" not in app
    assert "Reference / Execution Price" in app
    assert "costValue(t.total_cost)" in app
    assert "state.drawerTab" in app


def test_shared_kpi_cards_do_not_render_decorative_sparklines():
    app = (ROOT / "dashboard/foundation-app.js").read_text(encoding="utf-8")
    components = (ROOT / "dashboard/foundation-components.js").read_text(encoding="utf-8")
    assert "Array.isArray(values) && values.length > 1 ? spark" in components
    assert "variant:i" not in app
    assert "Current cross-section, not a time series" in app
    assert "Array.isArray(values)&&values.length>1?commandSpark(values,tone)" in app


def test_strategy_detail_tabs_are_data_bound_and_gate_incomplete_wq():
    app = (ROOT / "dashboard/foundation-app.js").read_text(encoding="utf-8")
    css = (ROOT / "dashboard/foundation.css").read_text(encoding="utf-8")
    for tab in ("Overview", "Performance", "Holdings", "Trades", "Risk & Evidence", "Technical Metadata"):
        assert tab in app
    for marker in (
        "drawerHistory(s)",
        "s.research_evidence?.research_series",
        "entityHoldings(s)",
        "state.contract.trades.filter",
        "strategy_cost_reconciliation",
        "admissionGatePanel(s)",
        "g.exact_blocker",
        "Paper fill rows",
        "DATA PENDING: no execution rows exist for this strategy.",
        "COMBINED_PORTFOLIO",
        "Combined strategy membership",
    ):
        assert marker in app
    assert "researchNetChart" in app
    assert "hist.length>1" in app
    assert "rs.net_equity?.length>1" in app
    assert "gate-checks" in css


def test_strategy_library_workflow_page_is_data_bound():
    app = (ROOT / "dashboard/foundation-app.js").read_text(encoding="utf-8")
    css = (ROOT / "dashboard/foundation.css").read_text(encoding="utf-8")
    for marker in (
        "function workflowNodes(c)",
        "Data Inputs",
        "Research Artifacts",
        "Paper Execution",
        "Holdings Ledger",
        "Combined Strategy",
        "c.wq_admission_gate",
        "prov.trade_record_counts",
        "lifecycleStage(s)",
        "lifecycleNextAction(s)",
        "Strategy lifecycle registry",
        "Verified Shadow Start",
        "combined_rebalance_allowed",
    ):
        assert marker in app
    assert "workflow-node-grid" in css


def test_page_release_safety_gates_incomplete_pages():
    app = (ROOT / "dashboard/foundation-app.js").read_text(encoding="utf-8")
    css = (ROOT / "dashboard/foundation.css").read_text(encoding="utf-8")
    for status in ("READY", "MVP_READY", "IN_DEVELOPMENT", "BLOCKED"):
        assert status in app
    for page in (
        "Portfolio Command Center",
        "Strategy Monitor",
        "Allocation & Rebalance",
        "Risk Factors & Exposure",
        "Correlation & Diversification",
        "Market & Macro Monitor",
        "Backtesting & Research Lab",
        "Strategy Library & Workflow",
        "Daily Risk Report",
    ):
        assert f'"{page}"' in app
    assert "function releasePanel" in app
    assert 'function releasePanel(page=state.selectedPage){return ""}' in app
    assert "No fabricated widgets" not in app
    assert "Incomplete modules are intentionally shown as unavailable" not in app
    assert "${releasePanel()}" in app
    assert "Research and operational returns remain separate</button>" not in app
    assert "Review required</button>" not in app
    assert "release-safety-panel" in css
