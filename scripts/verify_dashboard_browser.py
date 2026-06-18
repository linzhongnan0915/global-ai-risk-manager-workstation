"""Browser verification for the Risk Manager workstation."""

from __future__ import annotations

import argparse
import json
import math
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCREENSHOT_DIR = PROJECT_ROOT / "output" / "browser_verification"
REPORT_PATH = PROJECT_ROOT / "output" / "browser_verification" / "verification_report.json"

TABS = [
  "Portfolio Command Center",
  "Strategy Monitor",
  "Allocation & Rebalance",
  "Risk Factors & Exposure",
  "Correlation & Diversification",
  "Workflow & Shadow-Live Testing",
  "Backtesting & Research Lab",
  "Strategy Library & Governance",
  "Daily Risk Report / Decision Log",
]

VIEWPORTS = (
  (1920, 1080),
  (1440, 900),
  (1366, 768),
)

VERIFY_PORT = 8767
BASE_URL = f"http://127.0.0.1:{VERIFY_PORT}"

GEOMETRY_JS = """
() => {
  const doc = document.documentElement;
  const pageOverflow = doc.scrollWidth <= doc.clientWidth + 1;
  const topbar = document.querySelector('.topbar');
  const brand = document.querySelector('.brand');
  const tabButtons = [...document.querySelectorAll('.nav-rail button[data-tab]')];
  const drawer = document.getElementById('riskDrawer');
  const mainStage = document.querySelector('.main-stage');
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;
  const scrollers = [...document.querySelectorAll('*')].filter((node) => {
    if (!node || node === document.body || node === doc) return false;
    const style = window.getComputedStyle(node);
    const overflowY = style.overflowY;
    const overflowX = style.overflowX;
    const scrollableY = (overflowY === 'auto' || overflowY === 'scroll') && node.scrollHeight > node.clientHeight + 1;
    const scrollableX = (overflowX === 'auto' || overflowX === 'scroll') && node.scrollWidth > node.clientWidth + 1;
    return scrollableY || scrollableX;
  }).map((node) => ({
    tag: node.tagName.toLowerCase(),
    id: node.id || null,
    className: node.className || null,
    scrollHeight: node.scrollHeight,
    clientHeight: node.clientHeight,
    scrollWidth: node.scrollWidth,
    clientWidth: node.clientWidth,
  }));
  const primaryVertical = scrollers.filter((node) => node.className && String(node.className).includes('main-stage'));
  const approvedHorizontal = scrollers.filter((node) => {
    const cls = String(node.className || '');
    return cls.includes('table-scroll') || cls.includes('matrix-scroll') || cls.includes('mini-matrix') || cls.includes('table-viewport');
  });
  const headerOk = topbar && topbar.scrollWidth <= topbar.clientWidth + 1;
  const brandRect = brand ? brand.getBoundingClientRect() : null;
  const brandVisible = brandRect
    ? brandRect.top >= 0 && brandRect.bottom <= viewportHeight && brandRect.left >= 0 && brandRect.right <= viewportWidth
    : false;
  const tabsVisible = tabButtons.every((button) => {
    const rect = button.getBoundingClientRect();
    return rect.left >= 0 && rect.right <= viewportWidth + 0.5 && rect.width >= 48;
  });
  const drawerCollapsed = !drawer || drawer.classList.contains('collapsed') || drawer.offsetWidth === 0;
  const mainRect = mainStage ? mainStage.getBoundingClientRect() : null;
  const mainReachesRight = mainRect ? Math.abs(mainRect.right - viewportWidth) <= 2 : false;
  const activePanel = document.querySelector('.tab-panel.active');
  const panelOverflow = activePanel
    ? [...activePanel.querySelectorAll('.panel, .kpi-card, .approval-status-bar, canvas')].every((node) => {
        const rect = node.getBoundingClientRect();
        return rect.left >= -1 && rect.right <= viewportWidth + 1;
      })
    : true;
  const hiddenSidePanel = document.querySelector('.strategy-drawer:not(.collapsed)') == null || document.querySelector('.strategy-drawer:not(.collapsed)').getBoundingClientRect().right <= viewportWidth + 1;
  return {
    pageOverflow,
    headerOk,
    brandVisible,
    tabsVisible,
    tabCount: tabButtons.length,
    drawerCollapsed,
    mainReachesRight,
    panelOverflow,
    hiddenSidePanel,
    primaryVerticalCount: primaryVertical.length,
    approvedHorizontalCount: approvedHorizontal.length,
    extraScrollers: scrollers.filter((node) => {
      const cls = String(node.className || '');
      if (cls.includes('main-stage')) return false;
      if (cls.includes('table-scroll') || cls.includes('matrix-scroll') || cls.includes('mini-matrix') || cls.includes('table-viewport')) return false;
      if (node.id === 'riskDrawer' || node.id === 'strategyDrawer') return false;
      if (cls.includes('drawer-body')) return false;
      return false;
    }).slice(0, 12),
    unapprovedScrollers: [...document.querySelectorAll('*')].filter((node) => {
      if (!node || node === document.body || node === doc) return false;
      const cls = String(node.className || '');
      if (cls.includes('main-stage')) return false;
      if (cls.includes('table-scroll') || cls.includes('matrix-scroll') || cls.includes('mini-matrix') || cls.includes('table-viewport')) return false;
      if (node.id === 'riskDrawer' || node.id === 'strategyDrawer') return false;
      if (cls.includes('drawer-body')) return false;
      const style = window.getComputedStyle(node);
      if (style.overflowX !== 'auto' && style.overflowX !== 'scroll' && style.overflowY !== 'auto' && style.overflowY !== 'scroll') return false;
      return node.scrollHeight > node.clientHeight + 1 || node.scrollWidth > node.clientWidth + 1;
    }).map((node) => ({ tag: node.tagName.toLowerCase(), className: node.className || null })).slice(0, 12),
  };
}
"""

