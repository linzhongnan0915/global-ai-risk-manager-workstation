from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

from src.market.approved_rebalance_plan import (
    apply_approved_rebalance_plan,
    apply_due_approved_rebalance_plan,
    create_approved_rebalance_plan,
)
from src.market.paper_rebalance import paper_rebalance_snapshot_payload
from src.market.recommendation_review_draft import create_recommendation_review_draft


def _snapshot(*, session_marker: str = "2026-06-29", pending: bool = False) -> dict:
    return {
        "portfolio_summary": {"nav": 1_000_000},
        "session_state": {
            "calendar_date": session_marker,
            "market_session_status": "Open",
            "is_trading_day": True,
            "last_trading_session": "2026-06-26" if session_marker < "2026-06-29" else session_marker,
            "next_trading_session": "2026-06-29",
            "current_intraday_session": session_marker if session_marker >= "2026-06-29" else None,
        },
        "portfolio_daily": [{"date": "2026-06-26", "ending_nav": 1_000_000, "net_pnl": 0}],
        "strategies": [
            {
                "internal_id": "S1",
                "strategy_uid": "S1",
                "display_id": "#000001",
                "display_name": "Dynamic Strategy One",
                "membership_state": "approved_pending" if pending else "executed",
                "current_operational_status": "PENDING_USER_APPROVAL" if pending else "ACTIVE_UNALLOCATED",
                "current_weight": 0.0,
            },
            {
                "internal_id": "S2",
                "strategy_uid": "S2",
                "display_id": "#000002",
                "display_name": "Dynamic Strategy Two",
                "membership_state": "executed",
                "current_operational_status": "ACTIVE_ALLOCATED",
                "current_weight": 0.5,
            },
            {
                "internal_id": "COMBINED_PORTFOLIO",
                "strategy_uid": "COMBINED_PORTFOLIO",
                "display_id": "#COMBINED",
                "display_name": "Combined",
                "membership_state": "executed",
                "current_operational_status": "ACTIVE_COMPOSITE",
                "current_weight": 0.5,
            },
        ],
    }


def _row(uid: str, current: float, proposed: float, **extra) -> dict:
    row = {
        "strategy_uid": uid,
        "strategy_name": f"Strategy {uid}",
        "canonical_status": "ACTIVE_UNALLOCATED" if current == 0 else "ACTIVE_ALLOCATED",
        "current_weight": current,
        "recommended_weight": proposed,
        "proposed_weight": proposed,
        "evidence_status": "EVIDENCE_AVAILABLE",
        "data_quality": "PUBLIC_FALLBACK",
        "ml_status": "No ML evidence available",
        "recommendation_reason": "Paper rebalance test row.",
        "action_status": "INCREASE" if proposed > current else "REDUCE",
    }
    row.update(extra)
    return row


def _approved_plan(root: Path, *, rows: list[dict] | None = None, approval_snapshot: dict | None = None) -> dict:
    draft = create_recommendation_review_draft(
        root,
        rows or [_row("S1", 0.0, 0.2), _row("S2", 0.5, 0.8)],
        portfolio_nav=1_000_000,
        source_recommendation_artifact="test_recommendation_rows",
    )
    return create_approved_rebalance_plan(
        root,
        snapshot=approval_snapshot or _snapshot(session_marker="2026-06-27"),
        draft_id=draft["proposal_id"],
    )


def test_waiting_effective_date_plan_applies_when_session_reaches_effective_date(tmp_path: Path):
    root = tmp_path / "workstation"
    plan = _approved_plan(root)

    result = apply_approved_rebalance_plan(root, snapshot=_snapshot(session_marker="2026-06-29"), plan_id=plan["plan_id"])

    assert result["applied"] is True
    assert result["plan"]["status"] == "APPLIED_PAPER"
    assert result["event"]["applied_effective_date"] == "2026-06-29"
    assert result["current_paper_target"]["weights"]["S1"] == pytest.approx(0.2)
    assert result["current_paper_target"]["weights"]["S2"] == pytest.approx(0.8)


