"""Strategy Factory Gate 2 variant generation.

This module creates specification-only strategy variants from a reproducible
current_run. It intentionally does not run backtests, ML, ranking, trading, or
paper-ledger actions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json

from src.strategies.strategy_factory_data import data_status


REQUIRED_VARIANT_FIELDS = [
    "variant_id",
    "variant_name",
    "theme",
    "strategy_name",
    "source_run_id",
    "source_material_ids",
    "thesis",
    "signal_formula",
    "universe_or_proxy",
    "benchmark",
    "rebalance_frequency",
    "holding_period",
    "features",
    "model_plan",
    "data_requirements",
    "testability_status",
    "blocked_reason",
    "why_it_may_work",
    "why_it_may_fail",
]

THEME_COMMODITY_PROXY_TREND = "commodity_proxy_trend"
THEME_ETF_MOMENTUM_ROTATION = "etf_momentum_rotation"
THEME_US_STOCK_MOMENTUM_QUALITY = "us_stock_cross_sectional_momentum_quality"
THEME_US_STOCK_LOW_VOL_DEFENSIVE = "us_stock_low_vol_defensive"
THEME_UNKNOWN_REVIEW_REQUIRED = "unknown_review_required"
ETF_FIXTURE_SYMBOLS = {"SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "GLD"}
NON_STOCK_PROXY_SYMBOLS = ETF_FIXTURE_SYMBOLS | {"CPER", "JJC", "DBB", "DBC", "COPX", "XME", "UUP", "USO"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _artifact_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def _run_dir(root: Path, run_id: str) -> Path:
    return root / "output" / "strategy_factory" / "runs" / run_id


def _available_symbols(run_dir: Path) -> set[str]:
    availability = _read_json(run_dir / "data_availability.json", {})
    symbols = set(str(symbol).upper() for symbol in availability.get("available_symbols", []))
    symbols.update(str(symbol).upper() for symbol in availability.get("usable_symbols", []))
    try:
        status = data_status()
        symbols.update(str(symbol).upper() for symbol in status.get("symbols_available", []))
        provider = status.get("provider_status") or {}
        symbols.update(str(symbol).upper() for symbol in provider.get("available_symbols", []))
    except Exception:
        pass
    return symbols


def _status_for(required: list[str], available: set[str], proxy_only: bool = True) -> tuple[str, str | None]:
    missing = [symbol for symbol in required if symbol.upper() not in available]
    if missing:
        return "BLOCKED_NEEDS_DATA", f"Missing required local symbols: {', '.join(missing)}"
    return ("PROXY_ONLY" if proxy_only else "READY_TO_TEST"), None


def _model_plan(kind: str) -> dict[str, Any]:
    return {
        "status": "PLANNED_NOT_RUN_GATE2",
        "allowed_models": ["linear_regression", "ridge_regression", "logistic_regression_direction"],
        "blocked_models": [
            {
                "model": "random_forest_or_gradient_boosting",
                "reason": "Gate 2 is variant generation only; nonlinear diagnostics require later test gate and package/sample validation.",
            }
        ],
        "target": "next-period return and next-period direction",
        "split_method": "chronological_no_shuffle",
        "variant_model_note": kind,
    }


def _variant(
    *,
    variant_id: str,
    variant_name: str,
    theme: str,
    strategy_name: str,
    source_run_id: str,
    source_material_ids: list[str],
    thesis: str,
    signal_formula: str,
    universe_or_proxy: list[str],
    benchmark: str,
    rebalance_frequency: str,
    holding_period: str,
    features: list[str],
    data_requirements: list[str],
    available: set[str],
    why_it_may_work: str,
    why_it_may_fail: str,
    model_note: str,
) -> dict[str, Any]:
    required_symbols = list(dict.fromkeys([*universe_or_proxy, benchmark, *[item for item in data_requirements if item.isupper() and len(item) <= 5]]))
    testability_status, blocked_reason = _status_for(required_symbols, available, proxy_only=True)
    return {
        "schema_version": "strategy_factory_variant_spec_v1",
        "variant_id": variant_id,
        "variant_name": variant_name,
        "theme": theme,
        "strategy_name": strategy_name,
        "source_run_id": source_run_id,
        "source_material_ids": source_material_ids,
        "thesis": thesis,
        "signal_formula": signal_formula,
        "universe_or_proxy": universe_or_proxy,
        "benchmark": benchmark,
        "rebalance_frequency": rebalance_frequency,
        "holding_period": holding_period,
        "features": features,
        "model_plan": _model_plan(model_note),
        "data_requirements": data_requirements,
        "testability_status": testability_status,
        "blocked_reason": blocked_reason,
        "why_it_may_work": why_it_may_work,
        "why_it_may_fail": why_it_may_fail,
        "candidate_status": "NOT_CANDIDATE_GATE2",
        "generated_at": _now(),
    }


def _detect_theme(run_manifest: dict[str, Any], classification: dict[str, Any], requirements: dict[str, Any], selected_materials: Any) -> str:
    explicit = str(requirements.get("theme") or classification.get("theme") or "").lower()
    if explicit in {THEME_COMMODITY_PROXY_TREND, THEME_ETF_MOMENTUM_ROTATION, THEME_US_STOCK_MOMENTUM_QUALITY, THEME_US_STOCK_LOW_VOL_DEFENSIVE, THEME_UNKNOWN_REVIEW_REQUIRED}:
        return explicit
    text_parts = [
        " ".join(str(value) for value in run_manifest.get("selected_material_names", [])),
        json.dumps(selected_materials, sort_keys=True) if selected_materials else "",
        str(classification.get("strategy_type") or ""),
    ]
    lower = "\n".join(text_parts).lower()
    if any(token in lower for token in ("copper", "cper", "copx", "xme", "hg=f")):
        return THEME_COMMODITY_PROXY_TREND
    if any(token in lower for token in ("low vol", "low-vol", "low volatility", "lower volatility", "defensive", "realized volatility", "beta filter")):
        return THEME_US_STOCK_LOW_VOL_DEFENSIVE
    if any(token in lower for token in ("u.s. stock", "us stock", "u.s. equity", "us equity", "equity universe", "cross-sectional", "cross sectional", "quality", "roe", "gross margin", "profitability")):
        return THEME_US_STOCK_MOMENTUM_QUALITY
    if (
        any(token in lower for token in ("etf", "rotation"))
        and any(token in lower for token in ("spy", "qqq", "iwm", "efa", "eem", "tlt", "gld"))
    ):
        return THEME_ETF_MOMENTUM_ROTATION
    return THEME_UNKNOWN_REVIEW_REQUIRED


def _build_unknown_variant(run_manifest: dict[str, Any], theme: str) -> list[dict[str, Any]]:
    run_id = str(run_manifest.get("run_id") or "")
    source_material_ids = list(run_manifest.get("selected_material_ids") or [])
    return [
        {
            "schema_version": "strategy_factory_variant_spec_v1",
            "variant_id": "REVIEW_REQUIRED_UNKNOWN_MATERIAL_V1",
            "variant_name": "Review Required - Unknown Material",
            "theme": theme,
            "strategy_name": "Review Required - Unknown Material",
            "source_run_id": run_id,
            "source_material_ids": source_material_ids,
            "thesis": "Missing Evidence: material could not be classified into a supported Strategy Factory theme.",
            "signal_formula": "REVIEW_REQUIRED",
            "universe_or_proxy": [],
            "benchmark": "Missing Evidence",
            "rebalance_frequency": "Missing Evidence",
            "holding_period": "Missing Evidence",
            "features": [],
            "model_plan": {"status": "MISSING_EVIDENCE", "allowed_models": [], "target": "Missing Evidence"},
            "data_requirements": [],
            "testability_status": "REVIEW_REQUIRED",
            "blocked_reason": "Unknown material does not default to a supported strategy theme.",
            "why_it_may_work": "Missing Evidence",
            "why_it_may_fail": "Missing Evidence",
            "candidate_status": "NOT_CANDIDATE_GATE2",
            "generated_at": _now(),
        }
    ]


def _build_copper_variants(run_manifest: dict[str, Any], available: set[str]) -> list[dict[str, Any]]:
    run_id = str(run_manifest.get("run_id") or "")
    source_material_ids = list(run_manifest.get("selected_material_ids") or [])
    return [
        _variant(
            variant_id="COPPER_CPER_MOMENTUM_21_63_V1",
            variant_name="CPER Momentum 21/63",
            theme=THEME_COMMODITY_PROXY_TREND,
            strategy_name="Copper CPER Momentum 21/63",
            source_run_id=run_id,
            source_material_ids=source_material_ids,
            thesis="Copper ETF proxy trends may persist over short and medium horizons.",
            signal_formula="Long CPER when 21d momentum and 63d momentum are both positive; flat otherwise.",
            universe_or_proxy=["CPER"],
            benchmark="DBC",
            rebalance_frequency="monthly",
            holding_period="1 month",
            features=["momentum_21d", "momentum_63d", "commodity_basket_proxy_dbc"],
            data_requirements=["CPER", "DBC", "daily adjusted OHLCV"],
            available=available,
            why_it_may_work="It isolates the simplest trend hypothesis and avoids adding filters before the base signal is understood.",
            why_it_may_fail="Single ETF proxy trend can whipsaw and may be dominated by broad commodity beta.",
            model_note="Use linear/ridge diagnostics only after the rule return stream exists.",
        ),
        _variant(
            variant_id="COPPER_CPER_MOMENTUM_VOL_FILTER_V1",
            variant_name="CPER Momentum + Volatility Filter",
            theme=THEME_COMMODITY_PROXY_TREND,
            strategy_name="Copper CPER Momentum + Volatility Filter",
            source_run_id=run_id,
            source_material_ids=source_material_ids,
            thesis="Copper momentum may work better when realized volatility is not elevated.",
            signal_formula="Long CPER when 63d momentum is positive and 21d realized volatility is below its 252d trailing volatility; flat otherwise.",
            universe_or_proxy=["CPER"],
            benchmark="DBC",
            rebalance_frequency="monthly",
            holding_period="1 month",
            features=["momentum_63d", "realized_volatility_21d", "realized_volatility_252d", "drawdown"],
            data_requirements=["CPER", "DBC", "daily adjusted OHLCV"],
            available=available,
            why_it_may_work="It directly tests the current run's risk-regime idea and may avoid unstable trend breaks.",
            why_it_may_fail="The volatility filter can remove profitable rebound periods and overfit the proxy history.",
            model_note="Direction model can test whether volatility adds incremental information after momentum.",
        ),
        _variant(
            variant_id="COPPER_CPER_DBC_RELATIVE_STRENGTH_V1",
            variant_name="CPER vs DBC Relative Strength",
            theme=THEME_COMMODITY_PROXY_TREND,
            strategy_name="Copper CPER vs DBC Relative Strength",
            source_run_id=run_id,
            source_material_ids=source_material_ids,
            thesis="Copper-specific strength may matter only when it outperforms the broad commodity basket.",
            signal_formula="Long CPER when CPER 63d return minus DBC 63d return is positive; flat otherwise.",
            universe_or_proxy=["CPER"],
            benchmark="DBC",
            rebalance_frequency="monthly",
            holding_period="1 month",
            features=["cper_momentum_63d", "dbc_momentum_63d", "relative_strength_vs_dbc"],
            data_requirements=["CPER", "DBC", "daily adjusted OHLCV"],
            available=available,
            why_it_may_work="It separates copper-specific trend from generic commodity beta.",
            why_it_may_fail="Relative strength may underperform when the broad basket leads copper or when CPER liquidity/roll effects dominate.",
            model_note="Ridge diagnostics should compare relative strength against absolute momentum.",
        ),
        _variant(
            variant_id="COPPER_CPER_UUP_USD_FILTER_V1",
            variant_name="CPER Momentum + UUP/USD Filter",
            theme=THEME_COMMODITY_PROXY_TREND,
            strategy_name="Copper CPER Momentum + UUP/USD Filter",
            source_run_id=run_id,
            source_material_ids=source_material_ids,
            thesis="Copper trends may be more favorable when USD strength is not a headwind.",
            signal_formula="Long CPER when CPER 63d momentum is positive and UUP 63d momentum is non-positive; flat otherwise.",
            universe_or_proxy=["CPER"],
            benchmark="DBC",
            rebalance_frequency="monthly",
            holding_period="1 month",
            features=["cper_momentum_63d", "uup_momentum_63d", "usd_filter", "relative_strength_vs_dbc"],
            data_requirements=["CPER", "DBC", "UUP", "daily adjusted OHLCV"],
            available=available,
            why_it_may_work="It adds a macro filter consistent with copper's sensitivity to USD conditions.",
            why_it_may_fail="UUP is an imperfect USD proxy and the filter may remove valid copper supply/demand moves.",
            model_note="Logistic direction diagnostics can test whether the USD filter changes hit rate.",
        ),
        _variant(
            variant_id="COPPER_EQUITY_PROXY_TREND_COPX_XME_V1",
            variant_name="COPX/XME Copper Equity Proxy Trend",
            theme=THEME_COMMODITY_PROXY_TREND,
            strategy_name="Copper Equity Proxy Trend",
            source_run_id=run_id,
            source_material_ids=source_material_ids,
            thesis="Copper-linked miners and metals equities may express copper trend with equity-market sensitivity.",
            signal_formula="Long equal-weight COPX/XME when both ETFs have positive 63d momentum and COPX outperforms SPY over 63d; flat otherwise.",
            universe_or_proxy=["COPX", "XME"],
            benchmark="SPY",
            rebalance_frequency="monthly",
            holding_period="1 month",
            features=["copx_momentum_63d", "xme_momentum_63d", "relative_strength_vs_spy", "equity_beta_proxy"],
            data_requirements=["COPX", "XME", "SPY", "daily adjusted OHLCV"],
            available=available,
            why_it_may_work="Equity proxies can capture listed miner sensitivity and may be easier to trade than futures-linked notes.",
            why_it_may_fail="Miner ETFs add equity beta, company risk, and sector effects that are not pure copper exposure.",
            model_note="Model plan should include benchmark-relative features versus SPY.",
        ),
        _variant(
            variant_id="COMMODITY_BASKET_REGIME_FILTER_V1",
            variant_name="Commodity Basket Regime Filter",
            theme=THEME_COMMODITY_PROXY_TREND,
            strategy_name="Commodity Basket Regime Filter",
            source_run_id=run_id,
            source_material_ids=source_material_ids,
            thesis="Copper proxy exposure may be more robust when broad commodities confirm the regime.",
            signal_formula="Long CPER when CPER 63d momentum is positive and DBC 126d momentum is positive; reduce or flat when broad commodity regime is negative.",
            universe_or_proxy=["CPER"],
            benchmark="DBC",
            rebalance_frequency="monthly",
            holding_period="1 month",
            features=["cper_momentum_63d", "dbc_momentum_126d", "commodity_regime_filter", "drawdown"],
            data_requirements=["CPER", "DBC", "daily adjusted OHLCV"],
            available=available,
            why_it_may_work="It requires confirmation from the broader commodity complex before accepting copper trend exposure.",
            why_it_may_fail="Broad commodity confirmation may lag copper-specific moves and reduce responsiveness.",
            model_note="Use diagnostics to test whether broad commodity regime improves rule stability.",
        ),
    ]


def _build_etf_variants(run_manifest: dict[str, Any], available: set[str]) -> list[dict[str, Any]]:
    run_id = str(run_manifest.get("run_id") or "")
    source_material_ids = list(run_manifest.get("selected_material_ids") or [])
    universe = ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "GLD"]
    return [
        _variant(
            variant_id="ETF_ROTATION_63_126_TOP2_V1",
            variant_name="ETF Momentum Rotation 63/126 Top 2",
            theme=THEME_ETF_MOMENTUM_ROTATION,
            strategy_name="ETF Momentum Rotation 63/126 Top 2",
            source_run_id=run_id,
            source_material_ids=source_material_ids,
            thesis="Cross-asset ETF momentum may persist when monthly rotation concentrates in the strongest liquid sleeves.",
            signal_formula="Rank SPY, QQQ, IWM, EFA, EEM, TLT, and GLD by 63d plus 126d momentum at month-end; hold the top 2 equal-weight for the next month.",
            universe_or_proxy=universe,
            benchmark="SPY",
            rebalance_frequency="monthly",
            holding_period="1 month",
            features=["momentum_63d", "momentum_126d", "cross_sectional_rank"],
            data_requirements=[*universe, "daily adjusted OHLCV"],
            available=available,
            why_it_may_work="It tests a broad, liquid ETF trend-following hypothesis without relying on a single commodity proxy.",
            why_it_may_fail="Momentum rotations can crowd into lagging defensive assets after reversals and may underperform SPY in equity-led rallies.",
            model_note="ML is not required for the baseline rotation rule; diagnostics require ETF-specific returns and lineage.",
        ),
        _variant(
            variant_id="ETF_ROTATION_63_126_TOP3_V1",
            variant_name="ETF Momentum Rotation 63/126 Top 3",
            theme=THEME_ETF_MOMENTUM_ROTATION,
            strategy_name="ETF Momentum Rotation 63/126 Top 3",
            source_run_id=run_id,
            source_material_ids=source_material_ids,
            thesis="A broader top-3 ETF basket may reduce single-sleeve concentration while preserving momentum exposure.",
            signal_formula="Rank SPY, QQQ, IWM, EFA, EEM, TLT, and GLD by 63d plus 126d momentum at month-end; hold the top 3 equal-weight for the next month.",
            universe_or_proxy=universe,
            benchmark="SPY",
            rebalance_frequency="monthly",
            holding_period="1 month",
            features=["momentum_63d", "momentum_126d", "cross_sectional_rank", "equal_weight_top3"],
            data_requirements=[*universe, "daily adjusted OHLCV"],
            available=available,
            why_it_may_work="Diversifying across three liquid ETFs may reduce whipsaw from a top-2 concentration rule.",
            why_it_may_fail="Wider holdings can dilute the signal and remain exposed to broad equity beta through SPY/QQQ/IWM.",
            model_note="Compare against top-2 only after both ETF variants have their own artifact lineage.",
        ),
    ]


def _available_us_stock_universe(available: set[str]) -> list[str]:
    symbols = [
        symbol
        for symbol in sorted(str(item).upper() for item in available)
        if symbol.isalpha() and 1 <= len(symbol) <= 5 and symbol not in NON_STOCK_PROXY_SYMBOLS
    ]
    return symbols[:50] if len(symbols) >= 5 else ["US_EQUITY_UNIVERSE"]


def _registry_available_symbols(available: set[str], theme: str) -> list[str]:
    if theme == THEME_ETF_MOMENTUM_ROTATION:
        return sorted(symbol for symbol in available if symbol in ETF_FIXTURE_SYMBOLS)
    if theme in {THEME_US_STOCK_MOMENTUM_QUALITY, THEME_US_STOCK_LOW_VOL_DEFENSIVE}:
        symbols = set(_available_us_stock_universe(available))
        if "SPY" in available:
            symbols.add("SPY")
        return sorted(symbols)
    return sorted(available)


def _build_us_stock_variants(run_manifest: dict[str, Any], available: set[str]) -> list[dict[str, Any]]:
    run_id = str(run_manifest.get("run_id") or "")
    source_material_ids = list(run_manifest.get("selected_material_ids") or [])
    universe = _available_us_stock_universe(available)
    common = {
        "theme": THEME_US_STOCK_MOMENTUM_QUALITY,
        "source_run_id": run_id,
        "source_material_ids": source_material_ids,
        "universe_or_proxy": universe,
        "benchmark": "SPY",
        "rebalance_frequency": "monthly",
        "holding_period": "1 month",
        "available": available,
    }
    return [
        _variant(
            variant_id="US_STOCK_MOMENTUM_12_1_TOP50_V1",
            variant_name="U.S. Stock Momentum 12-1 Top 50",
            strategy_name="U.S. Stock Momentum 12-1 Top 50",
            thesis="U.S. stocks with stronger trailing momentum excluding the most recent month may continue to outperform over the next rebalance period.",
            signal_formula="Rank available U.S. stocks by 252d momentum excluding the most recent 21 trading days; hold the top basket equal-weight monthly.",
            features=["momentum_252d_ex_recent_21d", "cross_sectional_rank", "quality_proxy_missing_evidence"],
            data_requirements=[*universe, "SPY", "U.S. equity daily adjusted OHLCV", "fundamental quality fields if available"],
            why_it_may_work="It tests a broad U.S. equity cross-sectional continuation hypothesis using only artifact-backed prices.",
            why_it_may_fail="Momentum can reverse, available universe coverage may be incomplete, and quality features may be missing.",
            model_note="No ML is used unless a U.S. stock feature matrix, target, split, fitted model, OOS metric, and artifacts exist.",
            **common,
        ),
        _variant(
            variant_id="US_STOCK_MOMENTUM_6_1_TOP50_V1",
            variant_name="U.S. Stock Momentum 6-1 Top 50",
            strategy_name="U.S. Stock Momentum 6-1 Top 50",
            thesis="A shorter U.S. stock momentum horizon may adapt faster than 12-1 momentum while still excluding the most recent month.",
            signal_formula="Rank available U.S. stocks by 126d momentum excluding the most recent 21 trading days; hold the top basket equal-weight monthly.",
            features=["momentum_126d_ex_recent_21d", "cross_sectional_rank", "quality_proxy_missing_evidence"],
            data_requirements=[*universe, "SPY", "U.S. equity daily adjusted OHLCV"],
            why_it_may_work="It tests whether medium-horizon continuation is present in the available U.S. stock universe.",
            why_it_may_fail="Shorter momentum may be noisier and more sensitive to rebalance timing.",
            model_note="No ML is used unless a complete U.S. stock ML artifact chain exists.",
            **common,
        ),
        _variant(
            variant_id="US_STOCK_MOMENTUM_QUALITY_TOP50_V1",
            variant_name="U.S. Stock Momentum + Quality Top 50",
            strategy_name="U.S. Stock Momentum + Quality Top 50",
            thesis="Momentum combined with profitability or quality may avoid lower-quality rebound names when those fields are available.",
            signal_formula="Rank available U.S. stocks by 252d momentum excluding the most recent 21 trading days; add profitability/ROE/gross-margin quality only when source fields exist, otherwise mark quality as Missing Evidence.",
            features=["momentum_252d_ex_recent_21d", "quality_proxy_missing_evidence", "cross_sectional_rank"],
            data_requirements=[*universe, "SPY", "profitability", "roe", "gross_margin", "U.S. equity daily adjusted OHLCV"],
            why_it_may_work="It keeps quality as an explicit evidence requirement rather than silently replacing it with price momentum.",
            why_it_may_fail="If fundamentals are unavailable, the quality leg is Missing Evidence and cannot support the score.",
            model_note="Quality is not inferred by ML; missing fundamentals remain Missing Evidence.",
            **common,
        ),
        _variant(
            variant_id="US_STOCK_MOMENTUM_LIQUIDITY_FILTER_TOP50_V1",
            variant_name="U.S. Stock Momentum + Liquidity Filter Top 50",
            strategy_name="U.S. Stock Momentum + Liquidity Filter Top 50",
            thesis="A liquidity screen may make a U.S. stock momentum basket more implementable when price and volume fields are available.",
            signal_formula="Rank available U.S. stocks by 252d momentum excluding the most recent 21 trading days after applying available minimum price and dollar-volume filters; missing liquidity fields are Missing Evidence.",
            features=["momentum_252d_ex_recent_21d", "minimum_price_filter", "dollar_volume_filter_missing_evidence"],
            data_requirements=[*universe, "SPY", "close", "volume", "dollar_volume", "U.S. equity daily adjusted OHLCV"],
            why_it_may_work="It tests whether the signal can be expressed in a more liquid tradable stock basket.",
            why_it_may_fail="Liquidity filters can remove high-momentum smaller stocks and missing volume data blocks the filter evidence.",
            model_note="No ML is used unless a complete U.S. stock ML artifact chain exists.",
            **common,
        ),
    ]


def _build_us_stock_low_vol_variants(run_manifest: dict[str, Any], available: set[str]) -> list[dict[str, Any]]:
    run_id = str(run_manifest.get("run_id") or "")
    source_material_ids = list(run_manifest.get("selected_material_ids") or [])
    universe = _available_us_stock_universe(available)
    common = {
        "theme": THEME_US_STOCK_LOW_VOL_DEFENSIVE,
        "source_run_id": run_id,
        "source_material_ids": source_material_ids,
        "universe_or_proxy": universe,
        "benchmark": "SPY",
        "rebalance_frequency": "monthly",
        "holding_period": "1 month",
        "available": available,
    }
    return [
        _variant(
            variant_id="US_STOCK_LOW_VOL_63D_TOP20_V1",
            variant_name="U.S. Stock Low Vol 63D Top 20",
            strategy_name="U.S. Stock Low Vol Defensive 63D Top 20",
            thesis="U.S. stocks with lower recent realized volatility may provide a defensive equity basket with smoother participation versus SPY.",
            signal_formula="Rank available U.S. stocks by ascending 63d realized volatility of daily adjusted returns; hold the lowest-volatility basket equal-weight monthly.",
            features=["realized_volatility_63d", "defensive_rank", "cross_sectional_low_vol_score"],
            data_requirements=[*universe, "SPY", "U.S. equity daily adjusted OHLCV"],
            why_it_may_work="A lower-volatility basket can reduce drawdown sensitivity while retaining broad equity exposure.",
            why_it_may_fail="Low-volatility stocks can lag sharp risk-on rallies and may concentrate in defensive sectors.",
            model_note="No ML is used unless a complete U.S. stock low-vol feature matrix, target, split, fitted model, OOS metric, and artifacts exist.",
            **common,
        ),
        _variant(
            variant_id="US_STOCK_LOW_VOL_126D_TOP20_V1",
            variant_name="U.S. Stock Low Vol 126D Top 20",
            strategy_name="U.S. Stock Low Vol Defensive 126D Top 20",
            thesis="A medium-horizon low-volatility rank may be more stable than a shorter volatility window for defensive stock selection.",
            signal_formula="Rank available U.S. stocks by ascending 126d realized volatility of daily adjusted returns; hold the lowest-volatility basket equal-weight monthly.",
            features=["realized_volatility_126d", "defensive_rank", "cross_sectional_low_vol_score"],
            data_requirements=[*universe, "SPY", "U.S. equity daily adjusted OHLCV"],
            why_it_may_work="The longer volatility estimate may reduce turnover and avoid reacting to brief noise spikes.",
            why_it_may_fail="The longer window may adapt slowly after volatility regimes change.",
            model_note="No ML is used unless a complete low-volatility ML evidence chain exists.",
            **common,
        ),
        _variant(
            variant_id="US_STOCK_LOW_VOL_BETA_FILTER_TOP20_V1",
            variant_name="U.S. Stock Low Vol + Beta Filter Top 20",
            strategy_name="U.S. Stock Low Vol Defensive Beta Filter Top 20",
            thesis="Combining low realized volatility with an optional benchmark beta filter may improve defensive behavior when SPY-relative returns are available.",
            signal_formula="Rank stocks by ascending 126d realized volatility, optionally excluding stocks with trailing beta above 1.0 versus SPY when benchmark-relative returns are available; hold the top defensive basket equal-weight monthly.",
            features=["realized_volatility_126d", "beta_vs_spy_126d_optional", "defensive_rank"],
            data_requirements=[*universe, "SPY", "U.S. equity daily adjusted OHLCV", "benchmark-relative returns for beta if available"],
            why_it_may_work="The beta filter can avoid names whose low idiosyncratic volatility still carries high benchmark sensitivity.",
            why_it_may_fail="Beta estimates can be unstable and may over-filter stocks during market regime shifts.",
            model_note="Beta is a rule feature only; missing beta evidence remains Missing Evidence rather than inferred ML.",
            **common,
        ),
    ]


def _build_variants(run_manifest: dict[str, Any], available: set[str], theme: str) -> list[dict[str, Any]]:
    if theme == THEME_COMMODITY_PROXY_TREND:
        return _build_copper_variants(run_manifest, available)
    if theme == THEME_ETF_MOMENTUM_ROTATION:
        return _build_etf_variants(run_manifest, available)
    if theme == THEME_US_STOCK_MOMENTUM_QUALITY:
        return _build_us_stock_variants(run_manifest, available)
    if theme == THEME_US_STOCK_LOW_VOL_DEFENSIVE:
        return _build_us_stock_low_vol_variants(run_manifest, available)
    return _build_unknown_variant(run_manifest, theme)


def generate_strategy_variants(root: Path, run_id: str) -> dict[str, Any]:
    run_dir = _run_dir(root, run_id)
    if not run_dir.is_dir():
        raise ValueError(f"Strategy Factory run directory not found: {run_dir}")
    run_manifest = _read_json(run_dir / "run_manifest.json", {})
    if not run_manifest:
        raise ValueError(f"run_manifest.json missing or unreadable for {run_id}")

    selected_materials = _read_json(run_dir / "selected_materials.json", [])
    current_candidate = _read_json(run_dir / "current_run_candidate.json", {})
    availability = _read_json(run_dir / "data_availability.json", {})
    proxy_mapping = _read_json(run_dir / "proxy_mapping_used.json", {})
    classification = _read_json(run_dir / "strategy_type_classification.json", {})
    feature_plan = _read_json(run_dir / "feature_plan.json", {})
    intelligence_report = _artifact_text(run_dir / "intelligence_report.md")
    evidence_report = _artifact_text(run_dir / "evidence_report.md")

    variants_dir = run_dir / "variants"
    variants_dir.mkdir(parents=True, exist_ok=True)
    available = _available_symbols(run_dir)
    data_requirements = _read_json(run_dir / "data_requirements.json", {})
    theme = _detect_theme(run_manifest, classification, data_requirements, selected_materials)
    variants = _build_variants(run_manifest, available, theme)
    material_metadata = _read_json(run_dir / "material_metadata.json", {})
    if material_metadata.get("generated_from_material"):
        for variant in variants:
            variant["generated_from_material"] = True
            variant["source_material_path"] = material_metadata.get("source_material_path")
            variant["source_material_hash"] = material_metadata.get("source_material_hash")
            variant["material_generated_at"] = material_metadata.get("generated_at")
    registry_variants = []
    for variant in variants:
        variant_dir = variants_dir / variant["variant_id"]
        variant_path = variant_dir / "variant_spec.json"
        _write_json(variant_path, variant)
        registry_variants.append(
            {
                "variant_id": variant["variant_id"],
                "variant_name": variant["variant_name"],
                "theme": variant.get("theme"),
                "strategy_name": variant.get("strategy_name"),
                "testability_status": variant["testability_status"],
                "universe_or_proxy": variant["universe_or_proxy"],
                "benchmark": variant["benchmark"],
                "variant_spec_path": str(variant_path),
            }
        )

    registry = {
        "schema_version": "strategy_factory_variant_registry_v1",
        "status": "COMPLETED",
        "gate": "GATE2_VARIANT_GENERATION_ONLY",
        "source_run_id": run_id,
        "source_material_ids": run_manifest.get("selected_material_ids", []),
        "source_material_names": run_manifest.get("selected_material_names", []),
        "strategy_type": classification.get("strategy_type"),
        "theme": theme,
        "data_decision": availability.get("decision"),
        "available_symbols": _registry_available_symbols(available, theme),
        "variant_count": len(variants),
        "variants": registry_variants,
        "explicit_non_actions": [
            "NO_BACKTESTS_RUN",
            "NO_ML_RUN",
            "NO_RANKING",
            "NO_DASHBOARD_LAYOUT_CHANGE",
            "NO_DEPLOY",
            "NO_LIVE_TRADING",
            "NO_PAPER_LEDGER_MUTATION",
        ],
        "inputs_read": {
            "selected_material_count": len(selected_materials) if isinstance(selected_materials, list) else None,
            "current_run_candidate_present": bool(current_candidate),
            "proxy_mapping_groups": sorted((proxy_mapping.get("mapping") or {}).keys()),
            "feature_plan_status": feature_plan.get("status"),
            "intelligence_report_present": bool(intelligence_report),
            "evidence_report_present": bool(evidence_report),
        },
        "generated_at": _now(),
    }
    _write_json(variants_dir / "variant_registry.json", registry)
    _write_variant_generation_report(variants_dir / "variant_generation_report.md", registry, variants)
    return registry


def _write_variant_generation_report(path: Path, registry: dict[str, Any], variants: list[dict[str, Any]]) -> None:
    lines = [
        f"# Strategy Factory Gate 2 Variant Generation - {registry.get('source_run_id')}",
        "",
        "Status: COMPLETED",
        "",
        "Gate 2 generated strategy specifications only. No backtests, ML diagnostics, rankings, deployment, live trading, or paper-ledger mutation were performed.",
        "",
        "## Source Context",
        f"- Strategy type: {registry.get('strategy_type')}",
        f"- Data decision: {registry.get('data_decision')}",
        f"- Source materials: {', '.join(registry.get('source_material_ids') or [])}",
        "",
        "## Variants",
    ]
    for variant in variants:
        lines.extend(
            [
                f"### {variant['variant_name']}",
                f"- Variant ID: {variant['variant_id']}",
                f"- Testability: {variant['testability_status']}",
                f"- Universe/proxy: {', '.join(variant['universe_or_proxy'])}",
                f"- Benchmark: {variant['benchmark']}",
                f"- Signal: {variant['signal_formula']}",
                f"- Why it may work: {variant['why_it_may_work']}",
                f"- Why it may fail: {variant['why_it_may_fail']}",
                "",
            ]
        )
    lines.extend(
        [
            "## Next Gate",
            "Gate 3 should evaluate variants with controlled backtests and robustness checks. Gate 2 does not choose a winner or mark any variant as Candidate.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
