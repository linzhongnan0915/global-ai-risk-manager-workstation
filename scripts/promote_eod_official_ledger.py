"""Dry-run EOD official ledger promotion readiness.

This script reports whether the existing official pipeline can be run safely.
Step 13A intentionally does not execute ledger mutation from this command.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.reporting.operational_snapshot import (  # noqa: E402
    load_operational_snapshot_for_response,
    official_promotion_readiness,
)


def _latest(rows: list[dict[str, Any]], *keys: str) -> str | None:
    values = [
        str(row.get(key))
        for row in rows
        for key in keys
        if row.get(key)
    ]
    return max(values) if values else None


def _ledger_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    portfolio_daily = snapshot.get("portfolio_daily") or []
    strategy_daily = snapshot.get("strategy_daily") or []
    trades = snapshot.get("trades") or []
    holdings = snapshot.get("holdings") or []
    return {
        "portfolio_daily_dates": [row.get("date") for row in portfolio_daily if row.get("date")],
        "strategy_daily_latest_date": _latest(strategy_daily, "date"),
        "trades_latest_execution_date": _latest(trades, "execution_date"),
        "holdings_latest_date": _latest(holdings, "date"),
        "official_close_as_of": snapshot.get("official_close_as_of"),
        "data_as_of": snapshot.get("portfolio_summary", {}).get("as_of_date"),
    }


def build_report(root: Path, target_date: str | None, execute: bool) -> dict[str, Any]:
    snapshot = load_operational_snapshot_for_response(root)
    readiness = snapshot.get("official_promotion_readiness") or official_promotion_readiness(snapshot)
    blockers = list(readiness.get("blockers") or [])
    if target_date and readiness.get("target_ledger_date") and target_date != readiness.get("target_ledger_date"):
        blockers.append(
            f"Requested target date {target_date} does not match current trading session "
            f"{readiness.get('target_ledger_date')}."
        )
    before = _ledger_summary(snapshot)
    report = {
        "ok": not execute,
        "mode": "execute" if execute else "dry-run",
        "target_date": target_date or readiness.get("target_ledger_date"),
        "can_promote": bool(readiness.get("can_promote")) and not blockers,
        "readiness": {**readiness, "blockers": blockers},
        "before": before,
        "after": before,
        "official_ledger_mutated": False,
        "backup_created": False,
        "execute_mode": "deferred",
        "recommended_command_sequence": [
            "python scripts\\run_shadow_live_daily.py --raw-end-date <next-open-endpoint-date>",
            "python scripts\\build_canonical_frontend_contract.py",
            "python scripts\\build_operational_snapshot.py",
        ],
        "notes": [
            "Dry-run never mutates portfolio_daily, strategy_daily, holdings, or trades.",
            "Execute mode is deferred in Step 13A; official promotion remains manual and disabled by default.",
            "NEXT_OPEN_TO_OPEN requires the correct next-open return endpoint before official promotion.",
        ],
    }
    if execute:
        report["ok"] = False
        report["error"] = (
            "execute mode is deferred in Step 13A"
            if report["can_promote"]
            else "official promotion blocked"
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dry-run official EOD ledger promotion readiness.")
    parser.add_argument("--root", default=str(ROOT), help=argparse.SUPPRESS)
    parser.add_argument("--target-date", help="Target portfolio_daily ledger date, YYYY-MM-DD.")
    parser.add_argument("--dry-run", action="store_true", help="Report readiness only. This is the default.")
    parser.add_argument("--execute", action="store_true", help="Deferred in Step 13A; never mutates ledgers.")
    args = parser.parse_args(argv)
    report = build_report(Path(args.root), args.target_date, execute=bool(args.execute))
    print(json.dumps(report, indent=2, ensure_ascii=True))
    if args.execute and report.get("error") == "official promotion blocked":
        return 2
    if args.execute:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
