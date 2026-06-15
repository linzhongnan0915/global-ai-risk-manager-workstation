"""Run literature-derived strategy prototype backtests."""

from pathlib import Path
import json
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.strategies.literature_backtests import run_all_literature_backtests


def main() -> None:
    payload = run_all_literature_backtests(PROJECT_ROOT / "data/processed/market_price_history.csv")
    output = PROJECT_ROOT / "output/literature_strategy_backtests.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {output}")
    for item in payload["results"]:
        backtest = item["backtest"]
        net = backtest["net_metrics"]
        action = backtest["action"]
        print(
            f"{backtest['strategy_id']}: Sharpe={net.get('sharpe', 0):.2f}, "
            f"MaxDD={net.get('max_drawdown', 0):.2%}, Action={action['action']}"
        )


if __name__ == "__main__":
    main()
