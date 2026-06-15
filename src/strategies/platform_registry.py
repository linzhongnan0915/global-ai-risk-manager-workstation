"""Platform registry for Combined Portfolio members and extended reference baselines."""

from __future__ import annotations

from src.strategies.c3a1_signals import (
    breakout_persistence,
    downside_beta,
    improving_liquidity,
    low_amihud_illiquidity,
    low_gap_risk,
    low_max_effect,
    low_rolling_drawdown,
    low_tail_loss,
    low_downside_volatility,
    price_efficiency,
    relative_strength_12_1,
    relative_strength_6_1,
    residual_momentum_12_1,
    stable_dollar_volume,
    trend_quality,
    volatility_adjusted_momentum,
    volume_confirmed_trend,
)
from src.strategies.c3a2_signals import (
    distance_from_200dma,
    low_idiosyncratic_volatility_60d,
    low_intraday_range_volatility,
    low_market_beta_60d,
    low_realized_volatility_60d,
    medium_term_reversal_22d,
    short_term_reversal_5d,
    slow_momentum_9_1,
    high_log_dollar_volume_63d,
)
from src.strategies.c3a1_registry import C3A1_SPECS, C3A1_IDS
from src.strategies.downside_beta_defensive import SPEC as C2B2_003_SPEC
from src.strategies.liquidity_resilience import SPEC as C2A2_020_SPEC
from src.strategies.low_residual_volatility import SPEC as C2A2_002_SPEC
from src.strategies.overnight_gap_reversal import SPEC as C2A2_004_SPEC
from src.strategies.realized_skewness import SPEC as C2B2_004_SPEC
from src.strategies.strategy_factory import StrategySpec

COMPOSITE_ID = "COMBINED_PORTFOLIO_V1"
COMPOSITE_NAME = "Combined Portfolio"
COMPOSITE_LABEL = "Equal-weight composite of all eligible ACTIVE underlying strategies — research only."

STRATEGY_SELECTION_STATUS: dict[str, dict[str, str]] = {
    "C2A2_004": {"status": "REPAIR", "reason": "Distinct reversal profile, but extreme turnover and cost drag require repair."},
    "C2A2_020": {"status": "REPAIR", "reason": "Weak standalone Sharpe and material cost drag; retain for redesign review."},
    "C3A1_001": {"status": "ACTIVE", "reason": "Strongest standalone net Sharpe among current price-based strategies."},
    "C3A1_002": {"status": "ACTIVE", "reason": "Usable momentum baseline and superior replacement for C3A1_004."},
    "C3A1_003": {"status": "ACTIVE", "reason": "Positive standalone evidence with non-identical momentum horizon."},
    "C3A1_004": {"status": "ARCHIVED", "reason": "Correlation 0.905 with clearly superior C3A1_002; dominated duplicate."},
    "C3A1_005": {"status": "REPAIR", "reason": "Correlation 0.961 with C3A1_015, which has lower drawdown and slightly lower cost."},
    "C3A1_006": {"status": "REPAIR", "reason": "Weak Sharpe and unacceptable drawdown relative to return."},
    "C3A1_012": {"status": "REPAIR", "reason": "Weak standalone Sharpe and material cost drag; possible redesign value."},
    "C3A1_013": {"status": "ACTIVE", "reason": "Positive liquidity-premium evidence with credible standalone value."},
    "C3A1_015": {"status": "ACTIVE", "reason": "Retained over 0.961-correlated C3A1_005 due to lower drawdown and slightly lower cost."},
    "C3A2_008": {"status": "ACTIVE", "reason": "Strongest slow-momentum evidence; retained despite family overlap."},
    "C3A2_009": {"status": "REPAIR", "reason": "Diversifying profile, but negative marginal portfolio contribution requires repair."},
}

