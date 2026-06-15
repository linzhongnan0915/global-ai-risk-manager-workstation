"""Browser regression checks for dashboard proposal/workflow/breach semantics."""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERIFY_PORT = 8769
BASE_URL = f"http://127.0.0.1:{VERIFY_PORT}/dashboard/index.html"


def _start_verify_server() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "run_workstation_server.py"), "--port", str(VERIFY_PORT)],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_for_server(timeout_seconds: int = 25) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{VERIFY_PORT}/api/health", timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"Workstation server did not start on port {VERIFY_PORT}")


SEMANTICS_JS = """
() => {
  const governance = (document.getElementById('governanceFlow')?.innerText || '').toLowerCase();
  const approval = (document.getElementById('approvalStatusBar')?.innerText || '').toLowerCase();
  const allocationChecks = (document.getElementById('allocationPersistentChecks')?.innerText || '').toLowerCase();
  const command = (document.getElementById('commandDataQuality')?.innerText || '').toLowerCase();
  const factorPanel = document.querySelector('.tab-panel[data-tab-panel="Risk Factors & Exposure"]');
  const factorTitle = document.querySelector('#riskContribution')?.closest('.panel')?.querySelector('.panel-title')?.innerText?.toLowerCase() || '';
  const reportStrip = (document.getElementById('reportStatusStrip')?.innerText || '').toLowerCase();
  const parseCount = (text, label) => {
    const match = text.match(new RegExp(label + '\\\\s*(\\\\d+)', 'i'));
    return match ? Number(match[1]) : null;
  };
  return {
    governance,
    approval,
    allocationChecks,
    command,
    factorTitle,
    reportStrip,
    currentPortfolioBreaches: parseCount(allocationChecks, 'current portfolio breaches'),
    proposalGateBlockers: parseCount(allocationChecks, 'proposal gate blockers'),
    currentModelIssues: parseCount(reportStrip, 'current-model issues'),
    researchQualityIssues: parseCount(reportStrip, 'research quality'),
    dataQualityIssues: parseCount(reportStrip, 'data quality'),
    governanceIssues: parseCount(reportStrip, 'governance'),
  };
}
"""


DISPLAY_JS = """
() => {
  const researchText = (document.getElementById('researchChecklist')?.innerText || '').trim();
  const monitorKpi = (document.getElementById('monitorKpiStrip')?.innerText || '').toLowerCase();
  const memo = (document.getElementById('dailyRiskMemo')?.innerText || '').toLowerCase();
  const issues = document.getElementById('reportIssuesTable')?.innerText || '';
  const rawKeys = ['equity_beta', 'credit_spread', 'rates_duration', 'factor_herfindahl'];
  return {
    researchChecklistPopulated: researchText.length > 0,
    researchChecklistExplicitUnavailable: /unavailable/i.test(researchText),
    researchChecklistHasSection: /summary statistics|analyst prompt/i.test(researchText),
    riskChecklistExists: Boolean(document.getElementById('riskChecklist')),
    monitorHasAllocatedStrategyBreaches: monitorKpi.includes('allocated strategy breaches'),
    reportHasRawKeys: rawKeys.some((key) => memo.includes(key)),
    hasPortfolioPortfolio: issues.includes('Portfolio · Portfolio'),
  };
}
"""


