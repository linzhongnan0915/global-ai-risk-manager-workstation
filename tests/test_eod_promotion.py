"""Dry-run official EOD promotion workflow tests."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/promote_eod_official_ledger.py"


def _copy_root(tmp_path: Path) -> Path:
    target = tmp_path / "workstation"
    (target / "dashboard/data").mkdir(parents=True)
    (target / "dashboard/data/canonical_operational.json").write_text(
        (ROOT / "dashboard/data/canonical_operational.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return target


def _write_overlay(root: Path) -> None:
    generated = datetime.now(timezone.utc)
    overlay = {
        "schema_version": "intraday_overlay_v1",
        "generated_at": generated.isoformat(),
        "status": "LOADED",
        "provider": "test-delayed",
        "current_trading_session_date": "2026-06-15",
        "market_session_status": "After-hours",
        "delayed_estimate_as_of": "2026-06-15T16:05:00-04:00",
        "estimated_nav": 1_004_500.0,
        "estimated_pnl": 40.0,
        "estimated_return": 0.00004,
        "price_coverage": {"covered": 222, "total": 222},
        "strategy_estimates": [],
        "top_contributors": [],
        "top_detractors": [],
        "ticker_security_contribution": [],
        "holdings": [],
        "missing_tickers": [],
        "stale_tickers": [],
        "residual_pnl": None,
        "errors": [],
        "stale_after_seconds": 600,
        "next_refresh": (generated + timedelta(minutes=5)).isoformat(),
        "official_ledger_unchanged": True,
    }
    path = root / "output/operational_intraday_overlay.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(overlay), encoding="utf-8")


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), *args],
        check=False,
        cwd=ROOT,
        text=True,
        capture_output=True,
    )


def test_eod_promotion_dry_run_reports_blockers_without_mutation(tmp_path: Path):
    root = _copy_root(tmp_path)
    _write_overlay(root)
    before = (root / "dashboard/data/canonical_operational.json").read_text(encoding="utf-8")

    result = _run(root, "--target-date", "2026-06-15", "--dry-run")
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["mode"] == "dry-run"
    assert payload["official_ledger_mutated"] is False
    assert payload["backup_created"] is False
    assert payload["can_promote"] is False
    assert payload["readiness"]["readiness_state"] == "EOD_PENDING_OFFICIAL_PROMOTION"
    assert "2026-06-15" not in payload["after"]["portfolio_daily_dates"]
    assert payload["before"] == payload["after"]
    assert (root / "dashboard/data/canonical_operational.json").read_text(encoding="utf-8") == before


def test_eod_promotion_execute_refuses_when_blocked(tmp_path: Path):
    root = _copy_root(tmp_path)
    _write_overlay(root)

    result = _run(root, "--target-date", "2026-06-15", "--execute")
    payload = json.loads(result.stdout)

    assert result.returncode == 2
    assert payload["ok"] is False
    assert payload["error"] == "official promotion blocked"
    assert payload["official_ledger_mutated"] is False


def test_eod_promotion_default_is_dry_run(tmp_path: Path):
    root = _copy_root(tmp_path)
    _write_overlay(root)

    result = _run(root, "--target-date", "2026-06-15")
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["mode"] == "dry-run"
    assert payload["notes"][0] == "Dry-run never mutates portfolio_daily, strategy_daily, holdings, or trades."
