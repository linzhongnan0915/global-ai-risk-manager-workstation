"""Adapt Strategy Factory artifacts into Research Lab literature-compatible payloads."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from src.strategies.composite_membership import passes_composite_gate
from src.strategies.platform_registry import COMPOSITE_ID, RAPID_BACKTEST_IDS, SPEC_BY_ID
from src.strategies.literature_backtests import TRADING_DAYS, _annual_return, _risk_packet
from src.strategies.strategy_factory import StrategySpec

FACTORY_STRATEGY_IDS = RAPID_BACKTEST_IDS
DEFAULT_STRATEGY_ID = "C2A2_020"


def _research_composite_eligible(summary: dict[str, Any], board: dict[str, Any]) -> bool:
    """Research composite gate only — not live capital allocation approval."""
    if board.get("membership") != "ACTIVE":
        return False
    return passes_composite_gate(summary)

RESEARCH_GROUPS = (
    {"id": "CURRENT_US_EQUITY_RESEARCH", "label": "Active US-Equity Research (Combined Portfolio eligible)"},
    {"id": "REFERENCE_US_EQUITY_RESEARCH", "label": "Reference Only (Excluded from Combined Portfolio)"},
    {"id": "ARCHIVED_US_EQUITY_RESEARCH", "label": "Archived / Rejected US-Equity Research"},
    {"id": "COMBINED_PORTFOLIO", "label": "Combined Portfolio"},
    {"id": "LEGACY_PROXY", "label": "Research Reference / Legacy Proxy"},
)

FACTOR_INTERPRETATIONS: dict[str, list[dict[str, str]]] = {
    "C2A2_002": [
        {"label": "Low-volatility / defensive exposure", "kind": "ECONOMIC INTERPRETATION", "detail": "Long low residual volatility and short high residual volatility after beta estimation."},
        {"label": "Market beta", "kind": "PROXY", "detail": "Beta-neutral construction is intended, but residual low-vol can still behave defensively in stress."},
    ],
    "C2A2_020": [
        {"label": "Liquidity-resilience / defensive exposure", "kind": "ECONOMIC INTERPRETATION", "detail": "Lower price impact during market and volume stress is treated as a resilience premium."},
        {"label": "Turnover sensitivity", "kind": "MEASURED", "detail": "Average daily turnover is exported in the baseline daily returns file."},
    ],
    "C2B2_004": [
        {"label": "Skewness / lottery-demand exposure", "kind": "ECONOMIC INTERPRETATION", "detail": "Long negative realized skew and short positive skew targets crash-risk compensation versus lottery demand."},
        {"label": "Downside-risk exposure", "kind": "ECONOMIC INTERPRETATION", "detail": "Negative-skew names can cluster in stress even in a dollar-neutral book."},
    ],
}

DECISION_REASONS: dict[str, str] = {
    "C2A2_002": "ACTIVE Combined Portfolio member with high overlap to C2A2_020; retained for research composite at equal-weight 1/N — not allocation approved.",
    "C2A2_020": "Retained research-composite member with positive cost-adjusted baseline; not allocation approved.",
    "C2B2_004": "Retained research-composite member with positive cost-adjusted baseline; not allocation approved.",
}


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    return pd.read_csv(path)


def _load_candidate_pool(root: Path) -> dict[str, dict[str, Any]]:
    pool_path = root / "data/config/strategy_candidate_pool_2026_06_10.json"
    if not pool_path.exists():
        return {}
    payload = json.loads(pool_path.read_text(encoding="utf-8"))
    return {row["candidate_id"]: row for row in payload.get("candidates", [])}


def _load_leaderboard(root: Path) -> dict[str, dict[str, Any]]:
    path = root / "artifacts/rapid_20plus1/strategy_leaderboard.csv"
    if not path.exists():
        return {}
    frame = pd.read_csv(path)
    return {str(row["strategy_id"]): row.to_dict() for _, row in frame.iterrows()}


def _load_holdings_index(root: Path) -> dict[str, dict[str, Any]]:
    path = root / "artifacts/rapid_20plus1/current_holdings.csv"
    frame = _read_csv(path)
    if frame is None or frame.empty:
        return {}
    holdings: dict[str, dict[str, Any]] = {}
    for strategy_id, group in frame.groupby("strategy_id"):
        last_date = group["last_rebalance_date"].iloc[-1] if "last_rebalance_date" in group.columns else None
        latest = group
        if last_date is not None and pd.notna(last_date):
            latest = group.loc[group["last_rebalance_date"] == last_date]
        long_rows = latest.loc[latest["side"] == "long"]
        short_rows = latest.loc[latest["side"] == "short"]
        holdings[str(strategy_id)] = {
            "last_rebalance_date": str(last_date) if last_date is not None else None,
            "current_long_holdings": [
                {"ticker": str(row["ticker"]), "weight": float(row["weight"]), "side": "long"}
                for _, row in long_rows.sort_values("weight", ascending=False).head(12).iterrows()
            ],
            "current_short_holdings": [
                {"ticker": str(row["ticker"]), "weight": float(row["weight"]), "side": "short"}
                for _, row in short_rows.sort_values("weight", ascending=True).head(12).iterrows()
            ],
        }
    return holdings


def _research_group(strategy_id: str, membership: str | None = None) -> str:
    if strategy_id == COMPOSITE_ID:
        return "COMBINED_PORTFOLIO"
    if membership == "ACTIVE":
        return "CURRENT_US_EQUITY_RESEARCH"
    if membership == "REFERENCE_ONLY":
        return "REFERENCE_US_EQUITY_RESEARCH"
    return "ARCHIVED_US_EQUITY_RESEARCH"


def _lifecycle_status(strategy_id: str, summary: dict[str, Any], leaderboard_row: dict[str, Any] | None = None) -> str:
    if strategy_id == COMPOSITE_ID:
        return "RESEARCH COMPOSITE"
    row = leaderboard_row or {}
    if row.get("membership") == "REFERENCE_ONLY":
        return "REFERENCE ONLY"
    status = row.get("status")
    if status == "PASS":
        return "ACTIVE RESEARCH"
    if status == "WATCH":
        return "WATCH RESEARCH"
    if status == "FAIL":
        return "FAIL"
    return "REFERENCE ONLY"


def _decision_reason(strategy_id: str, summary: dict[str, Any], gates: dict[str, bool]) -> str:
    if strategy_id in DECISION_REASONS:
        return DECISION_REASONS[strategy_id]
    if not gates.get("positive_gross_edge"):
        return "Gross edge is not positive after the baseline screening gates."
    if not gates.get("gross_edge_exceeds_cost"):
        return "Transaction costs exceed gross edge in the current baseline."
    if not gates.get("positive_mean_ic"):
        return "Mean IC is not positive; signal separation is weak."
    if not gates.get("positive_d10_minus_d1"):
        return "Decile spread (D10-D1) is not positive; IC does not translate cleanly into portfolio return."
    if float(summary.get("net_sharpe") or 0) < 0:
        return "Net Sharpe is negative after transaction costs."
    if summary.get("decision") == "ARCHIVE":
        return "Archived after Strategy Factory screening; retained only for research reference."
    return "Passed baseline screening gates; retained for further research review only."


def _action_from_summary(strategy_id: str, summary: dict[str, Any], leaderboard_row: dict[str, Any] | None = None) -> dict[str, str]:
    lifecycle = _lifecycle_status(strategy_id, summary, leaderboard_row)
    if lifecycle == "REFERENCE ONLY":
        return {
            "action": "Reference Only",
            "reason_code": "reference_only",
            "interpretation": "Backtest complete but excluded from Combined Portfolio because net Sharpe is not positive after costs.",
        }
    if lifecycle in {"ACTIVE RESEARCH", "WATCH RESEARCH", "RESEARCH COMPOSITE"}:
        return {"action": "Keep Researching", "reason_code": "active_research", "interpretation": _decision_reason(strategy_id, summary, summary.get("decision_gates") or {})}
    if lifecycle == "ECONOMIC DUPLICATE":
        return {"action": "Reject", "reason_code": "economic_duplicate", "interpretation": _decision_reason(strategy_id, summary, summary.get("decision_gates") or {})}
    if lifecycle == "REJECTED":
        return {"action": "Reject", "reason_code": "negative_net_sharpe", "interpretation": _decision_reason(strategy_id, summary, summary.get("decision_gates") or {})}
    return {"action": "Pause", "reason_code": "archived_baseline", "interpretation": _decision_reason(strategy_id, summary, summary.get("decision_gates") or {})}


def _logic_explanation(spec: StrategySpec, candidate: dict[str, Any] | None) -> dict[str, str]:
    candidate = candidate or {}
    return {
        "economic_hypothesis": spec.hypothesis,
        "expected_return_driver": candidate.get("expected_return_driver") or "See screening report for the baseline return driver.",
        "signal_inputs": ", ".join(candidate.get("required_data") or []) or "Daily adjusted OHLCV and cross-sectional eligibility screens.",
        "score_direction": "Higher score -> long; lower score -> short after cross-sectional ranking.",
        "long_leg": f"Top {int(spec.side_fraction * 100)}% ranked names by signal score.",
        "short_leg": f"Bottom {int(spec.side_fraction * 100)}% ranked names by signal score.",
        "rebalance_frequency": f"Every {spec.rebalance_every} trading days.",
        "execution_timing": spec.execution_mode.replace("_", " "),
        "transaction_cost_assumption": f"{spec.buy_bps:g} bps buy / {spec.sell_bps:g} bps sell applied to turnover.",
        "likely_failure_regime": candidate.get("major_implementation_risk") or "See screening report for implementation risks.",
    }


def _ic_decile_packet(path: Path) -> dict[str, Any]:
    frame = _read_csv(path)
    if frame is None or frame.empty:
        return {"available": False}
    values = {str(row["metric"]): float(row["value"]) for _, row in frame.iterrows()}
    deciles = {key: value for key, value in values.items() if key.startswith("decile_")}
    return {
        "available": True,
        "mean_ic": values.get("mean_ic"),
        "deciles": deciles,
        "d1": values.get("decile_1"),
        "d10": values.get("decile_10"),
        "decile_spread": float(values.get("decile_10", 0) - values.get("decile_1", 0)) if "decile_10" in values and "decile_1" in values else None,
        "ic_time_series_available": False,
    }


def _attribution_packet(daily: pd.DataFrame) -> dict[str, Any]:
    required = {"long_contribution", "short_contribution"}
    if not required.issubset(daily.columns):
        return {"available": False, "message": "NOT AVAILABLE IN CURRENT BASELINE"}
    long_total = float(daily["long_contribution"].sum())
    short_total = float(daily["short_contribution"].sum())
    gross_total = float(daily["gross_return"].sum()) if "gross_return" in daily.columns else long_total + short_total
    return {
        "available": True,
        "long_contribution_total": long_total,
        "short_contribution_total": short_total,
        "gross_return_total": gross_total,
        "long_share": float(long_total / gross_total) if gross_total else None,
        "short_share": float(short_total / gross_total) if gross_total else None,
    }


def _limitations(summary: dict[str, Any]) -> list[str]:
    return [
        "Pilot 500 / current-listed survivorship-biased universe.",
        "Incomplete point-in-time universe; no full historical membership reconstruction.",
        "No complete borrow-cost model or market-impact model in the baseline.",
        "No formal factor neutralization in the current factory baseline.",
        "No full walk-forward validation in the current baseline artifacts.",
        "yfinance OHLCV limitations and hypothetical backfill where noted in summary.json.",
        "Historical research evidence is not live performance or shadow PnL.",
        "Missing execution returns are tracked separately and can invalidate a run when exposure thresholds are breached.",
        f"Survivorship flag: {summary.get('survivorship_biased_current_listed_universe', 'unknown')}.",
    ]


def _build_factory_item(
    strategy_id: str,
    factory_root: Path,
    candidate_pool: dict[str, dict[str, Any]],
    leaderboard: dict[str, dict[str, Any]],
    holdings_index: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    spec = SPEC_BY_ID[strategy_id]
    strategy_dir = factory_root / strategy_id
    summary = _read_json(strategy_dir / "summary.json")
    daily = _read_csv(strategy_dir / "daily_returns.csv")
    if summary is None or daily is None or daily.empty:
        return None
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.sort_values("date")
    net = pd.Series(daily["net_return"].astype(float).values, index=daily["date"])
    gross = pd.Series(daily["gross_return"].astype(float).values, index=daily["date"])
    turnover = pd.Series(daily["turnover"].astype(float).values, index=daily["date"])
    benchmark = pd.Series(0.0, index=net.index)
    market_returns = pd.DataFrame(index=net.index)
    risk_packet = _risk_packet(net, benchmark, turnover, market_returns)
    candidate = candidate_pool.get(strategy_id, {})
    ic_packet = _ic_decile_packet(strategy_dir / "ic_decile_summary.csv")
    ann_return = _annual_return(net)
    board = leaderboard.get(strategy_id) or {}
    group = _research_group(strategy_id, board.get("membership"))
    lifecycle = _lifecycle_status(strategy_id, summary, board)
    return {
        "research_group": group,
        "strategy_id": strategy_id,
        "backtest": {
            "strategy_id": strategy_id,
            "name": spec.name,
            "literature_source": "US equity Strategy Factory baseline",
            "research_source": "strategy_factory_v1",
            "hypothesis": spec.hypothesis,
            "universe": candidate.get("initial_us_equity_universe") or "Pilot 500 US common stocks",
            "rebalance": f"Every {spec.rebalance_every} trading days",
            "signal_summary": candidate.get("security_selection_concept") or spec.hypothesis,
            "failure_modes": candidate.get("major_implementation_risk") or "See screening report.",
            "observations": int(summary.get("observations") or len(daily)),
            "asset_class": "US individual equities",
            "strategy_family": candidate.get("strategy_family") or spec.version,
            "lifecycle_status": lifecycle,
            "allocation_eligible": False,
            "live_allocation_approved": False,
            "research_composite_eligible": _research_composite_eligible(summary, board),
            "test_period_start": daily["date"].iloc[0].date().isoformat(),
            "test_period_end": daily["date"].iloc[-1].date().isoformat(),
            "latest_data_date": daily["date"].iloc[-1].date().isoformat(),
            "gross_metrics": {
                "cumulative_return": float(summary.get("cumulative_gross_return") or daily["cumulative_gross"].iloc[-1]),
                "annual_return": _annual_return(gross),
            },
            "net_metrics": {
                "cumulative_return": float(summary.get("cumulative_net_return") or daily["cumulative_net"].iloc[-1]),
                "annual_return": ann_return,
                "annual_volatility": float(summary.get("annualized_net_volatility") or risk_packet["summary_statistics"]["annual_volatility"]),
                "sharpe": float(summary.get("net_sharpe") or risk_packet["summary_statistics"]["sharpe"]),
                "max_drawdown": float(summary.get("max_drawdown") or risk_packet["drawdown_behavior"]["max_drawdown"]),
            },
            "turnover": {
                "average_daily_turnover": float(summary.get("average_daily_turnover") or turnover.mean()),
                "annualized_turnover": float((summary.get("average_daily_turnover") or turnover.mean()) * TRADING_DAYS),
                "total_cost_drag": float(summary.get("transaction_cost_sum") or daily["transaction_cost"].sum()),
                "annualized_cost_drag": float(daily["transaction_cost"].mean() * TRADING_DAYS),
            },
            "return_series": {
                "dates": [idx.date().isoformat() for idx in net.index],
                "gross_returns": [float(value) for value in gross.values],
                "net_returns": [float(value) for value in net.values],
            },
            "risk_packet": risk_packet,
            "action": _action_from_summary(strategy_id, summary, board),
            "holdings": (holdings_index or {}).get(strategy_id),
            "factory_research": {
                "mean_ic": summary.get("mean_ic"),
                "decile_spread": summary.get("d10_minus_d1"),
                "ic_packet": ic_packet,
                "attribution": _attribution_packet(daily),
                "logic": _logic_explanation(spec, candidate),
                "limitations": _limitations(summary),
                "decision_reason": (
                    "Reference only — excluded from Combined Portfolio composite."
                    if board.get("membership") == "REFERENCE_ONLY"
                    else board.get("status") or _decision_reason(strategy_id, summary, summary.get("decision_gates") or {})
                ),
                "research_status": board.get("status"),
                "membership": board.get("membership"),
                "research_composite_eligible": _research_composite_eligible(summary, board),
                "live_allocation_approved": False,
                "composite_eligible": _research_composite_eligible(summary, board),
                "average_abs_correlation": board.get("average_abs_correlation"),
                "max_abs_correlation": board.get("max_abs_correlation"),
                "highest_corr_partner": board.get("highest_corr_partner"),
                "factor_interpretation": FACTOR_INTERPRETATIONS.get(strategy_id, []),
                "screening_report_path": str(strategy_dir / "screening_report.md"),
                "artifacts_present": {
                    name: (strategy_dir / name).exists()
                    for name in (
                        "summary.json",
                        "daily_returns.csv",
                        "positions_summary.csv",
                        "ic_decile_summary.csv",
                        "equity_curve.png",
                        "drawdown.png",
                        "decile_chart.png",
                        "screening_report.md",
                        "missing_execution_returns.csv",
                        "rebalance_audit.csv",
                    )
                },
            },
        },
        "walk_forward": {
            "windows": [],
            "status": "NOT AVAILABLE IN CURRENT BASELINE",
            "number_of_windows": 0,
            "positive_window_rate": 0.0,
            "average_test_sharpe": None,
        },
    }


def _build_combined_portfolio_item(composite_root: Path, factory_root: Path, leaderboard: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    summary_path = composite_root / "combined_portfolio_summary.json"
    if not summary_path.exists():
        summary_path = composite_root / "strategy_21_summary.json"
    daily_path = composite_root / "combined_portfolio_daily_returns.csv"
    if not daily_path.exists():
        daily_path = composite_root / "strategy_21_daily_returns.csv"
    summary = _read_json(summary_path)
    daily = _read_csv(daily_path)
    pairwise = _read_csv(composite_root / "candidate_pairwise_analysis.csv")
    corr_path = factory_root.parents[2] / "artifacts/rapid_20plus1/correlation_matrix.csv"
    corr = _read_csv(corr_path) if corr_path.exists() else None
    if summary is None or daily is None or daily.empty:
        return None
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.sort_values("date")
    net = pd.Series(daily["net_return"].astype(float).values, index=daily["date"])
    gross = pd.Series(daily["gross_return"].astype(float).values, index=daily["date"]) if "gross_return" in daily.columns else net.copy()
    turnover = pd.Series(daily["turnover"].astype(float).values, index=daily["date"]) if "turnover" in daily.columns else pd.Series(0.0, index=net.index)
    benchmark = pd.Series(0.0, index=net.index)
    risk_packet = _risk_packet(net, benchmark, turnover, pd.DataFrame(index=net.index))
    n = int(summary.get("N") or 0)
    weight = float(summary.get("equal_weight") or (1.0 / n if n else 0.0))
    active_ids = summary.get("active_member_ids") or summary.get("constituent_ids") or []
    reference_ids = summary.get("reference_only_ids") or []
    members = [
        {
            "strategy_id": strategy_id,
            "name": SPEC_BY_ID[strategy_id].name,
            "weight": weight,
            "sharpe": (summary.get("constituent_sharpes") or {}).get(strategy_id),
            "research_status": (leaderboard.get(strategy_id) or {}).get("status"),
            "membership": "ACTIVE",
        }
        for strategy_id in active_ids
    ]
    pairwise_rows = pairwise.to_dict(orient="records") if pairwise is not None else []
    corr_matrix = corr.set_index(corr.columns[0]).to_dict() if corr is not None else {}
    composite_payload = {
        "N": n,
        "equal_weight": weight,
        "weight_formula": summary.get("weight_formula") or "weight_i = 1 / N",
        "dynamic_membership": summary.get("dynamic_membership", True),
        "membership_rule": "Includes all currently eligible ACTIVE underlying strategies; equal-weight 1/N.",
        "members": members,
        "constituent_ids": active_ids,
        "eligible_member_ids": summary.get("eligible_member_ids") or active_ids,
        "reference_only_ids": reference_ids,
        "current_constituents": [
            {"strategy_id": strategy_id, "weight": weight, "side": "constituent"}
            for strategy_id in active_ids
        ],
        "weights": summary.get("constituent_weights") or {},
        "constituent_sharpes": summary.get("constituent_sharpes") or {},
        "pairwise_analysis": pairwise_rows,
        "correlation_matrix": corr_matrix,
        "common_start_date": summary.get("common_start_date"),
        "common_end_date": summary.get("common_end_date"),
    }
    return {
        "research_group": "COMBINED_PORTFOLIO",
        "strategy_id": COMPOSITE_ID,
        "backtest": {
            "strategy_id": COMPOSITE_ID,
            "name": summary.get("name") or "Combined Portfolio",
            "literature_source": "Combined Portfolio equal-weight research composite",
            "research_source": "rapid_20plus1",
            "hypothesis": summary.get("label") or "Equal-weight composite of effective platform strategies — research only.",
            "universe": f"Composite of {n} active US-equity research strategies (net Sharpe > 0)",
            "rebalance": f"Static equal weight 1/N where N={n}",
            "signal_summary": "Dynamic equal weight: weight_i = 1/N on shared valid dates; reference-only strategies excluded.",
            "failure_modes": "Member overlap and composite concentration require monitoring; not allocation approved.",
            "observations": len(daily),
            "asset_class": "US individual equities (research composite)",
            "strategy_family": "research_composite",
            "lifecycle_status": "RESEARCH COMPOSITE",
            "allocation_eligible": False,
            "live_allocation_approved": False,
            "research_composite_eligible": False,
            "test_period_start": daily["date"].iloc[0].date().isoformat(),
            "test_period_end": daily["date"].iloc[-1].date().isoformat(),
            "latest_data_date": daily["date"].iloc[-1].date().isoformat(),
            "gross_metrics": {"cumulative_return": float(summary.get("cumulative_gross_return") or gross.add(1).prod() - 1), "annual_return": _annual_return(gross)},
            "net_metrics": {
                "cumulative_return": float(summary.get("cumulative_net_return") or net.add(1).prod() - 1),
                "annual_return": float(summary.get("annualized_return") or _annual_return(net)),
                "annual_volatility": float(summary.get("annualized_volatility") or risk_packet["summary_statistics"]["annual_volatility"]),
                "sharpe": float(summary.get("sharpe") or risk_packet["summary_statistics"]["sharpe"]),
                "max_drawdown": float(summary.get("max_drawdown") or risk_packet["drawdown_behavior"]["max_drawdown"]),
            },
            "turnover": {"average_daily_turnover": None, "annualized_turnover": None, "total_cost_drag": float(summary.get("cost_drag") or 0), "annualized_cost_drag": None},
            "return_series": {
                "dates": [idx.date().isoformat() for idx in net.index],
                "gross_returns": [float(value) for value in gross.values],
                "net_returns": [float(value) for value in net.values],
            },
            "risk_packet": risk_packet,
            "action": {"action": "Keep Researching", "reason_code": "research_composite", "interpretation": "Research-only equal-weight Combined Portfolio; not live or allocation approved."},
            "factory_research": {
                "combined_portfolio": composite_payload,
                "strategy_21": composite_payload,
                "research_composite_eligible": False,
                "live_allocation_approved": False,
                "limitations": _limitations({"survivorship_biased_current_listed_universe": True}),
                "decision_reason": f"Equal-weight Combined Portfolio of {n} research-composite-eligible strategies; research only — not live allocation approved.",
                "artifacts_present": {
                    name: (composite_root / name).exists() or (factory_root.parents[2] / "artifacts/rapid_20plus1" / name).exists()
                    for name in (
                        "combined_portfolio_summary.json",
                        "combined_portfolio_daily_returns.csv",
                        "combined_portfolio_equity_drawdown.png",
                        "combined_portfolio_correlation_heatmap.png",
                        "combined_portfolio_evidence_manifest.json",
                        "combined_portfolio_report.md",
                    )
                },
            },
        },
        "walk_forward": {"windows": [], "status": "NOT AVAILABLE IN CURRENT BASELINE", "number_of_windows": 0, "positive_window_rate": 0.0, "average_test_sharpe": None},
    }


def build_factory_research_catalog(project_root: str | Path) -> dict[str, Any]:
    root = Path(project_root)
    factory_root = root / "output/research/strategy_factory_v1"
    composite_root = root / "output/research/strategy_21_research_composite_v1"
    candidate_pool = _load_candidate_pool(root)
    leaderboard = _load_leaderboard(root)
    holdings_index = _load_holdings_index(root)
    results: list[dict[str, Any]] = []
    for strategy_id in FACTORY_STRATEGY_IDS:
        item = _build_factory_item(strategy_id, factory_root, candidate_pool, leaderboard, holdings_index)
        if item:
            results.append(item)
    composite_item = _build_combined_portfolio_item(composite_root, factory_root, leaderboard)
    if composite_item:
        results.append(composite_item)
    active_count = sum(1 for row in leaderboard.values() if row.get("membership") == "ACTIVE")
    reference_count = sum(1 for row in leaderboard.values() if row.get("membership") == "REFERENCE_ONLY")
    composite_weight = (1.0 / active_count) if active_count else 0.0
    return {
        "source": "rapid_20plus1",
        "default_strategy_id": DEFAULT_STRATEGY_ID,
        "groups": list(RESEARCH_GROUPS),
        "architecture": {
            "dynamic_membership": True,
            "equal_weight_formula": "1/N",
            "research_composite_eligible_count": active_count,
            "eligible_active_count": active_count,
            "composite_constituent_count": active_count,
            "composite_equal_weight": composite_weight,
            "live_allocation_approved": False,
            "tested_candidate_count": len(RAPID_BACKTEST_IDS),
            "active_retained_count": active_count,
            "reference_only_count": reference_count,
        },
        "results": results,
        "results_count": len(results),
    }
