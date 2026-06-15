# Strategy Intake Workflow

This document defines the handoff path for boss-provided strategy documents, ETF lists, hedge fund examples, and research notes.

This workflow should follow the new risk manager platform mindset defined in `platform_workflow_reset.md`: strategy intake is not just a backtest queue. It is the admission gate into a multi-strategy allocation and risk governance system.

## Intake Steps

1. Convert the idea into a strategy hypothesis.
2. Identify the economic source of edge: risk premium, behavioral bias, institutional constraint, or market structure.
3. Define universe, data source, observation frequency, history length, and timestamp availability.
4. Define signal, position construction, rebalance frequency, and transaction cost assumptions.
5. Run the longest defensible backtest available.
6. Run rolling or walk-forward validation.
7. Stress test across major regimes and crisis windows.
8. Check factor exposure, correlation to active strategies, and portfolio diversification benefit.
9. Define risk limits, failure modes, live-monitoring metrics, and pause/retire rules.
10. Add the strategy to `data/config/strategy_registry.json` with lifecycle status.
11. Generate dashboard artifacts.
12. Require human approval before any real allocation change.

## Minimum Strategy Evidence

- Economic rationale and expected failure modes.
- Backtest period and data coverage.
- Gross and net performance after 5 bps buy / 5 bps sell transaction costs.
- Sharpe, volatility, max drawdown, win rate, turnover, and cost drag.
- Walk-forward or rolling out-of-sample evidence.
- Factor exposure and correlation to active strategies.
- Proposed allocation eligibility, risk limits, and known limitations.

## Take The Best From The Old Workflow

Keep the old live strategy discipline:

- Validate data quality and timestamp alignment before trusting any signal.
- Use macro regime and news context to interpret strategy behavior.
- Treat factor exposure as a risk explanation, not just a dashboard chart.
- Require long-history backtests and walk-forward validation.
- Keep human review mandatory.

Then apply the new platform lens:

- Every strategy must have lifecycle status.
- Every approved strategy must fit into portfolio-level risk limits.
- Every allocation change must show cost, risk, correlation, and factor impact.
- Every keep/reduce/pause/rebalance decision must be recorded in the decision log.
