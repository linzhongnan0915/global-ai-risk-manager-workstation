"""Paper allocation proposal V1.

Builds a review-only target allocation proposal from existing backend artifacts.
It never creates review drafts, approved plans, apply events, orders, or ledger
mutations.
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SOURCE = "paper_allocation_proposal_v1"
ARTIFACT_DIR = Path("data/automation/allocation_proposals")
WEIGHT_SUM_TARGET = 1.0
WEIGHT_SUM_TOLERANCE = 0.000001
DEFAULT_CANDIDATE_STARTER_TARGET = 0.02
PROPOSAL_CYCLE = "BIWEEKLY"
SCORE_FORMULA = {
    "return": 0.30,
    "risk": 0.20,
    "evidence": 0.20,
    "diversification": 0.10,
    "cost": 0.10,
    "data_quality": 0.10,
}


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
    if number != number:
        return None
    return number


def _next_biweekly_date(as_of_date: str) -> str:
    try:
        base = datetime.fromisoformat(as_of_date).date()
    except ValueError:
        base = datetime.now(timezone.utc).date()
    return (base + timedelta(days=14)).isoformat()


def paper_allocation_proposal_dir(root: str | Path) -> Path:
    return Path(root) / ARTIFACT_DIR


def paper_allocation_proposal_path(root: str | Path, as_of_date: str) -> Path:
    return paper_allocation_proposal_dir(root) / f"{as_of_date}.json"


def latest_paper_allocation_proposal_path(root: str | Path) -> Path | None:
    folder = paper_allocation_proposal_dir(root)
    if not folder.exists():
        return None
    paths = sorted(folder.glob("*.json"), key=lambda path: (path.name, path.stat().st_mtime), reverse=True)
    return paths[0] if paths else None


def read_latest_paper_allocation_proposal(root: str | Path) -> dict[str, Any]:
    root_path = Path(root)
    path = latest_paper_allocation_proposal_path(root_path)
    if path is None:
        return {
            "ok": False,
            "status": "MISSING_ARTIFACT",
            "source": SOURCE,
            "artifact_path": None,
            "paper_shadow_only": True,
            "financial_state_mutated": False,
            "message": "No paper allocation proposal artifact has been generated yet.",
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
            "message": "Latest paper allocation proposal is missing the expected schema source.",
        }
    return {
        "ok": True,
        "status": "AVAILABLE",
        "source": SOURCE,
        "artifact_path": _relative(root_path, path),
        "artifact": payload,
        "paper_shadow_only": True,
        "financial_state_mutated": False,
    }


def _card_uid(card: dict[str, Any]) -> str:
    return str(card.get("strategy_uid") or card.get("internal_id") or "").strip()


def _display_name(card: dict[str, Any]) -> str:
    return str(card.get("display_name") or card.get("strategy_name") or _card_uid(card) or "Display unavailable")


def _is_current_allocated(card: dict[str, Any]) -> bool:
    return str(card.get("source_status") or "") == "CANONICAL_OPERATIONAL" and (_safe_number(card.get("current_weight")) or 0.0) > 0.0


def _is_active_unallocated_candidate(card: dict[str, Any]) -> bool:
    current = _safe_number(card.get("current_weight")) or 0.0
    status_text = " ".join(
        str(card.get(key) or "")
        for key in ("source_status", "portfolio_status", "decision_recommendation", "research_decision")
    ).upper()
    return current == 0.0 and "ACTIVE_UNALLOCATED" in status_text


def _role(card: dict[str, Any]) -> str:
    return str(card.get("strategy_role") or card.get("research_decision") or card.get("portfolio_status") or "UNKNOWN")


def _sleeve_type(card: dict[str, Any]) -> str:
    return str(card.get("sleeve_type") or card.get("source_status") or "UNKNOWN")


def _is_combined(card: dict[str, Any]) -> bool:
    value = card.get("is_combined")
    if isinstance(value, bool):
        return value
    role_text = " ".join(
        str(card.get(key) or "")
        for key in ("strategy_role", "sleeve_type", "research_decision", "portfolio_status", "source_status")
    ).upper()
    return "COMPOSITE" in role_text


def _daily(card: dict[str, Any]) -> dict[str, Any]:
    value = card.get("daily_recommendation")
    return value if isinstance(value, dict) else {}


def _evidence_level(card: dict[str, Any]) -> str:
    daily = _daily(card)
    raw = str(daily.get("evidence_strength") or card.get("evidence_strength") or "").upper()
    if raw in {"STRONG", "PARTIAL", "WEAK", "MISSING"}:
        return raw
    if "RESEARCH" in raw or "MODERATE" in raw or "PARTIAL" in raw:
        return "PARTIAL"
    if "MISSING" in str(card.get("ml_role") or "").upper():
        return "MISSING"
    return "PARTIAL"


def _has_research_artifact(card: dict[str, Any], source_artifacts: list[Any]) -> bool:
    evidence_text = " ".join(
        [
            str(card.get("evidence_strength") or ""),
            str(card.get("source_status") or ""),
            str(card.get("portfolio_status") or ""),
            json.dumps(source_artifacts, default=str),
        ]
    ).upper()
    return any(token in evidence_text for token in ("RESEARCH", "BACKTEST", "VARIANT", "STRATEGY_FACTORY", "ACTIVATION"))


def _evidence_status(card: dict[str, Any], source_artifacts: list[Any]) -> str:
    if _has_research_artifact(card, source_artifacts):
        return "Research Evidence Available / Institutional Validation Pending"
    if _evidence_level(card) == "MISSING":
        return "Missing Evidence"
    return "Prototype Tested / Institutional Validation Pending"


def _blockers(card: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    warning = str(_daily(card).get("risk_warning") or "")
    ml_text = str(card.get("ml_role") or card.get("ml_evidence_status") or "").upper()
    attr = card.get("return_attribution_summary") if isinstance(card.get("return_attribution_summary"), dict) else {}
    decomp = card.get("decomposition_evidence") if isinstance(card.get("decomposition_evidence"), dict) else {}
    if "MISSING" in ml_text or "ML" in warning.upper():
        blockers.append("Missing ML validation evidence")
    if "MISSING" in str(attr.get("status") or "").upper() or "MISSING" in str(decomp.get("status") or "").upper() or "ATTRIBUTION" in warning.upper():
        blockers.append("Missing attribution/decomposition evidence")
    if _is_active_unallocated_candidate(card):
        blockers.append("Paper review required before funding active-unallocated sleeve")
    return list(dict.fromkeys(blockers))


def _bounded_score(value: float | None, *, scale: float, inverse: bool = False) -> float:
    if value is None:
        return 50.0
    raw = 50.0 + max(-20.0, min(20.0, value * scale))
    return 100.0 - raw if inverse else raw


def _component_scores(card: dict[str, Any], metrics: dict[str, Any] | None = None) -> tuple[dict[str, float], list[str]]:
    warnings: list[str] = []
    metrics = metrics or {}
    daily_action = str(_daily(card).get("recommended_action") or "").upper()
    return_score = {"INCREASE": 75.0, "HOLD": 60.0, "REVIEW": 50.0, "REDUCE": 35.0}.get(daily_action)
    metric_return = _safe_number(metrics.get("daily_return"))
    if metric_return is None:
        metric_return = _safe_number(metrics.get("cumulative_return"))
    if metric_return is not None:
        return_score = (return_score or 50.0) * 0.45 + _bounded_score(metric_return, scale=900.0) * 0.55
    if return_score is None:
        return_score = 50.0
        warnings.append("Return signal unavailable; neutral component score used.")
    evidence_level = _evidence_level(card)
    evidence_score = {"STRONG": 80.0, "PARTIAL": 60.0, "WEAK": 45.0, "MISSING": 30.0}.get(evidence_level, 50.0)
    risk_source = str(card.get("risk_metric_source") or "").upper()
    risk_status = str(card.get("risk_data_status") or "").upper()
    metric_drawdown = _safe_number(metrics.get("current_drawdown"))
    if metric_drawdown is not None:
        risk_score = _bounded_score(abs(metric_drawdown), scale=650.0, inverse=True)
    elif "MISSING" in risk_source or "MISSING" in risk_status:
        risk_score = 40.0
    elif risk_source or risk_status:
        risk_score = 60.0
    else:
        risk_score = 50.0
        warnings.append("Risk metric source unavailable; neutral risk component score used.")
    data_quality = 65.0 if card.get("source_status") else 50.0
    if not card.get("source_status"):
        warnings.append("Source status unavailable; neutral data quality score used.")
    turnover = _safe_number(metrics.get("turnover"))
    transaction_cost = _safe_number(metrics.get("transaction_cost"))
    cost_score = 50.0
    if turnover is not None or transaction_cost is not None:
        cost_score = 70.0 - min(30.0, abs(turnover or 0.0) * 600.0 + abs(transaction_cost or 0.0) * 0.01)
    scores = {
        "return": return_score,
        "risk": risk_score,
        "evidence": evidence_score,
        "diversification": 50.0,
        "cost": cost_score,
        "data_quality": data_quality,
    }
    return scores, warnings


def _weighted_score(scores: dict[str, float]) -> float:
    return round(sum(scores[key] * SCORE_FORMULA[key] for key in SCORE_FORMULA), 2)


def _action(score: float, card: dict[str, Any]) -> str:
    if _is_active_unallocated_candidate(card):
        return "CANDIDATE_REVIEW"
    if score >= 70.0:
        return "INCREASE"
    if score >= 55.0:
        return "HOLD"
    if score >= 40.0:
        return "REVIEW"
    return "REDUCE"


def _confidence(score: float, blockers: list[str]) -> str:
    if blockers:
        return "REVIEW_REQUIRED"
    if score >= 70.0:
        return "MEDIUM"
    if score >= 55.0:
        return "LOW"
    return "REVIEW_REQUIRED"


def _safe_nav(root: Path) -> float | None:
    summary = _read_json(root / "data" / "operational_snapshot" / "snapshot_summary.json", {})
    nav = _safe_number(((summary.get("portfolio_summary") or {}) if isinstance(summary, dict) else {}).get("nav"))
    return nav


def _operational_metrics(root: Path) -> dict[str, dict[str, Any]]:
    contract = _read_json(root / "dashboard" / "data" / "canonical_operational.json", {})
    if not isinstance(contract, dict):
        return {}
    metrics: dict[str, dict[str, Any]] = {}
    for row in contract.get("strategies") or []:
        if isinstance(row, dict):
            uid = str(row.get("internal_id") or row.get("strategy_uid") or "").strip()
            if uid:
                metrics[uid] = row
    portfolio = contract.get("portfolio_summary")
    if isinstance(portfolio, dict):
        metrics["__COMPOSITE_PORTFOLIO_METADATA__"] = portfolio
    return metrics


def _metrics_for_card(card: dict[str, Any], metrics: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if _is_combined(card):
        return metrics.get("__COMPOSITE_PORTFOLIO_METADATA__", {})
    return metrics.get(_card_uid(card), {})


def _row_shell(card: dict[str, Any], nav: float | None, metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    component_scores, warnings = _component_scores(card, metrics)
    score = _weighted_score(component_scores)
    blockers = _blockers(card)
    current = _safe_number(card.get("current_weight")) or 0.0
    source_artifacts = card.get("source_artifacts") if isinstance(card.get("source_artifacts"), list) else []
    action = _action(score, card)
    reason = _daily(card).get("reason") or "Backend evidence produced a paper review score; missing inputs remain explicit."
    if action == "CANDIDATE_REVIEW":
        reason = "Active-unallocated research sleeve is eligible only for a small paper review target; human review required."
    return {
        "strategy_uid": _card_uid(card),
        "display_name": _display_name(card),
        "strategy_role": _role(card),
        "sleeve_type": _sleeve_type(card),
        "is_combined": _is_combined(card),
        "current_weight": current,
        "suggested_weight": None,
        "target_weight": None,
        "delta": None,
        "score": score,
        "component_scores": component_scores,
        "suggested_action": action,
        "action": action,
        "confidence": _confidence(score, blockers),
        "short_reason": reason,
        "reason": reason,
        "review_required": bool(blockers) or action in {"REVIEW", "CANDIDATE_REVIEW"},
        "paper_trade_estimate": None,
        "risk_metric_source": card.get("risk_metric_source") or card.get("risk_data_status") or "NOT_AVAILABLE",
        "evidence_level": _evidence_level(card),
        "evidence_status": _evidence_status(card, source_artifacts),
        "institutional_validation_status": "Institutional Validation Pending",
        "blockers": blockers,
        "warnings": warnings,
        "source_artifacts": source_artifacts,
        "score_inputs": {
            key: metrics.get(key)
            for key in ("daily_return", "cumulative_return", "daily_pnl", "cumulative_pnl", "current_drawdown", "turnover", "transaction_cost")
            if metrics and key in metrics
        },
        "_nav": nav,
    }


def _rank_allocated_actions(rows: list[dict[str, Any]]) -> None:
    allocated = [row for row in rows if row["suggested_action"] != "CANDIDATE_REVIEW" and row["current_weight"] > 0.0]
    if not allocated:
        return
    score_values = {round(float(row["score"]), 8) for row in allocated}
    if len(score_values) <= 1:
        for row in allocated:
            row["suggested_action"] = "HOLD"
            row["action"] = "HOLD"
            row["short_reason"] = "Hold current paper exposure because eligible allocated scores are tied on available backend inputs."
            row["reason"] = row["short_reason"]
            row["review_required"] = bool(row["blockers"])
        return
    ordered = sorted(allocated, key=lambda row: (float(row["score"]), row["strategy_uid"]), reverse=True)
    bucket = max(1, math.ceil(len(ordered) * 0.25))
    top = {id(row) for row in ordered[:bucket]}
    bottom = {id(row) for row in ordered[-bucket:]}
    for row in ordered:
        if id(row) in top:
            row["suggested_action"] = "INCREASE"
            row["short_reason"] = "Top-quartile paper allocation score among eligible allocated strategies; review required before any paper plan."
        elif id(row) in bottom:
            row["suggested_action"] = "REDUCE"
            row["short_reason"] = "Bottom-quartile paper allocation score among eligible allocated strategies; review required before any paper plan."
        elif row["confidence"] == "REVIEW_REQUIRED" and float(row["score"]) < 48.0:
            row["suggested_action"] = "REVIEW"
            row["short_reason"] = "Uncertain middle-band paper allocation score with review-required evidence gaps."
        else:
            row["suggested_action"] = "HOLD"
            row["short_reason"] = "Middle-band paper allocation score; hold proposed target after candidate funding scale-down."
        row["action"] = row["suggested_action"]
        row["reason"] = row["short_reason"]
        row["review_required"] = bool(row["blockers"]) or row["suggested_action"] == "REVIEW"


def _assign_targets(rows: list[dict[str, Any]]) -> None:
    candidates = [row for row in rows if row["suggested_action"] == "CANDIDATE_REVIEW"]
    allocated = [row for row in rows if row["suggested_action"] != "CANDIDATE_REVIEW" and row["current_weight"] > 0.0]
    candidate_total = min(DEFAULT_CANDIDATE_STARTER_TARGET * len(candidates), WEIGHT_SUM_TARGET)
    existing_budget = max(0.0, WEIGHT_SUM_TARGET - candidate_total)
    for row in candidates:
        row["suggested_weight"] = DEFAULT_CANDIDATE_STARTER_TARGET
    current_sum = sum(row["current_weight"] for row in allocated)
    if allocated and current_sum > 0.0:
        provisional: list[float] = []
        for row in allocated:
            base = (row["current_weight"] / current_sum) * existing_budget
            if row["suggested_action"] == "INCREASE":
                base += min(0.005, existing_budget / max(len(allocated), 1))
            elif row["suggested_action"] == "REDUCE":
                base = max(0.0, base - min(0.005, existing_budget / max(len(allocated), 1)))
            provisional.append(base)
        provisional_sum = sum(provisional)
        for row, target in zip(allocated, provisional):
            row["suggested_weight"] = (target / provisional_sum) * existing_budget if provisional_sum else 0.0
    for row in rows:
        if row["suggested_weight"] is None:
            row["suggested_weight"] = 0.0
    included = [row for row in rows if row["suggested_weight"] > 0.0 or row["current_weight"] > 0.0]
    residual = WEIGHT_SUM_TARGET - sum(row["suggested_weight"] for row in included)
    if included and abs(residual) > 0.0:
        included[-1]["suggested_weight"] += residual
    for row in rows:
        row["target_weight"] = row["suggested_weight"]
        row["delta"] = row["suggested_weight"] - row["current_weight"]
        nav = row.pop("_nav", None)
        row["paper_trade_estimate"] = None if nav is None else round(row["delta"] * nav, 2)


def build_paper_allocation_proposal(
    root: str | Path,
    *,
    now: datetime | None = None,
    strategy_intelligence_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from src.strategy_intelligence import build_strategy_intelligence_payload

    root_path = Path(root)
    generated_at = (now or datetime.now(timezone.utc)).isoformat()
    as_of_date = generated_at[:10]
    intelligence = strategy_intelligence_payload or build_strategy_intelligence_payload(root_path, now=now)
    cards = [card for card in (intelligence.get("cards") or []) if isinstance(card, dict) and _card_uid(card)]
    nav = _safe_nav(root_path)
    metrics = _operational_metrics(root_path)
    rows = [
        _row_shell(card, nav, _metrics_for_card(card, metrics))
        for card in cards
        if _is_current_allocated(card) or _is_active_unallocated_candidate(card)
    ]
    _rank_allocated_actions(rows)
    _assign_targets(rows)
    target_sum = sum(row["suggested_weight"] for row in rows if row["suggested_weight"] is not None)
    residual = WEIGHT_SUM_TARGET - target_sum
    sums_to_100pct = abs(residual) <= WEIGHT_SUM_TOLERANCE
    estimated_turnover = sum(abs(_safe_number(row.get("delta")) or 0.0) for row in rows)
    summary = {
        "strategy_count": len(rows),
        "included_strategy_count": sum(1 for row in rows if row["suggested_weight"] > 0.0),
        "candidate_review_count": sum(row["suggested_action"] == "CANDIDATE_REVIEW" for row in rows),
        "active_unallocated_candidate_count": sum(row["suggested_action"] == "CANDIDATE_REVIEW" for row in rows),
        "increase_count": sum(row["suggested_action"] == "INCREASE" for row in rows),
        "hold_count": sum(row["suggested_action"] == "HOLD" for row in rows),
        "review_count": sum(row["suggested_action"] == "REVIEW" for row in rows),
        "reduce_count": sum(row["suggested_action"] == "REDUCE" for row in rows),
        "review_required_count": sum(bool(row["review_required"]) for row in rows),
        "estimated_turnover": estimated_turnover,
        "estimated_transaction_cost": None,
    }
    warnings = []
    if nav is None:
        warnings.append("NAV unavailable for paper_trade_estimate; target weights are still generated.")
    if not sums_to_100pct:
        warnings.append("Target weights do not sum to 100%; paper review is blocked.")
    return {
        "ok": True,
        "source": SOURCE,
        "as_of_date": as_of_date,
        "generated_at": generated_at,
        "paper_shadow_only": True,
        "financial_state_mutated": False,
        "proposal_mode": "paper_review_proposal",
        "proposal_cycle": PROPOSAL_CYCLE,
        "next_scheduled_proposal_date": _next_biweekly_date(as_of_date),
        "biweekly_auto_generate_proposal": True,
        "biweekly_auto_approve": False,
        "biweekly_auto_apply": False,
        "target_weight_sum": target_sum,
        "sums_to_100pct": sums_to_100pct,
        "weight_sum_target": WEIGHT_SUM_TARGET,
        "weight_sum_tolerance": WEIGHT_SUM_TOLERANCE,
        "residual_weight": residual,
        "auto_approval_allowed": False,
        "auto_apply_allowed": False,
        "review_required": True,
        "score_formula": SCORE_FORMULA,
        "summary": summary,
        "current_weights": {row["strategy_uid"]: row["current_weight"] for row in rows},
        "suggested_weights": {row["strategy_uid"]: row["suggested_weight"] for row in rows},
        "rows": rows,
        "warnings": warnings,
    }


def write_paper_allocation_proposal(
    root: str | Path,
    *,
    now: datetime | None = None,
    strategy_intelligence_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    payload = build_paper_allocation_proposal(
        root_path,
        now=now,
        strategy_intelligence_payload=strategy_intelligence_payload,
    )
    path = paper_allocation_proposal_path(root_path, payload["as_of_date"])
    _atomic_write_json(path, payload)
    return {
        "ok": True,
        "status": "GENERATED",
        "source": SOURCE,
        "artifact_path": _relative(root_path, path),
        "artifact": payload,
        "paper_shadow_only": True,
        "financial_state_mutated": False,
    }
