"""Paper rebalance lifecycle tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.market.paper_rebalance import (
    accept_paper_rebalance_plan,
    apply_paper_rebalance_plan,
    generate_paper_rebalance_plan,
    paper_rebalance_snapshot_payload,
    reject_paper_rebalance_plan,
)
from src.reporting.operational_snapshot import load_operational_snapshot_for_response


ROOT = Path(__file__).resolve().parents[1]


def _copy_root(tmp_path: Path) -> Path:
    root = tmp_path / "workstation"
    (root / "dashboard/data").mkdir(parents=True)
    (root / "dashboard/data/canonical_operational.json").write_text(
        (ROOT / "dashboard/data/canonical_operational.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return root


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _equal_targets(snapshot: dict) -> dict[str, float]:
    active = [
        row
        for row in snapshot["strategies"]
        if row.get("membership_state") == "executed"
        and row.get("internal_id") not in set(snapshot.get("removed_from_current_workstation_strategy_ids") or [])
    ]
    weight = 1 / len(active)
    return {row["internal_id"]: weight for row in active}


def test_generate_accept_apply_persists_paper_target_and_cost_record(tmp_path: Path):
    root = _copy_root(tmp_path)
    canonical_path = root / "dashboard/data/canonical_operational.json"
    canonical_before = _digest(canonical_path)
    snapshot = load_operational_snapshot_for_response(root)
    targets = _equal_targets(snapshot)
    first_id = next(iter(targets))
    targets[first_id] += 0.01
    second_id = list(targets)[1]
    targets[second_id] -= 0.01

    plan = generate_paper_rebalance_plan(root, snapshot, targets)

    assert plan["source_label"] == "user_adjusted_paper_target"
    assert plan["status"] == "Draft"
    assert plan["applied_status"] == "Draft"
    assert plan["execution_mode"] == "Paper Only"
    assert plan["live_brokerage_fill"] == "No"
    assert plan["official_ledger_mutation"] == "No"
    assert plan["paper_trade_notional_total"] > 0
    assert plan["paper_transaction_cost_total"] > 0
    assert any(row["action"] == "INCREASE" for row in plan["line_items"])
    assert any(row["action"] == "REDUCE" for row in plan["line_items"])

    accepted = accept_paper_rebalance_plan(root, plan["plan_id"])
    assert accepted["applied_status"] == "Accepted Pending Application"

    applied = apply_paper_rebalance_plan(root, plan["plan_id"])
    assert applied["current_paper_target"]["applied_status"] == "Applied to Paper Allocation"
    assert applied["current_paper_target"]["weights"][first_id] == pytest.approx(targets[first_id])
    assert applied["cost_record"]["paper_transaction_cost_total"] == pytest.approx(
        plan["paper_transaction_cost_total"]
    )
    assert applied["cost_record"]["live_brokerage_fill"] == "No"
    assert applied["cost_record"]["official_ledger_mutation"] == "No"

    reloaded = load_operational_snapshot_for_response(root)
    current = reloaded["paper_rebalance"]["current_paper_target"]
    assert current["applied_plan_id"] == plan["plan_id"]
    assert current["weights"][first_id] == pytest.approx(targets[first_id])
    assert reloaded["paper_rebalance"]["latest_cost_record"]["plan_id"] == plan["plan_id"]
    assert _digest(canonical_path) == canonical_before


def test_reject_plan_does_not_apply_target_or_cost(tmp_path: Path):
    root = _copy_root(tmp_path)
    snapshot = load_operational_snapshot_for_response(root)
    plan = generate_paper_rebalance_plan(root, snapshot, _equal_targets(snapshot))

    rejected = reject_paper_rebalance_plan(root, plan["plan_id"])

    assert rejected["applied_status"] == "Rejected"
    payload = paper_rebalance_snapshot_payload(root)
    assert payload["current_paper_target"] is None
    assert payload["costs"] == []


def test_over_allocated_target_blocks_generation(tmp_path: Path):
    root = _copy_root(tmp_path)
    snapshot = load_operational_snapshot_for_response(root)
    targets = _equal_targets(snapshot)
    first_id = next(iter(targets))
    targets[first_id] += 0.02

    with pytest.raises(ValueError, match="exceeds 100%"):
        generate_paper_rebalance_plan(root, snapshot, targets)


def test_missing_target_data_creates_review_and_blocks_accept(tmp_path: Path):
    root = _copy_root(tmp_path)
    snapshot = load_operational_snapshot_for_response(root)
    targets = _equal_targets(snapshot)
    targets.pop(next(iter(targets)))

    plan = generate_paper_rebalance_plan(root, snapshot, targets)

    assert plan["status"] == "Review"
    assert any(row["action"] == "REVIEW" for row in plan["line_items"])
    with pytest.raises(ValueError, match="review lines"):
        accept_paper_rebalance_plan(root, plan["plan_id"])
