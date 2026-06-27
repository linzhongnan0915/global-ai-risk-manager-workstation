# Full No-Hardcode Sweep - Strategy Factory and Dashboard

Generated: 2026-06-27

## Files Searched

- `src/strategies/strategy_factory_data.py`
- `src/strategies/strategy_factory_plugin.py`
- `src/strategies/strategy_factory_runner.py`
- `src/strategies/strategy_factory_variants.py`
- `src/strategies/strategy_factory_variant_evaluation.py`
- `src/strategies/strategy_factory_variant_ranking.py`
- `src/strategies/strategy_factory_readiness.py`
- `src/strategies/strategy_factory_us_stock_backtest.py`
- `src/strategies/strategy_factory_admission.py`
- `dashboard/foundation-app.js`
- `dashboard/app.js`
- `scripts/run_workstation_server.py`
- Strategy Factory pytest files under `tests/`

## Dangerous Hardcodes Found

- `dashboard/app.js` used fixed shadow-live count fallbacks: configured `16`, previous active `16`, and current active `17`.
- `dashboard/foundation-app.js` contained old display text `Correct 1/17 capital basis`.
- Strategy Factory evidence UI rendered the long raw data quality enum directly instead of compact operator badges.
- Low-vol turnover artifact stored `turnover = 0.0056770833333333335`, an average daily two-way-derived value, which displayed as `0.0x/year`.

## Dangerous Hardcodes Fixed

- Removed fixed `16` and `17` count fallbacks from `dashboard/app.js`; missing counts now render as `n/a`.
- Replaced the fixed `1/17` dashboard wording with `Current registry capital basis`.
- Added `factoryDataQualityBadges` so `PUBLIC_FALLBACK_PROTOTYPE_NOT_PIT_NOT_SURVIVORSHIP_BIAS_FREE` renders as compact badges: `PUBLIC FALLBACK`, `NOT PIT`, `NOT SURVIVORSHIP-FREE`, with the raw value only in tooltip.
- Changed U.S. stock backtest turnover to documented one-way turnover:
  `turnover_t = 0.5 * sum(abs(w_t - w_t-1))`.
- Added turnover lineage fields: `turnover_value`, `turnover_unit`, `turnover_frequency`, `turnover_definition`, `average_rebalance_turnover`, `annualized_turnover`, `cumulative_turnover`, and `rebalance_frequency_per_year`.
- Updated dashboard turnover display to prefer explicit artifact units before falling back to legacy cumulative turnover annualization.

## Allowed Examples and Fixtures Left Alone

- Copper names, `COPX`, `XME`, ETF rotation names, U.S. momentum names, and low-vol names remain in tests and theme-specific variant generators/evaluators.
- Copper/ETF/U.S. stock variant IDs remain inside theme-dispatched strategy variant logic.
- Display labels such as `#000018` remain in consent/identity tests as display labels only, not canonical IDs.

## Risky Prototype Fallbacks Remaining

- `strategy_factory_data.py` still contains copper proxy mapping for commodity theme data lookup.
- `strategy_factory_us_stock_backtest.py` still has a deterministic large-cap fallback when no security master is available; it is labeled with public fallback, not point-in-time, and not survivorship-free limitations.
- `strategy_factory_readiness.py` still names prototype U.S. stock extracted themes with theme-specific screen labels. Unknown material remains `Review Required - Unknown Material`.
- Public Yahoo fallback remains prototype evidence only; it is not institutional data evidence.

## Low Vol Turnover Verdict

- Source artifact: `output/strategy_factory/runs/SF_RUN_ANTI_HARDCODE_LOW_VOL_DEFENSIVE/variants/US_STOCK_LOW_VOL_63D_TOP20_V1/evaluation/variant_metrics.json`
- Raw before fix: `turnover = 0.0056770833333333335`
- Field meaning before fix: average daily two-way-derived turnover, not exact zero, not annualized.
- Corrected after fix: `annualized_turnover = 0.7153125x/year`
- Average rebalance turnover after fix: `0.07171052631578945`
- Rebalance frequency after fix: `9.975000000000001/year`
- Formula/unit: one-way annualized multiple from monthly rebalance weights.
- Verdict: `0.0x/year` was a bug caused by ambiguous artifact units plus display rounding.

## Automation Status

Automation remains blocked for this phase. This sweep changed evidence lineage, display wording, and hardcode blockers only. It did not build automation, change portfolio activation state machine, change NAV/P&L, or fabricate ML.

## Remaining Blockers Before Automation

- Institutional point-in-time and survivorship-free data are still missing for public fallback U.S. stock evidence.
- Low-vol and momentum U.S. stock ML evidence remains missing by design.
- Candidate activation still requires explicit user confirmation and must keep smoke/test records out of the real active universe.
