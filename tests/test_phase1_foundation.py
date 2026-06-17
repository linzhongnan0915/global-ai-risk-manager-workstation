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


def test_performance_analytics_layer_is_data_bound_and_separates_research():
    app = (ROOT / "dashboard/foundation-app.js").read_text(encoding="utf-8")
    data = contract()
    ordinary = [
        row
        for row in data["strategies"]
        if row["membership_state"] == "executed"
        and row["internal_id"] != "COMBINED_PORTFOLIO"
    ]
    assert len(ordinary) == 16
    assert len(data["portfolio_daily"]) < 20
    for marker in (
        "function performanceRows(c)",
        "MASTER_PORTFOLIO",
        "PORTFOLIO & STRATEGY PERFORMANCE ANALYTICS",
        "Master Portfolio, 16 ordinary active, Combined, and #000018 pending",
        "Insufficient Official History",
        "Minimum official observations required",
        "Official Ledger: portfolio_daily only; delayed estimates excluded",
        "Operational Ledger: strategy_daily official shadow-live rows",
        "Operational paper-ledger metrics and research/backtest metrics remain separate",
        "Missing research artifacts are shown as Not loaded rather than estimated",
        "Derived from ordinary strategy net returns; no separate Combined paper fills; no cost double count",
        "APPROVED_PENDING / PRE_OPERATIONAL. Current sleeve N/A; Operational NAV N/A; Operational P&L N/A; No Paper Fill; No Live Brokerage Fill.",
        "Research vs Operational Performance",
        "Portfolio performance analytics",
    ):
        assert marker in app
    assert "intraday_estimate" not in app.split("function performanceRows(c)", 1)[1].split("function performanceDisplay", 1)[0]


def test_strategy_monitor_status_hierarchy_keeps_provenance_secondary():
    app = (ROOT / "dashboard/foundation-app.js").read_text(encoding="utf-8")
    for marker in (
        'return s.membership_state==="executed"?"Active Paper"',
        'if(s.internal_id==="COMBINED_PORTFOLIO")return "Active Composite"',
        "Execution Mode: Paper Only | Provenance: Pending | Live Fill: No",
        "Execution Mode: Derived | Provenance: Derived from ordinary strategy net returns | Live Fill: No | No separate Combined paper fills | No cost double count",
        "Current Sleeve: N/A | Operational NAV/P&L: N/A | Paper Fill: No Paper Fill | Live Fill: No Live Brokerage Fill | Next Action: Pending admission evidence",
        "statusLabel=strategyPrimaryState(s)",
        "tone:strategyPrimaryTone(s)",
    ):
        assert marker in app
    status_cell = app.split("function strategyPanel()", 1)[1].split("function alerts", 1)[0]
    assert "strategyPrimaryState(r)" in status_cell
    assert "strategySecondaryState(r)" in status_cell
    assert "operationalDisplayLabel(r)" not in status_cell


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
    assert "posMax=Math.max" in app
    assert "negMax=Math.max" in app
    assert "Math.abs(r[basis])/sectionMax*100" in app
    assert "contributors and detractors scale independently" in app
    assert "/api/operational-snapshot?ts=" in app
    assert '"Cache-Control":"no-store"' in app
    for blocked in ("sec.gov", "/api/live-summary", "dashboard_artifact.json", "news"):
        assert blocked not in app.lower()
        assert blocked not in index.lower()
    assert "/api/operational-snapshot" in server
    assert "/api/decisions" in server
    assert "load_operational_snapshot_for_response" in server
    assert "operational_intraday_overlay.json" in (ROOT / "src/reporting/operational_snapshot.py").read_text(encoding="utf-8")
    assert "ENABLE_INTRADAY_SCHEDULER" in server


def test_dashboard_snapshot_loading_cannot_remain_infinite_loading_shell():
    app = (ROOT / "dashboard/foundation-app.js").read_text(encoding="utf-8")

    assert "SNAPSHOT_LOAD_TIMEOUT_MS=45000" in app
    assert "AbortController" in app
    assert "snapshotShapeError" in app
    assert "renderLoadFailed" in app
    assert 'data-load-state="LOAD_FAILED"' in app
    assert "DATA_MISSING" in app
    assert 'snapshotLoadState:"READY"' in app
    assert 'snapshotLoadState:"LOAD_FAILED"' in app


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
    assert "Official Promotion" in app
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


