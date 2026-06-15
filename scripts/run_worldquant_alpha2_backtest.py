"""Run WorldQuant Alpha #2 end-to-end research backtest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.download_worldquant_alpha2_pilot_prices import (
    SMOKE_FAILURES_PATH,
    SMOKE_OHLCV_PATH,
    SMOKE_TEST_TICKERS,
    run_smoke_download,
)
from src.strategies.worldquant.backtest import (
    run_alpha2_backtest,
    write_alpha2_backtest_outputs,
)
from src.strategies.worldquant.data_loader import (
    assert_cached_ohlcv_covers_requested_range,
    load_ohlcv_csv,
)
from src.strategies.worldquant.market_data import download_ohlcv
from src.strategies.worldquant.pilot_universe import DEFAULT_PILOT_UNIVERSE_OUTPUT
from src.strategies.worldquant.portfolio_returns import (
    EXECUTION_MODE_NEXT_OPEN_TO_CLOSE,
    validate_execution_mode,
)

DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "output" / "research" / "worldquant_alpha2"
DEFAULT_PILOT_OHLCV_PATH = PROJECT_ROOT / "data" / "raw" / "worldquant_alpha2" / "pilot_500_ohlcv.csv"
DEFAULT_PILOT_FAILURES_PATH = DEFAULT_PILOT_OHLCV_PATH.with_name("pilot_500_ohlcv_failures.csv")


def _load_tickers(mode: str) -> list[str]:
    if mode == "smoke":
        return list(SMOKE_TEST_TICKERS)
    pilot = pd.read_csv(DEFAULT_PILOT_UNIVERSE_OUTPUT)
    return sorted(pilot["symbol_normalized"].astype(str).str.upper().unique().tolist())


def _ensure_ohlcv(
    mode: str,
    *,
    start_date: str,
    end_date: str,
    ohlcv_path: Path,
    refresh: bool,
    batch_size: int,
    max_attempts: int,
) -> tuple[pd.DataFrame, str, str]:
    if mode == "smoke" and refresh:
        run_smoke_download(
            start_date=start_date,
            end_date=end_date,
            batch_size=batch_size,
            max_attempts=max_attempts,
        )
        ohlcv = load_ohlcv_csv(SMOKE_OHLCV_PATH)
        actual_start, actual_end = assert_cached_ohlcv_covers_requested_range(
            ohlcv,
            start_date,
            end_date,
        )
        return ohlcv, actual_start, actual_end

    if ohlcv_path.exists() and not refresh:
        ohlcv = load_ohlcv_csv(ohlcv_path)
        actual_start, actual_end = assert_cached_ohlcv_covers_requested_range(
            ohlcv,
            start_date,
            end_date,
        )
        return ohlcv, actual_start, actual_end

    tickers = _load_tickers(mode)
    ohlcv, failures, _ = download_ohlcv(
        tickers,
        start_date=start_date,
        end_date=end_date,
        batch_size=batch_size,
        max_attempts=max_attempts,
    )
    ohlcv_path.parent.mkdir(parents=True, exist_ok=True)
    ohlcv.to_csv(ohlcv_path, index=False)
    failures_path = ohlcv_path.with_name(f"{ohlcv_path.stem}_failures.csv")
    failures.to_csv(failures_path, index=False)
    print(f"Wrote OHLCV: {ohlcv_path}")
    print(f"Wrote failures: {failures_path}")
    if not failures.empty:
        print(failures.to_string(index=False))
    actual_start, actual_end = assert_cached_ohlcv_covers_requested_range(
        ohlcv,
        start_date,
        end_date,
    )
    return ohlcv, actual_start, actual_end


def run_mode(
    mode: str,
    *,
    start_date: str,
    end_date: str,
    output_dir: Path,
    execution_mode: str,
    refresh_data: bool,
    batch_size: int,
    max_attempts: int,
) -> dict:
    execution_mode = validate_execution_mode(execution_mode)

    if mode == "smoke":
        ohlcv_path = SMOKE_OHLCV_PATH
        failures_path = SMOKE_FAILURES_PATH
    else:
        ohlcv_path = DEFAULT_PILOT_OHLCV_PATH
        failures_path = DEFAULT_PILOT_FAILURES_PATH

    tickers = _load_tickers(mode)
    ohlcv, actual_start, actual_end = _ensure_ohlcv(
        mode,
        start_date=start_date,
        end_date=end_date,
        ohlcv_path=ohlcv_path,
        refresh=refresh_data,
        batch_size=batch_size,
        max_attempts=max_attempts,
    )
    download_failures = pd.read_csv(failures_path) if failures_path.exists() else pd.DataFrame()
    result = run_alpha2_backtest(
        ohlcv,
        tickers,
        execution_mode=execution_mode,
        download_failures=download_failures,
        requested_start_date=start_date,
        requested_end_date=end_date,
        actual_data_start_date=actual_start,
        actual_data_end_date=actual_end,
    )
    mode_output_dir = output_dir / mode / execution_mode
    paths = write_alpha2_backtest_outputs(result, mode_output_dir)

    print(f"Run status: {result.run_status}")
    print(result.summary.to_string(index=False))
    print("Output paths:")
    for name, path in paths.items():
        print(f"  - {name}: {path}")

    payload = {
        "mode": mode,
        "execution_mode": execution_mode,
        "run_status": result.run_status,
        "output_dir": str(mode_output_dir),
        "output_paths": {key: str(path) for key, path in paths.items()},
        "summary": result.summary.iloc[0].to_dict(),
    }
    manifest_path = mode_output_dir / "run_manifest.json"
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Run WorldQuant Alpha #2 research backtest")
    parser.add_argument("--mode", choices=["smoke", "pilot500"], default="smoke")
    parser.add_argument("--start-date", default="2024-01-01")
    parser.add_argument("--end-date", default="2024-03-31")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument(
        "--execution-mode",
        default=EXECUTION_MODE_NEXT_OPEN_TO_CLOSE,
        help="next_open_to_close (default) or close_to_close_lag2",
    )
    parser.add_argument("--refresh-data", action="store_true")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--max-attempts", type=int, default=3)
    args = parser.parse_args()

    if args.mode == "pilot500" and not DEFAULT_PILOT_UNIVERSE_OUTPUT.exists():
        raise FileNotFoundError(
            "Pilot 500 universe file is missing. Build it first with:\n"
            "  python scripts/build_worldquant_alpha2_universe.py"
        )

    run_mode(
        args.mode,
        start_date=args.start_date,
        end_date=args.end_date,
        output_dir=Path(args.output_dir),
        execution_mode=args.execution_mode,
        refresh_data=args.refresh_data,
        batch_size=args.batch_size,
        max_attempts=args.max_attempts,
    )


if __name__ == "__main__":
    main()
