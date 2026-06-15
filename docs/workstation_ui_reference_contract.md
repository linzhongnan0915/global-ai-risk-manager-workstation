# Workstation UI Reference Contract

Created: 2026-06-05

This document translates the user's dashboard screenshot references into a concrete UI and information-architecture contract.

The screenshots are not a pixel-copy target. They define the design language, information density, component structure, and professional risk workstation feel that this project must move toward.

## Product Identity

The platform is an institutional multi-strategy portfolio risk management workstation.

It is not:

- A retail investing app
- A single-strategy dashboard
- A stock quote board
- A marketing page
- A SaaS landing page
- A decorative demo prototype

Target feel:

- Hedge fund / asset manager workstation
- Bloomberg / BlackRock / Bridgewater inspired
- Dark professional theme
- Dense, sharp, compact, serious
- High information density with clear grouping
- Small labels, tight tables, compact KPI cards
- No large hero metrics, oversized cards, large whitespace, decorative gradients, or rounded marketing panels

## Layout Contract

The dashboard shell must use:

- Top header for platform name, date, capital, strategy count, regime, and data status
- Horizontal tabs for the 9 primary workflow modules
- Optional left navigation only for secondary navigation within a module
- Main work area with dense tables, charts, matrices, and decision panels
- Right-side strategy detail drawer or detail panel when a strategy is selected

The horizontal tabs and left navigation must not duplicate each other. The user should always know:

- Which module they are in
- What they are reviewing
- What action can be taken next

## Required Workflow Tabs

1. Portfolio Command Center
2. Strategy Monitor
3. Allocation & Rebalance
4. Risk Factors & Exposure
5. Correlation & Diversification
6. Market & Macro Monitor
7. Backtesting & Research Lab
8. Strategy Library & Workflow
9. Daily Risk Report / Decision Log

## Portfolio Command Center

The first screen must behave like a command center, not a generic dashboard.

Required elements:

- Compact KPI strip: AUM, Daily PnL, Cumulative PnL, Sharpe, Volatility, Max Drawdown, VaR, Expected Shortfall, Risk Status
- Tiny sparklines where useful
- Allocation table and compact allocation visual
- Top contributors and detractors
- Portfolio PnL plus drawdown chart
- Strategy performance table
- Rebalance recommendation
- Factor exposure heatmap
- Human review alerts
- Transaction cost, net benefit, and approval status

## Strategy Monitor

The Strategy Monitor must show 20+ strategies in a dense table.

Each strategy row should support these fields:

- Strategy name
- Type
- Current allocation
- Proposed allocation
- Current position summary
- Daily PnL
- MTD / YTD PnL
- Daily return
- Sharpe
- Rolling Sharpe
- Volatility
- Max drawdown
- Current drawdown
- Win rate
- Turnover
- Transaction cost drag
- Signal status
- Regime fit
- Factor exposure summary
- Correlation warning
- Risk limit status
- Action recommendation

Selecting a strategy must open or update a detail drawer / panel with:

- Strategy name, type, status
- Current allocation, proposed allocation, current position
- Performance chart
- Drawdown chart
- Signal history
- Position history
- Backtest summary
- Walk-forward results
- Factor exposure
- Current risk explanation
- Failure modes
- Human review note

A static table is not enough. Strategy selection and drill-down are mandatory.

## Allocation & Rebalance

This is the key decision tab. It cannot be a simple pie chart.

Required elements:

- Current vs proposed allocation
- Weight change
- Buy / sell direction
- Dollar amount
- Estimated transaction cost
- Cost assumption: 5 bps buy, 5 bps sell
- Risk before vs after
- Sharpe before vs after
- Volatility before vs after
- VaR / ES before vs after
- Drawdown before vs after
- Factor concentration before vs after
- Correlation before vs after
- Optimizer constraints
- Rebalance trade list
- Approve / reject / modify decision center
- Pending human approval status

The optimizer must never look like blind Sharpe maximization. It must visibly respect diversification, drawdown, correlation, turnover, transaction cost, factor concentration, risk limits, and human approval.

## Risk Factors & Exposure

Required elements:

- Portfolio factor exposure
- Strategy-by-factor matrix
- Heatmap
- Factor contribution to risk
- Factor contribution to return
- Risk limits breached
- Scenario shock table
- Sector / rates / FX / commodity / volatility exposure
- Macro regime panel
- Recent changes
- Human review alerts

Heatmaps should use clear red / green risk language. Empty decorative cards are not acceptable.

## Backtesting & Research Lab

This tab should feel like a research terminal, not a notebook screenshot.

Required elements:

- Selected strategy
- Backtest period
- Gross return vs net return after transaction costs
- Equity curve
- Drawdown chart
- Rolling Sharpe
- Return distribution
- Key metrics summary
- Walk-forward table
- No-look-ahead checklist
- Data coverage and quality
- Stress period performance
- Regime performance matrix
- Approval workflow
- Attached documents / evidence placeholder

## Daily Risk Report / Decision Log

This tab should feel like a daily risk memo plus operational log.

Required elements:

- Report date
- Portfolio summary
- Daily PnL
- YTD PnL
- Risk status
- Open alerts
- Limit breaches
- Data quality warnings
- Market summary
- Strategy alerts
- Rebalance recommendation
- Decision outcome log
- Human decision notes
- Accepted / rejected / modified decisions
- Data quality warning table
- Decision timeline
- Export controls

## Interaction Contract

The UI must support:

- Tab switching
- Strategy row selection
- Selected strategy detail drawer updates
- Sortable / filterable dense tables as the table layer matures
- Risk badge and threshold status display
- Recommendation display
- Approve / reject / modify buttons
- Dashboard artifact JSON driven rendering
- Future API refresh

## Visual Guardrails

Do not use:

- Marketing hero sections
- Retail portfolio app styling
- Oversized cards
- Large empty whitespace
- Large rounded rectangles
- Decorative gradients
- Fake risk circles without explanatory limits
- One-off charts not tied to risk manager decisions
- Generic dashboard copy that does not answer a risk workflow question

Use:

- Compact KPI cards
- Dense tables
- Tight row heights
- Small uppercase labels where helpful
- Workstation typography
- Thin borders
- Clear red / yellow / orange / green risk states
- Heatmaps
- Sparklines
- Right-side detail panels
- Decision center panels

## Daily Questions The UI Must Answer

1. What happened to the portfolio today?
2. Which strategies performed well or poorly?
3. Which risk limits or thresholds were triggered?
4. Which strategies need Keep, Watch, Reduce, Hedge, Pause, Rebalance, Research Hold, or Human Review?
5. What is the transaction cost of a rebalance?
6. Did risk improve before vs after the proposed rebalance?
7. Which recommendations require human approval?
8. Which strategies remain research-only because backtest or walk-forward evidence is missing?
