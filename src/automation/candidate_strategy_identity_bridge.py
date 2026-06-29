"""Read-only candidate-to-strategy identity bridge V0.

The bridge links Strategy Factory candidate artifacts to Strategy Intelligence
cards only through canonical IDs or explicit activation lineage. It never uses
display labels or fuzzy name matching.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.automation.allocation_recommendation_artifact import read_latest_allocation_recommendation_artifact
from src.automation.daily_recommendation_artifact import read_latest_daily_recommendation_artifact
from src.automation.ml_intelligence_patch_manifest import build_ml_intelligence_patch_manifest, ml_patch_by_identity
from src.automation.strategy_factory_evidence_manifest import build_strategy_factory_evidence_manifest, lineage_by_identity
from src.reporting.operational_snapshot import _strategy_factory_active_unallocated_records


SOURCE = "candidate_strategy_identity_bridge_v0"
CACHE_RELATIVE_PATH = Path("data/automation/identity_bridge/manifest.json")
ALPHA_RESEARCH_ENV = "STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT"


def _alpha_root() -> Path:
    configured = os.environ.get(ALPHA_RESEARCH_ENV)
    return Path(configured) if configured else Path(r"D:\Global_Ai\alpha_research")


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _normalize_identity(value: Any) -> str:
    text = str(value or "").upper()
    text = re.sub(r"(_RESEARCH_CARD|_TEST_SPEC|_DRAFT|_EXPERIMENT_V\d+)$", "", text)
    text = re.sub(r"[^A-Z0-9]+", "_", text)
    return text.strip("_")


def _identity_values(payload: dict[str, Any]) -> dict[str, str]:
    keys = ("strategy_uid", "candidate_id", "material_hash", "research_card_id", "test_spec_id")
    result: dict[str, str] = {}
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        normalized = _normalize_identity(value)
        if normalized:
            result[key] = normalized
    return result


def _card_identity(card: dict[str, Any]) -> dict[str, str]:
    values = {
        "strategy_uid": card.get("strategy_uid"),
        "candidate_id": card.get("candidate_id") or card.get("portfolio_candidate_id"),
        "material_hash": card.get("material_hash") or card.get("source_material_hash"),
        "research_card_id": (card.get("research_lineage") or {}).get("research_card_id"),
        "test_spec_id": (card.get("research_lineage") or {}).get("test_spec_id"),
    }
    return _identity_values(values)


def _factory_identity(item: dict[str, Any]) -> dict[str, str]:
    return _identity_values(item)


def _activation_index(root: Path) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in _strategy_factory_active_unallocated_records(root):
        candidate_key = _normalize_identity(row.get("candidate_id"))
        strategy_key = _normalize_identity(row.get("strategy_uid") or row.get("strategy_id"))
        material_key = _normalize_identity(row.get("source_material_hash"))
        for key in (candidate_key, strategy_key, material_key):
            if key:
                index.setdefault(key, row)
    return index


def _artifact_strategy_uids(root: Path) -> dict[str, list[dict[str, Any]]]:
    artifacts: dict[str, list[dict[str, Any]]] = {}
    latest_daily = read_latest_daily_recommendation_artifact(root)
    if latest_daily.get("ok"):
        for row in ((latest_daily.get("artifact") or {}).get("recommendations") or []):
            uid = _normalize_identity((row or {}).get("strategy_uid"))
            if uid:
                artifacts.setdefault(uid, []).append(
                    {"kind": "daily_recommendation", "path": latest_daily.get("artifact_path"), "status": "READ_ONLY_LINEAGE"}
                )
    latest_allocation = read_latest_allocation_recommendation_artifact(root)
    if latest_allocation.get("ok"):
        for row in ((latest_allocation.get("artifact") or {}).get("recommendations") or []):
            uid = _normalize_identity((row or {}).get("strategy_uid"))
            if uid:
                artifacts.setdefault(uid, []).append(
                    {"kind": "allocation_recommendation", "path": latest_allocation.get("artifact_path"), "status": "READ_ONLY_LINEAGE"}
                )
    return artifacts


def _source_artifacts(
    root: Path,
    factory_item: dict[str, Any],
    card: dict[str, Any] | None,
    activation: dict[str, Any] | None,
    artifact_index: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    artifacts = list(factory_item.get("source_artifacts") or [])
    uid = _normalize_identity((card or {}).get("strategy_uid") or (activation or {}).get("strategy_uid"))
    artifacts.extend(artifact_index.get(uid, []))
    if activation and activation.get("activation_artifact_path"):
        artifacts.append(
            {
                "kind": "activation_record",
                "path": str(activation.get("activation_artifact_path")),
                "status": "EXPLICIT_LINEAGE",
            }
        )
    return artifacts


def _match_factory_item(
    root: Path,
    item: dict[str, Any],
    cards_by_uid: dict[str, dict[str, Any]],
    cards_by_identity: dict[str, dict[str, Any]],
    activations: dict[str, dict[str, Any]],
    artifact_index: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any] | None, str | None]:
    factory_ids = _factory_identity(item)
    activation = None
    for key_name in ("candidate_id", "material_hash", "strategy_uid"):
        key = factory_ids.get(key_name)
        if key and key in activations:
            activation = activations[key]
            strategy_key = _normalize_identity(activation.get("strategy_uid") or activation.get("strategy_id"))
            card = cards_by_uid.get(strategy_key)
            if card:
                status = "MATCHED" if factory_ids.get("candidate_id") else "PARTIAL"
                return (
                    {
                        "strategy_uid": card.get("strategy_uid"),
                        "candidate_id": item.get("candidate_id") or activation.get("candidate_id"),
                        "research_card_id": item.get("research_card_id"),
                        "test_spec_id": item.get("test_spec_id"),
                        "material_hash": item.get("material_hash") or activation.get("source_material_hash"),
                        "match_status": status,
                        "match_basis": "activation_record",
                        "source_artifacts": _source_artifacts(root, item, card, activation, artifact_index),
                    },
                    _normalize_identity(card.get("strategy_uid")),
                )
    strategy_key = factory_ids.get("strategy_uid")
    if strategy_key and strategy_key in cards_by_uid:
        card = cards_by_uid[strategy_key]
        return (
            {
                "strategy_uid": card.get("strategy_uid"),
                "candidate_id": item.get("candidate_id"),
                "research_card_id": item.get("research_card_id"),
                "test_spec_id": item.get("test_spec_id"),
                "material_hash": item.get("material_hash"),
                "match_status": "MATCHED",
                "match_basis": "strategy_uid",
                "source_artifacts": _source_artifacts(root, item, card, None, artifact_index),
            },
            strategy_key,
        )
    for key_name in ("candidate_id", "material_hash", "research_card_id", "test_spec_id"):
        key = factory_ids.get(key_name)
        if key and key in cards_by_identity:
            card = cards_by_identity[key]
            return (
                {
                    "strategy_uid": card.get("strategy_uid"),
                    "candidate_id": item.get("candidate_id"),
                    "research_card_id": item.get("research_card_id"),
                    "test_spec_id": item.get("test_spec_id"),
                    "material_hash": item.get("material_hash"),
                    "match_status": "MATCHED",
                    "match_basis": "lineage_reference",
                    "source_artifacts": _source_artifacts(root, item, card, None, artifact_index),
                },
                _normalize_identity(card.get("strategy_uid")),
            )
    return None, None


def build_candidate_strategy_identity_bridge(
    root: str | Path,
    *,
    alpha_root: str | Path | None = None,
    strategy_cards: list[dict[str, Any]] | None = None,
    factory_manifest: dict[str, Any] | None = None,
    ml_patch_manifest: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    alpha = Path(alpha_root) if alpha_root is not None else _alpha_root()
    generated_at = (now or datetime.now(timezone.utc)).isoformat()
    factory = factory_manifest or build_strategy_factory_evidence_manifest(root_path, alpha_root=alpha, now=now)
    ml_patch = ml_patch_manifest or build_ml_intelligence_patch_manifest(root_path, alpha_root=alpha, factory_manifest=factory, now=now)
    cards = strategy_cards or []
    cards_by_uid = {
        _normalize_identity(card.get("strategy_uid")): card
        for card in cards
        if isinstance(card, dict) and _normalize_identity(card.get("strategy_uid"))
    }
    cards_by_identity: dict[str, dict[str, Any]] = {}
    for card in cards:
        if not isinstance(card, dict):
            continue
        for value in _card_identity(card).values():
            cards_by_identity.setdefault(value, card)
    activations = _activation_index(root_path)
    artifact_index = _artifact_strategy_uids(root_path)
    matches: list[dict[str, Any]] = []
    matched_strategy_uids: set[str] = set()
    matched_factory_ids: set[str] = set()
    activation_lineage_match_count = 0
    for item in factory.get("items") or []:
        if not isinstance(item, dict):
            continue
        match, strategy_key = _match_factory_item(root_path, item, cards_by_uid, cards_by_identity, activations, artifact_index)
        item_key = _normalize_identity(item.get("candidate_id") or item.get("strategy_uid") or item.get("research_card_id"))
        if match:
            matches.append(match)
            if strategy_key:
                matched_strategy_uids.add(strategy_key)
            if item_key:
                matched_factory_ids.add(item_key)
            if match.get("match_basis") == "activation_record":
                activation_lineage_match_count += 1
    factory_items = [item for item in factory.get("items") or [] if isinstance(item, dict)]
    unmatched_factory_items = []
    for item in factory_items:
        item_key = _normalize_identity(item.get("candidate_id") or item.get("strategy_uid") or item.get("research_card_id"))
        if item_key not in matched_factory_ids:
            unmatched_factory_items.append(
                {
                    "candidate_id": item.get("candidate_id"),
                    "strategy_uid": item.get("strategy_uid"),
                    "research_card_id": item.get("research_card_id"),
                    "test_spec_id": item.get("test_spec_id"),
                    "material_hash": item.get("material_hash"),
                    "match_status": "UNMATCHED",
                    "reason": "No canonical Strategy Intelligence card or activation lineage matched this Factory item.",
                }
            )
    unmatched_strategy_cards = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        uid_key = _normalize_identity(card.get("strategy_uid"))
        if uid_key and uid_key not in matched_strategy_uids:
            status = "MISSING_LINEAGE" if uid_key in activations else "UNMATCHED"
            unmatched_strategy_cards.append(
                {
                    "strategy_uid": card.get("strategy_uid"),
                    "candidate_id": card.get("candidate_id") or card.get("portfolio_candidate_id"),
                    "match_status": status,
                    "reason": "No canonical Factory candidate lineage matched this Strategy Intelligence card.",
                }
            )
    matched_count = len(matches)
    status = "AVAILABLE" if matched_count else "MISSING_LINEAGE"
    if matched_count and (unmatched_factory_items or unmatched_strategy_cards):
        status = "PARTIAL"
    return {
        "ok": True,
        "status": status,
        "source": SOURCE,
        "generated_at": generated_at,
        "paper_shadow_only": True,
        "financial_state_mutated": False,
        "summary": {
            "factory_candidate_count": len(factory_items),
            "strategy_card_count": len(cards),
            "matched_count": matched_count,
            "unmatched_factory_count": len(unmatched_factory_items),
            "unmatched_strategy_card_count": len(unmatched_strategy_cards),
            "activation_lineage_match_count": activation_lineage_match_count,
            "warnings": [],
        },
        "matches": matches,
        "unmatched_factory_items": unmatched_factory_items,
        "unmatched_strategy_cards": unmatched_strategy_cards,
        "warnings": [],
        "source_status": {
            "strategy_factory_evidence_status": factory.get("status"),
            "ml_intelligence_patch_status": ml_patch.get("status"),
        },
    }


def write_candidate_strategy_identity_bridge(
    root: str | Path,
    *,
    alpha_root: str | Path | None = None,
    strategy_cards: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> Path:
    root_path = Path(root)
    payload = build_candidate_strategy_identity_bridge(root_path, alpha_root=alpha_root, strategy_cards=strategy_cards, now=now)
    path = root_path / CACHE_RELATIVE_PATH
    _atomic_write_json(path, payload)
    return path


def bridge_matches_by_strategy_uid(bridge: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for match in bridge.get("matches") or []:
        if isinstance(match, dict):
            key = _normalize_identity(match.get("strategy_uid"))
            if key:
                result.setdefault(key, match)
    return result


def bridge_match_for_strategy(bridge: dict[str, Any], strategy_uid: Any) -> dict[str, Any] | None:
    return bridge_matches_by_strategy_uid(bridge).get(_normalize_identity(strategy_uid))
