"""Pytest wrapper for dashboard logic semantics browser regression script."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_logic_semantics_script_passes():
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "verify_dashboard_logic_semantics.py")],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["checks"]["no_rebalance_workflow_not_submitted"] is True
    assert payload["checks"]["current_portfolio_breaches_visible_with_clear_gate"] is True
    assert payload["checks"]["factor_panel_exposure_share_label"] is True
    assert payload["checks"]["reset_returns_no_active_proposal"] is True
    assert payload["checks"]["research_checklist_rendered_or_unavailable"] is True
    assert payload["checks"]["monitor_kpi_allocated_strategy_breaches_label"] is True
    assert payload["checks"]["report_no_raw_metric_keys"] is True
    assert payload["checks"]["no_portfolio_portfolio_subject_label"] is True
    assert payload["pass"] is True
