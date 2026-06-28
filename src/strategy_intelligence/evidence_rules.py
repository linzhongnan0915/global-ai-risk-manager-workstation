"""Evidence strength and decision recommendation rules."""

from __future__ import annotations

from typing import Any


def _status_text(row: dict[str, Any], research_summary: dict[str, Any] | None = None) -> str:
    evidence = row.get("research_evidence") or {}
    metrics = evidence.get("research_metrics") or {}
    parts = [
        row.get("evidence_status"),
        row.get("data_quality_status"),
        row.get("backtest_status"),
        row.get("current_operational_status"),
        row.get("operational_state"),
        row.get("action_status"),
        metrics.get("evidence_status"),
        metrics.get("data_quality_status"),
    ]
    if research_summary:
        parts.extend(
            [
                research_summary.get("decision"),
                research_summary.get("research_status"),
                (research_summary.get("raw_summary_row") or {}).get("decision"),
            ]
        )
    return " ".join(str(part or "") for part in parts).upper()


def evidence_strength(row: dict[str, Any], research_summary: dict[str, Any] | None = None) -> str:
    text = _status_text(row, research_summary)
    if "REJECT" in text:
        return "REJECTED_EVIDENCE"
    if "WATCH" in text or "ARCHIVE" in text:
        return "WATCH_ONLY"
    if "CONNECTED" in text or "COMPLETE" in text or "CONTINUE" in text:
        return "MODERATE_RESEARCH_EVIDENCE"
    if "MISSING" in text or "PENDING" in text:
        return "MISSING_EVIDENCE"
    return "PARTIAL_EVIDENCE"


def decision_recommendation(row: dict[str, Any], strength: str) -> str:
    status = str(row.get("current_operational_status") or row.get("operational_state") or "").upper()
    uid = str(row.get("strategy_uid") or row.get("strategy_id") or row.get("internal_id") or "")
    if uid == "COMBINED_PORTFOLIO":
        return "ACTIVE_MONITOR"
    if status in {"ACTIVE_UNALLOCATED", "ACTIVE_PENDING_REBALANCE"} or row.get("strategy_factory_phase2"):
        return "ACTIVE_UNALLOCATED_ZERO_WEIGHT"
    if strength == "REJECTED_EVIDENCE":
        return "REJECT_RESEARCH_ONLY"
    if strength == "WATCH_ONLY":
        return "WATCH_ONLY"
    if strength == "MISSING_EVIDENCE":
        return "MISSING_EVIDENCE"
    if str(row.get("membership_state") or "").lower() == "executed":
        return "ACTIVE_MONITOR"
    return "REVIEW_REQUIRED"


def merge_failure_modes(*groups: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for group in groups:
        for item in group:
            key = item.strip().lower()
            if key and key not in seen:
                seen.add(key)
                merged.append(item)
    return merged
