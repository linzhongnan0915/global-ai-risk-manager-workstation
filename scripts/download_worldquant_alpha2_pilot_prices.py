"""Download WorldQuant Alpha #2 pilot OHLCV prices (smoke test or full pilot)."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.strategies.worldquant.market_data import (
    assess_ticker_data_quality,
    build_download_audit,
    download_ohlcv,
    format_download_audit,
)

DEFAULT_OUTPUT_DIR = Path("data/raw/worldquant_alpha2")
SMOKE_SYMBOL_MAP_PATH = DEFAULT_OUTPUT_DIR / "pilot_smoke_symbol_map.csv"
SMOKE_OHLCV_PATH = DEFAULT_OUTPUT_DIR / "pilot_smoke_ohlcv.csv"
SMOKE_FAILURES_PATH = DEFAULT_OUTPUT_DIR / "pilot_smoke_failures.csv"
SMOKE_QUALITY_PATH = DEFAULT_OUTPUT_DIR / "pilot_smoke_data_quality_report.csv"

# Fixed deterministic smoke-test symbols from the pilot universe (not performance-selected).
SMOKE_TEST_TICKERS = [
    "AAL",    # NASDAQ ordinary
    "ACVA",   # NYSE ordinary
    "ADSK",   # NASDAQ ordinary
    "AEE",    # NYSE ordinary
    "ACMR",   # NASDAQ ordinary
    "AHR",    # REIT common equity
    "GOOD",   # REIT common equity
    "BRK.B",  # special class-share dot format
]


def _write_outputs(
    symbol_map,
    ohlcv,
    failures,
    *,
    symbol_map_path: Path,
    ohlcv_path: Path,
    failures_path: Path,
) -> None:
    symbol_map_path.parent.mkdir(parents=True, exist_ok=True)
    symbol_map.to_csv(symbol_map_path, index=False)
    ohlcv.to_csv(ohlcv_path, index=False)
    failures.to_csv(failures_path, index=False)


def run_smoke_download(
    *,
    start_date: str,
    end_date: str,
    batch_size: int = 4,
    max_attempts: int = 3,
) -> dict:
    ohlcv, failures, symbol_map = download_ohlcv(
        SMOKE_TEST_TICKERS,
        start_date=start_date,
        end_date=end_date,
        batch_size=batch_size,
        max_attempts=max_attempts,
    )
    quality_report = assess_ticker_data_quality(ohlcv, SMOKE_TEST_TICKERS)
    _write_outputs(
        symbol_map,
        ohlcv,
        failures,
        symbol_map_path=SMOKE_SYMBOL_MAP_PATH,
        ohlcv_path=SMOKE_OHLCV_PATH,
        failures_path=SMOKE_FAILURES_PATH,
    )
    quality_report.to_csv(SMOKE_QUALITY_PATH, index=False)
    audit = build_download_audit(SMOKE_TEST_TICKERS, symbol_map, ohlcv, failures)
    audit["output_paths"] = {
        "symbol_map": str(SMOKE_SYMBOL_MAP_PATH),
        "ohlcv": str(SMOKE_OHLCV_PATH),
        "failures": str(SMOKE_FAILURES_PATH),
        "data_quality_report": str(SMOKE_QUALITY_PATH),
    }
    print(format_download_audit(audit, output_paths=audit["output_paths"]))
    if failures.empty:
        print("Failure details: none")
    else:
        print("Failure details:")
        print(failures.to_string(index=False))
    return audit


def main() -> None:
    parser = argparse.ArgumentParser(description="Download WorldQuant Alpha #2 pilot OHLCV prices")
    parser.add_argument("--mode", choices=["smoke"], default="smoke")
    parser.add_argument("--start-date", default="2024-01-01")
    parser.add_argument("--end-date", default="2024-03-31")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--max-attempts", type=int, default=3)
    args = parser.parse_args()

    if args.mode == "smoke":
        run_smoke_download(
            start_date=args.start_date,
            end_date=args.end_date,
            batch_size=args.batch_size,
            max_attempts=args.max_attempts,
        )


if __name__ == "__main__":
    main()
