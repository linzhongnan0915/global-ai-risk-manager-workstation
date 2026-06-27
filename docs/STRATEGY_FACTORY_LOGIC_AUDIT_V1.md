# Strategy Factory Logic Audit V1 - SF_RUN_20260626T135231Z_37A53397

Status: COMPLETED

This is an audit of existing Strategy Factory artifacts. It did not run new backtests, ML, ranking, dashboard work, deployment, live trading, or paper-ledger mutation.

## 1. Material To Strategy Type
- Strategy type: `commodity trend / macro proxy`
- Confidence: `HIGH`
- Material summary path: `D:\Global_Ai\release_global_ai_risk_manager_workstation\output\strategy_factory\runs\SF_RUN_20260626T135231Z_37A53397\material_summary.json`
- Trigger keywords/themes: ETF proxy, commodities, commodity/macro keywords found in selected material or test spec, momentum, risk regime or volatility language found, trend or momentum language found, volatility
- Rule-based logic: Key themes and signal ideas came from rule-based material detectors. commodity/macro, trend/momentum, ETF proxy, and volatility themes map deterministically to commodity trend / macro proxy.
- Inferred logic: USD proxy and equity/miner proxy extensions are economic inferences from copper macro/proxy context, not direct proof of alpha.
- Limitations: Material is METHOD_REFERENCE_ONLY, not a validated alpha paper. Extracted text is short; conclusions depend on controlled material themes. Classification is transparent and heuristic, not a causal proof.

## 2. Strategy Type To Variants
### COPPER_CPER_MOMENTUM_21_63_V1
- Name: CPER Momentum 21/63
- Why generated: Create the simplest copper proxy trend baseline before adding filters.
- Material mapping: Maps to material themes: ETF proxy, commodities, momentum.
- Economic hypothesis: Copper ETF trends may persist over short and medium horizons.
- Data/proxy required: CPER, DBC
- Distinctness: Pure CPER absolute momentum; no volatility, USD, benchmark-relative, or equity-proxy filter.

### COPPER_CPER_MOMENTUM_VOL_FILTER_V1
- Name: CPER Momentum + Volatility Filter
- Why generated: Test whether risk-regime language should gate copper momentum exposure.
- Material mapping: Maps to material themes: momentum and volatility.
- Economic hypothesis: Copper momentum may be more reliable when realized volatility is not elevated.
- Data/proxy required: CPER, DBC
- Distinctness: Adds a volatility filter to the CPER momentum baseline.

### COPPER_CPER_DBC_RELATIVE_STRENGTH_V1
- Name: CPER vs DBC Relative Strength
- Why generated: Separate copper-specific strength from broad commodity beta.
- Material mapping: Maps to material themes: ETF proxy, commodities, momentum.
- Economic hypothesis: Copper exposure should be favored only when it outperforms the broad commodity basket.
- Data/proxy required: CPER, DBC
- Distinctness: Uses CPER return relative to DBC instead of absolute CPER trend only.

### COPPER_CPER_UUP_USD_FILTER_V1
- Name: CPER Momentum + UUP/USD Filter
- Why generated: Test whether USD macro pressure changes copper trend quality.
- Material mapping: Maps to material themes: commodities and macro proxy; USD filter is inferred from copper macro sensitivity.
- Economic hypothesis: Copper trend may be stronger when USD strength is not a headwind.
- Data/proxy required: CPER, DBC, UUP
- Distinctness: Adds a UUP/USD macro filter not present in the other CPER-only variants.

### COPPER_EQUITY_PROXY_TREND_COPX_XME_V1
- Name: COPX/XME Copper Equity Proxy Trend
- Why generated: Test listed copper/miner equity proxies as an alternate expression of copper trend.
- Material mapping: Maps to ETF proxy language; miner/equity expression is an implementation inference.
- Economic hypothesis: Copper-linked equities may capture copper regime sensitivity but add equity beta.
- Data/proxy required: COPX, XME, SPY
- Distinctness: Uses COPX/XME with SPY benchmark instead of CPER/DBC commodity proxy exposure.

