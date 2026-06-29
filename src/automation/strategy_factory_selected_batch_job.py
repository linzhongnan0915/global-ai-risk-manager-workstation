"""Strategy Factory selected batch job artifact.

Wraps the existing Strategy Factory run path with an operator-visible job
manifest. The wrapper records what happened; it does not create portfolio
approval, paper apply, brokerage, or accounting artifacts.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.strategies.strategy_factory_plugin import base_state, run_factory


SOURCE = "strategy_factory_selected_batch_job_v1"
ARTIFACT_DIR = Path("data/strategy_factory/jobs")
STAGES = [
    "material_lookup",
    "classification",
    "research_card_generation",
    "test_spec_generation",
    "evidence_report",
    "candidate_registry_update",
    "ml_gate",
]


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


def _relative(root: Path, path: Path | str | None) -> str | None:
    if not path:
        return None
    path_obj = Path(path)
    try:
        return path_obj.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return str(path).replace("\\", "/")


def strategy_factory_job_dir(root: str | Path) -> Path:
    return Path(root) / ARTIFACT_DIR


def strategy_factory_job_path(root: str | Path, job_id: str) -> Path:
    return strategy_factory_job_dir(root) / f"{job_id}.json"


def latest_strategy_factory_job_path(root: str | Path) -> Path | None:
    folder = strategy_factory_job_dir(root)
    if not folder.exists():
        return None
    paths = sorted(folder.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    return paths[0] if paths else None


def read_strategy_factory_job(root: str | Path, job_id: str) -> dict[str, Any]:
    root_path = Path(root)
    path = strategy_factory_job_path(root_path, job_id)
    if not path.exists():
        return {
            "ok": False,
            "status": "MISSING_ARTIFACT",
            "source": SOURCE,
            "job_id": job_id,
            "artifact_path": None,
            "message": "Strategy Factory selected batch job artifact not found.",
        }
    payload = _read_json(path, {})
    return {
        "ok": isinstance(payload, dict) and payload.get("source") == SOURCE,
        "status": "AVAILABLE" if isinstance(payload, dict) and payload.get("source") == SOURCE else "INVALID_ARTIFACT",
        "source": SOURCE,
        "job_id": job_id,
        "artifact_path": _relative(root_path, path),
        "job": payload,
    }


def read_latest_strategy_factory_job(root: str | Path) -> dict[str, Any]:
    root_path = Path(root)
    path = latest_strategy_factory_job_path(root_path)
    if path is None:
        return {
            "ok": False,
            "status": "MISSING_ARTIFACT",
            "source": SOURCE,
            "artifact_path": None,
            "message": "No Strategy Factory selected batch job has been run yet.",
        }
    payload = _read_json(path, {})
    return {
        "ok": isinstance(payload, dict) and payload.get("source") == SOURCE,
        "status": "AVAILABLE" if isinstance(payload, dict) and payload.get("source") == SOURCE else "INVALID_ARTIFACT",
        "source": SOURCE,
        "job_id": payload.get("job_id") if isinstance(payload, dict) else None,
        "artifact_path": _relative(root_path, path),
        "job": payload,
    }


def _stage(stage: str, status: str, reason: str, artifact_path: str | None = None, output_count: int | None = None) -> dict[str, Any]:
    return {
        "name": stage,
        "stage": stage,
        "status": status,
        "reason": reason,
        "output_count": output_count,
        "warnings": [] if status != "FAILED" else [reason],
        "errors": [] if status != "FAILED" else [reason],
        "artifact_path": artifact_path,
    }


def _existing_factory_stage(factory: dict[str, Any], wanted: str) -> dict[str, Any] | None:
    labels = {
        "classification": ("MATERIALS_ANALYZED",),
        "research_card_generation": ("RESEARCH_CARD_CREATED",),
        "test_spec_generation": ("TEST_SPEC_CREATED",),
        "evidence_report": ("EVIDENCE_REPORT_CREATED",),
        "ml_gate": ("ML_DIAGNOSTICS_RUN",),
    }
    wanted_labels = labels.get(wanted, ())
    for row in factory.get("stage_statuses") or []:
        if row.get("stage") in wanted_labels:
            return row
    return None


def _job_stages(root: Path, result: dict[str, Any], selected_material_ids: list[str]) -> list[dict[str, Any]]:
    factory = result.get("factory") if isinstance(result.get("factory"), dict) else {}
    run = result.get("run") if isinstance(result.get("run"), dict) else {}
    candidate = result.get("candidate") if isinstance(result.get("candidate"), dict) else {}
    generated = (run.get("generated_artifacts") or {}) if isinstance(run, dict) else {}
    selected_count = len(run.get("selected_material_ids") or selected_material_ids)
    stages = [
        _stage(
            "material_lookup",
            "COMPLETE" if selected_count else "FAILED",
            f"{selected_count} selected material id(s) resolved by backend run manifest." if selected_count else "No selected material ids were provided.",
            _relative(root, run.get("run_manifest_path") or result.get("run_manifest", {}).get("run_manifest_path")),
            selected_count,
        )
    ]
    for stage_name in STAGES[1:]:
        if stage_name == "candidate_registry_update" and candidate:
            stages.append(
                _stage(
                    "candidate_registry_update",
                    "COMPLETE",
                    "Current run candidate output was written by the existing Strategy Factory path.",
                    _relative(root, generated.get("current_run_candidate") or candidate.get("current_run", {}).get("current_run_candidate_path")),
                    1,
                )
            )
            continue
        factory_stage = _existing_factory_stage(factory, stage_name)
        status = "NOT_WIRED"
        reason = "Existing Strategy Factory run path did not emit this stage-specific artifact for the selected batch."
        artifact_path = None
        if factory_stage:
            raw_status = str(factory_stage.get("status") or "NOT_WIRED").upper()
            status = "COMPLETE" if raw_status in {"COMPLETED", "COMPLETE"} else raw_status if raw_status in {"FAILED", "NOT_WIRED"} else "NOT_WIRED"
            reason = str(factory_stage.get("reason") or reason)
            artifact_path = _relative(root, factory_stage.get("artifact_path"))
        output_count = 1 if status == "COMPLETE" and artifact_path else 0
        stages.append(_stage(stage_name, status, reason, artifact_path, output_count))
    return stages


def run_selected_batch_job(
    root: str | Path,
    *,
    material_ids: list[str],
    mode: str = "selected_batch",
) -> dict[str, Any]:
    root_path = Path(root)
    selected = [str(item).strip() for item in material_ids if str(item).strip()]
    if not selected:
        raise ValueError("material_ids must contain at least one backend material_id")
    result = run_factory(root_path, selected_material_ids=selected)
    run = result.get("run") if isinstance(result.get("run"), dict) else {}
    candidate = result.get("candidate") if isinstance(result.get("candidate"), dict) else {}
    job_id = str(run.get("run_id") or f"sf_job_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}")
    generated_at = datetime.now(timezone.utc).isoformat()
    artifact = {
        "ok": True,
        "source": SOURCE,
        "job_id": job_id,
        "mode": mode,
        "status": "COMPLETE" if result.get("ok") else "FAILED",
        "created_at": generated_at,
        "generated_at": generated_at,
        "paper_shadow_only": True,
        "financial_state_mutated": False,
        "selected_material_count": len(selected),
        "selected_material_ids": selected,
        "message": f"Selected batch job {job_id} recorded for {len(selected)} material id(s).",
        "stages": _job_stages(root_path, result, selected),
        "outputs": {
            "run_id": run.get("run_id"),
            "batch_id": run.get("batch_id"),
            "candidate_id": candidate.get("strategy_id") or candidate.get("candidate_id"),
            "candidate_name": candidate.get("name") or candidate.get("strategy_name"),
            "candidate_action": candidate.get("recommendation") or candidate.get("next_action") or "REVIEW_REQUIRED",
            "run_manifest_path": _relative(root_path, run.get("run_manifest_path")),
            "batch_manifest_path": _relative(root_path, run.get("batch_manifest_path")),
            "current_run_candidate_path": _relative(root_path, (run.get("generated_artifacts") or {}).get("current_run_candidate")),
            "current_run_report_path": _relative(root_path, (run.get("generated_artifacts") or {}).get("current_run_report")),
            "research_cards": [],
            "test_specs": [],
            "evidence_reports": [],
            "candidate_registry_updates": [],
            "ml_gate_outputs": [],
            "missing_evidence": [],
        },
        "warnings": [],
        "errors": [] if result.get("ok") else [str(result.get("error") or "Strategy Factory selected batch failed.")],
        "safety": {
            "live_trading": False,
            "brokerage_execution": False,
            "nav_pnl_mutation": False,
            "approved_plan_created": False,
            "paper_apply_created": False,
        },
    }
    path = strategy_factory_job_path(root_path, job_id)
    _atomic_write_json(path, artifact)
    factory = base_state(root_path)
    factory["latest_selected_batch_job"] = artifact
    return {
        "ok": True,
        "status": artifact["status"],
        "source": SOURCE,
        "job_id": job_id,
        "selected_material_count": len(selected),
        "message": artifact["message"],
        "artifact_path": _relative(root_path, path),
        "job": artifact,
        "factory": factory,
    }
