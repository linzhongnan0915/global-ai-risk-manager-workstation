"""Prebuild the operational snapshot for staging/runtime startup."""

from __future__ import annotations

import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.reporting.operational_snapshot import load_or_build_operational_snapshot


def main() -> int:
    snapshot = load_or_build_operational_snapshot(ROOT)
    snapshot_path = ROOT / "output" / "operational_snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot, separators=(",", ":")), encoding="utf-8")
    print(
        "Built operational snapshot "
        f"{snapshot.get('snapshot_id')} "
        f"version={snapshot.get('snapshot_version')} "
        f"strategies={len(snapshot.get('strategies') or [])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
