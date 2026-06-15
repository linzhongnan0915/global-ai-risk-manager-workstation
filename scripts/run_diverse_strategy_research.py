from __future__ import annotations

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.strategies.diverse_strategy_research import run_diverse_strategy_research


def main() -> int:
    result = run_diverse_strategy_research(
        ROOT,
        user_agent=os.environ.get("SEC_USER_AGENT", "RiskManagerPlatform Research research@example.com"),
    )
    print(f"Wrote {result['output_root']}")
    for row in result["summaries"]:
        print(row["strategy_id"], row["recommendation"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
