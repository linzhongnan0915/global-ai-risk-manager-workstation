"""Build the committed local canonical operational frontend contract."""

from __future__ import annotations

import json
from pathlib import Path

from src.reporting.canonical_frontend_contract import build_from_path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "dashboard/data/shadow_live_bundle.json"
TARGET = ROOT / "dashboard/data/canonical_operational.json"


def main() -> None:
    contract = build_from_path(SOURCE)
    TARGET.write_text(json.dumps(contract, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"Wrote {TARGET.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
