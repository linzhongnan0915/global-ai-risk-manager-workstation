from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest

from src.market.approved_rebalance_plan import create_approved_rebalance_plan
from src.market.paper_rebalance import paper_rebalance_snapshot_payload
from src.market.recommendation_review_draft import create_recommendation_review_draft
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
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "MISSING"


def _row(uid: str = "STRAT_UID_1", proposed_weight: float = 0.07, **extra) -> dict:
    row = {
        "strategy_uid": uid,
        "strategy_name": "Dynamic Strategy",
        "canonical_status": "ACTIVE_UNALLOCATED",
        "current_weight": 0.02,
        "recommended_weight": 0.05,
        "proposed_weight": proposed_weight,
        "evidence_status": "EVIDENCE_AVAILABLE",
        "data_quality": "PUBLIC_FALLBACK_PROTOTYPE_NOT_PIT_NOT_SURVIVORSHIP_BIAS_FREE",
        "ml_status": "No ML evidence available",
        "recommendation_reason": "Prototype public fallback warning, not a hard block.",
        "action_status": "STARTER_RECOMMENDATION_REVIEW_REQUIRED",
    }
    row.update(extra)
    return row


def _draft_and_snapshot(root: Path, rows: list[dict] | None = None) -> tuple[dict, dict]:
    draft = create_recommendation_review_draft(
        root,
        rows or [_row()],
        portfolio_nav=1_000_000,
        source_recommendation_artifact="operational_snapshot_runtime_recommendation_rows",
    )
    snapshot = load_operational_snapshot_for_response(
        root,
        now=datetime.fromisoformat("2026-06-27T12:00:00-04:00"),
    )
    return draft, snapshot


def test_approving_draft_creates_approved_rebalance_plan_artifact(tmp_path: Path):
    root = _copy_root(tmp_path)
    draft, snapshot = _draft_and_snapshot(root)

    plan = create_approved_rebalance_plan(root, snapshot=snapshot, draft_id=draft["proposal_id"])

    assert plan["plan_id"].startswith("approved-rebalance-")
    assert plan["source_draft_id"] == draft["proposal_id"]
    assert plan["status"] == "APPROVED_WAITING_EFFECTIVE_DATE"
    assert plan["approved_by"] == "USER_UI"
    assert plan["approval_channel"] == "dashboard"
    assert plan["effective_date_rule"] == "NEXT_TRADING_SESSION_FROM_BACKEND_SESSION_STATE"
    assert plan["rows"][0]["strategy_uid"] == "STRAT_UID_1"
    assert plan["approval_only"] is True
    assert plan["live_orders_created"] is False
    assert plan["brokerage_orders_created"] is False

    artifact = root / "data/paper_rebalance/approved_rebalance_plans.json"
    assert artifact.exists()
    payload = paper_rebalance_snapshot_payload(root)
    assert payload["approved_rebalance"]["latest_plan"]["plan_id"] == plan["plan_id"]


def test_effective_date_comes_from_backend_session_state_next_trading_session(tmp_path: Path):
    root = _copy_root(tmp_path)
    draft, snapshot = _draft_and_snapshot(root)

    plan = create_approved_rebalance_plan(root, snapshot=snapshot, draft_id=draft["proposal_id"])

    assert snapshot["session_state"]["calendar_date"] == "2026-06-27"
    assert snapshot["session_state"]["market_session_status"] == "MARKET_CLOSED_WEEKEND"
    assert snapshot["session_state"]["next_trading_session"] == "2026-06-29"
    assert plan["effective_date"] == snapshot["session_state"]["next_trading_session"]
    assert plan["effective_date"] != snapshot["session_state"]["calendar_date"]
    assert plan["last_trading_session"] == "2026-06-26"
    assert plan["next_trading_session"] == "2026-06-29"


def test_approved_plan_uses_strategy_uid_not_display_label(tmp_path: Path):
    root = _copy_root(tmp_path)
    draft, snapshot = _draft_and_snapshot(root)

    plan = create_approved_rebalance_plan(root, snapshot=snapshot, draft_id=draft["proposal_id"])

    assert plan["rows"][0]["strategy_uid"] == "STRAT_UID_1"
    assert not plan["rows"][0]["strategy_uid"].startswith("#")


def test_public_fallback_and_missing_ml_are_warnings_not_hard_blocks(tmp_path: Path):
    root = _copy_root(tmp_path)
    draft, snapshot = _draft_and_snapshot(root)

    plan = create_approved_rebalance_plan(root, snapshot=snapshot, draft_id=draft["proposal_id"])

    assert "PUBLIC_FALLBACK" in plan["warnings"]
    assert "MISSING_ML_OR_EVIDENCE_WARNING" in plan["warnings"]
    assert plan["status"] == "APPROVED_WAITING_EFFECTIVE_DATE"