### COMMODITY_BASKET_REGIME_FILTER_V1
- Name: Commodity Basket Regime Filter
- Why generated: Test whether broad commodity regime confirmation improves copper proxy trend.
- Material mapping: Maps to material themes: commodities, ETF proxy, momentum.
- Economic hypothesis: Copper exposure may be more robust when the broad commodity basket is also trending.
- Data/proxy required: CPER, DBC
- Distinctness: Uses DBC as a regime filter rather than only as benchmark comparison.

## 3. Variant To Features
### COPPER_CPER_MOMENTUM_21_63_V1
- `momentum_21d`: Short-term continuation Measures: Short-term continuation. Expected direction: Positive momentum should increase long exposure. Source: local CPER proxy data. Leakage risk: LOW when computed from current/prior dates only; leakage check requires target date after feature date and chronological split. Proxy-only: `True`.
- `momentum_63d`: Medium-term trend persistence Measures: Medium-term trend persistence. Expected direction: Positive momentum should increase long exposure. Source: local CPER proxy data. Leakage risk: LOW when computed from current/prior dates only; leakage check requires target date after feature date and chronological split. Proxy-only: `True`.
- `commodity_basket_proxy_dbc`: Broad commodity beta and benchmark context Measures: Broad commodity beta and benchmark context. Expected direction: Positive DBC regime may support copper exposure. Source: local DBC proxy data. Leakage risk: LOW when computed from current/prior dates only; leakage check requires target date after feature date and chronological split. Proxy-only: `True`.

### COPPER_CPER_MOMENTUM_VOL_FILTER_V1
- `momentum_63d`: Medium-term trend persistence Measures: Medium-term trend persistence. Expected direction: Positive momentum should increase long exposure. Source: local CPER proxy data. Leakage risk: LOW when computed from current/prior dates only; leakage check requires target date after feature date and chronological split. Proxy-only: `True`.
- `realized_volatility_21d`: Recent risk regime Measures: Recent risk regime. Expected direction: Elevated volatility should reduce or block exposure. Source: local daily return/equity curve artifacts. Leakage risk: LOW when computed from current/prior dates only; leakage check requires target date after feature date and chronological split. Proxy-only: `True`.
- `realized_volatility_252d`: Longer volatility baseline Measures: Longer volatility baseline. Expected direction: Current volatility below baseline should support exposure. Source: local daily return/equity curve artifacts. Leakage risk: LOW when computed from current/prior dates only; leakage check requires target date after feature date and chronological split. Proxy-only: `True`.
- `drawdown`: Trend break / risk state Measures: Trend break / risk state. Expected direction: Deeper drawdown should reduce confidence. Source: local daily return/equity curve artifacts. Leakage risk: LOW when computed from current/prior dates only; leakage check requires target date after feature date and chronological split. Proxy-only: `True`.

### COPPER_CPER_DBC_RELATIVE_STRENGTH_V1
- `cper_momentum_63d`: CPER medium-term trend Measures: CPER medium-term trend. Expected direction: Positive trend should support CPER exposure. Source: local CPER proxy data. Leakage risk: LOW when computed from current/prior dates only; leakage check requires target date after feature date and chronological split. Proxy-only: `True`.
- `dbc_momentum_63d`: Broad commodity medium-term trend Measures: Broad commodity medium-term trend. Expected direction: Positive DBC trend should support commodity exposure. Source: local DBC proxy data. Leakage risk: LOW when computed from current/prior dates only; leakage check requires target date after feature date and chronological split. Proxy-only: `True`.
- `relative_strength_vs_dbc`: Copper-specific strength versus broad commodities Measures: Copper-specific strength versus broad commodities. Expected direction: Positive relative strength should support exposure. Source: local DBC proxy data. Leakage risk: LOW when computed from current/prior dates only; leakage check requires target date after feature date and chronological split. Proxy-only: `True`.

