from src.risk.decision_engine import review_decisions


def _strategy(strategy_id: str, side: str, risk_status: str = "ok", blocker: bool = False) -> dict:
    current = 0.50
    proposed = 0.55 if side == "BUY" else 0.45
    return {
        "strategy_id": strategy_id,
        "name": strategy_id,
        "current_weight": current,
        "proposed_weight": proposed,
        "risk_status": risk_status,
        "evidence_status": "evidence_attached",
        "correlation_gate": {"allocation_blocker": blocker},
        "recommended_action": "Keep",
        "rebalance_trade": {"side": side, "estimated_cost": 10.0},
        "net_metrics": {"annual_return": 0.10, "annual_volatility": 0.12},
        "walk_forward": {"positive_window_rate": 0.70},
    }


def _risk(vol: float, sharpe: float) -> dict:
    return {
        "portfolio_volatility": vol,
        "portfolio_var_99": -0.02,
        "portfolio_expected_shortfall_95": -0.025,
        "portfolio_max_drawdown": -0.10,
        "portfolio_sharpe": sharpe,
    }


def test_double_check_blocks_buying_breached_strategy():
    result = review_decisions(
        [_strategy("A", "BUY", risk_status="breach")],
        {
            "proposed_weights": {"A": 1.0},
            "weight_changes": {"A": 0.05},
            "turnover": 0.05,
            "estimated_transaction_cost": 10.0,
            "capital": 1_000_000,
        },
        {"rebalance": {"checks": []}},
        {"portfolio_factor_change": {}},
        _risk(0.10, 0.8),
        _risk(0.09, 0.9),
    )

    assert result["final_decision"] == "Reject / Redesign Proposed Rebalance"
    assert result["strategy_decision_reviews"][0]["allocation_blocked"] is True
    assert result["auto_execution_allowed"] is False


def test_clean_improving_decision_still_requires_human_review():
    result = review_decisions(
        [_strategy("A", "BUY")],
        {
            "proposed_weights": {"A": 1.0},
            "weight_changes": {"A": 0.05},
            "turnover": 0.05,
            "estimated_transaction_cost": 10.0,
            "capital": 1_000_000,
        },
        {"rebalance": {"checks": []}},
        {"portfolio_factor_change": {}},
        _risk(0.10, 0.8),
        _risk(0.09, 0.9),
    )

    assert result["approval_status"] == "pending_human_approval"
    assert result["auto_execution_allowed"] is False
