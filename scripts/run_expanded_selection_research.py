from __future__ import annotations

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.strategies.expanded_selection_research import run_expanded_selection

if __name__ == "__main__":
    result = run_expanded_selection(
        ROOT, user_agent=os.environ.get("SEC_USER_AGENT", "RiskManagerPlatform Research research@example.com")
    )
    print(result["coverage"])
    for row in result["summaries"]:
        print(row["strategy_id"], row["classification"], row["net_sharpe"])
