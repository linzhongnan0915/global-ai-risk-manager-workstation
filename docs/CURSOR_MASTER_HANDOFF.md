# Cursor Master Handoff: Risk Manager Platform

## Role And Objective

Act as a senior quantitative risk engineer and institutional product designer. Continue the existing project in `D:\Global_Ai\risk_manager_platform`.

This is a hedge fund / asset manager multi-strategy portfolio risk management workstation. It is not a retail investing dashboard, single-strategy dashboard, stock screener, or marketing page.

Do not redesign blindly. Read the project contracts, inspect the generated artifact, run the application, and verify every change.

## Read First

Read these files before editing:

1. `README.md`
2. `docs/risk_manager_workstation_contract.md`
3. `docs/workstation_ui_reference_contract.md`
4. `docs/platform_workflow_reset.md`
5. `docs/strategy_return_risk_packet.md`
6. `docs/institutional_decision_workflow.md`
7. `docs/PROJECT_STATE.md`
8. `docs/NEXT_ACTIONS.md`
9. `data/config/workstation_ui_contract.json`
10. `data/config/dashboard_artifact_contract.json`
11. `data/config/strategy_registry.json`
12. `data/config/risk_limits.yaml`
13. `data/config/allocation_policy.yaml`
14. `output/dashboard_artifact.json`
15. `dashboard/index.html`, `dashboard/styles.css`, `dashboard/app.js`

## Non-Negotiable Truths

- Initial capital is `$1,000,000`; portfolio operating start date is `2026-06-04`.
- Monitor 20 strategies now and support 30-40 later.
- All strategies coexist. Research-only strategies have zero live allocation.
- Research-quality failures are not live breaches.
- Historical max drawdown is research evidence, not automatically a current live breach.
- Transaction cost is 5 bps buy and 5 bps sell.
- No real allocation change is automatically executed.
- Every decision requires human approval and an audit trail.
- No allocation increase without backtest evidence, walk-forward evidence, eligibility, and risk review.
- Optimizer must consider diversification, correlation, drawdown, turnover, cost, factor concentration, and limits. Never blindly maximize Sharpe.
- Negative correlation is a potential hedge relationship, not duplicate exposure.
- High positive correlation is duplicate exposure risk.
- All recommendations must be double-checked and show expected before/after impact.

## Current Verified State

- 20 monitored strategies: 10 allocated and 10 research-only.
- Allocated strategy-level live breaches: 0.
- Current hard portfolio/factor breaches: equity beta and credit spread.
- Friday daily portfolio PnL is approximately `-$6,893`.
- Positive offsets: Event-Driven Sector Risk Proxy `+$430`, Managed Futures Trend Proxy `+$44`, Commodity Inflation Shock Sleeve `+$44`.
- Seven allocated strategies lost money.
- Current system conclusion: `Modify Then Human Review`.
- Test baseline: `25 passed`.
- Framework validation passes.

## First Task: Documentation And Contract Audit

Before new features, reconcile documentation with actual implementation.

1. Update `README.md`, `docs/PROJECT_STATE.md`, and `docs/NEXT_ACTIONS.md`.
2. Remove stale statements that strategies, long-history backtests, walk-forward results, and limits are merely placeholders.
3. Clearly label what is real yfinance ETF-proxy research versus what remains provisional.
4. Reconcile `data/config/dashboard_artifact_contract.json` with the actual shape of `output/dashboard_artifact.json`.
5. Reconcile `data/config/workstation_ui_contract.json` with the user's requirements:
   - Remove any requirement for meaningless allocation donuts or fake risk scores.
   - Require useful tables, charts, limit explanations, drilldowns, and decision controls.
6. Create `docs/REQUIREMENTS_TRACEABILITY.md` mapping every user requirement to:
   - contract/config field
   - backend implementation
   - dashboard surface
   - test
   - status: complete / partial / missing

Do not hide missing work. Mark it explicitly.

## Second Task: Correct Remaining Risk Logic

Audit all calculations and decisions for financial and statistical consistency.

1. Ensure portfolio and simulated before/after metrics use the same dates, frequency, return definition, cost treatment, and annualization.
2. Do not present a front-end approximation as an official optimizer result.
3. Move rebalance simulation calculations into a tested Python module when practical; expose results through an artifact or local endpoint.
4. Verify:
   - gross vs net return
   - turnover and 5 bps per-side cost
   - VaR sign convention
   - Expected Shortfall sign convention
   - current drawdown vs historical max drawdown
   - rolling windows
   - OOS and walk-forward windows
   - factor exposure aggregation
   - factor-limit utilization
   - correlation duplicate and hedge classification
