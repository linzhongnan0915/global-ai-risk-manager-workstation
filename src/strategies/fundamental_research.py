"""Fundamental Strategy Research Pack v1: current-listed diagnostic candidates."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
import json

import numpy as np
import pandas as pd

from src.risk.performance import cumulative_returns, max_drawdown, sharpe_ratio, volatility
from src.strategies.fundamental_data import FIELD_TAGS, SecEdgarClient, normalize_company_facts
from src.strategies.strategy_factory import (
    StrategyContext,
    StrategySpec,
    build_execution_returns,
    common_eligibility,
    load_context,
    rank_and_weight,
)
from src.strategies.worldquant.portfolio_returns import compute_portfolio_returns_from_weights

PACK_ID = "FINAL_FUNDAMENTAL_RESEARCH_V1"
OUTPUT_ROOT = Path("output/research/final_fundamental_research_v1")
OHLCV_CACHE = Path("data/raw/fundamental_research/expanded_diagnostic_ohlcv.csv")
START_DATE = "2018-01-02"
END_DATE = "2026-06-10"
REBALANCE_EVERY = 20
MIN_CROSS_SECTION = 20
BUY_BPS = SELL_BPS = 5.0

CANDIDATE_FORMULAS = {
    "FUNDAMENTAL_MOMENTUM": ["annual revenue growth", "annual change operating margin", "annual change operating_cash_flow/assets"],
    "CAPEX_EFFICIENCY": ["annual revenue growth", "annual change revenue/assets", "free_cash_flow/assets", "negative annual asset growth"],
    "EARNINGS_QUALITY": ["negative accruals/assets", "operating_cash_flow/revenue", "operating_cash_flow/abs(net_income)"],
    "PROFITABLE_SMALL_CAP": ["negative market_cap", "quality score", "positive annual revenue growth"],
    "CONSERVATIVE_ASSET_GROWTH": ["negative annual asset growth", "quality score"],
    "CASH_FLOW_YIELD": ["operating_cash_flow/market_cap", "free_cash_flow/market_cap"],
    "MARGIN_IMPROVEMENT": ["annual change operating margin", "annual change operating_cash_flow/revenue"],
    "REVENUE_ACCELERATION": ["current annual revenue growth minus prior annual revenue growth"],
    "CASH_FLOW_MOMENTUM": ["annual operating cash-flow growth", "annual change operating_cash_flow/assets"],
    "LOW_LEVERAGE_QUALITY": ["negative liabilities/assets", "quality score"],
    "QUALITY_AT_REASONABLE_PRICE": ["quality score", "earnings yield", "free_cash_flow yield"],
    "SHAREHOLDER_YIELD": ["annual dividends plus annual share repurchases divided by point-in-time market cap"],
}


def safe_divide(numerator: float | pd.Series, denominator: float | pd.Series, *, epsilon: float = 1e-9):
    denominator = denominator.where(denominator.abs() > epsilon) if isinstance(denominator, pd.Series) else (
        denominator if abs(denominator) > epsilon else np.nan
    )
    return numerator / denominator


def normalized_capex(value: float | pd.Series):
    """SEC PaymentsToAcquirePropertyPlantAndEquipment is treated as a positive outflow magnitude."""
    return value.abs() if isinstance(value, pd.Series) else abs(value)


def _latest_period_rows(available: pd.DataFrame, *, annual_only: bool) -> pd.DataFrame:
    working = available.loc[available["form"].eq("10-K")] if annual_only else available
    if working.empty:
        return working
    tag_priority = {
        (field, tag): priority
        for field, tags in FIELD_TAGS.items()
        for priority, tag in enumerate(tags)
    }
    working = working.assign(
        tag_priority=[
            tag_priority.get((field, tag), 999)
            for field, tag in zip(working["field"], working["taxonomy_tag"])
        ]
    ).sort_values(
        ["field", "fiscal_period_end", "availability_datetime", "tag_priority"],
        ascending=[True, True, False, True],
    )
    return working.drop_duplicates(["field", "fiscal_period_end"], keep="first")


def _values_by_period(available: pd.DataFrame, *, annual_only: bool) -> dict[str, list[float]]:
    latest = _latest_period_rows(available, annual_only=annual_only)
    output: dict[str, list[float]] = {}
    for field, rows in latest.groupby("field"):
        ordered = rows.sort_values("fiscal_period_end")
        output[field] = [float(value) for value in ordered["value"].tail(3)]
    return output


def _last(values: dict[str, list[float]], field: str, offset: int = 1) -> float:
    series = values.get(field, [])
    return series[-offset] if len(series) >= offset else np.nan


def _raw_components_for_ticker(available: pd.DataFrame, prior_close: float) -> dict[str, float]:
    current = _values_by_period(available, annual_only=False)
    annual = _values_by_period(available, annual_only=True)
    assets = _last(current, "assets")
    revenue = _last(current, "revenue")
    net_income = _last(current, "net_income")
    ocf = _last(current, "operating_cash_flow")
    capex = normalized_capex(_last(current, "capex"))
    shares = _last(current, "shares_outstanding")
    market_cap = shares * prior_close if shares > 0 and prior_close > 0 else np.nan

    revenue_now, revenue_prev = _last(annual, "revenue"), _last(annual, "revenue", 2)
    assets_now, assets_prev = _last(annual, "assets"), _last(annual, "assets", 2)
    op_now, op_prev = _last(annual, "operating_income"), _last(annual, "operating_income", 2)
    gp_now, gp_prev = _last(annual, "gross_profit"), _last(annual, "gross_profit", 2)
    ocf_now, ocf_prev = _last(annual, "operating_cash_flow"), _last(annual, "operating_cash_flow", 2)
    capex_now, capex_prev = normalized_capex(_last(annual, "capex")), normalized_capex(_last(annual, "capex", 2))
    liabilities_now, liabilities_prev = _last(annual, "liabilities"), _last(annual, "liabilities", 2)
    receivables_now, receivables_prev = _last(annual, "receivables"), _last(annual, "receivables", 2)
    inventory_now, inventory_prev = _last(annual, "inventory"), _last(annual, "inventory", 2)
    revenue_prior = _last(annual, "revenue", 3)
    ocf_prior = _last(annual, "operating_cash_flow", 3)
    revenue_growth = safe_divide(revenue_now - revenue_prev, abs(revenue_prev))
    prior_revenue_growth = safe_divide(revenue_prev - revenue_prior, abs(revenue_prior))
    ocf_growth = safe_divide(ocf_now - ocf_prev, abs(ocf_prev))
    asset_growth = safe_divide(assets_now - assets_prev, abs(assets_prev))
    fcf = ocf - capex
    annual_payout = _last(annual, "dividends_paid") + _last(annual, "share_repurchases")
    gross_margins = [
        safe_divide(gross_profit, period_revenue)
        for gross_profit, period_revenue in zip(annual.get("gross_profit", []), annual.get("revenue", []))
    ]

    return {
        "quality_gp_assets": safe_divide(_last(current, "gross_profit"), assets),
        "quality_op_assets": safe_divide(_last(current, "operating_income"), assets),
        "quality_ocf_assets": safe_divide(ocf, assets),
        "annual_revenue_growth": revenue_growth,
        "revenue_acceleration": revenue_growth - prior_revenue_growth,
        "annual_ocf_growth": ocf_growth,
        "annual_margin_change": safe_divide(op_now, revenue_now) - safe_divide(op_prev, revenue_prev),
        "annual_ocf_assets_change": safe_divide(ocf_now, assets_now) - safe_divide(ocf_prev, assets_prev),
        "annual_gp_assets_change": safe_divide(gp_now, assets_now) - safe_divide(gp_prev, assets_prev),
        "annual_op_assets_change": safe_divide(op_now, assets_now) - safe_divide(op_prev, assets_prev),
        "annual_operating_income_growth": safe_divide(op_now - op_prev, abs(op_prev)),
        "annual_cash_flow_margin_change": safe_divide(ocf_now, revenue_now) - safe_divide(ocf_prev, revenue_prev),
        "annual_asset_turnover_change": safe_divide(revenue_now, assets_now) - safe_divide(revenue_prev, assets_prev),
        "asset_turnover": safe_divide(revenue, assets),
        "capex_assets": safe_divide(capex, assets),
        "prior_capex_assets": safe_divide(capex_prev, assets_prev),
        "fcf_assets": safe_divide(fcf, assets),
        "negative_asset_growth": -asset_growth,
        "negative_accruals_assets": -safe_divide(net_income - ocf, assets),
        "ocf_revenue": safe_divide(ocf, revenue),
        "ocf_abs_net_income": safe_divide(ocf, abs(net_income)),
        "earnings_yield": safe_divide(net_income, market_cap),
        "cash_flow_yield": safe_divide(ocf, market_cap),
        "book_to_market": safe_divide(_last(current, "equity"), market_cap),
        "fcf_yield": safe_divide(fcf, market_cap),
        "negative_market_cap": -market_cap,
        "negative_liabilities_assets": -safe_divide(_last(current, "liabilities"), assets),
        "negative_liabilities_assets_change": -(
            safe_divide(liabilities_now, assets_now) - safe_divide(liabilities_prev, assets_prev)
        ),
        "gross_margin": safe_divide(_last(current, "gross_profit"), revenue),
        "gross_margin_stability": -float(np.nanstd(gross_margins)) if len(gross_margins) >= 3 else np.nan,
        "receivables_growth_gap": -(safe_divide(receivables_now - receivables_prev, abs(receivables_prev)) - revenue_growth),
        "inventory_growth_gap": -(safe_divide(inventory_now - inventory_prev, abs(inventory_prev)) - revenue_growth),
        "shareholder_yield": safe_divide(annual_payout, market_cap),
        "market_cap": market_cap,
    }


def build_raw_component_panel(
    facts: pd.DataFrame, context: StrategyContext, signal_dates: pd.DatetimeIndex
) -> pd.DataFrame:
    """Build point-in-time raw components using filings and prices known before each execution open."""
    rows: list[dict[str, object]] = []
    close = context.panels["close"].shift(1)
    grouped = {ticker: frame for ticker, frame in facts.groupby("ticker")}
    for signal_date in signal_dates:
        cutoff = pd.Timestamp(signal_date).tz_localize("UTC") - pd.Timedelta(nanoseconds=1)
        for ticker in close.columns:
            ticker_facts = grouped.get(ticker)
            if ticker_facts is None:
                continue
            available = ticker_facts.loc[ticker_facts["availability_datetime"].le(cutoff)]
            if available.empty:
                continue
            components = _raw_components_for_ticker(available, float(close.loc[signal_date, ticker]))
            rows.append({"date": signal_date, "ticker": ticker, **components})
    return pd.DataFrame(rows).set_index(["date", "ticker"]).sort_index()


def _rank_mean(raw: pd.DataFrame, columns: list[str], *, minimum: int = 2) -> pd.Series:
    ranked = pd.concat(
        [raw[column].groupby(level="date").rank(pct=True).rename(column) for column in columns],
        axis=1,
    )
    return ranked.mean(axis=1, skipna=True).where(ranked.notna().sum(axis=1) >= minimum)


def build_candidate_scores(raw: pd.DataFrame, dates: pd.DatetimeIndex, tickers: Iterable[str]) -> dict[str, pd.DataFrame]:
    quality = _rank_mean(raw, ["quality_gp_assets", "quality_op_assets", "quality_ocf_assets"])
    scores = {
        "FUNDAMENTAL_MOMENTUM": _rank_mean(
            raw, ["annual_revenue_growth", "annual_margin_change", "annual_ocf_assets_change"]
        ),
        "CAPEX_EFFICIENCY": _rank_mean(
            raw, ["annual_revenue_growth", "annual_asset_turnover_change", "fcf_assets", "negative_asset_growth"]
        ),
        "EARNINGS_QUALITY": _rank_mean(
            raw, ["negative_accruals_assets", "ocf_revenue", "ocf_abs_net_income"]
        ),
        "PROFITABLE_SMALL_CAP": pd.concat(
            [raw["negative_market_cap"].groupby(level="date").rank(pct=True), quality,
             raw["annual_revenue_growth"].groupby(level="date").rank(pct=True)],
            axis=1,
        ).mean(axis=1, skipna=True).where(raw["annual_revenue_growth"].gt(0) & raw["market_cap"].gt(0)),
        "CONSERVATIVE_ASSET_GROWTH": raw["negative_asset_growth"].groupby(level="date").rank(
            pct=True
        ).where(quality.notna()) * 0.7 + quality * 0.3,
        "CASH_FLOW_YIELD": _rank_mean(raw, ["cash_flow_yield", "fcf_yield"]),
        "MARGIN_IMPROVEMENT": _rank_mean(
            raw, ["annual_margin_change", "annual_cash_flow_margin_change"]
        ),
        "REVENUE_ACCELERATION": raw["revenue_acceleration"].groupby(level="date").rank(pct=True),
        "CASH_FLOW_MOMENTUM": _rank_mean(raw, ["annual_ocf_growth", "annual_ocf_assets_change"]),
        "LOW_LEVERAGE_QUALITY": pd.concat(
            [raw["negative_liabilities_assets"].groupby(level="date").rank(pct=True), quality],
            axis=1,
        ).mean(axis=1, skipna=False),
        "QUALITY_AT_REASONABLE_PRICE": pd.concat(
            [
                quality,
                raw["earnings_yield"].groupby(level="date").rank(pct=True),
                raw["fcf_yield"].groupby(level="date").rank(pct=True),
            ],
            axis=1,
        ).mean(axis=1, skipna=False),
        "SHAREHOLDER_YIELD": raw["shareholder_yield"].groupby(level="date").rank(pct=True),
    }
    output: dict[str, pd.DataFrame] = {}
    for strategy_id, series in scores.items():
        panel = series.unstack("ticker").reindex(index=dates, columns=list(tickers)).ffill()
        output[strategy_id] = panel
    return output


def build_trade_log(
    strategy_id: str, target: pd.DataFrame, open_prices: pd.DataFrame, *, run_id: str
) -> pd.DataFrame:
    columns = [
        "strategy_id", "signal_date", "rebalance_date", "execution_date", "ticker", "action",
        "previous_weight", "target_weight", "delta_weight", "simulated_execution_price",
        "turnover_contribution", "estimated_transaction_cost", "execution_convention", "run_id",
        "record_status",
    ]
    rows: list[dict[str, object]] = []
    if target.empty:
        return pd.DataFrame(columns=columns)
    previous = pd.Series(0.0, index=target.columns)
    for signal_date, weights in target.iloc[:-1].iterrows():
        if weights.equals(previous):
            continue
        for ticker, target_weight in weights.items():
            previous_weight = float(previous[ticker])
            target_weight = float(target_weight)
            if np.isclose(previous_weight, target_weight):
                continue
            legs: list[tuple[str, float]]
            if previous_weight < 0 < target_weight:
                legs = [("COVER", -previous_weight), ("BUY", target_weight)]
            elif previous_weight > 0 > target_weight:
                legs = [("SELL", previous_weight), ("SHORT", -target_weight)]
            elif target_weight > previous_weight:
                legs = [("COVER" if target_weight <= 0 else "BUY", target_weight - previous_weight)]
            else:
                legs = [("SELL" if previous_weight >= 0 else "SHORT", previous_weight - target_weight)]
            for action, contribution in legs:
                rows.append(
                    {
                        "strategy_id": strategy_id,
                        "signal_date": signal_date.date().isoformat(),
                        "rebalance_date": signal_date.date().isoformat(),
                        "execution_date": signal_date.date().isoformat(),
                        "ticker": ticker,
                        "action": action,
                        "previous_weight": previous_weight,
                        "target_weight": target_weight,
                        "delta_weight": target_weight - previous_weight,
                        "simulated_execution_price": open_prices.loc[signal_date, ticker],
                        "turnover_contribution": contribution,
                        "estimated_transaction_cost": contribution * (BUY_BPS + SELL_BPS) / 2 / 10_000,
                        "execution_convention": "NEXT_OPEN_TO_OPEN",
                        "run_id": run_id,
                        "record_status": "SIMULATED | RESEARCH ONLY | NO LIVE FILL",
                    }
                )
        previous = weights.copy()
    return pd.DataFrame(rows, columns=columns)


def _annual_return(returns: pd.Series) -> float:
    return float((returns.add(1).prod() ** (252 / len(returns))) - 1) if len(returns) else np.nan


def _summary(strategy_id: str, daily: pd.DataFrame, eligible: pd.DataFrame) -> dict[str, object]:
    split = int(len(daily) * 0.70)
    oos = daily["net_return"].iloc[split:]
    net = daily["net_return"]
    gross = daily["gross_return"]
    sharpe = float(sharpe_ratio(net))
    oos_sharpe = float(sharpe_ratio(oos)) if len(oos) > 1 else np.nan
    recommendation = "KEEP_CANDIDATE" if sharpe >= 0.4 and oos_sharpe > 0 else (
        "REVIEW" if sharpe >= 0.2 or oos_sharpe > 0 else "REJECT_CANDIDATE"
    )
    eligible_counts = eligible.sum(axis=1)
    positive_eligible_counts = eligible_counts.loc[eligible_counts.gt(0)]
    return {
        "strategy_id": strategy_id,
        "test_period_start": daily["date"].iloc[0].date().isoformat(),
        "test_period_end": daily["date"].iloc[-1].date().isoformat(),
        "observations": int(len(daily)),
        "gross_cumulative_return": float(gross.add(1).prod() - 1),
        "net_cumulative_return": float(net.add(1).prod() - 1),
        "annualized_net_return": _annual_return(net),
        "net_sharpe": sharpe,
        "annualized_volatility": float(volatility(net)),
        "max_drawdown": float(max_drawdown(net)),
        "average_daily_turnover": float(daily["turnover"].mean()),
        "annualized_turnover": float(daily["turnover"].mean() * 252),
        "total_cost_drag": float(daily["transaction_cost"].sum()),
        "preliminary_oos_start": daily["date"].iloc[split].date().isoformat(),
        "preliminary_oos_convention": "Chronological 70/30 split; PRELIMINARY_OOS",
        "preliminary_oos_net_return": float(oos.add(1).prod() - 1),
        "preliminary_oos_sharpe": oos_sharpe,
        "average_eligible_count": float(positive_eligible_counts.mean()) if len(positive_eligible_counts) else 0.0,
        "minimum_eligible_count": int(positive_eligible_counts.min()) if len(positive_eligible_counts) else 0,
        "recommendation": recommendation,
        "research_status": "CURRENT_LISTED_DIAGNOSTIC | SURVIVORSHIP_BIAS_PRESENT | RESEARCH_CANDIDATE",
        "live_allocation_approved": False,
    }


def run_candidate(
    strategy_id: str, score: pd.DataFrame, context: StrategyContext, *, run_id: str
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, object]]:
    spec = StrategySpec(
        strategy_id, f"{strategy_id.lower()}_v1", strategy_id.replace("_", " ").title(),
        "Fundamental research candidate; see frozen formula map.", lambda _: score, REBALANCE_EVERY,
        min_cross_section=MIN_CROSS_SECTION, buy_bps=BUY_BPS, sell_bps=SELL_BPS,
    )
    eligible = common_eligibility(score, context, spec)
    target, positions = rank_and_weight(score, eligible, spec)
    asset_returns, execution_lag, return_definition = build_execution_returns(context, spec)
    result = compute_portfolio_returns_from_weights(
        target, asset_returns, execution_lag=execution_lag, buy_bps=BUY_BPS,
        sell_bps=SELL_BPS, return_definition=return_definition,
    )
    daily = pd.DataFrame(
        {
            "date": score.index,
            "gross_return": result.gross_return,
            "transaction_cost": result.transaction_cost,
            "net_return": result.net_return,
            "turnover": result.turnover,
        }
    ).dropna(subset=["gross_return", "net_return"]).reset_index(drop=True)
    trades = build_trade_log(strategy_id, target, context.panels["open"], run_id=run_id)
    active_targets = target.loc[target.abs().sum(axis=1).gt(0)]
    holdings = pd.DataFrame()
    if not active_targets.empty:
        last_rebalance_date = pd.to_datetime(positions.loc[positions["rebalance"], "date"]).max()
        last = target.loc[last_rebalance_date]
        holdings = pd.DataFrame(
            [{"strategy_id": strategy_id, "date": last_rebalance_date.date().isoformat(), "ticker": ticker,
              "side": "LONG" if weight > 0 else "SHORT", "target_weight": weight}
             for ticker, weight in last.items() if weight != 0]
        )
    summary = _summary(strategy_id, daily, eligible)
    summary["trade_cost_reconciliation_error"] = float(
        abs(trades["estimated_transaction_cost"].sum() - daily["transaction_cost"].sum())
    )
    return daily, holdings, trades, summary


def _active_return_panel(bundle_path: Path) -> pd.DataFrame:
    payload = json.loads(bundle_path.read_text(encoding="utf-8"))
    dates = pd.to_datetime(payload["shared_dates"])
    return pd.DataFrame(
        {
            row["strategy_id"]: row["backtest"]["return_series"]["net_returns"]
            for row in payload["factory_strategy_research"]["results"]
            if row.get("backtest", {}).get("factory_research", {}).get("membership") == "ACTIVE"
        },
        index=dates,
    )


def run_fundamental_research_pack(project_root: str | Path, *, user_agent: str) -> dict[str, object]:
    root = Path(project_root)
    raw_cache = root / OHLCV_CACHE
    if raw_cache.exists():
        context = load_context(raw_cache)
    else:
        raise FileNotFoundError(
            "expanded diagnostic OHLCV cache is required; run scripts/run_expanded_selection_research.py"
        )

    client = SecEdgarClient(user_agent=user_agent, cache_dir=root / "data/raw/sec_edgar_cache")
    cik_map = client.ticker_cik_map()
    fact_frames = [
        normalize_company_facts(ticker, client.company_facts(cik_map[ticker]), client.submissions(cik_map[ticker]))
        for ticker in context.panels["close"].columns
        if ticker in cik_map
    ]
    facts = pd.concat(fact_frames, ignore_index=True)
    monthly_signal_dates = context.panels["close"].index[::REBALANCE_EVERY]
    raw = build_raw_component_panel(facts, context, monthly_signal_dates)
    scores = build_candidate_scores(raw, context.panels["close"].index, context.panels["close"].columns)

    run_id = f"{PACK_ID}_{context.panels['close'].index.max().date().isoformat()}"
    summaries, daily_parts, holdings_parts, trade_parts = [], [], [], []
    candidate_returns: dict[str, pd.Series] = {}
    for strategy_id, score in scores.items():
        daily, holdings, trades, summary = run_candidate(strategy_id, score, context, run_id=run_id)
        summaries.append(summary)
        daily_parts.append(daily.assign(strategy_id=strategy_id))
        holdings_parts.append(holdings)
        trade_parts.append(trades)
        candidate_returns[strategy_id] = daily.set_index("date")["net_return"]

    candidate_panel = pd.DataFrame(candidate_returns)
    active = _active_return_panel(root / "dashboard/data/us_equity_research_bundle.json")
    correlations = pd.concat([candidate_panel, active], axis=1, join="inner").corr()
    output = root / OUTPUT_ROOT
    output.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(summaries).to_csv(output / "candidate_summary.csv", index=False)
    pd.concat(daily_parts, ignore_index=True).to_csv(output / "daily_net_returns.csv", index=False)
    pd.concat(holdings_parts, ignore_index=True).to_csv(output / "holdings.csv", index=False)
    pd.concat(trade_parts, ignore_index=True).to_csv(output / "trade_log.csv", index=False)
    correlations.to_csv(output / "correlation_matrix.csv")
    (output / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id, "pack_id": PACK_ID, "candidate_formulas": CANDIDATE_FORMULAS,
                "universe": list(context.panels["close"].columns), "universe_rule": (
                    "Expanded current-listed liquid diagnostic universe; price >= $5; "
                    "lagged ADV20 >= $5m; minimum 20 eligible names. PROFITABLE_SMALL_CAP is "
                    "relative-small-cap within this diagnostic universe and also requires positive revenue growth."
                ),
                "signal_timing": "SEC acceptance/publication <= prior calendar day; market cap uses prior close.",
                "execution": "NEXT_OPEN_TO_OPEN", "buy_bps": BUY_BPS, "sell_bps": SELL_BPS,
                "labels": ["CURRENT_LISTED_DIAGNOSTIC", "SURVIVORSHIP_BIAS_PRESENT", "RESEARCH_CANDIDATE"],
                "live_allocation_approved": False, "fundamental_candidates_promoted": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return {"output_root": output, "summaries": summaries, "correlations": correlations}