### COPPER_CPER_UUP_USD_FILTER_V1
- `cper_momentum_63d`: CPER medium-term trend Measures: CPER medium-term trend. Expected direction: Positive trend should support CPER exposure. Source: local CPER proxy data. Leakage risk: LOW when computed from current/prior dates only; leakage check requires target date after feature date and chronological split. Proxy-only: `True`.
- `uup_momentum_63d`: USD trend proxy Measures: USD trend proxy. Expected direction: Positive UUP momentum should reduce copper exposure. Source: local UUP proxy data. Leakage risk: LOW when computed from current/prior dates only; leakage check requires target date after feature date and chronological split. Proxy-only: `True`.
- `usd_filter`: Binary USD headwind filter Measures: Binary USD headwind filter. Expected direction: Filter should block when USD trend is unfavorable. Source: local UUP proxy data. Leakage risk: LOW when computed from current/prior dates only; leakage check requires target date after feature date and chronological split. Proxy-only: `True`.
- `relative_strength_vs_dbc`: Copper-specific strength versus broad commodities Measures: Copper-specific strength versus broad commodities. Expected direction: Positive relative strength should support exposure. Source: local DBC proxy data. Leakage risk: LOW when computed from current/prior dates only; leakage check requires target date after feature date and chronological split. Proxy-only: `True`.

### COPPER_EQUITY_PROXY_TREND_COPX_XME_V1
- `copx_momentum_63d`: Copper miner trend Measures: Copper miner trend. Expected direction: Positive COPX momentum should support miner proxy exposure. Source: local COPX/XME/SPY proxy data. Leakage risk: LOW when computed from current/prior dates only; leakage check requires target date after feature date and chronological split. Proxy-only: `True`.
- `xme_momentum_63d`: Metals/mining trend Measures: Metals/mining trend. Expected direction: Positive XME momentum should support miner proxy exposure. Source: local COPX/XME/SPY proxy data. Leakage risk: LOW when computed from current/prior dates only; leakage check requires target date after feature date and chronological split. Proxy-only: `True`.
- `relative_strength_vs_spy`: Miner equity strength versus market beta Measures: Miner equity strength versus market beta. Expected direction: Positive relative strength should support exposure. Source: local COPX/XME/SPY proxy data. Leakage risk: LOW when computed from current/prior dates only; leakage check requires target date after feature date and chronological split. Proxy-only: `True`.
- `equity_beta_proxy`: Equity-market sensitivity Measures: Equity-market sensitivity. Expected direction: Higher equity beta increases implementation/admission risk. Source: local COPX/XME/SPY proxy data. Leakage risk: LOW when computed from current/prior dates only; leakage check requires target date after feature date and chronological split. Proxy-only: `True`.

### COMMODITY_BASKET_REGIME_FILTER_V1
- `cper_momentum_63d`: CPER medium-term trend Measures: CPER medium-term trend. Expected direction: Positive trend should support CPER exposure. Source: local CPER proxy data. Leakage risk: LOW when computed from current/prior dates only; leakage check requires target date after feature date and chronological split. Proxy-only: `True`.
- `dbc_momentum_126d`: Broad commodity regime trend Measures: Broad commodity regime trend. Expected direction: Positive DBC regime should support commodity exposure. Source: local DBC proxy data. Leakage risk: LOW when computed from current/prior dates only; leakage check requires target date after feature date and chronological split. Proxy-only: `True`.
- `commodity_regime_filter`: Broad commodity confirmation Measures: Broad commodity confirmation. Expected direction: Positive DBC regime should support exposure. Source: local daily return/equity curve artifacts. Leakage risk: LOW when computed from current/prior dates only; leakage check requires target date after feature date and chronological split. Proxy-only: `True`.
- `drawdown`: Trend break / risk state Measures: Trend break / risk state. Expected direction: Deeper drawdown should reduce confidence. Source: local daily return/equity curve artifacts. Leakage risk: LOW when computed from current/prior dates only; leakage check requires target date after feature date and chronological split. Proxy-only: `True`.

