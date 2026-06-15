"""Tests for rebalance proposal gates."""

from src.allocation.rebalance_gates import evaluate_proposal_gates


def _check(limit_id: str, status: str, value: float) -> dict:
    return {
        "limit_id": limit_id,
        "metric": limit_id,
        "status": status,
        "current_value": value,
        "breach_threshold": 0.5,
    }


def test_blocks_new_hard_breach():
    gates = evaluate_proposal_gates(
        [_check("PORT_VOL", "ok", 0.08)],
        [_check("PORT_VOL", "breach", 0.15)],
        turnover=0.05,
    )
    assert any(g["gate"] == "new_hard_breach" and g["status"] == "breach" for g in gates)


def test_no_gate_when_turnover_zero():
    gates = evaluate_proposal_gates(
        [_check("PORT_VOL", "breach", 0.15)],
        [_check("PORT_VOL", "ok", 0.08)],
        turnover=0.0,
    )
    assert gates[0]["gate"] == "no_allocation_change"


def test_worsened_existing_breach():
    gates = evaluate_proposal_gates(
        [_check("PORT_VOL", "breach", 0.15)],
        [_check("PORT_VOL", "breach", 0.20)],
        turnover=0.03,
    )
    assert any(g["gate"] == "worsened_hard_breach" for g in gates)
