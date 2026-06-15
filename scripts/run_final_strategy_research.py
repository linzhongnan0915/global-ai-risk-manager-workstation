"""Final strategy research with MARKET_PROXY_REGIME_V0 diagnostics."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.risk.performance import max_drawdown, sharpe_ratio
from src.strategies.platform_registry import STRATEGY_SELECTION_STATUS
from src.strategies.worldquant.market_data import download_ohlcv

BUNDLE_PATH = ROOT / "dashboard/data/us_equity_research_bundle.json"
FUNDAMENTAL_ROOT = ROOT / "output/research/final_fundamental_research_v1"
OUTPUT_ROOT = ROOT / "output/research/final_strategy_research_v1"
REGIME_CACHE = ROOT / "data/raw/fundamental_research/growth_inflation_proxy_ohlcv.csv"
LEGACY_ACTIVE_BASE = (
    "C3A1_001", "C3A1_002", "C3A1_003", "C3A1_013", "C3A1_015", "C3A2_008",
)
ECONOMIC_FAMILIES = {
    "C2A2_004": "overnight reversal",
    "C2A2_020": "liquidity resilience",
    "C3A1_001": "residual momentum",
    "C3A1_002": "momentum",
    "C3A1_003": "momentum",
    "C3A1_004": "volatility-adjusted momentum",
    "C3A1_005": "trend quality",
    "C3A1_006": "breakout persistence",
    "C3A1_012": "liquidity stability",
    "C3A1_013": "liquidity premium",
    "C3A1_015": "price efficiency",
    "C3A2_008": "slow momentum",
    "C3A2_009": "liquidity / size diversification",
    "FUNDAMENTAL_MOMENTUM": "fundamental momentum",
    "CAPEX_EFFICIENCY": "investment efficiency",
    "EARNINGS_QUALITY": "earnings quality",
    "PROFITABLE_SMALL_CAP": "profitability / size",
    "CONSERVATIVE_ASSET_GROWTH": "conservative investment",
    "CASH_FLOW_YIELD": "cash-flow value",
    "MARGIN_IMPROVEMENT": "fundamental momentum",
    "REVENUE_ACCELERATION": "fundamental momentum",
    "CASH_FLOW_MOMENTUM": "fundamental momentum",
    "LOW_LEVERAGE_QUALITY": "quality / leverage",
    "QUALITY_AT_REASONABLE_PRICE": "quality / value",
    "SHAREHOLDER_YIELD": "shareholder distributions",
}
FUNDAMENTAL_REASONS = {
    "FUNDAMENTAL_MOMENTUM": "ACTIVE: strong net Sharpe, positive preliminary OOS, and low legacy correlation.",
    "CAPEX_EFFICIENCY": "REPAIR: preliminary OOS is positive, but costs consume the full-period edge.",
    "EARNINGS_QUALITY": "ACTIVE: strong net Sharpe, positive preliminary OOS, and low legacy correlation.",
    "PROFITABLE_SMALL_CAP": "REPAIR: credible full-period result, but preliminary OOS is negative.",
    "CONSERVATIVE_ASSET_GROWTH": "ARCHIVED: negative full-period and preliminary OOS evidence.",
    "CASH_FLOW_YIELD": "ARCHIVED: near-zero net return, negative preliminary OOS return, and cost drag exceeds edge.",
    "MARGIN_IMPROVEMENT": "ACTIVE: strongest net Sharpe, positive preliminary OOS, and low legacy correlation.",
    "REVENUE_ACCELERATION": "REPAIR: positive preliminary OOS, but weak full-period Sharpe and deep drawdown.",
    "CASH_FLOW_MOMENTUM": "REPAIR: positive preliminary OOS and low correlation, but sub-threshold full-period Sharpe.",
    "LOW_LEVERAGE_QUALITY": "REPAIR: positive return and OOS, but weak Sharpe and drawdown exceeds 30%.",
    "QUALITY_AT_REASONABLE_PRICE": "REPAIR: weak full-period evidence and negative OOS, retained only for low correlation.",
    "SHAREHOLDER_YIELD": "ARCHIVED: negative full-period and preliminary OOS evidence.",
}


def _bundle_rows() -> tuple[dict[str, dict], pd.DataFrame]:
    payload = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))
    rows = {row["strategy_id"]: row for row in payload["factory_strategy_research"]["results"]}
    dates = pd.to_datetime(payload["shared_dates"])
    returns = pd.DataFrame(
        {
            strategy_id: rows[strategy_id]["backtest"]["return_series"]["net_returns"]
            for strategy_id in STRATEGY_SELECTION_STATUS
        },
        index=dates,
    )
    return rows, returns


def _portfolio_stats(panel: pd.DataFrame) -> dict[str, float]:
    returns = panel.mean(axis=1)
    return {
        "net_cumulative_return": float(returns.add(1).prod() - 1),
        "net_sharpe": float(sharpe_ratio(returns)),
        "max_drawdown": float(max_drawdown(returns)),
    }


def legacy_diagnostics(rows: dict[str, dict], returns: pd.DataFrame) -> pd.DataFrame:
    base = _portfolio_stats(returns[list(LEGACY_ACTIVE_BASE)])
    records = []
    for strategy_id, decision in STRATEGY_SELECTION_STATUS.items():
        backtest = rows[strategy_id]["backtest"]
        series = returns[strategy_id]
        peers = returns[[value for value in LEGACY_ACTIVE_BASE if value != strategy_id]]
        retained_correlations = peers.corrwith(series).abs()
        all_correlations = returns.drop(columns=[strategy_id]).corrwith(series).abs()
        max_corr = float(all_correlations.max())
        avg_corr = float(retained_correlations.mean())
        record = {
            "strategy_id": strategy_id,
            "prior_status": decision["status"],
            "net_cumulative_return": backtest["net_metrics"]["cumulative_return"],
            "net_sharpe": backtest["net_metrics"]["sharpe"],
            "max_drawdown": backtest["net_metrics"]["max_drawdown"],
            "annualized_turnover": backtest["turnover"]["annualized_turnover"],
            "cost_drag": backtest["turnover"]["total_cost_drag"],
            "maximum_correlation": max_corr,
            "average_abs_correlation_with_retained": avg_corr,
            "marginal_sharpe_vs_current_active": np.nan,
            "marginal_return_vs_current_active": np.nan,
        }
        if strategy_id in LEGACY_ACTIVE_BASE:
            without = _portfolio_stats(peers)
            record["marginal_sharpe_vs_current_active"] = base["net_sharpe"] - without["net_sharpe"]
            record["marginal_return_vs_current_active"] = (
                base["net_cumulative_return"] - without["net_cumulative_return"]
            )
        records.append(record)
    frame = pd.DataFrame(records).set_index("strategy_id")
    frame["recommendation"] = frame["prior_status"]
    frame.loc["C3A2_009", "recommendation"] = "REPAIR"
    frame.loc["C3A1_005", "recommendation"] = "REPAIR"
    frame.loc["C3A1_015", "recommendation"] = "ACTIVE"
    return frame.reset_index()


def fundamental_recommendations() -> pd.DataFrame:
    summary = pd.read_csv(FUNDAMENTAL_ROOT / "candidate_summary.csv")
    _, legacy_returns = _bundle_rows()
    fundamental_daily = pd.read_csv(FUNDAMENTAL_ROOT / "daily_net_returns.csv", parse_dates=["date"])
    fundamental_returns = fundamental_daily.pivot(index="date", columns="strategy_id", values="net_return")
    corr = pd.concat([fundamental_returns, legacy_returns], axis=1, join="inner").corr()
    retained = list(LEGACY_ACTIVE_BASE)
    summary["maximum_correlation"] = [
        float(corr.loc[strategy_id, retained].abs().max()) for strategy_id in summary["strategy_id"]
    ]
    summary["recommendation"] = "REPAIR"
    active = (
        summary["net_sharpe"].ge(0.40)
        & summary["preliminary_oos_sharpe"].gt(0)
        & summary["net_cumulative_return"].gt(0)
        & summary["max_drawdown"].gt(-0.25)
        & summary["maximum_correlation"].lt(0.90)
    )
    archived = (
        summary["net_cumulative_return"].le(0)
        & summary["preliminary_oos_net_return"].le(0)
    ) | (
        summary["net_sharpe"].lt(0.10)
        & summary["preliminary_oos_net_return"].le(0)
        & summary["total_cost_drag"].gt(summary["net_cumulative_return"].clip(lower=0))
    )
    summary.loc[active, "recommendation"] = "ACTIVE"
    summary.loc[archived, "recommendation"] = "ARCHIVED"
    return summary


def _regime_labels(index: pd.DatetimeIndex) -> pd.Series:
    if REGIME_CACHE.exists():
        raw = pd.read_csv(REGIME_CACHE, parse_dates=["date"])
    else:
        raw, _, _ = download_ohlcv(
            ["SPY", "TIP", "IEF"], start_date="2017-09-01", end_date="2026-06-10",
            batch_size=3, include_rejected_history=True,
        )
        REGIME_CACHE.parent.mkdir(parents=True, exist_ok=True)
        raw.to_csv(REGIME_CACHE, index=False)
    raw["date"] = pd.to_datetime(raw["date"])
    close = raw.pivot(index="date", columns="ticker", values="adj_close").sort_index()
    growth = close["SPY"].pct_change(63).shift(1)
    inflation = (close["TIP"].pct_change(63) - close["IEF"].pct_change(63)).shift(1)
    labels = pd.Series(index=close.index, dtype=object)
    labels.loc[growth.ge(0) & inflation.ge(0)] = "MARKET_PROXY_GROWTH_UP_INFLATION_UP"
    labels.loc[growth.ge(0) & inflation.lt(0)] = "MARKET_PROXY_GROWTH_UP_INFLATION_DOWN"
    labels.loc[growth.lt(0) & inflation.ge(0)] = "MARKET_PROXY_GROWTH_DOWN_INFLATION_UP"
    labels.loc[growth.lt(0) & inflation.lt(0)] = "MARKET_PROXY_GROWTH_DOWN_INFLATION_DOWN"
    return labels.reindex(index).ffill()


def regime_analysis(returns: pd.DataFrame) -> pd.DataFrame:
    labels = _regime_labels(returns.index)
    rows = []
    for strategy_id in returns:
        for regime in sorted(labels.dropna().unique()):
            selected = returns.loc[labels.eq(regime), strategy_id].dropna()
            rows.append(
                {
                    "strategy_id": strategy_id,
                    "regime": regime,
                    "observations": len(selected),
                    "net_cumulative_return": float(selected.add(1).prod() - 1),
                    "net_sharpe": float(sharpe_ratio(selected)) if len(selected) > 1 else np.nan,
                }
            )
    return pd.DataFrame(rows)


def final_recommendations(
    rows: dict[str, dict], legacy: pd.DataFrame, fundamentals: pd.DataFrame, regimes: pd.DataFrame
) -> pd.DataFrame:
    output = []
    combined = pd.concat(
        [
            legacy[["strategy_id", "recommendation", "maximum_correlation"]].assign(
                economic_family=lambda frame: frame["strategy_id"].map(ECONOMIC_FAMILIES)
            ),
            fundamentals[["strategy_id", "recommendation", "maximum_correlation"]].assign(
                economic_family=lambda frame: frame["strategy_id"].map(ECONOMIC_FAMILIES)
            ),
        ],
        ignore_index=True,
    )
    for _, row in combined.iterrows():
        strategy_regimes = regimes.loc[regimes["strategy_id"].eq(row["strategy_id"])].dropna(subset=["net_sharpe"])
        best = (
            strategy_regimes.loc[strategy_regimes["net_sharpe"].idxmax(), "regime"]
            if not strategy_regimes.empty else "NOT_ANALYZED_ARCHIVED"
        )
        worst = (
            strategy_regimes.loc[strategy_regimes["net_sharpe"].idxmin(), "regime"]
            if not strategy_regimes.empty else "NOT_ANALYZED_ARCHIVED"
        )
        reason = STRATEGY_SELECTION_STATUS.get(row["strategy_id"], {}).get(
            "reason", FUNDAMENTAL_REASONS.get(row["strategy_id"], "Retain credible standalone or diversification value.")
        )
        if row["strategy_id"] == "C3A2_009":
            reason = "REPAIR: diversification is measurable, but accepted decision reflects negative marginal portfolio contribution."
        elif row["strategy_id"] == "C3A1_005":
            reason = "REPAIR: correlation 0.961 with C3A1_015, which has lower drawdown and slightly lower cost."
        elif row["strategy_id"] == "C3A1_015":
            reason = "ACTIVE: retained over 0.961-correlated C3A1_005 due to lower drawdown and slightly lower cost."
        elif row["strategy_id"] == "C3A1_004":
            reason = "ARCHIVED: correlation 0.905 with clearly superior C3A1_002; dominated duplicate."
        elif row["strategy_id"] in FUNDAMENTAL_REASONS:
            reason = FUNDAMENTAL_REASONS[row["strategy_id"]]
        elif row["recommendation"] == "ARCHIVED":
            reason = "No credible net and preliminary OOS edge after costs."
        elif row["recommendation"] == "REPAIR":
            reason = "Potential value remains, but evidence is insufficient for ACTIVE."
        output.append(
            {
                **row.to_dict(),
                "reason": reason,
                "regime_strength": best,
                "regime_weakness": worst,
            }
        )
    return pd.DataFrame(output)


def main() -> int:
    rows, legacy_returns = _bundle_rows()
    legacy = legacy_diagnostics(rows, legacy_returns)
    fundamentals = fundamental_recommendations()
    fundamental_daily = pd.read_csv(FUNDAMENTAL_ROOT / "daily_net_returns.csv", parse_dates=["date"])
    fundamental_returns = fundamental_daily.pivot(index="date", columns="strategy_id", values="net_return")
    viable = fundamentals.loc[fundamentals["recommendation"].ne("ARCHIVED"), "strategy_id"].tolist()
    retained_legacy = legacy.loc[legacy["recommendation"].ne("ARCHIVED"), "strategy_id"].tolist()
    returns = pd.concat([legacy_returns[retained_legacy], fundamental_returns[viable]], axis=1, join="inner")
    regimes = regime_analysis(returns)
    final = final_recommendations(rows, legacy, fundamentals, regimes)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    legacy.to_csv(OUTPUT_ROOT / "legacy_diagnostics.csv", index=False)
    fundamentals.to_csv(OUTPUT_ROOT / "fundamental_diagnostics.csv", index=False)
    regimes.to_csv(OUTPUT_ROOT / "market_proxy_regime_v0.csv", index=False)
    final.to_csv(OUTPUT_ROOT / "final_recommendations.csv", index=False)
    (OUTPUT_ROOT / "run_manifest.json").write_text(
        json.dumps(
            {
                "status": "RESEARCH_ONLY",
                "registry_updated": True,
                "combined_portfolio_updated": True,
                "dashboard_updated": True,
                "live_allocation_percent": 0.0,
                "execution_enabled": False,
                "regime_id": "MARKET_PROXY_REGIME_V0",
                "regime_disclosure": "Market-proxy diagnostic only; not a true macro Growth x Inflation model.",
                "regime_method": (
                    "Prior-day 63-day SPY return sign is the growth proxy; prior-day 63-day TIP minus IEF "
                    "relative-return sign is the inflation proxy. Analysis only; weights unchanged."
                ),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(final.groupby("recommendation").size().to_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