REPORT_LAYOUT_JS = """
() => {
  const workspace = document.getElementById('reportWorkspace');
  const memo = document.getElementById('dailyRiskMemo');
  const preview = document.getElementById('generatedReport');
  const strip = document.getElementById('reportStatusStrip');
  const doc = document.documentElement;
  const stripSpan = strip ? window.getComputedStyle(strip).gridColumnStart : null;
  const memoSpan = memo?.closest('.report-span-8') ? window.getComputedStyle(memo.closest('.report-span-8')).gridColumnEnd : null;
  return {
    workspaceExists: Boolean(workspace),
    memoHasSections: (memo?.querySelectorAll('section')?.length || 0) >= 5,
    previewHasContent: Boolean(preview?.innerText?.trim()),
    previewHasTitle: /daily risk report/i.test(preview?.innerText || ''),
    pageNoHorizontalOverflow: doc.scrollWidth <= doc.clientWidth + 1,
    stripFullWidth: strip ? strip.getBoundingClientRect().width >= (workspace?.getBoundingClientRect().width || 0) * 0.9 : false,
    noRebalanceCopy: /no rebalance proposed/i.test(document.body.innerText),
    executionNotAuthorized: /execution authorization: not authorized/i.test(document.body.innerText),
    workflowNotSubmitted: !/submitted for independent risk review/i.test(document.getElementById('governanceFlow')?.innerText || ''),
    workflowMonitoringOnly: /no active rebalance proposal/i.test(document.getElementById('governanceFlow')?.innerText || ''),
  };
}
"""


def _start_verify_server() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "run_workstation_server.py"), "--port", str(VERIFY_PORT)],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _find_open_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_server(timeout_seconds: int = 20) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{BASE_URL}/api/health", timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"Workstation server did not start on port {VERIFY_PORT}")