def test_missing_strategy_uid_blocks_approval(tmp_path: Path):
    root = _copy_root(tmp_path)
    draft = create_recommendation_review_draft(root, [_row()], portfolio_nav=1_000_000)
    path = root / "data/paper_rebalance/recommendation_review_drafts.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["drafts"][-1]["line_items"][0]["strategy_uid"] = ""
    path.write_text(json.dumps(payload), encoding="utf-8")
    snapshot = load_operational_snapshot_for_response(root, now=datetime.fromisoformat("2026-06-27T12:00:00-04:00"))

    with pytest.raises(ValueError, match="missing canonical strategy_uid"):
        create_approved_rebalance_plan(root, snapshot=snapshot, draft_id=draft["proposal_id"])


def test_smoke_test_and_pending_rows_block_approval(tmp_path: Path):
    root = _copy_root(tmp_path)
    draft = create_recommendation_review_draft(root, [_row()], portfolio_nav=1_000_000)
    path = root / "data/paper_rebalance/recommendation_review_drafts.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["drafts"][-1]["line_items"][0]["TEST_ARTIFACT"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")
    snapshot = load_operational_snapshot_for_response(root, now=datetime.fromisoformat("2026-06-27T12:00:00-04:00"))
    with pytest.raises(ValueError, match="smoke/test rows"):
        create_approved_rebalance_plan(root, snapshot=snapshot, draft_id=draft["proposal_id"])

    root2 = _copy_root(tmp_path / "pending")
    draft2 = create_recommendation_review_draft(root2, [_row()], portfolio_nav=1_000_000)
    path2 = root2 / "data/paper_rebalance/recommendation_review_drafts.json"
    payload2 = json.loads(path2.read_text(encoding="utf-8"))
    payload2["drafts"][-1]["line_items"][0]["canonical_status"] = "PENDING_USER_APPROVAL"
    path2.write_text(json.dumps(payload2), encoding="utf-8")
    snapshot2 = load_operational_snapshot_for_response(root2, now=datetime.fromisoformat("2026-06-27T12:00:00-04:00"))
    with pytest.raises(ValueError, match="pending approval rows"):
        create_approved_rebalance_plan(root2, snapshot=snapshot2, draft_id=draft2["proposal_id"])


def test_approval_does_not_mutate_weights_nav_combined_or_ledgers(tmp_path: Path):
    root = _copy_root(tmp_path)
    canonical = root / "dashboard/data/canonical_operational.json"
    target = root / "data/paper_rebalance/current_paper_target_weights.json"
    costs = root / "data/paper_rebalance/paper_rebalance_costs.json"
    before = {
        "canonical": _digest(canonical),
        "target": _digest(target),
        "costs": _digest(costs),
    }
    draft, snapshot = _draft_and_snapshot(root)
    before_portfolio_daily = snapshot["portfolio_daily"]
    before_strategies = snapshot["strategies"]

    plan = create_approved_rebalance_plan(root, snapshot=snapshot, draft_id=draft["proposal_id"])
    after = load_operational_snapshot_for_response(root, now=datetime.fromisoformat("2026-06-27T12:00:00-04:00"))

    assert _digest(canonical) == before["canonical"]
    assert _digest(target) == before["target"]
    assert _digest(costs) == before["costs"]
    assert after["portfolio_daily"] == before_portfolio_daily
    assert after["strategies"] == before_strategies
    assert plan["current_weight_mutation"] is False
    assert plan["target_weight_mutation"] is False
    assert plan["paper_ledger_mutation"] is False
    assert plan["combined_current_mutation"] is False
    assert plan["nav_pnl_impact"] == "NONE_UNTIL_EFFECTIVE_DATE_APPLY"


def test_estimated_transaction_cost_uses_5bps_formula(tmp_path: Path):
    root = _copy_root(tmp_path)
    draft, snapshot = _draft_and_snapshot(root, [_row(proposed_weight=0.08)])

    plan = create_approved_rebalance_plan(root, snapshot=snapshot, draft_id=draft["proposal_id"])
    nav = plan["portfolio_nav_used_for_cost_estimate"]
    row = plan["rows"][0]

    assert row["estimated_trade"] == pytest.approx((0.08 - 0.02) * nav)
    assert row["estimated_transaction_cost"] == pytest.approx(abs(0.08 - 0.02) * nav * 0.0005)
    assert plan["estimated_total_transaction_cost"] == pytest.approx(row["estimated_transaction_cost"])
