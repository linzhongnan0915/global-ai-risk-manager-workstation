"""Automation intelligence helpers with lazy exports."""

from __future__ import annotations

from typing import Any


__all__ = [
    "build_automation_intelligence_manifest",
    "build_allocation_recommendation_artifact",
    "build_daily_recommendation_artifact",
    "compact_automation_intelligence_summary",
    "read_latest_allocation_recommendation_artifact",
    "read_latest_daily_recommendation_artifact",
    "write_allocation_recommendation_artifact",
    "write_daily_recommendation_artifact",
]


def __getattr__(name: str) -> Any:
    if name in {"build_automation_intelligence_manifest", "compact_automation_intelligence_summary"}:
        from src.automation.automation_intelligence_manifest import (
            build_automation_intelligence_manifest,
            compact_automation_intelligence_summary,
        )

        exports = {
            "build_automation_intelligence_manifest": build_automation_intelligence_manifest,
            "compact_automation_intelligence_summary": compact_automation_intelligence_summary,
        }
        return exports[name]
    if name in {
        "build_allocation_recommendation_artifact",
        "read_latest_allocation_recommendation_artifact",
        "write_allocation_recommendation_artifact",
    }:
        from src.automation.allocation_recommendation_artifact import (
            build_allocation_recommendation_artifact,
            read_latest_allocation_recommendation_artifact,
            write_allocation_recommendation_artifact,
        )

        exports = {
            "build_allocation_recommendation_artifact": build_allocation_recommendation_artifact,
            "read_latest_allocation_recommendation_artifact": read_latest_allocation_recommendation_artifact,
            "write_allocation_recommendation_artifact": write_allocation_recommendation_artifact,
        }
        return exports[name]
    if name in {
        "build_daily_recommendation_artifact",
        "read_latest_daily_recommendation_artifact",
        "write_daily_recommendation_artifact",
    }:
        from src.automation.daily_recommendation_artifact import (
            build_daily_recommendation_artifact,
            read_latest_daily_recommendation_artifact,
            write_daily_recommendation_artifact,
        )

        exports = {
            "build_daily_recommendation_artifact": build_daily_recommendation_artifact,
            "read_latest_daily_recommendation_artifact": read_latest_daily_recommendation_artifact,
            "write_daily_recommendation_artifact": write_daily_recommendation_artifact,
        }
        return exports[name]
    raise AttributeError(name)
