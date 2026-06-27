from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.market.monthly_rebalance_proposal import (
    create_monthly_rebalance_proposal,
    create_review_draft_from_monthly_proposal,
    monthly_rebalance_proposal_snapshot_payload,
)
from src.market.paper_rebalance import paper_rebalance_snapshot_payload


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


def _session(month_date: str = "2026-07-15") -> dict:
    return {
        "calendar_date": month_date,
        "market_session_status": "MARKET_OPEN",
        "is_trading_day": True,
        "last_trading_session": month_date,
        "next_trading_session": "2026-07-16",
        "current_intraday_session": month_date,
    }


def _row(
    uid: str = "DYNAMIC_STRATEGY_A",
    *,
    current: float = 0.04,
    recommended: float = 0.06,
    status: str = "ACTIVE_ALLOCATED",
    data_quality: str = "INSTITUTIONAL_SAMPLE",
    ml_status: str = "ML_EVIDENCE_AVAILABLE",
    name: str = "Dynamic Strategy A",
) -> dict:
    return {
        "strategy_uid": uid,
        "strategy_name": name,
        "canonical_status": status,
        "current_weight": current,
        "recommended_weight": recommended,
        "proposed_weight": recommended,
        "evidence_status": "EVIDENCE_AVAILABLE",
        "data_quality": data_quality,
        "ml_status": ml_status,
        "recommendation_reason": "Dynamic monthly proposal input row.",
        "action_status": "INCREASE",
        "lineage_references": {"source": "unit_test_recommendation_artifact"},
    }


def test_monthly_proposal_artifact_created_from_dynamic_rows(tmp_path: Path) -> None:
    root = _copy_root(tmp_path)
    proposal = create_monthly_rebalance_proposal(
        root,
        [_row("DYNAMIC_A"), _row("DYNAMIC_B", recommended=0.03, name="Dynamic Strategy B")],
        portfolio_nav=1_000_000,
        session_state=_session(),
        source_recommendation_artifact="latest_dynamic_recommendation_artifact",
        source_strategy_universe_snapshot="dynamic_snapshot",
    )

    assert proposal["proposal_id"].startswith("monthly-proposal-")
    assert proposal["proposal_month"] == "2026-07"
    assert proposal["status"] == "MONTHLY_PROPOSAL_READY"
    assert proposal["review_status"] == "NOT_APPROVED"
    assert proposal["portfolio_nav_used_for_cost_estimate"] == pytest.approx(1_000_000)
    assert proposal["source_recommendation_artifact"] == "latest_dynamic_recommendation_artifact"
    assert proposal["source_strategy_universe_snapshot"] == "dynamic_snapshot"
    assert [row["strategy_uid"] for row in proposal["rows"]] == ["DYNAMIC_A", "DYNAMIC_B"]
    assert proposal["no_live_orders"] is True
    assert proposal["no_brokerage_orders"] is True
    assert proposal["nav_pnl_impact"] == "NONE_PROPOSAL_ONLY"

    payload = paper_rebalance_snapshot_payload(root)
    assert payload["monthly_proposal"]["latest_proposal"]["proposal_id"] == proposal["proposal_id"]


def test_monthly_proposal_is_one_per_month_unless_force(tmp_path: Path) -> None:
    root = _copy_root(tmp_path)
    first = create_monthly_rebalance_proposal(
        root,
        [_row("DYNAMIC_A")],
        portfolio_nav=1_000_000,
        session_state=_session(),
    )
    same = create_monthly_rebalance_proposal(
        root,
        [_row("DYNAMIC_B")],
        portfolio_nav=1_000_000,
        session_state=_session(),
    )
    forced = create_monthly_rebalance_proposal(
        root,
        [_row("DYNAMIC_C")],
        portfolio_nav=1_000_000,
        session_state=_session(),
        force=True,
    )

    assert same["proposal_id"] == first["proposal_id"]
    assert forced["proposal_id"] != first["proposal_id"]
    payload = monthly_rebalance_proposal_snapshot_payload(root)
    assert [proposal["proposal_month"] for proposal in payload["proposals"]].count("2026-07") == 1
    assert payload["latest_proposal"]["rows"][0]["strategy_uid"] == "DYNAMIC_C"


