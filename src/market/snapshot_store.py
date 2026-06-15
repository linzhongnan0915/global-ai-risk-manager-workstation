"""Atomic intraday snapshot storage."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.market.intraday_config import load_intraday_config


def new_snapshot_id(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    return f"snap-{stamp}-{uuid4().hex[:8]}"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(temp, path)


def publish_snapshot(snapshot: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config or load_intraday_config()
    snapshot_dir = Path(cfg["snapshot_dir"])
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_id = snapshot.get("snapshot_id") or new_snapshot_id()
    snapshot["snapshot_id"] = snapshot_id
    snapshot_path = snapshot_dir / f"{snapshot_id}.json"
    _atomic_write_json(snapshot_path, snapshot)
    pointer = {
        "snapshot_id": snapshot_id,
        "path": str(snapshot_path.as_posix()),
        "published_at": datetime.now(timezone.utc).isoformat(),
        "refresh_status": snapshot.get("refresh_status"),
    }
    _atomic_write_json(Path(cfg["latest_pointer_path"]), pointer)
    return pointer


def read_latest_pointer(config: dict[str, Any] | None = None) -> dict[str, Any] | None:
    cfg = config or load_intraday_config()
    path = Path(cfg["latest_pointer_path"])
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def read_latest_snapshot(config: dict[str, Any] | None = None) -> dict[str, Any] | None:
    pointer = read_latest_pointer(config)
    if not pointer:
        return None
    snapshot_path = Path(pointer["path"])
    if not snapshot_path.exists():
        return None
    return json.loads(snapshot_path.read_text(encoding="utf-8"))


def read_refresh_status(config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config or load_intraday_config()
    path = Path(cfg["status_path"])
    if not path.exists():
        return {"state": "idle", "in_progress": False}
    return json.loads(path.read_text(encoding="utf-8"))


def write_refresh_status(status: dict[str, Any], config: dict[str, Any] | None = None) -> None:
    cfg = config or load_intraday_config()
    _atomic_write_json(Path(cfg["status_path"]), status)
