"""Rewrite dashboard artifact JSON using compact separators."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = PROJECT_ROOT / "output" / "dashboard_artifact.json"


def compact_artifact(path: Path = ARTIFACT_PATH) -> tuple[int, int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    before = path.stat().st_size
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    after = path.stat().st_size
    return before, after


def main() -> int:
    if not ARTIFACT_PATH.is_file():
        print(f"Artifact not found: {ARTIFACT_PATH}", file=sys.stderr)
        return 1
    before, after = compact_artifact()
    print(f"Compacted {ARTIFACT_PATH.name}: {before} -> {after} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
