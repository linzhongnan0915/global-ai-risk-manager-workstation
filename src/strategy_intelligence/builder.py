"""Build Strategy Intelligence V1 cards from durable local artifacts."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.automation.daily_recommendation_artifact import read_latest_daily_recommendation_artifact
from src.market.paper_rebalance import paper_rebalance_snapshot_payload
from src.reporting.operational_snapshot import (
    REMOVED_CURRENT_WORKSTATION_STRATEGY_IDS,
    SNAPSHOT_VERSION,
    _entity_inventory,
    _paths,
    _read_json,
    _strategy_factory_active_unallocated_records,
    _strategy_factory_snapshot_row,
)
from src.strategy_intelligence.attribution_rules import attribution_summary
from src.strategy_intelligence.evidence_rules import decision_recommendation, evidence_strength, merge_failure_modes
from src.strategy_intelligence.mechanism_rules import classify_mechanism, research_decision
from src.strategy_intelligence.ml_status_rules import ml_status
from src.strategy_intelligence.schema import ARTIFACT_RELATIVE_PATH, COVERAGE_UNIVERSE, SCHEMA_VERSION


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _research_summary(root: Path, strategy_uid: str) -> dict[str, Any] | None:
    path = root / "data" / "research" / "canonical" / strategy_uid / "summary.json"
    return _read_json(path, None) if path.exists() else None


def _relative(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _source_artifacts(root: Path, row: dict[str, Any], research_summary: dict[str, Any] | None) -> list[dict[str, str]]:
    uid = str(row.get("strategy_uid") or row.get("strategy_id") or row.get("internal_id") or "")
    artifacts = [
        {"kind": "operational_summary", "path": "/api/snapshot-summary", "status": "READ_ONLY_ENDPOINT"},
        {"kind": "strategy_registry", "path": _relative(root, _paths(root)["canonical"]), "status": "CANONICAL_OPERATIONAL"},
    ]
    if research_summary:
        artifacts.append(
            {
                "kind": "research_summary",
                "path": _relative(root, root / "data" / "research" / "canonical" / uid / "summary.json"),
                "status": "HISTORICAL_RESEARCH",
            }
        )
    activation_path = row.get("activation_artifact_path")
    if activation_path:
        artifacts.append({"kind": "strategy_factory_activation", "path": str(activation_path), "status": "USER_CONFIRMED_LOCAL_ARTIFACT"})
    for filename in (
        "data/paper_rebalance/monthly_rebalance_proposals.json",
        "data/paper_rebalance/recommendation_review_drafts.json",
        "data/paper_rebalance/approved_rebalance_plans.json",
    ):
        path = root / filename
        if path.exists():
            artifacts.append({"kind": "paper_rebalance", "path": filename, "status": "READ_ONLY_LINEAGE"})
    return artifacts


def _latest_paper_status(paper: dict[str, Any], strategy_uid: str) -> dict[str, Any]:
    result = {"recommendation_status": "Unavailable", "proposal_status": "Unavailable", "approved_plan_status": "Unavailable"}
    for key, status_key, row_key in (
        ("monthly_proposal", "proposal_status", "rows"),
        ("recommendation_review", "recommendation_status", "line_items"),
        ("approved_rebalance", "approved_plan_status", "rows"),
    ):
        latest = (paper.get(key) or {}).get("latest_proposal") or (paper.get(key) or {}).get("latest_draft") or (paper.get(key) or {}).get("latest_plan") or {}
        rows = latest.get(row_key) or []
        if any(str(row.get("strategy_uid") or row.get("strategy_id") or "") == strategy_uid for row in rows):
            result[status_key] = str(latest.get("status") or latest.get("review_status") or "Present")
    return result


def _daily_recommendations_by_uid(root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    latest = read_latest_daily_recommendation_artifact(root)
    if not latest.get("ok"):
        return {}, latest
    artifact = latest.get("artifact") or {}
    rows = artifact.get("recommendations") if isinstance(artifact, dict) else []
    by_uid = {
        str(row.get("strategy_uid")): row
        for row in rows or []
        if isinstance(row, dict) and row.get("strategy_uid")
    }
    return by_uid, latest


def _daily_recommendation_section(
    recommendation: dict[str, Any] | None,
    latest: dict[str, Any],
) -> dict[str, Any]:
    if not latest.get("ok"):
        return {
            "status": latest.get("status") or "MISSING_ARTIFACT",
            "recommended_action": "NOT_AVAILABLE",
            "reason": latest.get("message") or "Daily recommendation artifact is not available.",
            "confidence": "NOT_AVAILABLE",
            "evidence_strength": "NOT_AVAILABLE",
            "risk_warning": None,
            "current_weight": None,
            "proposed_weight": None,
            "source_artifact": None,
        }
    if not recommendation:
        return {
            "status": "NOT_AVAILABLE",
            "recommended_action": "NOT_AVAILABLE",
            "reason": "No daily recommendation row matched this strategy_uid.",
            "confidence": "NOT_AVAILABLE",
            "evidence_strength": "NOT_AVAILABLE",
            "risk_warning": None,
            "current_weight": None,
            "proposed_weight": None,
            "source_artifact": latest.get("artifact_path"),
        }
    review_required = (
        recommendation.get("recommended_action") == "REVIEW"
        or recommendation.get("confidence") == "REVIEW_REQUIRED"
        or recommendation.get("evidence_strength") == "MISSING"
    )
    return {
        "status": "REVIEW_REQUIRED" if review_required else "AVAILABLE",
        "recommended_action": recommendation.get("recommended_action") or "NOT_AVAILABLE",
        "reason": recommendation.get("reason") or "No reason supplied by daily recommendation artifact.",
        "confidence": recommendation.get("confidence") or "NOT_AVAILABLE",
        "evidence_strength": recommendation.get("evidence_strength") or "NOT_AVAILABLE",
        "risk_warning": recommendation.get("risk_warning"),
        "current_weight": recommendation.get("current_weight"),
        "proposed_weight": recommendation.get("proposed_weight"),
        "source_artifact": latest.get("artifact_path"),
    }


def _ml_evidence_section(ml: dict[str, Any], card_artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    role = ml.get("ml_role") or "NOT_AVAILABLE"
    if role == "ML_MISSING_EVIDENCE":
        status = "MISSING_ML_EVIDENCE"
        summary = "Missing ML validation inputs; no supported ML claim is made."
    elif role == "ML_REJECTED":
        status = "REJECTED"
        summary = "ML evidence is rejected by existing status rules."
    elif role == "ML_WATCH_ONLY":
        status = "REVIEW_REQUIRED"
        summary = "ML evidence is watch-only and requires review."
    elif role == "ML_DIAGNOSTICS_AVAILABLE":
        status = "SUPPORTED"
        summary = "ML diagnostics fields are present in existing artifacts."
    else:
        status = "NOT_AVAILABLE"
        summary = "ML evidence status is not available."
    return {
        "status": status,
        "summary": summary,
        "source_artifacts": card_artifacts,
    }


def _decomposition_evidence_section(attribution: dict[str, Any], card_artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    status_text = attribution.get("status") or "NOT_AVAILABLE"
    if status_text == "Missing Attribution Evidence":
        status = "MISSING_ATTRIBUTION_EVIDENCE"
        summary = "Missing factor/sector/long-short decomposition evidence."
    elif status_text == "PARTIAL_ATTRIBUTION_EVIDENCE":
        status = "REVIEW_REQUIRED"
        summary = "Partial attribution/decomposition evidence is present and needs review."
    elif status_text == "NOT_AVAILABLE":
        status = "NOT_AVAILABLE"
        summary = "Attribution/decomposition status is not available."
    else:
        status = "AVAILABLE"
        summary = str(status_text)
    return {
        "status": status,
        "summary": summary,
        "source_artifacts": card_artifacts,
    }


def _operator_explanation(
    daily: dict[str, Any],
    ml_section: dict[str, Any],
    decomposition_section: dict[str, Any],
    missing: list[str],
) -> dict[str, Any]:
    action = daily.get("recommended_action") or "NOT_AVAILABLE"
    missing_items = list(missing[:2])
    if ml_section["status"] == "MISSING_ML_EVIDENCE" and "Missing ML Evidence" not in missing_items:
        missing_items.append("Missing ML Evidence")
    if decomposition_section["status"] == "MISSING_ATTRIBUTION_EVIDENCE" and "Missing Attribution Evidence" not in missing_items:
        missing_items.append("Missing Attribution Evidence")
    missing_items = missing_items[:4]
    return {
        "headline": f"Today's action: {action}",
        "why_this_action": daily.get("reason") or "No daily recommendation row is available for this strategy.",
        "what_is_missing": missing_items,
        "next_review_step": "Review missing ML and attribution evidence before increasing exposure."
        if missing_items
        else "Continue monitoring existing evidence and paper-only controls.",
    }


def _current_rows(root: Path) -> list[dict[str, Any]]:
    canonical = _read_json(_paths(root)["canonical"], {})
    rows = [
        deepcopy(row)
        for row in canonical.get("strategies") or []
        if row.get("membership_state") == "executed"
        and row.get("internal_id") not in REMOVED_CURRENT_WORKSTATION_STRATEGY_IDS
    ]
    by_uid = {str(row.get("internal_id")): row for row in rows if row.get("internal_id")}
    for activation in _strategy_factory_active_unallocated_records(root):
        snapshot_row = _strategy_factory_snapshot_row(activation)
        snapshot_row["activation_artifact_path"] = activation.get("activation_artifact_path")
        uid = str(snapshot_row.get("strategy_uid") or snapshot_row.get("internal_id"))
        if uid:
            by_uid[uid] = snapshot_row
    return list(by_uid.values())


def _card(
    root: Path,
    row: dict[str, Any],
    paper: dict[str, Any],
    generated_at: str,
    daily_rows: dict[str, dict[str, Any]],
    daily_latest: dict[str, Any],
) -> dict[str, Any]:
    uid = str(row.get("strategy_uid") or row.get("strategy_id") or row.get("internal_id") or "")
    research = _research_summary(root, uid)
    mechanism = classify_mechanism(row, research)
    attribution = attribution_summary(row, research)
    ml = ml_status(row, research)
    strength = evidence_strength(row, research)
    recommendation = decision_recommendation(row, strength)
    decision = research_decision(research)
    paper_status = _latest_paper_status(paper, uid)
    missing = merge_failure_modes(
        attribution.get("missing_evidence") or [],
        ml.get("missing_evidence") or [],
        ["Missing Attribution Evidence"] if attribution.get("status") == "Missing Attribution Evidence" else [],
    )
    failure_modes = merge_failure_modes(
        mechanism["failure_modes"],
        ["ML evidence missing"] if ml["ml_role"] == "ML_MISSING_EVIDENCE" else [],
        ["insufficient attribution"] if attribution["status"] == "Missing Attribution Evidence" else [],
    )
    current_weight = row.get("current_weight")
    if row.get("strategy_factory_phase2"):
        current_weight = 0.0
    source_artifacts = _source_artifacts(root, row, research)
    daily_section = _daily_recommendation_section(daily_rows.get(uid), daily_latest)
    ml_section = _ml_evidence_section(ml, source_artifacts)
    decomposition_section = _decomposition_evidence_section(attribution, source_artifacts)
    return {
        "card_id": f"strategy-intelligence::{uid}",
        "strategy_uid": uid,
        "strategy_name": row.get("display_name") or row.get("name") or row.get("strategy_name") or uid,
        "display_label": row.get("display_label") or row.get("display_id") or "Display only",
        "family": mechanism["family"],
        "mechanism_class": mechanism["mechanism_class"],
        "mechanism_source": mechanism["mechanism_source"],
        "is_generic_fallback": mechanism["is_generic_fallback"],
        "signal_metadata": mechanism["signal_metadata"],
        "source_status": "STRATEGY_FACTORY_ACTIVATION_RECORD" if row.get("strategy_factory_phase2") else "CANONICAL_OPERATIONAL",
        "portfolio_status": row.get("current_operational_status") or row.get("operational_state") or row.get("membership_state"),
        "current_weight": current_weight,
        "target_weight": row.get("target_weight") or row.get("recommended_weight") or row.get("proposed_weight"),
        "recommendation_status": paper_status["recommendation_status"],
        "proposal_status": paper_status["proposal_status"],
        "approved_plan_status": paper_status["approved_plan_status"],
        "research_decision": decision,
        "evidence_decision": decision if decision != "MISSING_RESEARCH_DECISION" else strength,
        "edge_thesis": mechanism["edge_thesis"],
        "economic_mechanism": mechanism["economic_mechanism"],
        "causal_thesis_confidence": mechanism["causal_thesis_confidence"],
        "return_attribution_summary": attribution,
        "ml_role": ml["ml_role"],
        "ml_evidence_status": ml["ml_evidence_status"],
        "evidence_strength": strength,
        "missing_evidence": missing,
        "failure_modes": failure_modes,
        "decision_recommendation": recommendation,
        "source_artifacts": source_artifacts,
        "daily_recommendation": daily_section,
        "ml_evidence": ml_section,
        "decomposition_evidence": decomposition_section,
        "operator_explanation": _operator_explanation(daily_section, ml_section, decomposition_section, missing),
        "generated_at": generated_at,
        "snapshot_version": SNAPSHOT_VERSION,
        "limitations": [
            "Rule-based V1 explanation; Causal Thesis is a hypothesis, not proof.",
            "Return Attribution remains missing unless factor/sector/long-short decomposition artifacts exist.",
            "Paper/shadow monitoring only; no execution authority is created by this card.",
            "Historical Research remains separate from Operational records.",
        ],
    }


def build_strategy_intelligence_payload(root: Path | str, *, now: datetime | None = None) -> dict[str, Any]:
    root = Path(root)
    generated_at = (now or datetime.now(timezone.utc)).isoformat()
    rows = _current_rows(root)
    paper = paper_rebalance_snapshot_payload(root)
    daily_rows, daily_latest = _daily_recommendations_by_uid(root)
    cards = [_card(root, row, paper, generated_at, daily_rows, daily_latest) for row in rows]
    daily_artifact = daily_latest.get("artifact") or {}
    daily_summary = daily_artifact.get("summary") if isinstance(daily_artifact, dict) else {}
    inventory = _entity_inventory(rows, {}, {}, {})
    summary = {
        "total_cards": len(cards),
        "strategies_explained": len(cards),
        "generic_fallback_count": sum(card["is_generic_fallback"] for card in cards),
        "cards_with_strategy_specific_mechanism": sum(not card["is_generic_fallback"] for card in cards),
        "missing_attribution_count": sum(
            card["return_attribution_summary"]["status"] == "Missing Attribution Evidence" for card in cards
        ),
        "attribution_missing_count": sum(
            card["return_attribution_summary"]["status"] == "Missing Attribution Evidence" for card in cards
        ),
        "ml_missing_evidence_count": sum(card["ml_role"] == "ML_MISSING_EVIDENCE" for card in cards),
        "ml_missing_count": sum(card["ml_role"] == "ML_MISSING_EVIDENCE" for card in cards),
        "review_required_count": sum(card["decision_recommendation"] in {"REVIEW_REQUIRED", "MISSING_EVIDENCE"} for card in cards),
        "rejected_watch_count": sum(card["decision_recommendation"] in {"REJECT_RESEARCH_ONLY", "WATCH_ONLY"} for card in cards),
        "watch_reject_review_count": sum(
            card["decision_recommendation"] in {"REJECT_RESEARCH_ONLY", "WATCH_ONLY", "REVIEW_REQUIRED", "MISSING_EVIDENCE"}
            for card in cards
        ),
        "active_unallocated_zero_weight_count": sum(
            card["decision_recommendation"] == "ACTIVE_UNALLOCATED_ZERO_WEIGHT" for card in cards
        ),
        "research_decision_counts": {
            decision: sum(card["research_decision"] == decision for card in cards)
            for decision in sorted({card["research_decision"] for card in cards})
        },
        "daily_recommendation_status": daily_latest.get("status") or "NOT_AVAILABLE",
        "daily_recommendation_count": len(daily_rows) if daily_latest.get("ok") else None,
        "daily_recommendation_review_count": (daily_summary or {}).get("review_count"),
        "daily_recommendation_missing_match_count": sum(
            card["daily_recommendation"]["recommended_action"] == "NOT_AVAILABLE" for card in cards
        ),
    }
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "snapshot_version": SNAPSHOT_VERSION,
        "coverage_universe": COVERAGE_UNIVERSE,
        "strategy_entity_inventory": inventory,
        "summary": summary,
        "cards": cards,
        "source_paths": {
            "artifact": ARTIFACT_RELATIVE_PATH,
            "canonical": _relative(root, _paths(root)["canonical"]),
            "snapshot_summary_endpoint": "/api/snapshot-summary",
            "strategy_intelligence_endpoint": "/api/strategy-intelligence",
            "daily_recommendation_artifact": daily_latest.get("artifact_path"),
        },
        "safety": {
            "state_mutation": False,
            "paper_rebalance_mutation": False,
            "full_snapshot_required": False,
            "execution_authority": "NONE",
        },
    }


def write_strategy_intelligence_artifact(root: Path | str, payload: dict[str, Any] | None = None) -> Path:
    root = Path(root)
    artifact = root / ARTIFACT_RELATIVE_PATH
    _atomic_write_json(artifact, payload or build_strategy_intelligence_payload(root))
    return artifact
