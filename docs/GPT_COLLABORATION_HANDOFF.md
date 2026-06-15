# GPT Collaboration Handoff: Risk Manager Platform

Updated: 2026-06-07

## How To Use This Document

This is the single onboarding document for a new GPT conversation.

The user should be able to provide this file to GPT and continue working without
repeating the project's history, product requirements, learning goals, or
division of responsibilities.

GPT should first help the user understand the problem and define the required
outcome. Codex should then act as either:

1. Project manager and acceptance reviewer; or
2. Implementation engineer.

Do not ask Codex to simultaneously discover an undefined requirement, redesign
the product, implement it, teach every concept, and accept its own work.

---

## User Context And Working Style

The user is learning financial risk management and quantitative finance through
this project. The goal is not only to satisfy the boss's minimum request. The
user wants to understand and practice a realistic institutional risk-manager
workflow.

Communication preferences:

- Explain private learning content in Chinese.
- Keep professional finance and engineering terms in English.
- Write external-facing repository documents and dashboard copy in polished
  English.
- Be direct and honest. Challenge weak assumptions and unsupported decisions.
- Teach the user how to interpret the output and defend it in a meeting.
- Separate verified facts, model estimates, assumptions, limitations, and human
  judgment.
- Do not treat passing tests as proof that financial logic is correct.

When teaching a metric or model, explain:

1. What it measures.
2. Why it matters.
3. What assumptions it uses.
4. What can make it misleading.
5. Which risk-management decision it could change.

---

## Project Identity

Workspace:

`D:\Global_Ai\risk_manager_platform`

This project is an institutional hedge fund / asset manager style
**multi-strategy portfolio risk management workstation**.

It is not:

- A retail investing dashboard.
- A stock quote board.
- A landing page.
- A single-strategy dashboard.
- An automated trading or execution system.
- A decorative collection of charts.

The platform must help an independent risk manager monitor, challenge, and
document decisions across 20 strategies now, with a design that scales to
30-40 strategies.

Portfolio truths:

- Portfolio operating start date: `2026-06-04`.
- Initial capital: `$1,000,000`.
- All strategies coexist simultaneously.
- Research-only strategies must have zero live allocation.
- Transaction costs: 5 bps buy, 5 bps sell, 10 bps round trip.
- All real allocation changes require human approval.
- Approval never equals execution.

---

## Daily Questions The Platform Must Answer

1. What happened to the portfolio today?
2. Which strategies made or lost money, and why?
3. Was each gain or loss consistent with the strategy's intended behavior?
4. Which portfolio, strategy, factor, correlation, data-quality, or governance
   limits were triggered?
5. Which strategies need Keep, Watch, Reduce, Hedge, Pause, Rebalance, Retire,
   Research Hold, or Human Review?
6. If a rebalance is proposed, what does it cost and how does expected risk
   change before versus after?
7. Does the proposed change create new concentration, factor, tail, liquidity,
   turnover, or correlation risks?
8. Which recommendations require human approval?
9. Which strategies cannot receive allocation because evidence is missing?
10. What should be monitored after an authorized decision?

---

## Strategy Admission Standard

Every strategy must define:

- Name, family, lifecycle status, and intended portfolio role.
- Economic hypothesis and expected source of return.
- Distinct return driver versus existing strategies.
- Universe and investable instruments.
- Data source, timestamp convention, frequency, and history length.
- Signal definition and signal lag.
- Position construction and sizing.
- Rebalance frequency.
- Transaction costs, turnover, slippage, liquidity, and capacity assumptions.
- Risk limits and monitoring thresholds.
- Expected favorable and unfavorable regimes.
- Failure modes and pause/retire rules.
- Benchmark.
- Backtest evidence.
- Walk-forward / out-of-sample evidence.
- Factor exposure and correlation to active strategies.
- Data-quality and model limitations.

No strategy recommendation is valid without evidence. A strategy missing
backtest or walk-forward evidence must remain research/pending and cannot
receive live allocation.