def test_master_portfolio_daily_performance_uses_visible_ledger_dates():
    data = contract()
    app = (ROOT / "dashboard/foundation-app.js").read_text(encoding="utf-8")
    assert [row["date"] for row in data["portfolio_daily"]] == [
        "2026-06-04",
        "2026-06-05",
        "2026-06-08",
        "2026-06-10",
        "2026-06-11",
    ]
    assert data["portfolio_daily"][-1]["data_as_of"] == "2026-06-12"
    assert data["portfolio_daily"][-1]["date"] != data["portfolio_daily"][-1]["data_as_of"]
    assert "Visible ledger date uses portfolio_daily.date" in app
    assert "function latestPortfolioLedgerDate(c)" in app
    assert "Official portfolio ledger through ${latestPortfolioLedgerDate(c)}" in app
    assert "Official close/as-of" in app
    assert "Official Daily Ledger records + Delayed Estimate" in app
    assert "function lifecycle(c)" in app
    assert "function showIntradayPoint(c)" in app
    assert "Official Promotion" in app
    assert "function promotionReadiness(c)" in app
    assert "Ready for promotion" in app
    assert "EOD pending promotion" in app
    assert "Blocked / Pending required canonical inputs" in app
    assert "Official ledger promotion is blocked by missing runtime promotion input and required canonical pipeline readiness. Delayed estimates remain separate and are not official ledger records." in app
    assert "Official ledger promotion blocked" in app
    assert "Manual dry-run only" in app
    assert "Execute disabled" in app
    assert "Intraday Runtime" in app
    assert "function intradayRuntimeValue(c)" in app
    assert "Delayed Estimate Loaded" in app
    assert "Not Running / Not Loaded" in app
    assert "official ledger remains separate" in app
    assert "EOD estimate pending official ledger promotion" in app
    assert "Delayed estimate / not official ledger" in app
    assert "sessionLabel(c)" in app
    assert "Official Daily Ledger through" not in app
    assert '<span>${r.date}</span>' in app
    assert "ctx.fillText(rows[i].date.slice(5),q.x,h-13)" in app
    assert "official_close_date||rows[i].date" not in app
    assert "r.official_close_date||r.date" not in app


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


