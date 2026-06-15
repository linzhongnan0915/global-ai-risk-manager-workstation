"""Render / public demo hosting helpers."""

from __future__ import annotations

import os
from pathlib import Path


def is_demo_hosting() -> bool:
    return bool(os.environ.get("RENDER") or os.environ.get("PUBLIC_DEMO"))


def intraday_scheduler_enabled(
    *,
    config_enabled: bool,
    force_start: bool | None,
    force_disable: bool,
) -> bool:
    if force_disable:
        return False
    if force_start is True:
        return True
    if is_demo_hosting():
        flag = os.environ.get("ENABLE_INTRADAY_SCHEDULER", "").strip().lower()
        if flag not in {"1", "true", "yes", "on"}:
            return False
    return bool(config_enabled)


def demo_scheduler_label(scheduler_enabled: bool) -> str | None:
    if not is_demo_hosting():
        return None
    if scheduler_enabled:
        return "Scheduler active while service is running"
    return "Manual refresh only while service is running"


def configure_yfinance_cache(project_root: Path) -> Path:
    cache_dir = Path(os.environ.get("YFINANCE_CACHE_DIR", project_root / "output" / ".yfinance_cache"))
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        import yfinance as yf

        yf.set_tz_cache_location(str(cache_dir))
    except Exception:
        pass
    return cache_dir
