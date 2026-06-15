"""Expanded current-listed diagnostic universe and final candidate selection batch."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.risk.performance import sharpe_ratio
from src.strategies.c3a1_signals import relative_strength_6_1
from src.strategies.diverse_strategy_research import _active_returns, _market_proxy_regime_labels, combine_components
from src.strategies.final_delivery_research import _robustness
from src.strategies.fundamental_data import SecEdgarClient, normalize_company_facts
from src.strategies.fundamental_research import (
    _rank_mean,
    build_raw_component_panel,
    run_candidate,
)
from src.strategies.strategy_factory import StrategyContext, load_context
from src.strategies.universe_foundation import diagnostic_broad_membership, diagnostic_small_cap_membership
from src.strategies.worldquant.market_data import download_ohlcv
from src.strategies.worldquant.research_universe import filter_research_universe_v1
from src.strategies.worldquant.universe import build_universe_from_download

PACK_ID = "FINAL_EXPANDED_SELECTION_V1"
OUTPUT_ROOT = Path("output/research/final_expanded_selection_v1")
OHLCV_CACHE = Path("data/raw/fundamental_research/expanded_diagnostic_ohlcv.csv")
START_DATE = "2018-01-02"
END_DATE = "2026-06-11"
DOWNLOAD_BATCH_SIZE = 50
MIN_CROSS_SECTION = 20

CANDIDATE_IDS = (
    "LIQUIDITY_SHOCK_RECOVERY",
    "OPERATING_EFFICIENCY_IMPROVEMENT",
    "CAPEX_EFFICIENCY",
    "PROFITABLE_SMALL_CAP",
    "CASH_FLOW_MOMENTUM",
    "REVENUE_ACCELERATION",
    "LOW_LEVERAGE_QUALITY",
    "OVERNIGHT_GAP_REVERSAL_REDUCED_TURNOVER",
    "GROSS_PROFITABILITY_GROWTH",
    "CASH_FLOW_MARGIN_IMPROVEMENT",
    "QUALITY_MOMENTUM_COMPOSITE",
    "LOW_ACCRUAL_MOMENTUM",
)

ECONOMIC_RATIONALES = {
    "LIQUIDITY_SHOCK_RECOVERY": "Fade sufficiently broad abnormal price declines accompanied by volume shocks.",
    "OPERATING_EFFICIENCY_IMPROVEMENT": "Prefer improving operating margin, asset turnover, and operating cash return.",
    "CAPEX_EFFICIENCY": "Prefer growth and free cash flow achieved with conservative asset expansion.",
    "PROFITABLE_SMALL_CAP": "Prefer profitable liquid small-cap names outside the microcap tail.",
    "CASH_FLOW_MOMENTUM": "Prefer improving operating cash flow and operating cash return.",
    "REVENUE_ACCELERATION": "Prefer accelerating annual revenue growth.",
    "LOW_LEVERAGE_QUALITY": "Prefer lower liabilities relative to assets with operating quality.",
    "OVERNIGHT_GAP_REVERSAL_REDUCED_TURNOVER": "Fade only large overnight gaps and rebalance less frequently.",
    "GROSS_PROFITABILITY_GROWTH": "Prefer improvement in gross profit/assets and operating income/assets.",
    "CASH_FLOW_MARGIN_IMPROVEMENT": "Prefer improving cash-flow margin, operating cash return, and free cash flow.",
    "QUALITY_MOMENTUM_COMPOSITE": "Combine fundamental momentum, earnings quality, and margin improvement before construction.",
    "LOW_ACCRUAL_MOMENTUM": "Prefer lower accruals combined with positive price momentum.",
}

FIELD_REQUIREMENTS = {
    "OPERATING_EFFICIENCY_IMPROVEMENT": ("revenue", "operating_income", "assets", "operating_cash_flow"),
    "CAPEX_EFFICIENCY": ("revenue", "assets", "operating_cash_flow", "capex"),
    "PROFITABLE_SMALL_CAP": ("shares_outstanding", "revenue", "assets", "gross_profit", "operating_income", "operating_cash_flow"),
    "CASH_FLOW_MOMENTUM": ("operating_cash_flow", "assets"),
    "REVENUE_ACCELERATION": ("revenue",),
    "LOW_LEVERAGE_QUALITY": ("liabilities", "assets", "gross_profit", "operating_income", "operating_cash_flow"),
    "GROSS_PROFITABILITY_GROWTH": ("gross_profit", "operating_income", "assets"),
    "CASH_FLOW_MARGIN_IMPROVEMENT": ("operating_cash_flow", "revenue", "capex", "assets"),
    "QUALITY_MOMENTUM_COMPOSITE": ("revenue", "gross_profit", "operating_income", "net_income", "assets", "operating_cash_flow"),
    "LOW_ACCRUAL_MOMENTUM": ("net_income", "operating_cash_flow", "assets"),
}


def _stable_order(symbols: list[str]) -> list[str]:
    return sorted(symbols, key=lambda value: (hashlib.sha256(value.encode()).hexdigest(), value))


def _mask(membership: pd.DataFrame, dates: pd.DatetimeIndex, tickers: pd.Index) -> pd.DataFrame:
    return membership.pivot(index="rebalance_date", columns="ticker", values="included").reindex(
        index=dates, columns=tickers
    ).ffill().fillna(False).astype(bool)


def _latest_liquid_count(raw: pd.DataFrame) -> int:
    if raw.empty:
        return 0
    close = raw.pivot(index="date", columns="ticker", values="close").sort_index()
    volume = raw.pivot(index="date", columns="ticker", values="volume").sort_index()
    latest = close.iloc[-1].ge(5) & close.mul(volume).rolling(20, min_periods=20).mean().shift(1).iloc[-1].ge(5_000_000)
    history = close.notna().sum().ge(60)
    return int((latest & history).sum())


def build_expanded_ohlcv(root: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    master, _, universe_audit = build_universe_from_download()
    common = filter_research_universe_v1(master)
    symbols = common["symbol_normalized"].astype(str).str.upper().tolist()
    ordered = _stable_order(symbols)
    cache_path = root / OHLCV_CACHE
    cached = pd.read_csv(cache_path, parse_dates=["date"]) if cache_path.exists() else pd.DataFrame()
    existing = set(cached["ticker"].unique()) if not cached.empty else set()
    failures: list[pd.DataFrame] = []
    attempted = set(existing)
    # A populated cache is the durable record of the completed free-data download pass.
    # A fresh run traverses the full current-listed common-equity universe without a smoke cap.
    if existing:
        ordered = []
    for offset in range(0, len(ordered), DOWNLOAD_BATCH_SIZE):
        batch = [ticker for ticker in ordered[offset : offset + DOWNLOAD_BATCH_SIZE] if ticker not in attempted]
        if not batch:
            continue
        attempted.update(batch)
        downloaded, failed, _ = download_ohlcv(
            batch, start_date=START_DATE, end_date=END_DATE, batch_size=DOWNLOAD_BATCH_SIZE,
            max_attempts=3, include_rejected_history=True,
        )
        if not failed.empty:
            retry_symbols = failed["ticker"].drop_duplicates().tolist()
            retry, retry_failed, _ = download_ohlcv(
                retry_symbols, start_date=START_DATE, end_date=END_DATE, batch_size=1,
                max_attempts=2, include_rejected_history=True,
            )
            downloaded = pd.concat([downloaded, retry], ignore_index=True)
            failed = retry_failed
        if not downloaded.empty:
            cached = pd.concat([cached, downloaded], ignore_index=True).drop_duplicates(["ticker", "date"], keep="last")
        failures.append(failed)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cached.sort_values(["ticker", "date"]).to_csv(cache_path, index=False)
    failure_frame = pd.concat(failures, ignore_index=True) if failures else pd.DataFrame()
    audit = {
        "raw_securities": int(len(master)),
        "common_equities": int(len(common)),
        "ohlcv_downloads_attempted": int(len(attempted)),
        "ohlcv_downloads_succeeded": int(cached["ticker"].nunique()),
        "latest_price_liquidity_eligible": _latest_liquid_count(cached),
        "universe_source": "CURRENT_LISTED_DIAGNOSTIC",
        "survivorship_bias_present": True,
        "source_universe_audit": universe_audit,
    }
    return cached, failure_frame, audit


def _sec_lookup(cik_map: dict[str, str], ticker: str) -> str | None:
    candidates = (ticker, ticker.replace("-", "."), ticker.replace(".", "-"))
    return next((cik_map[value] for value in candidates if value in cik_map), None)


def load_expanded_facts(root: Path, tickers: list[str], user_agent: str) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    client = SecEdgarClient(user_agent=user_agent, cache_dir=root / "data/raw/sec_edgar_cache")
    cik_map = client.ticker_cik_map()
    frames, failures, mapped = [], [], 0
    for ticker in tickers:
        cik = _sec_lookup(cik_map, ticker)
        if cik is None:
            failures.append({"ticker": ticker, "stage": "sec_mapping", "reason": "ticker_not_in_sec_map"})
            continue
        mapped += 1
        try:
            frames.append(normalize_company_facts(ticker, client.company_facts(cik), client.submissions(cik)))
        except Exception as exc:  # noqa: BLE001 - coverage report records issuer-specific failures
            failures.append({"ticker": ticker, "stage": "sec_download", "reason": type(exc).__name__, "detail": str(exc)})
    facts = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return facts, pd.DataFrame(failures), {"sec_mapped": mapped, "sec_facts_loaded": int(facts["ticker"].nunique()) if not facts.empty else 0}


def candidate_scores(raw: pd.DataFrame, context: StrategyContext) -> dict[str, pd.DataFrame]:
    dates, tickers = context.panels["close"].index, context.panels["close"].columns
    quality = _rank_mean(raw, ["quality_gp_assets", "quality_op_assets", "quality_ocf_assets"])
    fundamental_momentum = _rank_mean(raw, ["annual_revenue_growth", "annual_margin_change", "annual_ocf_assets_change"])
    earnings_quality = _rank_mean(raw, ["negative_accruals_assets", "ocf_revenue", "ocf_abs_net_income"])
    margin = _rank_mean(raw, ["annual_margin_change", "annual_cash_flow_margin_change"])
    price_momentum = relative_strength_6_1(context).stack().reindex(raw.index)
    series = {
        "OPERATING_EFFICIENCY_IMPROVEMENT": _rank_mean(raw, ["annual_margin_change", "annual_asset_turnover_change", "annual_ocf_assets_change"]),
        "CAPEX_EFFICIENCY": _rank_mean(raw, ["annual_revenue_growth", "annual_asset_turnover_change", "fcf_assets", "negative_asset_growth"]),
        "PROFITABLE_SMALL_CAP": pd.concat([raw["negative_market_cap"].groupby(level="date").rank(pct=True), quality, raw["annual_revenue_growth"].groupby(level="date").rank(pct=True)], axis=1).mean(axis=1, skipna=False).where(raw["annual_revenue_growth"].gt(0)),
        "CASH_FLOW_MOMENTUM": _rank_mean(raw, ["annual_ocf_growth", "annual_ocf_assets_change"]),
        "REVENUE_ACCELERATION": raw["revenue_acceleration"].groupby(level="date").rank(pct=True),
        "LOW_LEVERAGE_QUALITY": pd.concat([raw["negative_liabilities_assets"].groupby(level="date").rank(pct=True), quality], axis=1).mean(axis=1, skipna=False),
        "GROSS_PROFITABILITY_GROWTH": _rank_mean(raw, ["annual_gp_assets_change", "annual_op_assets_change"]),
        "CASH_FLOW_MARGIN_IMPROVEMENT": _rank_mean(raw, ["annual_cash_flow_margin_change", "annual_ocf_assets_change", "fcf_assets"]),
        "QUALITY_MOMENTUM_COMPOSITE": pd.concat([fundamental_momentum, earnings_quality, margin], axis=1).mean(axis=1, skipna=False),
        "LOW_ACCRUAL_MOMENTUM": pd.concat([raw["negative_accruals_assets"].groupby(level="date").rank(pct=True), price_momentum.groupby(level="date").rank(pct=True)], axis=1).mean(axis=1, skipna=False),
    }
    output = {key: value.unstack("ticker").reindex(index=dates, columns=tickers).ffill() for key, value in series.items()}
    returns_5d = context.panels["adj_close"].shift(1).div(context.panels["adj_close"].shift(6)).sub(1)
    volume_z = context.panels["volume"].shift(1).sub(context.panels["volume"].shift(1).rolling(63, min_periods=63).mean()).div(
        context.panels["volume"].shift(1).rolling(63, min_periods=63).std().replace(0, np.nan)
    )
    output["LIQUIDITY_SHOCK_RECOVERY"] = combine_components([-returns_5d, volume_z], [0.65, 0.35]).where(returns_5d.lt(-0.03) & volume_z.gt(1))
    gap = context.panels["open"].div(context.panels["adj_close"].shift(1)).sub(1)
    output["OVERNIGHT_GAP_REVERSAL_REDUCED_TURNOVER"] = (-gap).where(gap.abs().ge(0.02))
    return output


def classify(row: dict[str, Any]) -> tuple[str, str]:
    if row["average_eligible_count"] < MIN_CROSS_SECTION or row["eligible_portfolio_days"] < 12:
        return "DATA_INSUFFICIENT", "Eligible cross-section is below the minimum diagnostic threshold."
    gates = (
        row["net_cumulative_return"] > 0,
        row["preliminary_oos_net_return"] > 0,
        row["net_sharpe"] >= 0.25,
        row["double_cost_net_return"] > 0,
        row["delayed_execution_net_return"] > 0,
        row["maximum_active_correlation"] < 0.90,
        row["marginal_combined_portfolio_sharpe"] > 0,
    )
    if all(gates):
        return "ACTIVE", "Passed positive return, OOS, Sharpe, robustness, coverage, correlation, and marginal portfolio gates."
    if row["net_cumulative_return"] <= 0 and row["preliminary_oos_net_return"] <= 0:
        return "ARCHIVED", "Full-period and preliminary OOS returns are both non-positive."
    return "REPAIR", "One or more strict ACTIVE gates failed; negative or low-Sharpe candidates are not promoted."


def run_expanded_selection(root_path: str | Path, *, user_agent: str) -> dict[str, Any]:
    root = Path(root_path)
    output = root / OUTPUT_ROOT
    output.mkdir(parents=True, exist_ok=True)
    ohlcv, download_failures, coverage = build_expanded_ohlcv(root)
    context = load_context(root / OHLCV_CACHE)
    signal_dates = context.panels["close"].index[::20]
    broad_membership = diagnostic_broad_membership(signal_dates, context.panels["close"], context.lagged_adv)
    broad_mask = _mask(broad_membership, context.panels["close"].index, context.panels["close"].columns)
    latest_broad = broad_membership.loc[broad_membership["rebalance_date"].eq(signal_dates[-1]) & broad_membership["included"], "ticker"].tolist()
    facts, sec_failures, sec_audit = load_expanded_facts(root, latest_broad, user_agent)
    raw = build_raw_component_panel(facts, context, signal_dates)
    scores = candidate_scores(raw, context)
    market_cap = raw["market_cap"].unstack("ticker").reindex(index=signal_dates, columns=context.panels["close"].columns)
    small_membership = diagnostic_small_cap_membership(broad_membership, market_cap)
    small_mask = _mask(small_membership, context.panels["close"].index, context.panels["close"].columns)
    for strategy_id in scores:
        scores[strategy_id] = scores[strategy_id].where(
            small_mask if strategy_id == "PROFITABLE_SMALL_CAP" else broad_mask
        )
    active = _active_returns(root / "dashboard/data/us_equity_research_bundle.json")
    active_base_sharpe = float(sharpe_ratio(active.mean(axis=1)))
    run_id = f"{PACK_ID}_{context.panels['close'].index.max().date().isoformat()}"
    summaries, daily_parts, holdings_parts, trade_parts, returns = [], [], [], [], {}
    for strategy_id in CANDIDATE_IDS:
        daily, holdings, trades, row = run_candidate(strategy_id, scores[strategy_id], context, run_id=run_id)
        candidate = daily.set_index("date")["net_return"]
        aligned = pd.concat([active, candidate.rename(strategy_id)], axis=1, join="inner")
        corr = aligned.corr().loc[strategy_id, active.columns].abs()
        row.update(_robustness(scores[strategy_id], context))
        row.update({
            "maximum_active_correlation": float(corr.max()),
            "average_active_correlation": float(corr.mean()),
            "marginal_combined_portfolio_sharpe": float(sharpe_ratio(aligned.mean(axis=1)) - active_base_sharpe),
            "actual_universe_used": "SMALL_CAP_FUNDAMENTAL_UNIVERSE" if strategy_id == "PROFITABLE_SMALL_CAP" else ("OHLCV_UNIVERSE" if strategy_id in {"LIQUIDITY_SHOCK_RECOVERY", "OVERNIGHT_GAP_REVERSAL_REDUCED_TURNOVER"} else "FUNDAMENTAL_UNIVERSE"),
            "labels": "CURRENT_LISTED_DIAGNOSTIC | SURVIVORSHIP_BIAS_PRESENT | RESEARCH ONLY",
            "live_allocation_approved": False, "execution_enabled": False,
            "economic_rationale": ECONOMIC_RATIONALES[strategy_id],
        })
        eligible_counts = scores[strategy_id].notna().sum(axis=1)
        row["eligible_portfolio_days"] = int(eligible_counts.ge(MIN_CROSS_SECTION).sum())
        row["minimum_eligible_count"] = int(eligible_counts.loc[eligible_counts.ge(MIN_CROSS_SECTION)].min()) if row["eligible_portfolio_days"] else 0
        row["classification"], row["classification_reason"] = classify(row)
        summaries.append(row)
        daily_parts.append(daily.assign(strategy_id=strategy_id))
        holdings_parts.append(holdings)
        trade_parts.append(trades)
        returns[strategy_id] = candidate
    fields = sorted(facts["field"].unique()) if not facts.empty else []
    coverage.update(sec_audit)
    coverage["eligible_by_financial_field"] = {field: int(facts.loc[facts["field"].eq(field), "ticker"].nunique()) for field in fields}
    coverage["final_eligible_by_strategy"] = {
        row["strategy_id"]: {"average": row["average_eligible_count"], "minimum": row["minimum_eligible_count"]}
        for row in summaries
    }
    pd.DataFrame(summaries).to_csv(output / "candidate_summary.csv", index=False)
    pd.concat(daily_parts, ignore_index=True).to_csv(output / "daily_strategy_returns.csv", index=False)
    pd.concat(holdings_parts, ignore_index=True).to_csv(output / "holdings.csv", index=False)
    pd.concat(trade_parts, ignore_index=True).to_csv(output / "trade_log.csv", index=False)
    pd.concat([download_failures.assign(stage="ohlcv_download"), sec_failures], ignore_index=True).to_csv(output / "coverage_failures.csv", index=False)
    return_panel = pd.DataFrame(returns)
    return_panel.corr().to_csv(output / "candidate_correlation_matrix.csv")
    regime_labels = _market_proxy_regime_labels(root, return_panel.index)
    regime_rows = []
    for strategy_id in return_panel:
        for regime in sorted(regime_labels.dropna().unique()):
            selected = return_panel.loc[regime_labels.eq(regime), strategy_id].dropna()
            regime_rows.append({
                "strategy_id": strategy_id, "regime_id": "MARKET_PROXY_REGIME_V0", "regime": regime,
                "observations": len(selected), "net_cumulative_return": float(selected.add(1).prod() - 1),
                "net_sharpe": float(sharpe_ratio(selected)) if len(selected) > 1 else np.nan,
                "alters_weights": False,
            })
    pd.DataFrame(regime_rows).to_csv(output / "market_proxy_regime_v0.csv", index=False)
    (output / "coverage_report.json").write_text(json.dumps(coverage, indent=2, default=str), encoding="utf-8")
    (output / "run_manifest.json").write_text(json.dumps({
        "pack_id": PACK_ID, "status": "RESEARCH_ONLY", "execution": "NEXT_OPEN_TO_OPEN",
        "buy_bps": 5, "sell_bps": 5, "labels": ["CURRENT_LISTED_DIAGNOSTIC", "SURVIVORSHIP_BIAS_PRESENT"],
        "live_allocation_approved": False, "execution_enabled": False, "fill_status": "NO LIVE FILL",
        "hard_coded_60_name_cap_removed": True, "field_requirements": FIELD_REQUIREMENTS,
    }, indent=2), encoding="utf-8")
    return {"output_root": output, "summaries": summaries, "coverage": coverage}
