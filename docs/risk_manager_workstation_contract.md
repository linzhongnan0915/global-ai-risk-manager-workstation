# Risk Manager Workstation Contract

Created: 2026-06-05

This project is a hedge fund / asset manager style multi-strategy portfolio risk management workstation.

It is not a single-strategy dashboard, a stock quote board, a retail investing page, or a landing page.

## Operating Objective

The platform must answer these questions every day:

1. What happened to the portfolio today?
2. Which strategies made or lost money, and why?
3. Which risk limits or thresholds were triggered?
4. Which strategies need Keep, Watch, Reduce, Hedge, Pause, Rebalance, or Human Review?
5. If rebalance is proposed, what is the transaction cost and how does risk change before vs after?
6. Which recommendations require human approval?
7. Which strategies are blocked from live allocation because evidence is missing?

## Portfolio Scope

- Start date: 2026-06-04
- Initial capital: USD 1,000,000
- Current scope: 20+ strategies
- Future scope: 30-40 strategies
- All strategies exist simultaneously.
- A strategy can be selected for drill-down, but the platform view is always multi-strategy.

## Transaction Cost Standard

Every backtest, rebalance, and allocation recommendation must include transaction cost:

- Buy cost: 5 bps
- Sell cost: 5 bps
- Round trip cost: 10 bps
- Cost impact must be shown in dollars and performance/risk terms.

## Evidence Gate

Every strategy must have:

- Strategy hypothesis
- ETF / asset universe
- Signal definition
- Position construction
- Rebalance frequency
- Transaction cost assumption
- Risk limits
- Failure modes
- Backtest evidence
- Walk-forward / OOS evidence
- Data source and quality status

If a strategy lacks backtest or walk-forward evidence, it must remain `research`, `pending`, or `human_review_required`. It cannot be treated as approved allocation evidence.

## Required Strategy Drill-Down Packet

Clicking a strategy must expose:

1. Summary statistics
   - Daily return
   - Cumulative return
   - Annualized return
   - Annualized volatility
   - Sharpe
   - Sortino
   - Calmar
   - Win rate
   - Average win
   - Average loss
   - Payoff ratio
   - Profit factor
   - Turnover
   - Transaction cost drag

2. Distribution shape
   - Histogram
   - Mean
   - Median
   - Standard deviation
   - Skewness
   - Kurtosis
   - Excess kurtosis
   - P01 / P05 / P25 / P75 / P95 / P99
   - Outlier count

3. Tail risk
   - VaR 95
   - VaR 99
   - Expected Shortfall 95
   - Expected Shortfall 99
   - Worst 5 days
   - Worst 10 days
   - Left-tail frequency
   - Stress loss estimate

4. Drawdown behavior
   - Cumulative return curve
   - Underwater curve
   - Max drawdown
   - Current drawdown
   - Drawdown duration
   - Recovery time
   - Drawdown episode count

5. Time stability
   - Rolling 21D Sharpe
   - Rolling 63D Sharpe
   - Rolling 126D Sharpe
   - Rolling 252D Sharpe
   - Rolling volatility
   - Rolling drawdown
   - Rolling win rate
   - Rolling correlation to portfolio and benchmark

6. Regime breakdown
   - Equity up / down
   - High / low volatility
   - Credit supportive / credit stress
   - Rates falling / rates rising
   - USD up / USD down
   - Inflation proxy up / down
   - Risk-on / risk-off

7. Comparison
   - Benchmark beta
   - Benchmark correlation
   - Annualized alpha
   - Tracking error
   - Information ratio
   - Up capture
   - Down capture
   - Correlation to other active strategies
   - Marginal risk contribution

8. Decision packet
   - Current allocation
   - Proposed allocation
   - Allocation change
   - Estimated transaction cost
   - Risk before / after
   - Triggered limits
   - Recommended action
   - Reason code
   - Human approval status

## Portfolio-Level Packet

The portfolio command center must show:

- AUM
- Daily PnL
- Cumulative PnL
- Portfolio Sharpe
- Portfolio volatility
- VaR 99
- Expected Shortfall 95
- Max drawdown
- Current drawdown
- Strategy contribution to PnL
- Strategy contribution to risk
- Factor exposure
- Factor concentration
- Strategy correlation matrix
- Rebalance recommendation
- Transaction cost impact
- Human review alerts

## Strategy Independence Requirement

The platform must not count highly correlated strategies as independent diversification.

Each strategy should have a distinct return driver, signal logic, market regime behavior, and failure mode. If two strategies have high correlation or repeatedly lose money in the same regimes, risk management should treat them as duplicate exposure.

Correlation gate:

- The dashboard must show pairwise strategy correlation.
- Strategy pairs above the configured correlation threshold must be flagged.
- Strategies with duplicate-exposure breaches cannot be allocation eligible unless they are explicitly labeled as a hedge or overlay.
- If two strategies are essentially the same economic bet, the platform should keep the better evidence-adjusted strategy and mark the other as Merge / Redesign, Reduce, or Research Hold.

## Risk Limits

Risk limits must be explicit, visible, and color-coded:

- Green: within limit
- Yellow: watch
- Orange: warning / near breach
- Red: breach

Limits must be shown at portfolio and strategy level. The UI cannot show a generic decorative risk score without explaining:

- Which limit is being checked
- Current value
- Threshold
- Utilization
- Status
- Action

## Data Layer Contract

The platform must be API-ready:

- yfinance and OpenBB are data adapters.
- Future boss API must plug into the same artifact schema.
- Strategy logic, risk logic, dashboard layout, and decision workflow must not depend on a specific provider.
- Each data refresh must record source, timestamp, row count, missing values, stale data, and failure state.

## Dashboard Tabs

The allowed workflow tabs are:

1. Portfolio Command Center
2. Strategy Monitor
3. Allocation & Rebalance
4. Risk Factors & Exposure
5. Correlation & Diversification
6. Market & Macro Monitor
7. Backtesting & Research Lab
8. Strategy Library & Workflow
9. Daily Risk Report / Decision Log

The left navigation and top tabs must not duplicate each other without purpose. If both exist, the top tabs control primary workflow and the left sidebar shows contextual sections, risk-limit summary, and selected workflow shortcuts.

## Visual Direction

The interface must be:

- Institutional
- Dense but organized
- Dark professional workstation
- Bloomberg / BlackRock / Bridgewater inspired
- Data-first
- Compact
- Highly scannable

It must include:

- Compact KPI cards
- Sortable dense tables
- Heatmaps with labels and thresholds
- Sparklines
- Risk badges
- Current vs proposed allocation
- Rebalance decision center
- Transaction cost impact
- Human review alerts
- Strategy detail drawer
- Daily decision log

It must not become:

- Retail investing dashboard
- Landing page
- Single-strategy dashboard
- Decorative chart demo
- UI with unexplained circles or unlabeled heatmaps
