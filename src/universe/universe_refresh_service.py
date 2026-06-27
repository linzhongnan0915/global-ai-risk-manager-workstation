"""Refresh and API payload helpers for universe artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.universe.point_in_time import POINT_IN_TIME_STATUS, get_universe_members
from src.universe.providers import UniverseDataProvider
from src.universe.quality_report import summarize_snapshot_for_api
from src.universe.universe_builder import DEFAULT_UNIVERSE_OUTPUT_DIR, UniverseBuilder


def refresh_universe_artifacts(
    root: str | Path = ".",
    *,
    as_of_date: str | None = None,
    provider: UniverseDataProvider | None = None,
    output_dir: str | Path | None = None,
    universe_names: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    result = UniverseBuilder(
        root=root,
        provider=provider,
        output_dir=output_dir,
        universe_names=universe_names,
    ).build(as_of_date=as_of_date)
    return {
        "ok": True,
        "snapshot": result.snapshot_payload,
        "quality": result.quality_report,
        "output_paths": result.output_paths,
    }


def load_universe_snapshot(root: str | Path = ".") -> dict[str, Any]:
    path = Path(root) / DEFAULT_UNIVERSE_OUTPUT_DIR / "current_universe_snapshot.json"
    if not path.exists():
        return _unavailable_payload("current_universe_snapshot.json is unavailable")
    return json.loads(path.read_text(encoding="utf-8"))


def load_universe_quality(root: str | Path = ".") -> dict[str, Any]:
    path = Path(root) / DEFAULT_UNIVERSE_OUTPUT_DIR / "universe_quality_report.json"
    if not path.exists():
        return {
            "ok": True,
            "schema_version": "universe_quality_report_v1",
            "provider_status": {"status": "UNAVAILABLE"},
            "warnings": ["universe_quality_report.json is unavailable"],
            "point_in_time_status": POINT_IN_TIME_STATUS,
        }
    return json.loads(path.read_text(encoding="utf-8"))


def universe_summary_payload(root: str | Path = ".") -> dict[str, Any]:
    snapshot = load_universe_snapshot(root)
    if not snapshot.get("universes"):
        return {
            "ok": True,
            "schema_version": "universe_summary_v1",
            "as_of_date": snapshot.get("as_of_date"),
            "version": snapshot.get("version"),
            "source_status": snapshot.get("source_status", "UNAVAILABLE"),
            "data_source": snapshot.get("data_source", "UNKNOWN"),
            "point_in_time_status": POINT_IN_TIME_STATUS,
            "research_use": snapshot.get("research_use", "PROTOTYPE_ONLY"),
            "not_survivor_bias_free": snapshot.get("not_survivor_bias_free", True),
            "last_refresh_time": snapshot.get("generated_at"),
            "universes": {},
            "warnings": snapshot.get("warnings", ["Universe snapshot unavailable."]),
        }
    universes = {
        name: summarize_snapshot_for_api(_snapshot_from_dict(payload))
        for name, payload in snapshot.get("universes", {}).items()
    }
    return {
        "ok": True,
        "schema_version": "universe_summary_v1",
        "as_of_date": snapshot.get("as_of_date"),
        "version": snapshot.get("version"),
        "source_status": snapshot.get("source_status"),
        "data_source": snapshot.get("data_source"),
        "point_in_time_status": snapshot.get("point_in_time_status", POINT_IN_TIME_STATUS),
        "research_use": snapshot.get("research_use", "PROTOTYPE_ONLY"),
        "not_survivor_bias_free": snapshot.get("not_survivor_bias_free", True),
        "label_contract": snapshot.get("label_contract"),
        "last_refresh_time": snapshot.get("generated_at"),
        "universes": universes,
        "warnings": _collect_warnings(universes),
    }


def universe_members_payload(
    root: str | Path = ".",
    *,
    universe_name: str,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    snapshot = load_universe_snapshot(root)
    effective_date = as_of_date or snapshot.get("as_of_date")
    membership_path = Path(root) / DEFAULT_UNIVERSE_OUTPUT_DIR / "universe_membership.csv"
    payload = get_universe_members(universe_name, effective_date, membership_path=membership_path)
    return {
        "ok": True,
        **payload,
        "research_use": snapshot.get("research_use", "PROTOTYPE_ONLY"),
        "not_survivor_bias_free": snapshot.get("not_survivor_bias_free", True),
    }


def _unavailable_payload(reason: str) -> dict[str, Any]:
    return {
        "ok": True,
        "schema_version": "universe_snapshot_bundle_v1",
        "as_of_date": None,
        "generated_at": None,
        "version": None,
        "point_in_time_status": POINT_IN_TIME_STATUS,
        "source_status": "UNAVAILABLE",
        "data_source": "UNKNOWN",
        "universes": {},
        "warnings": [reason],
    }


def _collect_warnings(universes: dict[str, dict[str, Any]]) -> list[str]:
    warnings = set()
    for payload in universes.values():
        warnings.update(payload.get("warnings") or [])
    return sorted(warnings)


def _snapshot_from_dict(payload: dict[str, Any]):
    from dataclasses import MISSING

    from src.universe.models import UniverseSnapshot

    fields = UniverseSnapshot.__dataclass_fields__
    values = {}
    for name, field in fields.items():
        if name in payload:
            values[name] = payload.get(name)
        elif field.default is not MISSING:
            values[name] = field.default
        elif field.default_factory is not MISSING:  # type: ignore[attr-defined]
            values[name] = field.default_factory()  # type: ignore[misc]
        else:
            values[name] = None
    return UniverseSnapshot(**values)