FUNDAMENTAL_RESEARCH_CANDIDATE_IDS: tuple[str, ...] = (
    "FUNDAMENTAL_MOMENTUM",
    "EARNINGS_QUALITY",
    "CAPEX_EFFICIENCY",
    "PROFITABLE_SMALL_CAP",
    "CONSERVATIVE_ASSET_GROWTH",
    "CASH_FLOW_YIELD",
    "MARGIN_IMPROVEMENT",
    "REVENUE_ACCELERATION",
    "CASH_FLOW_MOMENTUM",
    "LOW_LEVERAGE_QUALITY",
    "QUALITY_AT_REASONABLE_PRICE",
    "SHAREHOLDER_YIELD",
)

FUNDAMENTAL_SELECTION_STATUS: dict[str, dict[str, str]] = {
    "FUNDAMENTAL_MOMENTUM": {"status": "ACTIVE", "reason": "Strong net Sharpe, positive preliminary OOS, and low legacy correlation."},
    "CAPEX_EFFICIENCY": {"status": "ARCHIVED", "reason": "Expanded-universe full-period and preliminary OOS returns are both negative."},
    "EARNINGS_QUALITY": {"status": "ACTIVE", "reason": "Strong net Sharpe, positive preliminary OOS, and low legacy correlation."},
    "PROFITABLE_SMALL_CAP": {"status": "ARCHIVED", "reason": "Expanded-universe full-period and preliminary OOS returns are both negative."},
    "CONSERVATIVE_ASSET_GROWTH": {"status": "ARCHIVED", "reason": "Negative full-period and preliminary OOS evidence."},
    "CASH_FLOW_YIELD": {"status": "ARCHIVED", "reason": "Near-zero net return, negative preliminary OOS return, and cost drag exceeds edge."},
    "MARGIN_IMPROVEMENT": {"status": "ACTIVE", "reason": "Strongest net Sharpe, positive preliminary OOS, and low legacy correlation."},
    "REVENUE_ACCELERATION": {"status": "REPAIR", "reason": "Positive preliminary OOS, but weak full-period Sharpe and deep drawdown."},
    "CASH_FLOW_MOMENTUM": {"status": "ARCHIVED", "reason": "Expanded-universe full-period and preliminary OOS returns are both negative."},
    "LOW_LEVERAGE_QUALITY": {"status": "ARCHIVED", "reason": "Expanded-universe net and preliminary OOS returns are negative."},
    "QUALITY_AT_REASONABLE_PRICE": {"status": "REPAIR", "reason": "Weak full-period evidence and negative OOS; retained only for low correlation."},
    "SHAREHOLDER_YIELD": {"status": "ARCHIVED", "reason": "Negative full-period and preliminary OOS evidence."},
}

FINAL_DELIVERY_CANDIDATE_IDS: tuple[str, ...] = (
    "OVERNIGHT_INTRADAY_ENSEMBLE",
    "FILING_SHOCK_CONTINUATION",
    "FUNDAMENTAL_SHOCK_RECOVERY",
    "CROSS_SECTIONAL_DISPERSION_REVERSAL",
    "LIQUIDITY_SHOCK_RECOVERY",
    "VOLATILITY_SCALED_TREND",
    "DOWNSIDE_RESILIENT_MOMENTUM",
    "REVENUE_ACCELERATION_QUALITY",
    "CASH_FLOW_GROWTH_QUALITY",
    "OPERATING_EFFICIENCY_IMPROVEMENT",
    "DELEVERAGING_PROFITABILITY",
)

