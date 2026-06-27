# Strategy Factory Hardcode Audit Phase 3A

Date: 2026-06-26

## Summary Verdict

Strategy Factory is not ready for automation or a second material without a Phase 3B de-hardcode pass.

The active dashboard entrypoint is `dashboard/index.html`, which loads `dashboard/foundation-app.js`. The current active dashboard count and Command Center rendering have dynamic Phase 2 overlay logic, but several static data snapshots and legacy dashboard code still encode the old 16/17 strategy world.

More importantly, the Strategy Factory research pipeline is still materially copper-dependent in several generic-looking modules. Variant generation always emits six copper/commodity variants, current-run backtesting explicitly blocks non-copper/non-commodity specs, variant evaluation dispatches on fixed copper variant IDs, and ranking applies copper/COPX/XME-specific scoring rules. These are acceptable as historical Gate 2-4 prototype outputs, but dangerous if treated as generic Strategy Factory behavior.

Safe to proceed to automation now: **No**.

## Searched Terms

- `copper`
- `COPX`
- `XME`
- `controlled_copper_strategy_material`
- `Copper Equity Proxy Trend`
- `commodity`
- fixed active count `17`
- fixed ordinary active count `16`
- fixed Combined constituent count
- fixed strategy IDs
- hardcoded strategy names
- hardcoded top contributors / detractors
- hardcoded family mix
- hardcoded current run id `SF_RUN_20260626T135231Z_37A53397`
- logic that always selects the copper run/material/variant

## Search Scope And Files Inspected

Broad searches covered 414 source, dashboard, test, config, data, and documentation files after excluding `.git`, `output`, caches, and `__pycache__`.

Focused inspection covered:

- `dashboard/index.html`
- `dashboard/foundation-app.js`
- `dashboard/app.js`
- `dashboard/data/canonical_operational.json`
- `dashboard/data/shadow_live_bundle.json`
- `dashboard/data/performance/paper_portfolio_daily.json`
- `src/strategies/strategy_factory_data.py`
- `src/strategies/strategy_factory_runner.py`
- `src/strategies/strategy_factory_variants.py`
- `src/strategies/strategy_factory_variant_evaluation.py`
- `src/strategies/strategy_factory_variant_ranking.py`
- `src/strategies/strategy_factory_intelligence.py`
- `src/strategies/strategy_factory_plugin.py`
- `scripts/verify_strategy_factory_operator_view.py`
- `tests/test_strategy_factory_admission_flow.py`
- `tests/test_strategy_factory_variant_review_dashboard.py`
- Strategy Factory closeout/gate/audit docs under `docs/`
- release docs such as `README.md`, `RELEASE_NOTES.md`, `BOSS_REVIEW_SUMMARY.md`, and `LOCAL_QA_REPORT.md`

## Allowed Example Content

These files contain copper or fixed-count language as documentation, historical release notes, fixture text, or controlled example evidence:

- `docs/STRATEGY_FACTORY_V0_CLOSEOUT.md`
- `docs/STRATEGY_FACTORY_GATE1_REPRODUCIBILITY.md`
- `docs/STRATEGY_FACTORY_GATE2_VARIANT_GENERATION.md`
- `docs/STRATEGY_FACTORY_GATE3A_SINGLE_VARIANT_EVALUATION.md`
- `docs/STRATEGY_FACTORY_GATE3B_ALL_VARIANT_EVALUATION.md`
- `docs/STRATEGY_FACTORY_LOGIC_AUDIT_V1.md`
- `docs/STRATEGY_FACTORY_FUNCTIONALITY_AUDIT.md`
- `README.md`
- `RELEASE_NOTES.md`
- `BOSS_REVIEW_SUMMARY.md`
- `LOCAL_QA_REPORT.md`
- `tests/test_strategy_factory_variant_review_dashboard.py`
- `tests/test_strategy_factory_admission_flow.py`

Notes:

- The Strategy Factory docs correctly describe the copper run as the V0 controlled example.
- The tests use copper/COPX/XME fixtures to prove existing behavior; that is acceptable for regression coverage.
- Release docs still describe the pre-Phase 2 16/17 universe. That is stale but not runtime logic.

## Risky Prototype Defaults

These are acceptable short-term but should be isolated before Phase 4 automation:

- `src/strategies/strategy_factory_data.py`
  - `V0_SYMBOLS` is the V0 proxy set: `CPER`, `JJC`, `DBB`, `COPX`, `XME`, and risk proxies.
  - `DEFAULT_PROXY_MAPPING` maps `copper` and commodity benchmarks.
  - `infer_data_requirements(...)` returns a copper/commodity requirement when the material text contains copper/commodity terms.
  - This is acceptable as V0 data population scope, but generic data requirements need a strategy-type registry before broader automation.