def test_strategy_library_governance_page_is_data_bound():
    app = (ROOT / "dashboard/foundation-app.js").read_text(encoding="utf-8")
    for marker in (
        "Strategy Library & Governance",
        "Data-bound strategy registry, canonical inputs, transformation lineage, evidence gates, and operating authority.",
        "function governanceRegistryRows(c)",
        "function governanceInputRows(c)",
        "function governanceLineageRows(c)",
        "function governanceGateRows(c)",
        "function governanceAuthorityRows(c)",
        "function governanceBlockedRows(c)",
        "function governanceHandoffRows(c)",
        "STRATEGY LIFECYCLE REGISTRY",
        "Display ID",
        "Lifecycle",
        "Operational Status",
        "Research Status",
        "Effective Date",
        "Current Sleeve",
        "Proposed Sleeve",
        "Execution Authority",
        "Data State",
        "Next Action",
        "function governanceLifecycle(s)",
        "function governanceResearchStatus(s)",
        "function governanceDataState(s)",
        "function governanceNextAction(s)",
        "PRE_OPERATIONAL",
        "APPROVED_PENDING",
        "Pending evidence",
        "Pending admission evidence",
        "Derived Complete",
        "Independent active top-level sleeve",
        "no separate Combined paper fills",
        'pending?"N/A":UI.percent',
        'pending?UI.percent(proposed,2):"N/A"',
        "CANONICAL INPUT INVENTORY",
        "Input Artifact",
        "Current Status",
        "Observed Count",
        "As-of / Effective Date",
        "Downstream Use",
        "Portfolio daily ledger",
        "Strategy registry",
        "Strategy daily ledgers",
        "Paper execution records",
        "Position / holdings rows",
        "Target rows",
        "Price coverage universe",
        "Candidate admission records",
        "Research evidence registry",
        "Operational snapshot metadata",
        "c.portfolio_daily.at(-1)?.date",
        "u.current_price_covered_ticker_count??intr.covered_tickers",
        "External institutional data research is tracked separately and is not represented as loaded",
        "DATA PROCESSING LINEAGE",
        "Processing Step",
        "Work Performed",
        "1. Load canonical snapshot",
        "operational snapshot / shadow live bundle",
        "Dashboard state model",
        "2. Reconcile membership",
        "cr.top_level_active_sleeves??active.length",
        "${pending.length} pending candidate",
        "3. Calculate top-level sleeves",
        "UI.percent(topWeight,2)",
        "4. Derive Combined strategy",
        "${ordinary.length} ordinary active strategy net returns",
        "5. Align portfolio performance dates",
        "portfolio_daily.date",
        "Use ledger date for visible chart/card dates; keep official close/data_as_of as metadata",
        "6. Build style / family proxy",
        "active strategy families",
        "7. Apply evidence gates",
        "signal rows, target rows, paper fill rows, position rows, execution provenance",
        "8. Block unsupported risk models",
        "VaR / ES / scenario / macro regime remain Blocked when not loaded",
        "EVIDENCE GATE MATRIX",
        "Strategy Group",
        "Canonical Signal",
        "Target Rows",
        "Paper Fill Rows",
        "Position Rows",
        "Verified Provenance",
        "Admission State",
        "Ordinary active strategies",
        "Combined strategy",
        "WQ_ALPHA_018 / #000018",
        "Missing canonical signal date",
        "Missing target rows",
        "Missing paper fill rows",
        "Missing position rows",
        "Missing verified execution provenance",
        "APPROVED_PENDING / PRE_OPERATIONAL / BLOCKED",
        "No separate Combined paper fills",
        "Derived from ordinary strategy net returns",
        "No cost double count",
        "OPERATING AUTHORITY & EXECUTION CONTROLS",
        "Initial Shadow Capital",
        "Real Funded Brokerage Capital",
        "Brokerage Execution",
        "Live Allocation",
        "No Live Brokerage Fill",
        "Human Review Required",
        "The dashboard can display paper operating records and human review states, but it does not authorize or submit live brokerage orders.",
        "DATA GAPS & BLOCKED ANALYTICS",
        "Analytics Area",
        "Required Input",
        "Fallback Policy",
        "Decision Use",
        "STYLE / FAMILY EXPOSURE PROXY",
        "Derived from active strategy families, not a validated factor model.",
        "This is a portfolio construction proxy derived from active strategy families. It is not a Barra model, factor loading model, covariance model, VaR model, or ES model.",
        "Factor contribution to risk",
        "validated institutional factor model + covariance history",
        "Human review only",
        "VaR",
        "validated VaR model + return history",
        "Expected Shortfall",
        "validated ES model + return distribution",
        "Scenario shock",
        "scenario definitions + exposure model",
        "Macro regime",
        "validated macro feed / regime model",
        "External institutional data",
        "Bloomberg / Morningstar / Factiva / CRSP exports or licensed feeds",
        "Tracked separately",
        "Not represented as loaded",
        "Research only",
        "PROJECT HANDOFF REFERENCES",
        "Static project references; not market or accounting data",
        "Reference Area",
        "Reference",
        "Use",
        "GitHub",
        "https://github.com/linzhongnan0915/global-ai-risk-manager-workstation",
        "Hosting",
        "https://global-ai-risk-manager-workstation.onrender.com",
        "LLM / Agentic Platform",
        "ChatGPT / Codex / Cursor-assisted engineering workflow for implementation planning, testing guidance, release notes, and dashboard QA.",
        "c.strategies.length",
        "c.strategy_daily.length",
        "c.trades.length",
        "c.holdings.length",
        "c.portfolio_daily.length",
        "Top-Level Active",
        "16 ordinary active strategies + 1 active Combined strategy",
        "Paper Provenance Gate",
        "Pending / Not Fully Verified",
        "Raw provenance gate count:",
        "rawProvenanceCount=c.execution_provenance?.trade_record_counts?.VERIFIED_SHADOW_EXECUTION??0",
        "wq_admission_gate",
        "combined_rebalance_allowed",
    ):
        assert marker in app
    old_library_label = "Strategy Library & " + "Workflow"
    assert old_library_label not in app
    assert "Verified Shadow Rows" not in app
    for misleading in (
        "Factor Exposure " + "Heatmap",
        "Portfolio Factor " + "Exposure",
        "Combined family mix",
    ):
        assert misleading not in app


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
        "Workflow & Shadow-Live Testing",
        "Backtesting & Research Lab",
        "Strategy Library & Governance",
        "Daily Risk Report",
    ):
        assert f'"{page}"' in app
    old_tab_label = "Market & " + "Macro Monitor"
    assert old_tab_label not in app
    assert "NO_LIVE_BROKERAGE" in app
    assert "Risk tab staging status" in app
    assert "Institutional factor model, VaR, ES, scenario shock, macro regime, and stress analytics are Blocked / Not loaded." in app
    assert "Correlation tab staging status" in app
    assert "No correlation matrix, duplicate-pair heatmap, cluster map, or diversification score is rendered or inferred." in app
    assert "Research Lab staging status" in app
    assert "OOS, walk-forward, stress test, macro regime, and backtest metrics are displayed only when loaded as canonical evidence." in app
    assert "Daily report staging status" in app
    assert "BLOCKED_SAFE" in app
    assert "external institutional data research is tracked separately" in app.lower()
    assert "Strategy Development Workflow" in app
    assert "Shadow-Live Paper Testing Workflow" in app
    assert "Strategy Admission Gate" in app
    assert "Combined Strategy Operating Workflow" in app
    assert "Risk Review Workflow" in app
    assert "Local-First Release Workflow" in app
    assert "Project Handoff References" in app
    assert "Research Idea" in app
    assert "Signal Definition" in app
    assert "Target Construction" in app
    assert "Paper Execution Record" in app
    assert "Position Ledger" in app
    assert "Human Approval" in app
    assert "WQ_ALPHA_018 / #000018" in app
    assert "Current sleeve</span><b>N/A</b>" in app
    assert "Operational NAV</span><b>N/A</b>" in app
    assert "Operational P&L</span><b>N/A</b>" in app
    assert "Paper fill</span><b class=\"tone-warning\">Not present</b>" in app
    assert "Live brokerage fill</span><b class=\"tone-warning\">Disabled / Not present</b>" in app
    assert "codex-clipboard" not in app
    assert "function releasePanel" in app
    assert 'function releasePanel(page=state.selectedPage){return ""}' in app
    assert "No fabricated widgets" not in app
    assert "Incomplete modules are intentionally shown as unavailable" not in app
    assert "${releasePanel()}" in app
    assert "Research and operational returns remain separate</button>" not in app
    assert "Review required</button>" not in app
    assert "release-safety-panel" in css
    assert "workflow-testing-grid" in css
    assert "workflow-step-card" in css


