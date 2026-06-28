"""ML evidence status rules for Strategy Intelligence Preview."""

from __future__ import annotations

from typing import Any

from src.strategy_intelligence.schema import ML_REQUIRED_EVIDENCE


ML_ARTIFACT_KEYS = {
    "feature_spec",
    "feature_spec_path",
    "target_spec",
    "target_spec_path",
    "split_spec",
    "train_validation_test_split",
    "oos_metrics",
    "walk_forward_metrics",
    "baseline_comparison",
    "model_artifact",
    "model_path",
    "feature_importance",
    "explainability_report",
}


def ml_status(row: dict[str, Any], research_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    sources = [row, row.get("research_evidence") or {}, (row.get("research_evidence") or {}).get("research_metrics") or {}]
    if research_summary:
        sources.extend([research_summary, research_summary.get("raw_summary_row") or {}])
    present = {
        key
        for source in sources
        for key in ML_ARTIFACT_KEYS
        if source.get(key) not in (None, "", [], {})
    }
    status_text = " ".join(str(source.get("ml_status") or source.get("ml_evidence_status") or "") for source in sources).lower()
    if "reject" in status_text:
        role = "ML_REJECTED"
    elif "watch" in status_text:
        role = "ML_WATCH_ONLY"
    elif present:
        role = "ML_DIAGNOSTICS_AVAILABLE"
    else:
        role = "ML_MISSING_EVIDENCE"
    missing = [] if present else list(ML_REQUIRED_EVIDENCE)
    return {
        "ml_role": role,
        "ml_evidence_status": role,
        "present_artifact_fields": sorted(present),
        "missing_evidence": missing,
    }
