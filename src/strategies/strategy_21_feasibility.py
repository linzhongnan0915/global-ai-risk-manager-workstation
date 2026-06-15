"""Minimal de-duplication and Strategy 21 research-composite analysis."""

from __future__ import annotations

from itertools import combinations
from pathlib import Path
import json

import numpy as np
import pandas as pd

from src.risk.performance import cumulative_returns, drawdown_series, max_drawdown, sharpe_ratio, volatility


RETAINED_IDS = ("C2A2_002", "C2A2_020", "C2B2_004")


def load_candidate_artifacts(factory_root: Path) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], dict[str, dict]]:
    returns = []
    audits = {}
    summaries = {}
    for strategy_id in RETAINED_IDS:
        daily = pd.read_csv(factory_root / strategy_id / "daily_returns.csv", parse_dates=["date"])
        returns.append(daily.set_index("date")["net_return"].rename(strategy_id))
        audits[strategy_id] = pd.read_csv(factory_root / strategy_id / "rebalance_audit.csv", parse_dates=["date"])
        summaries[strategy_id] = json.loads((factory_root / strategy_id / "summary.json").read_text())
    return pd.concat(returns, axis=1, join="inner").dropna(), audits, summaries


def exposure_summary(audit: pd.DataFrame, strategy_id: str) -> dict[str, object]:
    selected = audit.loc[audit["target_weight"] != 0].copy()
    selected["abs_weight"] = selected["target_weight"].abs()
    valid_beta = selected["lagged_beta"].notna()
    weight_sum = selected["abs_weight"].sum()
    weighted_beta = float(
        (selected.loc[valid_beta, "lagged_beta"] * selected.loc[valid_beta, "abs_weight"]).sum()
        / selected.loc[valid_beta, "abs_weight"].sum()
    )
    weighted_adv = float((selected["lagged_adv"] * selected["abs_weight"]).sum() / weight_sum)
    by_date = selected.groupby("date")
    concentration = by_date["target_weight"].apply(lambda x: float(x.abs().max()))
    return {
        "average_beta": weighted_beta,
        "average_lagged_adv": weighted_adv,
        "average_long_concentration": float(
            by_date.apply(lambda x: x.loc[x["target_weight"] > 0, "target_weight"].max()).mean()
        ),
        "average_short_concentration": float(
            by_date.apply(lambda x: x.loc[x["target_weight"] < 0, "target_weight"].abs().max()).mean()
        ),
        "average_max_position_concentration": float(concentration.mean()),
        "residual_volatility": (
            float((-selected["score"] * selected["abs_weight"]).sum() / weight_sum)
            if strategy_id == "C2A2_002"
            else "NOT_AVAILABLE_FROM_EXISTING_ARTIFACTS"
        ),
    }


def holdings_overlap(left: pd.DataFrame, right: pd.DataFrame) -> float:
    dates = sorted(set(left["date"]) | set(right["date"]))
    left_by_date = {date: set(group.loc[group["target_weight"] != 0, "ticker"]) for date, group in left.groupby("date")}
    right_by_date = {date: set(group.loc[group["target_weight"] != 0, "ticker"]) for date, group in right.groupby("date")}
    left_current: set[str] = set()
    right_current: set[str] = set()
    overlaps = []
    for date in dates:
        left_current = left_by_date.get(date, left_current)
        right_current = right_by_date.get(date, right_current)
        union = left_current | right_current
        if union:
            overlaps.append(len(left_current & right_current) / len(union))
    return float(np.mean(overlaps)) if overlaps else 0.0