def test_plan_does_not_apply_before_effective_date(tmp_path: Path):
    root = tmp_path / "workstation"
    plan = _approved_plan(root)

    result = apply_approved_rebalance_plan(root, snapshot=_snapshot(session_marker="2026-06-28"), plan_id=plan["plan_id"])

    assert result["applied"] is False
    assert result["message"] == "effective date has not arrived"
    assert not (root / "data/paper_rebalance/current_paper_target_weights.json").exists()
    assert paper_rebalance_snapshot_payload(root)["approved_rebalance"]["latest_plan"]["status"] == "APPROVED_WAITING_EFFECTIVE_DATE"


def test_active_unallocated_moves_from_zero_to_approved_target_weight(tmp_path: Path):
    root = tmp_path / "workstation"
    plan = _approved_plan(root)

    result = apply_approved_rebalance_plan(root, snapshot=_snapshot(session_marker="2026-06-29"), plan_id=plan["plan_id"])

    assert result["event"]["previous_weights_by_strategy_uid"]["S1"] == pytest.approx(0.0)
    assert result["event"]["new_weights_by_strategy_uid"]["S1"] == pytest.approx(0.2)
    assert result["event"]["per_strategy_trade_weight"]["S1"] == pytest.approx(0.2)


def test_strategy_uid_is_canonical_and_display_label_is_rejected(tmp_path: Path):
    root = tmp_path / "workstation"
    plan = _approved_plan(root)
    path = root / "data/paper_rebalance/approved_rebalance_plans.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["plans"][-1]["rows"][0]["strategy_uid"] = "#000001"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="display_label cannot be used"):
        apply_approved_rebalance_plan(root, snapshot=_snapshot(session_marker="2026-06-29"), plan_id=plan["plan_id"])


def test_transaction_cost_uses_5bps_formula(tmp_path: Path):
    root = tmp_path / "workstation"
    plan = _approved_plan(root)

    result = apply_approved_rebalance_plan(root, snapshot=_snapshot(session_marker="2026-06-29"), plan_id=plan["plan_id"])
    costs = result["event"]["per_strategy_transaction_cost"]

    assert costs["S1"] == pytest.approx(abs(0.2 - 0.0) * 1_000_000 * 0.0005)
    assert costs["S2"] == pytest.approx(abs(0.8 - 0.5) * 1_000_000 * 0.0005)
    assert result["event"]["total_transaction_cost"] == pytest.approx(costs["S1"] + costs["S2"])


def test_repeated_apply_is_idempotent_and_does_not_double_book_cost(tmp_path: Path):
    root = tmp_path / "workstation"
    plan = _approved_plan(root)

    first = apply_approved_rebalance_plan(root, snapshot=_snapshot(session_marker="2026-06-29"), plan_id=plan["plan_id"])
    second = apply_approved_rebalance_plan(root, snapshot=_snapshot(session_marker="2026-06-29"), plan_id=plan["plan_id"])
    events = paper_rebalance_snapshot_payload(root)["approved_rebalance"]["applied_events"]

    assert first["applied"] is True
    assert second["already_applied"] is True
    assert len(events) == 1
    assert second["event"]["total_transaction_cost"] == pytest.approx(first["event"]["total_transaction_cost"])


def test_concurrent_due_apply_is_exactly_once(tmp_path: Path):
    root = tmp_path / "workstation"
    plan = _approved_plan(root)
    snapshot = _snapshot(session_marker="2026-06-29")

    with ThreadPoolExecutor(max_workers=25) as executor:
        results = [
            future.result()
            for future in as_completed(
                [executor.submit(apply_due_approved_rebalance_plan, root, snapshot=snapshot) for _ in range(25)]
            )
        ]

    paper = paper_rebalance_snapshot_payload(root)
    events = paper["approved_rebalance"]["applied_events"]
    newly_applied = [row for row in results if row.get("applied")]
    already_applied = [row for row in results if row.get("already_applied")]
    skipped = [row for row in results if row.get("skipped")]

    assert len(events) == 1
    assert len(newly_applied) == 1
    assert len(already_applied) + len(skipped) == 24
    assert events[0]["plan_id"] == plan["plan_id"]
    assert events[0]["apply_key"] == newly_applied[0]["apply_key"]
    assert paper["current_paper_target"]["apply_key"] == events[0]["apply_key"]
    assert paper["approved_rebalance"]["latest_plan"]["status"] == "APPLIED_PAPER"
    assert paper["current_paper_target"]["paper_transaction_cost_total"] == pytest.approx(
        events[0]["total_transaction_cost"]
    )