def test_risk_factor_big_table_v1_is_snapshot_bound_without_hardcoded_row_count():
    app = (ROOT / "dashboard/foundation-app.js").read_text(encoding="utf-8")
    css = (ROOT / "dashboard/foundation.css").read_text(encoding="utf-8")

    for marker in (
        "Risk Factor Big Table v1",
        "Risk Factor Matrix v2",
        "Strategy x Factor Matrix from risk_factor_big_table",
        "function riskFactorRows(c)",
        "function riskFactorBigTable(c)",
        "function riskFactorCell(value,r)",
        "c.risk_factor_big_table||[]",
        "Rows come from risk_factor_big_table in /api/operational-snapshot; rendering does not hard-code strategy count.",
        "Factor cells show Missing Metadata where validated strategy-level factor metadata is absent; missing values are not converted to zero.",
        "Strategy Family Mix - Proxy Only, Not a Validated Factor Model",
        "Metadata / expected, not quantitative beta",
        "Combined Portfolio is displayed as Active Composite / Composite, separate from ordinary alpha strategies.",
        "#000018 / WQ_ALPHA_018 remains APPROVED_PENDING / PRE_OPERATIONAL with N/A operating metrics.",
        "legacy artifact estimate not authoritative",
        "position_source = committed_shadow_holdings",
        "legacy_artifact_position_estimate_authoritative = false",
        "No live brokerage positions or fills are represented",
        '"Risk Factors & Exposure":riskPageV1',
        "risk-factor-big-table",
        "risk-factor-matrix-v2",
    ):
        assert marker in app
    assert "risk-factor-big-table{min-width:3900px}" in css
    assert ".risk-factor-matrix{min-width:2250px}" in css
    assert ".factor-cell.missing" in css
    assert ".factor-cell.pending" in css
    assert ".factor-cell.proxy" in css
    table_function = app.split("function riskFactorRows(c)", 1)[1].split("function riskFactorBigTable", 1)[0]
    assert ".map(r=>" in table_function
    assert "slice(0" not in table_function
    assert "16 ordinary" not in table_function
    assert "18 registry" not in table_function


