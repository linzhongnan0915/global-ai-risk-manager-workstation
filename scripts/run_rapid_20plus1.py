"""Run the rapid 20+1 US-equity research backtests and artifacts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
DEFAULT_OHLCV = PROJECT_ROOT / "data/raw/worldquant_alpha2/pilot_500_validation_ohlcv.csv"
FACTORY_ROOT = PROJECT_ROOT / "output/research/strategy_factory_v1"


def run_all(skip_existing: bool = False, only_finalize: bool = False) -> int:
    if not only_finalize:
        from src.strategies.platform_registry import ALL_RAPID_SPECS
        from src.strategies.c3a1_signals import set_spy_return
        from src.strategies.rapid_20plus1 import ensure_spy_benchmark
        from src.strategies.strategy_factory import load_context, run_strategy

        if not DEFAULT_OHLCV.exists():
            print(f"Missing OHLCV input: {DEFAULT_OHLCV}", file=sys.stderr)
            return 1
        context = load_context(DEFAULT_OHLCV)
        spy_cache = PROJECT_ROOT / "artifacts/rapid_20plus1/spy_benchmark.csv"
        set_spy_return(ensure_spy_benchmark(context.daily_returns.index, spy_cache))
        for spec in ALL_RAPID_SPECS:
            out_dir = FACTORY_ROOT / spec.strategy_id
            summary_path = out_dir / "summary.json"
            if skip_existing and summary_path.exists():
                print(f"Skip existing {spec.strategy_id}")
                continue
            print(f"Running {spec.strategy_id} ...")
            run_strategy(spec, context, out_dir)
            print(f"Finished {spec.strategy_id}")

    from src.strategies.rapid_20plus1 import finalize_rapid_artifacts

    result = finalize_rapid_artifacts(PROJECT_ROOT)
    print(f"Artifacts written to {result['artifact_root']}")
    print(f"Combined Portfolio Sharpe: {result['composite_summary']['sharpe']:.3f}")
    print(f"Active members: {len(result['active_ids'])} / {len(result['composite_summary'].get('platform_member_ids', []))}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run rapid 20+1 research platform backtests.")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--finalize-only", action="store_true")
    args = parser.parse_args()
    return run_all(skip_existing=args.skip_existing, only_finalize=args.finalize_only)


if __name__ == "__main__":
    sys.exit(main())
