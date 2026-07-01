"""Daily Allocation Recommendation artifact V1.

Builds deterministic paper-shadow target weights from Strategy Intelligence
cards. This is not an optimizer, does not approve/apply paper plans, and never
mutates NAV/P&L or paper rebalance state.
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SOURCE = "daily_allocation_recommendation_artifact_v1"
SCHEMA_VERSION = "daily_allocation_recommendation_v1"
ARTIFACT_DIR = Path("data/automation/daily_allocation_recommendations")
WEIGHT_SUM_TARGET = 1.0
WEIGHT_SUM_TOLERANCE = 0.000001
MATERIAL_DELTA = 0.0005
STARTER_WEIGHT = 0.02
STARTER_WEIGHT_STRONG = 0.03
MAX_SINGLE_STRATEGY_WEIGHT = 0.15
MAX_DAILY_TILT = 0.02


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _read_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _safe_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def daily_allocation_recommendation_artifact_dir(root: str | Path) -> Path:
    return Path(root) / ARTIFACT_DIR


def daily_allocation_recommendation_artifact_path(root: str | Path, recommendation_date: str) -> Path:
    return daily_allocation_recommendation_artifact_dir(root) / f"{recommendation_date}.json"


def latest_daily_allocation_recommendation_artifact_path(root: str | Path) -> Path | None:
    folder = daily_allocation_recommendation_artifact_dir(root)
    if not folder.exists():
        return None
    paths = sorted(folder.glob("*.json"), key=lambda path: (path.name, path.stat().st_mtime), reverse=True)
    return paths[0] if paths else None


def read_latest_daily_allocation_recommendation(root: str | Path) -> dict[str, Any]:
    root_path = Path(root)
    path = latest_daily_allocation_recommendation_artifact_path(root_path)
    if path is None:
        return {
            "ok": False,
            "status": "MISSING_ARTIFACT",
            "source": SOURCE,
            "artifact_path": None,
            "paper_shadow_only": True,
            "financial_state_mutated": False,
            "paper_apply_created": False,
            "approved_plan_created": False,
            "message": "No daily allocation recommendation artifact has been generated yet.",
        }
    payload = _read_json(path, {})
    if not isinstance(payload, dict) or payload.get("source") != SOURCE:
        return {
            "ok": False,
            "status": "INVALID_ARTIFACT",
            "source": SOURCE,
            "artifact_path": _relative(root_path, path),
            "paper_shadow_only": True,
            "financial_state_mutated": False,
            "paper_apply_created": False,
            "approved_plan_created": False,
            "message": "Latest daily allocation recommendation artifact is missing the expected schema source.",
        }
    return {
        "ok": True,
        "status": "AVAILABLE",
        "source": SOURCE,
        "artifact_path": _relative(root_path, path),
        "artifact": payload,
        "paper_shadow_only": True,
        "financial_state_mutated": False,
        "paper_apply_created": False,
        "approved_plan_created": False,
    }


def _canonical_uid(card: dict[str, Any]) -> str:
    lineage = card.get("activation_lineage") if isinstance(card.get("activation_lineage"), dict) else {}
    for key in ("strategy_uid", "internal_id", "strategy_id", "candidate_id"):
        value = card.get(key)
        if value:
            return str(value).strip()
    for key in ("strategy_uid", "internal_id", "candidate_id"):
        value = lineage.get(key)
        if value:
            return str(value).strip()
    return ""


def _source_artifacts(card: dict[str, Any]) -> list[Any]:
    artifacts = card.get("source_artifacts")
    return artifacts if isinstance(artifacts, list) else []


def _status_text(card: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "source_status",
        "portfolio_status",
        "decision_recommendation",
        "research_decision",
        "strategy_role",
        "sleeve_type",
        "current_operational_status",
        "membership_state",
    ):
        parts.append(str(card.get(key) or ""))
    return " ".join(parts).upper()


def _is_combined(card: dict[str, Any], uid: str) -> bool:
    if card.get("is_combined") is True:
        return True
    text = " ".join(
        str(card.get(key) or "")
        for key in ("strategy_role", "sleeve_type", "research_decision", "portfolio_status", "display_id")
    ).upper()
    return uid == "COMBINED_PORTFOLIO" or "COMPOSITE" in text or "COMBINED" in text


def _allocation_role(card: dict[str, Any], uid: str, current: float | None) -> str:
    text = _status_text(card)
    if _is_combined(card, uid):
        return "top_level_derived_composite"
    if "ACTIVE_UNALLOCATED" in text or "STRATEGY_FACTORY_ACTIVATION_RECORD" in text:
        return "active_unallocated"
    if str(card.get("source_status") or "") == "CANONICAL_OPERATIONAL" and (current or 0.0) > 0.0:
        return "ordinary_active"
    return "excluded_or_review"


def _evidence_status(card: dict[str, Any]) -> str:
    daily = card.get("daily_recommendation") if isinstance(card.get("daily_recommendation"), dict) else {}
    for value in (daily.get("evidence_strength"), card.get("evidence_strength"), card.get("evidence_status")):
        if value:
            return str(value)
    return "MISSING_EVIDENCE"


def _risk_status(card: dict[str, Any]) -> str:
    for value in (card.get("risk_status"), card.get("risk_data_status"), card.get("risk_metric_source")):
        if value:
            return str(value)
    return "MISSING_RISK_EVIDENCE"


def _ml_status(card: dict[str, Any]) -> str:
    ml = card.get("ml_evidence") if isinstance(card.get("ml_evidence"), dict) else {}
    return str(ml.get("status") or card.get("ml_evidence_status") or card.get("ml_role") or "ML_MISSING_EVIDENCE")


def _attribution_status(card: dict[str, Any]) -> str:
    attribution = card.get("return_attribution_summary") if isinstance(card.get("return_attribution_summary"), dict) else {}
    decomposition = card.get("decomposition_evidence") if isinstance(card.get("decomposition_evidence"), dict) else {}
    return str(attribution.get("status") or decomposition.get("status") or "Missing Attribution Evidence")


def _missing_evidence(card: dict[str, Any], evidence: str, risk: str, ml: str, attribution: str) -> list[str]:
    values: list[str] = []
    raw = card.get("missing_evidence")
    if isinstance(raw, list):
        values.extend(str(item) for item in raw if item)
    elif raw:
        values.append(str(raw))
    checks = {
        "Missing strategy evidence": evidence,
        "Missing risk evidence": risk,
        "Missing ML evidence": ml,
        "Missing attribution evidence": attribution,
    }
    for label, value in checks.items():
        if "MISSING" in str(value).upper() and label not in values:
            values.append(label)
    return list(dict.fromkeys(values))


def _metric(card: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = _safe_number(card.get(name))
        if value is not None:
            return value
    metrics = card.get("metrics") if isinstance(card.get("metrics"), dict) else {}
    for name in names:
        value = _safe_number(metrics.get(name))
        if value is not None:
            return value
    return None


def _score(card: dict[str, Any], role: str, missing: list[str], evidence: str, risk: str) -> tuple[float, list[str]]:
    score = 50.0
    constraints: list[str] = ["deterministic_score_not_optimizer"]
    evidence_upper = evidence.upper()
    if "STRONG" in evidence_upper:
        score += 18.0
        constraints.append("strong_evidence_bonus")
    elif "PARTIAL" in evidence_upper or "RESEARCH" in evidence_upper:
        score += 6.0
        constraints.append("partial_evidence_neutral")
    elif "WEAK" in evidence_upper or "WATCH" in evidence_upper:
        score -= 8.0
        constraints.append("weak_evidence_penalty")
    if "MISSING" in evidence_upper:
        score -= 20.0
        constraints.append("missing_evidence_penalty")
    if any("ML" in item.upper() for item in missing):
        score -= 12.0
        constraints.append("missing_ml_penalty")
    if any("ATTRIBUTION" in item.upper() or "DECOMPOSITION" in item.upper() for item in missing):
        score -= 10.0
        constraints.append("missing_attribution_penalty")
    if "MISSING" in risk.upper():
        score -= 10.0
        constraints.append("missing_risk_evidence_penalty")
    drawdown = _metric(card, "current_drawdown", "max_drawdown", "drawdown")
    if drawdown is not None and drawdown < -0.10:
        score -= min(18.0, abs(drawdown) * 100.0)
        constraints.append("high_drawdown_penalty")
    daily_pnl = _metric(card, "daily_pnl", "recent_daily_pnl")
    daily_return = _metric(card, "daily_return", "recent_return", "cumulative_return")
    if daily_pnl is not None and daily_pnl < 0:
        score -= 3.0
        constraints.append("negative_daily_pnl_penalty")
    if daily_return is not None:
        if daily_return > 0:
            score += min(5.0, daily_return * 100.0)
            constraints.append("positive_recent_return_tilt")
        elif daily_return < 0:
            score -= min(5.0, abs(daily_return) * 100.0)
            constraints.append("negative_recent_return_penalty")
    if role == "active_unallocated":
        constraints.append("active_unallocated_starter_cap")
    if role == "top_level_derived_composite":
        constraints.append("derived_composite_not_ordinary_denominator")
    return max(0.0, min(100.0, score)), constraints


def _row_shell(card: dict[str, Any]) -> dict[str, Any]:
    uid = _canonical_uid(card)
    current = _safe_number(card.get("current_weight"))
    if current is None:
        current = 0.0
    role = _allocation_role(card, uid, current)
    evidence = _evidence_status(card)
    risk = _risk_status(card)
    ml = _ml_status(card)
    attribution = _attribution_status(card)
    missing = _missing_evidence(card, evidence, risk, ml, attribution)
    score, constraints = _score(card, role, missing, evidence, risk)
    return {
        "strategy_uid": uid,
        "strategy_id": card.get("strategy_id"),
        "internal_id": card.get("internal_id"),
        "strategy_name": card.get("strategy_name") or card.get("display_name") or uid,
        "allocation_role": role,
        "current_weight": current,
        "recommended_weight": 0.0,
        "delta": None,
        "action": "REVIEW",
        "rationale": "",
        "evidence_status": evidence,
        "risk_status": risk,
        "ml_status": ml,
        "attribution_status": attribution,
        "missing_evidence": missing,
        "constraints_applied": constraints,
        "source_artifacts": _source_artifacts(card),
        "paper_state": {
            "paper_shadow_only": True,
            "paper_apply_created": False,
            "approved_plan_created": False,
        },
        "live_trading": False,
        "brokerage_execution": False,
        "_score": score,
    }


def _target_seed(row: dict[str, Any]) -> float:
    role = row["allocation_role"]
    current = float(row["current_weight"] or 0.0)
    score = float(row["_score"])
    missing = row["missing_evidence"]
    if role == "top_level_derived_composite":
        return current
    if role == "excluded_or_review":
        return 0.0
    if role == "active_unallocated":
        if score >= 72.0 and not missing:
            row["constraints_applied"].append("strong_active_unallocated_starter_cap")
            return STARTER_WEIGHT_STRONG
        if score >= 55.0 and not any("ML" in item.upper() or "ATTRIBUTION" in item.upper() for item in missing):
            return STARTER_WEIGHT
        return 0.0
    tilt = 0.0
    if score >= 70.0:
        tilt = MAX_DAILY_TILT
        row["constraints_applied"].append("score_increase_tilt")
    elif score < 40.0:
        tilt = -MAX_DAILY_TILT
        row["constraints_applied"].append("score_reduce_tilt")
    return max(0.0, min(MAX_SINGLE_STRATEGY_WEIGHT, current + tilt))


def _assign_actions(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        current = float(row["current_weight"] or 0.0)
        recommended = float(row["recommended_weight"] or 0.0)
        delta = recommended - current
        row["delta"] = delta
        role = row["allocation_role"]
        missing = row["missing_evidence"]
        if role == "top_level_derived_composite":
            row["action"] = "HOLD"
            row["rationale"] = "Derived composite is shown for source-of-truth context and excluded from ordinary allocation denominator."
        elif role == "excluded_or_review":
            row["action"] = "ZERO_WEIGHT" if recommended == 0.0 else "REVIEW"
            row["rationale"] = "Strategy is excluded or not allocation eligible in canonical source; recommended target is zero unless reviewed."
        elif missing and recommended > 0.0:
            row["action"] = "REVIEW"
            row["rationale"] = "Evidence is incomplete; keep row review-required and do not claim model confidence."
        elif abs(delta) < MATERIAL_DELTA:
            row["action"] = "HOLD"
            row["rationale"] = "Recommended target is within material daily threshold of current paper weight."
        elif delta > 0:
            row["action"] = "INCREASE"
            row["rationale"] = "Deterministic evidence/risk score supports a capped paper-shadow increase."
        else:
            row["action"] = "REDUCE"
            row["rationale"] = "Deterministic evidence/risk score supports a capped paper-shadow reduction."
        row.pop("_score", None)


def _normalize_rows(rows: list[dict[str, Any]]) -> tuple[float, float, list[str]]:
    warnings: list[str] = []
    allocatable = [row for row in rows if row["allocation_role"] in {"ordinary_active", "active_unallocated"}]
    for row in rows:
        row["recommended_weight"] = _target_seed(row)
    target_rows = [row for row in allocatable if row["recommended_weight"] > 0.0]
    seed_sum = sum(float(row["recommended_weight"]) for row in target_rows)
    if seed_sum <= 0:
        residual = 1.0
        warnings.append("No positive allocation-eligible target seeds were available; residual cash is explicit.")
        return 0.0, residual, warnings
    scale = min(1.0, WEIGHT_SUM_TARGET / seed_sum)
    for row in target_rows:
        row["recommended_weight"] = float(row["recommended_weight"]) * scale
        row["constraints_applied"].append("normalized_across_allocation_eligible_rows")
    target_sum = sum(float(row["recommended_weight"]) for row in allocatable)
    residual = max(0.0, WEIGHT_SUM_TARGET - target_sum)
    if residual > WEIGHT_SUM_TOLERANCE:
        warnings.append("Target weights do not reach 100%; residual cash is explicit instead of fabricated allocation.")
    return target_sum, residual, warnings


def build_daily_allocation_recommendation_artifact(
    root: str | Path,
    *,
    now: datetime | None = None,
    strategy_intelligence_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from src.strategy_intelligence import build_strategy_intelligence_payload

    root_path = Path(root)
    generated_at = (now or datetime.now(timezone.utc)).isoformat()
    recommendation_date = generated_at[:10]
    intelligence = strategy_intelligence_payload or build_strategy_intelligence_payload(root_path, now=now)
    cards = intelligence.get("cards") if isinstance(intelligence, dict) else []
    rows = [_row_shell(card) for card in cards or [] if isinstance(card, dict) and _canonical_uid(card)]
    target_sum, residual_cash_weight, warnings = _normalize_rows(rows)
    _assign_actions(rows)
    missing_summary: dict[str, int] = {}
    for row in rows:
        for item in row["missing_evidence"]:
            missing_summary[item] = missing_summary.get(item, 0) + 1
    action_counts: dict[str, int] = {}
    role_counts: dict[str, int] = {}
    for row in rows:
        action_counts[row["action"]] = action_counts.get(row["action"], 0) + 1
        role_counts[row["allocation_role"]] = role_counts.get(row["allocation_role"], 0) + 1
    next_actions = []
    if action_counts.get("REVIEW"):
        next_actions.append("Review rows with incomplete evidence before using targets in any proposal.")
    if role_counts.get("active_unallocated"):
        next_actions.append("Review active-unallocated starter caps before funding paper sleeves.")
    if residual_cash_weight > WEIGHT_SUM_TOLERANCE:
        next_actions.append("Residual cash remains explicit; do not force fake 100% allocation.")
    return {
        "ok": True,
        "source": SOURCE,
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "recommendation_date": recommendation_date,
        "paper_shadow_only": True,
        "financial_state_mutated": False,
        "paper_apply_created": False,
        "approved_plan_created": False,
        "input_artifacts": {
            "strategy_intelligence": "provided_payload" if strategy_intelligence_payload is not None else "/api/strategy-intelligence",
            "risk_evidence": "strategy_intelligence_card_fields",
            "paper_performance": "strategy_intelligence_card_fields_when_available",
        },
        "allocation_universe": {
            "source": "strategy_intelligence_cards",
            "row_count": len(rows),
            "role_counts": role_counts,
            "identity_keys": ["strategy_uid", "internal_id", "strategy_id", "candidate_id", "activation_lineage"],
        },
        "constraints": {
            "material_delta": MATERIAL_DELTA,
            "starter_weight": STARTER_WEIGHT,
            "starter_weight_strong": STARTER_WEIGHT_STRONG,
            "max_single_strategy_weight": MAX_SINGLE_STRATEGY_WEIGHT,
            "max_daily_tilt": MAX_DAILY_TILT,
            "weight_sum_target": WEIGHT_SUM_TARGET,
            "weight_sum_tolerance": WEIGHT_SUM_TOLERANCE,
            "method": "transparent_deterministic_score_not_optimizer",
        },
        "target_sum": target_sum,
        "residual_cash_weight": residual_cash_weight,
        "rows": rows,
        "warnings": warnings,
        "missing_evidence_summary": missing_summary,
        "next_actions": next_actions,
        "labels": {
            "artifact": "Daily Allocation Recommendation",
            "method": "Deterministic paper-shadow scoring",
            "safety": "No paper apply, no approved plan, no NAV/P&L mutation",
        },
        "summary": {
            "row_count": len(rows),
            "action_counts": action_counts,
            "role_counts": role_counts,
        },
    }


def write_daily_allocation_recommendation_artifact(
    root: str | Path,
    *,
    now: datetime | None = None,
    strategy_intelligence_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    payload = build_daily_allocation_recommendation_artifact(
        root_path,
        now=now,
        strategy_intelligence_payload=strategy_intelligence_payload,
    )
    path = daily_allocation_recommendation_artifact_path(root_path, payload["recommendation_date"])
    _atomic_write_json(path, payload)
    return {
        "ok": True,
        "status": "GENERATED",
        "source": SOURCE,
        "artifact_path": _relative(root_path, path),
        "artifact": payload,
        "paper_shadow_only": True,
        "financial_state_mutated": False,
        "paper_apply_created": False,
        "approved_plan_created": False,
    }