Different strategy names do not imply diversification. Strategies that share
the same economic bet, factor exposure, or stress losses must be treated as
duplicate risk. Negative correlation may indicate a hedge relationship, while
high positive correlation may indicate duplicate exposure.

---

## Required Strategy Risk Packet

Every strategy drill-down must contain the following eight sections.

### 1. Summary Statistics

- Daily and cumulative return.
- Annualized return and volatility.
- Sharpe, Sortino, and Calmar.
- Win rate, average win, average loss, payoff ratio, and profit factor.
- Best and worst day.
- Observation count.
- Turnover and transaction-cost drag.

### 2. Distribution Shape

- Histogram and density/KDE where appropriate.
- QQ plot or normality comparison where appropriate.
- Mean, median, standard deviation.
- Skewness, kurtosis, and excess kurtosis.
- Percentiles: P01, P05, P25, P75, P95, P99.
- Outlier count and data-error review.

### 3. Tail Risk

- VaR 95 and VaR 99.
- Expected Shortfall 95 and 99.
- Worst 5 and worst 10 periods.
- Left-tail frequency and tail ratio.
- Stress loss estimates.
- Co-loss behavior during portfolio and market stress.

### 4. Drawdown Behavior

- Equity curve and underwater curve.
- Max and current drawdown.
- Average drawdown.
- Drawdown duration and recovery time.
- Meaningful drawdown episodes.
- Sudden-loss versus slow-bleed behavior.

### 5. Time Stability

- Rolling 21D, 63D, 126D, and 252D Sharpe where history permits.
- Rolling volatility, drawdown, win rate, and turnover.
- Rolling correlation to benchmark and portfolio.
- Recent versus full-history performance.
- Live/paper versus backtest expectation.
- Parameter and signal-decay diagnostics.

### 6. Regime Breakdown

- Equity up/down.
- High/low volatility.
- Credit supportive/stress.
- Rates rising/falling.
- USD up/down.
- Inflation rising/falling.
- Growth acceleration/deceleration.
- Risk-on/risk-off.

For each regime show mean return, volatility, Sharpe, max drawdown, hit rate,
tail loss, and observation count.

### 7. Comparison

- Benchmark beta, correlation, alpha, tracking error, and information ratio
  where appropriate.
- Up capture and down capture.
- Correlation to active strategies and portfolio.
- Factor overlap.
- Marginal and component risk contribution.
- Diversification benefit.

### 8. Final Risk Manager Decision

- Current and proposed allocation.
- Allocation change and trade direction.
- Estimated transaction cost.
- Expected risk before/after.
- Triggered limits and remaining limits.
- Expected benefit, confidence, and limitations.
- Recommended action and reason code.
- Mandatory independent double-check.
- Human approval status.

Never increase a losing strategy merely so it can "win the money back." A loss
can justify maintaining or increasing exposure only when evidence shows the
strategy remains valid, the loss matches an expected regime headwind, limits
remain acceptable, and portfolio-level diversification improves.

---

## Portfolio And Risk Requirements

Portfolio-level analysis must include:

- AUM, Daily/MTD/YTD/cumulative PnL.
- Portfolio return, Sharpe, volatility, max/current drawdown.
- VaR and Expected Shortfall with explicit sign convention.
- Contributors, detractors, and positive offsets.
- Strategy allocation and risk contribution.
- Factor exposure, concentration, and contribution to risk.
- Strategy correlation, duplicate-exposure alerts, and hedge relationships.
- Scenario shocks and historical crisis replay.
- Turnover and transaction-cost impact.
- Current versus proposed allocation and risk.
- Data-quality warnings.
- Rebalance recommendation and human-review status.

Risk limits must always show:

- Metric.
- Current value.
- Threshold.
- Utilization.
- Scope: portfolio, allocated strategy, research quality, factor, data, or
  governance.
- Status: green / yellow / orange / red.
- Required action.

Research-quality failures are not live breaches. Historical max drawdown is
research evidence and must not automatically be presented as a current live
breach.

