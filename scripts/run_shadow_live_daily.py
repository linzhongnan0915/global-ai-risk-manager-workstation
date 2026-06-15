import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.strategies.shadow_live_operations import run_shadow_live

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run frozen ACTIVE strategies from raw OHLCV and SEC inputs.")
    parser.add_argument("--freeze-date", help="Last date labeled RETROSPECTIVE_PAPER_BACKFILL (YYYY-MM-DD).")
    parser.add_argument("--raw-end-date", help="Raw-data download end date for deterministic operations/tests.")
    args = parser.parse_args()
    print(run_shadow_live(ROOT, freeze_date=args.freeze_date, raw_end_date=args.raw_end_date))