FINAL_DELIVERY_SELECTION_STATUS: dict[str, dict[str, str]] = {
    "OVERNIGHT_INTRADAY_ENSEMBLE": {"status": "ACTIVE", "reason": "Positive standalone, OOS, doubled-cost, delayed-execution, and marginal portfolio evidence."},
    "FILING_SHOCK_CONTINUATION": {"status": "ACTIVE", "reason": "Positive standalone, OOS, doubled-cost, delayed-execution, and marginal portfolio evidence."},
    "FUNDAMENTAL_SHOCK_RECOVERY": {"status": "ACTIVE", "reason": "Positive standalone, OOS, doubled-cost, delayed-execution, and diversification evidence."},
    "CROSS_SECTIONAL_DISPERSION_REVERSAL": {"status": "DATA_INSUFFICIENT", "reason": "Average eligible cross-section is below the minimum diagnostic threshold."},
    "LIQUIDITY_SHOCK_RECOVERY": {"status": "DATA_INSUFFICIENT", "reason": "Sparse event cross-section and negative expanded-universe net and preliminary OOS results."},
    "VOLATILITY_SCALED_TREND": {"status": "REPAIR", "reason": "Weak full-period Sharpe, doubled costs remove the edge, and marginal contribution is negative."},
    "DOWNSIDE_RESILIENT_MOMENTUM": {"status": "ARCHIVED", "reason": "Negative full-period and preliminary OOS evidence with negative marginal contribution."},
    "REVENUE_ACCELERATION_QUALITY": {"status": "ARCHIVED", "reason": "Negative full-period and preliminary OOS evidence with negative marginal contribution."},
    "CASH_FLOW_GROWTH_QUALITY": {"status": "ACTIVE", "reason": "Positive standalone, OOS, doubled-cost, delayed-execution, and marginal portfolio evidence."},
    "OPERATING_EFFICIENCY_IMPROVEMENT": {"status": "REPAIR", "reason": "Positive net and OOS evidence, but marginal Combined Portfolio Sharpe contribution is negative."},
    "DELEVERAGING_PROFITABILITY": {"status": "DATA_INSUFFICIENT", "reason": "Reliable point-in-time debt/assets or debt/equity history is unavailable."},
}

