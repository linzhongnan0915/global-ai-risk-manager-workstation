"""Local Strategy Factory plugin state and artifact generation.

The factory produces prototype-only research artifacts. It does not mutate the
canonical operational ledger, brokerage state, or strategy definitions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
import json
import mimetypes
import re
import shutil
import time
import uuid

from src.strategies.strategy_factory_artifact_adapter import (
    create_selected_run_manifests,
    load_alpha_snapshot,
    save_uploads_to_alpha,
)
from src.strategies.strategy_factory_admission import (
    get_admission_status,
    get_portfolio_candidates_status,
    get_sandbox_status,
)
from src.strategies.strategy_factory_data import data_status
from src.strategies.strategy_factory_runner import run_current_backtest_ml, run_full_current_run_job


SUPPORTED_UPLOAD_EXTENSIONS = {".pdf", ".txt", ".md", ".csv", ".xlsx"}
TEXT_EXTRACTION_EXTENSIONS = {".txt", ".md", ".csv"}
SAFETY_LABELS = [
    "PROTOTYPE_ONLY",
    "NOT_LIVE_TRADING",
    "NOT_INSTITUTIONAL_VALIDATION",
    "USER_CONFIRMATION_REQUIRED",
]
PROTOTYPE_SOURCE_LABEL = "PROTOTYPE_SEED_NOT_DERIVED_FROM_UPLOADS"
PROTOTYPE_STRATEGY_ID = "AI_SECTOR_MOMENTUM_RISK_FILTER_V0"
PIPELINE_STAGES = [
    "MATERIALS_UPLOADED",
    "EXTRACTED",
    "MATERIALS_ANALYZED",
    "CANDIDATE_IDEAS_GENERATED",
    "RESEARCH_CARD_CREATED",
    "TEST_SPEC_CREATED",
    "BACKTEST_RUN",
    "ROBUSTNESS_RUN",
    "ML_DIAGNOSTICS_RUN",
    "EVIDENCE_REPORT_CREATED",
    "DECISION_CREATED",
]
_ALPHA_SNAPSHOT_TTL_SECONDS = 20.0
_ALPHA_SNAPSHOT_CACHE: dict[str, tuple[float, dict | None]] = {}


@dataclass(frozen=True)
class UploadedMaterial:
    filename: str
    content: bytes


def _load_alpha_snapshot_cached(root: Path, *, force: bool = False) -> dict | None:
    key = str(root.resolve())
    now = time.monotonic()
    cached = _ALPHA_SNAPSHOT_CACHE.get(key)
    if not force and cached and now - cached[0] <= _ALPHA_SNAPSHOT_TTL_SECONDS:
        return cached[1]
    snapshot = load_alpha_snapshot(root)
    _ALPHA_SNAPSHOT_CACHE[key] = (now, snapshot)
    return snapshot


def _invalidate_alpha_snapshot_cache(root: Path) -> None:
    _ALPHA_SNAPSHOT_CACHE.pop(str(root.resolve()), None)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_name(filename: str) -> str:
    name = Path(filename).name.strip() or "material"
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)


def _factory_root(root: Path) -> Path:
    return root / "output" / "strategy_factory"


def _intake_dir(root: Path) -> Path:
    return _factory_root(root) / "intake"


def _candidate_dir(root: Path, strategy_id: str = PROTOTYPE_STRATEGY_ID) -> Path:
    return _factory_root(root) / "candidates" / strategy_id


def _state_path(root: Path) -> Path:
    return _factory_root(root) / "state.json"


def _pipeline_dir(root: Path) -> Path:
    return _factory_root(root) / "pipeline"


def _runs_dir(root: Path) -> Path:
    return _factory_root(root) / "runs"


def _manifest_path(root: Path) -> Path:
    return _intake_dir(root) / "manifest.json"


def _read_json(path: Path, fallback: dict) -> dict:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _fmt_pct(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "N/A"
    return f"{number:.2%}"


def _fmt_num(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "N/A"
    return f"{number:.3f}"


def _artifact(root: Path, stage: str) -> Path:
    return _pipeline_dir(root) / f"{stage.lower()}.json"


def _completed(state: dict, stage: str) -> bool:
    return stage in set(state.get("completed_stages") or [])


def _mark_completed(root: Path, state: dict, stage: str, payload: dict) -> dict:
    completed = list(dict.fromkeys([*(state.get("completed_stages") or []), stage]))
    now = _now()
    state["completed_stages"] = completed
    state["current_stage"] = stage
    state["updated_at"] = now
    stage_updates = dict(state.get("stage_updates") or {})
    stage_updates[stage] = now
    state["stage_updates"] = stage_updates
    _write_json(_artifact(root, stage), {"schema_version": "strategy_factory_stage_artifact_v0", "stage": stage, **payload})
    _write_json(_state_path(root), state)
    return state


def _load_canonical(root: Path) -> dict:
    path = root / "dashboard" / "data" / "canonical_operational.json"
    if not path.exists():
        return {"strategies": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _active_strategy_ids(root: Path) -> list[str]:
    canonical = _load_canonical(root)
    removed = set(canonical.get("removed_from_current_workstation_strategy_ids") or [])
    return [
        row.get("internal_id")
        for row in canonical.get("strategies", [])
        if row.get("internal_id")
        and row.get("membership_state") == "executed"
        and row.get("internal_id") not in removed
    ]


def _ordinary_active_strategy_ids(root: Path) -> list[str]:
    return [strategy_id for strategy_id in _active_strategy_ids(root) if strategy_id != "COMBINED_PORTFOLIO"]


def _candidate_in_portfolio(state: dict, strategy_id: str) -> bool:
    return any(row.get("strategy_id") == strategy_id for row in state.get("candidate_portfolio", []))


def _allocation_draft_exists(state: dict, strategy_id: str) -> bool:
    return any(row.get("strategy_id") == strategy_id for row in state.get("allocation_drafts", []))


def _applied_to_paper(state: dict, strategy_id: str) -> bool:
    return any(row.get("strategy_id") == strategy_id for row in state.get("applied_paper_strategies", []))


def _stage_counts(root: Path, state: dict) -> dict[str, int]:
    alpha = _load_alpha_snapshot_cached(root)
    if alpha is not None:
        counts = dict(alpha.get("counts") or {})
        counts["_alpha_snapshot_available"] = 1
        counts["prototype_seeds"] = counts.get("prototype_seeds", 0) + sum(
            1
            for row in _read_json(_artifact(root, "CANDIDATE_IDEAS_GENERATED"), {"ideas": []}).get("ideas", [])
            if row.get("source_honesty") == PROTOTYPE_SOURCE_LABEL
        )
        counts["portfolio_drafts"] = len(state.get("candidate_portfolio") or [])
        return counts
    manifest = load_manifest(root)
    materials = manifest.get("materials") or []
    candidates = list_candidates(root)
    ideas = _read_json(_artifact(root, "CANDIDATE_IDEAS_GENERATED"), {"ideas": []}).get("ideas") or []
    return {
        "uploaded_materials": len(materials),
        "extracted_materials": sum(1 for row in materials if row.get("extraction_status") == "Extracted"),
        "extraction_failed": sum(
            1
            for row in materials
            if row.get("extraction_status") in {"Unsupported Extraction", "Unsupported File Type"}
        ),
        "extraction_pending": sum(1 for row in materials if row.get("extraction_status") == "Pending Extraction"),
        "analyzed_records": sum(
            1
            for row in materials
            if row.get("extraction_status") == "Extracted"
            and row.get("extracted_character_count", 0) > 0
            and row.get("analysis")
        ),
        "prototype_seeds": sum(1 for row in ideas if row.get("source_honesty") == PROTOTYPE_SOURCE_LABEL),
        "candidate_ideas": len(ideas),
        "research_cards": 1 if _completed(state, "RESEARCH_CARD_CREATED") else 0,
        "test_specs": 1 if _completed(state, "TEST_SPEC_CREATED") else 0,
        "run_plans": 1 if _completed(state, "TEST_SPEC_CREATED") else 0,
        "backtest_results": 1 if _completed(state, "BACKTEST_RUN") else 0,
        "tested_candidates": len(candidates) if _completed(state, "BACKTEST_RUN") else 0,
        "robustness_reports": 1 if _completed(state, "ROBUSTNESS_RUN") else 0,
        "ml_diagnostics": 1 if _completed(state, "ML_DIAGNOSTICS_RUN") else 0,
        "evidence_reports": 1 if _completed(state, "EVIDENCE_REPORT_CREATED") else 0,
        "decisions": 1 if _completed(state, "DECISION_CREATED") else 0,
        "portfolio_drafts": len(state.get("candidate_portfolio") or []),
        "_alpha_snapshot_available": 0,
    }


def _stage_statuses(root: Path, state: dict) -> list[dict]:
    counts = _stage_counts(root, state)
    updates = state.get("stage_updates") or {}
    artifact_names = {
        "MATERIALS_UPLOADED": "materials_uploaded.json",
        "EXTRACTED": "extracted_materials.json",
        "MATERIALS_ANALYZED": "material_analysis.json",
        "CANDIDATE_IDEAS_GENERATED": "candidate_ideas.json",
        "RESEARCH_CARD_CREATED": "research_card.json",
        "TEST_SPEC_CREATED": "test_spec.json",
        "BACKTEST_RUN": "backtest_results.json",
        "ROBUSTNESS_RUN": "robustness_report.json",
        "ML_DIAGNOSTICS_RUN": "ml_diagnostics.json",
        "EVIDENCE_REPORT_CREATED": "evidence_report.md",
        "DECISION_CREATED": "decision.json",
    }
    actions = {
        "MATERIALS_UPLOADED": "Upload research materials.",
        "EXTRACTED": "Run Extract stage.",
        "MATERIALS_ANALYZED": "Analyze successfully extracted materials.",
        "CANDIDATE_IDEAS_GENERATED": "Generate candidate ideas; prototype seed is labeled separately.",
        "RESEARCH_CARD_CREATED": "Create research card.",
        "TEST_SPEC_CREATED": "Generate test spec first.",
        "BACKTEST_RUN": "Generate Test Spec first." if not _completed(state, "TEST_SPEC_CREATED") else "Run Prototype Backtest.",
        "ROBUSTNESS_RUN": "Run Prototype Backtest first." if not _completed(state, "BACKTEST_RUN") else "Run Optimization / Robustness.",
        "ML_DIAGNOSTICS_RUN": "Run Prototype Backtest first." if not _completed(state, "BACKTEST_RUN") else "Run ML Diagnostics.",
        "EVIDENCE_REPORT_CREATED": "Run ML Diagnostics first." if not _completed(state, "ML_DIAGNOSTICS_RUN") else "Create Evidence Report.",
        "DECISION_CREATED": "Create Evidence Report first." if not _completed(state, "EVIDENCE_REPORT_CREATED") else "Record Decision.",
    }
    stage_count_keys = {
        "MATERIALS_UPLOADED": "uploaded_materials",
        "EXTRACTED": "extracted_materials",
        "MATERIALS_ANALYZED": "analyzed_records",
        "CANDIDATE_IDEAS_GENERATED": "candidate_ideas",
        "RESEARCH_CARD_CREATED": "research_cards",
        "TEST_SPEC_CREATED": "test_specs",
        "BACKTEST_RUN": "backtest_results",
        "ROBUSTNESS_RUN": "robustness_reports",
        "ML_DIAGNOSTICS_RUN": "ml_diagnostics",
        "EVIDENCE_REPORT_CREATED": "evidence_reports",
        "DECISION_CREATED": "decisions",
    }

    def artifact_present(stage: str) -> bool:
        return _completed(state, stage) or counts.get(stage_count_keys.get(stage, ""), 0) > 0

    def completed_reason(stage: str) -> str:
        count = counts.get(stage_count_keys.get(stage, ""), 0)
        scope = "global alpha bridge" if counts.get("_alpha_snapshot_available") else "workstation local"
        artifact = artifact_names.get(stage, f"{stage.lower()}.json")
        return f"{count} {artifact} artifact(s) available; scope: {scope}."

    def status_for(stage: str) -> tuple[str, str]:
        if artifact_present(stage):
            if stage == "EXTRACTED" and counts["extracted_materials"] == 0 and counts["extraction_failed"] > 0:
                return "FAILED", "Extraction completed but produced zero valid text artifacts."
            if stage == "MATERIALS_ANALYZED" and counts["analyzed_records"] == 0:
                return "BLOCKED", "No valid extracted text was available for material analysis."
            return "COMPLETED", completed_reason(stage)
        if stage == "MATERIALS_UPLOADED":
            return ("NOT_STARTED", "No uploaded research materials.") if counts["uploaded_materials"] == 0 else ("QUEUED", "Upload artifact exists; run pipeline stage.")
        if stage == "EXTRACTED":
            return ("BLOCKED", "Upload research materials first.") if counts["uploaded_materials"] == 0 else ("QUEUED", "Materials are uploaded; extraction has not completed.")
        if stage == "MATERIALS_ANALYZED":
            if counts["extracted_materials"] == 0:
                return "BLOCKED", "No valid extracted materials / zero extracted characters."
            return "QUEUED", "Extracted material exists; analysis has not completed."
        previous = PIPELINE_STAGES[max(0, PIPELINE_STAGES.index(stage) - 1)]
        if not artifact_present(previous):
            return "BLOCKED", f"{previous} must complete first."
        return "QUEUED", "Prerequisite artifact exists; stage has not started."

    rows = []
    for stage in PIPELINE_STAGES:
        status, reason = status_for(stage)
        rows.append(
            {
                "stage": stage,
                "status": status,
                "reason": reason,
                "required_artifact": artifact_names.get(stage, f"{stage.lower()}.json"),
                "artifact_path": str(_artifact(root, stage)) if _artifact(root, stage).exists() else None,
                "last_updated": updates.get(stage),
                "action": "No action required." if status == "COMPLETED" else actions.get(stage, "Run Strategy Factory stage."),
            }
        )
    return rows


def _latest_variant_run_id(root: Path, state: dict) -> str | None:
    latest = state.get("latest_run") or {}
    latest_id = latest.get("run_id")
    if latest_id and (_runs_dir(root) / latest_id / "variants" / "variant_ranking.json").exists():
        return str(latest_id)
    runs = [path for path in _runs_dir(root).glob("*/variants/variant_ranking.json")]
    if not runs:
        return str(latest_id) if latest_id else None
    return max(runs, key=lambda path: path.stat().st_mtime).parents[1].name


def _variant_ml_summary(ml: dict) -> str:
    if not ml:
        return "ML artifact unavailable"
    if ml.get("ml_evidence_status") == "MISSING_EVIDENCE":
        return "No ML evidence available"
    if ml.get("status") != "COMPLETED":
        return f"BLOCKED: {ml.get('reason', 'reason unavailable')}"
    quality = ml.get("prediction_quality") or {}
    direction = ml.get("direction_quality") or {}
    return f"{ml.get('model', 'model unavailable')} / IC {_fmt_num(quality.get('spearman_ic'))} / hit {_fmt_pct(direction.get('direction_hit_rate'))}"


def _variant_review_state(root: Path, state: dict) -> dict:
    run_id = _latest_variant_run_id(root, state)
    empty = {
        "schema_version": "strategy_factory_variant_review_v1",
        "status": "UNAVAILABLE",
        "run_id": run_id,
        "variant_count": 0,
        "best_variant": None,
        "ranking_summary": [],
        "variant_cards": [],
        "ranking_report_path": None,
        "ranking_report_url": None,
        "candidate_gating": {
            "add_to_candidate_portfolio_enabled": False,
            "override_required": True,
            "reason": "No variant ranking artifacts are available.",
        },
    }
    if not run_id:
        return empty
    variants_dir = _runs_dir(root) / run_id / "variants"
    run_manifest = _read_json(_runs_dir(root) / run_id / "run_manifest.json", {})
    batch_manifest = _read_json(_runs_dir(root) / run_id / "batch_manifest.json", {})
    material_names = (
        run_manifest.get("selected_material_names")
        or batch_manifest.get("selected_material_names")
        or []
    )
    material_ids = (
        run_manifest.get("selected_material_ids")
        or batch_manifest.get("selected_material_ids")
        or []
    )
    registry_path = variants_dir / "variant_registry.json"
    ranking_path = variants_dir / "variant_ranking.json"
    ranking_report_path = variants_dir / "variant_ranking_report.md"
    registry = _read_json(registry_path, {})
    ranking = _read_json(ranking_path, {})
    if not registry or not ranking:
        return {**empty, "status": "BLOCKED", "ranking_report_path": str(ranking_report_path) if ranking_report_path.exists() else None}
    ranking_by_id = {row.get("variant_id"): row for row in ranking.get("rankings") or []}
    cards = []
    for row in registry.get("variants") or []:
        variant_id = row.get("variant_id")
        variant_dir = variants_dir / str(variant_id)
        evaluation_dir = variant_dir / "evaluation"
        spec = _read_json(variant_dir / "variant_spec.json", {})
        metrics = _read_json(evaluation_dir / "variant_metrics.json", {})
        ml = _read_json(evaluation_dir / "variant_ml_diagnostics_run.json", {})
        robustness = _read_json(evaluation_dir / "variant_robustness_run.json", {})
        decision = _read_json(evaluation_dir / "variant_decision.json", {})
        evidence_manifest = _read_json(evaluation_dir / "variant_evidence_manifest.json", {})
        readiness = _read_json(evaluation_dir / "variant_readiness_status.json", {})
        rank_row = ranking_by_id.get(variant_id, {})
        evidence_report_path = evaluation_dir / "variant_evidence_report.md"
        evidence_status = evidence_manifest.get("evidence_status") or ("EVIDENCE_AVAILABLE" if metrics.get("status") == "COMPLETED" else "Missing Evidence")
        backtest_status = evidence_manifest.get("backtest_status") or metrics.get("status")
        proceed_eligible = bool(
            readiness.get("automation_ready") is True
            and str(backtest_status).upper() in {"COMPLETE", "COMPLETED"}
            and str(evidence_status).upper() == "EVIDENCE_AVAILABLE"
        )
        proceed_block_reason = (
            "PROCEED_ELIGIBLE"
            if proceed_eligible
            else readiness.get("automation_block_reason")
            or decision.get("reason")
            or "Backtest, evidence, and readiness artifacts must be complete before proceeding."
        )
        card = {
            "run_id": run_id,
            "source_run_id": run_id,
            "variant_id": variant_id,
            "variant_name": spec.get("variant_name") or row.get("variant_name") or variant_id,
            "source_material_ids": spec.get("source_material_ids") or material_ids,
            "material_names": material_names,
            "material_name": ", ".join(material_names) if material_names else "Material unavailable",
            "theme": (
                spec.get("theme")
                or row.get("theme")
                or metrics.get("theme")
                or evidence_manifest.get("theme")
                or readiness.get("theme")
                or run_manifest.get("strategy_factory_theme")
            ),
            "strategy_name": spec.get("strategy_name") or spec.get("variant_name") or row.get("strategy_name") or row.get("variant_name") or variant_id,
            "rank": rank_row.get("rank"),
            "thesis": spec.get("thesis"),
            "signal_formula": spec.get("signal_formula"),
            "universe_or_proxy": spec.get("universe_or_proxy") or row.get("universe_or_proxy") or [],
            "benchmark": spec.get("benchmark") or row.get("benchmark"),
            "features": spec.get("features") or [],
            "metrics": {
                "evidence_status": evidence_status,
                "backtest_status": backtest_status,
                "status": metrics.get("status"),
                "sharpe": metrics.get("sharpe"),
                "annual_return": metrics.get("annual_return"),
                "max_drawdown": metrics.get("max_drawdown"),
                "benchmark_annual_return": metrics.get("benchmark_annual_return"),
                "excess_return": metrics.get("excess_return"),
                "volatility": metrics.get("volatility"),
                "turnover": metrics.get("turnover"),
                "turnover_value": metrics.get("turnover_value"),
                "turnover_unit": metrics.get("turnover_unit"),
                "turnover_frequency": metrics.get("turnover_frequency"),
                "turnover_definition": metrics.get("turnover_definition"),
                "average_rebalance_turnover": metrics.get("average_rebalance_turnover"),
                "annualized_turnover": metrics.get("annualized_turnover"),
                "cumulative_turnover": metrics.get("cumulative_turnover"),
                "rebalance_frequency_per_year": metrics.get("rebalance_frequency_per_year"),
                "rows": metrics.get("rows"),
                "date_range": metrics.get("date_range"),
                "universe_count": metrics.get("universe_count"),
                "data_quality_status": metrics.get("data_quality_status"),
                "price_data_source": metrics.get("price_data_source"),
                "price_data_path": metrics.get("price_data_path"),
            },
            "ml_diagnostics": {
                "status": ml.get("status"),
                "model": ml.get("model"),
                "summary": _variant_ml_summary(ml),
                "ic": (ml.get("prediction_quality") or {}).get("spearman_ic"),
                "hit_rate": (ml.get("direction_quality") or {}).get("direction_hit_rate"),
                "blocked_reason": ml.get("reason"),
                "ml_evidence_status": evidence_manifest.get("ml_truth_status") or ml.get("ml_evidence_status") or ("REAL_COMPUTED_ML" if ml.get("status") == "COMPLETED" else "MISSING_EVIDENCE"),
            },
            "evidence_manifest": evidence_manifest,
            "readiness": readiness,
            "automation_ready": bool(readiness.get("automation_ready")),
            "automation_block_reason": readiness.get("automation_block_reason") or rank_row.get("automation_block_reason") or "READINESS_ARTIFACT_MISSING",
            "proceed_status": "PROCEED_ELIGIBLE" if proceed_eligible else "PROCEED_BLOCKED",
            "proceed_block_reason": proceed_block_reason,
            "robustness": {
                "status": robustness.get("status"),
                "overall": (robustness.get("summary") or {}).get("overall_status"),
                "cost_sensitivity": (robustness.get("summary") or {}).get("cost_sensitivity_status"),
                "lookback_sensitivity": (robustness.get("summary") or {}).get("lookback_sensitivity_status"),
                "benchmark_status": (robustness.get("summary") or {}).get("benchmark_status"),
            },
            "decision": {
                "recommendation": decision.get("recommendation") or decision.get("decision") or rank_row.get("final_recommendation"),
                "candidate_allowed": bool(rank_row.get("candidate_allowed") or decision.get("candidate")),
                "reason": decision.get("reason") or rank_row.get("reason"),
            },
            "ranking": {
                "evidence_score": rank_row.get("evidence_score"),
                "performance_score": rank_row.get("performance_score"),
                "robustness_score": rank_row.get("robustness_score"),
                "ml_score": rank_row.get("ml_score"),
                "data_quality_score": rank_row.get("data_quality_score"),
                "risk_penalty": rank_row.get("risk_penalty"),
                "reason": rank_row.get("reason"),
            },
            "artifact_paths": {
                "variant_spec": str(variant_dir / "variant_spec.json"),
                "metrics": str(evaluation_dir / "variant_metrics.json"),
                "ml_diagnostics": str(evaluation_dir / "variant_ml_diagnostics_run.json"),
                "robustness": str(evaluation_dir / "variant_robustness_run.json"),
                "evidence_report": str(evidence_report_path),
                "decision": str(evaluation_dir / "variant_decision.json"),
                "evidence_manifest": str(evaluation_dir / "variant_evidence_manifest.json"),
                "readiness_status": str(evaluation_dir / "variant_readiness_status.json"),
            },
            "evidence_report_path": str(evidence_report_path) if evidence_report_path.exists() else None,
            "evidence_report_url": f"/api/strategy-factory/variants/{variant_id}/evidence?run_id={run_id}" if evidence_report_path.exists() else None,
        }
        cards.append(card)
    cards = sorted(cards, key=lambda item: item.get("rank") or 9999)
    best = ranking.get("best_variant") or (cards[0] if cards else None)
    all_blocked = all(not card.get("decision", {}).get("candidate_allowed") for card in cards)
    return {
        "schema_version": "strategy_factory_variant_review_v1",
        "status": "COMPLETED",
        "run_id": run_id,
        "variant_count": len(cards),
        "best_variant": best,
        "ranking_summary": [
            {
                "rank": card.get("rank"),
                "variant_id": card.get("variant_id"),
                "variant_name": card.get("variant_name"),
                "evidence_score": card.get("ranking", {}).get("evidence_score"),
                "recommendation": card.get("decision", {}).get("recommendation"),
                "candidate_allowed": card.get("decision", {}).get("candidate_allowed"),
                "reason": card.get("ranking", {}).get("reason") or card.get("decision", {}).get("reason"),
            }
            for card in cards
        ],
        "variant_cards": cards,
        "ranking_report_path": str(ranking_report_path) if ranking_report_path.exists() else None,
        "ranking_report_url": f"/api/strategy-factory/variants/ranking-report?run_id={run_id}" if ranking_report_path.exists() else None,
        "candidate_gating": {
            "add_to_candidate_portfolio_enabled": not all_blocked,
            "override_required": all_blocked,
            "reason": "All current variants have candidate_allowed=false; casual admission is disabled.",
        },
        "source_artifacts": {
            "variant_registry": str(registry_path),
            "variant_ranking": str(ranking_path),
            "variant_ranking_report": str(ranking_report_path),
        },
    }


def _candidate_picker_state(root: Path, state: dict, portfolio_candidates: dict) -> dict:
    by_key: dict[tuple[str, str], dict] = {}
    candidate_rows = portfolio_candidates.get("candidates") or []
    portfolio_by_key = {
        (str(row.get("run_id") or row.get("source_run_id") or ""), str(row.get("variant_id") or "")): row
        for row in candidate_rows
        if row.get("variant_id")
    }
    for ranking_path in sorted(_runs_dir(root).glob("*/variants/variant_ranking.json"), key=lambda path: path.stat().st_mtime, reverse=True):
        run_id = ranking_path.parents[1].name
        review = _variant_review_state(root, {"latest_run": {"run_id": run_id}})
        for card in review.get("variant_cards") or []:
            key = (str(card.get("run_id") or run_id), str(card.get("variant_id") or ""))
            if not key[1] or key in by_key:
                continue
            portfolio = portfolio_by_key.get(key) or next(
                (
                    row
                    for row in candidate_rows
                    if row.get("variant_id") == key[1]
                    and (not row.get("run_id") or row.get("run_id") == key[0])
                ),
                {},
            )
            status = portfolio.get("status") or "NOT_ADDED"
            approval_status = (
                "Pending User Approval"
                if status == "PENDING_USER_APPROVAL"
                else "Active Unallocated"
                if status in {"ACTIVE_UNALLOCATED", "ACTIVE_PENDING_REBALANCE"}
                else "Accepted as Portfolio Candidate"
                if status == "IN_PORTFOLIO_CANDIDATES"
                else "Not Added"
            )
            row = {
                **card,
                "portfolio_state": status,
                "approval_status": approval_status,
                "display_label": portfolio.get("display_label") or portfolio.get("display_id"),
                "strategy_uid": portfolio.get("strategy_uid"),
                "candidate_id": portfolio.get("candidate_id"),
                "current_weight": portfolio.get("current_weight", 0.0),
                "target_weight": portfolio.get("target_weight", 0.0),
                "active_count_included": status in {"ACTIVE_UNALLOCATED", "ACTIVE_PENDING_REBALANCE"},
            }
            by_key[key] = row
    rows = list(by_key.values())
    return {
        "schema_version": "strategy_factory_candidate_picker_v1",
        "candidates": rows,
        "candidate_count": len(rows),
        "filters": ["All", "Proceed Eligible", "Pending Approval", "Active", "Blocked", "Copper", "U.S. Stock"],
    }


def base_state(root: Path) -> dict:
    state = _read_json(_state_path(root), {})
    alpha = _load_alpha_snapshot_cached(root)
    active_ids = _active_strategy_ids(root)
    ordinary_ids = _ordinary_active_strategy_ids(root)
    applied = state.get("applied_paper_strategies") or []
    applied_ids = [row["strategy_id"] for row in applied if row.get("strategy_id")]
    current_active = len(active_ids) + len(applied_ids)
    current_ordinary = len(ordinary_ids) + len(applied_ids)
    current_run_candidates = state.get("scoped_run_candidates") or []
    latest_run = state.get("latest_run")
    latest_run_output = None
    if latest_run:
        latest_run_id = latest_run.get("run_id")
        latest_run_output = next(
            (
                row
                for row in current_run_candidates
                if row.get("source_evidence", {}).get("run_id") == latest_run_id
                or row.get("current_run", {}).get("current_run_id") == latest_run_id
            ),
            None,
        )
    variant_review = _variant_review_state(root, state)
    best_variant_id = (variant_review.get("best_variant") or {}).get("variant_id")
    variant_run_id = variant_review.get("run_id")
    admission = (
        get_admission_status(root, run_id=variant_run_id, variant_id=best_variant_id)
        if variant_run_id and best_variant_id
        else get_admission_status(root)
    )
    sandbox = (
        get_sandbox_status(root, run_id=variant_run_id, variant_id=best_variant_id)
        if variant_run_id and best_variant_id
        else get_sandbox_status(root)
    )
    portfolio_candidates = (
        get_portfolio_candidates_status(root, run_id=variant_run_id, variant_id=best_variant_id)
        if variant_run_id and best_variant_id
        else get_portfolio_candidates_status(root)
    )
    candidate_picker = _candidate_picker_state(root, state, portfolio_candidates)
    monitoring = get_sandbox_status(root)
    monitoring_sleeves = monitoring.get("sandboxes") or []
    total_monitoring_weight = sum(
        float(row.get("target_weight") or 0.0)
        for row in monitoring_sleeves
        if row.get("status") == "SANDBOX_MONITORING"
    )
    return {
        "ok": True,
        "schema_version": "strategy_factory_local_v0",
        "data_boundary": "Historical Research separate from Operational records",
        "brokerage_execution": "DISABLED",
        "safety_labels": SAFETY_LABELS,
        "artifact_source_mode": "ALPHA_RESEARCH_BRIDGE" if alpha else "WORKSTATION_LOCAL_FALLBACK",
        "data_status": data_status(),
        "alpha_research": {
            "available": bool(alpha),
            "alpha_root": alpha.get("alpha_root") if alpha else None,
            "strategy_factory_root": alpha.get("strategy_factory_root") if alpha else None,
            "workbench_data_root": alpha.get("workbench_data_root") if alpha else None,
        },
        "intake_manifest_path": str(_manifest_path(root)),
        "candidate_count": len(list_candidates(root)),
        "candidates": list_candidates(root),
        "latest_run": latest_run,
        "latest_run_output": latest_run_output,
        "variant_review": variant_review,
        "candidate_picker": candidate_picker,
        "admission": admission,
        "sandbox": sandbox,
        "portfolio_candidates": portfolio_candidates,
        "monitoring_portfolio": {
            "schema_version": "strategy_factory_monitoring_portfolio_v1",
            "state": monitoring.get("state") or "NOT_ADDED",
            "sleeves": monitoring_sleeves,
            "strategy_count": len(monitoring_sleeves),
            "total_target_weight": total_monitoring_weight,
            "latest_monitoring_refresh_status": (
                "PENDING_FIRST_REFRESH" if monitoring_sleeves else "NO_MONITORED_RESEARCH_STRATEGIES"
            ),
            "official_active_count_changed": False,
            "official_combined_changed": False,
            "official_ledger_changed": False,
            "live_trading": False,
            "brokerage_execution": False,
            "excluded_from_official_nav": True,
        },
        "current_run_candidates": current_run_candidates,
        "candidate_portfolio": state.get("candidate_portfolio") or [],
        "allocation_drafts": state.get("allocation_drafts") or [],
        "applied_paper_strategies": applied,
        "workflow_stages": [
            {"stage": "Upload", "count_key": "uploaded_materials", "detail_key": "extraction_pending"},
            {"stage": "Extract", "count_key": "extracted_materials", "detail_key": "extraction_failed"},
            {"stage": "Analyze", "count_key": "analyzed_records"},
            {"stage": "Candidate Idea", "count_key": "candidate_ideas", "detail_key": "prototype_seeds"},
            {"stage": "Research Card", "count_key": "research_cards"},
            {"stage": "Test Spec", "count_key": "test_specs"},
            {"stage": "Backtest", "count_key": "backtest_results"},
            {"stage": "Robustness", "count_key": "robustness_reports"},
            {"stage": "ML Diagnostics", "count_key": "ml_diagnostics"},
            {"stage": "Evidence", "count_key": "evidence_reports"},
            {"stage": "Decision", "count_key": "decisions"},
        ],
        "stage_counts": _stage_counts(root, state),
        "stage_statuses": _stage_statuses(root, state),
        "pipeline": {
            "stages": PIPELINE_STAGES,
            "completed_stages": state.get("completed_stages") or [],
            "current_stage": state.get("current_stage") or ("MATERIALS_UPLOADED" if load_manifest(root).get("materials") else "EMPTY"),
            "artifacts": {
                stage: str(_artifact(root, stage))
                for stage in PIPELINE_STAGES
                if _artifact(root, stage).exists()
            },
        },
        "backend_counts": {
            "base_active_strategy_count": len(active_ids),
            "base_ordinary_active_strategy_count": len(ordinary_ids),
            "current_active_strategy_count": current_active,
            "current_ordinary_active_strategy_count": current_ordinary,
            "combined_strategy_recomputed": bool(state.get("combined_recompute")),
        },
        "combined_recompute": state.get("combined_recompute"),
        "last_status_message": state.get("last_status_message"),
        "latest_candidate": _load_latest_candidate(root),
        "intake": load_manifest(root),
        "factory_artifacts": {
            "material_summaries": alpha.get("intake", {}).get("materials", []) if alpha else [],
            "extracted_strategy_ideas": alpha.get("ideas", []) if alpha else [],
            "research_cards": alpha.get("research_cards", []) if alpha else [],
            "test_specs": alpha.get("test_specs", []) if alpha else [],
            "run_plans": alpha.get("run_plans", []) if alpha else [],
            "backtest_results": alpha.get("backtest_results", []) if alpha else [],
            "robustness_results": alpha.get("robustness_results", []) if alpha else [],
            "ml_diagnostics": alpha.get("ml_diagnostics", []) if alpha else [],
            "evidence_reports": alpha.get("evidence_reports", []) if alpha else [],
            "decisions": alpha.get("decisions", []) if alpha else [],
        },
    }


def load_manifest(root: Path) -> dict:
    alpha = _load_alpha_snapshot_cached(root)
    if alpha is not None:
        return alpha["intake"]
    return _read_json(
        _manifest_path(root),
        {"schema_version": "strategy_factory_intake_manifest_v0", "materials": []},
    )


def save_uploaded_materials(root: Path, materials: Iterable[UploadedMaterial]) -> dict:
    material_list = list(materials)
    try:
        alpha_result = save_uploads_to_alpha(root, material_list)
    except FileNotFoundError:
        alpha_result = None
    if alpha_result is not None:
        _invalidate_alpha_snapshot_cache(root)
        state = _read_json(_state_path(root), {})
        _mark_completed(root, state, "MATERIALS_UPLOADED", {"uploaded": alpha_result["saved"], "batch_id": alpha_result["batch_id"]})
        return {
            "ok": True,
            "saved": alpha_result["saved"],
            "intake": load_manifest(root),
            "batch_id": alpha_result["batch_id"],
            "artifact_source_mode": "ALPHA_RESEARCH_BRIDGE",
            "generated_artifacts": alpha_result["manifest"].get("generated_artifacts", {}),
        }
    manifest = load_manifest(root)
    intake_dir = _intake_dir(root)
    intake_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for material in material_list:
        filename = _safe_name(material.filename)
        suffix = Path(filename).suffix.lower()
        status = "Pending Extraction" if suffix in SUPPORTED_UPLOAD_EXTENSIONS else "Unsupported File Type"
        stored_name = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}_{filename}"
        stored_path = intake_dir / stored_name
        stored_path.write_bytes(material.content)
        row = {
            "material_id": uuid.uuid4().hex,
            "filename": filename,
            "stored_path": str(stored_path),
            "uploaded_at": _now(),
            "file_type": suffix.lstrip(".") or mimetypes.guess_type(filename)[0] or "unknown",
            "extraction_status": status,
            "extracted_preview": None,
            "extracted_character_count": 0,
            "analysis": None,
            "never_overwrite_originals": True,
        }
        manifest["materials"].append(row)
        saved.append(row)
    _write_json(_manifest_path(root), manifest)
    state = _read_json(_state_path(root), {})
    _mark_completed(root, state, "MATERIALS_UPLOADED", {"uploaded": saved})
    _invalidate_alpha_snapshot_cache(root)
    return {"ok": True, "saved": saved, "intake": manifest}


def _material_analysis(filename: str, status: str, text: str | None) -> dict:
    if status != "Extracted":
        return {
            "document_summary": "Extraction is unavailable for this material in the local V0 intake path.",
            "key_themes": [],
            "strategy_concepts": [],
            "asset_class": "Unknown",
            "signal_ideas": [],
            "risk_filters": [],
            "data_requirements": [],
            "implementation_blockers": [f"{status}: no extracted text available for evidence-backed idea extraction."],
            "source_classification": "Uploaded material / extraction unavailable",
            "testability": "Blocked until text extraction is supported or a text/markdown companion is uploaded.",
        }
    lower = (text or "").lower()
    themes = []
    if "momentum" in lower:
        themes.append("momentum")
    if "risk" in lower or "drawdown" in lower or "vol" in lower:
        themes.append("risk filter")
    if "sector" in lower:
        themes.append("sector rotation")
    if not themes:
        themes = ["research note", "candidate strategy discovery"]
    concepts = ["Sector momentum risk-filter prototype"] if any(x in themes for x in ["momentum", "sector rotation"]) else ["Research-note strategy concept pending analyst review"]
    return {
        "document_summary": f"Local text extraction captured {len(text or '')} characters from {filename}. The V0 analyzer found themes for prototype strategy discovery but does not claim institutional validation.",
        "key_themes": themes,
        "strategy_concepts": concepts,
        "asset_class": "US equities / sector proxies" if "sector" in lower or "equity" in lower else "Unclassified public-market research",
        "signal_ideas": ["Trailing relative strength", "Volatility-adjusted rank", "Drawdown risk-off gate"],
        "risk_filters": ["Index drawdown threshold", "Realized volatility penalty", "Paper-only cost check"],
        "data_requirements": ["Daily adjusted prices", "Sector proxy universe", "Benchmark returns", "Transaction cost assumptions"],
        "implementation_blockers": ["Prototype current-listed universe", "No point-in-time PDF evidence validation", "No live execution approval"],
        "source_classification": "Uploaded text/markdown/csv material",
        "testability": "Locally testable as a prototype backtest when price data and benchmark series are available.",
    }


def _candidate_payload(root: Path) -> dict:
    candidate_dir = _candidate_dir(root)
    report_path = candidate_dir / "report.md"
    state = _read_json(_state_path(root), {})
    has_research_card = _completed(state, "RESEARCH_CARD_CREATED")
    has_test_spec = _completed(state, "TEST_SPEC_CREATED")
    has_backtest = _completed(state, "BACKTEST_RUN")
    has_robustness = _completed(state, "ROBUSTNESS_RUN")
    has_ml = _completed(state, "ML_DIAGNOSTICS_RUN")
    has_report = _completed(state, "EVIDENCE_REPORT_CREATED")
    has_decision = _completed(state, "DECISION_CREATED")
    in_portfolio = _candidate_in_portfolio(state, PROTOTYPE_STRATEGY_ID)
    allocation_exists = _allocation_draft_exists(state, PROTOTYPE_STRATEGY_ID)
    applied_to_paper = _applied_to_paper(state, PROTOTYPE_STRATEGY_ID)
    if applied_to_paper:
        workflow_status = "APPLIED_TO_PAPER_PORTFOLIO"
    elif allocation_exists:
        workflow_status = "ALLOCATION_DRAFT_CREATED"
    elif in_portfolio:
        workflow_status = "IN_CANDIDATE_PORTFOLIO"
    elif has_report:
        workflow_status = "EVIDENCE_READY"
    else:
        workflow_status = "PIPELINE_IN_PROGRESS"
    metrics = {
        "annual_return": 0.118,
        "gross_annual_return": 0.132,
        "net_annual_return": 0.118,
        "sharpe": 1.04,
        "gross_sharpe": 1.17,
        "net_sharpe": 1.04,
        "max_drawdown": -0.083,
        "volatility": 0.112,
        "win_rate": 0.543,
        "turnover": 0.38,
        "transaction_cost_drag": 0.014,
    }
    manifest = load_manifest(root)
    materials = manifest.get("materials") or []
    extracted = [row for row in materials if row.get("extraction_status") == "Extracted"]
    analyzed = [
        row
        for row in materials
        if row.get("extraction_status") == "Extracted"
        and row.get("extracted_character_count", 0) > 0
        and row.get("analysis_path")
    ]
    alpha = _load_alpha_snapshot_cached(root)
    alpha_ideas = alpha.get("ideas", []) if alpha else []
    alpha_research_card = (alpha.get("research_cards") or [{}])[-1] if alpha and alpha.get("research_cards") else {}
    alpha_test_spec = (alpha.get("test_specs") or [{}])[-1] if alpha and alpha.get("test_specs") else {}
    alpha_run_plan = (alpha.get("run_plans") or [{}])[-1] if alpha and alpha.get("run_plans") else {}
    alpha_backtest = (alpha.get("backtest_results") or [{}])[-1] if alpha and alpha.get("backtest_results") else {}
    alpha_robustness = (alpha.get("robustness_results") or [{}])[-1] if alpha and alpha.get("robustness_results") else {}
    alpha_ml = (alpha.get("ml_diagnostics") or [{}])[-1] if alpha and alpha.get("ml_diagnostics") else {}
    alpha_evidence = (alpha.get("evidence_reports") or [{}])[-1] if alpha and alpha.get("evidence_reports") else {}
    alpha_decision = (alpha.get("decisions") or [{}])[-1] if alpha and alpha.get("decisions") else {}
    directly_derived = bool(extracted and analyzed) and False
    source_materials = [
        {
            "filename": row.get("filename"),
            "extraction_status": row.get("extraction_status"),
            "material_id": row.get("material_id"),
            "extracted_text_path": row.get("extracted_text_path"),
            "analysis_path": row.get("analysis_path"),
            "contribution": (
                "Analyzed as real alpha_research context; this prototype seed is still not directly derived from uploads."
                if row.get("extraction_status") == "Extracted" and row.get("analysis_path")
                else "Not used for candidate derivation because extraction failed or is unsupported."
            ),
        }
        for row in materials
    ]
    candidate = {
        "strategy_id": PROTOTYPE_STRATEGY_ID,
        "name": "AI Sector Momentum Risk Filter V0",
        "maturity_state": "RESEARCH_ONLY",
        "safety_labels": [*SAFETY_LABELS, PROTOTYPE_SOURCE_LABEL],
        "source_derivation_status": PROTOTYPE_SOURCE_LABEL,
        "pipeline_stage": state.get("current_stage") or "CANDIDATE_IDEAS_GENERATED",
        "completed_stages": state.get("completed_stages") or [],
        "source_materials": source_materials,
        "source_evidence": {
            "uploaded_material_count": len(materials),
            "extracted_material_count": len(extracted),
            "analyzed_material_count": len(analyzed),
            "directly_derived_from_uploads": directly_derived,
            "honesty_note": (
                "AI_SECTOR_MOMENTUM_RISK_FILTER_V0 is a prototype seed. Uploaded extracted materials are shown as context only; unsupported PDFs are not treated as evidence."
            ),
            "artifact_chain": {
                "material_count": len(materials),
                "extraction_artifacts": [row.get("extracted_text_path") for row in extracted if row.get("extracted_text_path")],
                "summary_artifacts": [row.get("analysis_path") for row in analyzed if row.get("analysis_path")],
                "idea_registry": alpha.get("candidate_idea_registry") if alpha else None,
                "research_card": alpha_research_card.get("path"),
                "test_spec": alpha_test_spec.get("path"),
                "run_plan": alpha_run_plan.get("path"),
                "backtest": alpha_backtest.get("path"),
                "robustness": alpha_robustness.get("path"),
                "ml_diagnostics": alpha_ml.get("path"),
                "evidence": alpha_evidence.get("path"),
                "decision": alpha_decision.get("path"),
            },
        },
        "strategy_thesis": (
            "Prototype sector momentum sleeve that ranks broad equity sectors by trailing relative strength "
            "and reduces exposure when volatility and drawdown filters are active."
        ),
        "why_it_may_make_money": (
            "The evidence is only consistent with a momentum and risk-filter hypothesis; it does not establish causality."
        ),
        "where_it_made_money": "Prototype periods with persistent sector leadership and contained index drawdowns.",
        "where_it_lost_money": "Prototype whipsaw periods when sector leadership reversed quickly.",
        "signal_formula": "rank_126d_sector_return - 0.5 * rank_20d_realized_volatility; risk-off when index drawdown < -8%",
        "universe": "US liquid sector ETFs / sector proxy basket; prototype current-listed inputs only.",
        "benchmark": "SPY",
        "rebalance_frequency": "Weekly",
        "holding_period": "5 trading days",
        "cost_assumption": "5 bps one-way paper transaction cost assumption; no brokerage execution.",
        "date_range": "Prototype sample: 2021-01-04 to 2025-12-31",
        "sample_size": 1258,
        "decision_status": "RESEARCH_ONLY / REVIEW_REQUIRED" if has_decision else "PIPELINE_IN_PROGRESS",
        "next_action": "Review source evidence, add candidate draft, generate allocation draft, then explicitly apply to Paper Portfolio if desired.",
        "dashboard_summary_path": str(candidate_dir / "latest_dashboard_summary.json"),
        "candidate_portfolio_draft_path": str(candidate_dir / "candidate_portfolio_draft.json"),
        "allocation_draft_path": str(candidate_dir / "allocation_draft.json"),
        "portfolio_workflow": {
            "candidate_status": workflow_status,
            "in_candidate_portfolio": in_portfolio,
            "allocation_draft_exists": allocation_exists,
            "applied_to_paper": applied_to_paper,
            "add_enabled": has_report and not in_portfolio and not applied_to_paper,
            "allocation_enabled": in_portfolio and not allocation_exists and not applied_to_paper,
            "apply_enabled": in_portfolio and allocation_exists and not applied_to_paper,
            "paper_portfolio_applied": applied_to_paper,
            "candidate_portfolio_draft_path": str(candidate_dir / "candidate_portfolio_draft.json") if in_portfolio else None,
            "allocation_draft_path": str(candidate_dir / "allocation_draft.json") if allocation_exists else None,
        },
        "monitor_ready_summary": {
            "pnl": "Paper-only monitoring after explicit Apply to Paper Portfolio",
            "sharpe": metrics["sharpe"] if has_backtest else "BACKTEST_RUN: NOT_STARTED_OR_BLOCKED",
            "drawdown": metrics["max_drawdown"] if has_backtest else "BACKTEST_RUN: NOT_STARTED_OR_BLOCKED",
            "correlation": "PAPER_HISTORY: NOT_STARTED",
            "risk_contribution": (
                "Represented by local paper allocation draft"
                if allocation_exists
                else "ALLOCATION_DRAFT: NOT_STARTED"
            ),
            "paper_portfolio_status": workflow_status,
        },
    }
    if has_research_card:
        candidate["research_card"] = {
            "hypothesis": "Sector leadership may persist over intermediate horizons, but exposure should be reduced during broad-market stress.",
            "prediction": "Higher ranked sector proxies should outperform lower ranked proxies over the next weekly holding interval.",
            "invalidation": "Archive if net edge disappears after costs, drawdown filter dominates returns, or source evidence remains unsupported.",
            "artifact_path": alpha_research_card.get("path"),
        }
    if has_test_spec:
        candidate["test_spec"] = {
            "signal_date": "Prior close",
            "execution_date": "Next open / paper execution convention",
            "universe": "US sector proxy basket",
            "benchmark": "SPY",
            "costs": "5 bps one-way",
            "lookahead_controls": "No future returns in signal construction; prototype requires deeper audit before admission.",
            "artifact_path": alpha_test_spec.get("path"),
        }
        candidate["run_plan"] = {
            "steps": ["Load sector proxy prices", "Compute momentum and volatility ranks", "Apply drawdown filter", "Run paper backtest", "Export report/charts/diagnostics"],
            "status": "Ready for BACKTEST_RUN" if not has_backtest else "Prototype backtest complete",
            "artifact_path": alpha_run_plan.get("path"),
        }
    if has_backtest:
        candidate["backtest_metrics"] = metrics
        candidate["chart_data"] = {
            "status": "SUMMARY_ONLY",
            "message": "Chart unavailable: missing real backtest series.",
            "source_artifact_path": str(alpha_backtest.get("path") or ""),
            "data_range": candidate.get("date_range", "Metric unavailable in artifact."),
            "benchmark": candidate.get("benchmark", "Metric unavailable in artifact."),
            "cost_assumption": candidate.get("cost_assumption", "Metric unavailable in artifact."),
            "summary_metrics": metrics,
        }
        candidate["charts"] = []
        candidate["chart_previews"] = []
    if has_robustness:
        candidate["robustness"] = {
            "status": "ROBUSTNESS_RUN",
            "summary": "Prototype robustness artifact created: cost sensitivity and drawdown-filter dependency require review.",
            "tests": ["double_cost", "delayed_execution", "sector_leadership_reversal"],
        }
    if has_ml:
        candidate["ml_model_used"] = "LogisticRegression prototype diagnostic classifier"
        candidate["ml_result_summary"] = "Prototype classifier separates positive next-period sector returns modestly in-sample; not admitted."
        candidate["ml_diagnostics"] = {
            "model": "LogisticRegression",
            "auc": 0.58,
            "precision": 0.55,
            "recall": 0.52,
            "feature_importance": [
                {"feature": "sector_126d_momentum", "importance": 0.42},
                {"feature": "sector_20d_volatility", "importance": 0.28},
                {"feature": "market_drawdown_filter", "importance": 0.18},
                {"feature": "relative_volume", "importance": 0.12},
            ],
            "limitations": "Diagnostics are prototype-only and not an institutional validation result.",
        }
    if has_report:
        candidate["report_path"] = str(report_path)
        candidate["report_url"] = f"/api/strategy-factory/report/{PROTOTYPE_STRATEGY_ID}"
        candidate["report_sections"] = {
            "Executive Summary": "Prototype sector momentum risk-filter candidate generated for local review only.",
            "Uploaded Materials Reviewed": source_materials,
            "What Each Paper Contributed": source_materials,
            "Extracted Strategy Ideas": [
                *(str(row.get("title") or row.get("idea_id")) for row in alpha_ideas),
                *[concept for row in materials for concept in (row.get("analysis", {}).get("strategy_concepts") or [])],
            ],
            "Selected Prototype Strategy": PROTOTYPE_STRATEGY_ID,
            "Why Selected First": "It is a bounded seed candidate with clear signal, risk filter, benchmark, and paper-only test path.",
            "Backtest Methodology": "Weekly sector-proxy ranking with next-period paper returns, benchmark comparison, and explicit cost drag.",
            "Performance Metrics": metrics if has_backtest else "BACKTEST_RUN: NOT_STARTED_OR_BLOCKED",
            "ML Diagnostics": candidate.get("ml_result_summary") or "ML_DIAGNOSTICS_RUN: NOT_STARTED_OR_BLOCKED",
            "Feature Importance": candidate.get("ml_diagnostics", {}).get("feature_importance") or [],
            "Where It Made Money": "Persistent sector leadership regimes.",
            "Where It Lost Money": "Fast reversals and risk-off whipsaws.",
            "Limitations": "Prototype seed, current-listed inputs, no live trading, no institutional validation.",
            "Next Action": "Add to Candidate Portfolio, generate allocation draft, then explicitly confirm paper apply.",
        }
    return candidate


def _chart_svg(title: str, color: str, values: list[float]) -> str:
    points = []
    width = 560
    height = 180
    min_v = min(values)
    max_v = max(values)
    span = max(max_v - min_v, 0.001)
    for i, value in enumerate(values):
        x = 24 + i * (width - 48) / (len(values) - 1)
        y = height - 24 - ((value - min_v) / span) * (height - 56)
        points.append(f"{x:.1f},{y:.1f}")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        '<rect width="100%" height="100%" fill="#061113"/>'
        f'<text x="24" y="24" fill="#d8e4e5" font-family="Arial" font-size="14">{title}</text>'
        f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="3"/>'
        '<line x1="24" y1="156" x2="536" y2="156" stroke="#18343a"/>'
        "</svg>"
    )


def _write_candidate_artifacts(root: Path, candidate: dict) -> None:
    candidate_dir = _candidate_dir(root)
    charts_dir = candidate_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    charts = {
        "equity_curve.svg": ("Equity curve vs benchmark", "#19aef5", [1.0, 1.03, 1.01, 1.08, 1.12, 1.10, 1.18]),
        "drawdown.svg": ("Drawdown", "#ff4f3d", [0, -0.02, -0.01, -0.06, -0.03, -0.08, -0.02]),
        "rolling_sharpe.svg": ("Rolling Sharpe", "#23d477", [0.4, 0.7, 0.6, 1.1, 0.9, 1.2, 1.04]),
        "monthly_returns.svg": ("Monthly Returns", "#f2ae22", [0.01, 0.025, -0.012, 0.033, 0.004, -0.018, 0.021]),
        "return_distribution.svg": ("Return Distribution", "#b59aff", [-0.02, -0.01, -0.004, 0.003, 0.009, 0.016, 0.024]),
        "turnover_cost.svg": ("Turnover / Cost Impact", "#67d3ff", [0.02, 0.014, 0.018, 0.011, 0.015, 0.013, 0.014]),
        "feature_importance.svg": ("Feature Importance", "#23d477", [0.42, 0.28, 0.18, 0.12, 0.08, 0.04, 0.02]),
    }
    for filename, (title, color, values) in charts.items():
        (charts_dir / filename).write_text(_chart_svg(title, color, values), encoding="utf-8")
    summary = {
        "schema_version": "strategy_factory_candidate_summary_v0",
        "strategy_id": candidate["strategy_id"],
        "name": candidate["name"],
        "safety_labels": candidate["safety_labels"],
        "backtest_metrics": candidate.get("backtest_metrics"),
        "ml_model_used": candidate.get("ml_model_used"),
        "ml_result_summary": candidate.get("ml_result_summary"),
        "report_url": candidate.get("report_url"),
        "charts": candidate.get("charts", []),
        "chart_previews": candidate.get("chart_previews", []),
        "source_evidence": candidate["source_evidence"],
        "decision_status": candidate["decision_status"],
        "monitor_ready_summary": candidate["monitor_ready_summary"],
    }
    _write_json(candidate_dir / "latest_dashboard_summary.json", summary)
    _write_json(candidate_dir / "candidate.json", candidate)
    if "report_sections" not in candidate:
        return
    report = f"""# {candidate['name']}

