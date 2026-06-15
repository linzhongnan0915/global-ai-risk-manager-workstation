from __future__ import annotations

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.strategies.fundamental_research import run_fundamental_research_pack


def main() -> int:
    user_agent = os.environ.get("SEC_USER_AGENT")
    if not user_agent:
        raise RuntimeError("Set SEC_USER_AGENT to an identifying name and contact email.")
    result = run_fundamental_research_pack(ROOT, user_agent=user_agent)
    print(f"Wrote {result['output_root']}")
    for summary in result["summaries"]:
        print(summary["strategy_id"], f"Sharpe={summary['net_sharpe']:.3f}", summary["recommendation"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