def _post_simulate(payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{BASE_URL}/api/simulate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _slug(tab: str) -> str:
    return tab.lower().replace(" & ", "_").replace(" / ", "_").replace(" ", "_")


def _assert_geometry(report: dict, geometry: dict, viewport: tuple[int, int], tab: str) -> None:
    key = f"{viewport[0]}x{viewport[1]}::{tab}"
    report.setdefault("geometry", {})[key] = geometry
    checks = report.setdefault("geometry_checks", {})
    no_unapprovedScrollers = geometry.get("unapprovedScrollers") or []
    checks[key] = {
        "page_no_horizontal_overflow": geometry.get("pageOverflow") is True,
        "header_fits": geometry.get("headerOk") is True,
        "brand_visible": geometry.get("brandVisible") is True,
        "all_tabs_visible": geometry.get("tabsVisible") is True and geometry.get("tabCount") == 9,
        "drawer_collapsed_zero_width": geometry.get("drawerCollapsed") is True,
        "main_stage_reaches_right_edge": geometry.get("mainReachesRight") is True,
        "active_panel_within_viewport": geometry.get("panelOverflow") is True,
        "no_visible_side_detail_panel": geometry.get("hiddenSidePanel") is True,
        "single_primary_vertical_scroller": geometry.get("primaryVerticalCount", 0) <= 1,
        "no_unapproved_page_scrollers": len(no_unapprovedScrollers) == 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Risk Manager workstation in browser.")
    parser.add_argument("--no-screenshots", action="store_true", help="Skip screenshot capture; geometry and interaction checks only.")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed; skipping browser verification")
        return 2

    global VERIFY_PORT, BASE_URL
    VERIFY_PORT = _find_open_port()
    BASE_URL = f"http://127.0.0.1:{VERIFY_PORT}"
    server_proc = _start_verify_server()
    try:
        _wait_for_server()
        return _run_browser_verification(sync_playwright, no_screenshots=args.no_screenshots)
    finally:
        server_proc.terminate()
        server_proc.wait(timeout=10)


def _run_browser_verification(sync_playwright, no_screenshots: bool = False) -> int:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "url": f"{BASE_URL}/dashboard/index.html",
        "tabs": [],
        "console_errors": [],
        "api_checks": {},
        "checks": {},
        "geometry": {},
        "geometry_checks": {},
        "screenshots": [],
    }

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        def capture_console(msg):
            if msg.type != "error":
                return
            text = msg.text or ""
            if "favicon.ico" in text or "/api/" in text:
                return
            report["console_errors"].append(text)

        def capture_bad_response(response):
            if response.status >= 400 and "favicon" not in response.url and "/api/" not in response.url:
                report["console_errors"].append(f"{response.status} {response.url}")

        page.on("console", capture_console)
        page.on("response", capture_bad_response)
        page.goto(report["url"], wait_until="load", timeout=120000)
        page.wait_for_timeout(1500)
        served_snapshot = page.evaluate(
            """async () => {
                const response = await fetch(`/api/operational-snapshot?ts=${Date.now()}`);
                return await response.json();
            }"""
        )
        latest_ledger_date = (served_snapshot.get("portfolio_daily") or [{}])[-1].get("date")
        official_close_date = (served_snapshot.get("official_daily") or {}).get("latest_official_close_date")
        initial_body_text = page.locator("body").inner_text()
        initial_body_upper = initial_body_text.upper()
        report["checks"]["current_served_labels"] = (
            "WORKFLOW & SHADOW-LIVE TESTING" in initial_body_upper
            and "STRATEGY LIBRARY & GOVERNANCE" in initial_body_upper
            and "STRATEGY FAMILY MIX" in initial_body_upper
            and "PROXY ONLY" in initial_body_upper
            and "MARKET & MACRO MONITOR" not in initial_body_upper
            and "STRATEGY LIBRARY & WORKFLOW" not in initial_body_upper
            and "COMBINED FAMILY MIX" not in initial_body_upper
            and "INVALID_EXECUTION_RECORD" not in initial_body_upper
        )
        report["checks"]["official_date_label_precision"] = (
            (
                "official ledger through" in initial_body_text.lower()
                or "official fallback" in initial_body_text.lower()
                or "paper history" in initial_body_text.lower()
                or "showing official fallback" in initial_body_text.lower()
            )
            and "OFFICIAL LEDGER DATE" in initial_body_upper
            and (
                "PAPER PERFORMANCE LATEST DATE" in initial_body_upper
                or "paper ledger pending" in initial_body_text.lower()
                or "paper history" in initial_body_text.lower()
            )
            and latest_ledger_date is not None
            and (
                latest_ledger_date == official_close_date
                or f"Official Daily Ledger through {official_close_date}" not in initial_body_text
            )
        )
        chart_state = page.evaluate(
            """
            (officialRowsAvailable) => {
              const panel = document.querySelector('.primary-chart');
              const canvas = panel?.querySelector('#navChart');
              const legend = panel?.querySelector('.chart-legend');
              const detail = panel?.querySelector('#navChartDetail');
              const tooltip = panel?.querySelector('#navChartTooltip');
              const title = panel?.querySelector('.section-header strong');
              const rect = (el) => {
                const r = el.getBoundingClientRect();
                return {top:r.top,bottom:r.bottom,left:r.left,right:r.right,width:r.width,height:r.height};
              };
              const overlap = (a,b) => !(a.bottom <= b.top || a.top >= b.bottom || a.right <= b.left || a.left >= b.right);
              const cr = canvas ? rect(canvas) : null;
              const lr = legend ? rect(legend) : null;
              const dr = detail ? rect(detail) : null;
              const tr = tooltip ? rect(tooltip) : null;
              const expectedOfficialRows = Math.min(20, officialRowsAvailable);
              canvas?.dispatchEvent(new MouseEvent('mousemove', {
                bubbles: true,
                clientX: cr ? cr.left + cr.width * 0.5 : 0,
                clientY: cr ? cr.top + cr.height * 0.5 : 0,
              }));
              const hoverText = detail?.innerText || '';
              return {
                expectedOfficialRows,
                headerMentionsWindow: (
                  (/Paper history/i.test(panel?.innerText || ''))
                  || (/Official fallback/i.test(panel?.innerText || '') && /Paper ledger pending/i.test(panel?.innerText || ''))
                  || (/Paper ledger pending/i.test(panel?.innerText || '') && /Showing official fallback/i.test(panel?.innerText || ''))
                ),
                titleFullVisible: title?.innerText === 'Master Portfolio Daily Performance' && title.scrollWidth <= title.clientWidth + 1,
                detailStripPresent: Boolean(detail),
                detailFieldsPresent: ['date','source','nav','daily p&l','drawdown'].every((label) => (detail?.innerText || '').toLowerCase().includes(label)),
                hoverUpdatesDetail: /Official Ledger|Delayed Est\\./i.test(hoverText),
                floatingTooltipVisible: tooltip ? getComputedStyle(tooltip).display !== 'none' && tooltip.classList.contains('visible') : false,
                legendOverlapsCanvas: Boolean(cr && lr && overlap(lr, cr)),
                detailOverlapsCanvas: Boolean(cr && dr && overlap(dr, cr)),
                detailInsidePanel: Boolean(panel && dr && dr.top >= rect(panel).top - 1 && dr.bottom <= rect(panel).bottom + 1),
                legacyDateTiles: panel?.querySelectorAll('.daily-record').length || 0,
                bodyOverflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
              };
            }
            """,
            len(served_snapshot.get("portfolio_daily") or []),
        )
        report["checks"]["master_chart_window_and_detail"] = (
            chart_state["expectedOfficialRows"] <= 20
            and chart_state["headerMentionsWindow"] is True
            and chart_state["titleFullVisible"] is True
            and chart_state["detailStripPresent"] is True
            and chart_state["detailFieldsPresent"] is True
            and chart_state["hoverUpdatesDetail"] is True
        )
        report["checks"]["master_chart_no_overlap"] = (
            chart_state["floatingTooltipVisible"] is False
            and chart_state["legendOverlapsCanvas"] is False
            and chart_state["detailOverlapsCanvas"] is False
            and chart_state["detailInsidePanel"] is True
            and chart_state["legacyDateTiles"] == 0
            and chart_state["bodyOverflowX"] is False
        )
        report["api_checks"]["master_portfolio_chart"] = chart_state
        for _ in range(20):
            if page.locator(".workflow-tabs").count() > 0 or page.locator("button[data-page]").count() > 0 or page.locator("button[data-tab]").count() > 0:
                break
            page.wait_for_timeout(500)

        if True:
            workflow_tabs = [
                ("Portfolio Command Center", "1. Portfolio Command Center"),
                ("Strategy Monitor", "2. Strategy Monitor"),
                ("Allocation & Rebalance", "3. Allocation & Rebalance"),
                ("Risk Factors & Exposure", "4. Risk Factors & Exposure"),
                ("Correlation & Diversification", "5. Correlation & Diversification"),
                ("Workflow & Shadow-Live Testing", "6. Workflow & Shadow-Live Testing"),
                ("Backtesting & Research Lab", "7. Backtesting & Research Lab"),
                ("Strategy Library & Governance", "8. Strategy Library & Governance"),
                ("Daily Risk Report", "9. Daily Risk Report"),
            ]
            for viewport in VIEWPORTS:
                page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
                for index, (tab, button_name) in enumerate(workflow_tabs, start=1):
                    page.get_by_role("button", name=button_name, exact=True).click()
                    page.wait_for_timeout(400)
                    body_text = page.locator("body").inner_text()
                    report["tabs"].append({"tab": tab, "loaded": tab in body_text, "viewport": f"{viewport[0]}x{viewport[1]}"})
                    report["geometry_checks"][f"{viewport[0]}x{viewport[1]}::{tab}"] = {
                        "page_not_horizontally_overflowing": page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"),
                        "main_stage_present": page.locator(".main-stage").count() == 1,
                        "no_release_safety_panel": page.locator(".release-safety-panel").count() == 0,
                    }
                    if not no_screenshots:
                        slug = f"{viewport[0]}x{viewport[1]}_{index:02d}_{_slug(tab)}"
                        shot = SCREENSHOT_DIR / f"{slug}.png"
                        page.screenshot(path=str(shot), full_page=False)
                        report["screenshots"].append(str(shot.relative_to(PROJECT_ROOT)))

            page.set_viewport_size({"width": 1440, "height": 900})
            rail_checks = [
                ("workflow", "Workflow & Shadow-Live Testing"),
                ("settings", "Strategy Library & Governance"),
                ("reports", "Daily Risk Report"),
                ("risk", "Risk Factors & Exposure"),
            ]
            rail_results = {}
            for rail_key, expected_tab in rail_checks:
                page.locator(f'[data-rail-key="{rail_key}"]').click()
                page.wait_for_timeout(350)
                body_text = page.locator("body").inner_text()
                top_active = page.locator(f'button[data-page="{expected_tab}"].active').count() == 1
                rail_active = page.locator(f'button[data-rail-key="{rail_key}"].active').count() == 1
                rail_results[rail_key] = expected_tab in body_text and top_active and rail_active
            report["checks"]["left_rail_navigation"] = all(rail_results.values())
            report["api_checks"]["left_rail_navigation"] = rail_results
            page.get_by_role("button", name="2. Strategy Monitor", exact=True).click()
            page.wait_for_timeout(500)
            strategy_monitor_text = page.locator("body").inner_text()
            strategy_monitor_state = page.evaluate(
                """
                () => {
                  const rows = [...document.querySelectorAll('.monitor-table tbody tr')];
                  const statusCells = rows.map((row) => row.querySelector('td:nth-child(4)')?.innerText || '');
                  const forbiddenStatusText = /Execution Mode|Provenance|Live Fill|Paper only|Derived \\/ no live fills|Paper only \\/ no live fills/i;
                  const pageOverflow = document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
                  const kpiOverflow = [...document.querySelectorAll('.strategy-monitor-kpis .metric-card')].filter(
                    (el) => el.scrollWidth > el.clientWidth + 2 || el.scrollHeight > el.clientHeight + 2
                  ).length;
                  return {
                    visibleRows: rows.length,
                    wqRows: rows.filter((row) => row.dataset.rowId === 'WQ_ALPHA_018' || row.innerText.includes('#000018')).length,
                    pendingRows: rows.filter((row) => /APPROVED_PENDING|PRE_OPERATIONAL|PRE-OPERATIONAL|PENDING/i.test(row.innerText)).length,
                    statusExtraTextCount: statusCells.filter((text) => forbiddenStatusText.test(text)).length,
                    statusTexts: statusCells.slice(0, 6),
                    repeatedPerformancePanel: document.querySelectorAll('.performance-analytics-panel:not([style*="display: none"])').length,
                    kpiOverflow,
                    pageOverflow,
                  };
                }
                """
            )
            report["checks"]["final_counts_visible"] = (
                "STRATEGY OPERATIONAL REGISTRY" in strategy_monitor_text.upper()
                and "17 VISIBLE CURRENT ROWS" in strategy_monitor_text.upper()
                and "NO PENDING CANDIDATE" in strategy_monitor_text.upper()
            )
            report["checks"]["strategy_monitor_current_rows"] = strategy_monitor_state["visibleRows"] == 17
            report["checks"]["strategy_monitor_excludes_wq_pending"] = (
                strategy_monitor_state["wqRows"] == 0
                and strategy_monitor_state["pendingRows"] == 0
            )
            report["checks"]["strategy_status_column_compact"] = (
                strategy_monitor_state["statusExtraTextCount"] == 0
                and all("ACTIVE" in text.upper() for text in strategy_monitor_state["statusTexts"] if text)
            )
            report["checks"]["strategy_repeated_performance_panel_removed"] = (
                strategy_monitor_state["repeatedPerformancePanel"] == 0
            )
            report["checks"]["strategy_monitor_no_overflow"] = (
                strategy_monitor_state["kpiOverflow"] == 0
                and strategy_monitor_state["pageOverflow"] is False
            )
            report["api_checks"]["strategy_monitor_current_state"] = strategy_monitor_state
            page.locator('[data-view-id="COMBINED_PORTFOLIO"]').click()
            page.wait_for_timeout(400)
            drawer_text = page.locator("#detailDrawer").inner_text()
            report["checks"]["combined_drawer_derived"] = (
                ("DERIVED_COMPLETE" in drawer_text.upper() or "DERIVED COMBINED STRATEGY LEDGER" in drawer_text.upper())
                and "DAILY P&L" in drawer_text.upper()
                and "CUMULATIVE P&L" in drawer_text.upper()
                and ("INTRADAY EST. P&L" in drawer_text.upper() or "INTRADAY ESTIMATED P&L" in drawer_text.upper())
                and ("INTRADAY EST. NAV" in drawer_text.upper() or "INTRADAY ESTIMATED NAV" in drawer_text.upper())
            )
            page.get_by_role("button", name="Close strategy detail", exact=True).click()
            page.wait_for_timeout(200)
            page.get_by_role("button", name="4. Risk Factors & Exposure", exact=True).click()
            page.wait_for_timeout(500)
            risk_state = page.evaluate(
                """
                () => ({
                  rows: document.querySelectorAll('.risk-heatmap-table tbody tr').length,
                  pageOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
                })
                """
            )
            report["checks"]["risk_factors_current_rows"] = risk_state["rows"] == 17
            report["checks"]["risk_factors_no_page_overflow"] = risk_state["pageOverflow"] is False
            report["api_checks"]["risk_factors_current_state"] = risk_state
            report["checks"]["no_console_errors"] = len(report["console_errors"]) == 0
            geometry_pass = all(all(values.values()) for values in report["geometry_checks"].values())
            report["checks"]["geometry_pass"] = geometry_pass
            unique_tabs = {entry["tab"] for entry in report["tabs"]}
            report["passed"] = all(report["checks"].values()) and len(unique_tabs) == 9 and geometry_pass
            REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps({"checks": report["checks"], "api_checks": report["api_checks"], "geometry_pass": geometry_pass}, indent=2))
            print(f"Console errors: {len(report['console_errors'])}")
            print(f"Wrote {REPORT_PATH}")
            browser.close()
            return 0 if report["passed"] else 1

        artifact = json.loads((PROJECT_ROOT / "output/dashboard_artifact.json").read_text(encoding="utf-8"))
        strategies = artifact.get("strategies", [])
        first_allocated = next((row for row in strategies if row.get("current_weight", 0) > 0), strategies[0])
        current_weights = {row["strategy_id"]: row.get("current_weight", 0) for row in strategies}

        for viewport in VIEWPORTS:
            page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
            for index, tab in enumerate(TABS, start=1):
                page.click(f'button[data-tab="{tab}"]')
                page.wait_for_timeout(500)
                geometry = page.evaluate(GEOMETRY_JS)
                _assert_geometry(report, geometry, viewport, tab)
                if not no_screenshots:
                    slug = f"{viewport[0]}x{viewport[1]}_{index:02d}_{_slug(tab)}"
                    shot = SCREENSHOT_DIR / f"{slug}.png"
                    page.screenshot(path=str(shot), full_page=False)
                    report["screenshots"].append(str(shot.relative_to(PROJECT_ROOT)))
                    report["tabs"].append({"tab": tab, "loaded": True, "screenshot": shot.name, "viewport": f"{viewport[0]}x{viewport[1]}"})
                    full_shot = SCREENSHOT_DIR / f"full_{slug}.png"
                    page.screenshot(path=str(full_shot), full_page=True)
                    report["screenshots"].append(str(full_shot.relative_to(PROJECT_ROOT)))
                else:
                    report["tabs"].append({"tab": tab, "loaded": True, "viewport": f"{viewport[0]}x{viewport[1]}"})

        page.set_viewport_size({"width": 1440, "height": 900})
        page.click('button[data-tab="Strategy Monitor"]')
        page.wait_for_timeout(400)
        page.click("#monitorTable tr[data-strategy]")
        page.wait_for_timeout(400)
        report["checks"]["strategy_row_opens_detail"] = page.locator("#strategyDrawer:not(.collapsed)").count() > 0
        if page.locator("#strategyDrawer:not(.collapsed)").count():
            page.click("#closeStrategyDrawer")
            page.wait_for_timeout(200)
        report["checks"]["strategy_drawer_closes"] = page.locator("#strategyDrawer.collapsed").count() > 0

        page.click('button[data-tab="Allocation & Rebalance"]')
        page.wait_for_timeout(800)
        page.click("#resetWeights")
        page.wait_for_timeout(1200)
        report["checks"]["no_change_proposal_status"] = "no rebalance proposed" in page.locator("#approvalStatusBar").inner_text().lower()
        report["checks"]["simulation_completed"] = (
            "simulation not required" in page.locator("#decisionAuthorityStatus").inner_text().lower()
            or "no allocation change" in page.locator("#decisionAuthorityStatus").inner_text().lower()
        )
        approval_text = page.locator("#approvalStatusBar").inner_text().lower()
        report["checks"]["gate_status_not_contradictory"] = (
            "proposal gate status: clear" in approval_text or "proposal gate status: blocked" in approval_text
        ) and not ("blocked" in approval_text and "no hard gate blockers" in approval_text)
        report["checks"]["current_portfolio_breaches_visible"] = (
            "current portfolio breaches" in page.locator("#allocationPersistentChecks").inner_text().lower()
        )

        enabled_input = page.locator("#allocationEditorTable input.weight-input:not([disabled])").first
        original = float(enabled_input.input_value())
        enabled_input.fill(str(max(0, original - 2)))
        page.click("#simulateWeights")
        page.wait_for_timeout(1200)
        report["checks"]["custom_weight_edit_simulates"] = "simulation completed" in page.locator("#decisionAuthorityStatus").inner_text().lower()
        report["checks"]["factor_before_after_visible"] = "→" in page.locator("#allocationBeforeAfterStrip").inner_text() or "→" in page.locator("#factorConcentrationTable").inner_text()

        enabled_input.fill("5")
        page.click("#simulateWeights")
        page.wait_for_timeout(1200)
        report["checks"]["underinvestment_allowed"] = "cash" in page.locator("#simulationChecks").inner_text().lower()

        enabled_input.fill("20")
        page.click("#simulateWeights")
        page.wait_for_timeout(1200)
        sim_text = page.locator("#simulationChecks").inner_text().lower()
        report["checks"]["overinvestment_blocked_in_checks"] = "cannot exceed 100%" in sim_text or "exceed 100%" in sim_text
        report["checks"]["hard_breach_blocks_approval"] = page.locator("#approveDecision").is_disabled()

        page.click("#resetWeights")
        page.wait_for_timeout(800)
        page.click("#simulateWeights")
        page.wait_for_timeout(1000)
        page.fill("#decisionReviewer", "")
        page.fill("#decisionNote", "")
        page.click("#modifyDecision")
        report["checks"]["reviewer_validation_blocks_empty_decision"] = "required" in page.locator("#decisionAuthorityStatus").inner_text().lower()

        report["checks"]["execution_not_authorized"] = "execution authorization: disabled" in page.locator("#approvalStatusBar").inner_text().lower() or "not authorized" in page.locator("#decisionStatusLines").inner_text().lower()

        page.set_viewport_size({"width": 1440, "height": 900})
        if not no_screenshots:
            v2_shots = [
                ("v2_1440_command_center", "Portfolio Command Center"),
                ("v2_1440_strategy_monitor", "Strategy Monitor"),
            ]
            for name, tab in v2_shots:
                page.click(f'button[data-tab="{tab}"]')
                page.wait_for_timeout(500)
                path = SCREENSHOT_DIR / f"{name}.png"
                page.screenshot(path=str(path), full_page=False)
                report["screenshots"].append(str(path.relative_to(PROJECT_ROOT)))

        page.click('button[data-tab="Backtesting & Research Lab"]')
        page.wait_for_timeout(500)
        selector = page.locator("#researchLabSelector")
        option_count = selector.locator("option").count()
        first_caption = page.locator("#researchLabCaption").inner_text().lower()
        if option_count > 1:
            selector.select_option(index=1)
            page.wait_for_timeout(400)
            second_caption = page.locator("#researchLabCaption").inner_text().lower()
            report["checks"]["research_lab_selector_changes_strategy"] = first_caption != second_caption
        else:
            report["checks"]["research_lab_selector_changes_strategy"] = option_count >= 1
        report["checks"]["research_lab_summary_strip"] = page.locator("#researchLabSummaryStrip").inner_text().strip() != ""
        page.click("#literatureStrategyTable tr[data-literature-strategy]")
        page.wait_for_timeout(500)
        if page.locator("#strategyDrawer:not(.collapsed)").count():
            page.click("#closeStrategyDrawer")
            page.wait_for_timeout(200)
        caption = page.locator("#researchLabCaption").inner_text().lower()
        report["checks"]["research_lab_updates_on_selection"] = "|" in caption and "select a literature" not in caption

        page.click('button[data-tab="Daily Risk Report / Decision Log"]')
        page.wait_for_timeout(800)
        layout = page.evaluate(REPORT_LAYOUT_JS)
        report["checks"]["report_auto_render_on_open"] = layout.get("previewHasContent") and layout.get("memoHasSections")
        report["checks"]["report_preview_title"] = layout.get("previewHasTitle") is True
        report["checks"]["report_no_horizontal_overflow"] = layout.get("pageNoHorizontalOverflow") is True
        report["checks"]["report_status_strip_full_width"] = layout.get("stripFullWidth") is True
        report["checks"]["no_rebalance_report_copy"] = layout.get("noRebalanceCopy") is True
        report["checks"]["report_workflow_not_submitted_without_proposal"] = layout.get("workflowNotSubmitted") is True
        report["checks"]["report_workflow_monitoring_only"] = layout.get("workflowMonitoringOnly") is True
        report["checks"]["report_execution_not_authorized"] = layout.get("executionNotAuthorized") is True
        page.click("#generateReport")
        page.wait_for_timeout(400)
        report["checks"]["report_generation"] = "daily risk report" in page.locator("#generatedReport").inner_text().lower()
        page.fill("#reportDecisionReviewer", "Risk Manager QA")
        page.fill("#reportDecisionNote", "Prototype review note for verification.")
        page.select_option("#reportDecisionAction", "Modification requested")
        page.click("#reportRecordDecision")
        page.wait_for_timeout(500)
        report["checks"]["report_decision_recorded"] = "modification requested" in page.locator("#decisionLog").inner_text().lower()
        report["checks"]["report_decision_not_execution"] = "execution authorization: not authorized" in page.locator("#reportHumanDecision").inner_text().lower()

        topbar_text = page.locator("#topbarMeta").inner_text().lower()
        report["checks"]["market_status_not_unknown_when_closed"] = "market unknown" not in topbar_text or "closed" in topbar_text or "latest market close" in topbar_text

        page.click('button[data-tab="Backtesting & Research Lab"]')
        page.wait_for_timeout(500)
        research_checklist = page.locator("#researchChecklist").inner_text().strip()
        report["checks"]["research_checklist_populated_or_unavailable"] = (
            len(research_checklist) > 0
            and (
                "summary statistics" in research_checklist.lower()
                or "analyst prompt" in research_checklist.lower()
                or "unavailable" in research_checklist.lower()
            )
        )
        report["checks"]["research_checklist_uses_correct_id"] = page.locator("#researchChecklist").count() == 1

        page.click('button[data-tab="Strategy Monitor"]')
        page.wait_for_timeout(400)
        monitor_kpi = page.locator("#monitorKpiStrip").inner_text().lower()
        report["checks"]["monitor_allocated_strategy_breaches_label"] = "allocated strategy breaches" in monitor_kpi

        page.click('button[data-tab="Daily Risk Report / Decision Log"]')
        page.wait_for_timeout(500)
        memo_text = page.locator("#dailyRiskMemo").inner_text().lower()
        report["checks"]["report_memo_no_raw_metric_keys"] = not any(
            key in memo_text for key in ("equity_beta", "credit_spread", "rates_duration", "factor_herfindahl")
        )
        issues_text = page.locator("#reportIssuesTable").inner_text()
        report["checks"]["report_no_portfolio_portfolio_label"] = "Portfolio - Portfolio" not in issues_text

        page.click('button[data-tab="Risk Factors & Exposure"]')
        page.wait_for_timeout(400)
        factor_text = page.locator('.tab-panel[data-tab-panel="Risk Factors & Exposure"]').inner_text().lower()
        report["checks"]["factor_labels_human_readable"] = "equity_beta" not in factor_text and "factor_herfindahl" not in factor_text
        report["checks"]["factor_exposure_share_label"] = "factor exposure share" in factor_text and "factor contribution to portfolio risk" not in factor_text

        page.click('button[data-tab="Allocation & Rebalance"]')
        page.wait_for_timeout(400)
        toolbar = page.locator(".simulation-toolbar .toolbar-actions")
        report["checks"]["allocation_toolbar_horizontal"] = toolbar.count() > 0 and toolbar.evaluate("el => getComputedStyle(el).display") == "flex"

        with page.expect_download() as download_info:
            page.click('button[data-tab="Daily Risk Report / Decision Log"]')
            page.wait_for_timeout(300)
            page.click("#exportJson")
        report["checks"]["json_export"] = download_info.value.suggested_filename.endswith(".json")

        with page.expect_download() as download_info:
            page.click("#exportCsv")
        report["checks"]["csv_export"] = download_info.value.suggested_filename.endswith(".csv")

        disabled_inputs = page.locator("#allocationEditorTable input.weight-input:disabled").count()
        report["checks"]["invalid_allocation_blocked"] = disabled_inputs > 0

        browser.close()

    try:
        under = _post_simulate(
            {
                "current_weights": current_weights,
                "target_weights": {first_allocated["strategy_id"]: 0.05},
                "capital": artifact.get("initial_capital", 1_000_000),
            }
        )
        over = _post_simulate(
            {
                "current_weights": current_weights,
                "target_weights": {first_allocated["strategy_id"]: 1.2},
                "capital": artifact.get("initial_capital", 1_000_000),
            }
        )
        official = artifact.get("rebalance_simulation", {}).get("official_optimizer", {})
        official_turnover = float(official.get("turnover") or 0.0)
        report["api_checks"]["underinvestment_ok"] = (
            under.get("ok", True)
            and under.get("cash_weight", 0) > 0.9
            and any(check.get("metric") == "Cash sleeve" for check in under.get("checks", []))
        )
        report["api_checks"]["overinvestment_breach"] = any(
            check.get("metric") == "Invested weight" and check.get("status") == "breach"
            for check in over.get("checks", [])
        )
        factor_before = official.get("factor_exposure_before", {})
        factor_after = official.get("factor_exposure_after", {})
        report["api_checks"]["factor_before_not_equal_after"] = (
            factor_before != factor_after if official_turnover > 1e-6 else factor_before == factor_after
        )
        if official.get("metrics_before") and official.get("metrics_after"):
            report["api_checks"]["numeric_metrics_present"] = math.isfinite(
                float(official["metrics_before"].get("portfolio_sharpe", 0))
            )
        else:
            report["api_checks"]["numeric_metrics_present"] = False
    except Exception as exc:
        report["api_checks"]["error"] = str(exc)
        report["api_checks"]["underinvestment_ok"] = False
        report["api_checks"]["overinvestment_breach"] = False
        report["api_checks"]["factor_before_not_equal_after"] = False
        report["api_checks"]["numeric_metrics_present"] = False

    report["checks"]["no_console_errors"] = len(report["console_errors"]) == 0
    geometry_pass = all(all(values.values()) for values in report["geometry_checks"].values())
    report["checks"]["geometry_pass"] = geometry_pass
    unique_tabs = {entry["tab"] for entry in report["tabs"]}
    report["passed"] = (
        all(report["checks"].values())
        and all(value is True for key, value in report["api_checks"].items() if key != "error")
        and len(unique_tabs) == 9
        and geometry_pass
    )
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"checks": report["checks"], "api_checks": report["api_checks"], "geometry_pass": geometry_pass}, indent=2))
    print(f"Console errors: {len(report['console_errors'])}")
    print(f"Wrote {REPORT_PATH}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