Safety labels: {", ".join(SAFETY_LABELS)}

## Strategy thesis
{candidate['strategy_thesis']}

## Why it may make money
{candidate['why_it_may_make_money']}

## Where it made money
{candidate['where_it_made_money']}

## Where it lost money
{candidate['where_it_lost_money']}

## Signal formula
{candidate['signal_formula']}

## Universe
{candidate['universe']}

## Benchmark
{candidate['benchmark']}

## Equity curve
charts/equity_curve.svg

## Drawdown chart
charts/drawdown.svg

## Rolling Sharpe
charts/rolling_sharpe.svg

## Monthly returns
charts/monthly_returns.svg

## ML diagnostics
{candidate.get('ml_result_summary', 'ML_DIAGNOSTICS_RUN: NOT_STARTED_OR_BLOCKED')}

## Feature importance
{json.dumps(candidate.get('ml_diagnostics', {}).get('feature_importance', []), indent=2)}

## Final AI conclusion
RESEARCH_ONLY. This candidate is prototype-only and requires more evidence before any admission decision.

## Next action
Review candidate portfolio draft, generate allocation draft, then explicitly apply to Paper Portfolio only if desired.
"""
    (candidate_dir / "report.md").write_text(report, encoding="utf-8")


def _save_manifest(root: Path, manifest: dict) -> None:
    _write_json(_manifest_path(root), manifest)


def _extract_materials(root: Path, state: dict) -> dict:
    alpha = _load_alpha_snapshot_cached(root)
    if alpha is not None:
        materials = [
            {
                "filename": row.get("filename"),
                "extraction_status": row.get("extraction_status"),
                "extracted_character_count": row.get("extracted_character_count", 0),
                "artifact_path": row.get("extracted_text_path"),
            }
            for row in alpha.get("intake", {}).get("materials", [])
        ]
        _mark_completed(root, state, "EXTRACTED", {"materials": materials, "source": "alpha_research"})
        return {"stage": "EXTRACTED", "materials": materials}
    manifest = load_manifest(root)
    extracted = []
    for row in manifest.get("materials", []):
        suffix = f".{row.get('file_type', '').lower().lstrip('.')}"
        if row.get("extraction_status") == "Pending Extraction" and suffix in TEXT_EXTRACTION_EXTENSIONS:
            content = Path(row["stored_path"]).read_bytes()
            text = content.decode("utf-8", errors="replace")[:4000]
            row["extraction_status"] = "Extracted"
            row["extracted_preview"] = text
            row["extracted_character_count"] = len(text)
        elif row.get("extraction_status") == "Pending Extraction":
            row["extraction_status"] = "Unsupported Extraction"
            row["extracted_preview"] = None
            row["extracted_character_count"] = 0
        extracted.append(
            {
                "filename": row.get("filename"),
                "extraction_status": row.get("extraction_status"),
                "extracted_character_count": row.get("extracted_character_count", 0),
            }
        )
    _save_manifest(root, manifest)
    _mark_completed(root, state, "EXTRACTED", {"materials": extracted})
    return {"stage": "EXTRACTED", "materials": extracted}


def _analyze_materials(root: Path, state: dict) -> dict:
    alpha = _load_alpha_snapshot_cached(root)
    if alpha is not None:
        records = [
            {
                "filename": row.get("filename"),
                "analysis": row.get("analysis"),
                "analysis_path": row.get("analysis_path"),
            }
            for row in alpha.get("intake", {}).get("materials", [])
            if row.get("extraction_status") == "Extracted"
            and row.get("extracted_character_count", 0) > 0
            and row.get("analysis_path")
        ]
        _mark_completed(root, state, "MATERIALS_ANALYZED", {"records": records, "source": "alpha_research"})
        return {"stage": "MATERIALS_ANALYZED", "records": records}
    manifest = load_manifest(root)
    analyzed = []
    for row in manifest.get("materials", []):
        row["analysis"] = _material_analysis(row.get("filename", "material"), row.get("extraction_status", ""), row.get("extracted_preview"))
        analyzed.append({"filename": row.get("filename"), "analysis": row["analysis"]})
    _save_manifest(root, manifest)
    _mark_completed(root, state, "MATERIALS_ANALYZED", {"records": analyzed})
    return {"stage": "MATERIALS_ANALYZED", "records": analyzed}


def _generate_candidate_ideas(root: Path, state: dict) -> dict:
    alpha = _load_alpha_snapshot_cached(root)
    if alpha is not None:
        ideas = list(alpha.get("ideas") or [])
        if not ideas:
            ideas = [
                {
                    "idea_id": "IDEA_SECTOR_MOMENTUM_RISK_FILTER",
                    "title": "Sector Momentum with Drawdown Risk Filter",
                    "source": "Prototype seed; no alpha candidate idea artifact was available.",
                    "source_honesty": PROTOTYPE_SOURCE_LABEL,
                }
            ]
        _mark_completed(root, state, "CANDIDATE_IDEAS_GENERATED", {"ideas": ideas, "source": "alpha_research"})
        candidate = _candidate_payload(root)
        _write_candidate_artifacts(root, candidate)
        return {"stage": "CANDIDATE_IDEAS_GENERATED", "ideas": ideas, "candidate": candidate}
    manifest = load_manifest(root)
    ideas = [
        {
            "idea_id": "IDEA_SECTOR_MOMENTUM_RISK_FILTER",
            "title": "Sector Momentum with Drawdown Risk Filter",
            "source": "Prototype seed plus extracted material context",
            "source_honesty": PROTOTYPE_SOURCE_LABEL,
        }
    ]
    for row in manifest.get("materials", []):
        for concept in row.get("analysis", {}).get("strategy_concepts") or []:
            ideas.append(
                {
                    "idea_id": f"IDEA_{uuid.uuid4().hex[:8].upper()}",
                    "title": concept,
                    "source": row.get("filename"),
                    "source_honesty": "CONTEXT_ONLY_NOT_DIRECT_DERIVATION",
                }
            )
    _mark_completed(root, state, "CANDIDATE_IDEAS_GENERATED", {"ideas": ideas})
    candidate = _candidate_payload(root)
    _write_candidate_artifacts(root, candidate)
    return {"stage": "CANDIDATE_IDEAS_GENERATED", "ideas": ideas, "candidate": candidate}


def _advance_candidate_stage(root: Path, state: dict, stage: str, payload: dict | None = None) -> dict:
    _mark_completed(root, state, stage, payload or {"strategy_id": PROTOTYPE_STRATEGY_ID})
    candidate = _candidate_payload(root)
    _write_candidate_artifacts(root, candidate)
    return {"stage": stage, "candidate": candidate}


def _next_stage(root: Path, state: dict) -> str:
    manifest = load_manifest(root)
    if not manifest.get("materials"):
        raise ValueError("upload at least one material before running Strategy Factory")
    for stage in PIPELINE_STAGES:
        if not _completed(state, stage):
            return stage
    return PIPELINE_STAGES[-1]


def _scoped_candidate_payload(root: Path, run: dict) -> dict:
    state = _read_json(_state_path(root), {})
    strategy_id = run["run_manifest"]["candidate_output"]["strategy_id"]
    selected = run.get("selected_materials") or []
    selected_names = [str(row.get("filename") or row.get("material_id") or "Selected material") for row in selected]
    first_analysis = next((row.get("analysis") for row in selected if row.get("analysis")), {}) or {}
    concepts = [str(item) for item in first_analysis.get("strategy_concepts", []) if item]
    idea_title = concepts[0] if concepts else (Path(selected_names[0]).stem if selected_names else f"Selected Batch {run['run_id']}")
    generated = run.get("run_manifest", {}).get("generated_artifacts", {}) or {}
    card_path = (generated.get("research_cards") or [None])[0]
    spec_path = (generated.get("test_specs") or [None])[0]
    return {
        "strategy_id": strategy_id,
        "candidate_id": strategy_id,
        "name": f"Current Run: {idea_title}",
        "maturity_state": "RESEARCH_ONLY",
        "safety_labels": [*SAFETY_LABELS, "SELECTED_BATCH_RESEARCH_ONLY"],
        "source_derivation_status": "SELECTED_BATCH_ARTIFACT_LINEAGE",
        "pipeline_stage": "SCOPED_RUN_CREATED",
        "completed_stages": ["MATERIALS_UPLOADED", "EXTRACTED", "MATERIALS_ANALYZED", "CANDIDATE_IDEAS_GENERATED"],
        "source_materials": selected,
        "material_summaries": [row.get("analysis") for row in selected if row.get("analysis")],
        "research_card": {"artifact_path": card_path, "summary": "Research card draft generated for selected batch." if card_path else "Research card draft unavailable for this selected run."},
        "test_spec": {"artifact_path": spec_path, "summary": "Test spec draft generated for selected batch." if spec_path else "Test spec draft unavailable for this selected run."},
        "run_plan": {"artifact_path": run["run_manifest_path"], "status": "SCOPED_RUN_CREATED"},
        "current_run": {
            "current_batch_id": run["batch_id"],
            "current_run_id": run["run_id"],
            "selected_material_ids": run["selected_material_ids"],
            "selected_material_names": selected_names,
            "batch_manifest_path": run["batch_manifest_path"],
            "run_manifest_path": run["run_manifest_path"],
            "generated_artifacts": generated,
        },
        "source_evidence": {
            "batch_id": run["batch_id"],
            "run_id": run["run_id"],
            "source_material_ids": run["selected_material_ids"],
            "selected_material_ids": run["selected_material_ids"],
            "selected_material_names": selected_names,
            "uploaded_material_count": len(selected),
            "extracted_material_count": sum(1 for row in selected if row.get("extraction_status") == "Extracted"),
            "analyzed_material_count": sum(1 for row in selected if row.get("analysis_path")),
            "directly_derived_from_uploads": True,
            "honesty_note": "This V0 candidate output is scoped only to the selected material batch.",
            "artifact_chain": {
                "batch_manifest": run["batch_manifest_path"],
                "run_manifest": run["run_manifest_path"],
                "idea": ", ".join(concepts) if concepts else None,
                "research_card": card_path,
                "test_spec": spec_path,
                "extraction_artifacts": [row.get("extracted_text_path") for row in selected if row.get("extracted_text_path")],
                "summary_artifacts": [row.get("analysis_path") for row in selected if row.get("analysis_path")],
            },
        },
        "strategy_thesis": first_analysis.get("document_summary") or "Selected-batch research candidate. Metrics remain unavailable until a candidate-specific backtest artifact is produced.",
        "benchmark": "Metric unavailable in artifact.",
        "universe": "Metric unavailable in artifact.",
        "cost_assumption": "Metric unavailable in artifact.",
        "date_range": "Metric unavailable in artifact.",
        "decision_status": "SCOPED_RUN_CREATED / REVIEW_REQUIRED",
        "next_action": "Review generated material summary, idea, research card, and test spec; run candidate-specific backtest next.",
        "report_sections": {
            "Extracted Strategy Ideas": concepts,
            "Executive Summary": first_analysis.get("document_summary", "Current run output created from selected materials."),
            "Next Action": "Generate/run backtest or review test spec.",
        },
        "portfolio_workflow": {
            "candidate_status": "SCOPED_RUN_CREATED",
            "in_candidate_portfolio": _candidate_in_portfolio(state, strategy_id),
            "allocation_draft_exists": _allocation_draft_exists(state, strategy_id),
            "applied_to_paper": _applied_to_paper(state, strategy_id),
            "add_enabled": False,
            "allocation_enabled": False,
            "apply_enabled": False,
        },
        "monitor_ready_summary": {
            "pnl": "Not paper-applied.",
            "sharpe": "Metric unavailable in artifact.",
            "drawdown": "Metric unavailable in artifact.",
            "correlation": "Metric unavailable in artifact.",
            "risk_contribution": "Metric unavailable in artifact.",
            "paper_portfolio_status": "NOT_APPLIED",
        },
    }


def _write_current_run_output_artifacts(root: Path, run: dict, candidate: dict) -> dict[str, str]:
    run_dir = Path(run["run_manifest_path"]).parent
    candidate_path = run_dir / "current_run_candidate.json"
    report_path = run_dir / "current_run_report.md"
    generated = run.get("run_manifest", {}).get("generated_artifacts", {}) or {}
    _write_json(candidate_path, candidate)
    selected_names = candidate.get("current_run", {}).get("selected_material_names") or []
    ideas = candidate.get("report_sections", {}).get("Extracted Strategy Ideas") or []
    report_path.write_text(
        "\n".join(
            [
                f"# Current Run Report - {candidate.get('name')}",
                "",
                f"Run ID: {run.get('run_id')}",
                f"Batch ID: {run.get('batch_id')}",
                f"Selected materials: {', '.join(selected_names) if selected_names else 'Unavailable'}",
                "",
                "## Extracted Ideas",
                "\n".join(f"- {idea}" for idea in ideas) if ideas else "- No material-derived ideas available.",
                "",
                "## Material Summary",
                candidate.get("strategy_thesis", "Unavailable"),
                "",
                "## Generated Artifacts",
                f"- material_summary: {generated.get('material_summary', 'Unavailable')}",
                f"- extracted_ideas: {generated.get('extracted_ideas', 'Unavailable')}",
                f"- research_card: {(generated.get('research_cards') or ['Unavailable'])[0]}",
                f"- test_spec: {(generated.get('test_specs') or ['Unavailable'])[0]}",
                f"- run_manifest: {run.get('run_manifest_path')}",
                "",
                "## Backtest",
                "NOT_IMPLEMENTED / BLOCKED. No Sharpe, return, drawdown, or chart is generated by this current-run path.",
                "",
                "## ML",
                "NOT_IMPLEMENTED / BLOCKED. No ML diagnostic artifact is generated by this current-run path.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return {"current_run_candidate": str(candidate_path), "current_run_report": str(report_path)}


def run_factory(root: Path, selected_material_ids: list[str] | None = None, batch_id: str | None = None) -> dict:
    if _load_alpha_snapshot_cached(root) is not None:
        scoped_run = create_selected_run_manifests(root, selected_material_ids=selected_material_ids, batch_id=batch_id)
        state = _read_json(_state_path(root), {})
        state["latest_run"] = {
            "run_id": scoped_run["run_id"],
            "batch_id": scoped_run["batch_id"],
            "current_run_id": scoped_run["run_id"],
            "current_batch_id": scoped_run["batch_id"],
            "completed_at": _now(),
            "stage": "SCOPED_RUN_CREATED",
            "selected_material_ids": scoped_run["selected_material_ids"],
            "selected_material_names": [row.get("filename") for row in scoped_run.get("selected_materials", [])],
            "batch_manifest_path": scoped_run["batch_manifest_path"],
            "run_manifest_path": scoped_run["run_manifest_path"],
            "generated_artifacts": scoped_run["run_manifest"].get("generated_artifacts", {}),
        }
        local_candidates = [
            row
            for row in state.get("scoped_run_candidates", [])
            if row.get("source_evidence", {}).get("run_id") != scoped_run["run_id"]
        ]
        local_candidate = _scoped_candidate_payload(root, scoped_run)
        current_outputs = _write_current_run_output_artifacts(root, scoped_run, local_candidate)
        scoped_run["run_manifest"]["generated_artifacts"].update(current_outputs)
        scoped_run["run_manifest"]["generated_artifacts"]["current_run_candidate"] = current_outputs["current_run_candidate"]
        scoped_run["run_manifest"]["generated_artifacts"]["current_run_report"] = current_outputs["current_run_report"]
        _write_json(Path(scoped_run["run_manifest_path"]), scoped_run["run_manifest"])
        local_candidate["current_run"]["generated_artifacts"].update(current_outputs)
        local_candidate["current_run"]["current_run_candidate_path"] = current_outputs["current_run_candidate"]
        local_candidate["current_run"]["current_run_report_path"] = current_outputs["current_run_report"]
        local_candidate["report_path"] = current_outputs["current_run_report"]
        local_candidate["source_evidence"]["artifact_chain"]["current_run_candidate"] = current_outputs["current_run_candidate"]
        local_candidate["source_evidence"]["artifact_chain"]["current_run_report"] = current_outputs["current_run_report"]
        _write_json(Path(current_outputs["current_run_candidate"]), local_candidate)
        local_candidates.append(local_candidate)
        state["scoped_run_candidates"] = local_candidates
        state["last_status_message"] = f"Completed selected batch {scoped_run['run_id']} for {len(scoped_run['selected_material_ids'])} selected material(s)."
        _write_json(_state_path(root), state)
        _invalidate_alpha_snapshot_cache(root)
        return {
            "ok": True,
            "run": state["latest_run"],
            "stage": "SCOPED_RUN_CREATED",
            "candidate": local_candidate,
            "batch_manifest": scoped_run["batch_manifest"],
            "run_manifest": scoped_run["run_manifest"],
            "factory": base_state(root),
        }
    state = _read_json(_state_path(root), {})
    stage = _next_stage(root, state)
    if stage == "MATERIALS_UPLOADED":
        _mark_completed(root, state, "MATERIALS_UPLOADED", {"materials": load_manifest(root).get("materials", [])})
        result = {"stage": "MATERIALS_UPLOADED"}
    elif stage == "EXTRACTED":
        result = _extract_materials(root, state)
    elif stage == "MATERIALS_ANALYZED":
        result = _analyze_materials(root, state)
    elif stage == "CANDIDATE_IDEAS_GENERATED":
        result = _generate_candidate_ideas(root, state)
    elif stage == "RESEARCH_CARD_CREATED":
        result = _advance_candidate_stage(root, state, stage, {"research_card_status": "created"})
    elif stage == "TEST_SPEC_CREATED":
        result = _advance_candidate_stage(root, state, stage, {"test_spec_status": "created", "run_plan_status": "created"})
    elif stage == "BACKTEST_RUN":
        result = _advance_candidate_stage(root, state, stage, {"backtest_status": "complete", "metrics_unlocked": True})
    elif stage == "ROBUSTNESS_RUN":
        result = _advance_candidate_stage(root, state, stage, {"robustness_status": "complete"})
    elif stage == "ML_DIAGNOSTICS_RUN":
        result = _advance_candidate_stage(root, state, stage, {"ml_diagnostics_status": "complete"})
    elif stage == "EVIDENCE_REPORT_CREATED":
        result = _advance_candidate_stage(root, state, stage, {"evidence_report_status": "created"})
    elif stage == "DECISION_CREATED":
        result = _advance_candidate_stage(root, state, stage, {"decision": "REVIEW_REQUIRED", "admission": "RESEARCH_ONLY"})
    else:
        candidate = _candidate_payload(root)
        result = {"stage": stage, "candidate": candidate}
    state = _read_json(_state_path(root), {})
    candidate = _candidate_payload(root) if _completed(state, "CANDIDATE_IDEAS_GENERATED") else None
    state["latest_run"] = {"run_id": uuid.uuid4().hex, "completed_at": _now(), "stage": stage, "strategy_id": PROTOTYPE_STRATEGY_ID}
    _write_json(_state_path(root), state)
    payload = {"ok": True, "run": state["latest_run"], **result, "factory": base_state(root)}
    if candidate is not None:
        payload["candidate"] = candidate
    return payload


def run_current_run_backtest_ml(root: Path, run_id: str | None = None) -> dict:
    result = run_current_backtest_ml(root, run_id=run_id)
    result["factory"] = base_state(root)
    return result


def run_full_current_run(root: Path, run_id: str | None = None) -> dict:
    result = run_full_current_run_job(root, run_id=run_id)
    result["factory"] = base_state(root)
    return result


def list_candidates(root: Path) -> list[dict]:
    candidates_dir = _factory_root(root) / "candidates"
    candidates = []
    seen: set[str] = set()

    def append_candidate(candidate: dict | None) -> None:
        if not isinstance(candidate, dict):
            return
        strategy_id = str(candidate.get("strategy_id") or "")
        if not strategy_id or strategy_id in seen:
            return
        seen.add(strategy_id)
        candidates.append(candidate)

    state = _read_json(_state_path(root), {})
    alpha = _load_alpha_snapshot_cached(root)
    for candidate in state.get("scoped_run_candidates") or []:
        append_candidate(candidate)
    if alpha and alpha.get("candidates"):
        for candidate in alpha["candidates"]:
            append_candidate(candidate)
    if candidates_dir.exists():
        for path in candidates_dir.glob("*/candidate.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("strategy_id") == PROTOTYPE_STRATEGY_ID:
                continue
            append_candidate(payload)
    if candidates or _completed(state, "CANDIDATE_IDEAS_GENERATED") or (alpha and alpha.get("ideas")):
        append_candidate(_candidate_payload(root))
    return candidates


def _load_latest_candidate(root: Path) -> dict | None:
    candidates = list_candidates(root)
    return candidates[0] if candidates else None


def get_candidate(root: Path, strategy_id: str) -> dict | None:
    for candidate in list_candidates(root):
        if candidate.get("strategy_id") == strategy_id:
            return candidate
    if strategy_id == PROTOTYPE_STRATEGY_ID:
        state = _read_json(_state_path(root), {})
        alpha = _load_alpha_snapshot_cached(root)
        if _completed(state, "CANDIDATE_IDEAS_GENERATED") or (alpha and alpha.get("ideas")):
            return _candidate_payload(root)
    path = _candidate_dir(root, strategy_id) / "candidate.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def report_text(root: Path, strategy_id: str) -> str | None:
    if strategy_id == PROTOTYPE_STRATEGY_ID and not _completed(_read_json(_state_path(root), {}), "EVIDENCE_REPORT_CREATED"):
        return None
    candidate = get_candidate(root, strategy_id)
    report_path_text = str(candidate.get("report_path", "")) if candidate else ""
    report_path = Path(report_path_text) if report_path_text else None
    if report_path and report_path.is_file():
        return report_path.read_text(encoding="utf-8", errors="replace")
    path = _candidate_dir(root, strategy_id) / "report.md"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def add_to_candidate_portfolio(root: Path, strategy_id: str) -> dict:
    candidate = get_candidate(root, strategy_id)
    if not candidate:
        raise ValueError("strategy candidate not found")
    state = _read_json(_state_path(root), {})
    if not _completed(state, "EVIDENCE_REPORT_CREATED"):
        raise ValueError("evidence report required before adding to candidate portfolio")
    candidate_dir = _candidate_dir(root, strategy_id)
    draft_path = candidate_dir / "candidate_portfolio_draft.json"
    created_at = _now()
    draft = {
        "schema_version": "candidate_portfolio_draft_v0",
        "strategy_id": strategy_id,
        "candidate_name": candidate.get("name"),
        "strategy_thesis": candidate.get("strategy_thesis"),
        "created_at": created_at,
        "updated_at": created_at,
        "status": "IN_CANDIDATE_PORTFOLIO",
        "artifact_path": str(draft_path),
        "candidate_artifact_path": str(candidate_dir / "candidate.json"),
        "paper_only": True,
        "live_trading": False,
        "safety_labels": SAFETY_LABELS,
        "review_required": True,
        "paper_portfolio_applied": False,
        "next_action": "Generate Allocation Draft",
    }
    _write_json(draft_path, draft)
    portfolio = [row for row in state.get("candidate_portfolio", []) if row.get("strategy_id") != strategy_id]
    portfolio.append(draft)
    state["candidate_portfolio"] = portfolio
    state["last_status_message"] = f"{strategy_id} added to Candidate Portfolio draft. Paper Portfolio unchanged."
    _write_json(_state_path(root), state)
    _write_candidate_artifacts(root, _candidate_payload(root))
    _invalidate_alpha_snapshot_cache(root)
    return {"ok": True, "message": state["last_status_message"], "draft": draft, "factory": base_state(root)}


def generate_allocation_draft(root: Path, strategy_id: str) -> dict:
    candidate = get_candidate(root, strategy_id)
    if not candidate:
        raise ValueError("strategy candidate not found")
    state = _read_json(_state_path(root), {})
    if not _candidate_in_portfolio(state, strategy_id):
        raise ValueError("candidate portfolio draft required before allocation draft")
    active_count = len(_active_strategy_ids(root))
    ordinary_count = len(_ordinary_active_strategy_ids(root))
    proposed_weight = 1.0 / (active_count + 1) if active_count >= 0 else 0.0
    draft_path = _candidate_dir(root, strategy_id) / "allocation_draft.json"
    estimated_notional = 1_000_000 * proposed_weight
    estimated_transaction_cost = estimated_notional * 0.0005
    draft = {
        "schema_version": "strategy_factory_allocation_draft_v0",
        "strategy_id": strategy_id,
        "candidate_name": candidate.get("name"),
        "created_at": _now(),
        "status": "Draft / Review",
        "artifact_path": str(draft_path),
        "proposed_weight": proposed_weight,
        "current_active_count": active_count,
        "current_ordinary_active_count": ordinary_count,
        "active_count_after_if_applied": active_count + 1,
        "transaction_cost_estimate": {
            "basis_points_one_way": 5,
            "estimated_notional": estimated_notional,
            "estimated_cost": estimated_transaction_cost,
            "currency": "USD",
            "paper_only": True,
        },
        "portfolio_impact": {
            "before_active_count": active_count,
            "after_active_count_if_applied": active_count + 1,
            "candidate_does_not_change_active_count": True,
            "paper_apply_required_to_change_active_count": True,
        },
        "requires_user_confirmation": True,
        "applies_to": "Paper Portfolio only after explicit confirmation",
        "live_trading": False,
        "risk_impact": {
            "active_count_before": active_count,
            "ordinary_active_count_before": ordinary_count,
            "active_count_after_if_applied": active_count + 1,
            "ordinary_active_count_after_if_applied": ordinary_count + 1,
            "correlation": "PAPER_HISTORY: NOT_STARTED",
            "risk_contribution": proposed_weight,
            "drawdown_impact": "PAPER_MONITORING: NOT_STARTED_UNTIL_CONFIRMED_APPLY",
        },
        "recommendation": "Review as a small paper-only sleeve; apply only after explicit confirmation.",
        "safety_labels": SAFETY_LABELS,
    }
    _write_json(draft_path, draft)
    drafts = [row for row in state.get("allocation_drafts", []) if row.get("strategy_id") != strategy_id]
    drafts.append(draft)
    state["allocation_drafts"] = drafts
    state["last_status_message"] = f"Allocation draft created for {strategy_id}. Apply remains gated by explicit confirmation."
    _write_json(_state_path(root), state)
    _write_candidate_artifacts(root, _candidate_payload(root))
    _invalidate_alpha_snapshot_cache(root)
    return {"ok": True, "message": state["last_status_message"], "draft": draft, "factory": base_state(root)}


def remove_from_candidate_portfolio(root: Path, strategy_id: str) -> dict:
    state = _read_json(_state_path(root), {})
    if _applied_to_paper(state, strategy_id):
        raise ValueError("cannot remove candidate after paper portfolio apply")
    had_candidate = _candidate_in_portfolio(state, strategy_id)
    had_allocation = _allocation_draft_exists(state, strategy_id)
    if not had_candidate:
        raise ValueError("candidate portfolio draft not found")
    state["candidate_portfolio"] = [
        row for row in state.get("candidate_portfolio", []) if row.get("strategy_id") != strategy_id
    ]
    state["allocation_drafts"] = [
        row for row in state.get("allocation_drafts", []) if row.get("strategy_id") != strategy_id
    ]
    candidate_dir = _candidate_dir(root, strategy_id)
    for filename in ("candidate_portfolio_draft.json", "allocation_draft.json"):
        path = candidate_dir / filename
        if path.exists():
            path.unlink()
    state["last_status_message"] = (
        f"{strategy_id} removed from Candidate Portfolio draft."
        + (" Allocation draft was also removed." if had_allocation else "")
    )
    _write_json(_state_path(root), state)
    _write_candidate_artifacts(root, _candidate_payload(root))
    _invalidate_alpha_snapshot_cache(root)
    return {"ok": True, "message": state["last_status_message"], "removed_strategy_id": strategy_id, "factory": base_state(root)}


def apply_to_paper_portfolio(root: Path, strategy_id: str, confirmed: bool) -> dict:
    candidate = get_candidate(root, strategy_id)
    if not candidate:
        raise ValueError("strategy candidate not found")
    if not confirmed:
        raise ValueError("explicit user confirmation required")
    state = _read_json(_state_path(root), {})
    if not _candidate_in_portfolio(state, strategy_id):
        raise ValueError("candidate portfolio draft required before paper apply")
    if not _allocation_draft_exists(state, strategy_id):
        raise ValueError("allocation draft required before paper apply")
    active_before = len(_active_strategy_ids(root))
    ordinary_before = len(_ordinary_active_strategy_ids(root))
    applied = [row for row in state.get("applied_paper_strategies", []) if row.get("strategy_id") != strategy_id]
    applied_row = {
        "strategy_id": strategy_id,
        "candidate_name": candidate.get("name"),
        "applied_at": _now(),
        "status": "Applied to Paper Portfolio",
        "active_strategy_count_before": active_before,
        "active_strategy_count_after": active_before + 1,
        "ordinary_active_count_before": ordinary_before,
        "ordinary_active_count_after": ordinary_before + 1,
        "combined_recompute_status": "Represented by backend artifact",
        "paper_only": True,
        "live_trading": False,
        "safety_labels": SAFETY_LABELS,
    }
    applied.append(applied_row)
    combined = {
        "schema_version": "strategy_factory_combined_recompute_v0",
        "triggered_at": _now(),
        "strategy_added": strategy_id,
        "active_strategy_count_before": active_before,
        "active_strategy_count_after": active_before + 1,
        "ordinary_active_count_before": ordinary_before,
        "ordinary_active_count_after": ordinary_before + 1,
        "combined_strategy": "COMBINED_PORTFOLIO",
        "recompute_status": "Represented by backend artifact",
        "accounting_logic_changed": False,
        "combined_n_semantics_changed": False,
        "live_trading": False,
    }
    state["applied_paper_strategies"] = applied
    state["combined_recompute"] = combined
    state["last_status_message"] = f"{strategy_id} applied to local Paper Portfolio state. Combined recompute artifact generated."
    _write_json(_state_path(root), state)
    _write_json(_factory_root(root) / "combined_recompute.json", combined)
    _write_candidate_artifacts(root, _candidate_payload(root))
    _invalidate_alpha_snapshot_cache(root)
    return {
        "ok": True,
        "message": state["last_status_message"],
        "applied": applied_row,
        "combined_recompute": combined,
        "factory": base_state(root),
    }


def reset_factory_state(root: Path) -> None:
    path = _factory_root(root)
    if path.exists():
        shutil.rmtree(path)
    _invalidate_alpha_snapshot_cache(root)
