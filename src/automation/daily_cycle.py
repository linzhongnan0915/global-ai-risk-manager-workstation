"""Daily automation cycle for lightweight intelligence artifacts.

The cycle writes automation artifacts only. It does not create review drafts,
approved plans, paper rebalance plans, orders, NAV/P&L rows, or ledger records.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.automation.allocation_recommendation_artifact import (
    allocation_recommendation_artifact_path,
    read_latest_allocation_recommendation_artifact,
    write_allocation_recommendation_artifact,
)
from src.automation.daily_recommendation_artifact import (
    daily_recommendation_artifact_path,
    read_latest_daily_recommendation_artifact,
    write_daily_recommendation_artifact,
)
from src.automation.review_draft_eligibility import build_review_draft_eligibility


SOURCE = "daily_automation_cycle_v0"
ARTIFACT_DIR = Path("data/automation/daily_cycle")


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


def daily_cycle_artifact_dir(root: str | Path) -> Path:
    return Path(root) / ARTIFACT_DIR


def daily_cycle_artifact_path(root: str | Path, as_of_date: str) -> Path:
    return daily_cycle_artifact_dir(root) / f"{as_of_date}.json"


def latest_daily_cycle_artifact_path(root: str | Path) -> Path | None:
    folder = daily_cycle_artifact_dir(root)
    if not folder.exists():
        return None
    paths = sorted(folder.glob("*.json"), key=lambda path: (path.name, path.stat().st_mtime), reverse=True)
    return paths[0] if paths else None


def read_latest_daily_cycle_status(root: str | Path) -> dict[str, Any]:
    root_path = Path(root)
    path = latest_daily_cycle_artifact_path(root_path)
    if path is None:
        return {
            "ok": False,
            "status": "MISSING_ARTIFACT",
            "source": SOURCE,
            "artifact_path": None,
            "daily_cycle": {
                "status": "MISSING_ARTIFACT",
                "as_of_date": None,
                "last_run_at": None,
                "daily_recommendation_status": "MISSING_ARTIFACT",
                "allocation_recommendation_status": "MISSING_ARTIFACT",
                "review_draft_eligibility_status": "MISSING_ARTIFACT",
                "errors": [],
                "warnings": ["Daily automation cycle has not run yet."],
            },
            "paper_shadow_only": True,
            "financial_state_mutated": False,
        }
    payload = _read_json(path, {})
    if not isinstance(payload, dict) or payload.get("source") != SOURCE:
        return {
            "ok": False,
            "status": "FAILED",
            "source": SOURCE,
            "artifact_path": _relative(root_path, path),
            "daily_cycle": {
                "status": "FAILED",
                "as_of_date": None,
                "last_run_at": None,
                "daily_recommendation_status": "MISSING_ARTIFACT",
                "allocation_recommendation_status": "MISSING_ARTIFACT",
                "review_draft_eligibility_status": "MISSING_ARTIFACT",
                "errors": ["Latest daily cycle artifact has an invalid source schema."],
                "warnings": [],
            },
            "paper_shadow_only": True,
            "financial_state_mutated": False,
        }
    return {
        "ok": True,
        "status": payload.get("daily_cycle", {}).get("status") or "AVAILABLE",
        "source": SOURCE,
        "artifact_path": _relative(root_path, path),
        "daily_cycle": payload.get("daily_cycle") or payload,
        "artifact": payload,
        "paper_shadow_only": True,
        "financial_state_mutated": False,
    }


def _artifact_available(path: Path, expected_source: str) -> bool:
    payload = _read_json(path, {})
    return isinstance(payload, dict) and payload.get("source") == expected_source


def _review_status(payload: dict[str, Any]) -> str:
    eligibility = payload.get("eligibility") or {}
    required = eligibility.get("required_conditions") or {}
    blocking = eligibility.get("blocking_conditions") if isinstance(eligibility.get("blocking_conditions"), list) else []
    if required.get("allocation_artifact_available") is False:
        return "MISSING_ARTIFACT"
    if eligibility.get("review_draft_generation_allowed") is True:
        return "AVAILABLE"
    if "MISSING_ML_OR_ATTRIBUTION_EVIDENCE" in blocking:
        return "REVIEW_REQUIRED"
    return "BLOCKED"


def run_daily_automation_cycle(
    root: str | Path,
    *,
    now: datetime | None = None,
    force: bool = False,
) -> dict[str, Any]:
    root_path = Path(root)
    generated_at = (now or datetime.now(timezone.utc)).isoformat()
    as_of_date = generated_at[:10]
    daily_path = daily_recommendation_artifact_path(root_path, as_of_date)
    allocation_path = allocation_recommendation_artifact_path(root_path, as_of_date)
    status_path = daily_cycle_artifact_path(root_path, as_of_date)
    errors: list[str] = []
    warnings: list[str] = []
    steps: list[dict[str, Any]] = []

    try:
        if force or not _artifact_available(daily_path, "daily_recommendation_artifact_v0"):
            daily_result = write_daily_recommendation_artifact(root_path, now=now)
            steps.append({"name": "daily_recommendation", "status": "GENERATED", "artifact_path": daily_result.get("artifact_path")})
        else:
            steps.append({"name": "daily_recommendation", "status": "SKIPPED_EXISTING", "artifact_path": _relative(root_path, daily_path)})
    except Exception as exc:
        errors.append(f"daily_recommendation_failed: {exc}")
        steps.append({"name": "daily_recommendation", "status": "FAILED", "artifact_path": _relative(root_path, daily_path)})

    try:
        if not errors and (force or not _artifact_available(allocation_path, "allocation_recommendation_artifact_v0")):
            allocation_result = write_allocation_recommendation_artifact(root_path, now=now)
            steps.append(
                {"name": "allocation_recommendation", "status": "GENERATED", "artifact_path": allocation_result.get("artifact_path")}
            )
        elif errors:
            steps.append({"name": "allocation_recommendation", "status": "SKIPPED_DAILY_FAILED", "artifact_path": _relative(root_path, allocation_path)})
        else:
            steps.append({"name": "allocation_recommendation", "status": "SKIPPED_EXISTING", "artifact_path": _relative(root_path, allocation_path)})
    except Exception as exc:
        errors.append(f"allocation_recommendation_failed: {exc}")
        steps.append({"name": "allocation_recommendation", "status": "FAILED", "artifact_path": _relative(root_path, allocation_path)})

    eligibility = build_review_draft_eligibility(root_path)
    review_status = _review_status(eligibility)
    steps.append(
        {
            "name": "review_draft_eligibility",
            "status": review_status,
            "artifact_path": eligibility.get("latest_allocation_artifact"),
        }
    )
    if eligibility.get("warnings"):
        warnings.extend(str(item) for item in eligibility.get("warnings") or [])

    try:
        from src.automation.automation_intelligence_manifest import build_automation_intelligence_manifest

        manifest = build_automation_intelligence_manifest(root_path, now=now)
        steps.append({"name": "automation_intelligence_manifest", "status": "READ", "artifact_path": None})
    except Exception as exc:
        manifest = None
        errors.append(f"automation_intelligence_manifest_failed: {exc}")
        steps.append({"name": "automation_intelligence_manifest", "status": "FAILED", "artifact_path": None})

    daily_latest = read_latest_daily_recommendation_artifact(root_path)
    allocation_latest = read_latest_allocation_recommendation_artifact(root_path)
    daily_status = "AVAILABLE" if daily_latest.get("ok") else daily_latest.get("status") or "MISSING_ARTIFACT"
    allocation_status = "AVAILABLE" if allocation_latest.get("ok") else allocation_latest.get("status") or "MISSING_ARTIFACT"
    if errors:
        status = "FAILED" if daily_status == "MISSING_ARTIFACT" else "PARTIAL"
    elif daily_status == "AVAILABLE" and allocation_status == "AVAILABLE" and review_status in {"AVAILABLE", "BLOCKED", "REVIEW_REQUIRED"}:
        status = "AVAILABLE"
    else:
        status = "PARTIAL"

    daily_cycle = {
        "status": status,
        "as_of_date": as_of_date,
        "last_run_at": generated_at,
        "daily_recommendation_status": daily_status,
        "allocation_recommendation_status": allocation_status,
        "review_draft_eligibility_status": review_status,
        "errors": errors,
        "warnings": warnings,
    }
    payload = {
        "ok": not errors,
        "source": SOURCE,
        "generated_at": generated_at,
        "paper_shadow_only": True,
        "financial_state_mutated": False,
        "review_draft_created": False,
        "approved_plan_created": False,
        "apply_performed": False,
        "force": bool(force),
        "daily_cycle": daily_cycle,
        "steps": steps,
        "review_draft_eligibility": eligibility,
        "manifest_summary": {
            "overall_status": (manifest or {}).get("operator_summary", {}).get("overall_status") if isinstance(manifest, dict) else None,
        },
    }
    _atomic_write_json(status_path, payload)
    return {
        "ok": not errors,
        "status": status,
        "source": SOURCE,
        "artifact_path": _relative(root_path, status_path),
        "daily_cycle": daily_cycle,
        "artifact": payload,
        "paper_shadow_only": True,
        "financial_state_mutated": False,
        "review_draft_created": False,
        "approved_plan_created": False,
        "apply_performed": False,
    }
