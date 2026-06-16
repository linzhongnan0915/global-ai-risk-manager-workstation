"""Verify strategy drawer chart rendering and drawer view reset."""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DRAWER_PORT = 8768
BASE_URL = f"http://127.0.0.1:{DRAWER_PORT}"


def _start_server() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "run_workstation_server.py"), "--port", str(DRAWER_PORT), "--no-intraday-scheduler"],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_for_server(timeout_seconds: int = 20) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{BASE_URL}/api/health", timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"Workstation server did not start on port {DRAWER_PORT}")


def main() -> int:
    server = _start_server()
    try:
        _wait_for_server()
        return _run_drawer_checks()
    finally:
        server.terminate()
        server.wait(timeout=10)


def _run_drawer_checks() -> int:
    checks: dict[str, bool | list] = {}
    console_errors: list[str] = []
    overview_pixels: list[dict] = []
    perf_pixels: list[dict] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" and "favicon" not in (msg.text or "").lower() else None)
        page.goto(f"{BASE_URL}/dashboard/index.html", wait_until="load", timeout=120000)
        page.wait_for_function(
            """() => document.querySelector('button[data-page="Strategy Monitor"]')
              || document.querySelector('#navRail button[data-tab="Strategy Monitor"]')""",
            timeout=30000,
        )
        if page.locator('button[data-page="Strategy Monitor"]').count() > 0:
            page.click('button[data-page="Strategy Monitor"]')
            page.wait_for_timeout(500)
            checks["foundation_strategy_monitor_visible"] = page.locator(".strategy-monitor-page").count() == 1
            checks["foundation_strategy_rows_visible"] = page.locator('tr[data-row-id]').count() > 0
            page.locator('tr[data-row-id]').first.click()
            page.wait_for_timeout(500)
            checks["foundation_drawer_or_selection_available"] = (
                page.locator("#detailDrawer.open, tr.selected").count() > 0
            )
            checks["no_console_errors"] = len(console_errors) == 0
            browser.close()
            payload = {
                "checks": checks,
                "overview_pixels": overview_pixels,
                "perf_pixels": perf_pixels,
                "console_errors": console_errors,
                "pass": all(bool(value) for value in checks.values() if isinstance(value, bool)),
            }
            print(json.dumps(payload, indent=2))
            return 0 if payload["pass"] else 1
        page.click('#navRail button[data-tab="Strategy Monitor"]')
        page.wait_for_timeout(400)
        page.wait_for_selector("#monitorTable tr[data-strategy]", timeout=20000)
        rows = page.locator("#monitorTable tr[data-strategy]:visible")
        rows.first.click()
        page.wait_for_selector("#strategyDrawer:not(.collapsed)", timeout=5000)
        page.wait_for_function(
            """() => {
              const canvas = document.getElementById('drawerOverviewCumCanvas');
              if (!canvas || !canvas.width) return false;
              const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
              for (let i = 0; i < data.length; i += 4) {
                if (data[i] || data[i + 1] || data[i + 2] || data[i + 3]) return true;
              }
              return false;
            }""",
            timeout=15000,
        )

        checks["drawer_open_a"] = page.locator("#strategyDrawer:not(.collapsed)").count() == 1
        checks["overview_tab_active"] = (
            page.locator('#drawerTabs .drawer-tab.active[data-drawer-view="overview"]').count() == 1
        )
        checks["overview_charts_present"] = (
            page.locator("#drawerOverviewCumCanvas, #drawerOverviewDdCanvas").count() == 2
        )
        overview_pixels = page.evaluate(
            """() => {
              const canvases = ['drawerOverviewCumCanvas', 'drawerOverviewDdCanvas'];
              return canvases.map((id) => {
                const c = document.getElementById(id);
                if (!c) return {id, ok: false, reason: 'missing'};
                const ctx = c.getContext('2d');
                const data = ctx.getImageData(0, 0, c.width, c.height).data;
                let nonZero = 0;
                for (let i = 0; i < data.length; i += 4) if (data[i] || data[i+1] || data[i+2] || data[i+3]) nonZero++;
                return {id, ok: nonZero > 0, nonZero};
              });
            }"""
        )
        checks["overview_canvas_drawn"] = all(item["ok"] for item in overview_pixels)

        page.click('#drawerTabs button[data-drawer-view="performance"]')
        page.wait_for_timeout(400)
        checks["performance_charts_present"] = (
            page.locator("#drawerPerfGrossNetCanvas, #drawerPerfDrawdownCanvas, #drawerPerfRollingSharpeCanvas").count()
            == 3
        )
        perf_pixels = page.evaluate(
            """() => {
              const canvases = ['drawerPerfGrossNetCanvas', 'drawerPerfDrawdownCanvas', 'drawerPerfRollingSharpeCanvas'];
              return canvases.map((id) => {
                const c = document.getElementById(id);
                if (!c) return {id, ok: false, reason: 'missing'};
                const ctx = c.getContext('2d');
                const data = ctx.getImageData(0, 0, c.width, c.height).data;
                let nonZero = 0;
                for (let i = 0; i < data.length; i += 4) if (data[i] || data[i+1] || data[i+2] || data[i+3]) nonZero++;
                return {id, ok: nonZero > 0, nonZero};
              });
            }"""
        )
        checks["performance_canvas_drawn"] = all(item["ok"] for item in perf_pixels)

        page.click('#drawerTabs button[data-drawer-view="risk"]')
        page.wait_for_timeout(250)
        checks["risk_metrics_visible"] = page.locator("#drawerBody .drawer-metric-grid .drawer-metric").count() >= 4

        page.click("#closeStrategyDrawer")
        page.wait_for_selector("#strategyDrawer.collapsed", timeout=5000)
        checks["drawer_closed"] = page.locator("#strategyDrawer.collapsed").count() == 1

        rows.nth(1).click()
        page.wait_for_selector("#strategyDrawer:not(.collapsed)", timeout=5000)
        page.wait_for_selector("#drawerOverviewCumCanvas", timeout=15000)
        checks["drawer_open_b"] = True
        checks["overview_reset_on_b"] = (
            page.locator('#drawerTabs .drawer-tab.active[data-drawer-view="overview"]').count() == 1
        )
        checks["overview_charts_on_b"] = (
            page.locator("#drawerOverviewCumCanvas, #drawerOverviewDdCanvas").count() == 2
        )

        # Limits tab interaction regression
        rows.first.click()
        page.wait_for_selector("#strategyDrawer:not(.collapsed)", timeout=5000)
        strategy_a_name = page.locator("#drawerStrategyName").inner_text()

        def click_drawer_tab(view: str) -> None:
            page.click(f'#drawerTabs button[data-drawer-view="{view}"]')
            page.wait_for_timeout(350)

        click_drawer_tab("limits")
        limits_a_text = page.locator("#drawerBody").inner_text()
        checks["limits_strategy_a_renders"] = (
            "Metric" in limits_a_text or "No configured risk-limit or research-quality checks for this strategy." in limits_a_text
        )
        checks["limits_a_no_overview_stale"] = page.locator("#drawerOverviewCumCanvas").count() == 0

        click_drawer_tab("decision")
        checks["decision_replaces_limits"] = page.locator("#drawerDecisionNote").count() == 1
        click_drawer_tab("limits")
        limits_a_return = page.locator("#drawerBody").inner_text()
        checks["limits_returns_after_decision"] = (
            "Metric" in limits_a_return or "No configured risk-limit or research-quality checks for this strategy." in limits_a_return
        )
        checks["limits_return_no_decision_stale"] = page.locator("#drawerDecisionNote").count() == 0

        rows.nth(1).click()
        page.wait_for_selector("#strategyDrawer:not(.collapsed)", timeout=5000)
        strategy_b_name = page.locator("#drawerStrategyName").inner_text()
        click_drawer_tab("limits")
        limits_b_text = page.locator("#drawerBody").inner_text()
        checks["limits_strategy_b_renders"] = (
            "Metric" in limits_b_text or "No configured risk-limit or research-quality checks for this strategy." in limits_b_text
        )
        checks["limits_strategy_b_header_updated"] = strategy_b_name != strategy_a_name
        checks["limits_strategy_b_no_strategy_a_stale"] = (
            strategy_a_name not in limits_b_text or limits_b_text != limits_a_text
        )

        drawer_views = ["overview", "performance", "risk", "evidence", "limits", "decision"]
        stale_after_cycle = False
        for view in drawer_views:
            click_drawer_tab(view)
            body_text = page.locator("#drawerBody").inner_text()
            if view == "overview" and page.locator("#drawerOverviewCumCanvas").count() == 0:
                stale_after_cycle = True
            if view == "performance" and page.locator("#drawerPerfGrossNetCanvas").count() == 0:
                stale_after_cycle = True
            if view == "limits" and page.locator("#drawerOverviewCumCanvas, #drawerPerfGrossNetCanvas").count() > 0:
                stale_after_cycle = True
            if view == "decision" and page.locator("#drawerDecisionNote").count() == 0:
                stale_after_cycle = True
            if view == "evidence" and "Hypothesis:" not in body_text:
                stale_after_cycle = True
            if view == "risk" and "Factor exposure" not in body_text:
                stale_after_cycle = True
        checks["drawer_tab_cycle_no_stale_content"] = not stale_after_cycle
        checks["drawer_tab_cycle_no_reference_error"] = not any(
            "referenceerror" in err.lower() or "artifact is not defined" in err.lower()
            for err in console_errors
        )

        checks["no_console_errors"] = len(console_errors) == 0
        browser.close()

    payload = {
        "checks": checks,
        "overview_pixels": overview_pixels,
        "perf_pixels": perf_pixels,
        "console_errors": console_errors,
        "pass": all(bool(value) for value in checks.values() if isinstance(value, bool)),
    }
    print(json.dumps(payload, indent=2))
    return 0 if payload["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