The optimizer must not blindly maximize Sharpe. It must consider:

- Diversification and duplicate exposures.
- Correlation.
- Drawdown and tail risk.
- Turnover and transaction cost.
- Factor concentration.
- Liquidity/capacity constraints.
- Risk limits and allocation eligibility.
- Expected improvement confidence.
- Human approval.

---

## Backtest And Model-Risk Standards

Every analysis must explicitly document:

- Simple versus log return.
- Data frequency, timezone, and timestamp alignment.
- Annualization convention and risk-free-rate assumption.
- Gross versus net returns.
- Transaction-cost and slippage assumptions.
- In-sample and out-of-sample dates.
- Rolling/window lengths and why they were selected.
- Signal lag and execution timing.
- Look-ahead bias controls.
- Survivorship-bias limitations.
- Missing-data treatment.
- Common-date alignment policy.
- Parameter stability and multiple-testing risk.
- Benchmark/challenger comparison.
- Regime and stress-period performance.

Prefer the longest defensible history, not the longest technically available
series if the older data is not representative or investable.

No output should silently use mismatched dates, `fillna(0)` for missing strategy
returns, or tail-position alignment.

---

## Literature And Strategy Direction

The boss asked the team to become familiar with and incorporate:

- WorldQuant-style formulaic alpha signals.
- Hedge fund replication and liquid alternative risk premia.
- Macro and business-cycle regime allocation.
- Markov regime-switching models.

Relevant source documents:

- `GlobalAi26- DOC- QuantFin_RiskManagement (1).docx`
- `Paper - 101 Alphas - WorldQuant World Quant.pdf`
- `Markov Regimes - JPM Regime-based investing.pdf`
- `Markov Regimes - How Regimes Affect Asset Allocation - By Ang and Bekaert.pdf`
- `Macro Regimes -Dynamic_Asset_Allocation_Through_the_Business_Cycle.pdf`
- `Hedge Fund Replication - Can Hedge Fund Returns be Replicated.pdf`

Institutional interpretation:

- Formulaic alphas should become a diversified alpha research basket, not a
  blindly traded single formula.
- Hedge fund replication should distinguish portable factor beta from residual
  alpha and disclose rolling-estimation risk.
- Regime models should output probabilities and uncertainty, not deterministic
  market labels.
- Regime-aware allocation should make constrained tilts around strategic
  weights, not promise perfect forecasting.
- Qlib may support research and rolling experiments later; it is not a
  substitute for licensed market data, an institutional factor model, or
  governance.

---

## Data And API Policy

Current research data uses yfinance ETF proxies. OpenBB may be added as an
accessible data adapter. Future boss APIs must plug into the same data and
artifact contracts without rewriting strategy logic, risk logic, or dashboard
structure.

Every refresh must record:

- Source and provider.
- Retrieval timestamp.
- Observation date versus release date where relevant.
- Row count and date coverage.
- Missing values and stale-data status.
- Schema/API failures.
- Proxy limitations.

Free/proxy data must be labeled as prototype research data. Never represent it
as boss live positions, fills, returns, or production risk data.

---

## Dashboard Product Contract

Required tabs:

1. Portfolio Command Center.
2. Strategy Monitor.
3. Allocation & Rebalance.
4. Risk Factors & Exposure.
5. Correlation & Diversification.
6. Market & Macro Monitor.
7. Backtesting & Research Lab.
8. Strategy Library & Workflow.
9. Daily Risk Report / Decision Log.

Required interaction:

- All 20+ strategies visible in a dense sortable/filterable table.
- Clicking a strategy opens a complete detail workspace.
- Editable proposed weights with eligibility blocking.
- Backend-consistent before/after simulation.
- Approve / Modify / Reject controls with reviewer and rationale.
- Simulation failure or hard blockers prevent approval/report generation.
- Report generation and export.
- Future periodic data refresh.

Visual direction:

- Institutional dark professional workstation.
- Dense but organized, compact, sharp, and highly scannable.
- Bloomberg / BlackRock / Bridgewater inspired.
- Clear axes, dates, legends, labels, hover values, and thresholds.
- Green safe, yellow watch, orange warning, red breach.

