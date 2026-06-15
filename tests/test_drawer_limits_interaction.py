"""Browser regression tests for strategy drawer Limits tab rendering."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_drawer_limits_interaction_script_passes():
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "verify_drawer_charts.py")],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "limits_strategy_a_renders" in result.stdout
    assert "limits_returns_after_decision" in result.stdout
    assert "limits_strategy_b_renders" in result.stdout
    assert "drawer_tab_cycle_no_stale_content" in result.stdout
    payload = json.loads(result.stdout)
    assert payload["pass"] is True
