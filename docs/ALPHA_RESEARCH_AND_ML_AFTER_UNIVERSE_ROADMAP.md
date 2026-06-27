# Alpha Research And ML After Universe Roadmap

Universe engineering comes before strategy expansion, migration backtests, ML, and optimizer work. The platform sequence must not be inverted:

`Universe foundation -> broad universe population -> strategy migration audit -> provisional migration backtests -> strategy update/reject decisions -> point-in-time long-history validation -> ML research -> optimizer/allocation engine`

The project source of truth is `D:\Global_Ai\release_global_ai_risk_manager_workstation`. Alpha research experiments belong under `D:\Global_Ai\alpha_research`. Do not use the old `Risk_Manager_Platform` repository.

## Universe Direction

The broad universe target is not a random or pilot stock sample. It is a rules-based U.S. equity research universe with explicit tiers:

1. `US_LARGE_CAP_CORE` - S&P 500-style large-cap core.
2. `US_BROAD_MARKET` - Russell 3000-style broad-market research universe.
3. `US_SMALL_CAP` - Russell 2000-style / small-cap research subset.
4. `US_ALL_COMMON_RESEARCH` - broad current-listed U.S. common-stock research discovery pool, up to around 5,000 names where data supports it.
5. `US_TRADABLE_LIQUID` - filtered tradable subset based on price, ADV, market cap, asset type, and data quality.

The 5,000-name pool is for research discovery, AI strategy search, broad strategy testing, and pipeline development. It is not the direct optimizer/trading universe. Optimizer and allocation work should eventually use `US_TRADABLE_LIQUID` or approved strategy-specific universes only.

All yfinance/public fallback outputs must remain labeled:

- `DATA_SOURCE = YFINANCE_PUBLIC_FALLBACK`
- `POINT_IN_TIME_STATUS = CURRENT_MEMBERSHIP_ONLY_PROVISIONAL`
- `RESEARCH_USE = PROTOTYPE_ONLY`
- `NOT_SURVIVOR_BIAS_FREE = true`

## Long-Horizon Backtesting Direction

The long-term goal is to support 30-40 years of historical backtesting where data permits. This cannot be honestly completed with only yfinance/current-membership data.

True institutional validation requires point-in-time universe membership, delisted securities, delisting returns, corporate-action-adjusted prices, identifier history, price/volume and ADV history, market cap history, sector/industry history, data availability timestamps, and source/vendor metadata. Until those are available from boss/API/vendor data, yfinance/public fallback results remain provisional only.

## Existing Strategy Migration Direction

After broad universe coverage is visible, audit the 16 ordinary active strategies and classify which ones can actually be tested as stock-selection strategies. Do not directly backtest Combined as a stock selector; Combined is a portfolio/composite layer and may only be recomputed later from ordinary strategy results.

Allowed migration classifications:

- `READY_STOCK_SELECTOR`
- `NEEDS_SIGNAL_ADAPTER`
- `PROXY_ONLY_NOT_STOCK_SELECTOR`
- `DATA_BLOCKED`
- `UNSUPPORTED_FOR_MIGRATION`

Each strategy audit should document current definition, data dependency, universe dependency, stock-level signal availability, cross-sectional ranking ability, required fields, proposed default and expansion universes, rebalance frequency, execution convention, cost assumption, risk controls, blockers, and retain/update/rebuild/reject direction.

Only migratable ordinary strategies should proceed to provisional migration backtests. Strategies that are ETF/proxy/dashboard-only must not be assigned fabricated stock-selection signals.

## Provisional Migration Backtest Direction

For migratable strategies only, provisional migration backtests should evaluate gross return, net return after costs, annualized return, Sharpe, volatility, max drawdown, turnover, cost drag, win rate, benchmark excess return, beta/correlation where available, sector exposure, liquidity bucket performance, recent-period robustness, stress-period behavior, data quality coverage, and failure reasons.

Allowed provisional result labels:

- `PASS_PROVISIONAL`
- `WATCH_PROVISIONAL`
- `FAIL_PROVISIONAL`
- `BLOCKED_DATA`
- `NOT_MIGRATABLE`

A strategy with high gross returns but negative net returns after costs should not pass. A strategy whose returns only come from illiquid stocks should not pass. A strategy with high turnover and high cost drag should be `WATCH_PROVISIONAL` or `FAIL_PROVISIONAL`. A strategy that only worked in the old random/pilot universe should be challenged, not preserved automatically. A strategy blocked by missing data should be labeled `BLOCKED_DATA`, not forced.

## Release Safety

Do not overwrite official paper portfolio performance. Do not replace active strategy dashboard metrics with provisional migration results. Do not change Combined/N semantics. Do not promote any strategy. Do not implement optimizer based on provisional results. Do not begin final ML training/admission until universe, features, and timestamps are stable. Do not touch live brokerage semantics.

Migration results, when ready, should live in a separate research-only dashboard section such as `Provisional Universe Migration Backtest`, clearly separated from official NAV, official daily P&L, paper ledger, active strategy monitor, Combined active sleeve, and live brokerage fields.

## 1. AI Agent Strategy Factory

Generate candidate research cards only against explicit strategy-specific universes. Each card should state universe, hypothesis, signal, rebalance timing, execution lag, transaction costs, risk controls, and invalidation conditions.

## 2. Research Card Generation

Each research card should reference the universe snapshot version, data source, point-in-time status, and known survivorship/corporate-action limitations.

## 3. Strategy-Specific Universe Selection

Use `data/config/strategy_universe_mapping.yaml` as the bridge between strategy families and default, expansion, or deployment universes.

## 4. Feature Store

Build timestamped features keyed by stable security ID, ticker, observation date, data availability timestamp, and source. Do not mix final revised data with unavailable-at-signal-time features.

## 5. Walk-Forward Backtesting

Run walk-forward studies only after universe membership and feature availability are date-aware. Keep research, validation, and final untouched test windows separate.

## 6. ML Model Experiments

ML experiments should log universe snapshot version, feature timestamp audit status, model version, train/validation/test windows, and leakage checks.

## 7. Admission Gates

Admission gates should include universe integrity, point-in-time status, liquidity/cost feasibility, data-quality coverage, signal evidence, robustness, and operational monitoring readiness.

## 8. Portfolio Optimizer

Optimizer work should wait until tradable liquid universe definitions, transaction costs, constraints, covariance inputs, and shadow-live operational boundaries are stable.

## 9. Google Docs Research Archive

Research archive entries should cite universe version, source status, PIT status, limitations, and generated artifacts. Historical Research remains separate from Operational records.

## Staged Roadmap

1. Complete yfinance provisional broad-universe scaling from the 50-name smoke toward 500, 1500, 3000, and eventually 5000 names if stable.
2. Create the 16-strategy migration audit and classify every ordinary active strategy.
3. Build the provisional migration backtest harness in `D:\Global_Ai\alpha_research`.
4. Run provisional migration backtests for migratable strategies only.
5. Generate strategy-by-strategy retain/update/reject recommendations.
6. Integrate migration results into the Workstation dashboard as research-only artifacts.
7. When boss/API/vendor data is available, upgrade from provisional current-membership testing to point-in-time 30-40 year institutional backtests.
8. Only after validated strategy results are available, begin ML pipeline and optimizer work.

## Immediate Next Step

Continue controlled yfinance provisional broad-universe scaling and then perform the 16-strategy migration audit. Full migration backtests, ML, optimizer, and dashboard integration remain later stages.