- `scripts/verify_strategy_factory_operator_view.py`
  - Smoke checks still assert current copper strict admission remains blocked.
  - This is fine for the current controlled smoke, but Phase 3B needs a non-copper smoke path.

- `dashboard/data/canonical_operational.json`
  - Encodes current historical snapshot counts such as `current_n: 17`, `current_underlying_n: 16`, and Combined constituent counts.
  - Phase 2 overlay can display the activated Strategy Factory row dynamically, but the static snapshot remains old-state data.

- `dashboard/data/shadow_live_bundle.json`
  - Encodes `configured_strategy_count: 17`, `previous_active_count: 16`, and `current_active_count: 17`.
  - This is a snapshot artifact, not a generic Strategy Factory rule, but downstream propagation must stop treating it as final source of truth once activated strategies are promoted.

- `dashboard/data/performance/paper_portfolio_daily.json`
  - Contains `row_count: 16`, which is an existing paper performance artifact.
  - It should not be overwritten by Phase 3; Phase 4 should handle dynamic recomputation.

## Dangerous Hardcodes

These are generic-looking pipeline/dashboard paths that can make Strategy Factory behave like a copper-only demo or old fixed-count workstation.

### 1. Current-run backtest runner is copper/commodity-only

File: `src/strategies/strategy_factory_runner.py`

Findings:

- `COPPER_SYMBOLS` and `BENCHMARK_SYMBOLS` drive provider series selection.
- `_load_price_series(...)`, `_provider_market_series(...)`, and `_run_copper_backtest(...)` use copper-specific field names and assumptions.
- Non-copper/non-commodity specs are explicitly blocked with: `V0 runner only supports copper/commodities selected-run test specs.`
- Completed backtest artifacts hardcode `Current Run Copper Momentum Volatility Filter V0`.

Risk:

- A non-copper material can be ingested but cannot run the current-run evidence pipeline through this runner without being blocked or mislabeled.

### 2. Variant generation always emits copper variants

File: `src/strategies/strategy_factory_variants.py`

Findings:

- `_build_variants(...)` returns six fixed variants:
  - `COPPER_CPER_MOMENTUM_21_63_V1`
  - `COPPER_CPER_MOMENTUM_VOL_FILTER_V1`
  - `COPPER_CPER_DBC_RELATIVE_STRENGTH_V1`
  - `COPPER_CPER_UUP_USD_FILTER_V1`
  - `COPPER_EQUITY_PROXY_TREND_COPX_XME_V1`
  - `COMMODITY_BASKET_REGIME_FILTER_V1`
- The function does not branch on the classified strategy type except to copy metadata into the registry.

Risk:

- Any material that reaches Gate 2 would still receive copper/commodity variants.

### 3. Variant evaluation dispatches on fixed copper variant IDs

File: `src/strategies/strategy_factory_variant_evaluation.py`

Findings:

- Default `VARIANT_ID` is `COPPER_CPER_MOMENTUM_21_63_V1`.
- `_variant_signal(...)` dispatches on exact copper variant IDs.
- The unsupported path raises `Unsupported Gate 3B variant signal`.
- Signals hardcode CPER, DBC, UUP, COPX, XME, and SPY logic.

Risk:

- Non-copper variants cannot be evaluated through the same contract without new branch logic.

### 4. Ranking applies copper/COPX/XME-specific scoring

File: `src/strategies/strategy_factory_variant_ranking.py`

Findings:

- Data quality score applies a specific COPX/XME penalty.
- Economic logic score is a fixed map keyed by the six copper variant IDs.
- Report text says it ranks "six evaluated copper variants".
- Risk penalty text references "COPX/XME miner beta risk".

Risk:

- Ranking evidence scores are not generic. A non-copper candidate would receive fallback economic logic or irrelevant copper-oriented penalties.

### 5. Variant review payload contains copper-specific gating copy

File: `src/strategies/strategy_factory_plugin.py`

Finding:

- Variant review gating reason says: `All current copper variants have candidate_allowed=false; casual admission is disabled.`

Risk:

- Dashboard/API payload language would be wrong for non-copper runs.

### 6. Legacy dashboard contains fixed-count and commodity demo logic

File: `dashboard/app.js`

Findings:

- `configured_strategy_count || 16`
- `previous_active_count || 16`
- `current_active_count || 17`
- hardcoded candidate row: `Commodity Inflation Shock`
- `checks.slice(0, 16)`