def main() -> int:
    server = _start_verify_server()
    report: dict = {"checks": {}, "console_errors": [], "pass": False}
    try:
        _wait_for_server()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})

            def capture_console(msg):
                if msg.type == "error":
                    text = msg.text or ""
                    if "favicon.ico" not in text:
                        report["console_errors"].append(text)

            page.on("console", capture_console)
            page.goto(BASE_URL, wait_until="load", timeout=120000)
            page.wait_for_timeout(1500)

            page.click('button[data-tab="Allocation & Rebalance"]')
            page.wait_for_timeout(400)
            page.click("#resetWeights")
            page.wait_for_timeout(900)
            page.click('button[data-tab="Daily Risk Report / Decision Log"]')
            page.wait_for_timeout(700)
            reset_state = page.evaluate(SEMANTICS_JS)

            report["checks"]["no_rebalance_workflow_not_submitted"] = (
                "submitted for independent risk review" not in reset_state["governance"]
                and "pending human decision" not in reset_state["governance"]
            )
            report["checks"]["no_rebalance_workflow_monitoring_copy"] = (
                "no active rebalance proposal" in reset_state["governance"]
                and "monitoring acknowledgement only" in reset_state["governance"]
                and "not required" in reset_state["governance"]
            )
            report["checks"]["no_rebalance_allocation_consistent"] = (
                "no rebalance proposed" in reset_state["approval"]
                and "no rebalance proposed" in reset_state["command"]
            )
            report["checks"]["current_portfolio_breaches_visible_with_clear_gate"] = (
                (reset_state["currentPortfolioBreaches"] or 0) > 0
                and "proposal gate status: clear" in reset_state["approval"]
                and (reset_state["proposalGateBlockers"] or 0) == 0
            )

            page.click('button[data-tab="Allocation & Rebalance"]')
            page.wait_for_timeout(400)
            page.click("#useSystemProposal")
            page.wait_for_timeout(2500)
            page.click('button[data-tab="Daily Risk Report / Decision Log"]')
            page.wait_for_timeout(700)
            system_state = page.evaluate(SEMANTICS_JS)
            report["checks"]["system_proposal_activates_workflow"] = (
                "no rebalance proposed" not in system_state["approval"]
                and "no active rebalance proposal" not in system_state["governance"]
            )

            page.click('button[data-tab="Allocation & Rebalance"]')
            page.wait_for_timeout(400)
            page.click("#resetWeights")
            page.wait_for_timeout(900)
            page.click('button[data-tab="Daily Risk Report / Decision Log"]')
            page.wait_for_timeout(700)
            after_reset = page.evaluate(SEMANTICS_JS)
            report["checks"]["reset_returns_no_active_proposal"] = (
                "no active rebalance proposal" in after_reset["governance"]
                and "no rebalance proposed" in after_reset["approval"]
            )

            page.click('button[data-tab="Risk Factors & Exposure"]')
            page.wait_for_timeout(500)
            factor_state = page.evaluate(SEMANTICS_JS)
            report["checks"]["factor_panel_exposure_share_label"] = (
                "factor exposure share" in factor_state["factorTitle"]
                and "factor contribution to portfolio risk" not in factor_state["factorTitle"]
            )

            page.click('button[data-tab="Daily Risk Report / Decision Log"]')
            page.wait_for_timeout(500)
            issue_state = page.evaluate(SEMANTICS_JS)
            report["checks"]["issue_counts_separated"] = (
                issue_state["currentModelIssues"] is not None
                and issue_state["researchQualityIssues"] is not None
                and issue_state["dataQualityIssues"] is not None
                and issue_state["governanceIssues"] is not None
            )
            report["checks"]["current_model_excludes_research_from_totals"] = (
                (issue_state["currentModelIssues"] or 0) < (issue_state["researchQualityIssues"] or 0)
                or (issue_state["researchQualityIssues"] or 0) == 0
            )
            report["checks"]["command_report_proposal_consistent_after_reset"] = (
                "no rebalance proposed" in issue_state["command"]
                and "no rebalance proposed" in issue_state["approval"]
            )

            page.click('button[data-tab="Backtesting & Research Lab"]')
            page.wait_for_timeout(800)
            display_state = page.evaluate(DISPLAY_JS)
            report["checks"]["research_checklist_rendered_or_unavailable"] = (
                display_state["researchChecklistHasSection"]
                or display_state["researchChecklistExplicitUnavailable"]
            )
            report["checks"]["research_checklist_not_wrong_target"] = (
                not display_state["riskChecklistExists"] or display_state["researchChecklistPopulated"]
            )

            page.click('button[data-tab="Strategy Monitor"]')
            page.wait_for_timeout(500)
            display_state = page.evaluate(DISPLAY_JS)
            report["checks"]["monitor_kpi_allocated_strategy_breaches_label"] = (
                display_state["monitorHasAllocatedStrategyBreaches"]
            )

            page.click('button[data-tab="Daily Risk Report / Decision Log"]')
            page.wait_for_timeout(700)
            display_state = page.evaluate(DISPLAY_JS)
            report["checks"]["report_no_raw_metric_keys"] = not display_state["reportHasRawKeys"]
            report["checks"]["no_portfolio_portfolio_subject_label"] = not display_state["hasPortfolioPortfolio"]

            report["checks"]["no_console_errors"] = len(report["console_errors"]) == 0

            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()

    report["pass"] = all(report["checks"].values())
    print(json.dumps(report, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
