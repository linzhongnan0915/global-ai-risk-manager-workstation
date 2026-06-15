"""Export risk-manager decision tables from the dashboard artifact."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    artifact_path = PROJECT_ROOT / "output/dashboard_artifact.json"
    if not artifact_path.exists():
        raise FileNotFoundError("output/dashboard_artifact.json does not exist; run generate_dashboard_artifact first")
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    output_dir = PROJECT_ROOT / "output/risk_manager_tables"
    output_dir.mkdir(parents=True, exist_ok=True)

    strategies = artifact.get("strategies", [])
    decision_rows = [_decision_row(strategy) for strategy in strategies]
    factor_rows = [_factor_row(strategy) for strategy in strategies]
    strategy_names = {strategy["strategy_id"]: strategy["name"] for strategy in strategies}
    breach_rows = [
        {
            "strategy_id": check.get("scope") if check.get("scope") in strategy_names else None,
            "strategy": strategy_names.get(check.get("scope")),
            **check,
        }
        for check in artifact.get("risk_limits", {}).get("checks", [])
        if check.get("status") != "ok"
    ]
    position_rows = [
        {
            "strategy_id": strategy["strategy_id"],
            "strategy": strategy["name"],
            "ticker": position["ticker"],
            "weight": position["weight"],
        }
        for strategy in strategies
        for position in strategy.get("position_packet", {}).get("latest_positions", [])
    ]

    pd.DataFrame(decision_rows).to_csv(output_dir / "strategy_decision_table.csv", index=False)
    pd.DataFrame(factor_rows).fillna(0.0).to_csv(output_dir / "strategy_factor_exposure_matrix.csv", index=False)
    pd.DataFrame(breach_rows).to_csv(output_dir / "risk_limit_watchlist.csv", index=False)
    pd.DataFrame(position_rows).to_csv(output_dir / "latest_strategy_positions.csv", index=False)
    (output_dir / "daily_decision_log.json").write_text(
        json.dumps(artifact.get("daily_decision_log", []), indent=2),
        encoding="utf-8",
    )
    (output_dir / "institutional_decision_workflow.json").write_text(
        json.dumps(artifact.get("decision_workflow", {}), indent=2),
        encoding="utf-8",
    )
    (output_dir / "independent_risk_review.json").write_text(
        json.dumps(artifact.get("decision_review", {}), indent=2),
        encoding="utf-8",
    )
    print(f"Exported risk manager tables to {output_dir}")


def _decision_row(strategy: dict) -> dict:
    net = strategy.get("net_metrics", {})
    tail = strategy.get("risk_packet", {}).get("tail_risk", {})
    drawdown = strategy.get("risk_packet", {}).get("drawdown_behavior", {})
    wfo = strategy.get("walk_forward", {})
    factor = strategy.get("factor_exposure", {}).get("concentration", {})
    peer = strategy.get("risk_packet", {}).get("comparison_vs_other_strategies", {})
    top_peer = (peer.get("top_correlations") or [{}])[0]
    trade = strategy.get("rebalance_trade", {})
    return {
        "strategy_id": strategy.get("strategy_id"),
        "strategy": strategy.get("name"),
        "type": strategy.get("strategy_type"),
        "current_weight": strategy.get("current_weight"),
        "proposed_weight": strategy.get("proposed_weight"),
        "allocation_change": strategy.get("allocation_change"),
        "recommended_action": strategy.get("recommended_action"),
        "final_action_after_double_check": strategy.get("final_action_after_double_check"),
        "allocation_blocked": strategy.get("decision_review", {}).get("allocation_blocked"),
        "trade_decision": strategy.get("trade_decision", {}).get("action"),
        "risk_status": strategy.get("risk_status"),
        "evidence_status": strategy.get("evidence_status"),
        "sharpe": net.get("sharpe"),
        "annual_return": net.get("annual_return"),
        "annual_volatility": net.get("annual_volatility"),
        "max_drawdown": net.get("max_drawdown"),
        "current_drawdown": drawdown.get("current_drawdown"),
        "var_99": tail.get("var_99"),
        "expected_shortfall_95": tail.get("expected_shortfall_95"),
        "annualized_turnover": strategy.get("turnover", {}).get("annualized_turnover"),
        "annualized_cost_drag": strategy.get("turnover", {}).get("annualized_cost_drag"),
        "wfo_windows": wfo.get("number_of_windows"),
        "wfo_average_test_sharpe": wfo.get("average_test_sharpe"),
        "wfo_positive_window_rate": wfo.get("positive_window_rate"),
        "top_factor": factor.get("top_factor"),
        "top_factor_abs_exposure": factor.get("top_abs_exposure"),
        "highest_peer_correlation_strategy": top_peer.get("name"),
        "highest_peer_correlation": top_peer.get("correlation"),
        "trade_side": trade.get("side"),
        "trade_notional": trade.get("notional"),
        "estimated_trade_cost": trade.get("estimated_cost"),
        "human_approval_required": strategy.get("human_approval_required"),
    }


def _factor_row(strategy: dict) -> dict:
    row = {
        "strategy_id": strategy.get("strategy_id"),
        "strategy": strategy.get("name"),
    }
    row.update(strategy.get("factor_exposure", {}).get("latest", {}))
    return row


if __name__ == "__main__":
    main()
