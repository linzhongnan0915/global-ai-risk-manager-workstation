"""Black-box decomposition manifest V0.

Scans existing research and diagnostic artifacts for decomposition evidence.
It never trains models, runs backtests, creates attribution, or mutates
financial state.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.automation.candidate_strategy_identity_bridge import build_candidate_strategy_identity_bridge
from src.automation.ml_intelligence_patch_manifest import build_ml_intelligence_patch_manifest
from src.automation.strategy_factory_evidence_manifest import build_strategy_factory_evidence_manifest


SOURCE = "blackbox_decomposition_manifest_v0"
CACHE_RELATIVE_PATH = Path("data/automation/blackbox_decomposition/manifest.json")
ALPHA_RESEARCH_ENV = "STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT"


def _alpha_root() -> Path:
    configured = os.environ.get(ALPHA_RESEARCH_ENV)
    return Path(configured) if configured else Path(r"D:\Global_Ai\alpha_research")


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except (OSError, json.JSONDecodeError):
        return default


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


def _identity_values(item: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("strategy_uid", "candidate_id", "research_card_id", "test_spec_id", "material_hash"):
        normalized = _normalize_identity(item.get(key))
        if normalized:
            values.append(normalized)
    return list(dict.fromkeys(values))


def _empty_checklist() -> dict[str, bool]:
    return {
        "long_short_attribution_available": False,
        "factor_exposure_available": False,
        "sector_exposure_available": False,
        "beta_exposure_available": False,
        "liquidity_capacity_available": False,
        "regime_performance_available": False,
        "cost_sensitivity_available": False,
        "signal_bucket_available": False,
        "feature_group_available": False,
        "failure_periods_available": False,
    }


def _source(kind: str, alpha: Path, path: Path, status: str = "AVAILABLE") -> dict[str, Any]:
    return {"kind": kind, "path": _relative(alpha, path), "status": status}


def _artifact_kind(path: Path) -> str | None:
    text = "/".join(path.parts[-4:]).lower()
    name = path.name.lower()
    if "missing_evidence" in name:
        return "missing_evidence"
    if "long_short" in text or "leg_attribution" in text or "long_short_attribution" in text:
        return "long_short_attribution"
    if "attribution" in text or "decomposition" in text:
        return "attribution_decomposition"
    if "factor_exposure" in text or "factor_robustness" in text or "factor_ic" in text:
        return "factor_exposure"
    if "sector_exposure" in text or "sector_neutral" in text:
        return "sector_exposure"
    if "beta" in text or "correlation" in text or "risk_exposure" in text:
        return "beta_exposure"
    if "liquidity" in text or "capacity" in text:
        return "liquidity_capacity"
    if "regime" in text:
        return "regime_performance"
    if "cost_sensitivity" in text or "cost_capacity" in text:
        return "cost_sensitivity"
    if "signal_bucket" in text or "bucket" in text:
        return "signal_bucket"
    if "feature_importance" in text or "feature_group" in text or "feature_ic" in text:
        return "feature_group"
    if "failure_period" in text or "worst_days" in text or "drawdown_period" in text:
        return "failure_periods"
    return None


def _artifact_paths(alpha: Path, identities: list[str] | None = None) -> list[Path]:
    if not alpha.exists():
        return []
    extensions = {".csv", ".json", ".md", ".txt", ".yaml", ".yml"}
    paths: list[Path] = []
    roots: list[Path] = []
    for identity in identities or []:
        for base in (
            alpha / "experiments" / identity,
            alpha / "strategy_factory" / "evidence_reports" / identity,
            alpha / "strategy_factory" / "research_cards",
            alpha / "strategy_factory" / "codex_test_specs",
        ):
            if base.exists():
                roots.append(base)
    if not roots:
        roots = [alpha / "experiments", alpha / "strategy_factory"]
    for root in sorted({path.resolve(): path for path in roots if path.exists()}.values(), key=lambda value: value.as_posix()):
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in extensions:
                continue
            if _artifact_kind(path):
                paths.append(path)
    return sorted({path.resolve(): path for path in paths}.values(), key=lambda value: value.as_posix())


def _identity_matches_path(identity: str, path: Path) -> bool:
    if not identity:
        return False
    path_parts = [_normalize_identity(part) for part in path.parts]
    stem = _normalize_identity(path.stem)
    return identity in path_parts or identity == stem or stem.startswith(f"{identity}_") or stem.endswith(f"_{identity}")


def _paths_for_item(paths: list[Path], item: dict[str, Any]) -> list[Path]:
    identities = _identity_values(item)
    if not identities:
        return []
    result = []
    for path in paths:
        if any(_identity_matches_path(identity, path) for identity in identities):
            result.append(path)
    return result


def _missing_from_artifact(path: Path) -> list[str]:
    payload = _read_json(path, [])
    rows = []
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("missing_evidence") or payload.get("items") or []
    labels: list[str] = []
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                label = row.get("missing_item") or row.get("field_name") or row.get("required_for") or row.get("reason")
            else:
                label = row
            if label:
                labels.append(str(label))
    return list(dict.fromkeys(labels))


def _edge_summary(factory_item: dict[str, Any]) -> dict[str, bool]:
    evidence_text = json.dumps(factory_item.get("source_artifacts") or [], default=str).lower()
    missing_text = json.dumps(factory_item.get("missing_evidence") or [], default=str).lower()
    return {
        "edge_thesis_available": "research_card" in evidence_text or "evidence_report" in evidence_text,
        "economic_mechanism_available": "evidence_report" in evidence_text,
        "return_source_available": "return_source" in evidence_text or "attribution" in evidence_text,
        "failure_mode_available": "failure" in evidence_text or "failure" in missing_text,
        "causal_proof_claimed": False,
    }


def _risk_flags(checklist: dict[str, bool], ml_item: dict[str, Any] | None) -> dict[str, Any]:
    ml_risk = ml_item.get("risk_flags") if isinstance(ml_item, dict) else {}
    overfit = ml_risk.get("overfit_risk") if isinstance(ml_risk, dict) else None
    return {
        "factor_disguised_alpha_risk": None if checklist["factor_exposure_available"] else True,
        "sector_concentration_risk": None if checklist["sector_exposure_available"] else True,
        "liquidity_risk": None if checklist["liquidity_capacity_available"] else True,
        "cost_fragility_risk": None if checklist["cost_sensitivity_available"] else True,
        "regime_fragility_risk": None if checklist["regime_performance_available"] else True,
        "overfit_or_data_mining_risk": overfit,
    }


def _status(checklist: dict[str, bool], missing: list[str], review_required: bool) -> str:
    available_count = sum(bool(value) for value in checklist.values())
    if review_required:
        return "REVIEW_REQUIRED"
    if missing and not available_count:
        return "MISSING_DECOMPOSITION_EVIDENCE"
    if available_count >= len(checklist):
        return "AVAILABLE"
    if available_count:
        return "PARTIAL"
    return "MISSING_DECOMPOSITION_EVIDENCE"


def _ml_index(ml_manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in ml_manifest.get("items") or []:
        if not isinstance(item, dict):
            continue
        for identity in _identity_values(item):
            result.setdefault(identity, item)
    return result


def _bridge_match_index(identity_bridge: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for match in identity_bridge.get("matches") or []:
        if not isinstance(match, dict):
            continue
        for identity in _identity_values(match):
            result.setdefault(identity, match)
    return result


def _decomposition_item(alpha: Path, factory_item: dict[str, Any], paths: list[Path], ml_item: dict[str, Any] | None) -> dict[str, Any]:
    item_paths = _paths_for_item(paths, factory_item)
    checklist = _empty_checklist()
    source_artifacts: list[dict[str, Any]] = []
    missing: list[str] = list(factory_item.get("missing_evidence") or [])
    review_required = False
    for path in item_paths:
        kind = _artifact_kind(path)
        if not kind:
            continue
        if kind == "missing_evidence":
            missing.extend(_missing_from_artifact(path))
            source_artifacts.append(_source(kind, alpha, path))
            continue
        if kind == "long_short_attribution":
            checklist["long_short_attribution_available"] = True
        elif kind == "attribution_decomposition":
            checklist["long_short_attribution_available"] = True
            review_required = True
            source_artifacts.append(_source(kind, alpha, path, "REVIEW_REQUIRED"))
            continue
        elif kind == "factor_exposure":
            checklist["factor_exposure_available"] = True
        elif kind == "sector_exposure":
            checklist["sector_exposure_available"] = True
        elif kind == "beta_exposure":
            checklist["beta_exposure_available"] = True
        elif kind == "liquidity_capacity":
            checklist["liquidity_capacity_available"] = True
        elif kind == "regime_performance":
            checklist["regime_performance_available"] = True
        elif kind == "cost_sensitivity":
            checklist["cost_sensitivity_available"] = True
        elif kind == "signal_bucket":
            checklist["signal_bucket_available"] = True
        elif kind == "feature_group":
            checklist["feature_group_available"] = True
        elif kind == "failure_periods":
            checklist["failure_periods_available"] = True
        source_artifacts.append(_source(kind, alpha, path))
    missing = list(dict.fromkeys(str(value) for value in missing if value))
    status = _status(checklist, missing, review_required)
    return {
        "candidate_id": factory_item.get("candidate_id"),
        "strategy_uid": factory_item.get("strategy_uid"),
        "research_card_id": factory_item.get("research_card_id"),
        "test_spec_id": factory_item.get("test_spec_id"),
        "material_hash": factory_item.get("material_hash"),
        "decomposition_status": status,
        "evidence_checklist": checklist,
        "edge_summary": _edge_summary(factory_item),
        "risk_flags": _risk_flags(checklist, ml_item),
        "missing_evidence": missing or ["Black-box decomposition evidence artifacts are missing."],
        "source_artifacts": source_artifacts,
    }


def build_blackbox_decomposition_manifest(
    root: str | Path,
    *,
    alpha_root: str | Path | None = None,
    strategy_cards: list[dict[str, Any]] | None = None,
    factory_manifest: dict[str, Any] | None = None,
    ml_patch_manifest: dict[str, Any] | None = None,
    identity_bridge: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    alpha = Path(alpha_root) if alpha_root is not None else _alpha_root()
    generated_at = (now or datetime.now(timezone.utc)).isoformat()
    factory = factory_manifest or build_strategy_factory_evidence_manifest(root_path, alpha_root=alpha, now=now)
    ml_patch = ml_patch_manifest or build_ml_intelligence_patch_manifest(root_path, alpha_root=alpha, factory_manifest=factory, now=now)
    bridge = identity_bridge or build_candidate_strategy_identity_bridge(
        root_path,
        alpha_root=alpha,
        strategy_cards=strategy_cards or [],
        factory_manifest=factory,
        ml_patch_manifest=ml_patch,
        now=now,
    )
    if factory.get("status") == "MISSING_ARTIFACT":
        warnings = factory.get("warnings") if isinstance(factory.get("warnings"), list) else []
        return {
            "ok": False,
            "status": "MISSING_DECOMPOSITION_EVIDENCE",
            "source": SOURCE,
            "generated_at": generated_at,
            "paper_shadow_only": True,
            "financial_state_mutated": False,
            "ml_training_performed": False,
            "heavy_backtest_performed": False,
            "summary": {
                "candidate_count": None,
                "strategy_card_match_count": None,
                "decomposition_available_count": None,
                "missing_decomposition_count": None,
                "long_short_attribution_count": None,
                "factor_exposure_count": None,
                "sector_exposure_count": None,
                "regime_evidence_count": None,
                "cost_sensitivity_count": None,
                "signal_bucket_count": None,
                "feature_importance_count": None,
                "review_required_count": None,
            },
            "items": [],
            "warnings": warnings,
        }
    factory_items = [item for item in factory.get("items") or [] if isinstance(item, dict)]
    scan_identities = sorted({identity for item in factory_items for identity in _identity_values(item)})
    paths = _artifact_paths(alpha, scan_identities)
    ml_by_identity = _ml_index(ml_patch)
    bridge_by_identity = _bridge_match_index(bridge)
    items: list[dict[str, Any]] = []
    for factory_item in factory_items:
        ml_item = None
        for identity in _identity_values(factory_item):
            if identity in ml_by_identity:
                ml_item = ml_by_identity[identity]
                break
        item = _decomposition_item(alpha, factory_item, paths, ml_item)
        item["strategy_card_match_status"] = "MATCHED" if any(identity in bridge_by_identity for identity in _identity_values(factory_item)) else "NOT_MATCHED"
        items.append(item)
    available_count = sum(item["decomposition_status"] == "AVAILABLE" for item in items)
    partial_count = sum(item["decomposition_status"] == "PARTIAL" for item in items)
    review_count = sum(item["decomposition_status"] == "REVIEW_REQUIRED" for item in items)
    missing_count = sum(item["decomposition_status"] == "MISSING_DECOMPOSITION_EVIDENCE" for item in items)
    checklist_counts = {
        key: sum(bool((item.get("evidence_checklist") or {}).get(key)) for item in items)
        for key in _empty_checklist()
    }
    strategy_card_match_count = sum(item.get("strategy_card_match_status") == "MATCHED" for item in items)
    if available_count:
        status = "AVAILABLE" if not (partial_count or missing_count or review_count) else "PARTIAL"
    elif partial_count:
        status = "PARTIAL"
    elif review_count:
        status = "REVIEW_REQUIRED"
    else:
        status = "MISSING_DECOMPOSITION_EVIDENCE"
    return {
        "ok": True,
        "status": status,
        "source": SOURCE,
        "generated_at": generated_at,
        "paper_shadow_only": True,
        "financial_state_mutated": False,
        "ml_training_performed": False,
        "heavy_backtest_performed": False,
        "summary": {
            "candidate_count": len(items),
            "strategy_card_match_count": strategy_card_match_count,
            "decomposition_available_count": available_count + partial_count,
            "missing_decomposition_count": missing_count,
            "long_short_attribution_count": checklist_counts["long_short_attribution_available"],
            "factor_exposure_count": checklist_counts["factor_exposure_available"],
            "sector_exposure_count": checklist_counts["sector_exposure_available"],
            "regime_evidence_count": checklist_counts["regime_performance_available"],
            "cost_sensitivity_count": checklist_counts["cost_sensitivity_available"],
            "signal_bucket_count": checklist_counts["signal_bucket_available"],
            "feature_importance_count": checklist_counts["feature_group_available"],
            "review_required_count": review_count,
        },
        "items": items,
        "warnings": [],
    }


def write_blackbox_decomposition_manifest(
    root: str | Path,
    *,
    alpha_root: str | Path | None = None,
    strategy_cards: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> Path:
    root_path = Path(root)
    payload = build_blackbox_decomposition_manifest(root_path, alpha_root=alpha_root, strategy_cards=strategy_cards, now=now)
    path = root_path / CACHE_RELATIVE_PATH
    _atomic_write_json(path, payload)
    return path


def blackbox_decomposition_by_identity(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in manifest.get("items") or []:
        if not isinstance(item, dict):
            continue
        for identity in _identity_values(item):
            result.setdefault(identity, item)
    return result


def blackbox_decomposition_for_identity(manifest: dict[str, Any], *identities: Any) -> dict[str, Any]:
    index = blackbox_decomposition_by_identity(manifest)
    match = None
    for identity in identities:
        normalized = _normalize_identity(identity)
        if normalized in index:
            match = index[normalized]
            break
    if not match:
        return {
            "status": "NOT_AVAILABLE",
            "evidence_checklist": {},
            "edge_summary": {},
            "risk_flags": {},
            "missing_evidence": ["No canonical decomposition evidence match."],
            "source_artifacts": [],
        }
    return {
        "status": match.get("decomposition_status") or "NOT_AVAILABLE",
        "evidence_checklist": match.get("evidence_checklist") if isinstance(match.get("evidence_checklist"), dict) else {},
        "edge_summary": match.get("edge_summary") if isinstance(match.get("edge_summary"), dict) else {},
        "risk_flags": match.get("risk_flags") if isinstance(match.get("risk_flags"), dict) else {},
        "missing_evidence": match.get("missing_evidence") if isinstance(match.get("missing_evidence"), list) else [],
        "source_artifacts": match.get("source_artifacts") if isinstance(match.get("source_artifacts"), list) else [],
    }
