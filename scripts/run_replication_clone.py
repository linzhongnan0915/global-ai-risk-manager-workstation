"""Run prototype hedge fund replication clone analysis."""

from pathlib import Path
import json
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.replication.clone_model import (  # noqa: E402
    equal_weight_target_returns,
    load_factor_returns,
    result_to_dict,
    run_fixed_replication,
    run_rolling_replication,
)


def main() -> None:
    factors = load_factor_returns(PROJECT_ROOT / "data/processed/market_price_history.csv")
    target_tickers = ["SPY", "IEF", "LQD", "HYG", "UUP", "DBC"]
    target = equal_weight_target_returns(target_tickers, PROJECT_ROOT / "data/processed/market_price_history.csv")
    fixed = run_fixed_replication(target, factors, "STRAT_020", "Hedge Fund Replication Clone")
    rolling = run_rolling_replication(target, factors, "STRAT_020", "Hedge Fund Replication Clone", window=126)
    payload = {
        "as_of": target.index.max().date().isoformat(),
        "source": "yfinance_factor_proxy_prototype",
        "target_proxy_universe": target_tickers,
        "factor_proxies": {
            "SP500": "SPY",
            "BOND": "IEF",
            "USD": "UUP",
            "CREDIT": "HYG",
            "CMDTY": "DBC",
            "DVIX": "VIX first difference",
        },
        "results": [result_to_dict(fixed), result_to_dict(rolling)],
        "method_note": (
            "Prototype only. Fixed clone is explanatory and uses full-sample information. "
            "Rolling clone avoids look-ahead by estimating betas on prior 126 trading days."
        ),
    }
    output = PROJECT_ROOT / "output/replication_clone_snapshot.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {output}")
    print(f"Rolling R-squared: {rolling.r_squared:.3f}")
    print(f"Rolling annualized alpha: {rolling.alpha_annualized:.3%}")


if __name__ == "__main__":
    main()