EXPANDED_SELECTION_CANDIDATE_IDS: tuple[str, ...] = (
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

EXPANDED_SELECTION_STATUS: dict[str, dict[str, str]] = {
    "LIQUIDITY_SHOCK_RECOVERY": {"status": "DATA_INSUFFICIENT", "reason": "Sparse eligible event cross-section and negative net/OOS results."},
    "OPERATING_EFFICIENCY_IMPROVEMENT": {"status": "REPAIR", "reason": "Positive net and OOS evidence, but negative marginal portfolio Sharpe contribution."},
    "CAPEX_EFFICIENCY": {"status": "ARCHIVED", "reason": "Negative net and preliminary OOS results."},
    "PROFITABLE_SMALL_CAP": {"status": "ARCHIVED", "reason": "Negative net and preliminary OOS results."},
    "CASH_FLOW_MOMENTUM": {"status": "ARCHIVED", "reason": "Negative net and preliminary OOS results."},
    "REVENUE_ACCELERATION": {"status": "REPAIR", "reason": "Positive net and OOS results, but Sharpe is below 0.25."},
    "LOW_LEVERAGE_QUALITY": {"status": "ARCHIVED", "reason": "Negative net and preliminary OOS results."},
    "OVERNIGHT_GAP_REVERSAL_REDUCED_TURNOVER": {"status": "ACTIVE", "reason": "Passed positive net/OOS, Sharpe, doubled-cost, delayed-execution, correlation, coverage, and marginal portfolio gates."},
    "GROSS_PROFITABILITY_GROWTH": {"status": "REPAIR", "reason": "Positive preliminary OOS, but negative full-period net return and Sharpe."},
    "CASH_FLOW_MARGIN_IMPROVEMENT": {"status": "REPAIR", "reason": "Positive full-period net result, but negative preliminary OOS and low Sharpe."},
    "QUALITY_MOMENTUM_COMPOSITE": {"status": "REPAIR", "reason": "Positive preliminary OOS, but negative full-period net return and Sharpe."},
    "LOW_ACCRUAL_MOMENTUM": {"status": "REPAIR", "reason": "Strong standalone and robustness evidence, but negative marginal portfolio Sharpe contribution."},
}

OHLCV_ALPHA_CANDIDATE_IDS: tuple[str, ...] = (
    "RESIDUAL_SHORT_TERM_REVERSAL",
    "VOLUME_PRICE_DIVERGENCE_REVERSAL",
    "RANGE_COMPRESSION_BREAKOUT",
    "LOW_BETA_DEFENSIVE",
    "IDIOSYNCRATIC_VOLATILITY_REVERSAL",
    "LIQUIDITY_ADJUSTED_MOMENTUM",
    "GAP_VOLUME_CONTINUATION",
    "DRAWDOWN_RECOVERY",
    "INTRADAY_STRENGTH_PERSISTENCE",
    "DISPERSION_CONDITIONAL_MOMENTUM",
)

OHLCV_ALPHA_SELECTION_STATUS: dict[str, dict[str, str]] = {
    "RESIDUAL_SHORT_TERM_REVERSAL": {"status": "REPAIR", "reason": "Positive net and diversification evidence, but preliminary OOS return is slightly negative and Sharpe is below 0.25."},
    "VOLUME_PRICE_DIVERGENCE_REVERSAL": {"status": "ARCHIVED", "reason": "Negative net and preliminary OOS results; doubled costs and delayed execution also remain negative."},
    "RANGE_COMPRESSION_BREAKOUT": {"status": "REPAIR", "reason": "Positive OOS and delayed-execution results, but low Sharpe and doubled costs remove the edge."},
    "LOW_BETA_DEFENSIVE": {"status": "ARCHIVED", "reason": "Negative net and preliminary OOS results with negative marginal portfolio contribution."},
    "IDIOSYNCRATIC_VOLATILITY_REVERSAL": {"status": "ARCHIVED", "reason": "Negative net and preliminary OOS results; robustness tests remain negative."},
    "LIQUIDITY_ADJUSTED_MOMENTUM": {"status": "ACTIVE", "reason": "Passed positive net/OOS, Sharpe, doubled-cost, delayed-execution, coverage, correlation, and marginal portfolio gates."},
    "GAP_VOLUME_CONTINUATION": {"status": "REPAIR", "reason": "Positive preliminary OOS, but full-period net, Sharpe, doubled-cost, and delayed-execution results are negative."},
    "DRAWDOWN_RECOVERY": {"status": "REPAIR", "reason": "Positive preliminary OOS, but full-period net, Sharpe, doubled-cost, and delayed-execution results are negative."},
    "INTRADAY_STRENGTH_PERSISTENCE": {"status": "REPAIR", "reason": "Positive preliminary OOS, but full-period net, Sharpe, doubled-cost, and delayed-execution results are negative."},
    "DISPERSION_CONDITIONAL_MOMENTUM": {"status": "REPAIR", "reason": "Strong standalone and robustness evidence, but marginal Combined Portfolio Sharpe contribution is negative."},
}

DIVERSIFIED_CANDIDATE_IDS: tuple[str, ...] = (
    "BETA_NEUTRAL_RESIDUAL_MOMENTUM", "BETA_NEUTRAL_SHORT_TERM_REVERSAL",
    "LOW_VOLATILITY_TREND_CARRY", "VOLUME_CONFIRMED_GAP_CONTINUATION",
    "CASH_RETURN_ON_ASSETS", "FREE_CASH_FLOW_PROFITABILITY", "GROSS_MARGIN_STABILITY",
    "DEBT_PAYDOWN_PROFITABILITY", "WORKING_CAPITAL_DISCIPLINE",
    "QUALITY_FILTERED_FILING_DRIFT", "NEGATIVE_FILING_SHOCK_REVERSAL",
    "BALANCED_FUNDAMENTAL_MULTIFACTOR",
)

DIVERSIFIED_SELECTION_STATUS: dict[str, dict[str, str]] = {
    "BETA_NEUTRAL_RESIDUAL_MOMENTUM": {"status": "REPAIR", "reason": "Standalone and OOS evidence pass, but portfolio Sharpe, drawdown, and left-tail contributions are negative."},
    "BETA_NEUTRAL_SHORT_TERM_REVERSAL": {"status": "REPAIR", "reason": "Positive diversification and drawdown evidence, but OOS return is slightly negative and Sharpe is below 0.25."},
    "LOW_VOLATILITY_TREND_CARRY": {"status": "ARCHIVED", "reason": "Negative net and preliminary OOS results."},
    "VOLUME_CONFIRMED_GAP_CONTINUATION": {"status": "DATA_INSUFFICIENT", "reason": "Average eligible event cross-section is below the minimum threshold."},
    "CASH_RETURN_ON_ASSETS": {"status": "REPAIR", "reason": "Positive full-period net result, but OOS and stressed-cost results are negative."},
    "FREE_CASH_FLOW_PROFITABILITY": {"status": "REPAIR", "reason": "Positive full-period and stressed-cost results, but preliminary OOS is negative and Sharpe is low."},
    "GROSS_MARGIN_STABILITY": {"status": "ARCHIVED", "reason": "Negative net and preliminary OOS results."},
    "DEBT_PAYDOWN_PROFITABILITY": {"status": "REPAIR", "reason": "Positive full-period and robustness results, but preliminary OOS is negative and Sharpe is low."},
    "WORKING_CAPITAL_DISCIPLINE": {"status": "REPAIR", "reason": "Net Sharpe is only 0.103 without proven material portfolio benefit."},
    "QUALITY_FILTERED_FILING_DRIFT": {"status": "REPAIR", "reason": "Preliminary OOS return is only 0.09%, which is not economically meaningful."},
    "NEGATIVE_FILING_SHOCK_REVERSAL": {"status": "REPAIR", "reason": "Positive preliminary OOS, but full-period net and robustness results are negative."},
    "BALANCED_FUNDAMENTAL_MULTIFACTOR": {"status": "REPAIR", "reason": "Positive full-period and robustness results, but preliminary OOS and marginal Sharpe are negative."},
}

CHALLENGE_CANDIDATE_IDS: tuple[str, ...] = (
    "HEDGED_RESIDUAL_MOMENTUM_V2", "ORTHOGONAL_LOW_ACCRUAL_MOMENTUM", "CLUSTER_NEUTRAL_MEAN_REVERSION",
    "ASSET_LIGHT_COMPOUNDER", "FCF_REINVESTMENT_EFFICIENCY", "EARNINGS_QUALITY_VALUE_SPREAD",
    "CASH_CONVERSION_IMPROVEMENT", "HIGH_CONVICTION_FILING_DRIFT_V2", "CASH_FLOW_INFLECTION_CONTINUATION",
    "BALANCE_SHEET_REPAIR_AFTER_STRESS",
)

CHALLENGE_SELECTION_STATUS: dict[str, dict[str, str]] = {
    "HEDGED_RESIDUAL_MOMENTUM_V2": {"status": "REPAIR", "reason": "Negative net and robustness results; explicit SPY hedge and hedge-cost Trade Log remain unsupported by the shared stock-only backtester."},
    "ORTHOGONAL_LOW_ACCRUAL_MOMENTUM": {"status": "REPAIR", "reason": "OOS Sharpe is only 0.119 over roughly 636 trading days, OOS cumulative return is only 1.45%, and marginal portfolio Sharpe is negative."},
    "CLUSTER_NEUTRAL_MEAN_REVERSION": {"status": "ARCHIVED", "reason": "Negative full-period and preliminary OOS returns."},
    "ASSET_LIGHT_COMPOUNDER": {"status": "ARCHIVED", "reason": "Negative full-period and preliminary OOS returns."},
    "FCF_REINVESTMENT_EFFICIENCY": {"status": "ARCHIVED", "reason": "Negative full-period and preliminary OOS returns."},
    "EARNINGS_QUALITY_VALUE_SPREAD": {"status": "REPAIR", "reason": "Preliminary OOS return is negative and net Sharpe is below 0.25."},
    "CASH_CONVERSION_IMPROVEMENT": {"status": "REPAIR", "reason": "Negative net return, low Sharpe, and negative 2x-cost result."},
    "HIGH_CONVICTION_FILING_DRIFT_V2": {"status": "REPAIR", "reason": "Monthly shared panel does not prove exact event-timestamp execution."},
    "CASH_FLOW_INFLECTION_CONTINUATION": {"status": "REPAIR", "reason": "Strong diagnostic evidence, but monthly shared panel does not prove exact event-timestamp execution."},
    "BALANCE_SHEET_REPAIR_AFTER_STRESS": {"status": "ARCHIVED", "reason": "Negative full-period and preliminary OOS returns."},
}

EVENT_PANEL_CANDIDATE_IDS: tuple[str, ...] = (
    "CASH_FLOW_INFLECTION_CONTINUATION", "HIGH_CONVICTION_FILING_DRIFT_V2", "HEDGED_RESIDUAL_MOMENTUM_V3",
    "POST_FILING_MARGIN_ACCELERATION", "POST_FILING_CASH_FLOW_SURPRISE", "DEBT_REDUCTION_EVENT_DRIFT",
    "FCF_INFLECTION_QUALITY", "PROFITABILITY_TURNAROUND_MATCHED_CONTROL",
)

EVENT_PANEL_SELECTION_STATUS: dict[str, dict[str, str]] = {
    "CASH_FLOW_INFLECTION_CONTINUATION": {"status": "ARCHIVED", "reason": "Exact event-panel net, OOS, Sharpe, 2x-cost, and delayed-execution results are negative."},
    "HIGH_CONVICTION_FILING_DRIFT_V2": {"status": "ARCHIVED", "reason": "Exact event-panel net, OOS, 2x-cost, and delayed-execution results are negative."},
    "HEDGED_RESIDUAL_MOMENTUM_V3": {"status": "REPAIR", "reason": "Realized beta is controlled, but full-period net, Sharpe, 2x-cost, and delayed-execution results are negative."},
    "POST_FILING_MARGIN_ACCELERATION": {"status": "REPAIR", "reason": "Strong diagnostic results, but average eligible event cross-section is below 20."},
    "POST_FILING_CASH_FLOW_SURPRISE": {"status": "ACTIVE", "reason": "Passed every strict event-panel challenge gate with positive OOS, robustness, coverage, and portfolio-value evidence."},
    "DEBT_REDUCTION_EVENT_DRIFT": {"status": "ARCHIVED", "reason": "Negative full-period and OOS evidence with inadequate event coverage."},
    "FCF_INFLECTION_QUALITY": {"status": "ARCHIVED", "reason": "Negative full-period result, near-zero OOS, and inadequate event coverage."},
    "PROFITABILITY_TURNAROUND_MATCHED_CONTROL": {"status": "ARCHIVED", "reason": "Negative full-period/OOS evidence, inadequate event coverage, and concentration risk; CAUSAL_INSPIRED_NOT_CAUSAL_PROOF."},
}

WORLDQUANT_ALPHA_SELECTION_STATUS: dict[str, dict[str, str]] = {
    "WQ_ALPHA_018": {
        "status": "ACTIVE",
        "reason": (
            "Passed the locked strict challenge gate with positive net/OOS, "
            "2x-cost, delayed-execution, low-correlation, and marginal-Sharpe evidence."
        ),
    },
}

C3A2_SPECS: tuple[StrategySpec, ...] = (
    StrategySpec("C3A2_001", "c3a2_001_short_term_reversal_5d_v1", "Short-Term Reversal 5D",
                 "Fade 5-day moves; long recent losers and short recent winners.", short_term_reversal_5d, 20),
    StrategySpec("C3A2_002", "c3a2_002_low_realized_volatility_60d_v1", "Low Realized Volatility 60D",
                 "Long lower 60-day realized volatility.", low_realized_volatility_60d, 20),
    StrategySpec("C3A2_003", "c3a2_003_low_market_beta_60d_v1", "Low Market Beta 60D",
                 "Long lower trailing market beta.", low_market_beta_60d, 20, require_beta_history=True),
    StrategySpec("C3A2_004", "c3a2_004_medium_term_reversal_22d_v1", "Medium-Term Reversal 22D",
                 "Contrarian signal over roughly one trading month.", medium_term_reversal_22d, 20),
    StrategySpec("C3A2_005", "c3a2_005_low_idiosyncratic_volatility_60d_v1", "Low Idiosyncratic Volatility 60D",
                 "Long lower residual volatility after removing market movement.", low_idiosyncratic_volatility_60d, 20),
    StrategySpec("C3A2_006", "c3a2_006_distance_from_200dma_v1", "Distance From 200D MA",
                 "Long names below the 200-day average; short extended names.", distance_from_200dma, 20),
    StrategySpec("C3A2_007", "c3a2_007_low_intraday_range_volatility_v1", "Low Intraday Range Volatility",
                 "Long names with lower normalized daily high-low range.", low_intraday_range_volatility, 20),
    StrategySpec("C3A2_008", "c3a2_008_slow_momentum_9_1_v1", "Slow Momentum 9-1",
                 "Long stronger 9-1 momentum; short weaker momentum.", slow_momentum_9_1, 20),
    StrategySpec("C3A2_009", "c3a2_009_high_log_dollar_volume_63d_v1", "High Log Dollar Volume 63D",
                 "Long higher trailing dollar volume; short lower-liquidity names.",
                 high_log_dollar_volume_63d, 20),
)

# Pre-registered members that failed the positive-Sharpe gate but remain backtested for reference.
FAILED_PLATFORM_MEMBER_IDS: tuple[str, ...] = ("C3A2_001",)

C3A2_IDS = tuple(spec.strategy_id for spec in C3A2_SPECS)

# Deprecated historical pre-registration list. Runtime Combined Portfolio membership
# is derived only via eligible_composite_constituent_ids() — never this tuple.
DEPRECATED_HISTORICAL_PLATFORM_MEMBER_IDS: tuple[str, ...] = (
    "C2A2_002",
    "C2A2_020",
    "C2B2_004",
    "C3A1_002",
    "C3A1_003",
    "C3A1_006",
    "C3A1_008",
    "C3A1_009",
    "C3A1_011",
    "C3A1_012",
    "C3A1_013",
    "C3A1_017",
    "C3A2_002",
    "C3A2_003",
    "C3A2_004",
    "C3A2_005",
    "C3A2_006",
    "C3A2_007",
    "C3A2_008",
    "C3A2_009",
)

REFERENCE_ONLY_IDS: tuple[str, ...] = tuple(
    strategy_id for strategy_id in C3A1_IDS if strategy_id not in DEPRECATED_HISTORICAL_PLATFORM_MEMBER_IDS
)

# Additional backtested candidates eligible for in-sample composite replacement screening.
REPLACEMENT_CANDIDATE_IDS: tuple[str, ...] = ("C2B2_003", "C2A2_004")

RAPID_ACTIVE_UNDERLYING_IDS = (
    DEPRECATED_HISTORICAL_PLATFORM_MEMBER_IDS + REFERENCE_ONLY_IDS + FAILED_PLATFORM_MEMBER_IDS
)
RAPID_BACKTEST_IDS: tuple[str, ...] = tuple(
    dict.fromkeys(RAPID_ACTIVE_UNDERLYING_IDS + REPLACEMENT_CANDIDATE_IDS)
)

SPEC_BY_ID: dict[str, StrategySpec] = {
    C2A2_002_SPEC.strategy_id: C2A2_002_SPEC,
    C2A2_004_SPEC.strategy_id: C2A2_004_SPEC,
    C2A2_020_SPEC.strategy_id: C2A2_020_SPEC,
    C2B2_004_SPEC.strategy_id: C2B2_004_SPEC,
    C2B2_003_SPEC.strategy_id: C2B2_003_SPEC,
    **{spec.strategy_id: spec for spec in C3A1_SPECS},
    **{spec.strategy_id: spec for spec in C3A2_SPECS},
}

ALL_RAPID_SPECS: tuple[StrategySpec, ...] = tuple(
    SPEC_BY_ID[strategy_id] for strategy_id in RAPID_BACKTEST_IDS if strategy_id in SPEC_BY_ID
)
