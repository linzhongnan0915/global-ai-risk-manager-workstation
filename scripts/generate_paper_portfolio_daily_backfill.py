"""Generate paper portfolio daily close ledger from canonical rows plus delayed closes."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.generate_risk_factor_market_proxy_cache import current_holding_universe, fetch_yfinance_history
from src.market.paper_portfolio_ledger import (
    build_paper_portfolio_backfill_rows_from_price_history,
    paper_portfolio_daily_path,
    write_paper_portfolio_daily_rows,
)

DEFAULT_CANONICAL_PATH = PROJECT_ROOT / "dashboard/data/canonical_operational.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def generate_backfill(
    root: Path,
    *,
    canonical_path: Path = DEFAULT_CANONICAL_PATH,
    start_date: str = "2026-06-04",
    period: str = "1mo",
    interval: str = "1d",
    through_date: str | None = None,
) -> dict[str, Any]:
    canonical = load_json(canonical_path)
    universe = current_holding_universe(canonical)
    price_history, failed = fetch_yfinance_history(universe, period=period, interval=interval)
    rows = build_paper_portfolio_backfill_rows_from_price_history(
        canonical,
        price_history,
        start_date=start_date,
        through_date=through_date,
    )
    payload = write_paper_portfolio_daily_rows(root, rows)
    metadata = payload.setdefault("metadata", {})
    metadata.update(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "backfill_start_date": start_date,
            "backfill_through_date": payload.get("rows", [{}])[-1].get("date") if payload.get("rows") else None,
            "backfill_source": "canonical_portfolio_daily_plus_current_holdings_delayed_yfinance_close",
            "historical_holdings_available": "partial",
            "current_holdings_used_for_missing_dates": True,
            "failed_tickers": failed,
        }
    )
    paper_portfolio_daily_path(root).write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate paper portfolio daily performance backfill.")
    parser.add_argument("--root", default=str(PROJECT_ROOT))
    parser.add_argument("--start-date", default="2026-06-04")
    parser.add_argument("--period", default="1mo")
    parser.add_argument("--interval", default="1d")
    parser.add_argument("--through-date")
    args = parser.parse_args()
    payload = generate_backfill(
        Path(args.root),
        start_date=args.start_date,
        period=args.period,
        interval=args.interval,
        through_date=args.through_date,
    )
    rows = payload.get("rows") or []
    print(
        json.dumps(
            {
                "path": str(paper_portfolio_daily_path(Path(args.root))),
                "row_count": len(rows),
                "first_date": rows[0].get("date") if rows else None,
                "latest_date": rows[-1].get("date") if rows else None,
                "source": payload.get("metadata", {}).get("backfill_source"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
