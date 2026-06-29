"""Strategy Factory evidence manifest V0.

This module reads existing Strategy Factory artifacts from alpha_research and
summarizes their lineage. It does not run research, train models, backtest, or
mutate financial state.
"""

from __future__ import annotations

import csv
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SOURCE = "strategy_factory_evidence_manifest_v0"
ALPHA_RESEARCH_ENV = "STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT"
CACHE_RELATIVE_PATH = Path("data/automation/strategy_factory_evidence/manifest.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _canonical_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _identity_from_row(row: dict[str, Any]) -> str | None:
    for key in ("strategy_uid", "candidate_id", "strategy_id", "idea_id", "research_card_id", "test_spec_id"):
        value = _canonical_text(row.get(key))
        if value:
            return value
    return None


def _normalize_identity(value: Any) -> str:
    text = str(value or "").upper()
    text = re.sub(r"(_RESEARCH_CARD|_TEST_SPEC|_DRAFT)$", "", text)
    text = re.sub(r"[^A-Z0-9]+", "_", text)
    return text.strip("_")


def _first_heading_id(path: Path) -> str | None:
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                return stripped.lstrip("#").strip() or None
    except OSError:
        return None
    return None


def _artifact_id(path: Path, suffix_pattern: str) -> str:
    heading = _first_heading_id(path)
    if heading:
        return heading
    return re.sub(suffix_pattern, "", path.stem, flags=re.IGNORECASE)


def _status_for_path(path: Path | None) -> str:
    return "AVAILABLE" if path and path.exists() else "MISSING_ARTIFACT"


def _source(kind: str, alpha: Path, path: Path | None, status: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "path": _relative(alpha, path) if path else None,
        "status": status,
    }


def _registry_rows(sf: Path) -> tuple[list[dict[str, Any]], list[Path]]:
    rows_by_id: dict[str, dict[str, Any]] = {}
    paths: list[Path] = []
    for path in sorted((sf / "candidate_results").glob("*candidate*registry*.json")):
        payload = _read_json(path, {})
        candidates = payload.get("candidates") if isinstance(payload, dict) else None
        if not isinstance(candidates, list):
            continue
        paths.append(path)
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            identity = _identity_from_row(candidate)
            if identity:
                rows_by_id.setdefault(_normalize_identity(identity), dict(candidate))
    csv_path = sf / "candidate_portfolio" / "candidate_portfolio_registry.csv"
    if csv_path.exists():
        paths.append(csv_path)
        try:
            with csv_path.open("r", encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    identity = _identity_from_row(row)
                    if identity:
                        rows_by_id.setdefault(_normalize_identity(identity), dict(row))
        except OSError:
            pass
    return list(rows_by_id.values()), paths


def _path_index(paths: list[Path], suffix_pattern: str) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for path in paths:
        artifact_id = _artifact_id(path, suffix_pattern)
        index.setdefault(_normalize_identity(artifact_id), path)
        index.setdefault(_normalize_identity(path.stem), path)
    return index


def _evidence_index(sf: Path) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for path in sorted((sf / "evidence_reports").glob("*/evidence_report.md")):
        identity = path.parent.name
        index.setdefault(_normalize_identity(identity), path)
    return index


def _missing_evidence_index(sf: Path) -> dict[str, list[Any]]:
    index: dict[str, list[Any]] = {}
    for path in sorted(sf.glob("**/missing_evidence.json")):
        payload = _read_json(path, [])
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            rows = payload.get("missing_evidence") or payload.get("items") or []
        else:
            rows = []
        if not isinstance(rows, list):
            rows = []
        identity = path.parent.name
        index.setdefault(_normalize_identity(identity), rows)
    return index


def _ml_index(alpha: Path) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for path in sorted(alpha.glob("**/ml_diagnostics_summary.json")) if alpha.exists() else []:
        for parent in path.parents:
            if parent == alpha.parent:
                break
            identity = _normalize_identity(parent.name)
            if identity:
                index.setdefault(identity, path)
    return index


def _missing_labels(rows: list[Any], candidate: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for row in rows:
        if isinstance(row, dict):
            label = row.get("missing_item") or row.get("field_name") or row.get("required_for")
            if label:
                labels.append(str(label))
        elif row is not None:
            labels.append(str(row))
    for value in candidate.get("blocked_by") or []:
        if value:
            labels.append(str(value))
    for value in candidate.get("key_limitations") or []:
        if value and "missing" in str(value).lower():
            labels.append(str(value))
    return list(dict.fromkeys(labels))


def _review_required(candidate: dict[str, Any], missing: list[str]) -> bool:
    decision = str(candidate.get("decision") or candidate.get("lifecycle_status") or "").upper()
    eligible = candidate.get("candidate_portfolio_eligible")
    if missing:
        return True
    if decision in {"WATCH_ONLY", "REJECTED", "BLOCKED_NEEDS_BOSS_API"}:
        return True
    if eligible is False:
        return True
    return False


def build_strategy_factory_evidence_manifest(
    root: str | Path,
    *,
    alpha_root: str | Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    alpha = Path(alpha_root) if alpha_root is not None else _alpha_root()
    generated_at = (now or datetime.now(timezone.utc)).isoformat()
    if not alpha.exists():
        warning = f"alpha_research folder is missing: {alpha}"
        return {
            "ok": False,
            "status": "MISSING_ARTIFACT",
            "source": SOURCE,
            "generated_at": generated_at,
            "paper_shadow_only": True,
            "financial_state_mutated": False,
            "alpha_research_root": str(alpha),
            "summary": {
                "candidate_count": None,
                "research_card_count": None,
                "test_spec_count": None,
                "evidence_report_count": None,
                "ml_gate_count": None,
                "missing_evidence_count": None,
                "review_required_count": None,
            },
            "items": [],
            "warnings": [warning],
        }
    sf = alpha / "strategy_factory"
    if not sf.exists():
        warning = f"strategy_factory folder is missing under alpha_research: {sf}"
        return {
            "ok": False,
            "status": "MISSING_ARTIFACT",
            "source": SOURCE,
            "generated_at": generated_at,
            "paper_shadow_only": True,
            "financial_state_mutated": False,
            "alpha_research_root": str(alpha),
            "summary": {
                "candidate_count": None,
                "research_card_count": None,
                "test_spec_count": None,
                "evidence_report_count": None,
                "ml_gate_count": None,
                "missing_evidence_count": None,
                "review_required_count": None,
            },
            "items": [],
            "warnings": [warning],
        }
    candidates, registry_paths = _registry_rows(sf)
    research_cards = sorted((sf / "research_cards").glob("*.md"))
    test_specs = sorted((sf / "codex_test_specs").glob("*.md"))
    evidence = _evidence_index(sf)
    missing_index = _missing_evidence_index(sf)
    ml = _ml_index(alpha)
    ml_artifact_count = len({path.resolve() for path in ml.values()})
    research_index = _path_index(research_cards, r"(_research_card|_research_card_draft)$")
    test_index = _path_index(test_specs, r"(_test_spec|_test_spec_draft)$")

    items: list[dict[str, Any]] = []
    for candidate in candidates:
        identity = _identity_from_row(candidate)
        if not identity:
            continue
        key = _normalize_identity(identity)
        strategy_uid = _canonical_text(candidate.get("strategy_uid") or candidate.get("strategy_id"))
        candidate_id = _canonical_text(candidate.get("candidate_id") or candidate.get("idea_id") or candidate.get("strategy_id"))
        material_hash = _canonical_text(candidate.get("material_hash") or candidate.get("source_material_hash"))
        research_path = research_index.get(key)
        test_path = test_index.get(key)
        evidence_path = evidence.get(key)
        ml_path = ml.get(key)
        missing_rows = missing_index.get(key, [])
        missing = _missing_labels(missing_rows, candidate)
        research_status = _status_for_path(research_path)
        test_status = _status_for_path(test_path)
        evidence_status = _status_for_path(evidence_path)
        ml_status = _status_for_path(ml_path)
        if missing:
            status = "MISSING_EVIDENCE"
        elif _review_required(candidate, missing):
            status = "REVIEW_REQUIRED"
        elif research_path or test_path or evidence_path or ml_path:
            status = "AVAILABLE"
        else:
            status = "NOT_AVAILABLE"
        source_artifacts = [
            *[_source("candidate_registry", alpha, path, "AVAILABLE") for path in registry_paths],
            _source("research_card", alpha, research_path, research_status),
            _source("test_spec", alpha, test_path, test_status),
            _source("evidence_report", alpha, evidence_path, evidence_status),
            _source("ml_gate", alpha, ml_path, ml_status),
        ]
        items.append(
            {
                "candidate_id": candidate_id,
                "strategy_uid": strategy_uid,
                "research_card_id": _artifact_id(research_path, r"(_research_card|_research_card_draft)$") if research_path else None,
                "test_spec_id": _artifact_id(test_path, r"(_test_spec|_test_spec_draft)$") if test_path else None,
                "material_hash": material_hash,
                "status": status,
                "research_card_status": research_status,
                "test_spec_status": test_status,
                "evidence_report_status": evidence_status,
                "ml_gate_status": ml_status,
                "missing_evidence": missing,
                "source_artifacts": source_artifacts,
            }
        )

    review_required_count = sum(item["status"] in {"REVIEW_REQUIRED", "MISSING_EVIDENCE"} for item in items)
    missing_evidence_count = sum(len(item["missing_evidence"]) for item in items)
    status = "AVAILABLE"
    warnings: list[str] = []
    if not registry_paths:
        status = "MISSING_ARTIFACT"
        warnings.append("No Strategy Factory candidate registry artifact was found.")
    elif review_required_count:
        status = "REVIEW_REQUIRED"
    return {
        "ok": True,
        "status": status,
        "source": SOURCE,
        "generated_at": generated_at,
        "paper_shadow_only": True,
        "financial_state_mutated": False,
        "alpha_research_root": str(alpha),
        "cache_artifact_path": _relative(root_path, root_path / CACHE_RELATIVE_PATH),
        "summary": {
            "candidate_count": len(items),
            "research_card_count": len(research_cards),
            "test_spec_count": len(test_specs),
            "evidence_report_count": len(evidence),
            "ml_gate_count": ml_artifact_count,
            "missing_evidence_count": missing_evidence_count,
            "review_required_count": review_required_count,
        },
        "items": items,
        "warnings": warnings,
    }


def write_strategy_factory_evidence_manifest(
    root: str | Path,
    *,
    alpha_root: str | Path | None = None,
    now: datetime | None = None,
) -> Path:
    root_path = Path(root)
    payload = build_strategy_factory_evidence_manifest(root_path, alpha_root=alpha_root, now=now)
    path = root_path / CACHE_RELATIVE_PATH
    _atomic_write_json(path, payload)
    return path


def lineage_by_identity(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in manifest.get("items") or []:
        if not isinstance(item, dict):
            continue
        for key in (item.get("strategy_uid"), item.get("candidate_id"), item.get("research_card_id"), item.get("test_spec_id")):
            if key:
                result.setdefault(_normalize_identity(key), item)
    return result


def research_lineage_for_identity(manifest: dict[str, Any], *identities: Any) -> dict[str, Any]:
    index = lineage_by_identity(manifest)
    match = None
    for identity in identities:
        normalized = _normalize_identity(identity)
        if normalized in index:
            match = index[normalized]
            break
    if not match:
        manifest_status = manifest.get("status")
        status = "MISSING_ARTIFACT" if manifest_status == "MISSING_ARTIFACT" else "NOT_AVAILABLE"
        return {
            "status": status,
            "candidate_id": None,
            "research_card_id": None,
            "test_spec_id": None,
            "evidence_report_status": "NOT_AVAILABLE",
            "ml_gate_status": "NOT_AVAILABLE",
            "missing_evidence": [],
            "source_artifacts": [],
        }
    return {
        "status": match.get("status") or "NOT_AVAILABLE",
        "candidate_id": match.get("candidate_id"),
        "research_card_id": match.get("research_card_id"),
        "test_spec_id": match.get("test_spec_id"),
        "evidence_report_status": match.get("evidence_report_status") or "NOT_AVAILABLE",
        "ml_gate_status": match.get("ml_gate_status") or "NOT_AVAILABLE",
        "missing_evidence": match.get("missing_evidence") if isinstance(match.get("missing_evidence"), list) else [],
        "source_artifacts": match.get("source_artifacts") if isinstance(match.get("source_artifacts"), list) else [],
    }
