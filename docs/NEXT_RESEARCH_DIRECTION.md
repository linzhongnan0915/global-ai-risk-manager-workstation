# Next Research Direction

The dashboard is now a monitoring layer. It should help a risk manager inspect operational state, paper performance, stale data, warnings, and governance boundaries, but it is not the main value driver.

The next phase should shift effort toward quant research and ML:

- Bloomberg Terminal data and news learning for richer market, macro, and company context.
- Macro regime detection using validated market, rates, credit, volatility, and news features.
- Strategy selection by regime, so active sleeves can be evaluated under the conditions where they are expected to work.
- ML models across strategies for ranking, allocation support, drawdown alerts, and regime-aware sleeve selection.
- Portfolio optimization with explicit constraints, transaction costs, turnover, drawdown, and risk budget controls.
- Research paper documentation for each strategy before relying on it for portfolio decisions.

Future dashboard work should monitor research outputs, not drive the research itself. Research artifacts should be produced by separate notebooks, pipelines, or papers, then surfaced in the workstation as evidence.

Each future research output should include:

- Economic rationale.
- Data source.
- Signal construction.
- Backtest design and results.
- Transaction cost assumptions.
- Risk analysis.
- Regime analysis.
- ML extension, if applicable.
- Limitations and failure modes.
