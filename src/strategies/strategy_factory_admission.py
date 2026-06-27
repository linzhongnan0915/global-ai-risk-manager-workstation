"""Artifact-driven Strategy Factory variant admission workflow.

This module deliberately writes local research/admission artifacts only. It
does not mutate the canonical paper ledger, enable live trading, or connect to
brokerage execution.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import hashlib
import json
import re


BLOCKED_REASON = "Candidate admission disabled: proxy-only data and robustness/risk limitations."
SAFETY_LABELS = [
    "PROTOTYPE_ONLY",
    "NOT_LIVE_TRADING",
    "NOT_INSTITUTIONAL_VALIDATION",
    "USER_CONFIRMATION_REQUIRED",
]
ADMISSION_STATES = [
    "RESEARCH_OUTPUT",
    "CANDIDATE_BLOCKED",
    "CANDIDATE_READY",
    "IN_CANDIDATE_PORTFOLIO",
    "RISK_REVIEW_PENDING",
    "RISK_REVIEW_PASSED",
    "RISK_REVIEW_FAILED",
    "ALLOCATION_DRAFT_READY",
    "AWAITING_USER_CONFIRMATION",
    "PAPER_APPLIED",
]
SANDBOX_CONFIRMATION_TEXT = (
    "I understand this is prototype research-only paper sandbox exposure, "
    "not approved portfolio admission, and live trading remains disabled."
)
PORTFOLIO_CANDIDATE_CONFIRMATION_TEXT = (
    "I want to add this strategy to the portfolio candidate list."
)
ACTIVATION_CONFIRMATION_TEXT = (
    "Activate this strategy with 0.00% initial allocation and make it eligible for rebalance recommendations."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _factory_root(root: Path) -> Path:
    return root / "output" / "strategy_factory"


def _runs_dir(root: Path) -> Path:
    return _factory_root(root) / "runs"


def _admission_root(root: Path) -> Path:
    return _factory_root(root) / "admission"


def _portfolio_candidates_root(root: Path) -> Path:
    return _factory_root(root) / "portfolio_candidates"


def _portfolio_candidate_dir(root: Path, candidate_id: str) -> Path:
    return _portfolio_candidates_root(root) / candidate_id


def _safe_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned[:120] or "UNKNOWN"


def candidate_id_for(run_id: str, variant_id: str) -> str:
    digest = hashlib.sha1(f"{run_id}:{variant_id}".encode("utf-8")).hexdigest()[:10].upper()
    return f"SF_CAND_{_safe_id(variant_id)}_{digest}"


def sandbox_id_for(run_id: str, variant_id: str) -> str:
    digest = hashlib.sha1(f"sandbox:{run_id}:{variant_id}".encode("utf-8")).hexdigest()[:10].upper()
    return f"SF_SANDBOX_{_safe_id(variant_id)}_{digest}"


def _candidate_dir(root: Path, candidate_id: str) -> Path:
    return _admission_root(root) / candidate_id


def _sandbox_root(root: Path) -> Path:
    return _factory_root(root) / "sandbox"


def _sandbox_dir(root: Path, sandbox_id: str) -> Path:
    return _sandbox_root(root) / sandbox_id


def _variant_dir(root: Path, run_id: str, variant_id: str) -> Path:
    return _runs_dir(root) / run_id / "variants" / variant_id


def _variant_card(root: Path, run_id: str, variant_id: str) -> dict:
    variant_dir = _variant_dir(root, run_id, variant_id)
    evaluation_dir = variant_dir / "evaluation"
    variants_dir = variant_dir.parent
    spec = _read_json(variant_dir / "variant_spec.json", {})
    registry = _read_json(variants_dir / "variant_registry.json", {})
    ranking = _read_json(variants_dir / "variant_ranking.json", {})
    ranking_by_id = {row.get("variant_id"): row for row in ranking.get("rankings") or []}
    registry_by_id = {row.get("variant_id"): row for row in registry.get("variants") or []}
    rank_row = ranking_by_id.get(variant_id, {})
    reg_row = registry_by_id.get(variant_id, {})
    metrics = _read_json(evaluation_dir / "variant_metrics.json", {})
    ml = _read_json(evaluation_dir / "variant_ml_diagnostics_run.json", {})
    robustness = _read_json(evaluation_dir / "variant_robustness_run.json", {})
    decision = _read_json(evaluation_dir / "variant_decision.json", {})
    evidence_path = evaluation_dir / "variant_evidence_report.md"
    if not spec and not reg_row and not rank_row:
        raise ValueError("variant artifacts not found")
    candidate_allowed = bool(rank_row.get("candidate_allowed") or decision.get("candidate_allowed") or decision.get("candidate"))
    synthetic = bool(spec.get("synthetic_admission_test_only") or reg_row.get("synthetic_admission_test_only"))
    return {
        "run_id": run_id,
        "variant_id": variant_id,
        "variant_name": spec.get("variant_name") or reg_row.get("variant_name") or rank_row.get("variant_name") or variant_id,
        "theme": spec.get("theme") or reg_row.get("theme"),
        "strategy_name": spec.get("strategy_name") or spec.get("variant_name") or reg_row.get("strategy_name") or reg_row.get("variant_name") or variant_id,
        "source_material_ids": spec.get("source_material_ids") or [],
        "thesis": spec.get("thesis"),
        "signal_formula": spec.get("signal_formula"),
        "universe_or_proxy": spec.get("universe_or_proxy") or reg_row.get("universe_or_proxy") or [],
        "benchmark": spec.get("benchmark") or reg_row.get("benchmark"),
        "features": spec.get("features") or [],
        "model_plan": spec.get("model_plan") or {},
        "data_requirements": spec.get("data_requirements") or [],
        "metrics": metrics,
        "ml": ml,
        "robustness": robustness,
        "decision": decision,
        "ranking": rank_row,
        "candidate_allowed": candidate_allowed,
        "synthetic_admission_test_only": synthetic,
        "final_recommendation": rank_row.get("final_recommendation") or decision.get("recommendation"),
        "decision_reason": decision.get("reason") or rank_row.get("reason") or "",
        "artifact_paths": {
            "variant_spec": str(variant_dir / "variant_spec.json"),
            "variant_metrics": str(evaluation_dir / "variant_metrics.json"),
            "variant_ml_diagnostics": str(evaluation_dir / "variant_ml_diagnostics_run.json"),
            "variant_robustness": str(evaluation_dir / "variant_robustness_run.json"),
            "variant_decision": str(evaluation_dir / "variant_decision.json"),
            "variant_evidence_report": str(evidence_path) if evidence_path.exists() else None,
            "variant_ranking": str(variants_dir / "variant_ranking.json"),
        },
    }


def _admission_path(root: Path, candidate_id: str) -> Path:
    return _candidate_dir(root, candidate_id) / "candidate_admission.json"


def _load_admission(root: Path, candidate_id: str) -> dict:
    return _read_json(_admission_path(root, candidate_id), {})


def _write_log(root: Path, candidate_id: str, event: dict) -> dict:
    log_path = _candidate_dir(root, candidate_id) / "admission_log.json"
    log = _read_json(log_path, {"schema_version": "strategy_factory_admission_log_v1", "candidate_id": candidate_id, "events": []})
    log["events"].append({"timestamp": _now(), **event})
    _write_json(log_path, log)
    return log


def _state_response(root: Path, candidate_id: str, run_id: str, variant_id: str, status: str, message: str = "") -> dict:
    admission = _load_admission(root, candidate_id)
    return {
        "ok": status not in {"CANDIDATE_BLOCKED"},
        "candidate_id": candidate_id,
        "run_id": run_id,
        "variant_id": variant_id,
        "state": status,
        "status": status,
        "message": message,
        "admission": admission,
        "artifacts": _artifact_status(root, candidate_id),
        "safety": {
            "paper_only": True,
            "live_trading": False,
            "brokerage_execution": False,
            "paper_ledger_mutated": False,
        },
    }


def _artifact_status(root: Path, candidate_id: str) -> dict:
    base = _candidate_dir(root, candidate_id)
    names = [
        "candidate_admission.json",
        "candidate_portfolio_entry.json",
        "risk_review.json",
        "allocation_draft.json",
        "transaction_cost_estimate.json",
        "risk_impact_estimate.json",
        "paper_apply_confirmation.json",
        "combined_recompute_request.json",
        "admission_log.json",
        "paper_strategy_sleeve.json",
        "strategy_monitor_target.json",
        "allocation_rebalance_target.json",
        "portfolio_pnl_target.json",
        "risk_contribution_target.json",
        "correlation_target.json",
        "downstream_refresh_targets.json",
        "downstream_integration_status.json",
    ]
    return {name: str(base / name) if (base / name).exists() else None for name in names}


def _portfolio_candidate_artifacts(root: Path, candidate_id: str) -> dict:
    base = _portfolio_candidate_dir(root, candidate_id)
    names = ["portfolio_candidate.json", "activation_record.json", "activation_log.json"]
    return {name: str(base / name) if (base / name).exists() else None for name in names}


def _portfolio_candidate_log(root: Path, candidate_id: str, event: dict) -> dict:
    path = _portfolio_candidate_dir(root, candidate_id) / "activation_log.json"
    log = _read_json(
        path,
        {"schema_version": "strategy_factory_portfolio_candidate_activation_log_v1", "candidate_id": candidate_id, "events": []},
    )
    log["events"].append({"timestamp": _now(), **event})
    _write_json(path, log)
    return log


def _portfolio_candidate_eligible(variant: dict) -> tuple[bool, str]:
    recommendation = _variant_recommendation(variant)
    metrics = variant.get("metrics") or {}
    if recommendation in {"Reject", "Blocked"}:
        return False, "Reject/Blocked variants cannot be added to Portfolio Candidates."
    if recommendation not in {"Watch", "Modify"}:
        return False, "Only Watch/Modify variants can be added to Portfolio Candidates in Phase 1."
    if str(metrics.get("status") or "").upper() == "BLOCKED":
        return False, "Data-blocked variants cannot be added to Portfolio Candidates."
    if not metrics or metrics.get("sharpe") is None:
        return False, "Usable backtest metrics are required before Portfolio Candidate add."
    if not (variant.get("artifact_paths") or {}).get("variant_evidence_report"):
        return False, "Evidence report artifact is required before Portfolio Candidate add."
    return True, "Eligible for user-confirmed Portfolio Candidate add."


def _canonical_display_numbers(root: Path) -> list[int]:
    canonical = _read_json(root / "dashboard" / "data" / "canonical_operational.json", {})
    numbers: list[int] = []
    for strategy in canonical.get("strategies") or []:
        internal_id = str(strategy.get("internal_id") or "")
        if internal_id == "COMBINED_PORTFOLIO" or str(strategy.get("family") or "").lower() == "combined":
            continue
        match = re.fullmatch(r"#(\d{6})", str(strategy.get("display_id") or ""))
        if match:
            numbers.append(int(match.group(1)))
    return numbers


def _is_combined_strategy(row: dict) -> bool:
    return bool(
        row.get("internal_id") == "COMBINED_PORTFOLIO"
        or row.get("display_id") == "#COMBINED"
        or str(row.get("family") or "").lower() == "combined"
        or "combined" in str(row.get("strategy_type") or "").lower()
    )


def _canonical_active_count_breakdown(root: Path) -> dict[str, int]:
    canonical = _read_json(root / "dashboard" / "data" / "canonical_operational.json", {})
    rows = [
        row
        for row in canonical.get("strategies") or []
        if row.get("membership_state", "executed") == "executed"
        and row.get("internal_id") not in set(canonical.get("removed_from_current_workstation_strategy_ids") or [])
    ]
    combined = [row for row in rows if _is_combined_strategy(row)]
    ordinary = [row for row in rows if not _is_combined_strategy(row)]
    return {
        "ordinary_active_count": len(ordinary),
        "combined_active_count": len(combined),
        "top_level_active_count": len(ordinary) + len(combined),
    }


def _activation_records(root: Path) -> list[dict]:
    rows: list[dict] = []
    for path in sorted(_portfolio_candidates_root(root).glob("*/activation_record.json")):
        payload = _read_json(path, {})
        if payload:
            rows.append(payload)
    return rows


def _has_real_activation_consent(row: dict | None) -> bool:
    payload = row or {}
    return bool(
        payload.get("user_confirmed_at")
        and payload.get("activation_confirmed_at")
        and payload.get("user_action_id")
        and payload.get("activation_source") == "USER_UI"
        and payload.get("activation_confirmation") is True
        and payload.get("TEST_ARTIFACT") is not True
        and payload.get("SMOKE_ONLY") is not True
        and payload.get("EXCLUDE_FROM_ACTIVE_UNIVERSE") is not True
    )


def _strategy_uid(run_id: str, variant_id: str) -> str:
    digest = hashlib.sha256(f"{run_id}|{variant_id}".encode("utf-8")).hexdigest()[:12].upper()
    return f"SF_STRATEGY_UID_{digest}_{_safe_id(variant_id)}"


def _next_strategy_display_id(root: Path) -> str:
    numbers = _canonical_display_numbers(root)
    for activation in _activation_records(root):
        if not _has_real_activation_consent(activation):
            continue
        match = re.fullmatch(r"#(\d{6})", str(activation.get("display_id") or ""))
        if match:
            numbers.append(int(match.group(1)))
    return f"#{(max(numbers) if numbers else 0) + 1:06d}"


def _portfolio_candidate_payload(root: Path, run_id: str, variant_id: str, *, user_confirmation: bool, user_action_id: str | None = None) -> dict:
    variant = _variant_card(root, run_id, variant_id)
    eligible, reason = _portfolio_candidate_eligible(variant)
    candidate_id = candidate_id_for(run_id, variant_id)
    if not eligible:
        _portfolio_candidate_log(root, candidate_id, {"event": "portfolio_candidate_blocked", "reason": reason})
        return {
            "ok": False,
            "candidate_id": candidate_id,
            "run_id": run_id,
            "variant_id": variant_id,
            "state": "PORTFOLIO_CANDIDATE_BLOCKED",
            "status": "PORTFOLIO_CANDIDATE_BLOCKED",
            "reason": reason,
            "live_trading": False,
            "brokerage_execution": False,
        }
    if user_confirmation is not True:
        raise ValueError("explicit user_confirmation=true required to add Portfolio Candidate")
    now = _now()
    action_id = user_action_id or f"USER_UI_ACCEPT_{candidate_id}_{now}"
    metrics = variant.get("metrics") or {}
    ml = variant.get("ml") or {}
    ranking = variant.get("ranking") or {}
    return {
        "schema_version": "strategy_factory_portfolio_candidate_v1",
        "candidate_id": candidate_id,
        "strategy_uid": _strategy_uid(run_id, variant_id),
        "run_id": run_id,
        "source_run_id": run_id,
        "variant_id": variant_id,
        "source_material_hash": variant.get("source_material_hash") or (variant.get("source_variant") or {}).get("source_material_hash"),
        "strategy_name": variant.get("strategy_name") or variant.get("variant_name") or variant_id,
        "theme": variant.get("theme"),
        "variant_name": variant.get("variant_name") or variant_id,
        "thesis": variant.get("thesis"),
        "signal_formula": variant.get("signal_formula"),
        "universe_or_proxy": variant.get("universe_or_proxy") or [],
        "benchmark": variant.get("benchmark"),
        "recommendation": _variant_recommendation(variant),
        "candidate_allowed": bool(variant.get("candidate_allowed")),
        "evidence_metrics": {
            "sharpe": metrics.get("sharpe"),
            "annual_return": metrics.get("annual_return") or metrics.get("annualized_return"),
            "max_drawdown": metrics.get("max_drawdown"),
            "evidence_score": ranking.get("evidence_score"),
            "ml_summary": ml.get("recommendation") or ml.get("status") or "Missing Evidence",
        },
        "status": "IN_PORTFOLIO_CANDIDATES",
        "state": "IN_PORTFOLIO_CANDIDATES",
        "user_confirmed": True,
        "user_confirmed_at": now,
        "user_action_id": action_id,
        "acceptance_source": "USER_UI",
        "confirmation_text": PORTFOLIO_CANDIDATE_CONFIRMATION_TEXT,
        "simulated": True,
        "live_trading": False,
        "brokerage_execution": False,
        "current_weight": 0.0,
        "target_weight": 0.0,
        "recommended_weight": "RECOMMENDATION_PENDING",
        "eligible_for_optimizer": False,
        "eligible_for_rebalance": False,
        "active_strategy": False,
        "nav_pnl_impact": "NONE_UNTIL_ACTIVATED_AND_REBALANCED",
        "created_at": now,
        "updated_at": now,
        "source_variant": variant,
    }


def add_portfolio_candidate(root: Path, run_id: str, variant_id: str, user_confirmation: bool, user_action_id: str | None = None) -> dict:
    candidate = _portfolio_candidate_payload(root, run_id, variant_id, user_confirmation=user_confirmation, user_action_id=user_action_id)
    if not candidate.get("ok", True):
        return candidate
    candidate_id = candidate["candidate_id"]
    existing = _read_json(_portfolio_candidate_dir(root, candidate_id) / "portfolio_candidate.json", {})
    if existing.get("status") in {"IN_PORTFOLIO_CANDIDATES", "ACTIVE_UNALLOCATED", "ACTIVE_PENDING_REBALANCE"}:
        candidate = {**existing, "updated_at": _now()}
    _write_json(_portfolio_candidate_dir(root, candidate_id) / "portfolio_candidate.json", candidate)
    _portfolio_candidate_log(root, candidate_id, {"event": "portfolio_candidate_added", "status": "IN_PORTFOLIO_CANDIDATES"})
    return {
        "ok": True,
        "message": "Added to Portfolio Candidates. Strategy is not active until Activate Strategy is confirmed.",
        "candidate": candidate,
        **get_portfolio_candidates_status(root, run_id=run_id, variant_id=variant_id),
    }


def activate_portfolio_candidate(
    root: Path,
    run_id: str,
    variant_id: str,
    user_confirmation: bool,
    user_action_id: str | None = None,
    activation_source: str = "USER_UI",
    smoke_only: bool = False,
) -> dict:
    candidate_id = candidate_id_for(run_id, variant_id)
    candidate_path = _portfolio_candidate_dir(root, candidate_id) / "portfolio_candidate.json"
    candidate = _read_json(candidate_path, {})
    if not candidate:
        raise ValueError("portfolio candidate artifact required before activation")
    if user_confirmation is not True:
        raise ValueError("explicit user_confirmation=true required to activate strategy")
    activation_path = _portfolio_candidate_dir(root, candidate_id) / "activation_record.json"
    existing = _read_json(activation_path, {})
    before_counts = _canonical_active_count_breakdown(root)
    if existing and _has_real_activation_consent(existing):
        return {
            "ok": True,
            "message": "Strategy already activated as Active Unallocated.",
            "activation": existing,
            **get_portfolio_candidates_status(root, run_id=run_id, variant_id=variant_id),
        }
    display_id = existing.get("display_id") or candidate.get("display_id") or _next_strategy_display_id(root)
    numeric = display_id.removeprefix("#")
    now = _now()
    action_id = user_action_id or f"USER_UI_ACTIVATE_{candidate_id}_{now}"
    is_smoke = bool(smoke_only or activation_source != "USER_UI")
    active_status = "PENDING_USER_APPROVAL" if is_smoke else "ACTIVE_UNALLOCATED"
    activation = {
        "schema_version": "strategy_factory_active_unallocated_strategy_v1",
        "candidate_id": candidate_id,
        "strategy_uid": candidate.get("strategy_uid") or _strategy_uid(run_id, variant_id),
        "strategy_id": candidate.get("strategy_uid") or _strategy_uid(run_id, variant_id),
        "sleeve_id": f"SF_SLEEVE_{numeric}_{_safe_id(variant_id)}",
        "display_id": display_id,
        "display_label": display_id,
        "run_id": run_id,
        "source_run_id": run_id,
        "variant_id": variant_id,
        "source_material_hash": candidate.get("source_material_hash") or ((candidate.get("source_variant") or {}).get("source_material_hash")),
        "strategy_name": candidate.get("strategy_name") or candidate.get("variant_name") or variant_id,
        "status": active_status,
        "state": active_status,
        "membership_state": "pending_user_approval" if is_smoke else "active_unallocated",
        "current_weight": 0.0,
        "target_weight": 0.0,
        "recommended_weight": "RECOMMENDATION_PENDING",
        "proposed_weight": "RECOMMENDATION_PENDING",
        "eligible_for_optimizer": True,
        "eligible_for_rebalance": True,
        "nav_pnl_impact": "NONE_WHILE_CURRENT_WEIGHT_ZERO",
        "activation_confirmation_text": ACTIVATION_CONFIRMATION_TEXT,
        "user_confirmed": True,
        "user_confirmed_at": candidate.get("user_confirmed_at") or now,
        "activation_confirmed_at": None if is_smoke else now,
        "user_action_id": action_id,
        "activation_source": activation_source,
        "activation_confirmation": False if is_smoke else True,
        "TEST_ARTIFACT": True if is_smoke else False,
        "SMOKE_ONLY": True if is_smoke else False,
        "EXCLUDE_FROM_ACTIVE_UNIVERSE": True if is_smoke else False,
        "simulated": True,
        "live_trading": False,
        "brokerage_execution": False,
        "created_at": now,
        "activated_at": now,
    }
    candidate.update(
        {
            "status": "ACTIVE_UNALLOCATED",
            "state": active_status,
            "active_strategy": not is_smoke,
            "display_id": display_id,
            "display_label": display_id,
            "strategy_uid": activation["strategy_uid"],
            "strategy_id": activation["strategy_uid"],
            "current_weight": 0.0,
            "target_weight": 0.0,
            "recommended_weight": "RECOMMENDATION_PENDING",
            "eligible_for_optimizer": True,
            "eligible_for_rebalance": True,
            "activation_confirmed_at": activation["activation_confirmed_at"],
            "activation_source": activation["activation_source"],
            "activation_confirmation": activation["activation_confirmation"],
            "TEST_ARTIFACT": activation["TEST_ARTIFACT"],
            "SMOKE_ONLY": activation["SMOKE_ONLY"],
            "EXCLUDE_FROM_ACTIVE_UNIVERSE": activation["EXCLUDE_FROM_ACTIVE_UNIVERSE"],
            "updated_at": now,
        }
    )
    if is_smoke:
        candidate["status"] = "PENDING_USER_APPROVAL"
    _write_json(candidate_path, candidate)
    _write_json(activation_path, activation)
    _portfolio_candidate_log(root, candidate_id, {"event": "strategy_activated", "status": active_status, "display_id": display_id, "smoke_only": is_smoke})
    return {
        "ok": True,
        "message": (
            f"User-approved activation: {display_id} with 0.00% current allocation."
            if not is_smoke
            else f"Smoke/test activation recorded for {display_id}; excluded from active universe pending user approval."
        ),
        "activation": activation,
        "ordinary_active_count_before": before_counts["ordinary_active_count"],
        "combined_active_count_before": before_counts["combined_active_count"],
        "top_level_active_count_before": before_counts["top_level_active_count"],
        "ordinary_active_count_after": before_counts["ordinary_active_count"] + (0 if is_smoke else 1),
        "combined_active_count_after": before_counts["combined_active_count"],
        "top_level_active_count_after": before_counts["top_level_active_count"] + (0 if is_smoke else 1),
        "next_ordinary_display_label_after_approval": display_id,
        **get_portfolio_candidates_status(root, run_id=run_id, variant_id=variant_id),
    }


def get_portfolio_candidates_status(root: Path, run_id: str | None = None, variant_id: str | None = None) -> dict:
    rows: list[dict] = []
    for path in sorted(_portfolio_candidates_root(root).glob("*/portfolio_candidate.json")):
        payload = _read_json(path, {})
        if payload:
            cid = payload.get("candidate_id") or path.parent.name
            activation = _read_json(path.parent / "activation_record.json", {})
            confirmed = payload.get("user_confirmed") is True
            activation_confirmed = _has_real_activation_consent(activation) if activation else False
            row = {**payload, "activation": activation or None, "artifacts": _portfolio_candidate_artifacts(root, cid)}
            display_label = row.get("display_label") or row.get("display_id") or activation.get("display_label") or activation.get("display_id")
            row["display_label"] = display_label
            row["strategy_uid"] = row.get("strategy_uid") or activation.get("strategy_uid") or _strategy_uid(str(row.get("run_id") or ""), str(row.get("variant_id") or ""))
            row["strategy_id"] = row["strategy_uid"]
            if activation and not activation_confirmed:
                row = {
                    **row,
                    "status": "PENDING_USER_APPROVAL",
                    "state": "PENDING_USER_APPROVAL",
                    "active_strategy": False,
                    "pending_user_approval": True,
                    "eligible_for_optimizer": False,
                    "eligible_for_rebalance": False,
                    "nav_pnl_impact": "NONE_PENDING_USER_APPROVAL",
                }
            elif not confirmed:
                row = {
                    **row,
                    "status": "NEEDS_USER_CONFIRMATION",
                    "state": "NEEDS_USER_CONFIRMATION",
                    "active_strategy": False,
                    "legacy_unconfirmed": True,
                }
            rows.append(row)
    candidate_id = candidate_id_for(run_id, variant_id) if run_id and variant_id else None
    selected = next((row for row in rows if row.get("candidate_id") == candidate_id), None) if candidate_id else (rows[-1] if rows else None)
    active = [row for row in rows if row.get("status") in {"ACTIVE_UNALLOCATED", "ACTIVE_PENDING_REBALANCE"} and _has_real_activation_consent(row.get("activation") or row)]
    watchlist = [row for row in rows if row.get("status") == "IN_PORTFOLIO_CANDIDATES"]
    pending = [row for row in rows if row.get("status") == "PENDING_USER_APPROVAL"]
    counts = _canonical_active_count_breakdown(root)
    return {
        "ok": True,
        "schema_version": "strategy_factory_portfolio_candidates_status_v1",
        "state": (selected or {}).get("status") or "NOT_ADDED",
        "selected": selected,
        "candidates": rows,
        "watchlist": watchlist,
        "pending_approval": pending,
        "active_unallocated": active,
        "candidate_count": len(watchlist),
        "pending_approval_count": len(pending),
        "active_unallocated_count": len(active),
        "ordinary_active_count": counts["ordinary_active_count"] + len(active),
        "combined_active_count": counts["combined_active_count"],
        "top_level_active_count": counts["top_level_active_count"] + len(active),
        "next_ordinary_display_label": _next_strategy_display_id(root),
        "live_trading": False,
        "brokerage_execution": False,
    }


def _downstream_status(root: Path, candidate_id: str) -> dict:
    return _read_json(
        _candidate_dir(root, candidate_id) / "downstream_integration_status.json",
        {
            "strategy_monitor": "PENDING_NEXT_PAPER_REFRESH",
            "allocation": "PENDING_NEXT_PAPER_REFRESH",
            "risk": "PENDING_RISK_RECALCULATION",
            "correlation": "PENDING_NEXT_PAPER_REFRESH",
            "portfolio_nav_pnl": "PENDING_NEXT_PAPER_REFRESH",
            "combined": "PENDING_COMBINED_RECOMPUTE",
        },
    )


def _write_downstream_targets(root: Path, candidate_id: str, sleeve: dict, draft: dict, recompute: dict) -> dict:
    base = _candidate_dir(root, candidate_id)
    common = {
        "candidate_id": candidate_id,
        "strategy_id": sleeve["strategy_id"],
        "sleeve_id": sleeve["sleeve_id"],
        "source_run_id": sleeve["source_run_id"],
        "variant_id": sleeve["variant_id"],
        "target_weight": sleeve["target_weight"],
        "effective_date": sleeve["effective_date"],
        "paper_only": True,
        "live_trading": False,
        "brokerage_execution": False,
        "synthetic_admission_test_only": bool(sleeve.get("synthetic_admission_test_only")),
    }
    transaction = sleeve.get("transaction_cost_estimate") or {}
    allocation_delta = sleeve.get("allocation_delta") or {}
    targets = {
        "strategy_monitor_target.json": {
            "schema_version": "strategy_factory_strategy_monitor_target_v1",
            **common,
            "target_status": "PENDING_NEXT_PAPER_REFRESH",
            "visible_after": "next paper snapshot refresh",
            "nav_pnl_status": "PENDING_NEXT_PAPER_REFRESH",
        },
        "allocation_rebalance_target.json": {
            "schema_version": "strategy_factory_allocation_rebalance_target_v1",
            **common,
            "target_status": "PENDING_NEXT_PAPER_REFRESH",
            "allocation_delta": allocation_delta,
            "transaction_cost_estimate": transaction,
            "requires_review": True,
        },
        "portfolio_pnl_target.json": {
            "schema_version": "strategy_factory_portfolio_pnl_target_v1",
            **common,
            "target_status": "PENDING_NEXT_PAPER_REFRESH",
            "nav_status": "PENDING_NEXT_PAPER_REFRESH",
            "pnl_status": "PENDING_NEXT_PAPER_REFRESH",
            "nav_pnl_fabricated": False,
            "reason": "No NAV/P&L is generated until the next paper refresh has real downstream data.",
        },
        "risk_contribution_target.json": {
            "schema_version": "strategy_factory_risk_contribution_target_v1",
            **common,
            "target_status": "PENDING_NEXT_PAPER_REFRESH",
            "risk_impact_estimate": draft.get("risk_impact_estimate") or {},
            "risk_contribution_status": "PENDING_NEXT_PAPER_REFRESH",
        },
        "correlation_target.json": {
            "schema_version": "strategy_factory_correlation_target_v1",
            **common,
            "target_status": "PENDING_NEXT_PAPER_REFRESH",
            "correlation_status": "PENDING_NEXT_PAPER_REFRESH",
            "minimum_history_required": "pending paper return history",
        },
        "downstream_integration_status.json": {
            "schema_version": "strategy_factory_downstream_integration_status_v1",
            **common,
            "strategy_monitor": "PENDING_NEXT_PAPER_REFRESH",
            "allocation": "PENDING_NEXT_PAPER_REFRESH",
            "risk": "PENDING_RISK_RECALCULATION",
            "correlation": "PENDING_NEXT_PAPER_REFRESH",
            "portfolio_nav_pnl": "PENDING_NEXT_PAPER_REFRESH",
            "combined": "PENDING_COMBINED_RECOMPUTE",
            "combined_recompute_request_path": str(base / "combined_recompute_request.json"),
            "combined_recompute_required": True,
            "ready_flags": {
                "strategy_monitor": False,
                "allocation": False,
                "risk": False,
                "correlation": False,
                "portfolio_nav_pnl": False,
                "combined": False,
            },
        },
    }
    targets["downstream_refresh_targets.json"] = {
        "schema_version": "strategy_factory_downstream_refresh_targets_v1",
        **common,
        "targets": {
            "Strategy Monitor": "PENDING_NEXT_PAPER_REFRESH",
            "Allocation/Rebalance": "PENDING_NEXT_PAPER_REFRESH",
            "Portfolio NAV/P&L": "PENDING_NEXT_PAPER_REFRESH",
            "Risk Contribution": "PENDING_RISK_RECALCULATION",
            "Correlation": "PENDING_NEXT_PAPER_REFRESH",
            "Combined Strategy": "PENDING_COMBINED_RECOMPUTE",
        },
        "nav_pnl_fabricated": False,
        "combined_recompute_required": True,
    }
    for filename, payload in targets.items():
        _write_json(base / filename, payload)
    return targets["downstream_integration_status.json"]


def _default_target_weight(variant: dict) -> float:
    metrics = variant.get("metrics") or {}
    ranking = variant.get("ranking") or {}
    robustness = variant.get("robustness") or {}
    summary = robustness.get("summary") or {}
    evidence_score = float(ranking.get("evidence_score") or 0.0)
    sharpe = float(metrics.get("sharpe") or 0.0)
    proxy_or_public = bool(metrics.get("prototype_proxy_only")) or "public" in str(metrics.get("provider_mode") or "").lower()
    strong = evidence_score >= 80 and sharpe >= 1.0 and summary.get("overall_status") == "PASS" and not proxy_or_public
    return 0.02 if strong else 0.01


def _clamp_target_weight(value: float | None, variant: dict) -> float:
    requested = float(value) if value is not None else _default_target_weight(variant)
    return max(0.0, min(requested, 0.03))


def _sandbox_target_weight(value: float | None, variant: dict) -> float:
    metrics = variant.get("metrics") or {}
    ranking = variant.get("ranking") or {}
    requested = float(value) if value is not None else (0.01 if float(ranking.get("evidence_score") or 0.0) >= 55 and float(metrics.get("sharpe") or 0.0) >= 0.25 else 0.005)
    return max(0.0, min(requested, 0.01))


def _variant_recommendation(variant: dict) -> str:
    return str(variant.get("final_recommendation") or (variant.get("decision") or {}).get("recommendation") or "").strip()


def _sandbox_data_quality_status(metrics: dict, variant: dict) -> str:
    if metrics.get("status") == "BLOCKED":
        return "BLOCKED"
    if metrics.get("prototype_proxy_only") or (variant.get("decision_reason") or "").lower().find("proxy") >= 0:
        return "PROXY_ONLY"
    return metrics.get("data_quality_status") or metrics.get("provider_mode") or "Missing Evidence"


def _sandbox_ml_support(variant: dict) -> dict:
    ml = variant.get("ml") or {}
    model = ml.get("model") or ml.get("model_used") or ml.get("best_model")
    status = ml.get("status")
    if not ml:
        return {
            "status": "Missing Evidence",
            "model_type": None,
            "support": "Missing Evidence",
        }
    return {
        "status": status or "Missing Evidence",
        "model_type": model,
        "support": ml.get("interpretation") or ml.get("summary") or status or "Missing Evidence",
        "prediction_quality": ml.get("prediction_quality"),
        "direction_quality": ml.get("direction_quality"),
    }


def _sandbox_eligible(variant: dict) -> tuple[bool, str]:
    recommendation = _variant_recommendation(variant).lower()
    metrics = variant.get("metrics") or {}
    if recommendation in {"reject", "blocked", "block"}:
        return False, "Reject/Blocked variants cannot enter the paper sandbox."
    if recommendation not in {"watch", "modify"}:
        return False, "Paper sandbox is only for Watch or Modify research variants."
    if metrics.get("status") == "BLOCKED":
        return False, "Blocked data/backtest evidence cannot enter the paper sandbox."
    if metrics.get("sharpe") is None and metrics.get("annual_return") is None and metrics.get("max_drawdown") is None:
        return False, "Backtest/metrics evidence is required before paper sandbox monitoring."
    return True, "Eligible for user-confirmed paper sandbox monitoring."


def _sandbox_artifact_status(root: Path, sandbox_id: str) -> dict:
    base = _sandbox_dir(root, sandbox_id)
    names = [
        "sandbox_admission.json",
        "sandbox_paper_sleeve.json",
        "sandbox_allocation_draft.json",
        "sandbox_transaction_cost_estimate.json",
        "sandbox_risk_impact_estimate.json",
        "sandbox_combined_recompute_request.json",
        "sandbox_monitoring_status.json",
    ]
    return {name: str(base / name) if (base / name).exists() else None for name in names}


def _portfolio_monitor_payload(payload: dict) -> dict:
    if not payload:
        return payload
    enriched = dict(payload)
    enriched.setdefault("simulated", True)
    enriched.setdefault("paper_only", True)
    enriched.setdefault("live_trading", False)
    enriched.setdefault("brokerage_execution", False)
    enriched.setdefault("in_portfolio_monitor", enriched.get("status") == "SANDBOX_MONITORING")
    enriched.setdefault("ready_for_monitoring", enriched.get("status") == "SANDBOX_MONITORING")
    enriched.setdefault("ready_for_refresh", enriched.get("status") == "SANDBOX_MONITORING")
    enriched.setdefault("next_refresh_required", enriched.get("status") == "SANDBOX_MONITORING")
    enriched.setdefault("portfolio_monitor_status", "PENDING_FIRST_REFRESH")
    enriched.setdefault("evidence_report_available", bool((enriched.get("source_variant") or {}).get("evidence_report_path")))
    return enriched


def _sandbox_status_payload(root: Path, run_id: str | None, variant_id: str | None, sandbox_id: str | None = None) -> dict:
    if not sandbox_id and run_id and variant_id:
        sandbox_id = sandbox_id_for(run_id, variant_id)
    sandbox = _portfolio_monitor_payload(_read_json(_sandbox_dir(root, sandbox_id) / "sandbox_admission.json", {})) if sandbox_id else {}
    return {
        "ok": True,
        "schema_version": "strategy_factory_sandbox_status_v1",
        "sandbox_id": sandbox_id,
        "run_id": run_id or sandbox.get("source_run_id"),
        "variant_id": variant_id or sandbox.get("variant_id"),
        "state": sandbox.get("status") or "NOT_ADDED",
        "status": sandbox.get("status") or "NOT_ADDED",
        "sandbox": sandbox,
        "artifacts": _sandbox_artifact_status(root, sandbox_id) if sandbox_id else {},
        "paper_only": True,
        "live_trading": False,
        "brokerage_execution": False,
    }


def get_sandbox_status(root: Path, run_id: str | None = None, variant_id: str | None = None, sandbox_id: str | None = None) -> dict:
    if run_id and variant_id:
        return _sandbox_status_payload(root, run_id, variant_id, sandbox_id)
    sandboxes = []
    for path in sorted(_sandbox_root(root).glob("*/sandbox_admission.json")):
        payload = _portfolio_monitor_payload(_read_json(path, {}))
        if payload:
            sandboxes.append(payload)
    return {
        "ok": True,
        "schema_version": "strategy_factory_sandbox_status_v1",
        "state": sandboxes[-1].get("status") if sandboxes else "NOT_ADDED",
        "latest": sandboxes[-1] if sandboxes else None,
        "sandboxes": sandboxes,
        "paper_only": True,
        "live_trading": False,
        "brokerage_execution": False,
    }


def add_to_paper_sandbox(
    root: Path,
    run_id: str,
    variant_id: str,
    *,
    user_confirmation: bool,
    override_reason: str | None = None,
    target_weight: float | None = None,
) -> dict:
    variant = _variant_card(root, run_id, variant_id)
    eligible, reason = _sandbox_eligible(variant)
    sandbox_id = sandbox_id_for(run_id, variant_id)
    if not eligible:
        return {
            "ok": False,
            "sandbox_id": sandbox_id,
            "state": "SANDBOX_BLOCKED",
            "status": "SANDBOX_BLOCKED",
            "error": reason,
            "message": reason,
            "paper_only": True,
            "live_trading": False,
            "brokerage_execution": False,
        }
    if user_confirmation is not True:
        raise ValueError("explicit user_confirmation=true required for paper sandbox")
    now = _now()
    recommendation = _variant_recommendation(variant)
    ranking = variant.get("ranking") or {}
    metrics = variant.get("metrics") or {}
    weight = _sandbox_target_weight(target_weight, variant)
    data_quality_status = _sandbox_data_quality_status(metrics, variant)
    strict_candidate_allowed = bool(variant.get("candidate_allowed"))
    sandbox_only_reason = (
        "Strict admission blocked by proxy-only data and robustness/risk limitations; "
        "approved only for user-confirmed research paper sandbox monitoring."
        if not strict_candidate_allowed
        else "Paper sandbox monitoring is research-only and separate from strict institutional admission."
    )
    key_metrics = {
        "sharpe": metrics.get("sharpe"),
        "max_drawdown": metrics.get("max_drawdown"),
        "annualized_return": metrics.get("annual_return") or metrics.get("annualized_return"),
        "volatility": metrics.get("volatility"),
        "turnover": metrics.get("turnover"),
        "transaction_cost_assumption": metrics.get("cost_assumption"),
        "evidence_score": ranking.get("evidence_score"),
        "data_quality_status": data_quality_status,
        "ml_support": _sandbox_ml_support(variant),
    }
    base_common = {
        "sandbox_id": sandbox_id,
        "run_id": run_id,
        "source_run_id": run_id,
        "variant_id": variant_id,
        "variant_name": variant.get("variant_name"),
        "strategy_name": variant.get("variant_name"),
        "candidate_name": variant.get("variant_name"),
        "source_material_ids": variant.get("source_material_ids") or [],
        "research_source": (variant.get("source_material_ids") or ["Missing Evidence"])[0],
        "recommendation": recommendation,
        "decision_status": "SANDBOX_MONITORING",
        "evidence_score": ranking.get("evidence_score"),
        "override_reason": override_reason or "User-confirmed prototype research-only paper sandbox monitoring.",
        "sandbox_only_reason": sandbox_only_reason,
        "strict_admission_status": "BLOCKED" if not strict_candidate_allowed else "STRICT_REVIEW_AVAILABLE",
        "candidate_allowed": strict_candidate_allowed,
        "target_weight": weight,
        "simulated": True,
        "paper_only": True,
        "live_trading": False,
        "brokerage_execution": False,
        "user_confirmed": True,
        "status": "SANDBOX_MONITORING",
        "monitoring_status": "MONITORING_PENDING_REFRESH",
        "portfolio_monitor_status": "PENDING_FIRST_REFRESH",
        "in_portfolio_monitor": True,
        "ready_for_monitoring": True,
        "ready_for_refresh": True,
        "next_refresh_required": True,
        "evidence_report_available": bool(variant.get("evidence_report_path") or variant.get("evidence_report_url")),
        "created_at": now,
        "key_metrics": key_metrics,
        "next_required_validation_steps": [
            "Replace proxy/public fallback data with Boss/API or institutional-grade vendor data.",
            "Run forward paper monitoring without mutating official NAV or official paper ledger.",
            "Re-evaluate robustness, transaction costs, drawdown contribution, and correlation after fresh paper observations.",
            "Require separate strict candidate approval before any official portfolio admission.",
        ],
    }
    transaction = {
        "schema_version": "strategy_factory_sandbox_transaction_cost_estimate_v1",
        **base_common,
        "basis_points_one_way": 5,
        "estimated_portfolio_notional": 1_000_000,
        "estimated_trade_notional": 1_000_000 * weight,
        "estimated_cost_usd": 1_000_000 * weight * 0.0005,
    }
    risk = {
        "schema_version": "strategy_factory_sandbox_risk_impact_estimate_v1",
        **base_common,
        "estimated_drawdown_contribution": abs(float(metrics.get("max_drawdown") or 0.0)) * weight,
        "risk_impact_status": "PENDING_RISK_RECALCULATION",
    }
    allocation = {
        "schema_version": "strategy_factory_sandbox_allocation_draft_v1",
        **base_common,
        "allocation_delta": {sandbox_id: weight},
        "funding_source": "CASH_OR_PRO_RATA_REDUCTION_REVIEW_REQUIRED",
        "transaction_cost_estimate": transaction,
        "risk_impact_estimate": risk,
        "combined_recompute_required": True,
    }
    sleeve = {
        "schema_version": "strategy_factory_sandbox_paper_sleeve_v1",
        **base_common,
        "sandbox_sleeve_id": f"PAPER_SANDBOX_SLEEVE_{sandbox_id}",
        "strategy_id": f"SF_SANDBOX_STRATEGY_{sandbox_id}",
        "effective_date": now[:10],
        "research_monitoring_only": True,
        "not_institutional_validation": True,
        "approved_strategy": False,
        "transaction_cost_estimate": transaction,
        "allocation_delta": allocation["allocation_delta"],
        "combined_recompute_required": True,
    }
    recompute = {
        "schema_version": "strategy_factory_sandbox_combined_recompute_request_v1",
        **base_common,
        "sandbox_sleeve_id": sleeve["sandbox_sleeve_id"],
        "combined_recompute_status": "PENDING_COMBINED_RECOMPUTE",
        "combined_recompute_required": True,
        "accounting_logic_changed": False,
        "combined_n_semantics_changed": False,
    }
    monitoring = {
        "schema_version": "strategy_factory_sandbox_monitoring_status_v1",
        **base_common,
        "sandbox_sleeve_id": sleeve["sandbox_sleeve_id"],
        "warning": SANDBOX_CONFIRMATION_TEXT,
        "downstream_targets": {
            "Strategy Monitor": "PENDING_NEXT_PAPER_REFRESH",
            "Allocation/Rebalance": "PENDING_NEXT_PAPER_REFRESH",
            "Portfolio NAV/P&L": "PENDING_NEXT_PAPER_REFRESH",
            "Risk Contribution": "PENDING_RISK_RECALCULATION",
            "Correlation": "PENDING_NEXT_PAPER_REFRESH",
            "Combined Strategy": "PENDING_COMBINED_RECOMPUTE",
        },
        "nav_pnl_fabricated": False,
    }
    admission = {
        "schema_version": "strategy_factory_sandbox_admission_v1",
        **base_common,
        "created_at": now,
        "updated_at": now,
        "warning": SANDBOX_CONFIRMATION_TEXT,
        "sandbox_sleeve_id": sleeve["sandbox_sleeve_id"],
        "transaction_cost_estimate": transaction,
        "risk_impact_estimate": risk,
        "combined_recompute_required": True,
        "downstream_targets": monitoring["downstream_targets"],
        "source_variant": variant,
    }
    base = _sandbox_dir(root, sandbox_id)
    _write_json(base / "sandbox_admission.json", admission)
    _write_json(base / "sandbox_paper_sleeve.json", sleeve)
    _write_json(base / "sandbox_allocation_draft.json", allocation)
    _write_json(base / "sandbox_transaction_cost_estimate.json", transaction)
    _write_json(base / "sandbox_risk_impact_estimate.json", risk)
    _write_json(base / "sandbox_combined_recompute_request.json", recompute)
    _write_json(base / "sandbox_monitoring_status.json", monitoring)
    return {
        "ok": True,
        "message": "Paper sandbox monitoring sleeve created. This is not approved portfolio admission.",
        "sandbox_id": sandbox_id,
        "state": "SANDBOX_MONITORING",
        "status": "SANDBOX_MONITORING",
        "sandbox_admission": admission,
        "sandbox_paper_sleeve": sleeve,
        "sandbox_monitoring_status": monitoring,
        **get_sandbox_status(root, run_id, variant_id),
    }


def get_admission_status(root: Path, run_id: str | None = None, variant_id: str | None = None, candidate_id: str | None = None) -> dict:
    if not candidate_id and run_id and variant_id:
        candidate_id = candidate_id_for(run_id, variant_id)
    if not candidate_id:
        admissions = []
        for path in sorted(_admission_root(root).glob("*/candidate_admission.json")):
            payload = _read_json(path, {})
            if payload:
                admissions.append(payload)
        return {
            "ok": True,
            "schema_version": "strategy_factory_admission_status_v1",
            "states": ADMISSION_STATES,
            "admissions": admissions,
            "latest": admissions[-1] if admissions else None,
            "live_trading": False,
            "brokerage_execution": False,
        }
    admission = _load_admission(root, candidate_id)
    state = admission.get("status") or ("RESEARCH_OUTPUT" if run_id and variant_id else "UNAVAILABLE")
    return {
        "ok": True,
        "schema_version": "strategy_factory_admission_status_v1",
        "candidate_id": candidate_id,
        "run_id": run_id or admission.get("run_id"),
        "variant_id": variant_id or admission.get("variant_id"),
        "state": state,
        "status": state,
        "admission": admission,
        "artifacts": _artifact_status(root, candidate_id),
        "downstream_refresh_status": _downstream_status(root, candidate_id),
        "states": ADMISSION_STATES,
        "live_trading": False,
        "brokerage_execution": False,
    }


def add_candidate(root: Path, run_id: str, variant_id: str, target_weight: float | None = None) -> dict:
    variant = _variant_card(root, run_id, variant_id)
    candidate_id = candidate_id_for(run_id, variant_id)
    if not variant["candidate_allowed"]:
        _write_log(root, candidate_id, {"event": "add_candidate_blocked", "reason": BLOCKED_REASON})
        return _state_response(root, candidate_id, run_id, variant_id, "CANDIDATE_BLOCKED", BLOCKED_REASON)

    created_at = _now()
    admission = {
        "schema_version": "strategy_factory_candidate_admission_v1",
        "candidate_id": candidate_id,
        "run_id": run_id,
        "variant_id": variant_id,
        "variant_name": variant["variant_name"],
        "status": "IN_CANDIDATE_PORTFOLIO",
        "candidate_allowed": True,
        "target_weight": _clamp_target_weight(target_weight, variant),
        "created_at": created_at,
        "updated_at": created_at,
        "safety_labels": SAFETY_LABELS,
        "paper_only": True,
        "live_trading": False,
        "brokerage_execution": False,
        "paper_ledger_mutated": False,
        "synthetic_admission_test_only": variant["synthetic_admission_test_only"],
        "source_variant": variant,
        "next_action": "Run Risk Review",
    }
    entry = {
        "schema_version": "strategy_factory_candidate_portfolio_entry_v1",
        "candidate_id": candidate_id,
        "run_id": run_id,
        "variant_id": variant_id,
        "candidate_name": variant["variant_name"],
        "status": "IN_CANDIDATE_PORTFOLIO",
        "target_weight": admission["target_weight"],
        "paper_only": True,
        "live_trading": False,
        "synthetic_admission_test_only": variant["synthetic_admission_test_only"],
        "artifact_path": str(_candidate_dir(root, candidate_id) / "candidate_portfolio_entry.json"),
        "created_at": created_at,
    }
    _write_json(_candidate_dir(root, candidate_id) / "candidate_admission.json", admission)
    _write_json(_candidate_dir(root, candidate_id) / "candidate_portfolio_entry.json", entry)
    _write_log(root, candidate_id, {"event": "candidate_added", "status": "IN_CANDIDATE_PORTFOLIO"})
    return {"ok": True, "message": "Variant added to Candidate Portfolio artifact. Paper Portfolio unchanged.", **get_admission_status(root, run_id, variant_id)}


def run_risk_review(root: Path, run_id: str, variant_id: str) -> dict:
    candidate_id = candidate_id_for(run_id, variant_id)
    admission = _load_admission(root, candidate_id)
    if not admission:
        raise ValueError("candidate admission artifact required before risk review")
    variant = admission.get("source_variant") or _variant_card(root, run_id, variant_id)
    metrics = variant.get("metrics") or {}
    ranking = variant.get("ranking") or {}
    robustness = variant.get("robustness") or {}
    ml = variant.get("ml") or {}
    summary = robustness.get("summary") or {}
    max_drawdown = float(metrics.get("max_drawdown") or 0.0)
    sharpe = float(metrics.get("sharpe") or 0.0)
    evidence_score = float(ranking.get("evidence_score") or 0.0)
    data_quality_score = float(ranking.get("data_quality_score") or 0.0)
    ml_score = float(ranking.get("ml_score") or 0.0)
    transaction_cost_ok = True
    robustness_ok = summary.get("overall_status") == "PASS" or (variant.get("ranking") or {}).get("robustness_score", 0) >= 65
    ml_ok = (ml.get("status") in {None, "COMPLETED", "BLOCKED"}) and ml_score >= 50
    proxy_only = bool(metrics.get("prototype_proxy_only"))
    passed = (
        bool(admission.get("candidate_allowed"))
        and evidence_score >= 65
        and sharpe >= 0.5
        and max_drawdown > -0.35
        and robustness_ok
        and data_quality_score >= 60
        and ml_ok
        and transaction_cost_ok
        and not proxy_only
    )
    review_required = bool(admission.get("candidate_allowed")) and not passed and evidence_score >= 55 and max_drawdown > -0.45
    status = "PASS" if passed else "REVIEW_REQUIRED" if review_required else "FAIL"
    review_status = "RISK_REVIEW_PASSED" if passed else "RISK_REVIEW_FAILED"
    target_weight = float(admission.get("target_weight") or 0.02)
    transaction = {
        "schema_version": "strategy_factory_transaction_cost_estimate_v1",
        "candidate_id": candidate_id,
        "basis_points_one_way": 5,
        "target_weight": target_weight,
        "estimated_portfolio_notional": 1_000_000,
        "estimated_trade_notional": 1_000_000 * target_weight,
        "estimated_cost_usd": 1_000_000 * target_weight * 0.0005,
        "paper_only": True,
        "live_trading": False,
    }
    risk_impact = {
        "schema_version": "strategy_factory_risk_impact_estimate_v1",
        "candidate_id": candidate_id,
        "target_weight": target_weight,
        "estimated_drawdown_contribution": abs(max_drawdown) * target_weight,
        "portfolio_risk_delta": target_weight,
        "risk_notes": "Artifact estimate only; no paper ledger mutation.",
        "paper_only": True,
        "live_trading": False,
    }
    review = {
        "schema_version": "strategy_factory_risk_review_v1",
        "candidate_id": candidate_id,
        "run_id": run_id,
        "variant_id": variant_id,
        "status": status,
        "admission_state": review_status,
        "candidate_allowed": bool(admission.get("candidate_allowed")),
        "checks": {
            "candidate_allowed": "PASS" if admission.get("candidate_allowed") else "FAIL",
            "evidence_score": "PASS" if evidence_score >= 65 else "WATCH",
            "sharpe": "PASS" if sharpe >= 0.5 else "WATCH",
            "max_drawdown": "PASS" if max_drawdown > -0.35 else "FAIL",
            "robustness": "PASS" if robustness_ok else "WATCH",
            "data_quality": "PASS" if data_quality_score >= 60 else "WATCH",
            "ml_support": "PASS" if ml_ok else "WATCH",
            "transaction_cost_estimate": "PASS" if transaction_cost_ok else "WATCH",
            "correlation_risk_impact": "WATCH",
            "proxy_only": "FAIL" if proxy_only else "PASS",
            "live_trading_disabled": "PASS",
            "brokerage_execution_disabled": "PASS",
        },
        "reason": "Risk review passed for paper-only admission artifact." if passed else "Risk review requires manual review before paper apply." if review_required else "Risk review failed; paper apply blocked.",
        "transaction_cost_estimate_path": str(_candidate_dir(root, candidate_id) / "transaction_cost_estimate.json"),
        "risk_impact_estimate_path": str(_candidate_dir(root, candidate_id) / "risk_impact_estimate.json"),
        "created_at": _now(),
    }
    admission["status"] = review_status
    admission["updated_at"] = _now()
    admission["risk_review_status"] = status
    admission["next_action"] = "Generate Allocation Draft" if passed else "Review failed risk checks"
    _write_json(_candidate_dir(root, candidate_id) / "risk_review.json", review)
    _write_json(_candidate_dir(root, candidate_id) / "transaction_cost_estimate.json", transaction)
    _write_json(_candidate_dir(root, candidate_id) / "risk_impact_estimate.json", risk_impact)
    _write_json(_candidate_dir(root, candidate_id) / "candidate_admission.json", admission)
    _write_log(root, candidate_id, {"event": "risk_review", "status": status, "admission_state": review_status})
    status_payload = get_admission_status(root, run_id, variant_id)
    return {**status_payload, "ok": passed, "message": review["reason"], "risk_review": review}


def generate_allocation_draft(root: Path, run_id: str, variant_id: str, target_weight: float | None = None) -> dict:
    candidate_id = candidate_id_for(run_id, variant_id)
    admission = _load_admission(root, candidate_id)
    if not admission:
        raise ValueError("candidate admission artifact required before allocation draft")
    risk = _read_json(_candidate_dir(root, candidate_id) / "risk_review.json", {})
    if risk.get("status") != "PASS":
        raise ValueError("risk review PASS required before allocation draft")
    variant = admission.get("source_variant") or _variant_card(root, run_id, variant_id)
    weight = _clamp_target_weight(target_weight if target_weight is not None else admission.get("target_weight"), variant)
    transaction = _read_json(_candidate_dir(root, candidate_id) / "transaction_cost_estimate.json", {})
    risk_impact = _read_json(_candidate_dir(root, candidate_id) / "risk_impact_estimate.json", {})
    draft = {
        "schema_version": "strategy_factory_allocation_draft_v1",
        "candidate_id": candidate_id,
        "run_id": run_id,
        "variant_id": variant_id,
        "status": "ALLOCATION_DRAFT_READY",
        "target_weight": weight,
        "current_weights": {},
        "proposed_weights": {candidate_id: weight},
        "allocation_delta": {candidate_id: weight},
        "funding_source": "CASH_OR_PRO_RATA_REVIEW_REQUIRED",
        "transaction_cost_estimate": transaction,
        "risk_impact_estimate": risk_impact,
        "combined_recompute_required": True,
        "requires_user_confirmation": True,
        "paper_only": True,
        "live_trading": False,
        "brokerage_execution": False,
        "created_at": _now(),
    }
    admission["status"] = "AWAITING_USER_CONFIRMATION"
    admission["updated_at"] = _now()
    admission["target_weight"] = weight
    admission["next_action"] = "Apply to Paper Portfolio requires explicit user confirmation"
    _write_json(_candidate_dir(root, candidate_id) / "allocation_draft.json", draft)
    _write_json(_candidate_dir(root, candidate_id) / "candidate_admission.json", admission)
    _write_log(root, candidate_id, {"event": "allocation_draft_ready", "target_weight": weight})
    return {"ok": True, "message": "Allocation draft ready. Paper apply awaits explicit confirmation.", "allocation_draft": draft, **get_admission_status(root, run_id, variant_id)}


def apply_to_paper(root: Path, run_id: str, variant_id: str, user_confirmation: bool) -> dict:
    candidate_id = candidate_id_for(run_id, variant_id)
    admission = _load_admission(root, candidate_id)
    if not admission:
        raise ValueError("candidate admission artifact required before paper apply")
    if user_confirmation is not True:
        raise ValueError("explicit user_confirmation=true required for paper apply")
    draft = _read_json(_candidate_dir(root, candidate_id) / "allocation_draft.json", {})
    if not draft:
        raise ValueError("allocation draft required before paper apply")
    confirmed_at = _now()
    confirmation = {
        "schema_version": "strategy_factory_paper_apply_confirmation_v1",
        "candidate_id": candidate_id,
        "run_id": run_id,
        "variant_id": variant_id,
        "confirmed_at": confirmed_at,
        "user_confirmation": True,
        "confirmation_text": "Apply to paper portfolio only. No live trading.",
        "paper_only": True,
        "live_trading": False,
        "brokerage_execution": False,
        "paper_ledger_mutated": False,
    }
    sleeve = {
        "schema_version": "strategy_factory_paper_strategy_sleeve_v1",
        "strategy_id": f"SF_STRATEGY_{candidate_id}",
        "sleeve_id": f"PAPER_SLEEVE_{candidate_id}",
        "paper_sleeve_id": f"PAPER_SLEEVE_{candidate_id}",
        "candidate_id": candidate_id,
        "source_run_id": run_id,
        "run_id": run_id,
        "variant_id": variant_id,
        "target_weight": draft.get("target_weight"),
        "effective_date": confirmed_at[:10],
        "transaction_cost_estimate": draft.get("transaction_cost_estimate") or {},
        "allocation_delta": draft.get("allocation_delta") or {},
        "combined_recompute_required": True,
        "status": "PAPER_APPLIED_ARTIFACT_ONLY",
        "paper_only": True,
        "live_trading": False,
        "brokerage_execution": False,
        "synthetic_admission_test_only": bool(admission.get("synthetic_admission_test_only")),
        "created_at": confirmed_at,
    }
    recompute = {
        "schema_version": "strategy_factory_combined_recompute_request_v1",
        "candidate_id": candidate_id,
        "strategy_id": sleeve["strategy_id"],
        "sleeve_id": sleeve["sleeve_id"],
        "paper_sleeve_id": sleeve["paper_sleeve_id"],
        "requested_at": confirmed_at,
        "status": "PENDING_COMBINED_RECOMPUTE",
        "reason": "Paper strategy sleeve artifact created after explicit confirmation.",
        "paper_only": True,
        "live_trading": False,
        "brokerage_execution": False,
        "accounting_logic_changed": False,
        "combined_n_semantics_changed": False,
    }
    downstream = _write_downstream_targets(root, candidate_id, sleeve, draft, recompute)
    admission["status"] = "PAPER_APPLIED"
    admission["updated_at"] = confirmed_at
    admission["paper_sleeve_id"] = sleeve["paper_sleeve_id"]
    admission["sleeve_id"] = sleeve["sleeve_id"]
    admission["strategy_id"] = sleeve["strategy_id"]
    admission["target_weight"] = sleeve["target_weight"]
    admission["estimated_transaction_cost"] = (sleeve.get("transaction_cost_estimate") or {}).get("estimated_cost_usd")
    admission["combined_recompute_request_path"] = str(_candidate_dir(root, candidate_id) / "combined_recompute_request.json")
    admission["combined_recompute_required"] = True
    admission["downstream_refresh_status"] = downstream
    admission["paper_ledger_mutated"] = False
    _write_json(_candidate_dir(root, candidate_id) / "paper_apply_confirmation.json", confirmation)
    _write_json(_candidate_dir(root, candidate_id) / "paper_strategy_sleeve.json", sleeve)
    _write_json(_candidate_dir(root, candidate_id) / "combined_recompute_request.json", recompute)
    _write_json(_candidate_dir(root, candidate_id) / "candidate_admission.json", admission)
    _write_log(root, candidate_id, {"event": "paper_applied", "paper_sleeve_id": sleeve["paper_sleeve_id"]})
    return {
        "ok": True,
        "message": "Paper sleeve artifact created. Combined recompute request artifact written. Live trading remains disabled.",
        "paper_apply_confirmation": confirmation,
        "paper_strategy_sleeve": sleeve,
        "combined_recompute_request": recompute,
        "downstream_refresh_status": downstream,
        **get_admission_status(root, run_id, variant_id),
    }