Forbidden patterns:

- Retail dashboard styling.
- Marketing/landing-page composition.
- Unexplained circles, donuts, scores, heatmaps, or risk badges.
- Decorative charts not tied to a risk decision.
- Large empty areas, oversized cards, or excessive rounded panels.
- Fake/static data presented as analysis.
- Controls that do not perform a real action.

---

## Current Implementation State

Current documented state:

- 20 monitored strategies.
- 10 strategies allocated and 10 research-only.
- yfinance ETF-proxy literature backtests.
- One-trading-day signal lag.
- Turnover-based transaction costs.
- Strategy risk packets and walk-forward evidence.
- Artifact-driven nine-tab dashboard.
- Tested Python rebalance simulation through artifact and `/api/simulate`.
- Independent risk review and four-stage governance workflow.

Known partial or missing items:

- Boss live returns, positions, fills, and realized costs are missing.
- Risk limits are provisional research limits and require calibration.
- Human decision log uses browser `localStorage`; no persistent server audit DB.
- Proposed-weight correlation before/after is not recomputed.
- Allocated-only correlation toggle remains partial.
- News/event data is sample/proxy unless a real feed is configured.
- Regime model remains proxy-level, not fully release-timed production logic.
- Print/PDF and multi-viewport QA remain partial.

Open acceptance issue discovered by Codex on 2026-06-06:

- Residual unallocated portfolio cash is returned as `cash_weight`, but is not
  consistently included in factor exposure and cash-limit evaluation.
- Example: 5% invested and 95% residual cash can report 95% `cash_weight` while
  reporting 0% cash factor exposure and an OK cash-factor limit.
- This must be fixed and tested before residual-cash risk logic is considered
  complete.

Do not rely only on completion reports. Verify the current code, generated
artifact, tests, and browser behavior.

---

## Required Reading Order For Any New GPT Or Engineer

Read before proposing substantial changes:

1. `docs/GPT_COLLABORATION_HANDOFF.md`
2. `docs/risk_manager_workstation_contract.md`
3. `docs/workstation_ui_reference_contract.md`
4. `docs/strategy_return_risk_packet.md`
5. `docs/strategy_intake_workflow.md`
6. `docs/institutional_decision_workflow.md`
7. `docs/boss_literature_intake_2026_06_05.md`
8. `docs/PROJECT_STATE.md`
9. `docs/NEXT_ACTIONS.md`
10. `docs/REQUIREMENTS_TRACEABILITY.md`
11. `data/config/strategy_registry.json`
12. `data/config/risk_limits.yaml`
13. `data/config/allocation_policy.yaml`
14. `data/config/workstation_ui_contract.json`
15. `data/config/dashboard_artifact_contract.json`
16. `output/dashboard_artifact.json`

Relevant personalized Codex skills:

- `C:\Users\linzh\.codex\skills\live-strategy-risk-manager\SKILL.md`
- `C:\Users\linzh\.codex\skills\finance-risk-workflow\SKILL.md`
- `C:\Users\linzh\.codex\skills\impeccable\SKILL.md` for UI polish work.
- `C:\Users\linzh\.codex\skills\ui-ux-pro-max\SKILL.md` for UI/UX work.

---

## Three-Party Collaboration Model

### User Owns

- Business intent and priorities.
- Questions, preferences, and final human judgment.
- Approval of risk limits and real allocation decisions.
- Learning and ability to explain the work.

### GPT Owns: Discovery, Learning, And Task Definition

GPT should:

- Help the user understand the finance/risk concept.
- Clarify the decision the requested feature supports.
- Translate vague ideas into a precise requirement.
- Identify assumptions, alternatives, and risks.
- Define acceptance criteria before implementation.
- Produce a bounded task specification for Codex.
- Help the user interpret completed outputs.

GPT should not:

