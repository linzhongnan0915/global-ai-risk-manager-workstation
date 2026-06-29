"""ML Intelligence Patch Pack V0.

Reads existing ML diagnostics and missing-evidence artifacts, then exposes an
honest ML readiness view. This module never trains models, runs experiments, or
mutates financial state.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.automation.strategy_factory_evidence_manifest import (
    build_strategy_factory_evidence_manifest,
    lineage_by_identity,
)


SOURCE = "ml_intelligence_patch_pack_v0"
CACHE_RELATIVE_PATH = Path("data/automation/ml_intelligence_patch/manifest.json")
ALPHA_RESEARCH_ENV = "STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT"


def _alpha_root() -> Path:
    configured = os.environ.get(ALPHA_RESEARCH_ENV)
    return Path(configured) if configured else Path(r"D:\Global_Ai\alpha_research")


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except (OSError, json.JSONDecodeError):
        return default


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _relative(base: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _normalize_identity(value: Any) -> str:
    text = str(value or "").upper()
    text = re.sub(r"(_RESEARCH_CARD|_TEST_SPEC|_DRAFT|_EXPERIMENT_V\d+)$", "", text)
    text = re.sub(r"[^A-Z0-9]+", "_", text)
    return text.strip("_")


def _ml_path_index(alpha: Path) -> dict[str, Path]:
    index: dict[str, Path] = {}
    if not alpha.exists():
        return index
    for path in sorted(alpha.glob("**/ml_diagnostics_summary.json")):
        payload = _read_json(path, {})
        for identity in (payload.get("strategy_id"), payload.get("candidate_id"), payload.get("experiment_id")) if isinstance(payload, dict) else ():
            if identity:
                index.setdefault(_normalize_identity(identity), path)
        for parent in path.parents:
            if parent == alpha.parent:
                break
            identity = _normalize_identity(parent.name)
            if identity:
                index.setdefault(identity, path)
    return index


def _path_from_artifact(alpha: Path, artifact: dict[str, Any]) -> Path | None:
    raw = artifact.get("path") if isinstance(artifact, dict) else None
    if not raw:
        return None
    path = Path(str(raw))
    return path if path.is_absolute() else alpha / path


def _ml_path_for_item(alpha: Path, item: dict[str, Any], ml_index: dict[str, Path]) -> Path | None:
    for artifact in item.get("source_artifacts") or []:
        if isinstance(artifact, dict) and artifact.get("kind") == "ml_gate" and artifact.get("status") == "AVAILABLE":
            path = _path_from_artifact(alpha, artifact)
            if path and path.exists():
                return path
    for identity in (item.get("strategy_uid"), item.get("candidate_id"), item.get("research_card_id"), item.get("test_spec_id")):
        normalized = _normalize_identity(identity)
        if normalized in ml_index:
            return ml_index[normalized]
    return None


def _nearby_files(ml_path: Path | None) -> dict[str, Path]:
    if not ml_path:
        return {}
    folder = ml_path.parent
    names = {
        "feature_spec": [
            "ml_feature_matrix_manifest.json",
            "feature_timestamp_contract.csv",
            "feature_contract.csv",
        ],
        "target_spec": [
            "ml_target_definition.json",
            "target_contract.csv",
            "target_metadata.json",
        ],
        "timestamp_rule": [
            "timing_contract.csv",
            "feature_timestamp_contract.csv",
            "time_split_summary.csv",
        ],
        "leakage_check": [
            "ml_leakage_checks.json",
            "leakage_audit.csv",
        ],
        "split": [
            "ml_train_test_splits.csv",
            "training_window.csv",
            "test_window.csv",
            "walk_forward_windows.csv",
        ],
        "oos": [
            "walk_forward_summary.csv",
            "walk_forward_metrics.csv",
            "ml_walk_forward_predictions.csv",
        ],
        "baseline": [
            "baseline_summary.json",
            "ml_baseline_comparison.csv",
            "model_baseline_comparison.csv",
        ],
        "explainability": [
            "ml_feature_importance.csv",
            "feature_importance.csv",
            "model_decision_memo.md",
        ],
        "cost_capacity": [
            "cost_sensitivity.csv",
            "cost_sensitivity_summary.json",
            "liquidity_bucket_summary.csv",
            "capacity_summary.csv",
        ],
    }
    found: dict[str, Path] = {}
    for key, candidates in names.items():
        for name in candidates:
            path = folder / name
            if path.exists():
                found[key] = path
                break
    return found


def _text_blob(*values: Any) -> str:
    return json.dumps(values, sort_keys=True, default=str).upper()


def _ml_required(item: dict[str, Any], diag: dict[str, Any], missing: list[str]) -> bool:
    text = _text_blob(
        item.get("candidate_id"),
        item.get("research_card_id"),
        item.get("test_spec_id"),
        item.get("ml_gate_status"),
        missing,
        diag.get("ml_diagnostics_decision") if isinstance(diag, dict) else None,
    )
    return any(token in text for token in ("ML", "MACHINE_LEARNING", "MODEL", "CLASSIFICATION", "RANKING", "REGIME"))


def _ml_role(item: dict[str, Any], diag: dict[str, Any]) -> str:
    text = _text_blob(item, diag)
    if "REGIME" in text:
        return "REGIME_DETECTION"
    if "CLASSIFICATION" in text:
        return "CLASSIFICATION"
    if "RANK" in text:
        return "RANKING"
    if "VALIDATION" in text or "DIAGNOSTIC" in text:
        return "VALIDATION"
    if "ML" in text or "MODEL" in text:
        return "DISCOVERY"
    return "NOT_AVAILABLE"


def _missing_labels(item: dict[str, Any], diag: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for source in (item.get("missing_evidence") or [], diag.get("missing_evidence") if isinstance(diag, dict) else []):
        rows = source if isinstance(source, list) else [source]
        for row in rows:
            if isinstance(row, dict):
                label = row.get("missing_item") or row.get("field_name") or row.get("required_for")
            else:
                label = row
            if label:
                labels.append(str(label))
    return list(dict.fromkeys(labels))


def _risk_flags(diag: dict[str, Any], checklist: dict[str, bool]) -> dict[str, Any]:
    text = _text_blob(diag)
    leakage_status = str(diag.get("leakage_status") or "").upper() if isinstance(diag, dict) else ""
    overfit_status = str(diag.get("overfit_warning_status") or "").upper() if isinstance(diag, dict) else ""
    leakage_risk = True if any(token in leakage_status for token in ("FAIL", "HIGH", "RISK", "WATCH")) or "LEAKAGE_FAIL" in text else False
    overfit_risk = True if any(token in overfit_status for token in ("FAIL", "HIGH", "RISK")) or "OVERFIT" in text and "HIGH" in text else False
    if not diag:
        leakage_risk = None
        overfit_risk = None
    return {
        "leakage_risk": leakage_risk,
        "overfit_risk": overfit_risk,
        "missing_timestamp_rule": not checklist["timestamp_rule_available"],
        "missing_baseline": not checklist["baseline_comparison_available"],
        "missing_oos": not checklist["oos_or_walk_forward_available"],
        "missing_explainability": not checklist["explainability_output_available"],
    }


def _status(required: bool, diag: dict[str, Any], checklist: dict[str, bool], risk: dict[str, Any], missing: list[str]) -> str:
    decision = str(diag.get("ml_diagnostics_decision") or diag.get("status") or "").upper() if isinstance(diag, dict) else ""
    if risk["leakage_risk"] is True:
        return "ML_LEAKAGE_RISK"
    if risk["overfit_risk"] is True:
        return "ML_OVERFIT_RISK"
    if "REJECT" in decision:
        return "ML_REJECTED"
    if not required and not diag:
        return "ML_NOT_REQUIRED"
    if required and not diag:
        return "ML_MISSING_EVIDENCE"
    if missing or "INSUFFICIENT" in decision:
        return "ML_MISSING_EVIDENCE"
    supported_required = all(checklist.values())
    ready_required = all(
        checklist[key]
        for key in (
            "feature_spec_available",
            "target_spec_available",
            "timestamp_rule_available",
            "leakage_check_available",
            "train_validation_test_split_available",
            "oos_or_walk_forward_available",
            "baseline_comparison_available",
            "source_lineage_available",
        )
    )
    if supported_required:
        return "ML_SUPPORTED_BY_EVIDENCE"
    if ready_required:
        return "ML_READY_FOR_EXPERIMENT"
    return "ML_REVIEW_REQUIRED"


def _source_artifacts(alpha: Path, item: dict[str, Any], ml_path: Path | None, nearby: dict[str, Path]) -> list[dict[str, Any]]:
    artifacts = list(item.get("source_artifacts") or [])
    if ml_path:
        artifacts.append({"kind": "ml_diagnostics_summary", "path": _relative(alpha, ml_path), "status": "AVAILABLE"})
    for kind, path in nearby.items():
        artifacts.append({"kind": kind, "path": _relative(alpha, path), "status": "AVAILABLE"})
    return artifacts


def build_ml_intelligence_patch_manifest(
    root: str | Path,
    *,
    alpha_root: str | Path | None = None,
    strategy_cards: list[dict[str, Any]] | None = None,
    factory_manifest: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    alpha = Path(alpha_root) if alpha_root is not None else _alpha_root()
    generated_at = (now or datetime.now(timezone.utc)).isoformat()
    factory = factory_manifest or build_strategy_factory_evidence_manifest(root_path, alpha_root=alpha, now=now)
    if factory.get("status") == "MISSING_ARTIFACT":
        return {
            "ok": False,
            "status": "MISSING_ARTIFACT",
            "source": SOURCE,
            "generated_at": generated_at,
            "paper_shadow_only": True,
            "financial_state_mutated": False,
            "ml_training_performed": False,
            "summary": {
                "candidate_count": None,
                "strategy_card_match_count": None,
                "ml_gate_count": None,
                "ml_not_required_count": None,
                "ml_review_required_count": None,
                "ml_missing_evidence_count": None,
                "ml_ready_for_experiment_count": None,
                "ml_supported_by_evidence_count": None,
                "ml_rejected_count": None,
                "ml_overfit_risk_count": None,
                "ml_leakage_risk_count": None,
            },
            "items": [],
            "unmatched": {
                "factory_items_without_strategy_card_match": None,
                "strategy_cards_without_ml_patch_match": None,
                "warnings": factory.get("warnings") or [],
            },
            "warnings": factory.get("warnings") or [],
        }
    ml_index = _ml_path_index(alpha)
    cards = strategy_cards or []
    card_index = {
        _normalize_identity(card.get("strategy_uid") or card.get("candidate_id")): card
        for card in cards
        if isinstance(card, dict) and (card.get("strategy_uid") or card.get("candidate_id"))
    }
    items: list[dict[str, Any]] = []
    matched_cards: set[str] = set()
    for factory_item in factory.get("items") or []:
        if not isinstance(factory_item, dict):
            continue
        ml_path = _ml_path_for_item(alpha, factory_item, ml_index)
        diag = _read_json(ml_path, {}) if ml_path else {}
        nearby = _nearby_files(ml_path)
        missing = _missing_labels(factory_item, diag)
        required = _ml_required(factory_item, diag, missing)
        checklist = {
            "feature_spec_available": "feature_spec" in nearby,
            "target_spec_available": "target_spec" in nearby,
            "timestamp_rule_available": "timestamp_rule" in nearby,
            "leakage_check_available": "leakage_check" in nearby or bool(diag.get("leakage_status")),
            "train_validation_test_split_available": "split" in nearby,
            "oos_or_walk_forward_available": "oos" in nearby,
            "baseline_comparison_available": "baseline" in nearby,
            "explainability_output_available": "explainability" in nearby,
            "cost_turnover_capacity_available": "cost_capacity" in nearby,
            "source_lineage_available": bool(factory_item.get("source_artifacts")),
        }
        risk = _risk_flags(diag, checklist)
        ml_status = _status(required, diag, checklist, risk, missing)
        ml_role = _ml_role(factory_item, diag) if (required or diag) else "NOT_AVAILABLE"
        identities = [
            _normalize_identity(factory_item.get("strategy_uid")),
            _normalize_identity(factory_item.get("candidate_id")),
            _normalize_identity(factory_item.get("research_card_id")),
            _normalize_identity(factory_item.get("test_spec_id")),
        ]
        if any(identity in card_index for identity in identities):
            matched_cards.update(identity for identity in identities if identity in card_index)
        items.append(
            {
                "candidate_id": factory_item.get("candidate_id"),
                "strategy_uid": factory_item.get("strategy_uid"),
                "research_card_id": factory_item.get("research_card_id"),
                "test_spec_id": factory_item.get("test_spec_id"),
                "material_hash": factory_item.get("material_hash"),
                "ml_status": ml_status,
                "ml_role": ml_role,
                "evidence_checklist": checklist,
                "risk_flags": risk,
                "summary": _summary_text(ml_status, required, diag, missing),
                "missing_evidence": missing,
                "source_artifacts": _source_artifacts(alpha, factory_item, ml_path, nearby),
            }
        )
    item_index = ml_patch_by_identity({"items": items})
    strategy_without_match = None
    if strategy_cards is not None:
        strategy_without_match = sum(
            _normalize_identity(card.get("strategy_uid") or card.get("candidate_id")) not in item_index
            for card in cards
            if isinstance(card, dict)
        )
    factory_without_match = None
    if strategy_cards is not None:
        factory_without_match = max(len(items) - len(matched_cards), 0)
    counts = {status: sum(item["ml_status"] == status for item in items) for status in {item["ml_status"] for item in items}}
    review_required = sum(
        item["ml_status"] in {"ML_REVIEW_REQUIRED", "ML_MISSING_EVIDENCE", "ML_OVERFIT_RISK", "ML_LEAKAGE_RISK"}
        for item in items
    )
    status = "AVAILABLE" if items else "MISSING_ARTIFACT"
    if review_required:
        status = "REVIEW_REQUIRED"
    summary = {
        "candidate_count": len(items),
        "strategy_card_match_count": len(matched_cards) if strategy_cards is not None else None,
        "ml_gate_count": len({path.resolve() for path in ml_index.values()}),
        "ml_not_required_count": counts.get("ML_NOT_REQUIRED", 0),
        "ml_review_required_count": counts.get("ML_REVIEW_REQUIRED", 0),
        "ml_missing_evidence_count": counts.get("ML_MISSING_EVIDENCE", 0),
        "ml_ready_for_experiment_count": counts.get("ML_READY_FOR_EXPERIMENT", 0),
        "ml_supported_by_evidence_count": counts.get("ML_SUPPORTED_BY_EVIDENCE", 0),
        "ml_rejected_count": counts.get("ML_REJECTED", 0),
        "ml_overfit_risk_count": counts.get("ML_OVERFIT_RISK", 0),
        "ml_leakage_risk_count": counts.get("ML_LEAKAGE_RISK", 0),
    }
    return {
        "ok": True,
        "status": status,
        "source": SOURCE,
        "generated_at": generated_at,
        "paper_shadow_only": True,
        "financial_state_mutated": False,
        "ml_training_performed": False,
        "summary": summary,
        "items": items,
        "unmatched": {
            "factory_items_without_strategy_card_match": factory_without_match,
            "strategy_cards_without_ml_patch_match": strategy_without_match,
            "warnings": [],
        },
        "warnings": [],
    }


def _summary_text(status: str, required: bool, diag: dict[str, Any], missing: list[str]) -> str:
    if status == "ML_NOT_REQUIRED":
        return "No ML requirement was identified from canonical artifact evidence."
    if status == "ML_SUPPORTED_BY_EVIDENCE":
        return "ML diagnostics and required support artifacts are present; no ML support is fabricated."
    if status == "ML_READY_FOR_EXPERIMENT":
        return "Core ML experiment prerequisites are present, but support evidence is not complete."
    if status in {"ML_LEAKAGE_RISK", "ML_OVERFIT_RISK", "ML_REJECTED"}:
        return f"Existing ML diagnostics indicate {status}."
    if missing:
        return f"ML evidence is incomplete: {missing[0]}"
    if required and not diag:
        return "ML appears required, but no ML diagnostics artifact was found."
    return "ML evidence requires review before it can support a strategy claim."


def write_ml_intelligence_patch_manifest(
    root: str | Path,
    *,
    alpha_root: str | Path | None = None,
    strategy_cards: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> Path:
    root_path = Path(root)
    payload = build_ml_intelligence_patch_manifest(root_path, alpha_root=alpha_root, strategy_cards=strategy_cards, now=now)
    path = root_path / CACHE_RELATIVE_PATH
    _atomic_write_json(path, payload)
    return path


def ml_patch_by_identity(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in manifest.get("items") or []:
        if not isinstance(item, dict):
            continue
        for key in (item.get("strategy_uid"), item.get("candidate_id"), item.get("research_card_id"), item.get("test_spec_id")):
            normalized = _normalize_identity(key)
            if normalized:
                result.setdefault(normalized, item)
    return result


def ml_patch_for_identity(manifest: dict[str, Any], *identities: Any) -> dict[str, Any]:
    index = ml_patch_by_identity(manifest)
    match = None
    for identity in identities:
        normalized = _normalize_identity(identity)
        if normalized in index:
            match = index[normalized]
            break
    if not match:
        return {
            "status": "NOT_AVAILABLE",
            "ml_role": "NOT_AVAILABLE",
            "evidence_checklist": {},
            "risk_flags": {},
            "missing_evidence": [],
            "source_artifacts": [],
        }
    return {
        "status": match.get("ml_status") or "NOT_AVAILABLE",
        "ml_role": match.get("ml_role") or "NOT_AVAILABLE",
        "evidence_checklist": match.get("evidence_checklist") if isinstance(match.get("evidence_checklist"), dict) else {},
        "risk_flags": match.get("risk_flags") if isinstance(match.get("risk_flags"), dict) else {},
        "missing_evidence": match.get("missing_evidence") if isinstance(match.get("missing_evidence"), list) else [],
        "source_artifacts": match.get("source_artifacts") if isinstance(match.get("source_artifacts"), list) else [],
    }