## 4. Variant To Model Plan
### COPPER_CPER_MOMENTUM_21_63_V1
- Ridge: Ridge was used because it is interpretable and regularizes unstable coefficients on correlated momentum/risk features.
- Logistic: Logistic regression was used for next-period direction because the target is binary up/down.
- Chronological split: Chronological split was used because financial time series cannot be randomly shuffled without leakage risk.
- Target definition: next_period_net_return; direction model uses next_period_direction
- Sample count: 2066
- Train dates: {'end': '2024-01-02', 'start': '2018-04-05'}
- Test dates: {'end': '2026-06-24', 'start': '2024-01-03'}
- Blocked nonlinear models: [{"model": "random_forest_regressor", "reason": "sklearn unavailable: No module named 'sklearn'", "status": "BLOCKED"}, {"model": "gradient_boosting_regressor", "reason": "sklearn unavailable: No module named 'sklearn'", "status": "BLOCKED"}]

### COPPER_CPER_MOMENTUM_VOL_FILTER_V1
- Ridge: Ridge was used because it is interpretable and regularizes unstable coefficients on correlated momentum/risk features.
- Logistic: Logistic regression was used for next-period direction because the target is binary up/down.
- Chronological split: Chronological split was used because financial time series cannot be randomly shuffled without leakage risk.
- Target definition: next_period_net_return; direction model uses next_period_direction
- Sample count: 2066
- Train dates: {'end': '2024-01-02', 'start': '2018-04-05'}
- Test dates: {'end': '2026-06-24', 'start': '2024-01-03'}
- Blocked nonlinear models: [{"model": "random_forest_regressor", "reason": "sklearn unavailable: No module named 'sklearn'", "status": "BLOCKED"}, {"model": "gradient_boosting_regressor", "reason": "sklearn unavailable: No module named 'sklearn'", "status": "BLOCKED"}]

### COPPER_CPER_DBC_RELATIVE_STRENGTH_V1
- Ridge: Ridge was used because it is interpretable and regularizes unstable coefficients on correlated momentum/risk features.
- Logistic: Logistic regression was used for next-period direction because the target is binary up/down.
- Chronological split: Chronological split was used because financial time series cannot be randomly shuffled without leakage risk.
- Target definition: next_period_net_return; direction model uses next_period_direction
- Sample count: 2066
- Train dates: {'end': '2024-01-02', 'start': '2018-04-05'}
- Test dates: {'end': '2026-06-24', 'start': '2024-01-03'}
- Blocked nonlinear models: [{"model": "random_forest_regressor", "reason": "sklearn unavailable: No module named 'sklearn'", "status": "BLOCKED"}, {"model": "gradient_boosting_regressor", "reason": "sklearn unavailable: No module named 'sklearn'", "status": "BLOCKED"}]

### COPPER_CPER_UUP_USD_FILTER_V1
- Ridge: Ridge was used because it is interpretable and regularizes unstable coefficients on correlated momentum/risk features.
- Logistic: Logistic regression was used for next-period direction because the target is binary up/down.
- Chronological split: Chronological split was used because financial time series cannot be randomly shuffled without leakage risk.
- Target definition: next_period_net_return; direction model uses next_period_direction
- Sample count: 2066
- Train dates: {'end': '2024-01-02', 'start': '2018-04-05'}
- Test dates: {'end': '2026-06-24', 'start': '2024-01-03'}
- Blocked nonlinear models: [{"model": "random_forest_regressor", "reason": "sklearn unavailable: No module named 'sklearn'", "status": "BLOCKED"}, {"model": "gradient_boosting_regressor", "reason": "sklearn unavailable: No module named 'sklearn'", "status": "BLOCKED"}]

### COPPER_EQUITY_PROXY_TREND_COPX_XME_V1
- Ridge: Ridge was used because it is interpretable and regularizes unstable coefficients on correlated momentum/risk features.
- Logistic: Logistic regression was used for next-period direction because the target is binary up/down.
- Chronological split: Chronological split was used because financial time series cannot be randomly shuffled without leakage risk.
- Target definition: next_period_net_return; direction model uses next_period_direction
- Sample count: 2066
- Train dates: {'end': '2024-01-02', 'start': '2018-04-05'}
- Test dates: {'end': '2026-06-24', 'start': '2024-01-03'}
- Blocked nonlinear models: [{"model": "random_forest_regressor", "reason": "sklearn unavailable: No module named 'sklearn'", "status": "BLOCKED"}, {"model": "gradient_boosting_regressor", "reason": "sklearn unavailable: No module named 'sklearn'", "status": "BLOCKED"}]

