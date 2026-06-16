"""Regression test for formatIssueSubjectLabel artifact scoping."""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERIFY_PORT = 8771
BASE_URL = f"http://127.0.0.1:{VERIFY_PORT}/dashboard/index.html"

SUBJECT_LABEL_JS = """
() => {
  const staleArtifact = {
    strategies: [{ strategy_id: "STALE_ONLY", name: "Stale Global Name" }],
  };
  const suppliedArtifact = {
    strategies: [{ strategy_id: "PROTO_A", name: "Supplied Strategy Name" }],
  };
  activeArtifact = staleArtifact;
  const check = {
    subject_id: "PROTO_A",
    scope: "allocated_strategy_live",
    metric: "current_drawdown",
  };
  const label = formatIssueSubjectLabel(check, suppliedArtifact);
  const portfolioCheck = { subject_id: "portfolio", scope: "portfolio_live", metric: "var_99_1d" };
  const portfolioLabel = formatIssueSubjectLabel(portfolioCheck, suppliedArtifact);
  return {
    label,
    portfolioLabel,
    usesSuppliedStrategy: label === "Strategy - Supplied Strategy Name",
    avoidsStaleGlobal: label !== "Strategy - Stale Global Name",
    portfolioNotDuplicated: portfolioLabel === "Portfolio",
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


@pytest.fixture(scope="module")
def browser_page():
    server = _start_verify_server()
    try:
        _wait_for_server()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(BASE_URL, wait_until="load", timeout=120000)
            page.wait_for_timeout(1000)
            yield page
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()


def test_format_issue_subject_label_uses_supplied_artifact(browser_page):
    result = browser_page.evaluate(SUBJECT_LABEL_JS)
    assert result["usesSuppliedStrategy"] is True, result
    assert result["avoidsStaleGlobal"] is True, result
    assert result["portfolioNotDuplicated"] is True, result
