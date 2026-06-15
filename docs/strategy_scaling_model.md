# Strategy Scaling Model

Created: 2026-06-05

## Objective

The platform must support 20 strategies now and 30-40 strategies later without changing the core system.

Adding a strategy should mean adding a validated strategy record and an executable signal module, not redesigning the dashboard or rewriting risk logic.

## Strategy Operating Model

Every strategy goes through the same lifecycle:

1. `candidate`
   - Idea exists.
   - Literature source and ETF coverage are known.
   - Signal may still be rough.
   - No allocation evidence.

2. `prototype_running`
   - Signal is implemented with yfinance/OpenBB/boss API data.
   - Backtest and walk-forward evidence are generated.
   - Transaction costs are included.
   - Bias limitations are disclosed.

3. `research_hold`
   - Strategy is useful for analysis but lacks required evidence.
   - It can appear in dashboard, but cannot receive approved allocation.

4. `watch`
   - Evidence exists, but one or more risk or stability indicators require monitoring.

5. `allocation_eligible`
   - Backtest evidence exists.
   - WFO/OOS evidence exists.
   - Risk limits are within threshold.
   - Human approval is still required before real allocation change.

6. `paused`
   - Strategy breached drawdown, tail risk, data quality, or evidence limits.

7. `retired`
   - Strategy is kept for audit history but removed from active research allocation.

## Required Record For Each Strategy

Each strategy must define:

- Strategy ID
- Name
- Family
- Source paper / document
- Institutional role
- ETF universe
- Required non-ETF data
- Signal definition
- Rebalance frequency
- Position construction
- Transaction cost assumption
- Risk limit profile
- Failure modes
- Backtest status
- Walk-forward/OOS status
- Evidence status
- Human approval status
- Recommended action

## Current Strategy Count

The research catalog currently contains 20 strategy candidates across seven families:

1. Formulaic Alpha Baskets
2. Hedge Fund Replication
3. Macro And Business-Cycle Regime Allocation
4. Markov / High-Volatility Defensive Regimes
5. Managed Futures And Trend Replication
6. Relative Value, Arbitrage, And Event-Risk Proxies
7. Global, Style, And Volatility Overlay Sleeves

## Expansion To 30-40 Strategies

The next 10-20 strategies should be added by duplicating the same contract, not by inventing a new workflow.

Likely expansion families:

- Additional WorldQuant alpha formulas
- Sector-neutral alpha baskets
- More hedge fund style replication sleeves
- Regional macro sleeves
- Commodity sub-sleeves
- Rates curve sub-sleeves
- Credit quality / duration sleeves
- Volatility surface strategies
- News/event-risk strategies
- Qlib model-based alpha portfolios

## Allocation Rule

The platform can monitor all 20-40 strategies at once, but not all strategies are allocation eligible.

Allocation eligibility requires:

- Complete strategy specification
- Data quality pass
- Backtest evidence
- Walk-forward/OOS evidence
- Transaction cost included
- Risk limits not breached
- Pairwise correlation and duplicate-exposure gate passed
- Human approval

If any of these are missing, the strategy must remain `Research Hold`, `Watch`, or `Candidate`.

## Correlation And Duplicate Exposure Rule

The point of 20-40 strategies is not to create 20-40 labels. It is to create multiple independent return drivers.

If two strategies are highly correlated, the platform must assume they may be the same economic bet until proven otherwise.

Default rule:

- Pairwise absolute correlation below 0.45: acceptable
- 0.45 to 0.60: watch
- 0.60 to 0.75: warning
- 0.75 or above: duplicate-exposure breach

If a strategy breaches the duplicate-exposure threshold:

- It cannot be treated as independent allocation.
- It should be merged with the overlapping strategy, redesigned with a different signal/universe, reduced, or marked as hedge/overlay if it has a true risk-offsetting role.
- If two strategies move together and have the same failure mode, keep only the better evidence-adjusted implementation.

High correlation is not automatically bad for a hedge sleeve if the strategy is explicitly designed to offset portfolio risk, but it must then be labeled as a hedge or overlay, not independent alpha.

## Dashboard Rule

The dashboard must show all strategies, but visually separate:

- Running / eligible strategies
- Research hold strategies
- Candidate strategies
- Paused strategies
- Retired strategies

This prevents the platform from confusing "we are monitoring this idea" with "this is approved for allocation."