### COMMODITY_BASKET_REGIME_FILTER_V1
- Ridge: Ridge was used because it is interpretable and regularizes unstable coefficients on correlated momentum/risk features.
- Logistic: Logistic regression was used for next-period direction because the target is binary up/down.
- Chronological split: Chronological split was used because financial time series cannot be randomly shuffled without leakage risk.
- Target definition: next_period_net_return; direction model uses next_period_direction
- Sample count: 2066
- Train dates: {'end': '2024-01-02', 'start': '2018-04-05'}
- Test dates: {'end': '2026-06-24', 'start': '2024-01-03'}
- Blocked nonlinear models: [{"model": "random_forest_regressor", "reason": "sklearn unavailable: No module named 'sklearn'", "status": "BLOCKED"}, {"model": "gradient_boosting_regressor", "reason": "sklearn unavailable: No module named 'sklearn'", "status": "BLOCKED"}]

## 5. Metrics / Robustness To Decision
### COPPER_CPER_MOMENTUM_21_63_V1
- Sharpe: `0.18797555450425887`
- Annual return: `0.017073868111016965`
- Max drawdown: `-0.2431117813045911`
- ML IC: `-0.029457468647307253`
- Hit rate: `0.7129032258064516`
- Robustness: `WATCH`
- Proxy penalty applied: `True`
- Candidate blocking rule: Candidate requires non-proxy-only data, strong performance, strong robustness, supportive ML, acceptable drawdown/risk, complete artifacts, and candidate_allowed true. Proxy-only data blocks Candidate unless an explicit future override is added.
- Final label: `Modify`
- Reason: Weak risk-adjusted performance or drawdown severity requires changes before broader testing.

### COPPER_CPER_MOMENTUM_VOL_FILTER_V1
- Sharpe: `0.473319762981505`
- Annual return: `0.05293687468074304`
- Max drawdown: `-0.1825006749982141`
- ML IC: `-0.017741892483290916`
- Hit rate: `0.8064516129032258`
- Robustness: `WATCH`
- Proxy penalty applied: `True`
- Candidate blocking rule: Candidate requires non-proxy-only data, strong performance, strong robustness, supportive ML, acceptable drawdown/risk, complete artifacts, and candidate_allowed true. Proxy-only data blocks Candidate unless an explicit future override is added.
- Final label: `Watch`
- Reason: Pipeline completed, but proxy-only data and incomplete robustness/ML evidence do not support Candidate status.

### COPPER_CPER_DBC_RELATIVE_STRENGTH_V1
- Sharpe: `0.16958202646722434`
- Annual return: `0.013983787923344648`
- Max drawdown: `-0.3122359288513692`
- ML IC: `0.045961689483938854`
- Hit rate: `0.6580645161290323`
- Robustness: `WATCH`
- Proxy penalty applied: `True`
- Candidate blocking rule: Candidate requires non-proxy-only data, strong performance, strong robustness, supportive ML, acceptable drawdown/risk, complete artifacts, and candidate_allowed true. Proxy-only data blocks Candidate unless an explicit future override is added.
- Final label: `Modify`
- Reason: Weak risk-adjusted performance or drawdown severity requires changes before broader testing.

### COPPER_CPER_UUP_USD_FILTER_V1
- Sharpe: `0.13409967422967378`
- Annual return: `0.008931446259359488`
- Max drawdown: `-0.29768075364892077`
- ML IC: `0.05913404119370836`
- Hit rate: `0.8564516129032258`
- Robustness: `WATCH`
- Proxy penalty applied: `True`
- Candidate blocking rule: Candidate requires non-proxy-only data, strong performance, strong robustness, supportive ML, acceptable drawdown/risk, complete artifacts, and candidate_allowed true. Proxy-only data blocks Candidate unless an explicit future override is added.
- Final label: `Modify`
- Reason: Weak risk-adjusted performance or drawdown severity requires changes before broader testing.

