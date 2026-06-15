from __future__ import annotations

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.strategies.final_delivery_research import run_final_delivery_research


if __name__ == "__main__":
    result = run_final_delivery_research(
        ROOT, user_agent=os.environ.get("SEC_USER_AGENT", "RiskManagerPlatform Research research@example.com")
    )
    print(f"Wrote {result['output_root']}")
    for row in result["summaries"]:
        print(row["strategy_id"], row["classification"])
