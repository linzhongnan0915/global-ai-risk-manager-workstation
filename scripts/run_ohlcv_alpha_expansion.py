from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.strategies.ohlcv_alpha_expansion import run_ohlcv_alpha_expansion

if __name__ == "__main__":
    result = run_ohlcv_alpha_expansion(ROOT)
    for row in result["summaries"]:
        print(row["strategy_id"], row["classification"], row["net_sharpe"])