def test_risk_factor_market_proxy_matrix_v1_is_primary_when_available():
    app = (ROOT / "dashboard/foundation-app.js").read_text(encoding="utf-8")
    css = (ROOT / "dashboard/foundation.css").read_text(encoding="utf-8")

    for marker in (
        "risk_factor_market_proxy_table",
        "Market Data Risk Proxy Matrix",
        "Market Data Proxy",
        "Delayed yfinance overlay",
        "Not a validated Barra / institutional factor model",
        "Not live brokerage",
        "Not live real-time market data",
        "Market-data proxy from cached delayed yfinance overlay. Not a validated institutional factor model.",
        "function marketProxyRows(c)",
        "function marketProxyTable(c)",
        "SPY beta/correlation require sufficient overlapping benchmark history; missing values remain status labels, not zero.",
        "Rows come from risk_factor_market_proxy_table in /api/operational-snapshot when available; rendering does not hard-code strategy count.",
    ):
        assert marker in app
    for marker in (
        ".market-proxy-panel",
        ".market-proxy-table{min-width:2450px}",
        ".proxy-disclosure",
        ".proxy-cell.missing",
        ".proxy-cell.pending",
        ".risk-matrix-secondary",
    ):
        assert marker in css
    table_function = app.split("function marketProxyRows(c)", 1)[1].split("function marketProxyTable", 1)[0]
    assert ".map(r=>" in table_function
    assert "slice(0" not in table_function


def test_left_rail_navigation_maps_to_current_top_tabs():
    app = (ROOT / "dashboard/foundation-app.js").read_text(encoding="utf-8")
    for marker in (
        "const RAIL_TO_TAB =",
        'portfolio:"Portfolio Command Center"',
        'strategies:"Strategy Monitor"',
        'risk:"Risk Factors & Exposure"',
        'allocation:"Allocation & Rebalance"',
        'analytics:"Correlation & Diversification"',
        'research:"Backtesting & Research Lab"',
        'workflow:"Workflow & Shadow-Live Testing"',
        'reports:"Daily Risk Report"',
        'alerts:"Daily Risk Report"',
        'data:"Workflow & Shadow-Live Testing"',
        'settings:"Strategy Library & Governance"',
        "data-rail-key",
        "data-rail-page",
        "page=RAIL_TO_TAB[i]",
        "PRIMARY_RAIL_BY_TAB",
        "active=PRIMARY_RAIL_BY_TAB[state.selectedPage]===i",
        "const body=Array.isArray(rows)?rows.join(\"\"):rows",
        'document.querySelectorAll("[data-rail-page]")',
        "state.selectedPage=b.dataset.railPage",
    ):
        assert marker in app
    assert "NAV_PAGE_MAP" not in app