def pairwise_analysis(returns: pd.DataFrame, audits: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    drawdowns = returns.apply(lambda x: pd.Series(drawdown_series(x), index=returns.index))
    for left, right in combinations(returns.columns, 2):
        rolling = returns[left].rolling(60, min_periods=60).corr(returns[right]).dropna()
        left_dd = drawdowns[left] < 0
        right_dd = drawdowns[right] < 0
        drawdown_union = int((left_dd | right_dd).sum())
        overlap = float((left_dd & right_dd).sum() / drawdown_union) if drawdown_union else 0.0
        correlation = float(returns[left].corr(returns[right]))
        holding_overlap = holdings_overlap(audits[left], audits[right])
        if correlation >= 0.70 or holding_overlap >= 0.70:
            decision = "ECONOMICALLY_DUPLICATE"
        elif correlation >= 0.40 or holding_overlap >= 0.35 or overlap >= 0.75:
            decision = "PARTIALLY_OVERLAPPING"
        else:
            decision = "DISTINCT_ENOUGH"
        shared_driver = {
            frozenset(("C2A2_002", "C2A2_020")): "defensive low-risk and liquidity-resilience exposure",
            frozenset(("C2A2_002", "C2B2_004")): "defensive/crash-risk exposure",
            frozenset(("C2A2_020", "C2B2_004")): "resilience and crash-risk exposure",
        }.get(frozenset((left, right)), "shared return behavior requires economic interpretation")
        rows.append(
            {
                "strategy_left": left, "strategy_right": right, "daily_net_return_correlation": correlation,
                "rolling_60d_correlation_mean": float(rolling.mean()), "rolling_60d_correlation_min": float(rolling.min()),
                "rolling_60d_correlation_max": float(rolling.max()), "rolling_60d_correlation_latest": float(rolling.iloc[-1]),
                "drawdown_overlap": overlap, "rebalance_holdings_overlap": holding_overlap,
                "distinctness_decision": decision, "likely_shared_return_driver": shared_driver,
            }
        )
    return pd.DataFrame(rows)


def candidate_decisions(pairwise: pd.DataFrame, summaries: dict[str, dict]) -> dict[str, str]:
    removed: set[str] = set()
    for row in pairwise.loc[pairwise["distinctness_decision"] == "ECONOMICALLY_DUPLICATE"].itertuples():
        pair = [row.strategy_left, row.strategy_right]
        removed.add(min(pair, key=lambda key: summaries[key]["net_sharpe"]))
    decisions = {}
    for strategy_id in RETAINED_IDS:
        related = pairwise.loc[
            (pairwise["strategy_left"] == strategy_id) | (pairwise["strategy_right"] == strategy_id),
            "distinctness_decision",
        ]
        decisions[strategy_id] = (
            "REMOVE_FROM_COMPOSITE" if strategy_id in removed
            else "RETAIN_BUT_OVERLAPPING" if (related != "DISTINCT_ENOUGH").any()
            else "RETAIN_FOR_COMPOSITE"
        )
    return decisions


def build_composite(returns: pd.DataFrame, retained: list[str]) -> tuple[pd.DataFrame, dict[str, object]]:
    weights = {strategy_id: (1.0 / len(retained) if strategy_id in retained else 0.0) for strategy_id in returns.columns}
    weighted = returns.mul(pd.Series(weights))
    composite = weighted.sum(axis=1)
    daily = pd.DataFrame({"date": returns.index, "net_return": composite})
    daily["cumulative_return"] = cumulative_returns(composite)
    daily["drawdown"] = drawdown_series(composite)
    contributions = weighted.sum().to_dict()
    total = float(composite.sum())
    shares = {key: (float(value) / total if total != 0 else None) for key, value in contributions.items()}
    alerts = {
        "correlation_above_0_70": [],
        "composite_drawdown_above_10pct": bool(max_drawdown(composite) < -0.10),
        "component_over_50pct_total_pnl": [key for key, value in shares.items() if value is not None and value > 0.50],
    }
    summary = {
        "strategy_id": "STRATEGY_21_RESEARCH_COMPOSITE_V1", "research_only": True, "weights": weights,
        "cumulative_return": float(daily["cumulative_return"].iloc[-1]), "sharpe": float(sharpe_ratio(composite)),
        "annualized_volatility": float(volatility(composite)), "max_drawdown": float(max_drawdown(composite)),
        "component_contribution": contributions, "component_contribution_share": shares, "alerts": alerts,
        "contribution_reconciliation_error": float(abs(sum(contributions.values()) - total)),
    }
    return daily, summary


def run_analysis(factory_root: Path, output_dir: Path) -> dict[str, object]:
    import matplotlib.pyplot as plt

    output_dir.mkdir(parents=True, exist_ok=True)
    returns, audits, summaries = load_candidate_artifacts(factory_root)
    pairwise = pairwise_analysis(returns, audits)
    decisions = candidate_decisions(pairwise, summaries)
    exposures = {strategy_id: exposure_summary(audits[strategy_id], strategy_id) for strategy_id in RETAINED_IDS}
    retained = [key for key, value in decisions.items() if value != "REMOVE_FROM_COMPOSITE"]
    summary = {"candidate_decisions": decisions, "exposure_diagnostics": exposures, "retained_strategies": retained}
    pairwise.to_csv(output_dir / "candidate_pairwise_analysis.csv", index=False)
    (output_dir / "candidate_overlap_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    returns.corr().plot(kind="bar", title="Retained Candidate Net-Return Correlation")
    plt.tight_layout(); plt.savefig(output_dir / "candidate_correlation.png", dpi=140); plt.close()
    if len(retained) >= 2:
        daily, composite = build_composite(returns, retained)
        high_corr = pairwise.loc[
            pairwise["strategy_left"].isin(retained)
            & pairwise["strategy_right"].isin(retained)
            & pairwise["daily_net_return_correlation"].gt(0.70),
            ["strategy_left", "strategy_right"],
        ]
        composite["alerts"]["correlation_above_0_70"] = high_corr.to_dict("records")
        daily.to_csv(output_dir / "strategy_21_daily_returns.csv", index=False)
        (output_dir / "strategy_21_summary.json").write_text(json.dumps(composite, indent=2), encoding="utf-8")
        daily.plot(x="date", y=["cumulative_return", "drawdown"], title="Strategy 21 Research Composite")
        plt.tight_layout(); plt.savefig(output_dir / "strategy_21_equity_drawdown.png", dpi=140); plt.close()
    report = (
        "# Minimal Candidate De-duplication and Strategy 21 Feasibility\n\n"
        f"Retained strategies: {', '.join(retained)}.\n\n"
        "This is a research-only comparison using existing Strategy Factory artifacts. "
        "Residual volatility is unavailable for non-C2A2_002 candidates in the existing audit fields.\n"
    )
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    return summary
