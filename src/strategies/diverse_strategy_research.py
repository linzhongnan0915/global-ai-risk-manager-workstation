"""Compact Universe Foundation + Diverse Strategy Research batch."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.risk.performance import sharpe_ratio
from src.strategies.c3a1_signals import (
    residual_momentum_12_1,
    relative_strength_12_1,
    stable_dollar_volume,
    volume_confirmed_trend,
)
from src.strategies.c3a2_signals import (
    low_intraday_range_volatility,
    low_realized_volatility_60d,
    medium_term_reversal_22d,
    short_term_reversal_5d,
    slow_momentum_9_1,
)
from src.strategies.fundamental_data import SecEdgarClient, normalize_company_facts
from src.strategies.fundamental_research import (
    OHLCV_CACHE,
    _rank_mean,
    build_candidate_scores,
    build_raw_component_panel,
    run_candidate,
)
from src.strategies.liquidity_resilience import liquidity_resilience_score
from src.strategies.overnight_gap_reversal import overnight_gap_reversal_score
from src.strategies.strategy_factory import StrategyContext, load_context
from src.strategies.universe_foundation import (
    diagnostic_broad_membership,
    diagnostic_small_cap_membership,
    universe_manifest,
    write_universe_outputs,
)

PACK_ID = "UNIVERSE_FOUNDATION_DIVERSE_STRATEGY_RESEARCH_V1"
OUTPUT_ROOT = Path("output/research/universe_foundation_diverse_strategy_v1")
REBALANCE_EVERY = 20

CANDIDATES = {
    "RESIDUAL_MOMENTUM_ENSEMBLE": ("US_BROAD_LIQUID_POINT_IN_TIME", "momentum ensemble"),
    "PRICE_VOLUME_REVERSAL_ENSEMBLE": ("US_BROAD_LIQUID_POINT_IN_TIME", "price-volume reversal ensemble"),
    "VOLATILITY_LIQUIDITY_DEFENSIVE_ENSEMBLE": ("US_BROAD_LIQUID_POINT_IN_TIME", "defensive volatility/liquidity ensemble"),
    "OVERNIGHT_INTRADAY_ENSEMBLE": ("US_BROAD_LIQUID_POINT_IN_TIME", "overnight/intraday reversal ensemble"),
    "VALUE_QUALITY": ("SP500_POINT_IN_TIME", "value and quality"),
    "CAPEX_PRODUCTIVITY": ("SP500_POINT_IN_TIME", "capex productivity"),
    "PROFITABLE_SMALL_CAP_GROWTH": ("US_SMALL_CAP_LIQUID_POINT_IN_TIME", "profitable small-cap growth"),
    "SHAREHOLDER_YIELD_CAPITAL_ALLOCATION": ("SP500_POINT_IN_TIME", "shareholder yield/capital allocation"),
    "FILING_SHOCK_CONTINUATION": ("US_BROAD_LIQUID_POINT_IN_TIME", "event-driven filing continuation"),
    "CAPITAL_ALLOCATION_EVENT": ("US_BROAD_LIQUID_POINT_IN_TIME", "event-driven capital allocation"),
    "FUNDAMENTAL_SHOCK_RECOVERY": ("US_BROAD_LIQUID_POINT_IN_TIME", "matched-control fundamental shock recovery"),
}


def normalize_component(component: pd.DataFrame) -> pd.DataFrame:
    ranked = component.rank(axis=1, pct=True)
    return ranked.sub(ranked.mean(axis=1), axis=0).mul(2.0)


def combine_components(components: list[pd.DataFrame], weights: list[float]) -> pd.DataFrame:
    """Combine normalized signals before positions/returns so opposing trades net before costs."""
    if len(components) != len(weights) or not components:
        raise ValueError("components and weights must have equal non-zero length")
    total = float(sum(weights))
    return sum(normalize_component(component).mul(weight / total) for component, weight in zip(components, weights))


def _ensemble_scores(context: StrategyContext) -> dict[str, pd.DataFrame]:
    prior_intraday_reversal = -context.panels["close"].div(context.panels["open"]).sub(1.0).shift(1)
    return {
        "RESIDUAL_MOMENTUM_ENSEMBLE": combine_components(
            [residual_momentum_12_1(context), relative_strength_12_1(context), slow_momentum_9_1(context)],
            [0.4, 0.3, 0.3],
        ),
        "PRICE_VOLUME_REVERSAL_ENSEMBLE": combine_components(
            [short_term_reversal_5d(context), medium_term_reversal_22d(context), -volume_confirmed_trend(context)],
            [0.4, 0.35, 0.25],
        ),
        "VOLATILITY_LIQUIDITY_DEFENSIVE_ENSEMBLE": combine_components(
            [low_realized_volatility_60d(context), low_intraday_range_volatility(context), stable_dollar_volume(context), liquidity_resilience_score(context)],
            [0.3, 0.25, 0.2, 0.25],
        ),
        "OVERNIGHT_INTRADAY_ENSEMBLE": combine_components(
            [overnight_gap_reversal_score(context), prior_intraday_reversal, short_term_reversal_5d(context)],
            [0.5, 0.25, 0.25],
        ),
    }


def matched_control_recovery_score(raw: pd.DataFrame, context: StrategyContext) -> pd.Series:
    """Residualize fundamental shock on available size, volatility, liquidity, and prior-return controls."""
    vol = context.daily_returns.rolling(63, min_periods=63).std().shift(1)
    prior_return = context.panels["adj_close"].shift(1).div(context.panels["adj_close"].shift(64)).sub(1.0)
    rows: list[pd.Series] = []
    for date, frame in raw.groupby(level="date"):
        tickers = frame.index.get_level_values("ticker")
        controls = pd.DataFrame(
            {
                "size": np.log(frame["market_cap"].replace(0, np.nan).values),
                "volatility": vol.loc[date, tickers].values,
                "liquidity": np.log(context.lagged_adv.loc[date, tickers].replace(0, np.nan).values),
                "prior_return": prior_return.loc[date, tickers].values,
            },
            index=frame.index,
        )
        shock = -(frame["revenue_acceleration"] + frame["annual_margin_change"])
        valid = controls.notna().all(axis=1) & shock.notna()
        result = pd.Series(np.nan, index=frame.index)
        if valid.sum() >= 10:
            x = np.column_stack([np.ones(valid.sum()), controls.loc[valid].to_numpy()])
            residual = shock.loc[valid].to_numpy() - x @ np.linalg.lstsq(x, shock.loc[valid].to_numpy(), rcond=None)[0]
            result.loc[valid] = residual * -controls.loc[valid, "prior_return"]
        rows.append(result)
    return pd.concat(rows).sort_index()


def _load_facts(root: Path, context: StrategyContext, user_agent: str) -> pd.DataFrame:
    client = SecEdgarClient(user_agent=user_agent, cache_dir=root / "data/raw/sec_edgar_cache")
    cik_map = client.ticker_cik_map()
    frames = [
        normalize_company_facts(ticker, client.company_facts(cik_map[ticker]), client.submissions(cik_map[ticker]))
        for ticker in context.panels["close"].columns if ticker in cik_map
    ]
    return pd.concat(frames, ignore_index=True)


def _active_returns(bundle_path: Path) -> pd.DataFrame:
    payload = json.loads(bundle_path.read_text(encoding="utf-8"))
    shared_dates = payload["shared_dates"]
    series: dict[str, pd.Series] = {}
    for row in payload["factory_strategy_research"]["results"]:
        factory = row.get("backtest", {}).get("factory_research", {})
        if factory.get("membership") != "ACTIVE":
            continue
        returns = row["backtest"]["return_series"]
        values = returns["net_returns"]
        dates = returns.get("dates") or shared_dates[: len(values)]
        series[row["strategy_id"]] = pd.Series(values, index=pd.to_datetime(dates))
    return pd.DataFrame(series)


def _mask_from_membership(membership: pd.DataFrame, dates: pd.DatetimeIndex, tickers: pd.Index) -> pd.DataFrame:
    pivot = membership.pivot(index="rebalance_date", columns="ticker", values="included")
    return pivot.reindex(index=dates, columns=tickers).ffill().fillna(False).astype(bool)


def _screen(summary: dict[str, object], max_corr: float, marginal_sharpe: float) -> str:
    if summary["average_eligible_count"] < 20 or summary["annualized_turnover"] == 0:
        return "DATA_INSUFFICIENT"
    if summary["net_cumulative_return"] <= 0 and summary["preliminary_oos_net_return"] <= 0:
        return "ARCHIVED"
    if (
        summary["net_cumulative_return"] > 0
        and summary["preliminary_oos_net_return"] >= -0.02
        and summary["net_sharpe"] >= 0.25
        and summary["total_cost_drag"] < max(summary["gross_cumulative_return"], 0.01)
        and max_corr < 0.90
        and (summary["net_sharpe"] >= 0.35 or marginal_sharpe > 0)
    ):
        return "ACTIVE_CANDIDATE"
    return "REPAIR"


def _market_proxy_regime_labels(root: Path, index: pd.DatetimeIndex) -> pd.Series:
    path = root / "data/raw/fundamental_research/growth_inflation_proxy_ohlcv.csv"
    raw = pd.read_csv(path, parse_dates=["date"])
    close = raw.pivot(index="date", columns="ticker", values="adj_close").sort_index()
    growth = close["SPY"].pct_change(63).shift(1)
    inflation = (close["TIP"].pct_change(63) - close["IEF"].pct_change(63)).shift(1)
    labels = pd.Series(index=close.index, dtype=object)
    labels.loc[growth.ge(0) & inflation.ge(0)] = "MARKET_PROXY_GROWTH_UP_INFLATION_UP"
    labels.loc[growth.ge(0) & inflation.lt(0)] = "MARKET_PROXY_GROWTH_UP_INFLATION_DOWN"
    labels.loc[growth.lt(0) & inflation.ge(0)] = "MARKET_PROXY_GROWTH_DOWN_INFLATION_UP"
    labels.loc[growth.lt(0) & inflation.lt(0)] = "MARKET_PROXY_GROWTH_DOWN_INFLATION_DOWN"
    return labels.reindex(index).ffill()


def run_diverse_strategy_research(project_root: str | Path, *, user_agent: str) -> dict[str, object]:
    root = Path(project_root)
    output = root / OUTPUT_ROOT
    output.mkdir(parents=True, exist_ok=True)
    context = load_context(root / OHLCV_CACHE)
    signal_dates = context.panels["close"].index[::REBALANCE_EVERY]
    facts = _load_facts(root, context, user_agent)
    raw = build_raw_component_panel(facts, context, signal_dates)
    tickers = context.panels["close"].columns

    broad = diagnostic_broad_membership(signal_dates, context.panels["close"], context.lagged_adv)
    broad_mask = _mask_from_membership(broad, context.panels["close"].index, tickers)
    market_cap = raw["market_cap"].unstack("ticker").reindex(index=signal_dates, columns=tickers)
    small = diagnostic_small_cap_membership(broad, market_cap)
    small_mask = _mask_from_membership(small, context.panels["close"].index, tickers)

    empty = pd.DataFrame(columns=["rebalance_date", "ticker", "included", "reason"])
    manifests = {
        "SP500_POINT_IN_TIME": universe_manifest(
            "SP500_POINT_IN_TIME", source_mode="WRDS_CRSP_REQUIRED", status="DATA_UNAVAILABLE",
            labels=["POINT_IN_TIME_REQUIRED", "NO_CURRENT_LIST_SUBSTITUTION"],
            rule="WRDS/CRSP historical constituents with effective start/end dates.", member_counts=pd.Series(dtype=int),
        ),
        "US_BROAD_LIQUID_POINT_IN_TIME": universe_manifest(
            "US_BROAD_LIQUID_POINT_IN_TIME", source_mode="CURRENT_LISTED_DIAGNOSTIC", status="DIAGNOSTIC_FALLBACK",
            labels=["CURRENT_LISTED_DIAGNOSTIC", "SURVIVORSHIP_BIAS_PRESENT"],
            rule="price >= 5; lagged ADV20 >= 5m; >=60 price observations; formal CRSP history unavailable.",
            member_counts=broad.loc[broad["included"]].groupby("rebalance_date").size(),
        ),
        "US_SMALL_CAP_LIQUID_POINT_IN_TIME": universe_manifest(
            "US_SMALL_CAP_LIQUID_POINT_IN_TIME", source_mode="CURRENT_LISTED_DIAGNOSTIC", status="DIAGNOSTIC_FALLBACK",
            labels=["CURRENT_LISTED_DIAGNOSTIC", "SURVIVORSHIP_BIAS_PRESENT"],
            rule="Broad diagnostic eligibility; available shares x prior close; exclude bottom 10%; select next 30%.",
            member_counts=small.loc[small["included"]].groupby("rebalance_date").size(),
        ),
        "PILOT_500": universe_manifest(
            "PILOT_500", source_mode="LEGACY_BASELINE", status="LEGACY_BASELINE",
            labels=["LEGACY_BASELINE"], rule="Retained for historical comparison only.", member_counts=pd.Series(dtype=int),
        ),
    }
    write_universe_outputs(output / "universes", "SP500_POINT_IN_TIME", empty, manifests["SP500_POINT_IN_TIME"])
    write_universe_outputs(output / "universes", "US_BROAD_LIQUID_POINT_IN_TIME", broad, manifests["US_BROAD_LIQUID_POINT_IN_TIME"])
    write_universe_outputs(output / "universes", "US_SMALL_CAP_LIQUID_POINT_IN_TIME", small, manifests["US_SMALL_CAP_LIQUID_POINT_IN_TIME"])
    write_universe_outputs(output / "universes", "PILOT_500", empty, manifests["PILOT_500"])

    fundamental = build_candidate_scores(raw, context.panels["close"].index, tickers)
    filing_shock = _rank_mean(raw, ["revenue_acceleration", "annual_ocf_growth", "annual_margin_change"]).unstack("ticker")
    recovery = matched_control_recovery_score(raw, context).unstack("ticker")
    scores = _ensemble_scores(context) | {
        "PROFITABLE_SMALL_CAP_GROWTH": fundamental["PROFITABLE_SMALL_CAP"].where(small_mask),
        "FILING_SHOCK_CONTINUATION": filing_shock.reindex(context.panels["close"].index).ffill().where(broad_mask),
        "FUNDAMENTAL_SHOCK_RECOVERY": recovery.reindex(context.panels["close"].index).ffill().where(broad_mask),
    }
    for strategy_id in list(scores):
        if strategy_id != "PROFITABLE_SMALL_CAP_GROWTH":
            scores[strategy_id] = scores[strategy_id].where(broad_mask)

    active = _active_returns(root / "dashboard/data/us_equity_research_bundle.json")
    base_sharpe = float(sharpe_ratio(active.mean(axis=1)))
    summaries, daily_parts, holdings_parts, trade_parts = [], [], [], []
    run_id = f"{PACK_ID}_{context.panels['close'].index.max().date().isoformat()}"
    returns: dict[str, pd.Series] = {}
    for strategy_id, score in scores.items():
        daily, holdings, trades, summary = run_candidate(strategy_id, score, context, run_id=run_id)
        candidate = daily.set_index("date")["net_return"]
        aligned = pd.concat([active, candidate.rename(strategy_id)], axis=1, join="inner")
        correlations = aligned.corr().loc[strategy_id, active.columns].abs()
        marginal = float(sharpe_ratio(aligned.mean(axis=1)) - base_sharpe)
        summary.update(
            {
                "actual_universe_used": "US_SMALL_CAP_LIQUID_POINT_IN_TIME_DIAGNOSTIC_FALLBACK"
                if strategy_id == "PROFITABLE_SMALL_CAP_GROWTH" else "US_BROAD_LIQUID_POINT_IN_TIME_DIAGNOSTIC_FALLBACK",
                "universe_source_mode": "CURRENT_LISTED_DIAGNOSTIC",
                "bias_labels": "CURRENT_LISTED_DIAGNOSTIC | SURVIVORSHIP_BIAS_PRESENT",
                "maximum_active_correlation": float(correlations.max()),
                "average_active_correlation": float(correlations.mean()),
                "marginal_active_portfolio_sharpe": marginal,
                "recommendation": _screen(summary, float(correlations.max()), marginal),
                "economic_rationale": CANDIDATES[strategy_id][1],
                "primary_limitation": "Current-listed diagnostic fallback; survivorship bias present.",
            }
        )
        if strategy_id.startswith(("FILING_", "FUNDAMENTAL_SHOCK")):
            summary["research_labels"] = "EVENT_DRIVEN_DIAGNOSTIC" + (
                " | CAUSAL_INSPIRED_NOT_CAUSAL_PROOF | MATCHED_CONTROL_DIAGNOSTIC"
                if strategy_id == "FUNDAMENTAL_SHOCK_RECOVERY" else ""
            )
        summaries.append(summary)
        daily_parts.append(daily.assign(strategy_id=strategy_id))
        holdings_parts.append(holdings)
        trade_parts.append(trades)
        returns[strategy_id] = candidate

    insufficient = {
        "VALUE_QUALITY": "SP500_POINT_IN_TIME DATA_UNAVAILABLE; current S&P list substitution prohibited.",
        "CAPEX_PRODUCTIVITY": "SP500_POINT_IN_TIME DATA_UNAVAILABLE; current S&P list substitution prohibited.",
        "SHAREHOLDER_YIELD_CAPITAL_ALLOCATION": "SP500_POINT_IN_TIME DATA_UNAVAILABLE and payout/issuance coverage insufficient.",
        "CAPITAL_ALLOCATION_EVENT": "Reliable point-in-time issuance and payout-event coverage is insufficient.",
    }
    for strategy_id, reason in insufficient.items():
        summaries.append(
            {
                "strategy_id": strategy_id, "actual_universe_used": "NONE", "universe_source_mode": "DATA_UNAVAILABLE",
                "bias_labels": "POINT_IN_TIME_REQUIRED", "recommendation": "DATA_INSUFFICIENT",
                "economic_rationale": CANDIDATES[strategy_id][1], "primary_limitation": reason,
            }
        )

    pd.DataFrame(summaries).to_csv(output / "candidate_summary.csv", index=False)
    pd.concat(daily_parts, ignore_index=True).to_csv(output / "daily_strategy_returns.csv", index=False)
    pd.concat(holdings_parts, ignore_index=True).to_csv(output / "holdings.csv", index=False)
    pd.concat(trade_parts, ignore_index=True).to_csv(output / "trade_log.csv", index=False)
    pd.DataFrame(returns).corr().to_csv(output / "candidate_correlation_matrix.csv")
    return_panel = pd.DataFrame(returns)
    regime_labels = _market_proxy_regime_labels(root, return_panel.index)
    regime_rows = []
    for strategy_id in return_panel:
        for regime in sorted(regime_labels.dropna().unique()):
            selected = return_panel.loc[regime_labels.eq(regime), strategy_id].dropna()
            regime_rows.append(
                {
                    "strategy_id": strategy_id, "regime_id": "MARKET_PROXY_REGIME_V0",
                    "regime": regime, "observations": len(selected),
                    "net_cumulative_return": float(selected.add(1).prod() - 1),
                    "net_sharpe": float(sharpe_ratio(selected)) if len(selected) > 1 else np.nan,
                    "alters_weights": False,
                    "disclosure": "Lagged SPY/TIP/IEF market proxies; not a true macroeconomic regime.",
                }
            )
    pd.DataFrame(regime_rows).to_csv(output / "market_proxy_regime_v0.csv", index=False)
    specifications = {
        strategy_id: {"primary_universe": universe, "economic_rationale": rationale, "execution": "NEXT_OPEN_TO_OPEN", "buy_bps": 5, "sell_bps": 5}
        for strategy_id, (universe, rationale) in CANDIDATES.items()
    }
    (output / "strategy_specification.json").write_text(json.dumps(specifications, indent=2), encoding="utf-8")
    (output / "run_manifest.json").write_text(
        json.dumps(
            {
                "pack_id": PACK_ID, "status": "RESEARCH_ONLY", "universe_manifests": manifests,
                "execution": "NEXT_OPEN_TO_OPEN", "buy_bps": 5, "sell_bps": 5,
                "market_proxy_regime": {"id": "MARKET_PROXY_REGIME_V0", "alters_weights": False},
                "historical_sector_industry_status": "UNAVAILABLE_NOT_BACKFILLED",
                "active_membership_changed": False, "combined_portfolio_changed": False,
                "dashboard_changed": False, "live_allocation_approved": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return {"summaries": summaries, "output_root": output}
