"""Build Strategy Intelligence V1 cards from durable local artifacts."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


def _card(root: Path, row: dict[str, Any], paper: dict[str, Any], generated_at: str) -> dict[str, Any]:
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
        "source_artifacts": _source_artifacts(root, row, research),
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
    cards = [_card(root, row, paper, generated_at) for row in rows]
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
