"""Automation intelligence helpers with lazy exports."""

from __future__ import annotations

from typing import Any


__all__ = [
    "build_automation_intelligence_manifest",
    "build_allocation_recommendation_artifact",
    "build_candidate_strategy_identity_bridge",
    "build_daily_recommendation_artifact",
    "build_ml_intelligence_patch_manifest",
    "compact_automation_intelligence_summary",
    "build_review_draft_eligibility",
    "build_strategy_factory_evidence_manifest",
    "create_review_draft_from_allocation_recommendation",
    "read_latest_daily_cycle_status",
    "read_latest_allocation_recommendation_artifact",
    "read_latest_daily_recommendation_artifact",
    "run_daily_automation_cycle",
    "write_allocation_recommendation_artifact",
    "write_candidate_strategy_identity_bridge",
    "write_daily_recommendation_artifact",
    "write_ml_intelligence_patch_manifest",
    "write_strategy_factory_evidence_manifest",
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
        "read_latest_daily_cycle_status",
        "run_daily_automation_cycle",
    }:
        from src.automation.daily_cycle import (
            read_latest_daily_cycle_status,
            run_daily_automation_cycle,
        )

        exports = {
            "read_latest_daily_cycle_status": read_latest_daily_cycle_status,
            "run_daily_automation_cycle": run_daily_automation_cycle,
        }
        return exports[name]
    if name in {
        "build_candidate_strategy_identity_bridge",
        "write_candidate_strategy_identity_bridge",
    }:
        from src.automation.candidate_strategy_identity_bridge import (
            build_candidate_strategy_identity_bridge,
            write_candidate_strategy_identity_bridge,
        )

        exports = {
            "build_candidate_strategy_identity_bridge": build_candidate_strategy_identity_bridge,
            "write_candidate_strategy_identity_bridge": write_candidate_strategy_identity_bridge,
        }
        return exports[name]
    if name in {
        "build_ml_intelligence_patch_manifest",
        "write_ml_intelligence_patch_manifest",
    }:
        from src.automation.ml_intelligence_patch_manifest import (
            build_ml_intelligence_patch_manifest,
            write_ml_intelligence_patch_manifest,
        )

        exports = {
            "build_ml_intelligence_patch_manifest": build_ml_intelligence_patch_manifest,
            "write_ml_intelligence_patch_manifest": write_ml_intelligence_patch_manifest,
        }
        return exports[name]
    if name in {
        "build_strategy_factory_evidence_manifest",
        "write_strategy_factory_evidence_manifest",
    }:
        from src.automation.strategy_factory_evidence_manifest import (
            build_strategy_factory_evidence_manifest,
            write_strategy_factory_evidence_manifest,
        )

        exports = {
            "build_strategy_factory_evidence_manifest": build_strategy_factory_evidence_manifest,
            "write_strategy_factory_evidence_manifest": write_strategy_factory_evidence_manifest,
        }
        return exports[name]
    if name in {
        "build_review_draft_eligibility",
        "create_review_draft_from_allocation_recommendation",
    }:
        from src.automation.review_draft_eligibility import (
            build_review_draft_eligibility,
            create_review_draft_from_allocation_recommendation,
        )

        exports = {
            "build_review_draft_eligibility": build_review_draft_eligibility,
            "create_review_draft_from_allocation_recommendation": create_review_draft_from_allocation_recommendation,
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
