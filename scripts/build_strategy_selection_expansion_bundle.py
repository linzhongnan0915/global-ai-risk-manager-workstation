"""Apply the strategy-selection batch to the committed dashboard research bundle."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.reporting.strategy_factory_research_adapter import _annual_return, _risk_packet
from src.strategies.platform_registry import (
    CHALLENGE_CANDIDATE_IDS,
    CHALLENGE_SELECTION_STATUS,
    COMPOSITE_ID,
    DIVERSIFIED_CANDIDATE_IDS,
    DIVERSIFIED_SELECTION_STATUS,
    EVENT_PANEL_CANDIDATE_IDS,
    EVENT_PANEL_SELECTION_STATUS,
    EXPANDED_SELECTION_CANDIDATE_IDS,
    EXPANDED_SELECTION_STATUS,
    FINAL_DELIVERY_CANDIDATE_IDS,
    FINAL_DELIVERY_SELECTION_STATUS,
    FUNDAMENTAL_RESEARCH_CANDIDATE_IDS,
    FUNDAMENTAL_SELECTION_STATUS,
    OHLCV_ALPHA_CANDIDATE_IDS,
    OHLCV_ALPHA_SELECTION_STATUS,
    STRATEGY_SELECTION_STATUS,
)

BUNDLE_PATH = ROOT / "dashboard/data/us_equity_research_bundle.json"
PACK_ROOT = ROOT / "output/research/final_fundamental_research_v1"
FINAL_ROOT = ROOT / "output/research/final_strategy_research_v1"
DELIVERY_ROOT = ROOT / "output/research/final_platform_delivery_v1"
EXPANDED_ROOT = ROOT / "output/research/final_expanded_selection_v1"
OHLCV_ALPHA_ROOT = ROOT / "output/research/final_ohlcv_alpha_expansion_v1"
DIVERSIFIED_ROOT = ROOT / "output/research/final_diversified_strategy_batch_v1"
CHALLENGE_ROOT = ROOT / "output/research/final_strict_challenge_batch_v1"
EVENT_PANEL_ROOT = ROOT / "output/research/event_panel_final_four_strategy_batch_v1"
ACTIVE_IDS = tuple(
    strategy_id
    for strategy_id, decision in STRATEGY_SELECTION_STATUS.items()
    if decision["status"] == "ACTIVE"
) + tuple(
    strategy_id
    for strategy_id, decision in FUNDAMENTAL_SELECTION_STATUS.items()
    if decision["status"] == "ACTIVE"
) + tuple(
    strategy_id
    for strategy_id, decision in FINAL_DELIVERY_SELECTION_STATUS.items()
    if decision["status"] == "ACTIVE"
) + tuple(
    strategy_id
    for strategy_id, decision in EXPANDED_SELECTION_STATUS.items()
    if decision["status"] == "ACTIVE"
) + tuple(
    strategy_id
    for strategy_id, decision in OHLCV_ALPHA_SELECTION_STATUS.items()
    if decision["status"] == "ACTIVE"
) + tuple(
    strategy_id
    for strategy_id, decision in DIVERSIFIED_SELECTION_STATUS.items()
    if decision["status"] == "ACTIVE"
) + tuple(
    strategy_id
    for strategy_id, decision in CHALLENGE_SELECTION_STATUS.items()
    if decision["status"] == "ACTIVE" and strategy_id not in EVENT_PANEL_CANDIDATE_IDS
) + tuple(
    strategy_id
    for strategy_id, decision in EVENT_PANEL_SELECTION_STATUS.items()
    if decision["status"] == "ACTIVE"
)


def _series_metrics(returns: pd.Series) -> dict[str, float]:
    packet = _risk_packet(
        returns,
        pd.Series(0.0, index=returns.index),
        pd.Series(0.0, index=returns.index),
        pd.DataFrame(index=returns.index),
    )
    return {
        "cumulative_return": float(returns.add(1).prod() - 1),
        "annual_return": float(_annual_return(returns)),
        "annual_volatility": float(packet["summary_statistics"]["annual_volatility"]),
        "sharpe": float(packet["summary_statistics"]["sharpe"]),
        "max_drawdown": float(packet["drawdown_behavior"]["max_drawdown"]),
    }


def _apply_old_statuses(results: list[dict]) -> None:
    for item in results:
        strategy_id = item["strategy_id"]
        if strategy_id not in STRATEGY_SELECTION_STATUS:
            continue
        decision = STRATEGY_SELECTION_STATUS[strategy_id]
        status = decision["status"]
        backtest = item["backtest"]
        factory = backtest["factory_research"]
        eligible = status == "ACTIVE"
        item["research_group"] = status
        backtest["lifecycle_status"] = status
        backtest["research_composite_eligible"] = eligible
        factory["membership"] = status
        factory["research_status"] = status
        factory["research_composite_eligible"] = eligible
        factory["composite_eligible"] = eligible
        factory["decision_reason"] = decision["reason"]
        backtest["action"] = {
            "action": "Use in research composite" if eligible else status,
            "reason_code": status.lower(),
            "interpretation": decision["reason"],
        }


def _candidate_items(correlation: pd.DataFrame) -> list[dict]:
    summary = pd.read_csv(PACK_ROOT / "candidate_summary.csv").set_index("strategy_id")
    daily = pd.read_csv(PACK_ROOT / "daily_net_returns.csv", parse_dates=["date"])
    holdings = pd.read_csv(PACK_ROOT / "holdings.csv")
    trades = pd.read_csv(PACK_ROOT / "trade_log.csv")
    regimes = pd.read_csv(FINAL_ROOT / "market_proxy_regime_v0.csv")
    manifest = json.loads((PACK_ROOT / "run_manifest.json").read_text(encoding="utf-8"))
    candidate_ids = [value for value in FUNDAMENTAL_RESEARCH_CANDIDATE_IDS if value not in EXPANDED_SELECTION_CANDIDATE_IDS]
    retained_corr = correlation.loc[candidate_ids, list(ACTIVE_IDS)]
    output = []
    for strategy_id in candidate_ids:
        row = summary.loc[strategy_id]
        returns = daily.loc[daily["strategy_id"] == strategy_id].sort_values("date")
        net = pd.Series(returns["net_return"].values, index=returns["date"])
        gross = pd.Series(returns["gross_return"].values, index=returns["date"])
        turnover = pd.Series(returns["turnover"].values, index=returns["date"])
        packet = _risk_packet(net, pd.Series(0.0, index=net.index), turnover, pd.DataFrame(index=net.index))
        candidate_holdings = holdings.loc[holdings["strategy_id"] == strategy_id]
        latest_holdings_date = candidate_holdings["date"].max()
        latest_holdings = candidate_holdings.loc[candidate_holdings["date"].eq(latest_holdings_date)]
        holdings_packet = {
            "last_rebalance_date": latest_holdings_date,
            "current_long_holdings": latest_holdings.loc[latest_holdings["side"].eq("LONG"), ["ticker", "target_weight"]]
            .rename(columns={"target_weight": "weight"}).assign(side="long").to_dict(orient="records"),
            "current_short_holdings": latest_holdings.loc[latest_holdings["side"].eq("SHORT"), ["ticker", "target_weight"]]
            .rename(columns={"target_weight": "weight"}).assign(side="short").to_dict(orient="records"),
        }
        strategy_trades = trades.loc[trades["strategy_id"] == strategy_id]
        trade_log = {
            "status": "SIMULATED | RESEARCH ONLY | NO LIVE FILL",
            "execution_enabled": False,
            "record_count": int(len(strategy_trades)),
            "estimated_transaction_cost": float(strategy_trades["estimated_transaction_cost"].sum()),
            "latest_records": strategy_trades.tail(25).to_dict(orient="records"),
        }
        strategy_regimes = regimes.loc[regimes["strategy_id"] == strategy_id].to_dict(orient="records")
        decision = FUNDAMENTAL_SELECTION_STATUS[strategy_id]
        status = decision["status"]
        eligible = status == "ACTIVE"
        corr_row = retained_corr.loc[strategy_id].abs()
        output.append(
            {
                "research_group": status,
                "strategy_id": strategy_id,
                "backtest": {
                    "strategy_id": strategy_id,
                    "name": strategy_id.replace("_", " ").title(),
                    "literature_source": "SEC point-in-time fundamental expansion batch",
                    "research_source": manifest["pack_id"],
                    "hypothesis": "; ".join(manifest["candidate_formulas"][strategy_id]),
                    "universe": manifest["universe_rule"],
                    "rebalance": "Every 20 trading days",
                    "signal_summary": "; ".join(manifest["candidate_formulas"][strategy_id]),
                    "failure_modes": "Current-listed diagnostic universe; survivorship bias present.",
                    "observations": int(row["observations"]),
                    "asset_class": "US individual equities",
                    "strategy_family": "point_in_time_fundamental",
                    "lifecycle_status": status,
                    "allocation_eligible": False,
                    "live_allocation_approved": False,
                    "execution_enabled": False,
                    "research_composite_eligible": eligible,
                    "test_period_start": row["test_period_start"],
                    "test_period_end": row["test_period_end"],
                    "latest_data_date": row["test_period_end"],
                    "gross_metrics": {
                        "cumulative_return": float(row["gross_cumulative_return"]),
                        "annual_return": float(_annual_return(gross)),
                    },
                    "net_metrics": {
                        "cumulative_return": float(row["net_cumulative_return"]),
                        "annual_return": float(row["annualized_net_return"]),
                        "annual_volatility": float(row["annualized_volatility"]),
                        "sharpe": float(row["net_sharpe"]),
                        "max_drawdown": float(row["max_drawdown"]),
                    },
                    "turnover": {
                        "average_daily_turnover": float(row["average_daily_turnover"]),
                        "annualized_turnover": float(row["annualized_turnover"]),
                        "total_cost_drag": float(row["total_cost_drag"]),
                        "annualized_cost_drag": float(returns["transaction_cost"].mean() * 252),
                    },
                    "return_series": {
                        "dates": [date.date().isoformat() for date in returns["date"]],
                        "gross_returns": [round(float(value), 6) for value in gross],
                        "net_returns": [round(float(value), 6) for value in net],
                    },
                    "risk_packet": {
                        "summary_statistics": packet["summary_statistics"],
                        "drawdown_behavior": packet["drawdown_behavior"],
                        "chart_series": {
                            "drawdown": packet["chart_series"]["drawdown"],
                            "rolling_63d_sharpe": packet["chart_series"]["rolling_63d_sharpe"],
                        },
                    },
                    "action": {
                        "action": status,
                        "reason_code": status.lower(),
                        "interpretation": decision["reason"],
                    },
                    "holdings": holdings_packet,
                    "factory_research": {
                        "membership": status,
                        "research_status": status,
                        "research_composite_eligible": eligible,
                        "composite_eligible": eligible,
                        "live_allocation_approved": False,
                        "decision_reason": decision["reason"],
                        "limitations": [
                            "CURRENT_LISTED_DIAGNOSTIC",
                            "SURVIVORSHIP_BIAS_PRESENT",
                            "SEC XBRL tag and filing coverage varies by issuer.",
                        ],
                        "data_labels": ["CURRENT_LISTED_DIAGNOSTIC", "SURVIVORSHIP_BIAS_PRESENT"],
                        "simulated_trade_log": trade_log,
                        "market_proxy_regime_v0": strategy_regimes,
                        "regime_disclosure": "MARKET_PROXY_REGIME_V0 uses lagged SPY/TIP/IEF market proxies; it is not a true macro Growth x Inflation model.",
                        "preliminary_oos_start": row["preliminary_oos_start"],
                        "preliminary_oos_net_return": float(row["preliminary_oos_net_return"]),
                        "preliminary_oos_sharpe": float(row["preliminary_oos_sharpe"]),
                        "average_abs_correlation_with_retained": float(corr_row.mean()),
                        "max_abs_correlation_with_retained": float(corr_row.max()),
                        "highest_corr_retained_strategy": str(corr_row.idxmax()),
                        "trade_cost_reconciliation_error": float(row["trade_cost_reconciliation_error"]),
                    },
                },
                "walk_forward": {
                    "windows": [],
                    "status": "PRELIMINARY CHRONOLOGICAL OOS ONLY",
                    "number_of_windows": 1,
                    "positive_window_rate": float(row["preliminary_oos_net_return"] > 0),
                    "average_test_sharpe": float(row["preliminary_oos_sharpe"]),
                },
            }
        )
    return output


def _delivery_items(
    correlation: pd.DataFrame, shared_dates: list[str], *,
    candidate_ids: tuple[str, ...] = FINAL_DELIVERY_CANDIDATE_IDS,
    decisions: dict[str, dict[str, str]] = FINAL_DELIVERY_SELECTION_STATUS,
    pack_root: Path = DELIVERY_ROOT,
    research_source: str = "FINAL_PLATFORM_DELIVERY_RESEARCH_V1",
) -> list[dict]:
    summary = pd.read_csv(pack_root / "candidate_summary.csv").set_index("strategy_id")
    daily = pd.read_csv(pack_root / "daily_strategy_returns.csv", parse_dates=["date"])
    holdings = pd.read_csv(pack_root / "holdings.csv")
    trades = pd.read_csv(pack_root / "trade_log.csv")
    regimes = pd.read_csv(pack_root / "market_proxy_regime_v0.csv")
    output = []
    for strategy_id in candidate_ids:
        row = summary.loc[strategy_id]
        decision = decisions[strategy_id]
        status = decision["status"]
        eligible = status == "ACTIVE"
        strategy_daily = daily.loc[daily["strategy_id"].eq(strategy_id)].sort_values("date")
        strategy_holdings = holdings.loc[holdings["strategy_id"].eq(strategy_id)]
        strategy_trades = trades.loc[trades["strategy_id"].eq(strategy_id)]
        if strategy_daily.empty:
            gross = net = turnover = pd.Series(dtype=float)
            metrics = {"cumulative_return": None, "annual_return": None, "annual_volatility": None, "sharpe": None, "max_drawdown": None}
            packet = {"summary_statistics": {}, "drawdown_behavior": {}, "chart_series": {"drawdown": [], "rolling_63d_sharpe": []}}
            return_series = {"dates": [], "gross_returns": [], "net_returns": []}
        else:
            net = pd.Series(strategy_daily["net_return"].values, index=strategy_daily["date"])
            gross = pd.Series(strategy_daily["gross_return"].values, index=strategy_daily["date"])
            turnover = pd.Series(strategy_daily["turnover"].values, index=strategy_daily["date"])
            risk = _risk_packet(net, pd.Series(0.0, index=net.index), turnover, pd.DataFrame(index=net.index))
            metrics = {
                "cumulative_return": float(row["net_cumulative_return"]), "annual_return": float(row["annualized_net_return"]),
                "annual_volatility": float(row["annualized_volatility"]), "sharpe": float(row["net_sharpe"]),
                "max_drawdown": float(row["max_drawdown"]),
            }
            packet = {
                "summary_statistics": risk["summary_statistics"], "drawdown_behavior": risk["drawdown_behavior"],
                "chart_series": {"drawdown": risk["chart_series"]["drawdown"], "rolling_63d_sharpe": risk["chart_series"]["rolling_63d_sharpe"]},
            }
            return_series = {
                "dates": [date.date().isoformat() for date in strategy_daily["date"]],
                "gross_returns": [round(float(value), 6) for value in gross],
                "net_returns": [round(float(value), 6) for value in net],
            }
        latest_date = strategy_holdings["date"].max() if not strategy_holdings.empty else None
        latest = strategy_holdings.loc[strategy_holdings["date"].eq(latest_date)] if latest_date else strategy_holdings
        corr_row = correlation.loc[strategy_id, list(ACTIVE_IDS)].abs() if strategy_id in correlation.index else pd.Series(dtype=float)
        output.append(
            {
                "research_group": status,
                "strategy_id": strategy_id,
                "backtest": {
                    "strategy_id": strategy_id, "name": strategy_id.replace("_", " ").title(),
                    "literature_source": "Final platform delivery diagnostic batch",
                    "research_source": research_source,
                    "hypothesis": str(row["economic_rationale"]), "signal_summary": str(row["economic_rationale"]),
                    "universe": str(row["actual_universe_used"]), "rebalance": "Every 20 trading days",
                    "failure_modes": str(row["classification_reason"]), "asset_class": "US individual equities",
                    "strategy_family": "final_delivery_diagnostic", "lifecycle_status": status,
                    "allocation_eligible": False, "live_allocation_approved": False, "execution_enabled": False,
                    "research_composite_eligible": eligible,
                    "gross_metrics": {"cumulative_return": None if strategy_daily.empty else float(row["gross_cumulative_return"]), "annual_return": None if strategy_daily.empty else float(_annual_return(gross))},
                    "net_metrics": metrics,
                    "turnover": {
                        "average_daily_turnover": None if strategy_daily.empty else float(row["average_daily_turnover"]),
                        "annualized_turnover": None if strategy_daily.empty else float(row["annualized_turnover"]),
                        "total_cost_drag": None if strategy_daily.empty else float(row["total_cost_drag"]),
                    },
                    "return_series": return_series, "risk_packet": packet,
                    "action": {"action": status, "reason_code": status.lower(), "interpretation": decision["reason"]},
                    "holdings": {
                        "last_rebalance_date": latest_date,
                        "current_long_holdings": latest.loc[latest["side"].eq("LONG"), ["ticker", "target_weight"]].rename(columns={"target_weight": "weight"}).assign(side="long").to_dict(orient="records"),
                        "current_short_holdings": latest.loc[latest["side"].eq("SHORT"), ["ticker", "target_weight"]].rename(columns={"target_weight": "weight"}).assign(side="short").to_dict(orient="records"),
                    },
                    "factory_research": {
                        "membership": status, "research_status": status, "research_composite_eligible": eligible,
                        "composite_eligible": eligible, "live_allocation_approved": False, "decision_reason": decision["reason"],
                        "limitations": ["CURRENT_LISTED_DIAGNOSTIC", "SURVIVORSHIP_BIAS_PRESENT", str(row["classification_reason"])],
                        "data_labels": ["CURRENT_LISTED_DIAGNOSTIC", "SURVIVORSHIP_BIAS_PRESENT", "RESEARCH ONLY"],
                        "simulated_trade_log": {
                            "status": "SIMULATED | RESEARCH ONLY | NO LIVE FILL", "execution_enabled": False,
                            "record_count": int(len(strategy_trades)),
                            "estimated_transaction_cost": float(strategy_trades["estimated_transaction_cost"].sum()) if not strategy_trades.empty else 0.0,
                            "latest_records": strategy_trades.tail(25).to_dict(orient="records"),
                        },
                        "market_proxy_regime_v0": regimes.loc[regimes["strategy_id"].eq(strategy_id)].to_dict(orient="records"),
                        "regime_disclosure": "MARKET_PROXY_REGIME_V0 uses lagged SPY/TIP/IEF market proxies; it is not a true macro Growth x Inflation model.",
                        "preliminary_oos_net_return": None if strategy_daily.empty else float(row["preliminary_oos_net_return"]),
                        "preliminary_oos_sharpe": None if strategy_daily.empty else float(row["preliminary_oos_sharpe"]),
                        "double_cost_net_return": None if strategy_daily.empty else float(row["double_cost_net_return"]),
                        "delayed_execution_net_return": None if strategy_daily.empty else float(row["delayed_execution_net_return"]),
                        "average_abs_correlation_with_retained": None if corr_row.empty else float(corr_row.mean()),
                        "max_abs_correlation_with_retained": None if corr_row.empty else float(corr_row.max()),
                        "marginal_combined_portfolio_sharpe": None if strategy_daily.empty else float(row["marginal_combined_portfolio_sharpe"]),
                        "marginal_max_drawdown_improvement": None if strategy_daily.empty or "marginal_max_drawdown_improvement" not in row else float(row["marginal_max_drawdown_improvement"]),
                        "marginal_left_tail_improvement": None if strategy_daily.empty or "marginal_left_tail_improvement" not in row else float(row["marginal_left_tail_improvement"]),
                        "latest_estimated_market_beta_exposure": None if strategy_daily.empty or "latest_estimated_market_beta_exposure" not in row else float(row["latest_estimated_market_beta_exposure"]),
                        "trade_cost_reconciliation_error": None if strategy_daily.empty else float(row["trade_cost_reconciliation_error"]),
                    },
                },
                "walk_forward": {"windows": [], "status": "PRELIMINARY CHRONOLOGICAL OOS ONLY", "number_of_windows": 1 if not strategy_daily.empty else 0},
            }
        )
    return output


def _rebuild_composite(results: list[dict], shared_dates: list[str]) -> None:
    by_id = {item["strategy_id"]: item for item in results}
    active = [by_id[strategy_id] for strategy_id in ACTIVE_IDS]
    weight = 1.0 / len(active)
    shared_index = pd.to_datetime(shared_dates)

    def aligned_series(item: dict, field: str) -> pd.Series:
        series = item["backtest"]["return_series"]
        dates = pd.to_datetime(series.get("dates") or shared_dates[: len(series[field])])
        return pd.Series(series[field], index=dates).reindex(shared_index, fill_value=0.0)

    gross = pd.DataFrame(
        {item["strategy_id"]: aligned_series(item, "gross_returns") for item in active},
        index=shared_index,
    ).mean(axis=1)
    net_panel = pd.DataFrame(
        {item["strategy_id"]: aligned_series(item, "net_returns") for item in active},
        index=shared_index,
    )
    net = net_panel.mean(axis=1)
    corr = net_panel.corr()
    pairwise = [
        {"strategy_left": left, "strategy_right": right, "correlation": float(corr.loc[left, right])}
        for pos, left in enumerate(ACTIVE_IDS)
        for right in ACTIVE_IDS[pos + 1 :]
    ]
    item = by_id[COMPOSITE_ID]
    backtest = item["backtest"]
    packet = _risk_packet(net, pd.Series(0.0, index=net.index), pd.Series(0.0, index=net.index), pd.DataFrame(index=net.index))
    item["research_group"] = "COMBINED_PORTFOLIO"
    backtest["hypothesis"] = f"Equal-weight composite of all {len(active)} eligible ACTIVE underlying strategies - research only."
    backtest["universe"] = f"Composite of {len(active)} active US-equity research strategies"
    backtest["rebalance"] = f"Dynamic equal weight 1/N where N={len(active)}"
    backtest["gross_metrics"] = {
        "cumulative_return": float(gross.add(1).prod() - 1),
        "annual_return": float(_annual_return(gross)),
    }
    backtest["net_metrics"] = _series_metrics(net)
    member_cost_drag = [member["backtest"]["turnover"]["total_cost_drag"] for member in active]
    member_turnover = [member["backtest"]["turnover"]["average_daily_turnover"] for member in active]
    backtest["turnover"] = {
        "average_daily_turnover": float(sum(member_turnover) * weight),
        "annualized_turnover": float(sum(member_turnover) * weight * 252),
        "total_cost_drag": float(sum(member_cost_drag) * weight),
        "annualized_cost_drag": float(sum(member_cost_drag) * weight / len(net) * 252),
    }
    backtest["return_series"] = {
        "gross_returns": [round(float(value), 6) for value in gross],
        "net_returns": [round(float(value), 6) for value in net],
    }
    backtest["risk_packet"] = {
        "summary_statistics": packet["summary_statistics"],
        "drawdown_behavior": packet["drawdown_behavior"],
        "chart_series": {
            "drawdown": packet["chart_series"]["drawdown"],
            "rolling_63d_sharpe": packet["chart_series"]["rolling_63d_sharpe"],
        },
    }
    composite = {
        "N": len(active),
        "equal_weight": weight,
        "weight_formula": "weight_i = 1 / N",
        "dynamic_membership": True,
        "membership_rule": "Includes ACTIVE strategies only; equal-weight 1/N.",
        "members": [
            {
                "strategy_id": member["strategy_id"],
                "name": member["backtest"]["name"],
                "weight": weight,
                "sharpe": member["backtest"]["net_metrics"]["sharpe"],
                "research_status": "ACTIVE",
                "membership": "ACTIVE",
            }
            for member in active
        ],
        "constituent_ids": list(ACTIVE_IDS),
        "eligible_member_ids": list(ACTIVE_IDS),
        "reference_only_ids": [
            row["strategy_id"]
            for row in results
            if row["backtest"]["factory_research"].get("membership") != "ACTIVE"
            and row["strategy_id"] != COMPOSITE_ID
        ],
        "current_constituents": [
            {"strategy_id": strategy_id, "weight": weight, "side": "constituent"}
            for strategy_id in ACTIVE_IDS
        ],
        "weights": {strategy_id: weight for strategy_id in ACTIVE_IDS},
        "constituent_sharpes": {
            member["strategy_id"]: member["backtest"]["net_metrics"]["sharpe"] for member in active
        },
        "pairwise_analysis": pairwise,
        "correlation_matrix": corr.to_dict(),
        "common_start_date": shared_dates[0],
        "common_end_date": shared_dates[-1],
    }
    backtest["factory_research"]["combined_portfolio"] = composite
    backtest["factory_research"]["strategy_21"] = composite
    backtest["factory_research"]["decision_reason"] = (
        f"Equal-weight Combined Portfolio of {len(active)} ACTIVE strategies; research only."
    )


def build_bundle() -> dict:
    payload = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))
    catalog = payload["factory_strategy_research"]
    results = catalog["results"]
    _apply_old_statuses(results)
    results[:] = [item for item in results if item["strategy_id"] not in FUNDAMENTAL_RESEARCH_CANDIDATE_IDS]
    results[:] = [item for item in results if item["strategy_id"] not in FINAL_DELIVERY_CANDIDATE_IDS]
    results[:] = [item for item in results if item["strategy_id"] not in EXPANDED_SELECTION_CANDIDATE_IDS]
    results[:] = [item for item in results if item["strategy_id"] not in OHLCV_ALPHA_CANDIDATE_IDS]
    results[:] = [item for item in results if item["strategy_id"] not in DIVERSIFIED_CANDIDATE_IDS]
    results[:] = [item for item in results if item["strategy_id"] not in CHALLENGE_CANDIDATE_IDS]
    results[:] = [item for item in results if item["strategy_id"] not in EVENT_PANEL_CANDIDATE_IDS]
    fundamental_daily = pd.read_csv(PACK_ROOT / "daily_net_returns.csv", parse_dates=["date"])
    fundamental_returns = fundamental_daily.pivot(index="date", columns="strategy_id", values="net_return")
    fundamental_returns = fundamental_returns.drop(columns=list(EXPANDED_SELECTION_CANDIDATE_IDS), errors="ignore")
    existing_returns = pd.DataFrame(
        {
            item["strategy_id"]: item["backtest"]["return_series"]["net_returns"]
            for item in results
            if item["strategy_id"] != COMPOSITE_ID
        },
        index=pd.to_datetime(payload["shared_dates"]),
    )
    delivery_daily = pd.read_csv(DELIVERY_ROOT / "daily_strategy_returns.csv", parse_dates=["date"])
    delivery_returns = delivery_daily.pivot(index="date", columns="strategy_id", values="net_return")
    delivery_returns = delivery_returns.drop(columns=list(EXPANDED_SELECTION_CANDIDATE_IDS), errors="ignore")
    expanded_daily = pd.read_csv(EXPANDED_ROOT / "daily_strategy_returns.csv", parse_dates=["date"])
    expanded_returns = expanded_daily.pivot(index="date", columns="strategy_id", values="net_return")
    ohlcv_alpha_daily = pd.read_csv(OHLCV_ALPHA_ROOT / "daily_strategy_returns.csv", parse_dates=["date"])
    ohlcv_alpha_returns = ohlcv_alpha_daily.pivot(index="date", columns="strategy_id", values="net_return")
    diversified_daily = pd.read_csv(DIVERSIFIED_ROOT / "daily_strategy_returns.csv", parse_dates=["date"])
    diversified_returns = diversified_daily.pivot(index="date", columns="strategy_id", values="net_return")
    challenge_daily = pd.read_csv(CHALLENGE_ROOT / "daily_strategy_returns.csv", parse_dates=["date"])
    challenge_returns = challenge_daily.pivot(index="date", columns="strategy_id", values="net_return")
    challenge_returns = challenge_returns.drop(columns=list(EVENT_PANEL_CANDIDATE_IDS), errors="ignore")
    event_daily = pd.read_csv(EVENT_PANEL_ROOT / "daily_strategy_returns.csv", parse_dates=["date"])
    event_returns = event_daily.pivot(index="date", columns="strategy_id", values="net_return")
    correlation = pd.concat([fundamental_returns, delivery_returns, expanded_returns, ohlcv_alpha_returns, diversified_returns, challenge_returns, event_returns, existing_returns], axis=1, join="inner").corr()
    composite = next(item for item in results if item["strategy_id"] == COMPOSITE_ID)
    results.remove(composite)
    results.extend(_candidate_items(correlation))
    original_delivery_ids = tuple(value for value in FINAL_DELIVERY_CANDIDATE_IDS if value not in EXPANDED_SELECTION_CANDIDATE_IDS)
    results.extend(_delivery_items(correlation, payload["shared_dates"], candidate_ids=original_delivery_ids))
    results.extend(_delivery_items(
        correlation, payload["shared_dates"], candidate_ids=EXPANDED_SELECTION_CANDIDATE_IDS,
        decisions=EXPANDED_SELECTION_STATUS, pack_root=EXPANDED_ROOT,
        research_source="FINAL_EXPANDED_SELECTION_V1",
    ))
    results.extend(_delivery_items(
        correlation, payload["shared_dates"], candidate_ids=OHLCV_ALPHA_CANDIDATE_IDS,
        decisions=OHLCV_ALPHA_SELECTION_STATUS, pack_root=OHLCV_ALPHA_ROOT,
        research_source="FINAL_OHLCV_ALPHA_EXPANSION_V1",
    ))
    results.extend(_delivery_items(
        correlation, payload["shared_dates"], candidate_ids=DIVERSIFIED_CANDIDATE_IDS,
        decisions=DIVERSIFIED_SELECTION_STATUS, pack_root=DIVERSIFIED_ROOT,
        research_source="FINAL_DIVERSIFIED_STRATEGY_BATCH_V1",
    ))
    results.extend(_delivery_items(
        correlation, payload["shared_dates"], candidate_ids=tuple(value for value in CHALLENGE_CANDIDATE_IDS if value not in EVENT_PANEL_CANDIDATE_IDS),
        decisions=CHALLENGE_SELECTION_STATUS, pack_root=CHALLENGE_ROOT,
        research_source="FINAL_STRICT_CHALLENGE_BATCH_V1",
    ))
    results.extend(_delivery_items(
        correlation, payload["shared_dates"], candidate_ids=EVENT_PANEL_CANDIDATE_IDS,
        decisions=EVENT_PANEL_SELECTION_STATUS, pack_root=EVENT_PANEL_ROOT,
        research_source="EVENT_PANEL_FINAL_FOUR_STRATEGY_BATCH_V1",
    ))
    results.append(composite)
    _rebuild_composite(results, payload["shared_dates"])
    counts = {
        status: sum(
            item["backtest"]["factory_research"].get("membership") == status for item in results
        )
        for status in ("ACTIVE", "REPAIR", "RESEARCH_CANDIDATE", "REFERENCE_ONLY", "ARCHIVED", "DATA_INSUFFICIENT")
    }
    arch = catalog["architecture"]
    arch.update(
        {
            "research_composite_eligible_count": counts["ACTIVE"],
            "eligible_active_count": counts["ACTIVE"],
            "composite_constituent_count": counts["ACTIVE"],
            "composite_equal_weight": 1.0 / counts["ACTIVE"],
            "tested_candidate_count": len(results) - 1,
            "active_retained_count": counts["ACTIVE"],
            "repair_count": counts["REPAIR"],
            "research_candidate_count": counts["RESEARCH_CANDIDATE"],
            "reference_only_count": counts["REFERENCE_ONLY"],
            "archived_count": counts["ARCHIVED"],
            "data_insufficient_count": counts["DATA_INSUFFICIENT"],
        }
    )
    catalog["groups"] = [
        {"id": "ACTIVE", "label": "ACTIVE"},
        {"id": "REPAIR", "label": "REPAIR"},
        {"id": "RESEARCH_CANDIDATE", "label": "RESEARCH CANDIDATE"},
        {"id": "DATA_INSUFFICIENT", "label": "DATA INSUFFICIENT"},
        {"id": "REFERENCE_ARCHIVED", "label": "REFERENCE ONLY / ARCHIVED"},
        {"id": "COMBINED_PORTFOLIO", "label": "Combined Portfolio"},
    ]
    catalog["results_count"] = len(results)
    catalog["source"] = "accepted_final_strategy_research_integration_v1"
    catalog["market_proxy_regime"] = {
        "id": "MARKET_PROXY_REGIME_V0",
        "disclosure": "Lagged SPY/TIP/IEF market-proxy analysis only; not a true macro Growth x Inflation model.",
        "alters_weights": False,
    }
    catalog["execution_enabled"] = False
    catalog["live_allocation_percent"] = 0.0
    payload["bundle_version"] = 4
    return payload


def main() -> int:
    payload = build_bundle()
    BUNDLE_PATH.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    composite = next(
        row for row in payload["factory_strategy_research"]["results"]
        if row["strategy_id"] == COMPOSITE_ID
    )["backtest"]["factory_research"]["combined_portfolio"]
    for manifest_path in (
        DELIVERY_ROOT / "run_manifest.json", EXPANDED_ROOT / "run_manifest.json",
        OHLCV_ALPHA_ROOT / "run_manifest.json",
        DIVERSIFIED_ROOT / "run_manifest.json",
        CHALLENGE_ROOT / "run_manifest.json",
        EVENT_PANEL_ROOT / "run_manifest.json",
    ):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.update(
            {
                "registry_updated": True, "bundle_updated": True, "dashboard_updated": True,
                "combined_portfolio_updated": True, "combined_portfolio_N": composite["N"],
                "combined_portfolio_equal_weight": composite["equal_weight"],
            }
        )
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote {BUNDLE_PATH} ({payload['factory_strategy_research']['results_count']} results)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
