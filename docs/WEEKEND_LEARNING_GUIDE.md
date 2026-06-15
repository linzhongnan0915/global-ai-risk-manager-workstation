# Weekend Learning Guide

## The Core Mental Model

A risk manager does not ask only, "Did the strategy make money?"

The daily questions are:

1. What happened?
2. Why did it happen?
3. Was the loss or gain consistent with the strategy's intended behavior?
4. Did a risk limit, evidence requirement, or portfolio concentration rule fail?
5. What action is justified by the evidence?
6. Who is authorized to approve it?
7. What should happen after the decision?

## Study The Workstation In This Order

### 1. Portfolio Command Center

Start with portfolio PnL, volatility, VaR, Expected Shortfall, drawdown, contributors, detractors, and risk-limit counts.

Goal: explain what changed today before opening any individual strategy.

### 2. Strategy Monitor

Select one profitable strategy and one losing strategy. Compare:

- Current and proposed allocation
- Daily, MTD, and YTD PnL
- Sharpe and rolling Sharpe
- Current and maximum drawdown
- Turnover and signal state
- Factor exposure
- Failure modes
- Final double-check action

Goal: learn why a losing strategy is not automatically increased or stopped.

### 3. Open Strategy Review

Read the eight-section risk packet from top to bottom.

For every metric, answer two questions:

- What does this metric measure?
- What decision could this metric change?

Example: a poor recent rolling Sharpe with acceptable long-history Sharpe may mean Watch, while a breached drawdown limit plus failed OOS evidence may justify Reduce or Pause.

### 4. Allocation & Rebalance

Compare current and proposed risk. Then check:

- Which trades are proposed?
- What is the transaction cost?
- Which allocation changes are blocked?
- Does the expected improvement survive the double-check?
- Is the proposal authorized?

Goal: understand why an optimizer output is a proposal, not a decision.

### 5. Risk Factors & Correlation

Look for:

- Large factor exposures
- Factor concentration
- Strategies that appear different but share the same risk driver
- Correlations that increase diversification risk
- Scenario losses that exceed limits

Goal: understand that different strategy names do not guarantee independent risk.

### 6. Daily Risk Report

Read the governance flow:

1. PM proposal
2. Independent risk review
3. Human decision authority
4. Execution and monitoring

Goal: be able to explain who owns each decision and why the system cannot auto-execute.

## A Practical Strategy Review Template

Use this sequence when reviewing any strategy:

1. State the hypothesis and intended portfolio role.
2. Confirm universe, signal, rebalance rule, and transaction costs.
3. Check bias controls and walk-forward evidence.
4. Review return distribution and tail losses.
5. Review drawdown depth, duration, and recovery behavior.
6. Compare recent rolling behavior with long-history behavior.
7. Explain the best and worst regimes.
8. Check benchmark beta, cross-strategy correlation, and factor overlap.
9. Review all triggered risk limits.
10. Recommend Keep, Watch, Reduce, Hedge, Pause, Rebalance, or Human Review.

## What The Current Prototype Cannot Prove

- It cannot prove live execution performance.
- It cannot replace licensed position, factor, or market data.
- It cannot eliminate ETF-proxy mismatch.
- It cannot make an authorized allocation decision.
- It cannot treat historical optimizer improvement as guaranteed future benefit.

Those limitations are part of the risk-manager conclusion, not defects to hide.