### COPPER_EQUITY_PROXY_TREND_COPX_XME_V1
- Sharpe: `0.90855170737167`
- Annual return: `0.1716954696818307`
- Max drawdown: `-0.25842056427756777`
- ML IC: `0.08283386108678262`
- Hit rate: `0.7580645161290323`
- Robustness: `WATCH`
- Proxy penalty applied: `True`
- Candidate blocking rule: Candidate requires non-proxy-only data, strong performance, strong robustness, supportive ML, acceptable drawdown/risk, complete artifacts, and candidate_allowed true. Proxy-only data blocks Candidate unless an explicit future override is added.
- Final label: `Watch`
- Reason: Pipeline completed, but proxy-only data and incomplete robustness/ML evidence do not support Candidate status.

### COMMODITY_BASKET_REGIME_FILTER_V1
- Sharpe: `0.28185245091018457`
- Annual return: `0.030587469451595073`
- Max drawdown: `-0.29464245319488014`
- ML IC: `-0.029870025921492682`
- Hit rate: `0.7838709677419354`
- Robustness: `WATCH`
- Proxy penalty applied: `True`
- Candidate blocking rule: Candidate requires non-proxy-only data, strong performance, strong robustness, supportive ML, acceptable drawdown/risk, complete artifacts, and candidate_allowed true. Proxy-only data blocks Candidate unless an explicit future override is added.
- Final label: `Watch`
- Reason: Pipeline completed, but proxy-only data and incomplete robustness/ML evidence do not support Candidate status.

## 6. Ranking Score
- Heuristic: `True`
- Disclaimer: The formula is a transparent heuristic for prototype ranking; it is not institutional validation or admission logic.
- Weights: `{"data_quality": 0.15, "economic_logic": 0.15, "ml": 0.15, "performance": 0.25, "risk_penalty": -0.1, "robustness": 0.2}`
- `performance_score`: Composite of Sharpe, annual return, max drawdown, and benchmark comparison.
- `robustness_score`: Overall robustness, cost sensitivity, lookback sensitivity, benchmark status, and stress-period behavior.
- `ml_score`: Return Spearman IC and direction hit rate, with penalty for negative IC.
- `data_quality_score`: Starts high, then penalizes proxy-only data and equity/miner proxy exposure.
- `risk_penalty`: Adds penalties for proxy-only data, high drawdown, weak robustness, negative ML IC, and COPX/XME miner beta risk.
- `evidence_score`: 0.25*performance + 0.20*robustness + 0.15*ML + 0.15*data_quality + 0.15*economic_logic - 0.10*risk_penalty.
- Best variant: `COPPER_EQUITY_PROXY_TREND_COPX_XME_V1`
- Best variant recommendation: `Watch`
- Candidate portfolio action: `NONE`

## 7. Anti-Randomness Checks
- `variants_not_random`: PASS - Each variant has deterministic id, signal_formula, universe_or_proxy, benchmark, features, and data_requirements in variant_spec.json.
- `no_candidate_without_artifacts`: PASS - candidate_allowed is false for all copper rankings and each decision references completed/blocked artifacts.
- `no_ml_without_artifact`: PASS - ML completion is read from variant_ml_diagnostics_run.json or ml_diagnostics_run.json only.
- `no_paper_derived_without_source`: PASS - Material ids and analysis paths are recorded; source_classification is METHOD_REFERENCE_ONLY rather than overclaiming paper-derived alpha.
- `proxy_only_blocks_candidate`: PASS - PROXY_ONLY status appears in data decisions and candidate_allowed false is explained for the copper run.

## Answer To Audit Question
Factory logic used controlled material themes to classify the run as commodity trend / macro proxy, generated deterministic copper proxy variants from that type, selected features/models based on interpretable time-series diagnostics, evaluated evidence through metrics/ML/robustness/proxy penalties, ranked variants with a transparent heuristic score, and rejected Candidate status because the evidence is proxy-only and not strong enough for admission.
