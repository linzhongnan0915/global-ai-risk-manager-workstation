"""Literature-derived ETF strategy prototypes.

These are research prototypes built from boss-provided literature themes:
formulaic alpha signals, hedge fund replication, business-cycle regimes,
Markov/high-volatility regimes, and managed-futures trend following.

They are not trade recommendations. They exist so the platform can run a
repeatable research workflow: signal -> no-look-ahead weights -> costs ->
backtest -> walk-forward -> risk/action classification.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from src.risk.engine import expected_shortfall, historical_var
from src.risk.performance import max_drawdown, sharpe_ratio, volatility


BUY_BPS = 5.0
SELL_BPS = 5.0
TRADING_DAYS = 252

FACTOR_LOADINGS: dict[str, dict[str, float]] = {
    "SPY": {"equity_beta": 1.0},
    "IVV": {"equity_beta": 1.0},
    "VOO": {"equity_beta": 1.0},
    "QQQ": {"equity_beta": 1.15, "growth_style": 0.70},
    "IWM": {"equity_beta": 1.20, "small_cap": 0.80},
    "MDY": {"equity_beta": 1.05, "small_cap": 0.40},
    "EFA": {"equity_beta": 0.90, "international_equity": 0.80},
    "EEM": {"equity_beta": 1.10, "emerging_market": 1.00, "usd_fx": -0.30},
    "QUAL": {"equity_beta": 0.90, "quality_style": 0.80},
    "USMV": {"equity_beta": 0.70, "defensive_style": 0.80},
    "VLUE": {"equity_beta": 0.95, "value_style": 0.80},
    "MTUM": {"equity_beta": 1.05, "momentum_style": 0.80},
    "IVE": {"equity_beta": 0.95, "value_style": 0.90},
    "IVW": {"equity_beta": 1.05, "growth_style": 0.90},
    "XLF": {"equity_beta": 1.05, "sector_financials": 0.80},
    "XLI": {"equity_beta": 1.00, "sector_industrials": 0.80},
    "SHY": {"rates_duration": 0.20},
    "IEF": {"rates_duration": 0.65},
    "TLT": {"rates_duration": 1.20},
    "TIP": {"rates_duration": 0.45, "inflation_linked": 0.80},
    "HYG": {"credit_spread": 1.00, "equity_beta": 0.35},
    "JNK": {"credit_spread": 1.00, "equity_beta": 0.35},
    "LQD": {"credit_spread": 0.55, "rates_duration": 0.40},
    "EMB": {"credit_spread": 0.80, "emerging_market": 0.70, "usd_fx": -0.20},
    "UUP": {"usd_fx": 1.00},
    "FXE": {"usd_fx": -0.80},
    "FXY": {"usd_fx": -0.70, "safe_haven_fx": 0.50},
    "DBC": {"commodity_beta": 1.00, "inflation_beta": 0.60},
    "USO": {"commodity_beta": 1.15, "oil_beta": 1.00, "inflation_beta": 0.40},
    "GLD": {"gold": 1.00, "safe_haven": 0.60},
    "VIX": {"volatility": 1.00},
    "VXX": {"volatility": 1.20, "tail_hedge": 0.70},
    "SVXY": {"volatility": -1.00, "short_vol": 1.00},
    "MNA": {"event_driven": 0.90, "equity_beta": 0.25},
    "CWB": {"convertible": 0.90, "credit_spread": 0.35, "equity_beta": 0.40},
    "DBMF": {"managed_futures": 1.00, "trend_following": 0.90},
    "BIL": {"cash": 1.00},
}


@dataclass(frozen=True)
class StrategyPrototype:
    strategy_id: str
    name: str
    literature_source: str
    hypothesis: str
    universe: list[str]
    rebalance: str
    signal_summary: str
    failure_modes: list[str]
    builder: Callable[[pd.DataFrame], pd.DataFrame]


def load_price_returns(price_path: str | Path = "data/processed/market_price_history.csv") -> tuple[pd.DataFrame, pd.DataFrame]:
    panel = pd.read_csv(price_path)
    if panel.empty:
        raise ValueError("market price history is empty")
    panel["date"] = pd.to_datetime(panel["date"])
    prices = panel.pivot_table(index="date", columns="ticker", values="adj_close", aggfunc="last").sort_index()
    returns = prices.pct_change(fill_method=None).dropna(how="all")
    return prices, returns


def strategy_prototypes() -> list[StrategyPrototype]:
    return [
        StrategyPrototype(
            strategy_id="PROTO_WQ_ALPHA_ETF",
            name="WorldQuant-Inspired ETF Alpha Basket",
            literature_source="WorldQuant 101 Formulaic Alphas",
            hypothesis="Short-horizon price/volume signals can be combined into a low-correlation alpha basket after timing and cost controls.",
            universe=["SPY", "QQQ", "IWM", "QUAL", "VLUE", "MTUM", "USMV"],
            rebalance="weekly",
            signal_summary="Blend 20-day momentum with 5-day mean reversion across liquid style ETFs; hold top-ranked ETFs after one-day signal lag.",
            failure_modes=["alpha decay", "crowding", "turnover cost drag", "style factor reversal", "ETF proxy too coarse for stock-level WorldQuant alphas"],
            builder=weights_worldquant_inspired_alpha,
        ),
        StrategyPrototype(
            strategy_id="PROTO_HF_REPLICATION",
            name="Liquid Alternative Factor Premia Clone",
            literature_source="Hasanhodzic and Lo hedge fund replication",
            hypothesis="A transparent basket of liquid equity, bond, credit, USD, commodity, and volatility proxies can replicate part of hedge-fund-style risk premia.",
            universe=["SPY", "IEF", "HYG", "UUP", "DBC", "GLD"],
            rebalance="monthly",
            signal_summary="Equal risk-premia basket with mild defensive tilt when VIX trend rises.",
            failure_modes=["missing illiquidity premium", "factor proxy mismatch", "volatility shock", "credit stress", "clone gap versus true hedge fund returns"],
            builder=weights_liquid_alt_clone,
        ),
        StrategyPrototype(
            strategy_id="PROTO_BUSINESS_CYCLE",
            name="Business-Cycle Regime Allocation",
            literature_source="Dynamic Asset Allocation Through the Business Cycle",
            hypothesis="Risk assets perform better when growth proxies accelerate; duration and cash are more useful when growth proxies decelerate.",
            universe=["SPY", "HYG", "IEF", "BIL", "DBC", "UUP"],
            rebalance="monthly",
            signal_summary="Use SPY trend as growth proxy and DBC trend as inflation proxy to map recovery, expansion, slowdown, and contraction allocations.",
            failure_modes=["market proxy not true macro data", "regime whipsaw", "late cycle false signal", "inflation proxy mismatch"],
            builder=weights_business_cycle,
        ),
        StrategyPrototype(
            strategy_id="PROTO_MARKOV_DEFENSIVE",
            name="High-Volatility Regime Defensive Switch",
            literature_source="Ang and Bekaert Markov regime asset allocation",
            hypothesis="When high-volatility bear regime probability is elevated, reduce risky assets and shift toward cash/duration.",
            universe=["SPY", "IEF", "BIL", "HYG", "USMV"],
            rebalance="weekly",
            signal_summary="Approximate Markov high-vol regime with rolling SPY volatility, drawdown, and VIX level; switch to defensive assets when stress probability is high.",
            failure_modes=["threshold overfitting", "late de-risking", "false high-vol signal", "duration fails during inflation shock"],
            builder=weights_high_vol_defensive,
        ),
        StrategyPrototype(
            strategy_id="PROTO_MANAGED_FUTURES",
            name="Managed Futures Trend Proxy",
            literature_source="Hedge fund replication / managed futures category",
            hypothesis="Cross-asset trend following can diversify equity beta by holding assets with positive medium-term trends.",
            universe=["SPY", "TLT", "DBC", "UUP", "GLD", "DBMF"],
            rebalance="weekly",
            signal_summary="Hold assets with positive 63-day trend, equal-weighted with cash fallback.",
            failure_modes=["choppy market whipsaw", "crowded trend reversal", "commodity mean reversion", "cost drag"],
            builder=weights_managed_futures_trend,
        ),
        StrategyPrototype(
            strategy_id="CAND_EQUITY_MARKET_NEUTRAL",
            name="Equity Market-Neutral Style Spread",
            literature_source="WorldQuant alpha diversification / equity long-short style proxy",
            hypothesis="A long defensive-quality style basket versus short broad/high-beta equity basket can reduce direct equity beta.",
            universe=["QUAL", "USMV", "QQQ", "IWM", "SPY"],
            rebalance="weekly",
            signal_summary="Long quality/min-vol when defensive relative strength improves; short high-beta/growth proxies to reduce equity beta.",
            failure_modes=["short squeeze", "factor reversal", "market beta leakage", "borrow and execution assumptions missing"],
            builder=weights_equity_market_neutral,
        ),
        StrategyPrototype(
            strategy_id="CAND_CREDIT_CARRY_STRESS_GATE",
            name="Credit Carry With Stress Gate",
            literature_source="Hedge fund replication / credit risk premium",
            hypothesis="Credit carry should be earned only when credit trend and volatility conditions are supportive.",
            universe=["HYG", "LQD", "IEF", "BIL", "SPY", "VIX"],
            rebalance="weekly",
            signal_summary="Hold HYG/LQD carry when credit trend is positive and volatility stress is low; rotate to BIL/IEF during stress.",
            failure_modes=["spread widening", "liquidity shock", "default cycle", "false calm before credit stress"],
            builder=weights_credit_carry_stress_gate,
        ),
        StrategyPrototype(
            strategy_id="CAND_RATES_DURATION_REGIME",
            name="Rates Duration Regime",
            literature_source="Business cycle allocation / duration in contraction",
            hypothesis="Duration exposure is most useful when growth/risk proxies weaken, but should be reduced during inflation/rate-up regimes.",
            universe=["SHY", "IEF", "TLT", "TIP", "BIL", "SPY", "DBC"],
            rebalance="weekly",
            signal_summary="Tilt to TLT/IEF when equity trend weakens and commodity inflation pressure is not dominant; otherwise favor SHY/BIL/TIP.",
            failure_modes=["inflation shock", "bear steepening", "duration-equity correlation flip", "policy surprise"],
            builder=weights_rates_duration_regime,
        ),
        StrategyPrototype(
            strategy_id="CAND_TREASURY_CURVE_RV",
            name="Treasury Curve Relative Value Proxy",
            literature_source="Rates RV proxy / hedge fund relative value",
            hypothesis="Treasury curve relative moves can create a rates RV sleeve distinct from outright duration.",
            universe=["SHY", "IEF", "TLT", "BIL"],
            rebalance="weekly",
            signal_summary="Mean-revert relative performance between long and intermediate Treasury ETFs with cash buffer.",
            failure_modes=["curve shock", "funding stress", "ETF proxy mismatch", "mean reversion failure"],
            builder=weights_treasury_curve_rv,
        ),
        StrategyPrototype(
            strategy_id="CAND_VOL_CARRY_CRASH_FILTER",
            name="Volatility Carry With Crash Filter",
            literature_source="Hedge fund replication / volatility risk premium",
            hypothesis="Volatility carry can earn premium in calm regimes but must be shut down during volatility stress.",
            universe=["SVXY", "VXX", "BIL", "SPY", "VIX"],
            rebalance="weekly",
            signal_summary="Hold small SVXY exposure only when VIX and realized volatility are falling; move to BIL or VXX hedge during stress.",
            failure_modes=["volatility spike", "product decay", "tail loss", "vol futures curve not modeled"],
            builder=weights_vol_carry_crash_filter,
        ),
        StrategyPrototype(
            strategy_id="CAND_TAIL_HEDGE_CRISIS",
            name="Tail Hedge Crisis Sleeve",
            literature_source="Markov high-vol regime / defensive allocation",
            hypothesis="A crisis sleeve should lose small carry in calm periods but offset portfolio losses during high-volatility regimes.",
            universe=["VXX", "TLT", "GLD", "BIL", "SPY", "VIX"],
            rebalance="event-driven weekly prototype",
            signal_summary="Activate VXX/TLT/GLD when VIX, realized vol, or SPY drawdown stress rises; otherwise hold BIL.",
            failure_modes=["premium bleed", "late hedge activation", "rates/equity correlation flip", "vol product decay"],
            builder=weights_tail_hedge_crisis,
        ),
        StrategyPrototype(
            strategy_id="CAND_MERGER_ARB_PROXY",
            name="Merger Arbitrage Proxy",
            literature_source="Hedge fund replication limitation / event-driven style",
            hypothesis="Merger-arb style returns can be proxied with MNA and cash, but true deal alpha requires event data.",
            universe=["MNA", "BIL", "SPY"],
            rebalance="weekly",
            signal_summary="Hold MNA with partial SPY beta hedge when market stress is controlled; move to BIL during risk-off.",
            failure_modes=["deal break", "event data missing", "liquidity gap", "market stress beta"],
            builder=weights_merger_arb_proxy,
        ),
        StrategyPrototype(
            strategy_id="CAND_CONVERTIBLE_ARB_PROXY",
            name="Convertible Arbitrage Proxy",
            literature_source="Hedge fund replication / convertible arbitrage style",
            hypothesis="Convertible arbitrage can be approximated as a mix of convertible, credit, equity, and duration exposures.",
            universe=["CWB", "HYG", "IEF", "SPY", "BIL"],
            rebalance="weekly",
            signal_summary="Hold CWB with credit/rates support when credit is stable; de-risk to BIL/IEF under credit stress.",
            failure_modes=["credit spread widening", "equity vol shock", "liquidity stress", "convertible optionality not modeled"],
            builder=weights_convertible_arb_proxy,
        ),
        StrategyPrototype(
            strategy_id="CAND_COMMODITY_INFLATION_SHOCK",
            name="Commodity Inflation Shock Sleeve",
            literature_source="Business cycle / inflation regime allocation",
            hypothesis="Commodity and gold exposures can hedge inflation and supply shock regimes distinct from equity beta.",
            universe=["DBC", "USO", "GLD", "UUP", "BIL"],
            rebalance="weekly",
            signal_summary="Hold commodity assets with positive trend and inflation pressure; use BIL fallback when trend is weak.",
            failure_modes=["roll drag", "supply reversal", "USD squeeze", "commodity mean reversion"],
            builder=weights_commodity_inflation_shock,
        ),
        StrategyPrototype(
            strategy_id="CAND_USD_MACRO_PRESSURE",
            name="USD Macro Pressure Sleeve",
            literature_source="JPM regime / macro pressure",
            hypothesis="USD strength is a macro stress and liquidity factor that can diversify equity and credit exposures.",
            universe=["UUP", "FXE", "FXY", "GLD", "BIL"],
            rebalance="weekly",
            signal_summary="Hold UUP/FXY/GLD during USD or risk-off pressure; otherwise remain in BIL.",
            failure_modes=["central bank surprise", "FX ETF proxy mismatch", "carry unwind", "policy shock"],
            builder=weights_usd_macro_pressure,
        ),
        StrategyPrototype(
            strategy_id="CAND_EM_MACRO_RISK",
            name="Emerging Markets Macro Risk Sleeve",
            literature_source="Regime investing / EM replication limitation",
            hypothesis="EM risk premia should be held only when USD pressure is low and global risk appetite is supportive.",
            universe=["EEM", "EMB", "UUP", "GLD", "BIL", "SPY"],
            rebalance="weekly",
            signal_summary="Hold EEM/EMB when SPY trend is positive and UUP trend is weak; rotate to BIL/GLD under USD stress.",
            failure_modes=["USD spike", "liquidity stress", "geopolitical shock", "country-specific risk missing"],
            builder=weights_em_macro_risk,
        ),
        StrategyPrototype(
            strategy_id="CAND_RISK_PARITY_OVERLAY",
            name="Risk Parity ETF Overlay",
            literature_source="Regime allocation / portfolio stabilizer",
            hypothesis="Volatility-balanced cross-asset exposure can stabilize portfolio risk better than equal weights.",
            universe=["SPY", "TLT", "GLD", "DBC", "BIL"],
            rebalance="monthly",
            signal_summary="Allocate by inverse 63-day volatility across equity, duration, gold, commodities, and cash.",
            failure_modes=["correlation breakdown", "leverage assumptions missing", "rates/equity selloff", "volatility targeting lag"],
            builder=weights_risk_parity_overlay,
        ),
        StrategyPrototype(
            strategy_id="CAND_GLOBAL_VALUE_ROTATION",
            name="Global Value Rotation",
            literature_source="Business cycle / global style allocation",
            hypothesis="Value, growth, developed ex-US, and EM equities respond differently across cycles and USD regimes.",
            universe=["IVE", "IVW", "EFA", "EEM", "UUP", "BIL"],
            rebalance="monthly",
            signal_summary="Rank global/style ETFs by risk-adjusted trend, penalizing EM when USD pressure rises.",
            failure_modes=["currency drag", "regional policy shock", "value trap", "global equity beta concentration"],
            builder=weights_global_value_rotation,
        ),
        StrategyPrototype(
            strategy_id="CAND_INDEX_ARBITRAGE_PROXY",
            name="Index Arbitrage Proxy",
            literature_source="ETF relative value / implementation discipline",
            hypothesis="S&P 500 ETF tracking spreads are usually tiny, so this tests whether edge survives cost.",
            universe=["SPY", "IVV", "VOO", "BIL"],
            rebalance="daily research",
            signal_summary="Mean-revert short-horizon relative performance among SPY, IVV, and VOO with dollar-neutral ETF spread.",
            failure_modes=["edge consumed by costs", "execution timing mismatch", "intraday data required", "tracking spread too small"],
            builder=weights_index_arbitrage_proxy,
        ),
        StrategyPrototype(
            strategy_id="CAND_EVENT_DRIVEN_SECTOR_PROXY",
            name="Event-Driven Sector Risk Proxy",
            literature_source="Event-driven replication limitation",
            hypothesis="Sector-event sleeves can be monitored with ETFs, but true event alpha requires news and deal data.",
            universe=["XLF", "XLI", "MNA", "BIL", "SPY"],
            rebalance="weekly",
            signal_summary="Hold sector/event proxies when sector trend is positive and market stress is low; otherwise BIL.",
            failure_modes=["event data lag", "deal concentration", "sector beta", "risk-off correlation spike"],
            builder=weights_event_driven_sector_proxy,
        ),
    ]


def weights_worldquant_inspired_alpha(returns: pd.DataFrame) -> pd.DataFrame:
    tickers = ["SPY", "QQQ", "IWM", "QUAL", "VLUE", "MTUM", "USMV"]
    available = [ticker for ticker in tickers if ticker in returns.columns]
    mom = returns[available].rolling(20).sum()
    reversal = -returns[available].rolling(5).sum()
    score = 0.55 * mom.rank(axis=1, pct=True) + 0.45 * reversal.rank(axis=1, pct=True)
    return _top_n_weights(score, n=3, rebalance_every=5)


def weights_liquid_alt_clone(returns: pd.DataFrame) -> pd.DataFrame:
    risky = [ticker for ticker in ["SPY", "IEF", "HYG", "UUP", "DBC", "GLD"] if ticker in returns.columns]
    weights = pd.DataFrame(0.0, index=returns.index, columns=returns.columns)
    if not risky:
        return weights
    base = pd.Series(1 / len(risky), index=risky)
    vix_stress = _vix_stress_score(returns)
    for date in returns.index:
        w = base.copy()
        if vix_stress.loc[date] > 0.6:
            for ticker in ["SPY", "HYG", "DBC"]:
                if ticker in w:
                    w[ticker] *= 0.55
            for ticker in ["IEF", "GLD", "UUP"]:
                if ticker in w:
                    w[ticker] *= 1.35
        w = w / w.sum()
        weights.loc[date, w.index] = w
    return _rebalance_only(weights, every=21)


def weights_business_cycle(returns: pd.DataFrame) -> pd.DataFrame:
    weights = pd.DataFrame(0.0, index=returns.index, columns=returns.columns)
    growth = returns["SPY"].rolling(63).sum() if "SPY" in returns else pd.Series(0, index=returns.index)
    growth_change = growth.diff(21)
    inflation = returns["DBC"].rolling(63).sum() if "DBC" in returns else pd.Series(0, index=returns.index)
    for date in returns.index:
        g = growth.loc[date]
        dg = growth_change.loc[date]
        inf = inflation.loc[date]
        if pd.isna(g) or pd.isna(dg):
            alloc = {"SPY": 0.35, "HYG": 0.20, "IEF": 0.25, "BIL": 0.10, "DBC": 0.05, "UUP": 0.05}
        elif g <= 0 and dg > 0:
            alloc = {"SPY": 0.35, "HYG": 0.30, "IEF": 0.20, "BIL": 0.05, "DBC": 0.05, "UUP": 0.05}
        elif g > 0 and dg > 0:
            alloc = {"SPY": 0.50, "HYG": 0.20, "IEF": 0.10, "BIL": 0.05, "DBC": 0.10 if inf > 0 else 0.05, "UUP": 0.05}
        elif g > 0 and dg <= 0:
            alloc = {"SPY": 0.25, "HYG": 0.15, "IEF": 0.25, "BIL": 0.20, "DBC": 0.05, "UUP": 0.10}
        else:
            alloc = {"SPY": 0.10, "HYG": 0.05, "IEF": 0.45, "BIL": 0.25, "DBC": 0.05, "UUP": 0.10}
        for ticker, value in alloc.items():
            if ticker in weights.columns:
                weights.loc[date, ticker] = value
        row_sum = weights.loc[date].sum()
        if row_sum:
            weights.loc[date] = weights.loc[date] / row_sum
    return _rebalance_only(weights, every=21)


def weights_high_vol_defensive(returns: pd.DataFrame) -> pd.DataFrame:
    weights = pd.DataFrame(0.0, index=returns.index, columns=returns.columns)
    spy_vol = returns["SPY"].rolling(21).std() * np.sqrt(TRADING_DAYS) if "SPY" in returns else pd.Series(0, index=returns.index)
    spy_dd = _drawdown_from_returns(returns["SPY"]) if "SPY" in returns else pd.Series(0, index=returns.index)
    vix = _vix_level_proxy(returns)
    vol_rank = spy_vol.rolling(252).rank(pct=True)
    dd_stress = (spy_dd < -0.08).astype(float)
    vix_stress = (vix > 25).astype(float)
    stress = (0.5 * vol_rank.fillna(0.5) + 0.25 * dd_stress + 0.25 * vix_stress).clip(0, 1)
    for date in returns.index:
        if stress.loc[date] > 0.65:
            alloc = {"SPY": 0.10, "HYG": 0.05, "USMV": 0.15, "IEF": 0.45, "BIL": 0.25}
        elif stress.loc[date] > 0.45:
            alloc = {"SPY": 0.25, "HYG": 0.10, "USMV": 0.25, "IEF": 0.30, "BIL": 0.10}
        else:
            alloc = {"SPY": 0.45, "HYG": 0.20, "USMV": 0.20, "IEF": 0.10, "BIL": 0.05}
        for ticker, value in alloc.items():
            if ticker in weights.columns:
                weights.loc[date, ticker] = value
        row_sum = weights.loc[date].sum()
        if row_sum:
            weights.loc[date] = weights.loc[date] / row_sum
    return _rebalance_only(weights, every=5)


def weights_managed_futures_trend(returns: pd.DataFrame) -> pd.DataFrame:
    tickers = [ticker for ticker in ["SPY", "TLT", "DBC", "UUP", "GLD", "DBMF"] if ticker in returns.columns]
    trend = returns[tickers].rolling(63).sum()
    positive = trend > 0
    weights = pd.DataFrame(0.0, index=returns.index, columns=returns.columns)
    for date in returns.index:
        chosen = [ticker for ticker in tickers if bool(positive.loc[date, ticker])]
        if not chosen:
            if "BIL" in weights.columns:
                weights.loc[date, "BIL"] = 1.0
            continue
        for ticker in chosen:
            weights.loc[date, ticker] = 1 / len(chosen)
    return _rebalance_only(weights, every=5)


def weights_style_rotation(returns: pd.DataFrame) -> pd.DataFrame:
    tickers = [ticker for ticker in ["QUAL", "VLUE", "MTUM", "USMV", "SPY"] if ticker in returns.columns]
    trend = returns[tickers].rolling(126).sum()
    vol_penalty = returns[tickers].rolling(63).std()
    score = trend.rank(axis=1, pct=True) - vol_penalty.rank(axis=1, pct=True) * 0.35
    return _top_n_weights(score, n=2, rebalance_every=5)


def weights_equity_market_neutral(returns: pd.DataFrame) -> pd.DataFrame:
    weights = pd.DataFrame(0.0, index=returns.index, columns=returns.columns)
    longs = [ticker for ticker in ["QUAL", "USMV"] if ticker in returns.columns]
    shorts = [ticker for ticker in ["QQQ", "IWM", "SPY"] if ticker in returns.columns]
    if not longs or not shorts:
        return weights
    defensive_score = returns[longs].mean(axis=1).rolling(63).sum() - returns[shorts].mean(axis=1).rolling(63).sum()
    for date in returns.index:
        scale = 1.0 if defensive_score.loc[date] > 0 else 0.55
        for ticker in longs:
            weights.loc[date, ticker] = 0.5 * scale / len(longs)
        for ticker in shorts:
            weights.loc[date, ticker] = -0.5 * scale / len(shorts)
        if "BIL" in weights.columns:
            weights.loc[date, "BIL"] = 1.0 - weights.loc[date].abs().sum()
    return _rebalance_only(weights, every=5)


def weights_credit_carry_stress_gate(returns: pd.DataFrame) -> pd.DataFrame:
    weights = pd.DataFrame(0.0, index=returns.index, columns=returns.columns)
    credit = returns["HYG"].rolling(63).sum() if "HYG" in returns else pd.Series(-1, index=returns.index)
    stress = _vix_stress_score(returns)
    for date in returns.index:
        if credit.loc[date] > 0 and stress.loc[date] < 0.45:
            alloc = {"HYG": 0.45, "LQD": 0.30, "IEF": 0.15, "BIL": 0.10}
        elif stress.loc[date] > 0.65:
            alloc = {"BIL": 0.55, "IEF": 0.35, "LQD": 0.10}
        else:
            alloc = {"LQD": 0.35, "BIL": 0.35, "IEF": 0.30}
        _assign_alloc(weights, date, alloc)
    return _rebalance_only(weights, every=5)


def weights_rates_duration_regime(returns: pd.DataFrame) -> pd.DataFrame:
    weights = pd.DataFrame(0.0, index=returns.index, columns=returns.columns)
    equity_trend = returns["SPY"].rolling(63).sum() if "SPY" in returns else pd.Series(0, index=returns.index)
    inflation_trend = returns["DBC"].rolling(63).sum() if "DBC" in returns else pd.Series(0, index=returns.index)
    for date in returns.index:
        if equity_trend.loc[date] < 0 and inflation_trend.loc[date] <= 0:
            alloc = {"TLT": 0.45, "IEF": 0.35, "BIL": 0.20}
        elif inflation_trend.loc[date] > 0:
            alloc = {"TIP": 0.35, "SHY": 0.35, "BIL": 0.30}
        else:
            alloc = {"IEF": 0.40, "SHY": 0.35, "BIL": 0.25}
        _assign_alloc(weights, date, alloc)
    return _rebalance_only(weights, every=5)


def weights_treasury_curve_rv(returns: pd.DataFrame) -> pd.DataFrame:
    weights = pd.DataFrame(0.0, index=returns.index, columns=returns.columns)
    if not {"TLT", "IEF"}.issubset(returns.columns):
        return weights
    spread = (returns["TLT"] - returns["IEF"]).rolling(21).sum()
    z = _zscore(spread, 126)
    for date in returns.index:
        if z.loc[date] > 1:
            alloc = {"TLT": -0.45, "IEF": 0.45, "BIL": 0.10}
        elif z.loc[date] < -1:
            alloc = {"TLT": 0.45, "IEF": -0.45, "BIL": 0.10}
        else:
            alloc = {"BIL": 1.0}
        _assign_alloc(weights, date, alloc)
    return _rebalance_only(weights, every=5)


def weights_vol_carry_crash_filter(returns: pd.DataFrame) -> pd.DataFrame:
    weights = pd.DataFrame(0.0, index=returns.index, columns=returns.columns)
    vix = _vix_level_proxy(returns)
    spy_trend = returns["SPY"].rolling(63).sum() if "SPY" in returns else pd.Series(0, index=returns.index)
    vix_trend = vix.pct_change(21).fillna(0)
    for date in returns.index:
        if vix.loc[date] < 22 and vix_trend.loc[date] < 0 and spy_trend.loc[date] > 0:
            alloc = {"SVXY": 0.30, "BIL": 0.70}
        elif vix.loc[date] > 28:
            alloc = {"VXX": 0.15, "BIL": 0.85}
        else:
            alloc = {"BIL": 1.0}
        _assign_alloc(weights, date, alloc)
    return _rebalance_only(weights, every=5)


def weights_tail_hedge_crisis(returns: pd.DataFrame) -> pd.DataFrame:
    weights = pd.DataFrame(0.0, index=returns.index, columns=returns.columns)
    stress = _vix_stress_score(returns)
    spy_dd = _drawdown_from_returns(returns["SPY"]) if "SPY" in returns else pd.Series(0, index=returns.index)
    for date in returns.index:
        if stress.loc[date] > 0.65 or spy_dd.loc[date] < -0.08:
            alloc = {"VXX": 0.20, "TLT": 0.30, "GLD": 0.25, "BIL": 0.25}
        elif stress.loc[date] > 0.40:
            alloc = {"TLT": 0.35, "GLD": 0.25, "BIL": 0.40}
        else:
            alloc = {"BIL": 0.95, "GLD": 0.05}
        _assign_alloc(weights, date, alloc)
    return _rebalance_only(weights, every=5)


def weights_merger_arb_proxy(returns: pd.DataFrame) -> pd.DataFrame:
    weights = pd.DataFrame(0.0, index=returns.index, columns=returns.columns)
    stress = _vix_stress_score(returns)
    for date in returns.index:
        if stress.loc[date] < 0.50:
            alloc = {"MNA": 0.80, "SPY": -0.15, "BIL": 0.05}
        else:
            alloc = {"MNA": 0.30, "BIL": 0.70}
        _assign_alloc(weights, date, alloc)
    return _rebalance_only(weights, every=5)


def weights_convertible_arb_proxy(returns: pd.DataFrame) -> pd.DataFrame:
    weights = pd.DataFrame(0.0, index=returns.index, columns=returns.columns)
    credit = returns["HYG"].rolling(63).sum() if "HYG" in returns else pd.Series(0, index=returns.index)
    for date in returns.index:
        if credit.loc[date] > 0:
            alloc = {"CWB": 0.55, "HYG": 0.20, "IEF": 0.15, "SPY": -0.10, "BIL": 0.20}
        else:
            alloc = {"CWB": 0.25, "IEF": 0.35, "BIL": 0.40}
        _assign_alloc(weights, date, alloc)
    return _rebalance_only(weights, every=5)


def weights_commodity_inflation_shock(returns: pd.DataFrame) -> pd.DataFrame:
    tickers = [ticker for ticker in ["DBC", "USO", "GLD", "UUP"] if ticker in returns.columns]
    trend = returns[tickers].rolling(63).sum()
    weights = pd.DataFrame(0.0, index=returns.index, columns=returns.columns)
    for date in returns.index:
        chosen = [ticker for ticker in tickers if trend.loc[date, ticker] > 0]
        if chosen:
            for ticker in chosen:
                weights.loc[date, ticker] = 0.85 / len(chosen)
            if "BIL" in weights.columns:
                weights.loc[date, "BIL"] = 0.15
        elif "BIL" in weights.columns:
            weights.loc[date, "BIL"] = 1.0
    return _rebalance_only(weights, every=5)


def weights_usd_macro_pressure(returns: pd.DataFrame) -> pd.DataFrame:
    weights = pd.DataFrame(0.0, index=returns.index, columns=returns.columns)
    uup_trend = returns["UUP"].rolling(63).sum() if "UUP" in returns else pd.Series(0, index=returns.index)
    risk_off = returns["SPY"].rolling(63).sum() < 0 if "SPY" in returns else pd.Series(False, index=returns.index)
    for date in returns.index:
        if uup_trend.loc[date] > 0 or risk_off.loc[date]:
            alloc = {"UUP": 0.45, "FXY": 0.20, "GLD": 0.20, "BIL": 0.15}
        else:
            alloc = {"BIL": 0.70, "FXE": 0.15, "GLD": 0.15}
        _assign_alloc(weights, date, alloc)
    return _rebalance_only(weights, every=5)


def weights_em_macro_risk(returns: pd.DataFrame) -> pd.DataFrame:
    weights = pd.DataFrame(0.0, index=returns.index, columns=returns.columns)
    spy_trend = returns["SPY"].rolling(63).sum() if "SPY" in returns else pd.Series(0, index=returns.index)
    usd_trend = returns["UUP"].rolling(63).sum() if "UUP" in returns else pd.Series(0, index=returns.index)
    for date in returns.index:
        if spy_trend.loc[date] > 0 and usd_trend.loc[date] <= 0:
            alloc = {"EEM": 0.45, "EMB": 0.30, "GLD": 0.10, "BIL": 0.15}
        elif usd_trend.loc[date] > 0:
            alloc = {"BIL": 0.60, "GLD": 0.25, "EMB": 0.15}
        else:
            alloc = {"EMB": 0.35, "BIL": 0.45, "GLD": 0.20}
        _assign_alloc(weights, date, alloc)
    return _rebalance_only(weights, every=5)


def weights_risk_parity_overlay(returns: pd.DataFrame) -> pd.DataFrame:
    tickers = [ticker for ticker in ["SPY", "TLT", "GLD", "DBC", "BIL"] if ticker in returns.columns]
    vol = returns[tickers].rolling(63).std()
    inv_vol = 1 / vol.replace(0, np.nan)
    raw = inv_vol.div(inv_vol.sum(axis=1), axis=0).fillna(0.0)
    weights = pd.DataFrame(0.0, index=returns.index, columns=returns.columns)
    for ticker in tickers:
        weights[ticker] = raw[ticker]
    return _rebalance_only(weights, every=21)


def weights_global_value_rotation(returns: pd.DataFrame) -> pd.DataFrame:
    tickers = [ticker for ticker in ["IVE", "IVW", "EFA", "EEM"] if ticker in returns.columns]
    score = returns[tickers].rolling(126).sum().rank(axis=1, pct=True)
    if "UUP" in returns and "EEM" in score:
        usd_pressure = returns["UUP"].rolling(63).sum() > 0
        score.loc[usd_pressure, "EEM"] *= 0.5
    return _top_n_weights(score, n=2, rebalance_every=21)


def weights_index_arbitrage_proxy(returns: pd.DataFrame) -> pd.DataFrame:
    tickers = [ticker for ticker in ["SPY", "IVV", "VOO"] if ticker in returns.columns]
    weights = pd.DataFrame(0.0, index=returns.index, columns=returns.columns)
    if len(tickers) < 2:
        return weights
    short_term = returns[tickers].rolling(5).sum()
    for date in returns.index:
        row = short_term.loc[date].dropna()
        if len(row) < 2:
            continue
        long_ticker = row.idxmin()
        short_ticker = row.idxmax()
        weights.loc[date, long_ticker] = 0.50
        weights.loc[date, short_ticker] = -0.50
        if "BIL" in weights.columns:
            weights.loc[date, "BIL"] = 0.0
    return _rebalance_only(weights, every=1)


def weights_event_driven_sector_proxy(returns: pd.DataFrame) -> pd.DataFrame:
    weights = pd.DataFrame(0.0, index=returns.index, columns=returns.columns)
    sector_trend = returns[[ticker for ticker in ["XLF", "XLI"] if ticker in returns.columns]].rolling(63).sum()
    stress = _vix_stress_score(returns)
    for date in returns.index:
        if stress.loc[date] < 0.50 and not sector_trend.empty:
            chosen = sector_trend.loc[date].dropna()
            best = chosen.idxmax() if not chosen.empty else "MNA"
            alloc = {best: 0.40, "MNA": 0.35, "SPY": -0.10, "BIL": 0.35}
        else:
            alloc = {"MNA": 0.25, "BIL": 0.75}
        _assign_alloc(weights, date, alloc)
    return _rebalance_only(weights, every=5)


def run_strategy_backtest(strategy: StrategyPrototype, returns: pd.DataFrame) -> dict:
    weights = strategy.builder(returns).reindex(index=returns.index, columns=returns.columns).fillna(0.0)
    # One-day execution lag: today's signal weights are applied to tomorrow's returns.
    shifted = weights.shift(1).fillna(0.0)
    gross = (shifted * returns).sum(axis=1, min_count=1)
    turnover = shifted.diff().abs().sum(axis=1).fillna(shifted.abs().sum(axis=1))
    cost = turnover * (BUY_BPS + SELL_BPS) / 2 / 10_000
    net = gross - cost
    active_index = _active_strategy_index(shifted)
    if active_index.empty:
        return _missing_strategy_backtest(strategy, returns.index)
    gross = gross.loc[active_index]
    turnover = turnover.loc[active_index]
    cost = cost.loc[active_index]
    net = net.loc[active_index]
    shifted = shifted.loc[active_index]
    benchmark = returns["SPY"].reindex(net.index).fillna(0.0) if "SPY" in returns.columns else pd.Series(0.0, index=net.index)
    aligned_market_returns = returns.reindex(net.index)
    return {
        "strategy_id": strategy.strategy_id,
        "name": strategy.name,
        "literature_source": strategy.literature_source,
        "hypothesis": strategy.hypothesis,
        "universe": strategy.universe,
        "rebalance": strategy.rebalance,
        "signal_summary": strategy.signal_summary,
        "failure_modes": strategy.failure_modes,
        "observations": int(net.dropna().shape[0]),
        "backtest_evidence": _backtest_evidence(net),
        "gross_metrics": _summary_metrics(gross),
        "net_metrics": _summary_metrics(net),
        "risk_packet": _risk_packet(net, benchmark, turnover, aligned_market_returns),
        "position_packet": _position_packet(shifted, weights.loc[active_index], turnover, cost),
        "factor_exposure": _factor_exposure_packet(shifted),
        "return_series": {
            "dates": [idx.date().isoformat() for idx in net.index],
            "gross_returns": [float(value) for value in gross.reindex(net.index)],
            "net_returns": [float(value) for value in net],
        },
        "turnover": {
            "average_daily_turnover": float(turnover.mean()),
            "annualized_turnover": float(turnover.mean() * TRADING_DAYS),
            "total_cost_drag": float(cost.sum()),
            "annualized_cost_drag": float(cost.mean() * TRADING_DAYS),
        },
        "action": _action_recommendation(net, turnover),
    }


def run_walk_forward(strategy: StrategyPrototype, returns: pd.DataFrame, train_days: int = 504, test_days: int = 126) -> dict:
    weights = strategy.builder(returns).reindex(index=returns.index, columns=returns.columns).fillna(0.0)
    shifted = weights.shift(1).fillna(0.0)
    gross = (shifted * returns).sum(axis=1, min_count=1)
    turnover = shifted.diff().abs().sum(axis=1).fillna(shifted.abs().sum(axis=1))
    net = gross - turnover * (BUY_BPS + SELL_BPS) / 2 / 10_000
    active_index = _active_strategy_index(shifted)
    if active_index.empty:
        return {
            "windows": [],
            "train_days": train_days,
            "test_days": test_days,
            "number_of_windows": 0,
            "positive_window_rate": 0.0,
            "average_test_sharpe": 0.0,
            "status": "missing_data",
        }
    net = net.loc[active_index]
    windows = []
    start = 0
    while start + train_days + test_days <= len(net):
        train = net.iloc[start : start + train_days]
        test = net.iloc[start + train_days : start + train_days + test_days]
        windows.append(
            {
                "train_start": train.index[0].date().isoformat(),
                "train_end": train.index[-1].date().isoformat(),
                "test_start": test.index[0].date().isoformat(),
                "test_end": test.index[-1].date().isoformat(),
                "train_sharpe": sharpe_ratio(train.tolist()),
                "test_sharpe": sharpe_ratio(test.tolist()),
                "test_return": _compound_return(test),
                "test_max_drawdown": max_drawdown(test.tolist()),
            }
        )
        start += test_days
    if not windows:
        return {
            "windows": [],
            "train_days": train_days,
            "test_days": test_days,
            "number_of_windows": 0,
            "positive_window_rate": 0.0,
            "average_test_sharpe": 0.0,
            "status": "insufficient_history",
        }
    return {
        "windows": windows,
        "train_days": train_days,
        "test_days": test_days,
        "number_of_windows": len(windows),
        "in_sample_start": windows[0]["train_start"],
        "in_sample_end": windows[0]["train_end"],
        "first_oos_start": windows[0]["test_start"],
        "last_oos_end": windows[-1]["test_end"],
        "positive_window_rate": float(np.mean([w["test_return"] > 0 for w in windows])),
        "average_test_sharpe": float(np.mean([w["test_sharpe"] for w in windows])),
        "status": "complete",
    }


def run_all_literature_backtests(price_path: str | Path = "data/processed/market_price_history.csv") -> dict:
    _, returns = load_price_returns(price_path)
    prototypes = strategy_prototypes()
    results = []
    for strategy in prototypes:
        results.append(
            {
                "backtest": run_strategy_backtest(strategy, returns),
                "walk_forward": run_walk_forward(strategy, returns),
            }
        )
    _attach_cross_strategy_comparison(results)
    return {
        "source": "yfinance_etf_proxy_research",
        "price_path": str(price_path),
        "as_of": returns.index.max().date().isoformat(),
        "cost_assumption": "5 bps buy and 5 bps sell; turnover-based daily rebalance cost",
        "no_lookahead": "Weights are shifted by one trading day before applying returns.",
        "bias_controls": {
            "lookahead_bias": "One-day signal execution lag is applied before returns.",
            "survivorship_bias": "ETF proxy universe uses currently listed ETFs; this is disclosed and not a survivorship-free single-stock universe.",
            "data_snooping": "Prototype signals are literature-driven, but parameter choices still require future grid/WFO validation.",
            "transaction_cost": "5 bps buy and 5 bps sell are included through turnover cost.",
        },
        "results": results,
    }


def _attach_cross_strategy_comparison(results: list[dict]) -> None:
    series = {}
    names = {}
    for item in results:
        backtest = item["backtest"]
        dates = backtest["return_series"]["dates"]
        values = backtest["return_series"]["net_returns"]
        if not dates:
            continue
        series[backtest["strategy_id"]] = pd.Series(values, index=pd.to_datetime(dates))
        names[backtest["strategy_id"]] = backtest["name"]
    if not series:
        return
    frame = pd.DataFrame(series).dropna(how="all").fillna(0.0)
    corr = frame.corr().fillna(0.0)
    for item in results:
        strategy_id = item["backtest"]["strategy_id"]
        if strategy_id not in corr.columns:
            item["backtest"]["risk_packet"]["comparison_vs_other_strategies"] = {
                "top_correlations": [],
                "average_abs_correlation_to_others": 0.0,
                "status": "missing_data",
                "interpretation": "Not enough overlapping return history to compare this strategy against the current peer set.",
            }
            continue
        row = corr[strategy_id].drop(labels=[strategy_id], errors="ignore").sort_values(key=lambda values: values.abs(), ascending=False)
        top = [
            {
                "strategy_id": other_id,
                "name": names.get(other_id, other_id),
                "correlation": float(value),
                "interpretation": "high duplicate-exposure risk" if abs(value) >= 0.75 else "watch overlap" if abs(value) >= 0.45 else "low overlap",
            }
            for other_id, value in row.head(5).items()
        ]
        item["backtest"]["risk_packet"]["comparison_vs_other_strategies"] = {
            "top_correlations": top,
            "average_abs_correlation_to_others": float(row.abs().mean()) if len(row) else 0.0,
        }


def _position_packet(executed_weights: pd.DataFrame, signal_weights: pd.DataFrame, turnover: pd.Series, cost: pd.Series) -> dict:
    latest_executed = executed_weights.iloc[-1] if len(executed_weights) else pd.Series(dtype=float)
    latest_signal = signal_weights.iloc[-1] if len(signal_weights) else pd.Series(dtype=float)
    history = []
    for idx, row in executed_weights.tail(252).iterrows():
        positions = _compact_weight_row(row)
        history.append(
            {
                "date": idx.date().isoformat(),
                "gross_exposure": float(row.abs().sum()),
                "net_exposure": float(row.sum()),
                "positions": positions,
            }
        )
    signal_history = []
    for idx, row in signal_weights.tail(252).iterrows():
        signal_history.append({"date": idx.date().isoformat(), "signal_weights": _compact_weight_row(row)})
    return {
        "latest_positions": _compact_weight_row(latest_executed),
        "latest_signal_weights": _compact_weight_row(latest_signal),
        "latest_gross_exposure": float(latest_executed.abs().sum()) if len(latest_executed) else 0.0,
        "latest_net_exposure": float(latest_executed.sum()) if len(latest_executed) else 0.0,
        "average_gross_exposure": float(executed_weights.abs().sum(axis=1).mean()) if len(executed_weights) else 0.0,
        "average_net_exposure": float(executed_weights.sum(axis=1).mean()) if len(executed_weights) else 0.0,
        "average_abs_exposure_by_ticker": _compact_weight_row(executed_weights.abs().mean(axis=0)) if len(executed_weights) else [],
        "position_history": history,
        "signal_history": signal_history,
        "turnover_history": [
            {"date": idx.date().isoformat(), "turnover": float(value)}
            for idx, value in turnover.tail(252).items()
        ],
        "transaction_cost_history": [
            {"date": idx.date().isoformat(), "cost_return_drag": float(value)}
            for idx, value in cost.tail(252).items()
        ],
    }


def _compact_weight_row(row: pd.Series, threshold: float = 1e-6) -> list[dict[str, float | str]]:
    if row.empty:
        return []
    active = row[abs(row) > threshold].sort_values(key=lambda values: values.abs(), ascending=False)
    return [{"ticker": str(ticker), "weight": float(weight)} for ticker, weight in active.items()]


def _factor_exposure_packet(executed_weights: pd.DataFrame) -> dict:
    if executed_weights.empty:
        return {
            "method": "ETF proxy loading map",
            "latest": {},
            "average": {},
            "concentration": {"top_factor": None, "top_abs_exposure": 0.0, "herfindahl_abs_exposure": 0.0},
        }
    latest = _factor_exposures_for_row(executed_weights.iloc[-1])
    average = _factor_exposures_for_row(executed_weights.mean(axis=0))
    abs_total = sum(abs(value) for value in latest.values())
    herfindahl = sum((abs(value) / abs_total) ** 2 for value in latest.values()) if abs_total else 0.0
    top_factor = max(latest, key=lambda key: abs(latest[key])) if latest else None
    return {
        "method": "Transparent ETF proxy loading map, not a licensed Barra model.",
        "latest": latest,
        "average": average,
        "concentration": {
            "top_factor": top_factor,
            "top_abs_exposure": float(abs(latest[top_factor])) if top_factor else 0.0,
            "herfindahl_abs_exposure": float(herfindahl),
        },
        "interpretation": "Positive and negative values are signed proxy exposures from ETF weights. Use this as a prototype factor-risk view until a licensed factor model or boss API is available.",
    }


def _factor_exposures_for_row(row: pd.Series) -> dict[str, float]:
    exposures: dict[str, float] = {}
    for ticker, weight in row.items():
        loading = FACTOR_LOADINGS.get(str(ticker), {})
        for factor, beta in loading.items():
            exposures[factor] = exposures.get(factor, 0.0) + float(weight) * float(beta)
    return {key: float(value) for key, value in sorted(exposures.items()) if abs(value) > 1e-8}


def _missing_strategy_backtest(strategy: StrategyPrototype, index: pd.Index) -> dict:
    return {
        "strategy_id": strategy.strategy_id,
        "name": strategy.name,
        "literature_source": strategy.literature_source,
        "hypothesis": strategy.hypothesis,
        "universe": strategy.universe,
        "rebalance": strategy.rebalance,
        "signal_summary": strategy.signal_summary,
        "failure_modes": strategy.failure_modes,
        "observations": 0,
        "backtest_evidence": {
            "status": "missing_data",
            "start_date": None,
            "end_date": None,
            "observations": 0,
            "years": 0.0,
            "transaction_cost_included": True,
            "lookahead_bias_check": "not evaluated because required data is unavailable",
            "data_source": "yfinance ETF proxy panel",
        },
        "gross_metrics": {},
        "net_metrics": {},
        "risk_packet": _empty_risk_packet("Required ETF data is unavailable for this strategy in the current price panel."),
        "position_packet": {
            "latest_positions": [],
            "latest_signal_weights": [],
            "position_history": [],
            "signal_history": [],
            "turnover_history": [],
            "transaction_cost_history": [],
        },
        "factor_exposure": {
            "method": "ETF proxy loading map",
            "latest": {},
            "average": {},
            "concentration": {"top_factor": None, "top_abs_exposure": 0.0, "herfindahl_abs_exposure": 0.0},
        },
        "return_series": {"dates": [], "net_returns": []},
        "turnover": {
            "average_daily_turnover": 0.0,
            "annualized_turnover": 0.0,
            "total_cost_drag": 0.0,
            "annualized_cost_drag": 0.0,
        },
        "action": {"action": "Research Hold", "reason_code": "missing_data", "interpretation": "Required ETF data is unavailable."},
    }


def _empty_risk_packet(reason: str) -> dict:
    return {
        "summary_statistics": {"status": "missing_data", "reason": reason},
        "distribution_shape": {"status": "missing_data", "reason": reason},
        "tail_risk": {"status": "missing_data", "reason": reason},
        "drawdown_behavior": {"status": "missing_data", "reason": reason},
        "time_stability": {"status": "missing_data", "reason": reason},
        "regime_breakdown": {"status": "missing_data", "reason": reason},
        "comparison_vs_benchmark": {"status": "missing_data", "reason": reason},
        "chart_series": {"dates": [], "returns": [], "cumulative_return": [], "drawdown": [], "rolling_63d_sharpe": []},
        "comparison_vs_other_strategies": {"top_correlations": [], "average_abs_correlation_to_others": 0.0},
    }


def _active_strategy_index(weights: pd.DataFrame) -> pd.Index:
    active = weights.abs().sum(axis=1) > 1e-10
    if not active.any():
        return weights.index[:0]
    first_active = active[active].index[0]
    return weights.loc[first_active:].index


def _summary_metrics(returns: pd.Series) -> dict[str, float]:
    values = returns.dropna().astype(float).tolist()
    if not values:
        return {}
    return {
        "cumulative_return": _compound_return(pd.Series(values)),
        "annual_return": float((np.prod([1 + value for value in values]) ** (TRADING_DAYS / len(values))) - 1),
        "annual_volatility": volatility(values),
        "sharpe": sharpe_ratio(values),
        "max_drawdown": max_drawdown(values),
        "var_99": historical_var(values, 0.99),
        "expected_shortfall_95": expected_shortfall(values, 0.95),
        "win_rate": float(np.mean([value > 0 for value in values])),
        "best_day": float(max(values)),
        "worst_day": float(min(values)),
    }


def _backtest_evidence(returns: pd.Series) -> dict:
    clean = returns.dropna()
    if clean.empty:
        return {
            "status": "missing",
            "start_date": None,
            "end_date": None,
            "years": 0.0,
            "transaction_cost_included": True,
            "lookahead_bias_check": "no returns available",
        }
    years = len(clean) / TRADING_DAYS
    return {
        "status": "attached",
        "start_date": clean.index[0].date().isoformat(),
        "end_date": clean.index[-1].date().isoformat(),
        "observations": int(len(clean)),
        "years": float(years),
        "frequency": "daily",
        "transaction_cost_included": True,
        "cost_assumption": "5 bps buy, 5 bps sell, turnover-based",
        "lookahead_bias_check": "pass: weights are shifted one trading day before applying returns",
        "survivorship_bias_note": "ETF proxy test uses currently available ETFs and is not a survivorship-free stock universe.",
        "data_source": "yfinance ETF proxy panel",
    }


def _risk_packet(strategy_returns: pd.Series, benchmark_returns: pd.Series, turnover: pd.Series, market_returns: pd.DataFrame) -> dict:
    clean = strategy_returns.dropna().astype(float)
    benchmark = benchmark_returns.reindex(clean.index).fillna(0.0).astype(float)
    turnover = turnover.reindex(clean.index).fillna(0.0).astype(float)
    return {
        "summary_statistics": _summary_statistics(clean, turnover),
        "distribution_shape": _distribution_shape(clean),
        "tail_risk": _tail_risk(clean),
        "drawdown_behavior": _drawdown_behavior(clean),
        "time_stability": _time_stability(clean),
        "regime_breakdown": _regime_breakdown(clean, market_returns.reindex(clean.index)),
        "comparison_vs_benchmark": _benchmark_comparison(clean, benchmark),
        "chart_series": _chart_series(clean),
    }


def _summary_statistics(returns: pd.Series, turnover: pd.Series) -> dict:
    downside = returns[returns < 0]
    ann_return = _annual_return(returns)
    ann_vol = float(returns.std(ddof=1) * np.sqrt(TRADING_DAYS)) if len(returns) > 1 else 0.0
    downside_vol = float(downside.std(ddof=1) * np.sqrt(TRADING_DAYS)) if len(downside) > 1 else 0.0
    win = returns[returns > 0]
    loss = returns[returns < 0]
    max_dd = max_drawdown(returns.tolist())
    return {
        "observations": int(len(returns)),
        "cumulative_return": _compound_return(returns),
        "annual_return": ann_return,
        "annual_volatility": ann_vol,
        "sharpe": sharpe_ratio(returns.tolist()),
        "sortino": float(ann_return / downside_vol) if downside_vol else 0.0,
        "calmar": float(ann_return / abs(max_dd)) if max_dd else 0.0,
        "win_rate": float((returns > 0).mean()),
        "loss_rate": float((returns < 0).mean()),
        "average_daily_return": float(returns.mean()),
        "average_win": float(win.mean()) if len(win) else 0.0,
        "average_loss": float(loss.mean()) if len(loss) else 0.0,
        "payoff_ratio": float(abs(win.mean() / loss.mean())) if len(win) and len(loss) and loss.mean() else 0.0,
        "profit_factor": float(win.sum() / abs(loss.sum())) if len(loss) and loss.sum() else 0.0,
        "best_day": float(returns.max()),
        "worst_day": float(returns.min()),
        "annualized_turnover": float(turnover.mean() * TRADING_DAYS),
    }


def _distribution_shape(returns: pd.Series) -> dict:
    std = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    centered = returns - returns.mean()
    skewness = float((centered**3).mean() / (std**3)) if std else 0.0
    kurtosis = float((centered**4).mean() / (std**4)) if std else 0.0
    return {
        "mean": float(returns.mean()),
        "median": float(returns.median()),
        "standard_deviation": std,
        "skewness": skewness,
        "kurtosis": kurtosis,
        "excess_kurtosis": kurtosis - 3,
        "p01": float(returns.quantile(0.01)),
        "p05": float(returns.quantile(0.05)),
        "p25": float(returns.quantile(0.25)),
        "p75": float(returns.quantile(0.75)),
        "p95": float(returns.quantile(0.95)),
        "p99": float(returns.quantile(0.99)),
        "positive_days": int((returns > 0).sum()),
        "negative_days": int((returns < 0).sum()),
        "zero_days": int((returns == 0).sum()),
    }


def _tail_risk(returns: pd.Series) -> dict:
    std = returns.std(ddof=1)
    left_tail_2sigma = returns[returns < returns.mean() - 2 * std] if std else pd.Series(dtype=float)
    worst_days = returns.nsmallest(min(10, len(returns)))
    return {
        "var_95": float(returns.quantile(0.05)),
        "var_99": float(returns.quantile(0.01)),
        "expected_shortfall_95": float(returns[returns <= returns.quantile(0.05)].mean()),
        "expected_shortfall_99": float(returns[returns <= returns.quantile(0.01)].mean()),
        "left_tail_2sigma_count": int(len(left_tail_2sigma)),
        "left_tail_2sigma_frequency": float(len(left_tail_2sigma) / len(returns)) if len(returns) else 0.0,
        "worst_10_days": [{"date": idx.date().isoformat(), "return": float(value)} for idx, value in worst_days.items()],
    }


def _drawdown_behavior(returns: pd.Series) -> dict:
    wealth = (1 + returns.fillna(0.0)).cumprod()
    peak = wealth.cummax()
    drawdown = wealth / peak - 1
    durations = []
    current_duration = 0
    for value in drawdown:
        if value < 0:
            current_duration += 1
        elif current_duration:
            durations.append(current_duration)
            current_duration = 0
    if current_duration:
        durations.append(current_duration)
    worst_date = drawdown.idxmin()
    return {
        "max_drawdown": float(drawdown.min()),
        "max_drawdown_date": worst_date.date().isoformat(),
        "current_drawdown": float(drawdown.iloc[-1]),
        "average_drawdown": float(drawdown[drawdown < 0].mean()) if (drawdown < 0).any() else 0.0,
        "drawdown_days": int((drawdown < 0).sum()),
        "drawdown_frequency": float((drawdown < 0).mean()),
        "max_drawdown_duration_days": int(max(durations)) if durations else 0,
        "current_drawdown_duration_days": int(current_duration),
        "drawdown_episode_count": int(len(durations)),
    }


def _time_stability(returns: pd.Series) -> dict:
    windows = {}
    for window in [21, 63, 126, 252]:
        rolling_return = returns.rolling(window).mean() * TRADING_DAYS
        rolling_vol = returns.rolling(window).std() * np.sqrt(TRADING_DAYS)
        rolling_sharpe = (rolling_return / rolling_vol.replace(0, np.nan)).dropna()
        rolling_dd = returns.rolling(window).apply(lambda values: max_drawdown(list(values)), raw=False).dropna()
        windows[f"{window}d"] = {
            "latest_rolling_sharpe": float(rolling_sharpe.iloc[-1]) if len(rolling_sharpe) else 0.0,
            "average_rolling_sharpe": float(rolling_sharpe.mean()) if len(rolling_sharpe) else 0.0,
            "min_rolling_sharpe": float(rolling_sharpe.min()) if len(rolling_sharpe) else 0.0,
            "latest_rolling_volatility": float(rolling_vol.dropna().iloc[-1]) if len(rolling_vol.dropna()) else 0.0,
            "worst_rolling_drawdown": float(rolling_dd.min()) if len(rolling_dd) else 0.0,
            "positive_sharpe_rate": float((rolling_sharpe > 0).mean()) if len(rolling_sharpe) else 0.0,
        }
    return windows


def _regime_breakdown(strategy_returns: pd.Series, market_returns: pd.DataFrame) -> dict:
    regimes: dict[str, pd.Series] = {}
    if "SPY" in market_returns:
        regimes["equity_up"] = market_returns["SPY"] > 0
        regimes["equity_down"] = market_returns["SPY"] <= 0
        realized_vol = market_returns["SPY"].rolling(21).std()
        regimes["high_realized_vol"] = realized_vol >= realized_vol.quantile(0.75)
        regimes["low_realized_vol"] = realized_vol <= realized_vol.quantile(0.25)
    if "HYG" in market_returns:
        regimes["credit_supportive"] = market_returns["HYG"] > 0
        regimes["credit_stress"] = market_returns["HYG"] <= 0
    if "IEF" in market_returns:
        regimes["rates_falling_duration_supportive"] = market_returns["IEF"] > 0
        regimes["rates_rising_duration_headwind"] = market_returns["IEF"] <= 0
    if "UUP" in market_returns:
        regimes["usd_up"] = market_returns["UUP"] > 0
        regimes["usd_down"] = market_returns["UUP"] <= 0
    output = {}
    for name, mask in regimes.items():
        sliced = strategy_returns[mask.reindex(strategy_returns.index).fillna(False)]
        output[name] = _regime_stats(sliced)
    return output


def _regime_stats(returns: pd.Series) -> dict:
    if returns.empty:
        return {"observations": 0, "annual_return": 0.0, "annual_volatility": 0.0, "sharpe": 0.0, "max_drawdown": 0.0, "win_rate": 0.0}
    return {
        "observations": int(len(returns)),
        "annual_return": _annual_return(returns),
        "annual_volatility": float(returns.std(ddof=1) * np.sqrt(TRADING_DAYS)) if len(returns) > 1 else 0.0,
        "sharpe": sharpe_ratio(returns.tolist()),
        "max_drawdown": max_drawdown(returns.tolist()),
        "win_rate": float((returns > 0).mean()),
        "expected_shortfall_95": float(returns[returns <= returns.quantile(0.05)].mean()),
    }


def _benchmark_comparison(strategy_returns: pd.Series, benchmark_returns: pd.Series) -> dict:
    aligned = pd.concat([strategy_returns, benchmark_returns], axis=1).dropna()
    aligned.columns = ["strategy", "benchmark"]
    if aligned.empty:
        return {}
    variance = aligned["benchmark"].var()
    beta = float(aligned["strategy"].cov(aligned["benchmark"]) / variance) if variance else 0.0
    alpha_daily = float(aligned["strategy"].mean() - beta * aligned["benchmark"].mean())
    active = aligned["strategy"] - aligned["benchmark"]
    tracking_error = float(active.std(ddof=1) * np.sqrt(TRADING_DAYS)) if len(active) > 1 else 0.0
    up = aligned[aligned["benchmark"] > 0]
    down = aligned[aligned["benchmark"] < 0]
    return {
        "benchmark": "SPY",
        "correlation": float(aligned["strategy"].corr(aligned["benchmark"])) if len(aligned) > 1 else 0.0,
        "beta": beta,
        "alpha_annualized": float(alpha_daily * TRADING_DAYS),
        "tracking_error": tracking_error,
        "information_ratio": float((active.mean() * TRADING_DAYS) / tracking_error) if tracking_error else 0.0,
        "up_capture": float(up["strategy"].mean() / up["benchmark"].mean()) if len(up) and up["benchmark"].mean() else 0.0,
        "down_capture": float(down["strategy"].mean() / down["benchmark"].mean()) if len(down) and down["benchmark"].mean() else 0.0,
        "active_return_annualized": float(active.mean() * TRADING_DAYS),
    }


def _chart_series(returns: pd.Series) -> dict:
    tail = returns.tail(756)
    wealth = (1 + tail).cumprod()
    drawdown = wealth / wealth.cummax() - 1
    rolling_sharpe = (tail.rolling(63).mean() * TRADING_DAYS) / (tail.rolling(63).std() * np.sqrt(TRADING_DAYS)).replace(0, np.nan)
    return {
        "dates": [idx.date().isoformat() for idx in tail.index],
        "returns": [float(value) for value in tail],
        "cumulative_return": [float(value - 1) for value in wealth],
        "drawdown": [float(value) for value in drawdown],
        "rolling_63d_sharpe": [None if pd.isna(value) else float(value) for value in rolling_sharpe],
    }


def _action_recommendation(returns: pd.Series, turnover: pd.Series) -> dict[str, str]:
    values = returns.dropna().astype(float).tolist()
    if len(values) < 30:
        return {"action": "Research Hold", "reason_code": "missing_evidence", "interpretation": "Insufficient return history."}
    sharpe = sharpe_ratio(values)
    dd = max_drawdown(values)
    ann_cost = float(turnover.mean() * (BUY_BPS + SELL_BPS) / 2 / 10_000 * TRADING_DAYS)
    if dd < -0.45:
        return {
            "action": "Research Hold",
            "reason_code": "historical_drawdown_quality_failure",
            "interpretation": "Full-history drawdown fails the research-quality gate; this is not a live breach.",
        }
    if ann_cost > 0.015:
        return {"action": "Reduce", "reason_code": "cost_drag", "interpretation": "Turnover cost drag is too high for current evidence."}
    if sharpe < 0.25:
        return {"action": "Watch", "reason_code": "weak_risk_adjusted_return", "interpretation": "Risk-adjusted return is below minimum review threshold."}
    if sharpe > 1.0 and dd > -0.12:
        return {"action": "Increase Review", "reason_code": "validated_proxy_strength", "interpretation": "Prototype evidence is strong enough for deeper validation, not live allocation yet."}
    return {"action": "Keep Research", "reason_code": "acceptable_proxy_evidence", "interpretation": "Continue research and add WFO/regime/factor diagnostics."}


def _compound_return(returns: pd.Series) -> float:
    return float(np.prod(1.0 + returns.dropna().to_numpy(dtype=float)) - 1.0)


def _annual_return(returns: pd.Series) -> float:
    clean = returns.dropna()
    if clean.empty:
        return 0.0
    return float(np.prod(1 + clean.to_numpy(dtype=float)) ** (TRADING_DAYS / len(clean)) - 1)


def _top_n_weights(score: pd.DataFrame, n: int, rebalance_every: int) -> pd.DataFrame:
    raw = pd.DataFrame(0.0, index=score.index, columns=score.columns)
    for date in score.index:
        row = score.loc[date].dropna()
        if row.empty:
            continue
        chosen = row.nlargest(min(n, len(row))).index
        raw.loc[date, chosen] = 1 / len(chosen)
    return _rebalance_only(raw, rebalance_every)


def _rebalance_only(weights: pd.DataFrame, every: int) -> pd.DataFrame:
    rebalanced = pd.DataFrame(index=weights.index, columns=weights.columns, dtype=float)
    last = pd.Series(0.0, index=weights.columns)
    for idx, date in enumerate(weights.index):
        if idx % every == 0:
            row = weights.loc[date].fillna(0.0)
            if row.abs().sum() > 0 and (row < 0).any():
                last = row
            elif row.sum() > 0:
                last = row / row.sum()
        rebalanced.loc[date] = last
    return rebalanced.fillna(0.0)


def _assign_alloc(weights: pd.DataFrame, date, alloc: dict[str, float]) -> None:
    for ticker, value in alloc.items():
        if ticker in weights.columns:
            weights.loc[date, ticker] = value


def _zscore(series: pd.Series, window: int) -> pd.Series:
    mean = series.rolling(window).mean()
    std = series.rolling(window).std().replace(0, np.nan)
    return ((series - mean) / std).fillna(0.0)


def _drawdown_from_returns(returns: pd.Series) -> pd.Series:
    wealth = (1.0 + returns.fillna(0.0)).cumprod()
    peak = wealth.cummax()
    return wealth / peak - 1.0


def _vix_level_proxy(returns: pd.DataFrame) -> pd.Series:
    if "VIX" not in returns.columns:
        return pd.Series(20.0, index=returns.index)
    # Reconstruct approximate relative level from VIX returns when actual levels
    # are not passed into this strategy builder.
    return 20.0 * (1.0 + returns["VIX"].fillna(0.0)).cumprod()


def _vix_stress_score(returns: pd.DataFrame) -> pd.Series:
    vix = _vix_level_proxy(returns)
    return ((vix - 15) / 20).clip(0, 1)
