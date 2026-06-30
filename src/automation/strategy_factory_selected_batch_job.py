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
MISSING_LABELS = {
    "research_card": ["Prototype Only"],
    "test_spec": ["Prototype Only"],
    "evidence_report": [
        "Prototype Only",
        "Missing Attribution",
        "Missing Regime Evidence",
    ],
    "backtest_output": ["Prototype Only"],
    "ml_gate_output": ["Prototype Only", "Missing ML Evidence"],
    "robustness_output": ["Prototype Only", "Missing Robustness Evidence"],
    "candidate_registry_update": ["Prototype Only", "Institutional Validation Pending"],
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


def _relative(root: Path, path: Path | str | None) -> str | None:
    if not path:
        return None
    if isinstance(path, (list, tuple)):
        path = _first_artifact_path(path)
        if not path:
            return None
    path_obj = Path(path)
    try:
        return path_obj.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return str(path).replace("\\", "/")


def _path_exists(root: Path, path: Path | str | None) -> bool:
    if not path:
        return False
    if isinstance(path, (list, tuple)):
        path = _first_artifact_path(path)
        if not path:
            return False
    path_obj = Path(path)
    if not path_obj.is_absolute():
        path_obj = root / path_obj
    try:
        return path_obj.exists()
    except OSError:
        return False


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _first_artifact_path(value: Any) -> Any:
    values = _as_list(value)
    return values[0] if values else None


def _artifact_paths(generated: dict[str, Any], *keys: str) -> list[Any]:
    paths: list[Any] = []
    for key in keys:
        paths.extend(_as_list(generated.get(key)))
    return [path for path in paths if path]


def _material_records(run: dict[str, Any], selected_material_ids: list[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for source in (
        run.get("selected_materials"),
        (run.get("batch_manifest") or {}).get("selected_materials"),
        (run.get("run_manifest") or {}).get("selected_materials"),
    ):
        if isinstance(source, list):
            records.extend(row for row in source if isinstance(row, dict))
    by_id: dict[str, dict[str, Any]] = {
        str(row.get("material_id")): row for row in records if row.get("material_id")
    }
    return [
        {
            "material_id": material_id,
            "material_hash": (
                by_id.get(material_id, {}).get("material_hash")
                or by_id.get(material_id, {}).get("source_material_hash")
                or by_id.get(material_id, {}).get("hash")
            ),
        }
        for material_id in selected_material_ids
    ]


def _material_hashes(materials: list[dict[str, Any]]) -> list[str]:
    return [str(row["material_hash"]) for row in materials if row.get("material_hash")]


def _material_id_for_path(path: Any, selected_material_ids: list[str]) -> str | None:
    text = str(path or "")
    matches = [material_id for material_id in selected_material_ids if material_id and material_id in text]
    return matches[0] if len(matches) == 1 else None


def _stage_lookup(stages: list[dict[str, Any]], stage_name: str) -> dict[str, Any] | None:
    return next((stage for stage in stages if stage.get("stage") == stage_name), None)


def _candidate_id(candidate: dict[str, Any]) -> Any:
    return candidate.get("candidate_id") or candidate.get("strategy_id") or candidate.get("idea_id")


def _strategy_uid(candidate: dict[str, Any]) -> Any:
    return candidate.get("strategy_uid") or candidate.get("strategy_id")


def _lineage_item(
    root: Path,
    *,
    artifact_type: str,
    artifact_path: Any = None,
    material_id: str | None = None,
    material_ids: list[str] | None = None,
    candidate_id: Any = None,
    strategy_uid: Any = None,
    status: str | None = None,
    missing_reason: str | None = None,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    exists = _path_exists(root, artifact_path)
    resolved_status = status or ("AVAILABLE" if exists else "MISSING_ARTIFACT")
    resolved_missing = missing_reason
    if not exists and not resolved_missing:
        resolved_missing = f"{artifact_type} artifact was not emitted by the selected-batch run."
    item = {
        "artifact_type": artifact_type,
        "artifact_path": _relative(root, artifact_path),
        "exists": exists,
        "material_id": material_id,
        "material_ids": material_ids or ([material_id] if material_id else []),
        "strategy_uid": strategy_uid,
        "candidate_id": candidate_id,
        "status": resolved_status,
        "missing_reason": None if exists else resolved_missing,
        "labels": labels or (["Prototype Only"] if exists else MISSING_LABELS.get(artifact_type, ["Prototype Only"])),
    }
    return item


def _material_output_items(
    root: Path,
    *,
    artifact_type: str,
    paths: list[Any],
    selected_material_ids: list[str],
    candidate_id: Any,
    strategy_uid: Any,
) -> list[dict[str, Any]]:
    if paths:
        return [
            _lineage_item(
                root,
                artifact_type=artifact_type,
                artifact_path=path,
                material_id=_material_id_for_path(path, selected_material_ids),
                material_ids=[_material_id_for_path(path, selected_material_ids)] if _material_id_for_path(path, selected_material_ids) else selected_material_ids,
                candidate_id=candidate_id,
                strategy_uid=strategy_uid,
                labels=["Prototype Only"],
            )
            for path in paths
        ]
    return [
        _lineage_item(
            root,
            artifact_type=artifact_type,
            material_id=material_id,
            candidate_id=candidate_id,
            strategy_uid=strategy_uid,
            status="MISSING_ARTIFACT",
            labels=MISSING_LABELS[artifact_type],
        )
        for material_id in selected_material_ids
    ]


def _stage_output_item(
    root: Path,
    *,
    artifact_type: str,
    stage: dict[str, Any] | None,
    artifact_path: Any = None,
    selected_material_ids: list[str],
    candidate_id: Any,
    strategy_uid: Any,
) -> dict[str, Any]:
    path = artifact_path or (stage or {}).get("artifact_path")
    status = str((stage or {}).get("status") or ("AVAILABLE" if _path_exists(root, path) else "MISSING_ARTIFACT"))
    reason = (stage or {}).get("reason")
    if not _path_exists(root, path) and not reason:
        reason = f"{artifact_type} artifact is not available for this selected-batch job."
    return _lineage_item(
        root,
        artifact_type=artifact_type,
        artifact_path=path,
        material_ids=selected_material_ids,
        candidate_id=candidate_id,
        strategy_uid=strategy_uid,
        status=status,
        missing_reason=None if _path_exists(root, path) else str(reason),
        labels=["Prototype Only"] if _path_exists(root, path) else MISSING_LABELS.get(artifact_type, ["Prototype Only"]),
    )


def _job_outputs(
    root: Path,
    *,
    run: dict[str, Any],
    candidate: dict[str, Any],
    stages: list[dict[str, Any]],
    selected_material_ids: list[str],
) -> dict[str, Any]:
    generated = (run.get("generated_artifacts") or {}) if isinstance(run, dict) else {}
    candidate_id = _candidate_id(candidate)
    strategy_uid = _strategy_uid(candidate)
    run_candidate_path = generated.get("current_run_candidate") or (candidate.get("current_run") or {}).get("current_run_candidate_path")
    run_report_path = generated.get("current_run_report") or generated.get("evidence_report")
    return {
        "run_id": run.get("run_id"),
        "batch_id": run.get("batch_id"),
        "candidate_id": candidate_id,
        "candidate_name": candidate.get("name") or candidate.get("strategy_name"),
        "candidate_action": candidate.get("recommendation") or candidate.get("next_action") or "REVIEW_REQUIRED",
        "run_manifest_path": _relative(root, run.get("run_manifest_path")),
        "batch_manifest_path": _relative(root, run.get("batch_manifest_path")),
        "current_run_candidate_path": _relative(root, run_candidate_path),
        "current_run_report_path": _relative(root, run_report_path),
        "research_cards": _material_output_items(
            root,
            artifact_type="research_card",
            paths=_artifact_paths(generated, "research_cards", "research_card"),
            selected_material_ids=selected_material_ids,
            candidate_id=candidate_id,
            strategy_uid=strategy_uid,
        ),
        "test_specs": _material_output_items(
            root,
            artifact_type="test_spec",
            paths=_artifact_paths(generated, "test_specs", "test_spec"),
            selected_material_ids=selected_material_ids,
            candidate_id=candidate_id,
            strategy_uid=strategy_uid,
        ),
        "evidence_reports": [
            _stage_output_item(
                root,
                artifact_type="evidence_report",
                stage=_stage_lookup(stages, "evidence_report"),
                artifact_path=run_report_path,
                selected_material_ids=selected_material_ids,
                candidate_id=candidate_id,
                strategy_uid=strategy_uid,
            )
        ],
        "backtest_outputs": [
            _stage_output_item(
                root,
                artifact_type="backtest_output",
                stage=_stage_lookup(stages, "backtest"),
                artifact_path=generated.get("backtest_output") or generated.get("backtest_outputs"),
                selected_material_ids=selected_material_ids,
                candidate_id=candidate_id,
                strategy_uid=strategy_uid,
            )
        ],
        "ml_gate_outputs": [
            _stage_output_item(
                root,
                artifact_type="ml_gate_output",
                stage=_stage_lookup(stages, "ml_gate"),
                artifact_path=generated.get("ml_gate_output") or generated.get("ml_gate_outputs"),
                selected_material_ids=selected_material_ids,
                candidate_id=candidate_id,
                strategy_uid=strategy_uid,
            )
        ],
        "robustness_outputs": [
            _stage_output_item(
                root,
                artifact_type="robustness_output",
                stage=_stage_lookup(stages, "robustness"),
                artifact_path=generated.get("robustness_output") or generated.get("robustness_outputs"),
                selected_material_ids=selected_material_ids,
                candidate_id=candidate_id,
                strategy_uid=strategy_uid,
            )
        ],
        "candidate_registry_updates": [
            _stage_output_item(
                root,
                artifact_type="candidate_registry_update",
                stage=_stage_lookup(stages, "candidate_registry_update"),
                artifact_path=run_candidate_path,
                selected_material_ids=selected_material_ids,
                candidate_id=candidate_id,
                strategy_uid=strategy_uid,
            )
        ],
        "missing_evidence": [],
    }


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
            status = "COMPLETE" if raw_status in {"COMPLETED", "COMPLETE"} else raw_status if raw_status in {"BLOCKED", "FAILED", "NOT_WIRED"} else "NOT_WIRED"
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
    selected_from_run = [str(item).strip() for item in run.get("selected_material_ids") or selected if str(item).strip()]
    material_lineage = _material_records(run, selected_from_run)
    stages = _job_stages(root_path, result, selected)
    outputs = _job_outputs(
        root_path,
        run=run,
        candidate=candidate,
        stages=stages,
        selected_material_ids=selected_from_run,
    )
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
        "selected_material_count": len(selected_from_run),
        "selected_material_ids": selected_from_run,
        "selected_material_hashes": _material_hashes(material_lineage),
        "selected_materials": material_lineage,
        "selection_source": (run.get("batch_manifest") or {}).get("source") or run.get("selection_source") or "selected_batch_request",
        "message": f"Selected batch job {job_id} recorded for {len(selected_from_run)} material id(s).",
        "stages": stages,
        "outputs": outputs,
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