5. Add tests for all corrected logic.
6. Every proposed rebalance must show:
   - expected benefit and confidence
   - risk before and after
   - factor exposure before and after
   - correlation/diversification before and after
   - turnover and transaction cost
   - remaining breaches and newly created breaches
   - decision limitations

## Third Task: Make The Workstation Truly Operable

Complete every interaction. No dead buttons or read-only fake controls.

### Portfolio Command Center

- Clearly answer what happened today, why, who protected, who lost, and what needs attention.
- Show positive offsets separately from loss drivers.
- Show live breaches separately from research concerns.
- Improve the cumulative return and drawdown chart with readable axes, dates, tooltips, and legends.
- Add direct links from alerts and strategy rows to the relevant detail.

### Strategy Monitor And Detail

- Sortable and filterable 20+ strategy table.
- Clicking a strategy opens a complete detail workspace.
- Detail must include:
  - summary statistics
  - distribution shape
  - tail risk
  - drawdown behavior
  - rolling stability
  - regime breakdown
  - benchmark and other-strategy comparison
  - positions and signal history
  - factor exposure
  - transaction costs
  - failure modes
  - bias controls
  - backtest and walk-forward evidence
  - final risk-manager decision and rationale

### Allocation And Rebalance

- Editable target weights.
- Research-only and ineligible strategies cannot receive allocation.
- Display total invested weight and cash.
- Simulate before/after risk using a consistent backend calculation.
- Show hard blockers, warnings, and required modifications.
- Human reviewer and rationale are mandatory.
- Approve, modify, and reject actions must write to an audit log.
- Approval must never equal execution.

### Risk Factors And Correlation

- Factor matrix must have meaningful row/column labels and tooltips.
- Explain economic meaning, current exposure, limit, utilization, and action.
- Correlation matrix must show real strategy names, clustering, duplicate exposure alerts, hedge relationships, and allocated-only versus full-research views.

### Research Lab

- Strategy picker must update all charts and tables.
- Charts must include gross versus net, equity curve, drawdown, distribution, rolling Sharpe/volatility/correlation, regime performance, worst periods, and walk-forward results.
- Explicitly display IS/OOS dates, train/test window lengths, bias disclosures, data source, and transaction-cost assumptions.

### Daily Report

- Generate a decision-ready daily risk report.
- Include open breaches, strategy alerts, recommended actions, before/after proposal, human decision, and execution status.
- JSON and CSV exports must work.
- Print/PDF layout must be readable.

## Fourth Task: Institutional Visual And UX Upgrade

Match the supplied institutional workstation reference quality.

- Dense, organized, compact, and readable.
- No large empty panels.
- No meaningless donut/risk-score graphics.
- No excessive rounded cards, decorative gradients, or retail-dashboard styling.
- Use green for safe, yellow for watch, orange for warning, and red for breach.
- Preserve neutral colors for research-only/not-live statuses.
- Use professional charts with clear axes, dates, legends, hover values, and consistent colors.
- Prevent all text overflow and broken layouts.
- Make horizontal scrolling deliberate and keep key identifiers sticky.
- Ensure each screen communicates a risk-manager decision, not merely data.
- Test at 1600x900, 1920x1080, and a narrower desktop viewport.

## Required Verification

After each meaningful change:

```powershell
python -m pytest -q
python scripts\validate_framework.py
python scripts\generate_dashboard_artifact.py
```

Run the dashboard:

```powershell
python -m http.server 8765 --bind 127.0.0.1
```

Use browser automation to verify:

- no console errors
- all nine tabs load
- strategy row opens detail
- filters and sorting work
- target weight edit works
- invalid allocation is blocked
- simulation produces consistent before/after metrics
- reviewer and note validation works
- approve/modify/reject writes audit log
- report generation works
- JSON/CSV export works in a normal browser
- no text overflow or incoherent empty space

## Completion Deliverables

1. Updated implementation.
2. Updated documentation and contracts.
3. `docs/REQUIREMENTS_TRACEABILITY.md`.
4. `docs/CURSOR_COMPLETION_REPORT.md` containing:
   - files changed
   - risk logic corrections
   - UI/interaction improvements
   - test results
   - browser verification results
   - remaining limitations
   - screenshots of all nine tabs

Do not claim completion while any required interaction is dead, any decision uses inconsistent metrics, or documentation contradicts the implementation.
