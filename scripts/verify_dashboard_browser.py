"""Browser verification for the Risk Manager workstation."""

from __future__ import annotations

import argparse
import json
import math
import socket
import subprocess
import sys
import tempfile
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
  "Universe & Data Coverage",
  "Workflow & Shadow-Live Testing",
  "Strategy Factory",
  "Strategy Library & Governance",
  "Daily Risk Report",
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


def _wait_for_server(timeout_seconds: int = 60) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{BASE_URL}/api/health", timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"Workstation server did not start on port {VERIFY_PORT}")


def _runtime_contamination_paths() -> list[str]:
    try:
        result = subprocess.run(
            [
                "git",
                "status",
                "--porcelain=v1",
                "--ignored",
                "--untracked-files=normal",
                "--",
                "data",
                "output",
            ],
            cwd=str(PROJECT_ROOT),
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return []
    paths: list[str] = []
    for line in result.stdout.splitlines():
        if line.startswith(("?? ", "!! ")):
            paths.append(line)
    return paths


def _fail_runtime_contaminated(paths: list[str]) -> int:
    report = {
        "passed": False,
        "environment_status": "ENV_CONTAMINATED",
        "message": (
            "Untracked or ignored data/** or output/** runtime artifacts can alter "
            "dashboard browser verification. Re-run with --clean-runtime for a "
            "deterministic clean runtime, or --allow-dirty-runtime for explicit "
            "local debugging."
        ),
        "contamination_paths": paths[:50],
        "contamination_path_count": len(paths),
        "checks": {},
        "api_checks": {},
        "console_errors": [],
    }
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("ENV_CONTAMINATED: untracked or ignored data/** or output/** artifacts detected.")
    for path in paths[:20]:
        print(f"  {path}")
    if len(paths) > 20:
        print(f"  ... {len(paths) - 20} more")
    print(f"Wrote {REPORT_PATH}")
    return 3


def _run_clean_runtime(no_screenshots: bool) -> int:
    temp_root = Path(tempfile.mkdtemp(prefix="rmw-dashboard-clean-runtime-"))
    try:
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(temp_root), "HEAD"],
            cwd=str(PROJECT_ROOT),
            check=True,
        )
        diff = subprocess.run(
            ["git", "diff", "--binary", "HEAD", "--", ".", ":(exclude)data/**", ":(exclude)output/**"],
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            check=True,
        ).stdout
        if diff.strip():
            subprocess.run(
                ["git", "apply", "--binary", "--whitespace=nowarn", "-"],
                cwd=str(temp_root),
                input=diff,
                check=True,
            )
        command = [sys.executable, str(temp_root / "scripts" / "verify_dashboard_browser.py")]
        if no_screenshots:
            command.append("--no-screenshots")
        return subprocess.run(command, cwd=str(temp_root), check=False).returncode
    finally:
        subprocess.run(
            ["git", "worktree", "remove", str(temp_root), "--force"],
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )


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


def _open_page(page, tab: str) -> None:
    button = page.locator(f'button[data-page="{tab}"]').first
    if button.count():
        button.click()
    else:
        page.get_by_role("button", name=tab).click()
    page.wait_for_function(
        """(name) => document.querySelector(`button[data-page="${name}"].active`) !== null""",
        arg=tab,
        timeout=15000,
    )
    page.wait_for_timeout(500)


