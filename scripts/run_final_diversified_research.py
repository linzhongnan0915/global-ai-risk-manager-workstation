import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.strategies.final_diversified_research import run_final_diversified_batch

if __name__ == "__main__":
    result = run_final_diversified_batch(ROOT, user_agent=os.environ.get("SEC_USER_AGENT", "RiskManagerPlatform Research research@example.com"))
    for row in result["summaries"]:
        print(row["strategy_id"], row["classification"], row.get("net_sharpe"))