Current status:

- `dashboard/index.html` loads `foundation-app.js`, not `app.js`.

Risk:

- If `dashboard/app.js` is still served by any legacy path, it preserves fixed-count and commodity demo assumptions. If it is unused, classify as legacy cleanup, not active runtime blocker.

## Dashboard Fixed-17 Assessment

Active dashboard file: `dashboard/foundation-app.js`.

Findings:

- The active Command Center functions are dynamic:
  - `contributors(c)` sorts current strategy rows by P&L.
  - `styleMix(c)` computes family mix from active strategy rows.
  - `phase2UniverseCounts(c)` and `phase2ApplyUniverseInventory(c)` compute active, unallocated, allocated, candidate, and optimizer counts from rows.
- No active generic Command Center logic was found that assumes exactly 17 strategies.

Remaining risk:

- Static data snapshots still encode the 16/17 pre-Strategy-Factory universe.
- Legacy `dashboard/app.js` contains fixed-count fallbacks.

## Is Factory Currently Copper-Dependent?

Yes for the current evidence pipeline beyond intake/admission.

The intake, portfolio candidate, activation, and dashboard review plumbing can carry a generic Strategy Factory artifact. But Gate 2 variant generation, Gate 3 variant evaluation, Gate 4 ranking, and current-run backtest evidence are still materially copper/commodity-specific.

## Recommended Phase 3B Fixes

1. Introduce a strategy-type variant generator registry.
   - Change `src/strategies/strategy_factory_variants.py`.
   - Generate variants from `strategy_type_classification.json`, material themes, and available data instead of always generating copper variants.

2. Replace copper-only current-run runner with a spec-driven rule runner.
   - Change `src/strategies/strategy_factory_runner.py`.
   - Inputs should be symbols, benchmark, signal formula/rule template, rebalance frequency, cost assumption, and data requirements.
   - Preserve explicit blocking for unsupported specs.

3. Replace fixed variant-ID evaluation dispatch with declarative signal evaluation.
   - Change `src/strategies/strategy_factory_variant_evaluation.py`.
   - Use fields in `variant_spec.json` or a small rule-template registry.

4. Make ranking scoring generic with optional strategy-type penalties.
   - Change `src/strategies/strategy_factory_variant_ranking.py`.
   - Move COPX/XME/miner-beta penalties into a commodity/equity-proxy rule, not a global hardcode.

5. Remove copper-specific dashboard/API copy.
   - Change `src/strategies/strategy_factory_plugin.py`.
   - Replace "All current copper variants..." with run/strategy-type aware gating copy.

6. Add a second non-copper fixture and smoke path.
   - Change `tests/test_strategy_factory_variant_review_dashboard.py`.
   - Change `tests/test_strategy_factory_admission_flow.py` only where copper fixture naming leaks into generic state-machine tests.
   - Change `scripts/verify_strategy_factory_operator_view.py` to support a non-copper smoke scenario.

7. Isolate or retire legacy dashboard fixed-count code.
   - Inspect whether any route still serves `dashboard/app.js`.
   - If unused, document or remove later.
   - If used, replace fixed 16/17 fallbacks and hardcoded commodity candidate text.

8. Treat static snapshot counts as historical inputs, not dynamic registry truth.
   - Do not manually edit `dashboard/data/canonical_operational.json` or `dashboard/data/shadow_live_bundle.json` in Phase 3B unless the data-generation contract is updated.
   - Phase 4 should regenerate dynamic recommendation/rebalance artifacts.

## Phase 3B Files To Change

- `src/strategies/strategy_factory_variants.py`
- `src/strategies/strategy_factory_runner.py`
- `src/strategies/strategy_factory_variant_evaluation.py`
- `src/strategies/strategy_factory_variant_ranking.py`
- `src/strategies/strategy_factory_plugin.py`
- `src/strategies/strategy_factory_data.py`
- `src/strategies/strategy_factory_intelligence.py`
- `scripts/verify_strategy_factory_operator_view.py`
- `tests/test_strategy_factory_variant_review_dashboard.py`
- `tests/test_strategy_factory_admission_flow.py`
- `dashboard/app.js` if still reachable

Potential data-generation targets for later phases:

- `dashboard/data/canonical_operational.json`
- `dashboard/data/shadow_live_bundle.json`
- `dashboard/data/performance/paper_portfolio_daily.json`

## Final Gate

Proceed to automation now: **No**.

Proceed to Phase 3B de-hardcode: **Yes**.