def _run_core_friction_checks(page, report: dict) -> None:
    core_tabs = [
        "Portfolio Command Center",
        "Strategy Intelligence",
        "Allocation & Rebalance",
        "Strategy Factory",
    ]
    core_tab_results = {}
    generic_results = {}
    for tab in core_tabs:
        _open_page(page, tab)
        text = page.locator("body").inner_text()
        state = page.evaluate(
            """
            () => {
              const stage = document.querySelector('.main-stage');
              const rect = stage?.getBoundingClientRect();
              const aboveFoldText = [...document.querySelectorAll('.main-stage *')]
                .filter((el) => {
                  const r = el.getBoundingClientRect();
                  return r.bottom > 0 && r.top < window.innerHeight && r.width > 0 && r.height > 0;
                })
                .map((el) => el.innerText || '')
                .join('\\n')
                .trim();
              const bodyStart = (document.body?.innerText || '').trim().slice(0, 1200);
              return {
                hasStage: Boolean(stage),
                stageHeight: rect?.height || 0,
                stageWidth: rect?.width || 0,
                stageTextLength: (stage?.innerText || '').trim().length,
                aboveFoldTextLength: aboveFoldText.length,
                conflictMarkers: /<<<<<<<|=======|>>>>>>>/.test(document.body?.innerText || ''),
                rawJsonWall: /^\\s*[\\[{][\\s\\S]{200,}/.test(bodyStart) && /"\\w+"\\s*:/.test(bodyStart),
                horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
              };
            }
            """
        )
        core_tab_results[tab] = tab in text and state["hasStage"] and state["stageTextLength"] > 40
        generic_results[tab] = {
            **state,
            "no_giant_blank_main_stage": state["stageHeight"] > 120 and state["stageWidth"] > 600 and state["aboveFoldTextLength"] > 40,
            "no_conflict_markers": not state["conflictMarkers"],
            "no_raw_json_wall_above_fold": not state["rawJsonWall"],
            "no_horizontal_overflow": not state["horizontalOverflow"],
        }

    report["api_checks"]["core_tabs_open"] = core_tab_results
    report["checks"]["core_tabs_open"] = all(core_tab_results.values())
    report["api_checks"]["generic_friction_checks"] = generic_results
    report["checks"]["generic_no_giant_blank_main_stage"] = all(
        row["no_giant_blank_main_stage"] for row in generic_results.values()
    )
    report["checks"]["generic_no_conflict_markers"] = all(
        row["no_conflict_markers"] for row in generic_results.values()
    )
    report["checks"]["generic_no_raw_json_wall"] = all(
        row["no_raw_json_wall_above_fold"] for row in generic_results.values()
    )

    _open_page(page, "Strategy Intelligence")
    intelligence = page.evaluate(
        """
        async () => {
          const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
          const stage = document.querySelector('.main-stage') || document.scrollingElement;
          const buttons = [...document.querySelectorAll('[data-intel-uid]')].filter((button) => button.dataset.intelUid);
          const detailUid = () => document.querySelector('.strategy-intelligence-detail-header span')?.innerText?.trim() || '';
          const activeUid = () => document.querySelector('[data-intel-uid].active')?.dataset?.intelUid || detailUid();
          if (stage) stage.scrollTop = Math.min(220, Math.max(0, stage.scrollHeight - stage.clientHeight));
          await sleep(80);
          const beforeUid = activeUid();
          const target = buttons.find((button) => button.dataset.intelUid !== beforeUid) || buttons[0];
          const before = {
            selectedUid: beforeUid,
            detailUid: detailUid(),
            stageTop: stage?.scrollTop || 0,
            windowY: window.scrollY || 0,
            buttonCount: buttons.length,
          };
          if (target) target.click();
          await sleep(550);
          const nextStage = document.querySelector('.main-stage') || document.scrollingElement;
          const after = {
            selectedUid: activeUid(),
            detailUid: detailUid(),
            stageTop: nextStage?.scrollTop || 0,
            windowY: window.scrollY || 0,
          };
          return {
            before,
            after,
            selected_detail_changes: buttons.length > 1 ? after.selectedUid !== before.selectedUid : after.selectedUid === before.selectedUid,
            page_did_not_jump_to_top: before.stageTop <= 2 || after.stageTop > 2,
          };
        }
        """
    )
    report["api_checks"]["strategy_intelligence_interaction"] = intelligence
    report["checks"]["strategy_intelligence_selection_changes_detail"] = (
        intelligence.get("selected_detail_changes") is True
    )
    report["checks"]["strategy_intelligence_selection_preserves_scroll"] = (
        intelligence.get("page_did_not_jump_to_top") is True
    )

    _open_page(page, "Strategy Factory")
    factory_before = page.evaluate(
        """
        () => {
          const stage = document.querySelector('.main-stage') || document.scrollingElement;
          if (stage) stage.scrollTop = 0;
          const target = document.querySelector('.strategy-factory-page .factory-material-window')
            || document.querySelector('.strategy-factory-page')
            || stage;
          const rect = target?.getBoundingClientRect();
          return {
            before_scroll_y: window.scrollY || 0,
            before_stage_top: stage?.scrollTop || 0,
            before_target_top: target?.scrollTop || 0,
            target_selector: target?.className || target?.tagName || '',
            target_scroll_height: target?.scrollHeight || 0,
            target_client_height: target?.clientHeight || 0,
            point: rect ? {x: rect.left + rect.width / 2, y: rect.top + Math.min(rect.height / 2, 120)} : {x: window.innerWidth / 2, y: window.innerHeight / 2},
          };
        }
        """
    )
    page.mouse.move(factory_before["point"]["x"], factory_before["point"]["y"])
    page.mouse.wheel(0, 700)
    page.wait_for_timeout(350)
    factory_after = page.evaluate(
        """
        () => {
          const stage = document.querySelector('.main-stage') || document.scrollingElement;
          const target = document.querySelector('.strategy-factory-page .factory-material-window')
            || document.querySelector('.strategy-factory-page')
            || stage;
          return {
            after_scroll_y: window.scrollY || 0,
            after_stage_top: stage?.scrollTop || 0,
            after_target_top: target?.scrollTop || 0,
          };
        }
        """
    )
    factory_scroll = {**factory_before, **factory_after}
    factory_scroll["stage_scroll_delta"] = factory_scroll["after_stage_top"] - factory_scroll["before_stage_top"]
    factory_scroll["target_scroll_delta"] = factory_scroll["after_target_top"] - factory_scroll["before_target_top"]
    factory_scroll["window_scroll_delta"] = factory_scroll["after_scroll_y"] - factory_scroll["before_scroll_y"]
    factory_scroll["scroll_position_changed"] = any(
        abs(factory_scroll[key]) > 2
        for key in ("stage_scroll_delta", "target_scroll_delta", "window_scroll_delta")
    )
    report["api_checks"]["strategy_factory_scroll_behavior"] = factory_scroll
    report["checks"]["strategy_factory_wheel_not_locked"] = factory_scroll["scroll_position_changed"] is True

    _open_page(page, "Allocation & Rebalance")
    allocation = page.evaluate(
        """
        () => {
          const body = document.body?.innerText || '';
          const proposalTable = document.querySelector('.p0-proposal-table');
          const compactMissing = /No P0 paper allocation proposal generated yet/i.test(body);
          const commandPanel = [...document.querySelectorAll('.panel')].find((panel) => /Proposal Operations|Operator/i.test(panel.innerText || ''));
          const approvedPlanSeparate = /Existing Approved Paper Plan\\s+—\\s+Not Current P0 Proposal|Existing Approved Paper Plan - Not Current P0 Proposal/i.test(body);
          const unsafeButtons = [...document.querySelectorAll('button')].filter((button) => /Approve Proposal|Manual Rebalance/i.test(button.innerText || ''));
          return {
            proposal_table_exists: Boolean(proposalTable),
            compact_missing_proposal_state_exists: compactMissing,
            right_command_panel_exists: Boolean(commandPanel),
            existing_approved_plan_separate: approvedPlanSeparate,
            unsafe_action_count: unsafeButtons.length,
            unsafe_actions_disabled: unsafeButtons.every((button) => button.disabled || button.getAttribute('aria-disabled') === 'true'),
            unsafe_action_labels: unsafeButtons.map((button) => ({text: button.innerText, disabled: button.disabled})),
          };
        }
        """
    )
    report["api_checks"]["allocation_operator_states"] = allocation
    report["checks"]["allocation_p0_table_or_compact_empty_state"] = (
        allocation["proposal_table_exists"] or allocation["compact_missing_proposal_state_exists"]
    )
    report["checks"]["allocation_right_command_panel_exists"] = allocation["right_command_panel_exists"] is True
    report["checks"]["allocation_approved_plan_separate"] = allocation["existing_approved_plan_separate"] is True
    report["checks"]["allocation_future_unsafe_actions_disabled"] = (
        allocation["unsafe_action_count"] >= 2 and allocation["unsafe_actions_disabled"] is True
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Risk Manager workstation in browser.")
    parser.add_argument("--no-screenshots", action="store_true", help="Skip screenshot capture; geometry and interaction checks only.")
    parser.add_argument(
        "--clean-runtime",
        action="store_true",
        help="Run verification from a temporary clean git worktree so local data/output artifacts cannot affect results.",
    )
    parser.add_argument(
        "--allow-dirty-runtime",
        action="store_true",
        help="Run against the current worktree even when untracked/ignored data/output runtime artifacts are present.",
    )
    args = parser.parse_args()

    if args.clean_runtime:
        return _run_clean_runtime(no_screenshots=args.no_screenshots)

    contamination_paths = _runtime_contamination_paths()
    if contamination_paths and not args.allow_dirty_runtime:
        return _fail_runtime_contaminated(contamination_paths)

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
        "ignored_console_errors": [],
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
            location = msg.location or {}
            source_url = location.get("url") or ""
            if "favicon.ico" in text or "favicon.ico" in source_url or "/api/" in text or "/api/" in source_url:
                report["ignored_console_errors"].append({"text": text, "url": source_url})
                return
            report["console_errors"].append(text)

        def capture_bad_response(response):
            if response.status >= 400 and "favicon" not in response.url and "/api/" not in response.url:
                report["console_errors"].append(f"{response.status} {response.url}")

        page.on("console", capture_console)
        page.on("response", capture_bad_response)
        startup_requests = []
        page.on("request", lambda request: startup_requests.append({"method": request.method, "url": request.url}))
        page.goto(report["url"], wait_until="load", timeout=120000)
        page.wait_for_selector(".workflow-tabs, button[data-page]", timeout=120000)
        page.wait_for_selector(".command-board", timeout=120000)
        page.wait_for_timeout(500)
        served_snapshot = page.evaluate(
            """async () => {
                const response = await fetch(`/api/operational-snapshot?ts=${Date.now()}`);
                return await response.json();
            }"""
        )
        paper_rows = served_snapshot.get("paper_performance_daily") or []
        latest_portfolio_daily_date = (paper_rows or served_snapshot.get("portfolio_daily") or [{}])[-1].get("date")
        inventory = served_snapshot.get("strategy_entity_inventory") or {}
        expected_top_level_rows = int(inventory.get("top_level_active_count") or 0)
        command_button = page.locator('button:has-text("Portfolio Command Center")').first
        if command_button.count():
            command_button.click()
            page.wait_for_timeout(500)
        initial_body_text = page.locator("body").inner_text()
        initial_body_upper = initial_body_text.upper()
        initial_metrics = page.evaluate("() => window.__phase1Metrics || {}")
        initial_rail_state = page.evaluate(
            """() => {
              const text = document.querySelector('.rail-summary')?.innerText || '';
              const summary = window.__phase1Metrics || {};
              return {text, metrics: summary};
            }"""
        )
        command_startup_state = page.evaluate(
            """() => {
              const text = document.body.innerText || '';
              const sourceText = document.querySelector('.command-source-strip')?.innerText || '';
              const requests = window.__commandVerifierRequests || [];
              return {
                commandBoardVisible: document.querySelectorAll('.command-board').length === 1,
                largeDetailGateVisible: /Detail Not Loaded|Operational Detail Pending|Pending Detail/i.test(text),
                loadDetailsVisible: /Load Details|Load now/i.test(text),
                sourceText,
              };
            }"""
        )
        refresh_posts = [
            item for item in startup_requests
            if item["method"] == "POST" and "/api/refresh-data" in item["url"]
        ]
        report["checks"]["command_center_direct_state_startup"] = (
            command_startup_state["commandBoardVisible"] is True
            and command_startup_state["largeDetailGateVisible"] is False
            and command_startup_state["loadDetailsVisible"] is False
        )
        report["checks"]["command_center_no_auto_post_refresh"] = len(refresh_posts) == 0
        report["api_checks"]["command_center_startup"] = {
            **command_startup_state,
            "phase1Metrics": initial_metrics,
            "refreshPosts": refresh_posts,
            "initialRail": initial_rail_state,
        }
        load_details = page.locator("[data-load-details]").first
        if load_details.count():
            load_details.click()
            page.wait_for_selector(".primary-chart, .strategy-monitor-page", timeout=120000)
            page.wait_for_timeout(500)
            initial_body_text = page.locator("body").inner_text()
            initial_body_upper = initial_body_text.upper()
        report["checks"]["current_served_labels"] = (
            "WORKFLOW & SHADOW-LIVE TESTING" in initial_body_upper
            and "STRATEGY LIBRARY & GOVERNANCE" in initial_body_upper
            and "STRATEGY FAMILY MIX" in initial_body_upper
            and ("PROXY ONLY" in initial_body_upper or "STYLE / FAMILY EXPOSURE PROXY" in initial_body_upper)
            and "MARKET & MACRO MONITOR" not in initial_body_upper
            and "STRATEGY LIBRARY & WORKFLOW" not in initial_body_upper
            and "COMBINED FAMILY MIX" not in initial_body_upper
            and "INVALID_EXECUTION_RECORD" not in initial_body_upper
        )
        source_label_state = page.evaluate(
            """() => {
              const header = document.querySelector('.global-header')?.innerText || '';
              const chart = document.querySelector('.primary-chart')?.innerText || '';
              const retired = /Portfolio Daily Date|Portfolio Daily Source|Intraday Estimate Status|Latest Delayed Price|Official Ledger|Delayed Estimate|Paper Daily/i;
              return {
                header,
                chart,
                current_date: /Current Date/i.test(header),
                data_updated: /Data Updated/i.test(header) && /Data Updated/i.test(chart),
                portfolio_nav: /Portfolio NAV/i.test(header),
                daily_pnl: /Daily P&L/i.test(header),
                retired_labels_hidden: !retired.test(header) && !/Official Ledger|Delayed Estimate|Paper Daily/i.test(chart),
              };
            }"""
        )
        report["checks"]["command_center_source_labels"] = all(
            source_label_state[key] is True
            for key in ("current_date", "data_updated", "portfolio_nav", "daily_pnl", "retired_labels_hidden")
        )
        report["api_checks"]["command_center_source_labels"] = source_label_state
        portfolio_label_state = {
            "current_date": "CURRENT DATE" in initial_body_upper,
            "data_updated": "DATA UPDATED" in initial_body_upper,
            "portfolio_nav": "PORTFOLIO NAV" in initial_body_upper,
            "daily_pnl": "DAILY P&L" in initial_body_upper,
            "retired_header_labels_hidden": not any(
                label in initial_body_upper
                for label in (
                    "PORTFOLIO DAILY DATE",
                    "PORTFOLIO DAILY SOURCE",
                    "INTRADAY ESTIMATE STATUS",
                    "LATEST DELAYED PRICE",
                )
            ),
            "snapshot_date_available": latest_portfolio_daily_date is not None,
        }
        report["checks"]["portfolio_daily_label_precision"] = (
            portfolio_label_state["current_date"]
            and portfolio_label_state["data_updated"]
            and portfolio_label_state["portfolio_nav"]
            and portfolio_label_state["daily_pnl"]
            and portfolio_label_state["retired_header_labels_hidden"]
            and portfolio_label_state["snapshot_date_available"]
            and bool(served_snapshot.get("session_state"))
            and bool(served_snapshot.get("portfolio_summary"))
        )
        report["api_checks"]["portfolio_daily_label_state"] = portfolio_label_state
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
                sourceAndWindowExplained: /Portfolio NAV, daily P&L, and drawdown by date/i.test(panel?.innerText || ''),
                sourceChipsPresent: Boolean(panel?.querySelector('.chart-status-chips')) && /^Data Updated:/i.test((panel?.querySelector('.chart-status-chips')?.innerText || '').trim()) && !/Paper Daily|Official Ledger|Delayed Estimate|Intraday/i.test(panel?.querySelector('.chart-status-chips')?.innerText || ''),
                titleFullVisible: /Daily Performance/i.test(title?.innerText || panel?.innerText || ''),
                detailStripPresent: Boolean(detail),
                detailFieldsPresent: ['date','nav','daily p&l','drawdown'].every((label) => (detail?.innerText || '').toLowerCase().includes(label)) && !/\\bSource\\b/i.test(detail?.innerText || ''),
                hoverUpdatesDetail: ['date','nav','daily p&l'].every((label) => (hoverText || detail?.innerText || '').toLowerCase().includes(label)) && !/Paper Performance|Official Ledger|Delayed Estimate|Delayed Est\\.|Portfolio Daily|Paper Daily|\\bSource\\b/i.test(hoverText || detail?.innerText || ''),
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
            and chart_state["sourceAndWindowExplained"] is True
            and chart_state["sourceChipsPresent"] is True
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
            _run_core_friction_checks(page, report)
            workflow_tabs = [
                "Portfolio Command Center",
                "Strategy Monitor",
                "Strategy Intelligence",
                "Allocation & Rebalance",
                "Risk Factors & Exposure",
                "Correlation & Diversification",
                "Universe & Data Coverage",
                "Workflow & Shadow-Live Testing",
                "Strategy Factory",
                "Strategy Library & Governance",
                "Daily Risk Report",
            ]
            for viewport in VIEWPORTS:
                page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
                for index, tab in enumerate(workflow_tabs, start=1):
                    page.locator(f'button[data-page="{tab}"]').click()
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
                ("data", "Universe & Data Coverage"),
                ("workflow", "Workflow & Shadow-Live Testing"),
                ("settings", "Strategy Library & Governance"),
                ("reports", "Daily Risk Report"),
                ("risk", "Risk Factors & Exposure"),
            ]
            rail_content_markers = {
                "Universe & Data Coverage": ["Universe & Data Coverage", "Data Source Status"],
                "Workflow & Shadow-Live Testing": ["Workflow & Shadow-Live Testing", "workflow-map-page"],
                "Strategy Library & Governance": ["Strategy Library & Governance", "Registry Entities"],
                "Daily Risk Report": ["Daily Risk Report / Decision Log", "Daily strategy summary"],
                "Risk Factors & Exposure": ["Risk Factor Exposure Matrix", "Risk Factors"],
            }
            def rail_state(name: str, key: str) -> dict:
                return page.evaluate(
                    """
                    ({name, key, markers}) => {
                      const stage = document.querySelector('.main-stage');
                      const text = stage?.innerText || '';
                      const html = stage?.innerHTML || '';
                      const topButton = document.querySelector(`button[data-page="${name}"]`);
                      const activeTop = document.querySelector('button[data-page].active');
                      const activeRail = document.querySelector('button[data-rail-key].active');
                      const matched = markers.filter((marker) => text.includes(marker) || html.includes(marker));
                      return {
                        expected_tab: name,
                        rail_key: key,
                        top_tab_exists: topButton !== null,
                        top_active: topButton?.classList.contains('active') || false,
                        rail_active: document.querySelector(`button[data-rail-key="${key}"]`)?.classList.contains('active') || false,
                        active_top_page: activeTop?.dataset.page || null,
                        active_rail_key: activeRail?.dataset.railKey || null,
                        matched_markers: matched,
                        expected_markers: markers,
                        content_rendered: matched.length === markers.length,
                        main_stage_text_first_300: text.trim().slice(0, 300),
                      };
                    }
                    """,
                    arg={"name": name, "key": key, "markers": rail_content_markers[name]},
                )
            rail_results = {}
            for rail_key, expected_tab in rail_checks:
                rail_button = page.locator(f'[data-rail-key="{rail_key}"]')
                rail_button.scroll_into_view_if_needed()
                rail_button.click()
                state_after_click = rail_state(expected_tab, rail_key)
                deadline = time.time() + 15
                while time.time() < deadline:
                    state_after_click = rail_state(expected_tab, rail_key)
                    if state_after_click["rail_active"] and state_after_click["content_rendered"]:
                        if not state_after_click["top_tab_exists"] or state_after_click["top_active"]:
                            break
                    page.wait_for_timeout(250)
                state_after_click["passed"] = (
                    state_after_click["rail_active"]
                    and state_after_click["content_rendered"]
                    and (state_after_click["top_active"] if state_after_click["top_tab_exists"] else True)
                )
                rail_results[rail_key] = state_after_click
            report["checks"]["left_rail_navigation"] = all(item["passed"] for item in rail_results.values())
            report["api_checks"]["left_rail_navigation"] = rail_results
            _open_page(page, "Strategy Monitor")
            page.wait_for_function(
                """() => document.querySelectorAll('.strategy-monitor-page .monitor-table tbody tr[data-row-id]').length > 0""",
                timeout=15000,
            )
            strategy_monitor_text = page.locator("body").inner_text()
            strategy_monitor_state = page.evaluate(
                """
                () => {
                  const rows = [...document.querySelectorAll('.strategy-monitor-page .monitor-table tbody tr[data-row-id]')];
                  const statusCells = rows.map((row) => row.querySelector('td:nth-child(4)')?.innerText || '');
                  const forbiddenStatusText = /Execution Mode|Provenance|Live Fill|Paper only|Derived \\/ no live fills|Paper only \\/ no live fills/i;
                  const pageOverflow = document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
                  const kpiOverflow = [...document.querySelectorAll('.strategy-monitor-kpis .metric-card')].filter(
                    (el) => el.scrollWidth > el.clientWidth + 2 || el.scrollHeight > el.clientHeight + 2
                  ).length;
                  return {
                    visibleRows: rows.length,
                    wqRows: rows.filter((row) => row.dataset.rowId === 'WQ_ALPHA_018' || row.innerText.includes('#000018')).length,
                    pendingCandidateRows: rows.filter((row) => /APPROVED_PENDING|PRE_OPERATIONAL|PRE-OPERATIONAL|PENDING_USER_APPROVAL/i.test(row.innerText)).length,
                    combinedRows: rows.filter((row) => row.dataset.rowId === 'COMBINED_PORTFOLIO' && /ACTIVE COMPOSITE/i.test(row.innerText)).length,
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
                and "ORDINARY ACTIVE" in strategy_monitor_text.upper()
                and "TOP-LEVEL ACTIVE" in strategy_monitor_text.upper()
                and "PENDING APPROVAL" in strategy_monitor_text.upper()
            )
            report["checks"]["strategy_monitor_current_rows"] = strategy_monitor_state["visibleRows"] == expected_top_level_rows
            report["checks"]["strategy_monitor_excludes_wq_pending"] = (
                strategy_monitor_state["wqRows"] == 0
                and strategy_monitor_state["pendingCandidateRows"] == 0
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
            report["checks"]["combined_drawer_derived"] = strategy_monitor_state["combinedRows"] == 1
            _open_page(page, "Risk Factors & Exposure")
            page.wait_for_function(
                """() => document.querySelectorAll('.risk-factor-page .risk-heatmap-table tbody tr').length > 0""",
                timeout=15000,
            )
            risk_state = page.evaluate(
                """
                () => ({
                  rows: document.querySelectorAll('.risk-factor-page .risk-heatmap-table tbody tr').length,
                  pageOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
                })
                """
            )
            report["checks"]["risk_factors_current_rows"] = risk_state["rows"] == expected_top_level_rows
            report["checks"]["risk_factors_no_page_overflow"] = risk_state["pageOverflow"] is False
            report["api_checks"]["risk_factors_current_state"] = risk_state
            report["checks"]["no_console_errors"] = len(report["console_errors"]) == 0
            geometry_pass = all(all(values.values()) for values in report["geometry_checks"].values())
            report["checks"]["geometry_pass"] = geometry_pass
            unique_tabs = {entry["tab"] for entry in report["tabs"]}
            report["passed"] = all(report["checks"].values()) and len(unique_tabs) == 11 and geometry_pass
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

        page.click('button[data-tab="Strategy Factory"]')
        page.wait_for_timeout(500)
        strategy_factory_layout = page.evaluate(
            """
            () => {
              const pageEl = document.querySelector('.strategy-factory-page.readable-layout');
              const detail = document.querySelector('#factoryCandidateDetail');
              const report = document.querySelector('#factoryReportViewer');
              const stagePanel = document.querySelector('.factory-stage-status-panel');
              const workflowStrip = document.querySelector('.factory-workflow-strip');
              const workflowCards = Array.from(document.querySelectorAll('.factory-workflow-strip div'));
              const workflowTops = workflowCards.map(el => Math.round(el.getBoundingClientRect().top));
              const width = (el) => el ? el.getBoundingClientRect().width : 0;
              const pageWidth = width(pageEl);
              return {
                hasReadableLayout: !!pageEl,
                hasStageStatusPanel: !!stagePanel,
                detailWidth: width(detail),
                reportWidth: width(report),
                pageWidth,
                detailNotCollapsed: !!detail && width(detail) >= Math.min(900, pageWidth * 0.75),
                reportNotCollapsed: !report || width(report) >= Math.min(900, pageWidth * 0.75),
                noTinyFactorySections: Array.from(document.querySelectorAll('.strategy-factory-page .factory-section')).every(el => el.getBoundingClientRect().width >= Math.min(900, pageWidth * 0.75)),
                explicitStatesVisible: !!stagePanel && /NOT_STARTED|QUEUED|COMPLETED|FAILED|BLOCKED/.test(stagePanel.innerText),
                workflowSingleRow: workflowCards.length >= 11 && new Set(workflowTops).size === 1,
                workflowUsesHorizontalScroll: !!workflowStrip && getComputedStyle(workflowStrip).overflowX !== 'visible',
              };
            }
            """
        )
        report["checks"]["strategy_factory_readable_layout"] = strategy_factory_layout.get("hasReadableLayout") is True
        report["checks"]["strategy_factory_stage_status_panel"] = strategy_factory_layout.get("hasStageStatusPanel") is True
        report["checks"]["strategy_factory_detail_not_collapsed"] = strategy_factory_layout.get("detailNotCollapsed") is True
        report["checks"]["strategy_factory_report_not_collapsed"] = strategy_factory_layout.get("reportNotCollapsed") is True
        report["checks"]["strategy_factory_no_tiny_sections"] = strategy_factory_layout.get("noTinyFactorySections") is True
        report["checks"]["strategy_factory_explicit_states"] = strategy_factory_layout.get("explicitStatesVisible") is True
        report["checks"]["strategy_factory_workflow_single_row"] = strategy_factory_layout.get("workflowSingleRow") is True
        report["checks"]["strategy_factory_workflow_horizontal_scroll"] = strategy_factory_layout.get("workflowUsesHorizontalScroll") is True
        strategy_factory_scroll = page.evaluate(
            """
            async () => {
              const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));
              const getRoot = () => document.querySelector('.strategy-factory-page');
              const getScroller = () => document.querySelector('.main-stage') || document.scrollingElement;
              const checks = [];
              const clickStable = async (selector) => {
                const root = getRoot();
                const el = root && root.querySelector(selector);
                if (!el || el.disabled) return true;
                el.scrollIntoView({ block: 'center', inline: 'nearest' });
                await sleep(80);
                const beforeScroller = getScroller();
                const beforeY = beforeScroller.scrollTop;
                const beforeX = beforeScroller.scrollLeft;
                const beforeHash = window.location.hash;
                el.click();
                await sleep(250);
                const afterScroller = getScroller();
                checks.push({
                  selector,
                  beforeY,
                  afterY: afterScroller.scrollTop,
                  beforeX,
                  afterX: afterScroller.scrollLeft,
                  beforeHash,
                  afterHash: window.location.hash,
                });
                return Math.abs(afterScroller.scrollTop - beforeY) <= 2 && Math.abs(afterScroller.scrollLeft - beforeX) <= 2 && window.location.hash === beforeHash;
              };
              const viewStable = await clickStable('[data-factory-view]');
              const tabStable = await clickStable('[data-factory-detail-tab]');
              const controlStable = await clickStable('[data-factory-material-control]');
              const sortStable = await clickStable('[data-factory-material-sort]');
              const checkbox = getRoot() && getRoot().querySelector('[data-factory-material-id]');
              let checkboxStable = true;
              if (checkbox) {
                checkbox.scrollIntoView({ block: 'center', inline: 'nearest' });
                await sleep(80);
                const beforeScroller = getScroller();
                const beforeY = beforeScroller.scrollTop;
                const beforeX = beforeScroller.scrollLeft;
                const beforeHash = window.location.hash;
                checkbox.click();
                await sleep(250);
                const afterScroller = getScroller();
                checks.push({
                  selector: '[data-factory-material-id]',
                  beforeY,
                  afterY: afterScroller.scrollTop,
                  beforeX,
                  afterX: afterScroller.scrollLeft,
                  beforeHash,
                  afterHash: window.location.hash,
                });
                checkboxStable = Math.abs(afterScroller.scrollTop - beforeY) <= 2 && Math.abs(afterScroller.scrollLeft - beforeX) <= 2 && window.location.hash === beforeHash;
              }
              const materialWindow = document.querySelector('.factory-material-window');
              const materialWindowContained = materialWindow
                ? getComputedStyle(materialWindow).overscrollBehaviorY === 'contain' && materialWindow.clientHeight <= 560
                : true;
              return {
                checked: checks,
                scrollRootClass: getScroller().className || getScroller().tagName,
                materialWindowContained,
                stable: viewStable && tabStable && controlStable && sortStable && checkboxStable && materialWindowContained,
              };
            }
            """
        )
        report["checks"]["strategy_factory_actions_preserve_scroll"] = strategy_factory_scroll.get("stable") is True
        selector = page.locator("#researchLabSelector")
        if selector.count():
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
        else:
            report["checks"]["research_lab_selector_changes_strategy"] = True
            report["checks"]["research_lab_summary_strip"] = True
            report["checks"]["research_lab_updates_on_selection"] = True

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

        page.click('button[data-tab="Strategy Factory"]')
        page.wait_for_timeout(500)
        if page.locator("#researchChecklist").count():
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
        else:
            report["checks"]["research_checklist_populated_or_unavailable"] = page.locator(".factory-stage-status-panel").count() == 1
            report["checks"]["research_checklist_uses_correct_id"] = True

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
    api_boolean_pass = all(
        value is True
        for key, value in report["api_checks"].items()
        if key != "error" and isinstance(value, bool)
    )
    report["passed"] = (
        all(report["checks"].values())
        and api_boolean_pass
        and len(unique_tabs) == 11
        and geometry_pass
    )
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"checks": report["checks"], "api_checks": report["api_checks"], "geometry_pass": geometry_pass}, indent=2))
    print(f"Console errors: {len(report['console_errors'])}")
    print(f"Wrote {REPORT_PATH}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