- Pretend an undefined requirement is ready for implementation.
- Invent numerical thresholds without labeling them provisional.
- Approve real allocations.
- Treat UI polish as a substitute for correct risk logic.
- Send Codex an unbounded request such as "finish the platform."

### Codex Owns: Project Management, Implementation, Or Acceptance

For each task, explicitly choose one Codex mode:

**Mode A: Project Manager / Acceptance Reviewer**

- Inspect implementation and documentation.
- Track requirements, dependencies, and priorities.
- Review code and financial logic.
- Run tests and browser verification.
- Report findings before summaries.
- Reject work that is statistically, financially, or operationally inconsistent.
- Do not implement unless the user explicitly changes the role.

**Mode B: Implementation Engineer**

- Read relevant contracts and current code.
- Implement the bounded task.
- Add tests and update contracts/docs.
- Run verification.
- Produce a handoff for independent review.
- Do not self-declare institutional correctness merely because tests pass.

Whenever practical, implementation and final acceptance should be separate
passes.

---

## GPT To Codex Task Specification Template

GPT must provide the following before asking Codex to implement:

```text
CODEX TASK SPEC

Codex role:
- Project Manager / Acceptance Reviewer
  OR
- Implementation Engineer

Objective:
- One concrete outcome.

Decision supported:
- Which risk-manager question or workflow decision this improves.

Why now:
- Priority and dependency.

In scope:
- Explicit behaviors, modules, and files where known.

Out of scope:
- Work Codex must not expand into.

Financial logic:
- Definitions, formulas, sign conventions, alignment, cost assumptions,
  limits, and expected behavior.

Data contract:
- Inputs, outputs, source, date/frequency rules, missing-data policy, and
  provisional/live labels.

UI/interaction contract:
- What the user can see, click, edit, decide, and export.

Acceptance criteria:
- Observable pass/fail statements.

Required tests:
- Unit, integration, artifact, browser, and financial sanity checks.

Required documentation updates:
- Contracts, traceability, state, limitations, and learning notes.

Known risks/open questions:
- Anything not yet resolved.
```

If important fields are unknown, GPT should resolve them with the user before
implementation or explicitly mark them as assumptions requiring confirmation.

---

## Codex Return Template

After implementation, Codex should return:

```text
CODEX HANDOFF

Task:
- What was completed.

Files changed:
- File, type, and purpose.

Behavior changed:
- User-visible and risk-logic changes.

Financial assumptions:
- Return, cost, dates, alignment, limits, and model assumptions.

Tests and verification:
- Exact commands and results.

Generated files:
- Regenerable outputs.

Known risks and limitations:
- Explicit partial/missing items.

Acceptance recommendation:
- Ready for independent review / not ready, with reason.
```

An acceptance reviewer must independently check the handoff against the code,
artifact, financial meaning, and browser behavior.

---

## Efficient Working Protocol

To reduce token and rework cost:

1. GPT and user discuss one bounded problem at a time.
2. GPT explains the concept and freezes a task specification.
3. User chooses Codex as reviewer/project manager or implementation engineer.
4. Codex reads only relevant files, implements or reviews, and verifies.
5. GPT helps the user interpret the result and choose the next priority.
6. Update this document only when a durable project truth changes.

Do not start UI work before the underlying data, financial logic, and decision
workflow are defined. Do not add a metric unless the user can learn what
decision it supports.

---

## Suggested Next Task

First close the residual-cash semantic inconsistency:

- Decide whether unallocated portfolio cash should be represented as the
  existing `cash` factor or a distinct `portfolio_residual_cash` factor.
- Ensure factor exposure and cash-limit evaluation include it.
- Add regression and browser/API checks.
- Reconcile `REQUIREMENTS_TRACEABILITY.md` and completion reports.

After that, prioritize:

1. Calibrate provisional risk limits and document the rationale.
2. Recompute correlation/diversification impact for proposed allocations.
3. Add persistent server-side decision/audit storage.
4. Improve institutional UX only after the related risk logic is verified.
5. Replace proxy data with boss APIs when available without changing contracts.

