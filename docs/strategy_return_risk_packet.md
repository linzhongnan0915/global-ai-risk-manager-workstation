# Strategy Return Risk Packet

Created: 2026-06-05

## Purpose

Every strategy detail view should help the risk analyst answer:

```text
What does this strategy's return behavior look like,
what risks does it hide,
when does it fail,
and what should the risk manager do with its allocation?
```

This packet is the required analysis template for any strategy with a return series.

## 1. Summary Statistics

Purpose: understand the basic return and risk profile.

Required metrics:

- Mean daily return.
- Annualized return.
- Annualized volatility.
- Sharpe ratio.
- Sortino ratio.
- Win rate.
- Best day.
- Worst day.
- Skewness.
- Kurtosis.
- Number of observations.

Risk analyst questions:

- Is the return high enough relative to volatility?
- Is the Sharpe supported by many periods or only a few lucky periods?
- Is Sortino much worse than Sharpe, suggesting downside volatility matters?
- Is skewness negative, suggesting left-tail risk?
- Is kurtosis high, suggesting fat tails or crash risk?

## 2. Distribution Shape

Purpose: inspect the shape of daily or periodic returns.

Required charts:

- Histogram.
- Density/KDE curve when available.
- QQ plot against normal distribution when available.
- Box plot or outlier summary.

Required checks:

- Is the distribution close to normal or visibly non-normal?
- Is the left tail longer than the right tail?
- Are returns clustered around zero?
- Are there extreme outliers?
- Are positive returns frequent but small while negative returns are rare but large?

Risk analyst questions:

- Does the strategy hide crash-like behavior?
- Does a normal-distribution risk model underestimate tail losses?
- Are outliers real market events or data errors?

## 3. Tail Risk

Purpose: estimate what happens in bad markets.

Required metrics:

- 95% VaR.
- 99% VaR.
- 95% Expected Shortfall.
- 99% Expected Shortfall.
- Worst 5 days or periods.
- Worst 10 days or periods.
- Tail ratio when available.
- Left-tail frequency.

Risk analyst questions:

- How bad is a normal bad day?
- If the strategy enters the worst 5% of outcomes, how much does it lose on average?
- Are tail losses much worse than VaR suggests?
- Do tail losses happen together with portfolio or market stress?

## 4. Drawdown Behavior

Purpose: understand cumulative loss pain and recovery behavior.

Required charts:

- Cumulative return curve.
- Drawdown or underwater curve.

Required metrics:

- Max drawdown.
- Current drawdown.
- Average drawdown.
- Longest drawdown duration.
- Time to recovery.
- Number of meaningful drawdown episodes.

Risk analyst questions:

- Does the strategy lose suddenly or bleed slowly?
- Is the current drawdown normal relative to history?
- How long can capital be trapped before recovery?
- Does the drawdown match known failure modes?

## 5. Time Stability

Purpose: test whether performance is stable or concentrated in a few periods.

Required rolling diagnostics:

- Rolling 3-month Sharpe.
- Rolling 6-month Sharpe.
- Rolling 12-month volatility.
- Rolling drawdown.
- Rolling win rate.
- Rolling correlation to benchmark and portfolio.

Required checks:

- Subperiod performance.
- Recent performance versus full-history performance.
- Live or paper performance versus backtest expectation.
- Signal decay indicators when available.

Risk analyst questions:

- Is performance persistent or concentrated in one window?
- Is recent behavior worse than historical behavior?
- Is volatility rising?
- Is the strategy becoming more correlated with the rest of the book?

## 6. Regime Breakdown

Purpose: identify where the strategy works and where it fails.

Required regime splits:

- VIX high versus VIX low.
- Equity market up versus down.
- Rates up versus down.
- Credit spread widening versus tightening.
- USD up versus down.
- Inflation rising versus falling when data is available.
- Growth/risk-on versus slowdown/risk-off.

Required metrics by regime:

- Mean return.
- Volatility.
- Sharpe.
- Max drawdown.
- Hit rate.
- Tail loss.

Risk analyst questions:

- Which regime is the strategy designed for?
- Is it currently in a favorable or unfavorable regime?
- Is a loss normal for this regime?
- Does the strategy diversify the portfolio in stress regimes?

## 7. Comparison Versus Benchmark And Other Strategies

Purpose: decide whether the strategy adds unique value to the portfolio.

Required comparisons:

- Correlation to benchmark.
- Beta to benchmark.
- Alpha versus benchmark when appropriate.
- Tracking error.
- Information ratio when appropriate.
- Correlation to active strategies.
- Correlation to portfolio.
- Factor overlap with active strategies.
- Marginal risk contribution.
- Diversification benefit.

Risk analyst questions:

- Is this strategy real alpha or disguised beta?
- Does it duplicate an existing active strategy?
- Does it reduce or increase portfolio concentration?
- Is a lower-Sharpe strategy still useful because it diversifies the book?

## Final Risk Manager Decision

Every strategy review should end with one of:

- Keep.
- Increase review.
- Reduce.
- Hedge.
- Pause.
- Retire.
- Reject.

Required explanation:

- Main evidence.
- Main risk.
- Current allocation.
- Proposed allocation.
- Transaction cost impact.
- Factor/correlation impact.
- Data or model limitation.
- Human approval status.