def test_public_fallback_missing_ml_and_active_unallocated_are_warnings_with_caps(tmp_path: Path) -> None:
    root = _copy_root(tmp_path)
    proposal = create_monthly_rebalance_proposal(
        root,
        [
            _row(
                "ACTIVE_UNALLOCATED_PUBLIC",
                current=0.0,
                recommended=0.12,
                status="ACTIVE_UNALLOCATED",
                data_quality="PUBLIC_FALLBACK_PROTOTYPE_NOT_PIT_NOT_SURVIVORSHIP_BIAS_FREE",
                ml_status="No ML evidence available",
            )
        ],
        portfolio_nav=2_000_000,
        session_state=_session(),
    )
    line = proposal["rows"][0]

    assert line["monthly_proposed_weight"] <= 0.03
    assert "STARTER_CAP_ACTIVE_UNALLOCATED" in line["cap_reason"]
    assert "PROTOTYPE_PUBLIC_DATA_CAP" in line["cap_reason"]
    assert "MISSING_ML_CAP" in line["cap_reason"]
    assert "PUBLIC_FALLBACK" in line["warning_flags"]
    assert "NOT_PIT" in line["warning_flags"]
    assert "NOT_SURVIVORSHIP_FREE" in line["warning_flags"]
    assert "MISSING_ML_OR_EVIDENCE_WARNING" in line["warning_flags"]


def test_monthly_proposal_uses_5bps_cost_formula(tmp_path: Path) -> None:
    root = _copy_root(tmp_path)
    proposal = create_monthly_rebalance_proposal(
        root,
        [_row("DYNAMIC_A", current=0.10, recommended=0.14)],
        portfolio_nav=3_000_000,
        session_state=_session(),
    )
    line = proposal["rows"][0]

    assert line["estimated_trade"] == pytest.approx((0.14 - 0.10) * 3_000_000)
    assert line["estimated_transaction_cost"] == pytest.approx(abs(0.14 - 0.10) * 3_000_000 * 0.0005)
    assert proposal["estimated_total_transaction_cost"] == pytest.approx(line["estimated_transaction_cost"])


@pytest.mark.parametrize(
    "row, message",
    [
        ({**_row(uid=""), "strategy_uid": ""}, "missing canonical strategy_uid"),
        (_row(uid="#000020"), "display_label cannot be used as canonical strategy_uid"),
        ({**_row("PENDING_ROW"), "canonical_status": "PENDING_USER_APPROVAL"}, "pending approval rows"),
        ({**_row("SMOKE_ROW"), "SMOKE_ONLY": True}, "smoke/test rows"),
        ({**_row("FAKE_ROW"), "data_quality": "FAKE_DATA"}, "fake evidence"),
    ],
)
def test_monthly_proposal_hard_blocks_invalid_rows(tmp_path: Path, row: dict, message: str) -> None:
    root = _copy_root(tmp_path)

    with pytest.raises(ValueError, match=message):
        create_monthly_rebalance_proposal(root, [row], portfolio_nav=1_000_000, session_state=_session())


def test_monthly_proposal_does_not_mutate_current_weights_nav_ledger_or_combined(tmp_path: Path) -> None:
    root = _copy_root(tmp_path)
    canonical = root / "dashboard/data/canonical_operational.json"
    before = _digest(canonical)

    proposal = create_monthly_rebalance_proposal(
        root,
        [_row("DYNAMIC_A")],
        portfolio_nav=1_000_000,
        session_state=_session(),
    )
    payload = paper_rebalance_snapshot_payload(root)

    assert _digest(canonical) == before
    assert payload["current_paper_target"] is None
    assert payload["costs"] == []
    assert payload["approved_rebalance"]["latest_plan"] is None
    assert proposal["current_weight_mutation"] is False
    assert proposal["target_weight_mutation"] is False
    assert proposal["paper_ledger_mutation"] is False
    assert proposal["combined_current_mutation"] is False


def test_monthly_proposal_feeds_existing_review_draft_flow(tmp_path: Path) -> None:
    root = _copy_root(tmp_path)
    proposal = create_monthly_rebalance_proposal(
        root,
        [_row("DYNAMIC_A", current=0.01, recommended=0.03)],
        portfolio_nav=1_500_000,
        session_state=_session(),
    )

    draft = create_review_draft_from_monthly_proposal(root, proposal["proposal_id"])

    assert draft["review_status"] == "DRAFT_NOT_APPLIED"
    assert draft["source_recommendation_artifact"] == f"monthly_rebalance_proposal:{proposal['proposal_id']}"
    assert draft["line_items"][0]["strategy_uid"] == "DYNAMIC_A"
    assert draft["line_items"][0]["estimated_transaction_cost"] == pytest.approx(
        abs(0.03 - 0.01) * 1_500_000 * 0.0005
    )
    assert draft["live_trading"] is False
    assert draft["brokerage_execution"] is False


def test_monthly_proposal_source_has_no_production_hardcoded_names_counts_dates() -> None:
    source = Path("src/market/monthly_rebalance_proposal.py").read_text(encoding="utf-8")

    for forbidden in [
        "Copper Equity Proxy Trend",
        "U.S. Stock Low Vol Defensive 63D Top 20",
        "COPX",
        "XME",
        "#000020",
        "2026-06-29",
    ]:
        assert forbidden not in source
