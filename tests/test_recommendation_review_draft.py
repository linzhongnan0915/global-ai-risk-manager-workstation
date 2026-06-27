from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.market.paper_rebalance import paper_rebalance_snapshot_payload
from src.market.recommendation_review_draft import create_recommendation_review_draft


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


def _row(uid: str = "STRAT_UID_1", proposed_weight: float = 0.07) -> dict:
    return {
        "strategy_uid": uid,
        "strategy_name": "Dynamic Strategy",
        "canonical_status": "ACTIVE_UNALLOCATED",
        "current_weight": 0.02,
        "recommended_weight": 0.05,
        "proposed_weight": proposed_weight,
        "estimated_trade": 0,
        "estimated_transaction_cost": 0,
        "evidence_status": "EVIDENCE_AVAILABLE",
        "data_quality": "PUBLIC_FALLBACK_PROTOTYPE_NOT_PIT_NOT_SURVIVORSHIP_BIAS_FREE",
        "ml_status": "No ML evidence available",
        "recommendation_reason": "Prototype public fallback warning, not a hard block.",
        "action_status": "STARTER_RECOMMENDATION_REVIEW_REQUIRED",
    }


def test_recommendation_review_draft_artifact_created_from_recommendation_rows(tmp_path: Path):
    root = _copy_root(tmp_path)
    draft = create_recommendation_review_draft(
        root,
        [_row()],
        portfolio_nav=1_000_000,
        source_recommendation_artifact="operational_snapshot_runtime_recommendation_rows",
    )

    assert draft["proposal_id"].startswith("recommendation-review-")
    assert draft["review_status"] == "DRAFT_NOT_APPLIED"
    assert draft["source_recommendation_artifact"] == "operational_snapshot_runtime_recommendation_rows"
    assert draft["recommendation_only"] is True
    assert draft["draft_not_applied"] is True
    assert draft["line_items"][0]["strategy_uid"] == "STRAT_UID_1"
    assert draft["line_items"][0]["strategy_name"] == "Dynamic Strategy"
    assert draft["line_items"][0]["current_weight"] == pytest.approx(0.02)
    assert draft["line_items"][0]["recommended_weight"] == pytest.approx(0.05)
    assert draft["line_items"][0]["proposed_weight"] == pytest.approx(0.07)
    assert draft["line_items"][0]["user_edited_weight"] == pytest.approx(0.07)

    payload = paper_rebalance_snapshot_payload(root)
    assert payload["recommendation_review"]["latest_draft"]["proposal_id"] == draft["proposal_id"]


def test_editing_proposed_weight_recalculates_trade_and_5bp_cost(tmp_path: Path):
    root = _copy_root(tmp_path)
    draft = create_recommendation_review_draft(root, [_row(proposed_weight=0.08)], portfolio_nav=2_000_000)
    line = draft["line_items"][0]

    assert line["estimated_trade"] == pytest.approx((0.08 - 0.02) * 2_000_000)
    assert line["estimated_transaction_cost"] == pytest.approx(abs(0.08 - 0.02) * 2_000_000 * 0.0005)


def test_draft_does_not_mutate_current_target_nav_combined_or_paper_ledger(tmp_path: Path):
    root = _copy_root(tmp_path)
    canonical_path = root / "dashboard/data/canonical_operational.json"
    before = _digest(canonical_path)

    draft = create_recommendation_review_draft(root, [_row()], portfolio_nav=1_000_000)
    payload = paper_rebalance_snapshot_payload(root)

    assert _digest(canonical_path) == before
    assert payload["current_paper_target"] is None
    assert payload["costs"] == []
    assert draft["current_weight_mutation"] is False
    assert draft["target_weight_mutation"] is False
    assert draft["paper_ledger_mutation"] is False
    assert draft["combined_current_mutation"] is False
    assert draft["nav_pnl_impact"] == "NONE_UNTIL_APPROVED_AND_EFFECTIVE_DATE"
    assert draft["live_trading"] is False
    assert draft["brokerage_execution"] is False


def test_public_fallback_and_missing_ml_are_warnings_not_hard_blocks(tmp_path: Path):
    root = _copy_root(tmp_path)
    draft = create_recommendation_review_draft(root, [_row()], portfolio_nav=1_000_000)
    flags = draft["line_items"][0]["warning_flags"]

    assert "PUBLIC_FALLBACK" in flags
    assert "NOT_PIT" in flags
    assert "NOT_SURVIVORSHIP_FREE" in flags
    assert "MISSING_ML_OR_EVIDENCE_WARNING" in flags


def test_missing_strategy_uid_hard_blocks_draft_row_inclusion(tmp_path: Path):
    root = _copy_root(tmp_path)
    row = _row(uid="")

    with pytest.raises(ValueError, match="missing canonical strategy_uid"):
        create_recommendation_review_draft(root, [row], portfolio_nav=1_000_000)


def test_display_label_is_never_canonical_id(tmp_path: Path):
    root = _copy_root(tmp_path)

    with pytest.raises(ValueError, match="display_label cannot be used as canonical strategy_uid"):
        create_recommendation_review_draft(root, [_row(uid="#000020")], portfolio_nav=1_000_000)