def test_due_apply_service_before_effective_date_writes_no_apply_state(tmp_path: Path):
    root = tmp_path / "workstation"
    plan = _approved_plan(root)

    result = apply_due_approved_rebalance_plan(root, snapshot=_snapshot(session_marker="2026-06-28"))
    paper = paper_rebalance_snapshot_payload(root)

    assert result["applied"] is False
    assert result["already_applied"] is False
    assert result["message"] == "effective date has not arrived"
    assert paper["approved_rebalance"]["latest_plan"]["plan_id"] == plan["plan_id"]
    assert paper["approved_rebalance"]["latest_plan"]["status"] == "APPROVED_WAITING_EFFECTIVE_DATE"
    assert paper["approved_rebalance"]["applied_events"] == []
    assert paper["current_paper_target"] is None
    assert not (root / "data/paper_rebalance/approved_rebalance_apply.lock").exists()


def test_smoke_test_and_pending_rows_do_not_apply(tmp_path: Path):
    root = tmp_path / "workstation"
    plan = _approved_plan(root)
    path = root / "data/paper_rebalance/approved_rebalance_plans.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["plans"][-1]["rows"][0]["TEST_ARTIFACT"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="smoke/test rows"):
        apply_approved_rebalance_plan(root, snapshot=_snapshot(session_marker="2026-06-29"), plan_id=plan["plan_id"])

    root2 = tmp_path / "pending"
    plan2 = _approved_plan(root2)
    with pytest.raises(ValueError, match="not an active paper strategy"):
        apply_approved_rebalance_plan(root2, snapshot=_snapshot(session_marker="2026-06-29", pending=True), plan_id=plan2["plan_id"])


def test_no_live_or_brokerage_orders_created(tmp_path: Path):
    root = tmp_path / "workstation"
    plan = _approved_plan(root)

    result = apply_approved_rebalance_plan(root, snapshot=_snapshot(session_marker="2026-06-29"), plan_id=plan["plan_id"])

    assert result["event"]["no_live_orders"] is True
    assert result["event"]["no_brokerage_orders"] is True
    assert result["current_paper_target"]["no_live_orders"] is True
    assert result["current_paper_target"]["no_brokerage_orders"] is True


def test_combined_updates_dynamically_from_ordinary_active_rows(tmp_path: Path):
    root = tmp_path / "workstation"
    plan = _approved_plan(
        root,
        rows=[
            _row("S1", 0.0, 0.2),
            _row("S2", 0.5, 0.7),
            _row("COMBINED_PORTFOLIO", 0.5, 0.1),
        ],
    )

    result = apply_approved_rebalance_plan(root, snapshot=_snapshot(session_marker="2026-06-29"), plan_id=plan["plan_id"])
    summary = result["event"]["combined_dynamic_summary"]

    assert summary["ordinary_strategy_count"] == 2
    assert summary["ordinary_weight_total"] == pytest.approx(0.9)
    assert summary["computed_from"] == "active ordinary strategy_uid weights"


def test_old_historical_pnl_is_not_rewritten(tmp_path: Path):
    root = tmp_path / "workstation"
    plan = _approved_plan(root)
    snapshot = _snapshot(session_marker="2026-06-29")
    before = list(snapshot["portfolio_daily"])

    result = apply_approved_rebalance_plan(root, snapshot=snapshot, plan_id=plan["plan_id"])

    assert snapshot["portfolio_daily"] == before
    assert result["event"]["old_historical_pnl_rewritten"] is False
    assert result["plan"]["old_historical_pnl_rewritten"] is False
