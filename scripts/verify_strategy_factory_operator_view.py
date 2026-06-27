"""Focused browser smoke for Strategy Factory operator actions."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8765/dashboard/index.html?smoke=strategy-factory-operator")
    args = parser.parse_args()
    url = args.url
    if url.startswith("[") and "](" in url and url.endswith(")"):
        url = url.split("](", 1)[1][:-1]
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print("playwright not installed; skipping Strategy Factory operator smoke")
        return 0

    errors: list[str] = []
    response_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.on(
            "console",
            lambda msg: errors.append(msg.text)
            if msg.type == "error" and "Failed to load resource: the server responded with a status of 404" not in msg.text
            else None,
        )
        page.on(
            "response",
            lambda response: response_errors.append(f"{response.status} {response.url}")
            if response.status >= 400 and not response.url.endswith("/favicon.ico")
            else None,
        )
        page.goto(url, wait_until="domcontentloaded")
        page.get_by_role("button", name="8. Strategy Factory").click()
        if "backend-trading-session-state" in url:
            screenshot_path = "D:/Global_Ai/release_global_ai_risk_manager_workstation/output/strategy_factory/backend_trading_session_state.png"
            page.get_by_role("button", name="1. Portfolio Command Center").click()
            page.wait_for_selector(".command-center", timeout=15000)
            session_state = page.evaluate(
                """async () => {
                    const r = await fetch('/api/operational-snapshot?ts=' + Date.now(), {cache: 'no-store'});
                    const j = await r.json();
                    return j.session_state || {};
                }"""
            )
            for key in [
                "calendar_date",
                "market_session_status",
                "is_trading_day",
                "last_trading_session",
                "next_trading_session",
                "current_intraday_session",
                "latest_quote_asof",
                "quote_freshness",
                "daily_ledger_date",
                "daily_ledger_relation",
                "intraday_estimate_status",
            ]:
                assert key in session_state, f"backend session_state missing {key}: {session_state}"
            header_text = page.locator(".global-header").inner_text(timeout=10000)
            assert "Pending today" not in header_text, "header still uses old pending-today wording"
            assert "latest delayed price as-of" in header_text.lower(), "quote as-of header missing"
            assert (
                "Market Closed" in header_text
                or "Current intraday session" in header_text
                or "No current session intraday" in header_text
                or "STALE_PRIOR_SESSION" in header_text
            ), "header does not reflect backend session state"
            page.screenshot(path=screenshot_path, full_page=True)
            browser.close()
            assert not response_errors, f"resource errors: {response_errors}"
            assert not errors, f"console errors: {errors}"
            print(f"Backend trading session state smoke PASS screenshot={screenshot_path}")
            return 0
        if "strategy-detail-drawer-format" in url:
            screenshot_path = "D:/Global_Ai/release_global_ai_risk_manager_workstation/output/strategy_factory/strategy_detail_drawer_format_fix.png"
            page.get_by_role("button", name="1. Portfolio Command Center").click()
            page.wait_for_selector(".command-center", timeout=15000)
            header_text = page.locator(".global-header").inner_text(timeout=10000)
            assert "Pending today" not in header_text, "non-trading session still says Pending today"
            assert "latest delayed price as-of" in header_text.lower(), "quote as-of header missing"
            assert ("Market Closed" in header_text or "Current intraday session" in header_text or "No current session intraday" in header_text), "session status missing"

            target = page.locator("[data-contributor-id]").first
            if not target.count():
                target = page.locator(".command-performance-table tbody tr").first
            target.click()
            page.wait_for_selector("#detailDrawer.open", timeout=15000)
            drawer_text = page.locator("#detailDrawer").inner_text(timeout=10000)
            for expected in [
                "Strategy Detail",
                "Sleeve Weight",
                "Daily P&L",
                "Operational NAV",
                "Latest delayed price as-of",
                "Paper / Next Open",
                "Paper Provenance Pending",
                "No Live Fill",
            ]:
                assert expected.lower() in drawer_text.lower(), f"drawer missing {expected}"
            assert "T15:45:00-04:00" not in drawer_text, "raw ISO timestamp still visible in drawer"
            layout = page.evaluate(
                """() => {
                    const drawer = document.querySelector('#detailDrawer');
                    const kpis = document.querySelector('.strategy-detail-kpis');
                    const status = document.querySelector('.drawer-governance-status');
                    const kpiText = kpis ? kpis.innerText : '';
                    const statusText = status ? status.innerText : '';
                    const cols = kpis ? getComputedStyle(kpis).gridTemplateColumns.split(' ').length : 0;
                    return {
                        drawerWidth: drawer ? drawer.getBoundingClientRect().width : 0,
                        cols,
                        kpiText,
                        statusText,
                        statusBadgeCount: status ? status.querySelectorAll('.status-badge').length : 0,
                    };
                }"""
            )
            assert layout["cols"] <= 2, f"drawer KPI grid still too wide: {layout}"
            assert "Execution Type" not in layout["kpiText"], "execution type still rendered as numeric KPI"
            assert "Execution Verification" not in layout["kpiText"], "execution verification still rendered as numeric KPI"
            assert "Live Fill" not in layout["kpiText"], "live fill still rendered as numeric KPI"
            assert "paper / next open" in layout["statusText"].lower(), "paper execution status missing from governance rows"
            assert layout["statusBadgeCount"] >= 3, "status rows are not rendered as compact badges"
            page.screenshot(path=screenshot_path, full_page=True)
            browser.close()
            assert not response_errors, f"resource errors: {response_errors}"
            assert not errors, f"console errors: {errors}"
            print(f"Strategy detail drawer format smoke PASS screenshot={screenshot_path}")
            return 0
        if "quick-ui-risk-factor-dynamic" in url or "ui-correction-list-first" in url:
            command_screenshot = "D:/Global_Ai/release_global_ai_risk_manager_workstation/output/strategy_factory/ui_correction_command_center_compact_header.png"
            monitor_screenshot = "D:/Global_Ai/release_global_ai_risk_manager_workstation/output/strategy_factory/ui_correction_strategy_monitor_list_first.png"
            risk_screenshot = "D:/Global_Ai/release_global_ai_risk_manager_workstation/output/strategy_factory/ui_correction_risk_factor_dynamic.png"

            page.get_by_role("button", name="1. Portfolio Command Center").click()
            page.wait_for_selector(".command-status-strip", timeout=15000)
            command_text = page.locator(".command-center").inner_text(timeout=10000)
            for expected in [
                "Portfolio NAV",
                "Daily P&L",
                "Top-Level Active",
                "Active Unallocated",
                "Pending Approval",
                "Recommendation/Rebalance",
                "Txn Cost / 5bps",
                "Top contributors & detractors",
                "Rebalance decision center",
                "Current membership & allocation",
                "Strategy performance",
                "Strategy Family Mix",
            ]:
                assert expected.lower() in command_text.lower(), f"Command Center missing {expected}"
            layout = page.evaluate(
                """() => {
                    const strip = document.querySelector('.command-status-strip');
                    const details = document.querySelector('.command-secondary-diagnostics');
                    const board = document.querySelector('.command-board');
                    const contrib = document.querySelector('.cmd-contributors');
                    const chart = document.querySelector('.cmd-chart');
                    return {
                        stripHeight: strip ? strip.getBoundingClientRect().height : 0,
                        detailsPresent: !!details,
                        boardTop: board ? board.getBoundingClientRect().top : 9999,
                        contribTop: contrib ? contrib.getBoundingClientRect().top : 9999,
                        chartTop: chart ? chart.getBoundingClientRect().top : 9999,
                    };
                }"""
            )
            assert layout["stripHeight"] and layout["stripHeight"] <= 70, f"KPI strip too tall: {layout}"
            assert layout["detailsPresent"] is False, "new diagnostic bar should not be visible"
            assert layout["boardTop"] < 220, f"command board starts too low: {layout}"
            assert abs(layout["contribTop"] - layout["chartTop"]) < 24, f"body panel alignment changed too much: {layout}"
            page.screenshot(path=command_screenshot, full_page=True)

            page.get_by_role("button", name="2. Strategy Monitor").click()
            page.wait_for_selector("text=Strategy operational registry", timeout=15000)
            monitor_text = page.locator(".strategy-monitor-page").inner_text(timeout=10000)
            for expected in [
                "Display only",
                "Display-only label; canonical identity uses strategy_uid.",
                "Strategy Name",
                "Active Unallocated",
                "Current weight",
                "Recommended weight",
                "Strategy operational registry",
            ]:
                assert expected.lower() in monitor_text.lower(), f"Strategy Monitor missing {expected}"
            assert "Display label" not in monitor_text, "old Display label wording still visible"
            monitor_layout = page.evaluate(
                """() => {
                    const summary = document.querySelector('.strategy-monitor-status-summary');
                    const registry = document.querySelector('.strategy-monitor-panel');
                    const cards = document.querySelectorAll('.strategy-monitor-page > .metric-grid .metric-card').length;
                    return {
                        summaryHeight: summary ? summary.getBoundingClientRect().height : 0,
                        registryTop: registry ? registry.getBoundingClientRect().top : 9999,
                        cards,
                    };
                }"""
            )
            assert monitor_layout["summaryHeight"] and monitor_layout["summaryHeight"] <= 56, f"summary too tall: {monitor_layout}"
            assert monitor_layout["registryTop"] < 190, f"registry not high enough: {monitor_layout}"
            assert monitor_layout["cards"] == 0, f"large top KPI cards still present: {monitor_layout}"
            page.screenshot(path=monitor_screenshot, full_page=True)

            page.get_by_role("button", name="4. Risk Factors & Exposure").click()
            page.wait_for_selector("text=Risk Factor Exposure Matrix", timeout=15000)
            risk_text = page.locator(".risk-factor-page").inner_text(timeout=10000)
            for expected in [
                "dynamic active universe",
                "active-unallocated",
                "Missing",
                "No portfolio impact",
                "ordinary",
                "Combined",
            ]:
                assert expected.lower() in risk_text.lower(), f"Risk Factors missing {expected}"
            risk_state = page.evaluate(
                """() => ({
                    phase2Rows: document.querySelectorAll('.risk-factor-page .phase2-unallocated-row').length,
                    consoleText: document.body.innerText || ''
                })"""
            )
            assert risk_state["phase2Rows"] >= 1, "active-unallocated strategy not visible in risk matrix"
            page.screenshot(path=risk_screenshot, full_page=True)

            browser.close()
            assert not response_errors, f"resource errors: {response_errors}"
            assert not errors, f"console errors: {errors}"
            print(
                "Quick UI risk factor dynamic smoke PASS "
                f"screenshots={command_screenshot},{monitor_screenshot},{risk_screenshot}"
            )
            return 0
        if "phase1b-recommendation-review-draft" in url:
            page.get_by_role("button", name="3. Allocation & Rebalance").click()
            page.wait_for_selector("text=Recommendation Only", timeout=15000)
            button = page.get_by_role("button", name="Generate Recommendation Review Draft")
            assert button.count(), "Generate Recommendation Review Draft CTA missing"
            assert button.first.is_enabled(), "Generate Recommendation Review Draft CTA disabled"
            button.first.click()
            page.wait_for_function(
                """() => {
                    const text = document.body.innerText || '';
                    return text.includes('DRAFT_NOT_APPLIED') && /recommendation-review-[a-f0-9]+/i.test(text);
                }""",
                timeout=15000,
            )
            allocation_text = page.locator(".allocation-workstation-page").inner_text(timeout=10000)
            for expected in [
                "Recommendation Only",
                "DRAFT_NOT_APPLIED",
                "None until approved + effective date",
                "Current/Target Weights: Unchanged",
                "Combined Current: Unchanged",
                "Brokerage Execution: Disabled",
            ]:
                assert expected.lower() in allocation_text.lower(), f"Phase 1B allocation page missing {expected}"
            assert page.get_by_role("button", name="Accept disabled").first.is_disabled(), "Accept should be disabled in Phase 1B"
            assert page.get_by_role("button", name="Apply disabled").first.is_disabled(), "Apply should be disabled in Phase 1B"
            draft_status = page.evaluate(
                """async () => {
                    const r = await fetch('/api/paper-rebalance?ts=' + Date.now(), {cache: 'no-store'});
                    const j = await r.json();
                    const d = j.paper_rebalance?.recommendation_review?.latest_draft;
                    return {
                        proposal_id: d?.proposal_id || '',
                        review_status: d?.review_status || '',
                        line_count: (d?.line_items || []).length,
                        current_weight_mutation: d?.current_weight_mutation,
                        target_weight_mutation: d?.target_weight_mutation,
                        paper_ledger_mutation: d?.paper_ledger_mutation,
                        combined_current_mutation: d?.combined_current_mutation,
                        live_trading: d?.live_trading,
                        brokerage_execution: d?.brokerage_execution,
                    };
                }"""
            )
            assert draft_status["proposal_id"], "recommendation review draft artifact missing"
            assert draft_status["review_status"] == "DRAFT_NOT_APPLIED", f"wrong review status: {draft_status}"
            assert draft_status["line_count"] > 0, "draft has no line items"
            assert draft_status["current_weight_mutation"] is False
            assert draft_status["target_weight_mutation"] is False
            assert draft_status["paper_ledger_mutation"] is False
            assert draft_status["combined_current_mutation"] is False
            assert draft_status["live_trading"] is False
            assert draft_status["brokerage_execution"] is False
            screenshot_path = "D:/Global_Ai/release_global_ai_risk_manager_workstation/output/strategy_factory/phase1b_recommendation_review_draft.png"
            page.screenshot(path=screenshot_path, full_page=True)
            browser.close()
            assert not response_errors, f"resource errors: {response_errors}"
            assert not errors, f"console errors: {errors}"
            print(
                "Strategy Factory Phase 1B recommendation review draft smoke PASS "
                f"proposal_id={draft_status['proposal_id']} line_count={draft_status['line_count']} "
                f"screenshot={screenshot_path}"
            )
            return 0
        if "combined-vs-ordinary-active-counts" in url:
            page.get_by_role("button", name="2. Strategy Monitor").click()
            page.wait_for_selector("text=Ordinary Active", timeout=15000)
            monitor_text = page.locator(".strategy-monitor-page").inner_text(timeout=10000)
            for expected in [
                "Ordinary Active",
                "Combined",
                "Top-Level Active",
                "pending approval excluded",
                "Composite top-level row",
                "Does not count as active",
            ]:
                assert expected.lower() in monitor_text.lower(), f"Strategy Monitor missing {expected}"
            assert "17 active strategies" not in monitor_text, "ambiguous active strategy wording still visible"
            status = page.evaluate(
                """async () => {
                    const metricValue = label => {
                        const card = [...document.querySelectorAll('.metric-card')]
                            .find(node => ((node.querySelector('.metric-label') || {}).innerText || '').trim().toLowerCase() === String(label).toLowerCase());
                        const text = card ? ((card.querySelector('.metric-value') || card).innerText || '') : '';
                        const match = text.match(/-?\\d+/);
                        return match ? Number(match[0]) : null;
                    };
                    let j = {};
                    try {
                        const r = await fetch('/api/strategy-factory/portfolio-candidates/status?ts=' + Date.now(), {cache: 'no-store'});
                        j = await r.json();
                    } catch (_) {}
                    const ordinary = j.ordinary_active_count ?? metricValue('Ordinary Active');
                    const combined = j.combined_active_count ?? metricValue('Combined');
                    const topLevel = j.top_level_active_count ?? metricValue('Top-Level Active');
                    const pending = j.pending_approval_count ?? metricValue('Pending Approval');
                    const nextLabel = j.next_ordinary_display_label || '';
                    return {ordinary, combined, topLevel, pending, nextLabel};
                }"""
            )
            assert status["ordinary"] is not None, "ordinary active count missing"
            assert status["combined"] is not None, "combined count missing"
            assert status["topLevel"] is not None, "top-level count missing"
            assert status["combined"] >= 1, "Combined row was not counted separately"
            assert status["topLevel"] == status["ordinary"] + status["combined"], f"top-level count mismatch: {status}"
            page.get_by_role("button", name="1. Portfolio Command Center").click()
            page.wait_for_selector("text=Top-Level Active", timeout=15000)
            command_text = page.locator(".command-center").inner_text(timeout=10000)
            for expected in ["Ordinary Active", "Combined", "Top-Level Active", "Composite top-level row"]:
                assert expected.lower() in command_text.lower(), f"Command Center missing {expected}"
            screenshot_path = "D:/Global_Ai/release_global_ai_risk_manager_workstation/output/strategy_factory/combined_vs_ordinary_active_counts.png"
            page.screenshot(path=screenshot_path, full_page=True)
            browser.close()
            assert not response_errors, f"resource errors: {response_errors}"
            assert not errors, f"console errors: {errors}"
            print(
                "Strategy Factory combined vs ordinary active-count smoke PASS "
                f"ordinary={status['ordinary']} combined={status['combined']} top_level={status['topLevel']} "
                f"pending={status['pending']} next_label={status['nextLabel']} screenshot={screenshot_path}"
            )
            return 0
        if "phase2a-approve-rebalance-plan" in url:
            page.get_by_role("button", name="3. Allocation & Rebalance").click()
            page.wait_for_selector("text=Recommendation Only", timeout=15000)
            generate = page.get_by_role("button", name="Generate Recommendation Review Draft")
            assert generate.count(), "Generate Recommendation Review Draft CTA missing"
            if generate.first.is_enabled():
                generate.first.click()
                page.wait_for_function(
                    """() => {
                        const text = document.body.innerText || '';
                        return text.includes('DRAFT_NOT_APPLIED') && /recommendation-review-[a-f0-9]+/i.test(text);
                    }""",
                    timeout=15000,
                )
            approve = page.locator('[data-allocation-action="approveDraft"]')
            assert approve.count(), "Approve Rebalance Plan Artifact CTA missing"
            page.wait_for_function(
                """() => {
                    const b = document.querySelector('[data-allocation-action="approveDraft"]');
                    return b && !b.disabled;
                }""",
                timeout=15000,
            )
            assert approve.first.is_enabled(), "Approve Rebalance Plan Artifact CTA disabled"
            page.on("dialog", lambda dialog: dialog.accept())
            approve.first.click()
            page.wait_for_function(
                """() => {
                    const text = document.body.innerText || '';
                    return text.includes('APPROVED_WAITING_EFFECTIVE_DATE') &&
                        text.includes('Approved Plan Created') &&
                        text.includes('No NAV/P&L Impact Yet');
                }""",
                timeout=15000,
            )
            state = page.evaluate(
                """async () => {
                    const s = await fetch('/api/operational-snapshot?ts=' + Date.now(), {cache: 'no-store'}).then(r => r.json());
                    const r = await fetch('/api/paper-rebalance?ts=' + Date.now(), {cache: 'no-store'}).then(r => r.json());
                    const p = r.paper_rebalance?.approved_rebalance?.latest_plan;
                    return {
                        next_trading_session: s.session_state?.next_trading_session,
                        calendar_date: s.session_state?.calendar_date,
                        plan_id: p?.plan_id || '',
                        effective_date: p?.effective_date || '',
                        status: p?.status || '',
                        nav_pnl_impact: p?.nav_pnl_impact || '',
                        current_weight_mutation: p?.current_weight_mutation,
                        target_weight_mutation: p?.target_weight_mutation,
                        paper_ledger_mutation: p?.paper_ledger_mutation,
                        combined_current_mutation: p?.combined_current_mutation,
                        live_orders_created: p?.live_orders_created,
                        brokerage_orders_created: p?.brokerage_orders_created,
                        row_count: (p?.rows || []).length,
                    };
                }"""
            )
            assert state["plan_id"].startswith("approved-rebalance-"), f"approved plan missing: {state}"
            assert state["status"] == "APPROVED_WAITING_EFFECTIVE_DATE", f"wrong status: {state}"
            assert state["effective_date"] == state["next_trading_session"], f"effective date not backend next session: {state}"
            assert state["effective_date"] != state["calendar_date"], f"effective date used calendar date: {state}"
            assert state["row_count"] > 0, f"approved plan rows missing: {state}"
            assert state["current_weight_mutation"] is False
            assert state["target_weight_mutation"] is False
            assert state["paper_ledger_mutation"] is False
            assert state["combined_current_mutation"] is False
            assert state["live_orders_created"] is False
            assert state["brokerage_orders_created"] is False
            assert state["nav_pnl_impact"] == "NONE_UNTIL_EFFECTIVE_DATE_APPLY"
            allocation_text = page.locator(".allocation-workstation-page").inner_text(timeout=10000)
            for expected in [
                "Waiting Effective Date",
                "Estimated Transaction Cost",
                "No NAV/P&L Impact Yet",
                "No Live/Brokerage Orders",
            ]:
                assert expected.lower() in allocation_text.lower(), f"Phase 2A allocation page missing {expected}"
            screenshot_path = "D:/Global_Ai/release_global_ai_risk_manager_workstation/output/strategy_factory/phase2a_approve_rebalance_plan.png"
            page.screenshot(path=screenshot_path, full_page=True)
            browser.close()
            assert not response_errors, f"resource errors: {response_errors}"
            assert not errors, f"console errors: {errors}"
            print(f"Phase 2A approve rebalance plan smoke PASS screenshot={screenshot_path}")
            return 0
        if "phase2b-practical-paper-apply" in url:
            page.get_by_role("button", name="3. Allocation & Rebalance").click()
            page.wait_for_selector("text=Recommendation Only", timeout=15000)
            state_before = page.evaluate(
                """async () => {
                    const r = await fetch('/api/paper-rebalance?ts=' + Date.now(), {cache: 'no-store'}).then(x => x.json());
                    return {
                        approved: r.paper_rebalance?.approved_rebalance?.latest_plan || null,
                        current_target: r.paper_rebalance?.current_paper_target || null
                    };
                }"""
            )
            if not state_before["approved"]:
                generate = page.get_by_role("button", name="Generate Recommendation Review Draft")
                if generate.first.is_enabled():
                    generate.first.click()
                    page.wait_for_function(
                        """() => (document.body.innerText || '').includes('DRAFT_NOT_APPLIED')""",
                        timeout=15000,
                    )
                approve = page.locator('[data-allocation-action="approveDraft"]')
                page.wait_for_function(
                    """() => {
                        const b = document.querySelector('[data-allocation-action="approveDraft"]');
                        return b && !b.disabled;
                    }""",
                    timeout=15000,
                )
                page.on("dialog", lambda dialog: dialog.accept())
                approve.first.click()
                page.wait_for_function(
                    """() => (document.body.innerText || '').includes('APPROVED_WAITING_EFFECTIVE_DATE')""",
                    timeout=15000,
                )
            apply_button = page.locator('[data-allocation-action="applyApproved"]')
            assert apply_button.count(), "Apply Approved Paper Rebalance CTA missing"
            page.wait_for_function(
                """() => {
                    const b = document.querySelector('[data-allocation-action="applyApproved"]');
                    return b && !b.disabled;
                }""",
                timeout=15000,
            )
            page.on("dialog", lambda dialog: dialog.accept())
            apply_button.first.click()
            page.wait_for_function(
                """() => {
                    const text = document.body.innerText || '';
                    return text.includes('APPLIED_PAPER') || text.includes('APPROVED_WAITING_EFFECTIVE_DATE');
                }""",
                timeout=15000,
            )
            state_after = page.evaluate(
                """async () => {
                    const s = await fetch('/api/operational-snapshot?ts=' + Date.now(), {cache: 'no-store'}).then(r => r.json());
                    const r = await fetch('/api/paper-rebalance?ts=' + Date.now(), {cache: 'no-store'}).then(r => r.json());
                    const p = r.paper_rebalance?.approved_rebalance?.latest_plan;
                    const e = r.paper_rebalance?.approved_rebalance?.latest_applied_event;
                    const t = r.paper_rebalance?.current_paper_target;
                    return {
                        session: s.session_state || {},
                        status: p?.status || '',
                        plan_id: p?.plan_id || '',
                        event_plan_id: e?.plan_id || '',
                        event_cost: e?.total_transaction_cost ?? null,
                        target_status: t?.applied_status || '',
                        no_live_orders: e ? e.no_live_orders : t?.no_live_orders,
                        no_brokerage_orders: e ? e.no_brokerage_orders : t?.no_brokerage_orders,
                        old_historical_pnl_rewritten: e?.old_historical_pnl_rewritten,
                    };
                }"""
            )
            assert state_after["plan_id"].startswith("approved-rebalance-"), f"approved plan missing: {state_after}"
            if state_after["status"] == "APPLIED_PAPER":
                assert state_after["event_plan_id"] == state_after["plan_id"], f"applied event missing: {state_after}"
                assert state_after["target_status"] == "APPLIED_PAPER", f"current paper target not applied: {state_after}"
                assert state_after["event_cost"] is not None and state_after["event_cost"] >= 0, f"cost missing: {state_after}"
                assert state_after["no_live_orders"] is True
                assert state_after["no_brokerage_orders"] is True
                assert state_after["old_historical_pnl_rewritten"] is False
            else:
                assert state_after["status"] == "APPROVED_WAITING_EFFECTIVE_DATE", f"unexpected status: {state_after}"
                assert state_after["session"].get("current_intraday_session") in {None, "", state_after["session"].get("calendar_date")}, f"waiting state should be driven by session_state: {state_after}"
            screenshot_path = "D:/Global_Ai/release_global_ai_risk_manager_workstation/output/strategy_factory/phase2b_practical_paper_apply.png"
            page.screenshot(path=screenshot_path, full_page=True)
            browser.close()
            assert not response_errors, f"resource errors: {response_errors}"
            assert not errors, f"console errors: {errors}"
            print(f"Phase 2B practical paper apply smoke PASS screenshot={screenshot_path} status={state_after['status']} cost={state_after['event_cost']}")
            return 0
        if "phase2c-applied-state-readiness" in url:
            waiting_screenshot = "D:/Global_Ai/release_global_ai_risk_manager_workstation/output/strategy_factory/phase2c_waiting_state.png"
            applied_screenshot = "D:/Global_Ai/release_global_ai_risk_manager_workstation/output/strategy_factory/phase2c_applied_state_fixture.png"
            snapshot = page.evaluate(
                """async () => await fetch('/api/operational-snapshot?ts=' + Date.now(), {cache: 'no-store'}).then(r => r.json())"""
            )
            paper = page.evaluate(
                """async () => await fetch('/api/paper-rebalance?ts=' + Date.now(), {cache: 'no-store'}).then(r => r.json())"""
            )
            ordinary = [
                row for row in snapshot.get("strategies", [])
                if row.get("membership_state") == "executed" and row.get("internal_id") != "COMBINED_PORTFOLIO"
            ]
            assert len(ordinary) >= 2, "Phase 2C fixture needs at least two ordinary active rows"
            uid_a = ordinary[0].get("strategy_uid") or ordinary[0].get("internal_id")
            uid_b = ordinary[1].get("strategy_uid") or ordinary[1].get("internal_id")
            strategy_name_a = ordinary[0].get("display_name") or ordinary[0].get("ui_name") or uid_a
            strategy_name_b = ordinary[1].get("display_name") or ordinary[1].get("ui_name") or uid_b
            for row in snapshot["strategies"]:
                if (row.get("strategy_uid") or row.get("internal_id")) == uid_a:
                    row["strategy_factory_phase2"] = True
                    row["current_operational_status"] = "ACTIVE_UNALLOCATED"
                    row["current_weight"] = 0.0
                    row["recommended_weight"] = 0.2
            session = dict(snapshot.get("session_state") or {})
            effective_date = session.get("next_trading_session") or session.get("calendar_date") or "2099-01-01"
            plan_id = "approved-rebalance-fixture"
            event_id = "applied-rebalance-fixture"
            rows = [
                {
                    "strategy_uid": uid_a,
                    "strategy_name": strategy_name_a,
                    "current_weight": 0.0,
                    "recommended_weight": 0.2,
                    "proposed_weight": 0.2,
                    "approved_target_weight": 0.2,
                    "estimated_trade": 200000,
                    "estimated_transaction_cost": 100,
                    "evidence_status": "EVIDENCE_AVAILABLE",
                    "data_quality": "PUBLIC_FALLBACK",
                    "ml_status": "No ML evidence available",
                    "recommendation_reason": "Fixture applied-state row.",
                    "action_status": "INCREASE",
                },
                {
                    "strategy_uid": uid_b,
                    "strategy_name": strategy_name_b,
                    "current_weight": 0.5,
                    "recommended_weight": 0.8,
                    "proposed_weight": 0.8,
                    "approved_target_weight": 0.8,
                    "estimated_trade": 300000,
                    "estimated_transaction_cost": 150,
                    "evidence_status": "EVIDENCE_AVAILABLE",
                    "data_quality": "PUBLIC_FALLBACK",
                    "ml_status": "No ML evidence available",
                    "recommendation_reason": "Fixture applied-state row.",
                    "action_status": "INCREASE",
                },
            ]
            waiting_plan = {
                "plan_id": plan_id,
                "status": "APPROVED_WAITING_EFFECTIVE_DATE",
                "effective_date": effective_date,
                "estimated_total_transaction_cost": 250,
                "rows": rows,
                "live_orders_created": False,
                "brokerage_orders_created": False,
            }
            applied_event = {
                "event_id": event_id,
                "plan_id": plan_id,
                "applied_effective_date": effective_date,
                "per_strategy_trade_weight": {uid_a: 0.2, uid_b: 0.3},
                "per_strategy_transaction_cost": {uid_a: 100, uid_b: 150},
                "total_transaction_cost": 250,
                "combined_dynamic_summary": {
                    "ordinary_strategy_count": len(ordinary),
                    "ordinary_weight_total": 1.0,
                    "computed_from": "active ordinary strategy_uid weights",
                },
                "no_live_orders": True,
                "no_brokerage_orders": True,
                "old_historical_pnl_rewritten": False,
            }
            applied_plan = {
                **waiting_plan,
                "status": "APPLIED_PAPER",
                "applied_status": "APPLIED_PAPER",
                "applied_effective_date": effective_date,
                "total_transaction_cost_booked": 250,
                "applied_event_id": event_id,
            }
            waiting_snapshot = copy.deepcopy(snapshot)
            waiting_paper = copy.deepcopy(paper)
            waiting_paper.setdefault("paper_rebalance", {}).setdefault("approved_rebalance", {})["latest_plan"] = waiting_plan
            waiting_paper["paper_rebalance"]["approved_rebalance"]["latest_applied_event"] = None
            waiting_snapshot["paper_rebalance"] = waiting_paper["paper_rebalance"]
            applied_snapshot = copy.deepcopy(snapshot)
            applied_paper = copy.deepcopy(paper)
            applied_paper.setdefault("paper_rebalance", {}).setdefault("approved_rebalance", {})["latest_plan"] = applied_plan
            applied_paper["paper_rebalance"]["approved_rebalance"]["latest_applied_event"] = applied_event
            applied_paper["paper_rebalance"]["current_paper_target"] = {
                "applied_plan_id": plan_id,
                "applied_event_id": event_id,
                "applied_status": "APPLIED_PAPER",
                "weights": {uid_a: 0.2, uid_b: 0.8},
                "paper_transaction_cost_total": 250,
                "combined_dynamic_summary": applied_event["combined_dynamic_summary"],
                "no_live_orders": True,
                "no_brokerage_orders": True,
            }
            applied_snapshot["paper_rebalance"] = applied_paper["paper_rebalance"]
            fixture_state = {"mode": "waiting"}

            def route_snapshot(route):
                body = waiting_snapshot if fixture_state["mode"] == "waiting" else applied_snapshot
                route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

            def route_paper(route):
                body = waiting_paper if fixture_state["mode"] == "waiting" else applied_paper
                route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

            page.route("**/api/operational-snapshot**", route_snapshot)
            page.route("**/api/paper-rebalance**", route_paper)

            page.goto(url, wait_until="domcontentloaded")
            page.get_by_role("button", name="3. Allocation & Rebalance").click()
            page.wait_for_selector("text=APPROVED_WAITING_EFFECTIVE_DATE", timeout=15000)
            waiting_text = page.locator(".allocation-workstation-page").inner_text(timeout=10000)
            for expected in [
                "APPROVED_WAITING_EFFECTIVE_DATE",
                "Effective Date",
                "Estimated Transaction Cost",
                "$0 booked until effective date",
                "No Live/Brokerage Orders",
            ]:
                assert expected.lower() in waiting_text.lower(), f"waiting state missing {expected}"
            page.screenshot(path=waiting_screenshot, full_page=True)

            fixture_state["mode"] = "applied"
            page.goto(url, wait_until="domcontentloaded")
            page.get_by_role("button", name="3. Allocation & Rebalance").click()
            page.wait_for_selector("text=APPLIED_PAPER", timeout=15000)
            applied_text = page.locator(".allocation-workstation-page").inner_text(timeout=10000)
            for expected in [
                "Plan Applied / Paper Effective",
                "APPLIED_PAPER",
                "Booked Transaction Cost",
                "Trade weight",
                "active-unallocated rows now paper-weighted",
                "Combined updated dynamically",
                "No Live/Brokerage Orders",
                "Historical P&L not rewritten",
            ]:
                assert expected.lower() in applied_text.lower(), f"applied state missing {expected}"
            page.screenshot(path=applied_screenshot, full_page=True)
            browser.close()
            assert not response_errors, f"resource errors: {response_errors}"
            assert not errors, f"console errors: {errors}"
            print(f"Phase 2C applied-state readiness smoke PASS screenshots={waiting_screenshot},{applied_screenshot}")
            return 0
        if "phase3a-monthly-auto-proposal" in url:
            screenshot_path = "D:/Global_Ai/release_global_ai_risk_manager_workstation/output/strategy_factory/phase3a_monthly_auto_proposal.png"
            page.get_by_role("button", name="3. Allocation & Rebalance").click()
            page.wait_for_selector("text=Monthly Auto Proposal", timeout=15000)
            page.get_by_role("button", name="Generate Monthly Proposal").click()
            page.wait_for_selector("text=MONTHLY_PROPOSAL_READY", timeout=15000)
            proposal_text = page.locator(".allocation-workstation-page").inner_text(timeout=10000)
            for expected in [
                "Monthly Auto Proposal",
                "MONTHLY_PROPOSAL_READY",
                "NOT_APPROVED",
                "No NAV/P&L Impact Yet",
                "No Live/Brokerage Orders",
                "Review Monthly Proposal",
            ]:
                assert expected.lower() in proposal_text.lower(), f"monthly proposal UI missing {expected}"
            page.get_by_role("button", name="Review Monthly Proposal").click()
            page.wait_for_selector("text=DRAFT_NOT_APPLIED", timeout=15000)
            state_after = page.evaluate(
                """async () => {
                    const r = await fetch('/api/paper-rebalance?ts=' + Date.now(), {cache: 'no-store'}).then(x => x.json());
                    const paper = r.paper_rebalance || {};
                    const proposal = (paper.monthly_proposal || {}).latest_proposal || {};
                    const draft = (paper.recommendation_review || {}).latest_draft || {};
                    return {
                        proposal_id: proposal.proposal_id,
                        proposal_status: proposal.status,
                        review_status: proposal.review_status,
                        rows: (proposal.rows || []).length,
                        no_live_orders: proposal.no_live_orders,
                        no_brokerage_orders: proposal.no_brokerage_orders,
                        nav_pnl_impact: proposal.nav_pnl_impact,
                        draft_status: draft.review_status,
                        draft_source: draft.source_recommendation_artifact,
                        current_target: paper.current_paper_target,
                        latest_cost_record: paper.latest_cost_record,
                    };
                }"""
            )
            assert state_after["proposal_id"], f"monthly proposal missing: {state_after}"
            assert state_after["proposal_status"] == "MONTHLY_PROPOSAL_READY", state_after
            assert state_after["review_status"] == "NOT_APPROVED", state_after
            assert state_after["rows"] > 0, state_after
            assert state_after["no_live_orders"] is True, state_after
            assert state_after["no_brokerage_orders"] is True, state_after
            assert state_after["nav_pnl_impact"] == "NONE_PROPOSAL_ONLY", state_after
            assert state_after["draft_status"] == "DRAFT_NOT_APPLIED", state_after
            assert str(state_after["draft_source"]).startswith("monthly_rebalance_proposal:"), state_after
            page.screenshot(path=screenshot_path, full_page=True)
            browser.close()
            assert not response_errors, f"resource errors: {response_errors}"
            assert not errors, f"console errors: {errors}"
            print(f"Phase 3A monthly auto proposal smoke PASS screenshot={screenshot_path} proposal={state_after['proposal_id']}")
            return 0
        if "final-system-verification" in url:
            out_dir = Path("D:/Global_Ai/release_global_ai_risk_manager_workstation/output/strategy_factory/final_verification")
            out_dir.mkdir(parents=True, exist_ok=True)
            api_state = page.evaluate(
                """async () => {
                    const health = await fetch('/api/health?ts=' + Date.now(), {cache: 'no-store'});
                    const snapshotResponse = await fetch('/api/operational-snapshot?ts=' + Date.now(), {cache: 'no-store'});
                    const paperResponse = await fetch('/api/paper-rebalance?ts=' + Date.now(), {cache: 'no-store'});
                    const snapshot = await snapshotResponse.json();
                    const paper = await paperResponse.json();
                    return {
                        health: health.status,
                        snapshotStatus: snapshotResponse.status,
                        paperStatus: paperResponse.status,
                        hasSessionState: !!snapshot.session_state,
                        strategyCount: (snapshot.strategies || []).length,
                        inventory: snapshot.strategy_entity_inventory || {},
                        hasRisk: !!(snapshot.risk_factor_summary || snapshot.risk_exposure || snapshot.factor_exposure),
                        hasContributors: !!(snapshot.top_contributors || snapshot.top_bottom_contributors || snapshot.performance_attribution),
                        monthlyProposal: ((paper.paper_rebalance || {}).monthly_proposal || {}).latest_proposal || null,
                        reviewDraft: ((paper.paper_rebalance || {}).recommendation_review || {}).latest_draft || null,
                        approvedPlan: ((paper.paper_rebalance || {}).approved_rebalance || {}).latest_plan || null,
                    };
                }"""
            )
            assert api_state["health"] == 200, api_state
            assert api_state["snapshotStatus"] == 200, api_state
            assert api_state["paperStatus"] == 200, api_state
            assert api_state["hasSessionState"], api_state
            assert api_state["strategyCount"] > 0, api_state

            page.get_by_role("button", name="1. Portfolio Command Center").click()
            page.wait_for_selector(".command-center", timeout=15000)
            command_text = page.locator(".command-center").inner_text(timeout=10000)
            for expected in [
                "Current Membership",
                "Top Contributors",
                "Master Portfolio Daily Performance",
                "Strategy Performance",
                "Rebalance Decision Center",
            ]:
                assert expected.lower() in command_text.lower(), f"Command Center missing {expected}"
            page.screenshot(path=str(out_dir / "command_center.png"), full_page=True)

            page.get_by_role("button", name="2. Strategy Monitor").click()
            page.wait_for_selector(".strategy-monitor-page", timeout=15000)
            monitor_text = page.locator(".strategy-monitor-page").inner_text(timeout=10000)
            for expected in ["Ordinary Active", "Combined", "Top-Level Active", "Strategy operational registry"]:
                assert expected.lower() in monitor_text.lower(), f"Strategy Monitor missing {expected}"
            assert "display-only label; canonical identity uses strategy_uid" in monitor_text.lower()
            page.screenshot(path=str(out_dir / "strategy_monitor.png"), full_page=True)

            page.get_by_role("button", name="3. Allocation & Rebalance").click()
            page.wait_for_selector(".allocation-workstation-page", timeout=15000)
            allocation_text = page.locator(".allocation-workstation-page").inner_text(timeout=10000)
            if "MONTHLY_PROPOSAL_READY" not in allocation_text:
                page.get_by_role("button", name="Generate Monthly Proposal").click()
                page.wait_for_selector("text=MONTHLY_PROPOSAL_READY", timeout=15000)
                allocation_text = page.locator(".allocation-workstation-page").inner_text(timeout=10000)
            for expected in [
                "Recommendation Only",
                "Monthly Auto Proposal",
                "MONTHLY_PROPOSAL_READY",
                "No NAV/P&L Impact Yet",
                "No Live/Brokerage Orders",
                "Backend session",
            ]:
                assert expected.lower() in allocation_text.lower(), f"Allocation missing {expected}"
            page.screenshot(path=str(out_dir / "allocation_rebalance.png"), full_page=True)

            page.get_by_role("button", name="4. Risk Factors & Exposure").click()
            page.wait_for_selector(".page", timeout=15000)
            risk_text = page.locator(".page").inner_text(timeout=10000)
            for expected in ["Risk", "Missing", "No portfolio impact"]:
                assert expected.lower() in risk_text.lower(), f"Risk Factors missing {expected}"
            page.screenshot(path=str(out_dir / "risk_factors.png"), full_page=True)

            page.get_by_role("button", name="8. Strategy Factory").click()
            page.wait_for_selector("text=Strategy Factory", timeout=15000)
            factory_text = page.locator(".strategy-factory-page").inner_text(timeout=10000)
            for expected in ["Best Variant Evidence", "Selected Strategy Action", "Generated Strategy Candidate Pool"]:
                assert expected.lower() in factory_text.lower(), f"Strategy Factory missing {expected}"
            page.screenshot(path=str(out_dir / "strategy_factory.png"), full_page=True)

            page.get_by_role("button", name="1. Portfolio Command Center").click()
            page.wait_for_selector(".command-center", timeout=15000)
            target = page.locator("[data-contributor-id]").first
            if not target.count():
                target = page.locator(".command-performance-table tbody tr").first
            target.click()
            page.wait_for_selector("#detailDrawer.open", timeout=15000)
            drawer_text = page.locator("#detailDrawer").inner_text(timeout=10000)
            assert "T15:45:00-04:00" not in drawer_text, "raw ISO timestamp visible in detail drawer"
            assert "Paper / Next Open" in drawer_text and "No Live Fill" in drawer_text, "paper-only drawer status missing"
            page.screenshot(path=str(out_dir / "strategy_detail_drawer.png"), full_page=True)

            fresh_state = page.evaluate(
                """async () => {
                    const r = await fetch('/api/paper-rebalance?ts=' + Date.now(), {cache: 'no-store'});
                    const p = (await r.json()).paper_rebalance || {};
                    const proposal = (p.monthly_proposal || {}).latest_proposal || {};
                    const draft = (p.recommendation_review || {}).latest_draft || {};
                    const approved = (p.approved_rebalance || {}).latest_plan || {};
                    return {
                        proposalStatus: proposal.status,
                        proposalRows: (proposal.rows || []).length,
                        reviewStatus: draft.review_status,
                        approvedStatus: approved.status || null,
                        currentTarget: p.current_paper_target,
                        latestCost: p.latest_cost_record,
                        liveBrokerageFill: p.live_brokerage_fill,
                        brokerageExecution: p.brokerage_execution,
                    };
                }"""
            )
            assert fresh_state["proposalStatus"] == "MONTHLY_PROPOSAL_READY", fresh_state
            assert fresh_state["proposalRows"] > 0, fresh_state
            assert fresh_state["liveBrokerageFill"] == "No", fresh_state
            assert fresh_state["brokerageExecution"] == "Disabled", fresh_state
            browser.close()
            assert not response_errors, f"resource errors: {response_errors}"
            assert not errors, f"console errors: {errors}"
            print(f"Final system verification smoke PASS screenshots={out_dir}")
            return 0
        if "ui-polish-strategy-monitor-factory-action" in url:
            page.get_by_role("button", name="2. Strategy Monitor").click()
            page.wait_for_selector("text=Ordinary Active", timeout=15000)
            monitor_text = page.locator(".strategy-monitor-page").inner_text(timeout=10000)
            for expected in [
                "Ordinary Active",
                "Combined",
                "Top-Level Active",
                "Top-Level Active = Ordinary Active + Combined",
                "Pending Approval",
                "Portfolio Candidates",
                "Active Unallocated",
                "Optimizer Eligible",
                "Pending approval and portfolio candidates are not active strategies.",
            ]:
                assert expected.lower() in monitor_text.lower(), f"Strategy Monitor polish missing {expected}"
            assert "Current Rows" not in page.locator(".strategy-monitor-kpis").inner_text(timeout=10000), "vague Current Rows card still shown as main KPI"
            candidate_text = page.locator(".portfolio-candidate-monitor").inner_text(timeout=10000)
            for expected in [
                "Strategy Factory Approval & Activation",
                "Pending Approval",
                "Candidate / Pending",
                "0.00%",
                "Recommendation Pending",
                "No impact until approved and rebalanced",
                "Approve & Activate Strategy",
            ]:
                assert expected.lower() in candidate_text.lower(), f"candidate monitor polish missing {expected}"
            layout_issues = page.evaluate(
                """() => {
                    const issues = [];
                    for (const selector of ['.strategy-monitor-panel tr', '.portfolio-candidate-monitor tr']) {
                        document.querySelectorAll(selector).forEach((row, index) => {
                            const rr = row.getBoundingClientRect();
                            if (!rr.width || !rr.height) return;
                            row.querySelectorAll('td, th, strong, span, button').forEach((child, childIndex) => {
                                const cr = child.getBoundingClientRect();
                                if (!cr.width || !cr.height) return;
                                if (cr.left < rr.left - 3 || cr.right > rr.right + 12) {
                                    issues.push(`${selector} overflow ${index}/${childIndex}`);
                                }
                            });
                        });
                    }
                    return issues.slice(0, 12);
                }"""
            )
            assert not layout_issues, f"long-name/row overflow issues: {layout_issues}"
            page.get_by_role("button", name="8. Strategy Factory").click()
            page.wait_for_selector("text=Selected Strategy Action", timeout=15000)
            action_text = page.locator(".selected-strategy-action-panel").inner_text(timeout=10000)
            expected_action = (
                "Approve & Activate Strategy"
                if "Pending Approval" in action_text
                else "View in Allocation & Rebalance"
                if "Active Unallocated" in action_text
                else "Proceed with Strategy"
            )
            assert expected_action in action_text, f"clear primary action missing: {expected_action}"
            assert "RECOMMENDATION_PENDING" not in action_text, "raw recommendation enum visible in selected action panel"
            assert "eligible_for_rebalance" not in action_text, "raw rebalance field visible in selected action panel"
            screenshot_path = "D:/Global_Ai/release_global_ai_risk_manager_workstation/output/strategy_factory/ui_polish_strategy_monitor_factory_action.png"
            page.screenshot(path=screenshot_path, full_page=True)
            browser.close()
            assert not response_errors, f"resource errors: {response_errors}"
            assert not errors, f"console errors: {errors}"
            print(f"Strategy Monitor + Factory action UI polish smoke PASS screenshot={screenshot_path}")
            return 0
        if "approve-activate-from-strategy-monitor" in url:
            page.get_by_role("button", name="2. Strategy Monitor").click()
            page.wait_for_selector("text=Pending Approval", timeout=15000)
            before = page.evaluate(
                """async () => {
                    const metricValue = label => {
                        const card = [...document.querySelectorAll('.strategy-monitor-kpis .metric-card')]
                            .find(node => ((node.querySelector('.metric-label') || {}).innerText || '').trim().toLowerCase() === String(label).toLowerCase());
                        const text = card ? ((card.querySelector('.metric-value') || card).innerText || '') : '';
                        const match = text.match(/-?\\d+/);
                        return match ? Number(match[0]) : null;
                    };
                    const r = await fetch('/api/strategy-factory/portfolio-candidates/status?ts=' + Date.now(), {cache: 'no-store'});
                    const j = await r.json();
                    const row = (j.pending_approval || [])[0] || {};
                    return {
                        ordinary: metricValue('Ordinary Active'),
                        combined: metricValue('Combined'),
                        topLevel: metricValue('Top-Level Active'),
                        pending: (j.pending_approval || []).length,
                        activeUnallocated: (j.active_unallocated || []).length,
                        name: row.strategy_name || row.variant_name || '',
                        runId: row.run_id || row.source_run_id || '',
                        variantId: row.variant_id || '',
                    };
                }"""
            )
            assert before["pending"] > 0, "no pending approval strategy available for monitor activation smoke"
            pending_row = page.locator(".pending-approval-row").filter(has_text=before["name"]).first
            if pending_row.count() == 0:
                pending_row = page.locator(".pending-approval-row").first
            page.once("dialog", lambda dialog: dialog.accept())
            pending_row.get_by_role("button", name="Approve & Activate Strategy").click()
            page.wait_for_function(
                """before => {
                    const metricValue = label => {
                        const card = [...document.querySelectorAll('.strategy-monitor-kpis .metric-card')]
                            .find(node => ((node.querySelector('.metric-label') || {}).innerText || '').trim().toLowerCase() === String(label).toLowerCase());
                        const text = card ? ((card.querySelector('.metric-value') || card).innerText || '') : '';
                        const match = text.match(/-?\\d+/);
                        return match ? Number(match[0]) : null;
                    };
                    return metricValue('Ordinary Active') === before.ordinary + 1
                        && metricValue('Top-Level Active') === before.topLevel + 1
                        && metricValue('Active Unallocated') === before.activeUnallocated + 1;
                }""",
                arg=before,
                timeout=20000,
            )
            after = page.evaluate(
                """async name => {
                    const metricValue = label => {
                        const card = [...document.querySelectorAll('.strategy-monitor-kpis .metric-card')]
                            .find(node => ((node.querySelector('.metric-label') || {}).innerText || '').trim().toLowerCase() === String(label).toLowerCase());
                        const text = card ? ((card.querySelector('.metric-value') || card).innerText || '') : '';
                        const match = text.match(/-?\\d+/);
                        return match ? Number(match[0]) : null;
                    };
                    const r = await fetch('/api/strategy-factory/portfolio-candidates/status?ts=' + Date.now(), {cache: 'no-store'});
                    const j = await r.json();
                    const active = (j.active_unallocated || []).find(row => (row.strategy_name || row.variant_name || '') === name) || (j.active_unallocated || [])[0] || {};
                    const activation = active.activation || {};
                    return {
                        ordinary: metricValue('Ordinary Active'),
                        combined: metricValue('Combined'),
                        topLevel: metricValue('Top-Level Active'),
                        pending: (j.pending_approval || []).length,
                        activeUnallocated: (j.active_unallocated || []).length,
                        activeName: active.strategy_name || active.variant_name || '',
                        currentWeight: active.current_weight,
                        targetWeight: active.target_weight,
                        eligibleForRebalance: active.eligible_for_rebalance || activation.eligible_for_rebalance,
                        liveTrading: active.live_trading || activation.live_trading,
                        brokerageExecution: active.brokerage_execution || activation.brokerage_execution,
                        activationConfirmation: activation.activation_confirmation,
                        activationSource: activation.activation_source,
                        hasUserConfirmedAt: Boolean(activation.user_confirmed_at),
                        hasActivationConfirmedAt: Boolean(activation.activation_confirmed_at),
                        navPnlImpact: active.nav_pnl_impact || activation.nav_pnl_impact || '',
                    };
                }""",
                before["name"],
            )
            assert after["ordinary"] == before["ordinary"] + 1, f"ordinary active count did not increase: before={before} after={after}"
            assert after["combined"] == before["combined"], f"combined count changed: before={before} after={after}"
            assert after["topLevel"] == before["topLevel"] + 1, f"top-level count did not increase: before={before} after={after}"
            assert after["pending"] == before["pending"] - 1, f"pending count did not decrease: before={before} after={after}"
            assert after["activeUnallocated"] == before["activeUnallocated"] + 1, f"active unallocated did not increase: before={before} after={after}"
            assert after["currentWeight"] in (0, 0.0, None), f"current weight not zero: {after}"
            assert after["targetWeight"] in (0, 0.0, None), f"target weight not zero: {after}"
            assert after["eligibleForRebalance"] is True, "activated strategy not rebalance eligible"
            assert after["liveTrading"] in (False, None), "live trading unexpectedly enabled"
            assert after["brokerageExecution"] in (False, None), "brokerage execution unexpectedly enabled"
            assert after["activationConfirmation"] is True, "activation confirmation lineage missing"
            assert after["activationSource"] == "USER_UI", "activation source is not USER_UI"
            assert after["hasUserConfirmedAt"] and after["hasActivationConfirmedAt"], "activation timestamps missing"
            assert "NONE" in after["navPnlImpact"].upper(), "NAV/P&L impact lineage missing"
            monitor_text = page.locator(".strategy-monitor-page").inner_text(timeout=10000)
            assert before["name"].lower() in monitor_text.lower(), "activated strategy missing from Strategy Monitor"
            page.get_by_role("button", name="3. Allocation & Rebalance").click()
            page.wait_for_selector("text=Paper Allocation Decision Center", timeout=15000)
            allocation_text = page.locator(".allocation-workstation-page").inner_text(timeout=10000)
            assert before["name"].split()[0].lower() in allocation_text.lower(), "activated strategy missing from Allocation & Rebalance"
            screenshot_path = "D:/Global_Ai/release_global_ai_risk_manager_workstation/output/strategy_factory/approve_activate_from_strategy_monitor.png"
            page.screenshot(path=screenshot_path, full_page=True)
            browser.close()
            assert not response_errors, f"resource errors: {response_errors}"
            assert not errors, f"console errors: {errors}"
            print(
                "Strategy Monitor approve activation smoke PASS "
                f"before={before} after={after} screenshot={screenshot_path}"
            )
            return 0
        if "compact-evidence-card-density-fix" in url:
            page.wait_for_selector(".compact-evidence-card", timeout=15000)
            status = page.evaluate(
                """() => {
                    const card = document.querySelector('.compact-evidence-card');
                    const pool = document.querySelector('.strategy-candidate-picker');
                    const workspace = [...document.querySelectorAll('.factory-section')].find(x => x.innerText.includes('Selected Variant / Evidence Workspace'));
                    const action = document.querySelector('.selected-strategy-action-panel');
                    const raw = 'PUBLIC_FALLBACK_PROTOTYPE_NOT_PIT_NOT_SURVIVORSHIP_BIAS_FREE';
                    const sectionTop = label => {
                        const node = [...document.querySelectorAll('.factory-section')].find(x => x.innerText.toLowerCase().includes(label.toLowerCase()));
                        return node ? node.getBoundingClientRect().top : -1;
                    };
                    const cardText = card ? card.innerText : '';
                    const cardTextLower = cardText.toLowerCase();
                    const rect = card ? card.getBoundingClientRect() : {height: 9999};
                    return {
                        height: rect.height,
                        hasBadges: ['PUBLIC FALLBACK', 'NOT PIT', 'NOT SURVIVORSHIP-FREE'].every(x => cardText.includes(x)),
                        rawVisible: cardText.includes(raw),
                        pathCollapsed: !!card && cardTextLower.includes('evidence artifact: available') && !cardText.match(/[A-Z]:\\\\.*variant_evidence_report\\.md/),
                        lineageClosed: [...document.querySelectorAll('.compact-lineage-details')].every(d => !d.open),
                        fullTextClosed: [...document.querySelectorAll('.compact-evidence-details')].every(d => !d.open),
                        order: {
                            evidence: sectionTop('Best Variant Evidence Card'),
                            ranking: sectionTop('Variant Ranking Table'),
                            workspace: sectionTop('Selected Variant / Evidence Workspace'),
                            action: sectionTop('Selected Strategy Action'),
                            pool: sectionTop('Generated Strategy Candidate Pool')
                        }
                    };
                }"""
            )
            assert status["height"] < 430, f"evidence card too tall: {status['height']}"
            assert status["hasBadges"], "data quality badges not visible in compact evidence card"
            assert not status["rawVisible"], "raw data quality enum is visible in main evidence card"
            assert status["pathCollapsed"], "evidence artifact path is not collapsed/truncated"
            assert status["lineageClosed"], "technical lineage details are open by default"
            assert status["fullTextClosed"], "full thesis/signal/readiness details are open by default"
            order = status["order"]
            assert all(value >= 0 for value in order.values()), f"missing Strategy Factory sections: {order}"
            assert order["evidence"] < order["ranking"] < order["workspace"] < order["action"] < order["pool"], f"candidate pool moved above normal workflow: {order}"
            screenshot_path = "D:/Global_Ai/release_global_ai_risk_manager_workstation/output/strategy_factory/compact_evidence_card_density_fix.png"
            page.screenshot(path=screenshot_path, full_page=True)
            browser.close()
            assert not response_errors, f"resource errors: {response_errors}"
            assert not errors, f"console errors: {errors}"
            print(f"Strategy Factory compact evidence card density smoke PASS height={status['height']} screenshot={screenshot_path}")
            return 0
        if "factory-workflow-top-candidate-pool-below" in url:
            page.wait_for_selector("text=Generated Strategy Candidate Pool", timeout=15000)
            status = page.evaluate(
                """async () => {
                    const r = await fetch('/api/strategy-factory?ts=' + Date.now(), {cache: 'no-store'});
                    const j = await r.json();
                    const rows = (j.candidate_picker || {}).candidates || [];
                    const text = document.body.innerText.toLowerCase();
                    const sectionIndex = label => text.indexOf(String(label).toLowerCase());
                    return {
                        count: rows.length,
                        names: rows.map(row => row.strategy_name || row.variant_name || row.variant_id),
                        variants: rows.map(row => row.variant_id),
                        source_ok: rows.every(row => row.run_id && row.variant_id && row.artifact_paths && row.artifact_paths.variant_spec),
                        order: {
                            intake: sectionIndex('Compact Intake Bar'),
                            decision: sectionIndex('Strategy Factory Decision Panel / Run Decision Summary'),
                            evidence: sectionIndex('Best Variant Evidence Card'),
                            workspace: sectionIndex('Selected Variant / Evidence Workspace'),
                            action: sectionIndex('Selected Strategy Action'),
                            pool: sectionIndex('Generated Strategy Candidate Pool'),
                            archives: sectionIndex('Debug / Archives')
                        }
                    };
                }"""
            )
            assert status["count"] > 0, "candidate pool payload is empty"
            assert status["source_ok"], "candidate pool rows missing artifact lineage"
            order = status["order"]
            assert all(value >= 0 for value in order.values()), f"missing expected sections: {order}"
            assert order["intake"] < order["decision"] < order["evidence"] < order["workspace"] < order["action"] < order["pool"] < order["archives"], f"wrong Strategy Factory section order: {order}"
            pool_text = page.locator(".strategy-candidate-picker").inner_text(timeout=10000)
            assert "Select / Load Candidate" in pool_text, "candidate pool missing Select / Load Candidate action"
            for forbidden in ["Proceed with Strategy", "Confirm Candidate", "Activate Strategy", "Approve & Activate Strategy", "View in Strategy Monitor"]:
                assert forbidden not in pool_text, f"candidate pool contains workflow action: {forbidden}"
            action_text = page.locator(".selected-strategy-action-panel").inner_text(timeout=10000)
            assert any(label in action_text for label in ["Proceed with Strategy", "Add to Portfolio Candidates", "Activate Strategy", "Approve & Activate Strategy", "Not eligible"]), "selected action panel missing workflow action/state"
            action_text_lower = action_text.lower()
            assert "strict gate details" in action_text_lower, "strict gate details are not collapsed under selected action panel"
            assert "show technical lineage" in action_text_lower, "technical lineage is not collapsed under selected action panel"
            rendered_rows = page.locator(".factory-candidate-picker-table tbody tr").count()
            assert rendered_rows == status["count"], f"rendered candidate rows {rendered_rows} != payload count {status['count']}"
            if status["count"] >= 2:
                for idx in [0, 1]:
                    row = page.locator(".factory-candidate-picker-table tbody tr").nth(idx)
                    variant_id = status["variants"][idx]
                    row.get_by_role("button", name="Select / Load Candidate").click()
                    page.wait_for_timeout(250)
                    assert variant_id in page.locator(".strategy-factory-page").inner_text(timeout=10000), f"selection {idx} did not update selected workflow"
            screenshot_path = "D:/Global_Ai/release_global_ai_risk_manager_workstation/output/strategy_factory/factory_workflow_top_candidate_pool_below.png"
            page.screenshot(path=screenshot_path, full_page=True)
            browser.close()
            assert not response_errors, f"resource errors: {response_errors}"
            assert not errors, f"console errors: {errors}"
            print(f"Strategy Factory workflow-top candidate-pool-below smoke PASS candidates={status['count']} screenshot={screenshot_path}")
            return 0
        if "dynamic-candidate-picker-no-hardcode" in url:
            page.wait_for_selector("text=Generated Strategy Candidate Pool", timeout=15000)
            status = page.evaluate(
                """async () => {
                    const r = await fetch('/api/strategy-factory?ts=' + Date.now(), {cache: 'no-store'});
                    const j = await r.json();
                    const rows = (j.candidate_picker || {}).candidates || [];
                    const pending = rows.filter(row => row.portfolio_state === 'PENDING_USER_APPROVAL');
                    const active = rows.filter(row => ['ACTIVE_UNALLOCATED', 'ACTIVE_PENDING_REBALANCE'].includes(row.portfolio_state));
                    return {
                        count: rows.length,
                        names: rows.map(row => row.strategy_name || row.variant_name || row.variant_id),
                        variants: rows.map(row => row.variant_id),
                        pending_count: pending.length,
                        active_count: active.length,
                        pending_index: rows.findIndex(row => row.portfolio_state === 'PENDING_USER_APPROVAL'),
                        low_vol_status: (rows.find(row => String(row.theme || '').includes('low_vol') && row.portfolio_state === 'PENDING_USER_APPROVAL') || {}).portfolio_state || '',
                        has_proceed: rows.some(row => row.proceed_status === 'PROCEED_ELIGIBLE'),
                        source_ok: rows.every(row => row.run_id && row.variant_id && row.artifact_paths && row.artifact_paths.variant_spec)
                    };
                }"""
            )
            assert status["count"] > 0, "candidate picker payload is empty"
            assert status["source_ok"], "candidate picker rows missing artifact lineage"
            assert status["has_proceed"], "no proceed-eligible generated candidate found"
            card_count = page.locator(".factory-picker-card").count()
            assert card_count == status["count"], f"rendered picker count {card_count} != payload count {status['count']}"
            page_text = page.locator(".strategy-factory-page").inner_text(timeout=10000)
            for name in status["names"][: min(5, len(status["names"]))]:
                assert name in page_text, f"candidate from registry not rendered: {name}"
            if status["count"] >= 2:
                first_card = page.locator(".factory-picker-card").nth(0)
                second_card = page.locator(".factory-picker-card").nth(1)
                first_variant = status["variants"][0]
                second_variant = status["variants"][1]
                first_card.click()
                page.wait_for_timeout(250)
                assert first_variant in page.locator(".strategy-factory-page").inner_text(timeout=10000), "first selection did not update evidence workspace"
                second_card.click()
                page.wait_for_timeout(250)
                assert second_variant in page.locator(".strategy-factory-page").inner_text(timeout=10000), "second selection did not update evidence workspace"
            if status["pending_count"]:
                pending_row = page.locator(".factory-candidate-picker-table tbody tr").nth(status["pending_index"])
                pending_row.get_by_role("button", name="Select / Load Candidate").click()
                page.wait_for_timeout(250)
                action_text = page.locator(".selected-strategy-action-panel").inner_text(timeout=10000)
                assert "Approve & Activate Strategy" in action_text, "pending approval action missing from selected action panel"
            assert status["active_count"] == 0, "unconfirmed/smoke pending records leaked into active count"
            screenshot_path = "D:/Global_Ai/release_global_ai_risk_manager_workstation/output/strategy_factory/dynamic_candidate_picker_no_hardcode.png"
            page.screenshot(path=screenshot_path, full_page=True)
            browser.close()
            assert not response_errors, f"resource errors: {response_errors}"
            assert not errors, f"console errors: {errors}"
            print(f"Strategy Factory dynamic candidate picker smoke PASS candidates={status['count']} active_count={status['active_count']} pending_count={status['pending_count']} screenshot={screenshot_path}")
            return 0
        if "user-consent-activation-hygiene" in url or "display-label-consent-fast-fix" in url:
            page.wait_for_selector("text=Strategy Factory Decision Panel", timeout=15000)
            page.wait_for_selector(".portfolio-candidate-card", timeout=15000)
            status = page.evaluate(
                """async () => {
                    const r = await fetch('/api/strategy-factory/portfolio-candidates/status?ts=' + Date.now(), {cache: 'no-store'});
                    const j = await r.json();
                    const labelOf = row => row.display_label || row.activation?.display_label || row.display_id || row.activation?.display_id || '';
                    const uidOf = row => row.strategy_uid || row.activation?.strategy_uid || '';
                    const pending = (j.pending_approval || [])[0] || {};
                    const pendingUid = uidOf(pending);
                    const active = (j.active_unallocated || []).filter(row => uidOf(row) && uidOf(row) === pendingUid);
                    return {
                        state: j.state,
                        pending_count: j.pending_approval_count || 0,
                        active_count: j.active_unallocated_count || 0,
                        pending_status: pending.status || '',
                        pending_name: pending.strategy_name || pending.variant_name || '',
                        pending_display_label: labelOf(pending),
                        pending_strategy_uid: pendingUid,
                        active_pending_uid_count: active.length,
                        has_user_confirmed_at: Boolean((pending.activation || {}).user_confirmed_at),
                        has_activation_confirmed_at: Boolean((pending.activation || {}).activation_confirmed_at),
                        activation_source: (pending.activation || {}).activation_source || '',
                        activation_confirmation: (pending.activation || {}).activation_confirmation === true
                    };
                }"""
            )
            if status["pending_count"]:
                assert status["pending_status"] == "PENDING_USER_APPROVAL", "selected pending row is not pending user approval"
                assert status["pending_display_label"], "pending display label missing"
                assert status["pending_strategy_uid"] and status["pending_strategy_uid"] != status["pending_display_label"], "strategy_uid missing or equal to display label"
                assert status["active_pending_uid_count"] == 0, "pending strategy_uid leaked into active_unallocated"
                assert status["has_activation_confirmed_at"] is False, "pending row unexpectedly has real activation confirmation"
                assert status["activation_source"] != "USER_UI" or status["activation_confirmation"] is False, "pending row has real USER_UI confirmation"
                card_text = page.locator(".portfolio-candidate-card").first.inner_text(timeout=10000)
                assert "Approve & Activate Strategy" in card_text, "manual approve button missing"
                assert "display label" in card_text.lower(), "display label metadata missing"
                assert "show technical lineage" in card_text.lower(), "technical lineage disclosure missing"
                assert "PENDING_USER_APPROVAL" in card_text, "Strategy Factory card missing pending state"
                page.get_by_role("button", name="2. Strategy Monitor").click()
                page.wait_for_selector("text=Pending User Approval", timeout=15000)
                monitor_text = page.locator(".strategy-monitor-page").inner_text(timeout=10000)
                assert status["pending_display_label"] in monitor_text, "pending display label missing from pending approval monitor"
                assert "PENDING_USER_APPROVAL" in monitor_text, "pending approval status missing from monitor"
                page.get_by_role("button", name="3. Allocation & Rebalance").click()
                page.wait_for_selector("text=Paper Allocation Decision Center", timeout=15000)
                allocation_text = page.locator(".allocation-workstation-page").inner_text(timeout=10000)
                assert status["pending_display_label"] not in allocation_text, "pending display label leaked into Allocation active rows"
                page.get_by_role("button", name="1. Portfolio Command Center").click()
                page.wait_for_selector("text=Current membership", timeout=15000)
                command_text = page.locator(".command-center").inner_text(timeout=10000)
                assert status["pending_display_label"] not in command_text, "pending display label leaked into Command Center active universe"
            screenshot_path = (
                "D:/Global_Ai/release_global_ai_risk_manager_workstation/output/strategy_factory/display_label_consent_fast_fix.png"
                if "display-label-consent-fast-fix" in url
                else "D:/Global_Ai/release_global_ai_risk_manager_workstation/output/strategy_factory/user_consent_activation_hygiene.png"
            )
            page.screenshot(path=screenshot_path, full_page=True)
            browser.close()
            assert not response_errors, f"resource errors: {response_errors}"
            assert not errors, f"console errors: {errors}"
            print(f"Strategy Factory user-consent activation hygiene smoke PASS active_count={status['active_count']} pending_count={status['pending_count']} screenshot={screenshot_path}")
            return 0
        if "phase1-portfolio-candidate-activation" in url:
            page.wait_for_selector("text=Strategy Factory Decision Panel", timeout=15000)
            page.wait_for_selector(".portfolio-candidate-card", timeout=15000)
            phase1_text = page.locator(".portfolio-candidate-card").first.inner_text(timeout=10000)
            assert "no live trading" in phase1_text.lower(), "Phase 1 card missing no-live-trading safety"
            assert "no brokerage" in phase1_text.lower(), "Phase 1 card missing no-brokerage safety"
            if "ACTIVE_UNALLOCATED" not in phase1_text:
                if "IN_PORTFOLIO_CANDIDATES" not in phase1_text:
                    add_button = page.get_by_role("button", name="Add to Portfolio Candidates").first
                    assert add_button.is_disabled(), "Add to Portfolio Candidates enabled before confirmation"
                    checkbox = page.locator("[data-factory-portfolio-candidate-confirm]").first
                    checkbox.click()
                    page.wait_for_selector("text=Confirmation checked. Add to Portfolio Candidates is enabled.", timeout=10000)
                    assert checkbox.is_checked(), "Portfolio Candidate confirmation checkbox did not visibly toggle"
                    add_button = page.get_by_role("button", name="Add to Portfolio Candidates").first
                    assert add_button.is_enabled(), "Add to Portfolio Candidates did not enable after confirmation"
                    add_button.click()
                    page.wait_for_selector("text=IN_PORTFOLIO_CANDIDATES", timeout=15000)
                activate_button = page.get_by_role("button", name="Activate Strategy").first
                assert activate_button.is_disabled(), "Activate Strategy enabled before second confirmation"
                activation_checkbox = page.locator("[data-factory-activation-confirm]").first
                activation_checkbox.click()
                page.wait_for_timeout(250)
                activation_checkbox = page.locator("[data-factory-activation-confirm]").first
                assert activation_checkbox.is_checked(), "Activation confirmation checkbox did not visibly toggle"
                activate_button = page.get_by_role("button", name="Activate Strategy").first
                assert activate_button.is_enabled(), "Activate Strategy did not enable after confirmation"
                activate_button.click()
                page.wait_for_selector("text=ACTIVE_UNALLOCATED", timeout=15000)
            page.get_by_role("button", name="2. Strategy Monitor").click()
            page.wait_for_selector("text=Portfolio Candidates / Watchlist", timeout=15000)
            monitor_text = page.locator(".portfolio-candidate-monitor").inner_text(timeout=10000)
            for expected in ["Active unallocated", "0.00%", "RECOMMENDATION_PENDING", "No NAV/P&L impact until nonzero weight is confirmed in rebalance."]:
                assert expected.lower() in monitor_text.lower(), f"Strategy Monitor Phase 1 section missing {expected}"
            screenshot_path = "D:/Global_Ai/release_global_ai_risk_manager_workstation/output/strategy_factory/phase1_portfolio_candidate_activation_smoke.png"
            page.screenshot(path=screenshot_path, full_page=True)
            browser.close()
            assert not response_errors, f"resource errors: {response_errors}"
            assert not errors, f"console errors: {errors}"
            print(f"Strategy Factory Phase 1 portfolio candidate activation smoke PASS screenshot={screenshot_path}")
            return 0
        if "phase2-dynamic-strategy-universe" in url or "anti-hardcode-proceed-strategy-gate" in url:
            page.wait_for_selector("text=Strategy Factory Decision Panel", timeout=15000)
            page.wait_for_selector(".portfolio-candidate-card", timeout=15000)
            phase1_text = page.locator(".portfolio-candidate-card").first.inner_text(timeout=10000)
            if "ACTIVE_UNALLOCATED" not in phase1_text:
                if "IN_PORTFOLIO_CANDIDATES" not in phase1_text:
                    button_name = "Proceed with Strategy" if "anti-hardcode-proceed-strategy-gate" in url else "Add to Portfolio Candidates"
                    add_button = page.get_by_role("button", name=button_name).first
                    assert add_button.is_disabled(), f"{button_name} enabled before confirmation"
                    checkbox = page.locator("[data-factory-portfolio-candidate-confirm]").first
                    checkbox.click()
                    page.wait_for_selector("text=Confirmation checked. Add to Portfolio Candidates is enabled.", timeout=10000)
                    add_button = page.get_by_role("button", name=button_name).first
                    assert add_button.is_enabled(), f"{button_name} did not enable after confirmation"
                    add_button.click()
                    page.wait_for_selector("text=IN_PORTFOLIO_CANDIDATES", timeout=15000)
                activate_button = page.get_by_role("button", name="Activate Strategy").first
                assert activate_button.is_disabled(), "Activate Strategy enabled before second confirmation"
                activation_checkbox = page.locator("[data-factory-activation-confirm]").first
                activation_checkbox.click()
                page.wait_for_timeout(250)
                activate_button = page.get_by_role("button", name="Activate Strategy").first
                assert activate_button.is_enabled(), "Activate Strategy did not enable after confirmation"
                activate_button.click()
                page.wait_for_selector("text=ACTIVE_UNALLOCATED", timeout=15000)
            status = page.evaluate(
                """async () => {
                    const r = await fetch('/api/strategy-factory/portfolio-candidates/status?ts=' + Date.now(), {cache: 'no-store'});
                    const j = await r.json();
                    const row = (j.active_unallocated || [])[0] || j.selected || {};
                    const activation = row.activation || {};
                    return {
                        display_id: activation.display_id || row.display_id || '',
                        strategy_name: row.strategy_name || row.variant_name || '',
                        candidate_id: row.candidate_id || '',
                        current_weight: row.current_weight,
                        target_weight: row.target_weight,
                        eligible_for_rebalance: row.eligible_for_rebalance || activation.eligible_for_rebalance
                    };
                }"""
            )
            display_id = status.get("display_id") or "#000018"
            strategy_name = status.get("strategy_name") or "Strategy Factory"

            page.get_by_role("button", name="2. Strategy Monitor").click()
            page.wait_for_selector("text=Strategy operational registry", timeout=15000)
            monitor_page_text = page.locator(".strategy-monitor-page").inner_text(timeout=10000)
            registry_text = page.locator(".strategy-monitor-panel").inner_text(timeout=10000)
            for expected in [
                display_id,
                "ACTIVE_UNALLOCATED",
                "WAITING_REBALANCE",
                "Strategy Factory",
                "0.00%",
                "ACTIVE_UNALLOCATED_WAITING_REBALANCE",
            ]:
                assert expected.lower() in monitor_page_text.lower(), f"Strategy Monitor missing {expected}"
            assert strategy_name.lower().split()[0] in registry_text.lower(), "activated strategy name missing from main registry"
            assert "Portfolio Candidates / Watchlist" in monitor_page_text, "watchlist section missing"
            assert "Active Unallocated Strategies" in monitor_page_text, "active unallocated section missing"
            assert "No NAV/P&L impact until nonzero weight is confirmed in rebalance." in monitor_page_text

            page.get_by_role("button", name="1. Portfolio Command Center").click()
            page.wait_for_selector("text=Current strategy universe", timeout=15000)
            command_text = page.locator(".command-center").inner_text(timeout=10000)
            for expected in [
                "Current strategy universe",
                "Allocated active",
                "Active unallocated",
                "Portfolio candidates",
                "Optimizer eligible",
                "Combined future eligible",
                "Current membership & allocation",
                "Recommended",
                "Top contributors & detractors",
                "Strategy Family Mix",
            ]:
                assert expected.lower() in command_text.lower(), f"Command Center missing {expected}"
            assert display_id.lower() in command_text.lower(), "activated strategy missing from command center tables"
            assert "active unallocated rows show $0 / N/A until rebalance allocation".lower() in command_text.lower(), "zero-weight P&L note missing"

            page.get_by_role("button", name="3. Allocation & Rebalance").click()
            page.wait_for_selector("text=Paper Allocation Decision Center", timeout=15000)
            allocation_text = page.locator(".allocation-workstation-page").inner_text(timeout=10000)
            for expected in [
                display_id,
                "0.00%",
                "OPTIMIZER_RECOMMENDED",
                "Initial recommendation for newly activated Strategy Factory strategy",
                "Estimated Cost",
                "No live order",
            ]:
                assert expected.lower() in allocation_text.lower(), f"Allocation & Rebalance missing {expected}"
            assert status.get("current_weight") in (0, 0.0, None), "activation current_weight is not zero"
            assert status.get("target_weight") in (0, 0.0, None), "activation target_weight is not zero"
            assert status.get("eligible_for_rebalance") is True, "activation is not rebalance eligible"

            screenshot_path = "D:/Global_Ai/release_global_ai_risk_manager_workstation/output/strategy_factory/anti_hardcode_proceed_strategy_gate.png" if "anti-hardcode-proceed-strategy-gate" in url else "D:/Global_Ai/release_global_ai_risk_manager_workstation/output/strategy_factory/phase2_dynamic_strategy_universe_smoke.png"
            page.screenshot(path=screenshot_path, full_page=True)
            browser.close()
            assert not response_errors, f"resource errors: {response_errors}"
            assert not errors, f"console errors: {errors}"
            print(f"Strategy Factory Phase 2 dynamic strategy universe smoke PASS display_id={display_id} screenshot={screenshot_path}")
            return 0
        if "phase2a-command-center-overflow-fix" in url:
            page.wait_for_selector("text=Strategy Factory Decision Panel", timeout=15000)
            page.wait_for_selector(".portfolio-candidate-card", timeout=15000)
            phase1_text = page.locator(".portfolio-candidate-card").first.inner_text(timeout=10000)
            if "ACTIVE_UNALLOCATED" not in phase1_text:
                if "IN_PORTFOLIO_CANDIDATES" not in phase1_text:
                    checkbox = page.locator("[data-factory-portfolio-candidate-confirm]").first
                    checkbox.click()
                    page.wait_for_selector("text=Confirmation checked. Add to Portfolio Candidates is enabled.", timeout=10000)
                    page.get_by_role("button", name="Add to Portfolio Candidates").first.click()
                    page.wait_for_selector("text=IN_PORTFOLIO_CANDIDATES", timeout=15000)
                activation_checkbox = page.locator("[data-factory-activation-confirm]").first
                activation_checkbox.click()
                page.wait_for_timeout(250)
                page.get_by_role("button", name="Activate Strategy").first.click()
                page.wait_for_selector("text=ACTIVE_UNALLOCATED", timeout=15000)
            status = page.evaluate(
                """async () => {
                    const r = await fetch('/api/strategy-factory/portfolio-candidates/status?ts=' + Date.now(), {cache: 'no-store'});
                    const j = await r.json();
                    const row = (j.active_unallocated || [])[0] || j.selected || {};
                    const activation = row.activation || {};
                    return {
                        display_id: activation.display_id || row.display_id || '',
                        strategy_name: row.strategy_name || row.variant_name || ''
                    };
                }"""
            )
            display_id = status.get("display_id") or "#000018"
            page.get_by_role("button", name="1. Portfolio Command Center").click()
            page.wait_for_selector("text=Current strategy universe", timeout=15000)
            page.wait_for_selector("text=Current membership & allocation", timeout=15000)
            command_text = page.locator(".command-center").inner_text(timeout=10000)
            for expected in [
                "Current strategy universe",
                "18",
                "Current membership & allocation",
                "Strategy performance",
                "Rebalance decision center",
                "Strategy Family Mix",
                display_id,
                "ACTIVE_UNALLOCATED",
                "0.00%",
                "OPTIMIZER_RECOMMENDED",
            ]:
                assert expected.lower() in command_text.lower(), f"Command Center overflow smoke missing {expected}"
            layout = page.evaluate(
                """() => {
                    const center = document.querySelector('.command-center');
                    const stage = document.querySelector('.main-stage');
                    const selectors = [
                        '.command-board .allocation-row',
                        '.command-performance-table tbody tr',
                        '.cmd-rebalance .allocation-decision-row',
                        '.cmd-factor .style-row'
                    ];
                    const issues = [];
                    if (center && center.scrollWidth > center.clientWidth + 8) issues.push('command-center horizontal overflow');
                    if (stage && stage.scrollWidth > stage.clientWidth + 24) issues.push('main-stage horizontal overflow');
                    for (const selector of selectors) {
                        document.querySelectorAll(selector).forEach((row, index) => {
                            const rr = row.getBoundingClientRect();
                            if (!rr.width || !rr.height) return;
                            if (rr.height > 62) issues.push(`${selector} row too tall ${index}: ${rr.height}`);
                            row.querySelectorAll('span, small, strong, b, em, td, label').forEach((child, childIndex) => {
                                const cr = child.getBoundingClientRect();
                                if (!cr.width || !cr.height) return;
                                if (cr.left < rr.left - 2 || cr.right > rr.right + 2) {
                                    issues.push(`${selector} child outside row ${index}/${childIndex}`);
                                }
                            });
                        });
                    }
                    return issues;
                }"""
            )
            assert not layout, f"visible overflow/overlap issues: {layout}"
            screenshot_path = "D:/Global_Ai/release_global_ai_risk_manager_workstation/output/strategy_factory/phase2a_command_center_overflow_fix.png"
            page.screenshot(path=screenshot_path, full_page=True)
            browser.close()
            assert not response_errors, f"resource errors: {response_errors}"
            assert not errors, f"console errors: {errors}"
            print(f"Strategy Factory Phase 2A Command Center overflow smoke PASS display_id={display_id} screenshot={screenshot_path}")
            return 0
        if "strategy-factory-ui-polish" in url:
            page.wait_for_selector("text=Strategy Factory Decision Panel", timeout=15000)
            page.wait_for_selector("text=Best Variant Evidence Card", timeout=15000)
            page.wait_for_selector("text=Strict Portfolio Admission", timeout=15000)
            page.wait_for_selector("text=Paper Sandbox Monitoring", timeout=15000)
            decision_text = page.locator(".factory-decision-panel").inner_text(timeout=10000)
            for expected in [
                "Best strategy candidate",
                "Current run id",
                "Selected material",
                "Strict admission state",
                "Candidate allowed",
                "Paper sandbox state",
                "Primary next action",
                "Research-only",
                "No live trading",
                "No brokerage execution",
                "Strict admission remains separate",
            ]:
                assert expected.lower() in decision_text.lower(), f"decision panel missing {expected}"
            evidence_text = page.locator(".factory-best-evidence-card").inner_text(timeout=10000)
            for expected in [
                "Thesis",
                "Signal formula",
                "Universe / proxy",
                "Benchmark",
                "Sharpe",
                "Annual return",
                "Max drawdown",
                "Evidence score",
                "ML summary",
                "Recommendation reason",
            ]:
                assert expected.lower() in evidence_text.lower(), f"best evidence card missing {expected}"
            admission_text = page.locator(".factory-admission-polish-grid").inner_text(timeout=10000)
            for expected in ["Strict Portfolio Admission", "Paper Sandbox Monitoring", "PAPER_ONLY", "NO_LIVE_TRADING", "NO_BROKERAGE"]:
                assert expected.lower() in admission_text.lower(), f"admission/sandbox polish missing {expected}"
            assert not page.locator("details[open]").filter(has_text="Global idea registry debug").count(), "debug/archive area is expanded by default"
            assert not page.locator("details[open]").filter(has_text="Intermediate current-run candidates - not ranked variants.").count(), "candidate archives are expanded by default"
            browser.close()
            assert not response_errors, f"resource errors: {response_errors}"
            assert not errors, f"console errors: {errors}"
            print("Strategy Factory operator browser smoke PASS")
            return 0
        if "add-to-portfolio-monitor" in url:
            page.wait_for_selector("text=Strategy Factory Decision Panel", timeout=15000)
            page.wait_for_selector("text=Portfolio Monitor", timeout=15000)
            strict_text = page.locator("article").filter(has_text="Strict Portfolio Admission").first.inner_text(timeout=10000)
            assert "BLOCKED" in strict_text, "strict admission should remain blocked for current copper"
            monitor_panel = page.locator(".monitoring-portfolio-card").first
            monitor_text = monitor_panel.inner_text(timeout=10000)
            assert "candidate allowed" in page.locator(".factory-decision-panel").inner_text(timeout=10000).lower(), "decision panel missing Candidate allowed"
            if "In Portfolio Monitor" not in monitor_text:
                add_button = monitor_panel.get_by_role("button", name="Add to Portfolio")
                assert add_button.is_disabled(), "Add to Portfolio enabled before confirmation"
                checkbox = monitor_panel.locator("[data-factory-sandbox-confirm]").first
                checkbox.click()
                page.wait_for_selector("text=Confirmation checked. Add to Portfolio is enabled.", timeout=10000)
                assert checkbox.is_checked(), "Portfolio Monitor confirmation checkbox did not visibly toggle"
                add_button = monitor_panel.get_by_role("button", name="Add to Portfolio")
                assert add_button.is_enabled(), "Add to Portfolio did not enable after confirmation"
                add_button.click()
                page.wait_for_selector("text=In Portfolio Monitor", timeout=15000)
            monitor_panel = page.locator(".monitoring-portfolio-card").first
            monitor_text = monitor_panel.inner_text(timeout=10000)
            for expected in [
                "In Portfolio Monitor",
                "Target weight",
                "Pending first refresh",
                "No Live Trading",
                "No Brokerage",
                "View in Strategy Monitor",
            ]:
                assert expected.lower() in monitor_text.lower(), f"Portfolio Monitor card missing {expected}"
            page.get_by_role("button", name="View in Strategy Monitor").click()
            page.wait_for_selector("text=Portfolio Monitor - Research Strategies", timeout=15000)
            strategy_monitor_text = page.locator(".research-monitoring-portfolio").inner_text(timeout=10000)
            for expected in ["Portfolio-monitored strategy", "Target weight", "Sharpe", "Annual return", "Max drawdown", "Pending first refresh", "View Evidence"]:
                assert expected.lower() in strategy_monitor_text.lower(), f"Strategy Monitor missing {expected}"
            page.get_by_role("button", name="1. Portfolio Command Center").click()
            page.wait_for_selector("text=Research Strategies in Portfolio Monitor", timeout=15000)
            command_text = page.locator(".research-monitoring-command").inner_text(timeout=10000)
            for expected in ["Research strategies monitored", "Total target weight", "Best strategy by Sharpe", "Latest refresh status"]:
                assert expected.lower() in command_text.lower(), f"Command Center monitor summary missing {expected}"
            screenshot_path = "D:/Global_Ai/release_global_ai_risk_manager_workstation/output/strategy_factory/add_to_portfolio_monitor_smoke.png"
            page.screenshot(path=screenshot_path, full_page=True)
            browser.close()
            assert not response_errors, f"resource errors: {response_errors}"
            assert not errors, f"console errors: {errors}"
            print(f"Strategy Factory add-to-portfolio monitor smoke PASS screenshot={screenshot_path}")
            return 0
        else:
            page.wait_for_selector("text=Run Decision Summary", timeout=15000)
        page.wait_for_selector("text=Variant Ranking Table", timeout=15000)
        page.wait_for_selector("text=Selected Variant / Evidence Workspace", timeout=15000)
        page.wait_for_selector("text=Review Mode", timeout=15000)
        page.wait_for_selector("text=Expand Material Library", timeout=15000)
        assert not page.locator(".factory-review-intake[open]").count(), "Material Library is expanded in Review Mode"
        assert not page.locator("#factoryCandidateWorkspace:visible").count(), "Candidate debug workspace is visible by default"
        assert not page.locator("text=Intermediate current-run candidates - not ranked variants.").is_visible(), "Debug archives are expanded by default"
        before_hash = page.evaluate("window.location.hash")

        page.locator('[data-factory-workspace-tab="Evidence"]').click()
        evidence_placeholder = page.locator(".factory-workspace-body").inner_text(timeout=10000)
        assert "Click View Evidence to load selected variant evidence." in evidence_placeholder, "Evidence tab implies missing artifact before load"
        assert "Missing Evidence" not in evidence_placeholder, "Evidence tab shows Missing Evidence even though artifact exists"
        assert page.evaluate("window.location.hash") == before_hash, "Evidence tab changed URL hash"

        page.locator('[data-factory-workspace-tab="Backtest"]').click()
        backtest_text = page.locator(".factory-workspace-body").inner_text(timeout=10000)
        for expected in ["Status", "Provider/data mode", "Symbols used", "Date range", "Sharpe", "Annual return", "Max drawdown", "Benchmark return", "Artifact source"]:
            assert expected.lower() in backtest_text.lower(), f"Backtest tab missing {expected}"
        assert "[object Object]" not in backtest_text, "Backtest tab shows raw date_range object"
        assert page.evaluate("window.location.hash") == before_hash, "Backtest tab changed URL hash"

        page.locator('[data-factory-workspace-tab="ML"]').click()
        ml_text = page.locator(".factory-workspace-body").inner_text(timeout=10000)
        for expected in ["ML status", "Model", "IC", "Hit rate", "Prediction quality", "Feature importance top 5", "Leakage check", "Artifact source"]:
            assert expected.lower() in ml_text.lower(), f"ML tab missing {expected}"
        assert "ML diagnostics are mixed/weak; not sufficient for Candidate." in ml_text, "ML interpretation missing"
        assert page.evaluate("window.location.hash") == before_hash, "ML tab changed URL hash"

        page.locator('[data-factory-workspace-tab="Robustness"]').click()
        robustness_text = page.locator(".factory-workspace-body").inner_text(timeout=10000)
        for expected in ["Overall robustness status", "Cost sensitivity", "Lookback sensitivity", "Benchmark comparison", "Key weakness", "Artifact source"]:
            assert expected.lower() in robustness_text.lower(), f"Robustness tab missing {expected}"
        assert "Robustness is WATCH, so Candidate admission remains blocked." in robustness_text, "Robustness interpretation missing"
        assert page.evaluate("window.location.hash") == before_hash, "Robustness tab changed URL hash"

        page.evaluate("document.querySelector('.main-stage').scrollTop = 120")
        before_hash = page.evaluate("window.location.hash")
        before_main_scroll = page.evaluate("document.querySelector('.main-stage').scrollTop")
        page.get_by_text("Expand Material Library").click()
        page.wait_for_selector(".factory-review-intake[open]", timeout=10000)
        page.get_by_role("button", name="Clear selection").click()
        page.wait_for_selector(".factory-review-intake[open]", timeout=10000)
        assert "Selected 0" in page.locator(".factory-selected-count").inner_text(), "selected count did not clear"
        material_window = page.locator(".factory-material-window").first
        assert material_window.count(), "material table window missing"
        page.evaluate("document.querySelector('.factory-material-window').scrollTop = 120")
        checkbox_count = page.locator("[data-factory-material-id]").count()
        assert checkbox_count, "no material checkbox found"
        first_checkbox = page.locator("[data-factory-material-id]").nth(min(8, checkbox_count - 1))
        first_checkbox.scroll_into_view_if_needed()
        before_material_scroll = page.evaluate("document.querySelector('.factory-material-window').scrollTop")
        first_checkbox.click()
        page.wait_for_selector(".factory-review-intake[open]", timeout=10000)
        assert "Selected 1" in page.locator(".factory-selected-count").inner_text(), "selected count did not increment"
        after_material_scroll = page.evaluate("document.querySelector('.factory-material-window').scrollTop")
        assert abs(after_material_scroll - before_material_scroll) < 60, "material table scroll jumped after checkbox"
        first_checkbox = page.locator("[data-factory-material-id]").nth(min(8, checkbox_count - 1))
        first_checkbox.click()
        page.wait_for_selector(".factory-review-intake[open]", timeout=10000)
        assert "Selected 0" in page.locator(".factory-selected-count").inner_text(), "selected count did not decrement"
        page.get_by_role("button", name="Select all visible").click()
        page.wait_for_selector(".factory-review-intake[open]", timeout=10000)
        selected_text = page.locator(".factory-selected-count").inner_text()
        assert selected_text != "Selected 0", "select all visible did not update selected count"
        page.get_by_role("button", name="Clear selection").click()
        page.wait_for_selector(".factory-review-intake[open]", timeout=10000)
        assert "Selected 0" in page.locator(".factory-selected-count").inner_text(), "clear selection collapsed or failed"
        assert page.evaluate("window.location.hash") == before_hash, "material selection changed URL hash"
        assert abs(page.evaluate("document.querySelector('.main-stage').scrollTop") - before_main_scroll) < 80, "material selection jumped main-stage scroll"

        page.evaluate("document.querySelector('.main-stage').scrollTop = 420")
        page.get_by_role("button", name="View Evidence").first.scroll_into_view_if_needed()
        before_hash = page.evaluate("window.location.hash")
        before_scroll = page.evaluate("document.querySelector('.main-stage').scrollTop")

        page.get_by_role("button", name="View Evidence").first.click()
        page.wait_for_selector(".factory-styled-report-viewer", timeout=10000)
        page.wait_for_selector("text=Executive Summary", timeout=10000)
        page.wait_for_selector("text=Final Decision", timeout=10000)
        assert page.locator('[data-factory-workspace-tab="Evidence"].active').count(), "View Evidence did not switch workspace to Evidence tab"
        evidence_text = page.locator(".factory-styled-report-viewer").first.inner_text(timeout=10000)
        after_hash = page.evaluate("window.location.hash")
        after_scroll = page.evaluate("document.querySelector('.main-stage').scrollTop")
        assert evidence_text.strip(), "evidence report content did not render"
        assert before_hash == after_hash, "View Evidence changed URL hash"
        assert abs(after_scroll - before_scroll) < 80, "View Evidence jumped scroll position"

        page.get_by_role("button", name="Open Ranking Report").first.scroll_into_view_if_needed()
        before_scroll = page.evaluate("document.querySelector('.main-stage').scrollTop")
        page.get_by_role("button", name="Open Ranking Report").first.click()
        page.wait_for_selector("text=Variant Ranking Report", timeout=10000)
        ranking_text = page.locator(".factory-styled-report-viewer").first.inner_text(timeout=10000)
        assert "ranking" in ranking_text.lower() or "variant" in ranking_text.lower(), "ranking report content did not render"
        assert page.evaluate("window.location.hash") == before_hash, "Open Ranking Report changed URL hash"
        assert abs(page.evaluate("document.querySelector('.main-stage').scrollTop") - before_scroll) < 80, "Open Ranking Report jumped scroll position"

        page.locator('[data-factory-workspace-tab="Provenance"]').click()
        page.wait_for_selector("text=Artifact availability checklist", timeout=10000)
        provenance_text = page.locator(".factory-workspace-body").inner_text(timeout=10000)
        for expected in ["Source run", "Variant id", "Data mode", "Data decision", "Symbols", "Date range", "Metrics", "ML diagnostics", "Robustness", "Evidence report", "Decision"]:
            assert expected.lower() in provenance_text.lower(), f"Provenance tab missing {expected}"
        assert page.evaluate("window.location.hash") == before_hash, "Provenance tab changed URL hash"

        assert page.locator("text=Existing old drafts").count(), "old drafts section missing"
        strict_admission = page.get_by_role("button", name="Add to Portfolio Review")
        if strict_admission.count():
            assert strict_admission.first.is_disabled(), "strict candidate admission button is enabled"
        else:
            page.wait_for_selector("text=Selected Strategy Action", timeout=10000)
            assert page.locator("text=Strict gate is separate from simulated portfolio workflow.").count(), "strict gate separation copy missing"
            assert (
                page.get_by_role("button", name="Proceed with Strategy").count()
                or page.get_by_role("button", name="Activate Strategy").count()
                or page.get_by_role("button", name="View in Strategy Monitor").count()
                or page.get_by_role("button", name="View in Allocation & Rebalance").count()
            ), "current Strategy Factory action CTA missing"

        if "sandbox-eligibility-confirmation" in url or "sandbox-evidence-detail" in url:
            page.get_by_text("Paper Sandbox Monitoring").first.scroll_into_view_if_needed()
            before_hash = page.evaluate("window.location.hash")
            before_scroll = page.evaluate("document.querySelector('.main-stage').scrollTop")
            sandbox_panel = page.locator("article").filter(has_text="Paper Sandbox Monitoring").first
            sandbox_text = sandbox_panel.inner_text(timeout=10000)
            sandbox_text_lower = sandbox_text.lower()
            assert page.locator("text=Strict Portfolio Admission").count(), "strict admission panel missing"
            assert "BLOCKED" in page.locator("article").filter(has_text="Strict Portfolio Admission").first.inner_text(timeout=10000), "strict copper admission is not blocked"
            if "SANDBOX_MONITORING" not in sandbox_text:
                assert "sandbox eligible?" in sandbox_text_lower, "sandbox eligibility field missing"
                assert "true" in sandbox_text_lower, "current Watch variant is not sandbox eligible"
                sandbox_button = sandbox_panel.get_by_role("button", name="Add to Paper Sandbox")
                assert sandbox_button.is_disabled(), "sandbox button enabled before confirmation"
                checkbox = sandbox_panel.locator("[data-factory-sandbox-confirm]").first
                checkbox.click()
                page.wait_for_selector("text=Confirmation checked. Add to Paper Sandbox is enabled.", timeout=10000)
                assert checkbox.is_checked(), "sandbox confirmation checkbox did not visibly toggle"
                sandbox_button = sandbox_panel.get_by_role("button", name="Add to Paper Sandbox")
                assert sandbox_button.is_enabled(), "sandbox button did not enable after confirmation"
                assert page.evaluate("window.location.hash") == before_hash, "sandbox confirmation changed URL hash"
                assert abs(page.evaluate("document.querySelector('.main-stage').scrollTop") - before_scroll) < 100, "sandbox confirmation jumped scroll"
                sandbox_button.click()
                page.wait_for_selector("text=SANDBOX_MONITORING", timeout=15000)
                page.wait_for_selector("text=Paper sandbox sleeve id", timeout=10000)
            sandbox_text = sandbox_panel.inner_text(timeout=10000)
            for expected in [
                "SANDBOX_MONITORING",
                "sandbox_id",
                "Paper sandbox sleeve id",
                "Target weight",
                "Estimated transaction cost",
                "Combined recompute requested",
                "Strategy Monitor",
                "Allocation/Rebalance",
                "Portfolio NAV/P&L",
                "Risk Contribution",
                "Correlation",
                "Combined Strategy",
            ]:
                assert expected.lower() in sandbox_text.lower(), f"sandbox panel missing {expected}"
            assert page.evaluate("window.location.hash") == before_hash, "sandbox add changed URL hash"

            if "sandbox-evidence-detail" in url:
                evidence_button = sandbox_panel.get_by_role("button", name="View Sandbox Evidence")
                assert evidence_button.is_enabled(), "View Sandbox Evidence is not enabled after sandbox monitoring"
                before_hash = page.evaluate("window.location.hash")
                before_scroll = page.evaluate("document.querySelector('.main-stage').scrollTop")
                evidence_button.click()
                page.wait_for_selector("text=Sandbox Evidence Detail", timeout=10000)
                evidence_text = page.locator(".factory-sandbox-evidence-detail").inner_text(timeout=10000)
                for expected in [
                    "Strategy summary",
                    "Why sandbox-only",
                    "Metrics table",
                    "Sharpe",
                    "Max drawdown",
                    "Annualized return",
                    "ML method",
                    "Risk warnings",
                    "Next validation steps",
                    "Artifact IDs / lineage",
                    "run_id",
                    "variant_id",
                    "sandbox_id",
                    "Official paper ledger, official NAV, official Combined sleeve, live trading, and brokerage execution remain untouched.",
                ]:
                    assert expected.lower() in evidence_text.lower(), f"sandbox evidence detail missing {expected}"
                assert "Missing Evidence" in evidence_text or "ridge" in evidence_text.lower(), "missing/available ML evidence state not rendered"
                assert page.evaluate("window.location.hash") == before_hash, "View Sandbox Evidence changed URL hash"
                assert abs(page.evaluate("document.querySelector('.main-stage').scrollTop") - before_scroll) < 100, "View Sandbox Evidence jumped scroll"

        browser.close()

    assert not response_errors, f"resource errors: {response_errors}"
    assert not errors, f"console errors: {errors}"
    print("Strategy Factory operator browser smoke PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
