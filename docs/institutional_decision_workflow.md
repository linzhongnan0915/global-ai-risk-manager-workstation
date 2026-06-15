# Institutional Portfolio Decision Workflow

This project separates portfolio construction from independent risk oversight.

The system can generate proposals, calculate risk, identify objections, and recommend an outcome. It cannot make or execute a real capital decision.

## Stage 1: Portfolio Proposal

Owner: Portfolio Manager / Portfolio Construction

The proposal owner must explain:

- What problem or opportunity triggered the proposal?
- What is the expected alpha or portfolio benefit?
- Why should each strategy weight increase or decrease?
- What regime assumptions support the proposal?
- What are the liquidity, capacity, turnover, and execution assumptions?
- When does the proposal expire?

Required output:

- Current and proposed weights
- Trade list
- Investment thesis
- Expected benefit
- Implementation window
- Proposal owner

The risk manager does not own the alpha thesis.

## Stage 2: Independent Risk Review

Owner: Independent Risk Manager

The reviewer must independently challenge:

- Evidence quality and bias controls
- Risk limits and mandate compliance
- Drawdown and tail-risk behavior
- Factor concentration
- Correlation and duplicate exposure
- Stress scenarios
- Liquidity, turnover, and transaction cost
- Expected benefit relative to uncertainty

Possible risk conclusions:

- No objection
- Conditions required
- Blocking objection
- Escalation required

The reviewer should ask whether the proposal solves the original problem or merely transfers risk elsewhere.

## Stage 3: Decision Authority

Owner: Authorized Human Approver

Allowed outcomes:

- Approve
- Approve with Conditions
- Reject
- Escalate

The decision record must include:

- Named authority
- Decision timestamp
- Conditions
- Override reason, when applicable
- Override approver
- Decision expiry date
- Execution authorization

A system recommendation is not a human decision.

## Stage 4: Execution and Post-Decision Monitoring

Owners: Trading / Operations and Risk

Before execution:

- Confirm authorization
- Confirm final weights and trade list
- Confirm transaction-cost estimate
- Confirm implementation window

After execution:

- T+1: reconcile positions, weights, and realized costs
- 21 trading days: review volatility, drawdown, rolling Sharpe, and breaches
- 63 trading days: review correlation, factor concentration, risk-adjusted performance, and benefit versus cost

The monitoring process compares the decision-time expectation with the realized outcome.

## Invalidation and Escalation

A decision must be reviewed or invalidated when:

- The allocation change causes a new breach
- Realized cost materially exceeds the estimate
- Expected risk improvement fails to appear
- Correlation or concentration rises unexpectedly
- The investment thesis or regime assumption is no longer valid
- The expected benefit remains negative after the review horizon

## Current Prototype Status

The current platform:

- Generates a portfolio-construction proposal
- Runs an independent system risk review
- Produces required modifications and expected impact
- Leaves human reviewer and authority fields unassigned
- Prevents automatic execution
- Creates pending post-decision monitoring checkpoints

This is a research-grade governance workflow. Final institutional use requires named owners, mandate-specific limits, live positions, liquidity data, execution records, and formal approval policy.
