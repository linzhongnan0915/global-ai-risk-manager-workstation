# GlobalAI A1 Open Items and Cautions

## Purpose
- PASS with CAUTION means mergeable but unfinished work must be tracked.
- This file is the durable backlog for known unfinished A1/A1.5/A2 scaffold items.
- Do not remove items unless a PR explicitly resolves them.

## Current status summary
- Backend evidence foundation mostly completed.
- Dashboard/source-of-truth layer still incomplete.
- A1 is not final until Command Center, Strategy Intelligence, Daily Report, Allocation, and automation are correctly wired.

## A1 Open Items

1. Command Center source-of-truth and freshness
Status: PARTIAL
Already done:
- direct-state startup work merged in PR #20
- source labels added for NAV / Daily P&L / chart / portfolio date
Still open:
- verify new strategy additions update tables/charts correctly
- verify daily P&L/date/chart freshness across paper daily / official ledger / delayed estimate
- ensure stale/fallback states are visually clear
- avoid fake empty dashboard and fake zeros
Next PR:
- Command Center freshness verification / post-merge audit if needed

2. Daily Allocation Recommendation Engine
Status: NOT DONE
Requirement:
- every eligible strategy must receive a daily recommended target weight
- output recommended_weight, current_weight, delta, action, rationale, evidence status, risk status
- actions: HOLD / INCREASE / REDUCE / REVIEW / ZERO_WEIGHT
- no hardcoded strategy names/counts/weights
- no paper apply
Next PR:
- daily allocation recommendation artifact/spec

3. Biweekly Rebalance Proposal
Status: NOT DONE
Requirement:
- every two weeks generate paper rebalance proposal from latest recommendation targets
- compare current vs recommended target
- include cost/drift/min/max/risk/evidence constraints
- proposal only; user confirmation required for accept/apply
- no automatic paper apply
Next PR:
- biweekly rebalance proposal artifact/spec

4. Allocation page cleanup
Status: NOT DONE
Requirement:
- current / recommended / proposed / approved / applied / legacy manual states must be visually separated
- useful table should be primary
- empty P0 proposal should not dominate first screen
- legacy/manual draft collapsed
- approve/apply safety unchanged
Next PR:
- Allocation UI structure cleanup

5. Daily Report UI artifact wiring
Status: NOT DONE
Already done:
- daily_report_artifact_v0 backend exists
Still open:
- Daily Report tab must read /api/automation-intelligence/daily-report/latest
- show Summary / Portfolio & Allocation / Evidence & Risk / Actions
- missing artifact state must be compact and honest
- frontend must not invent report content
Next PR:
- Daily Report UI artifact wiring

6. Strategy Intelligence all-strategy overview
Status: PARTIAL
Already done:
- Strategy Intelligence reads risk evidence
- evidence/missing evidence fields exist
Still open:
- make Strategy Intelligence the main strategy overview
- show all strategies clearly with action/evidence/risk/ML/attribution/missing evidence
- Strategy Monitor should be Advanced/operational, not main boss-facing strategy quality page
Next PR:
- Strategy Intelligence overview enhancement

7. Risk / Evidence page
Status: NOT DONE
Requirement:
- directly surface latest risk_evidence_artifact_v0
- show VaR/CVaR insufficient history honestly
- show drawdown/vol computed when artifact says computed
- show missing risk evidence labels
Next PR:
- Risk Evidence UI wiring

8. Advanced / Legacy tools cleanup
Status: NOT DONE
Requirement:
- Advanced should be a clean landing page
- contain Strategy Monitor, Universe/Data, Correlation, Workflow, Library/Governance, Diagnostics
- Correlation should stay out of top nav
- do not delete backend capabilities
Next PR:
- Advanced tools cleanup

9. Strategy Monitor role clarification
Status: NOT DONE
Requirement:
- Strategy Monitor = operational/performance table
- Strategy Intelligence = strategy evidence/quality overview
- labels/navigation should make the difference clear
Next PR:
- Strategy Intelligence / Advanced nav cleanup

10. A1 evidence pack / boss package
Status: NOT DONE
Requirement:
- screenshots
- merged PR list
- artifact list
- source-of-truth map
- safety statement
- missing evidence list
- A2 next-step plan
Next PR:
- A1 evidence pack docs/export

## A1.5 Automation Open Items

11. Daily automation control layer
Status: NOT DONE
Requirement:
- daily cycle should generate/update:
  - operational snapshot status
  - risk evidence artifact
  - Strategy Intelligence summary
  - Daily Report artifact
  - daily allocation recommendation
  - warnings / missing evidence / next actions
- failure states must be visible
- no automatic apply
Next PR:
- automation control layer spec

12. Full auto but paper-safe workflow
Status: NOT DONE
Requirement:
- auto-generate recommendations and proposals
- manual confirmation for accept/apply
- no live trading
- no brokerage execution
Next PR:
- A1.5 automation safety spec

## A2 Scaffold Open Items

13. ML evidence artifact schema
Status: NOT DONE
Include:
- feature set
- target
- model family
- baseline comparison
- train/test split
- OOS / walk-forward
- leakage checks
- explainability status
- missing evidence labels

14. Robustness / walk-forward artifact schema
Status: NOT DONE

15. Regime evidence schema
Status: NOT DONE

16. SHAP / feature importance / attribution placeholders
Status: NOT DONE

17. Optimizer input/output contract
Status: NOT DONE
Include:
- current weights
- recommended weights
- constraints
- risk budget
- costs
- missing evidence penalties
- proposal-only output

## Permanent safety rules
- no hardcoded strategy names/counts/weights/dates/NAV/P&L
- no fake VaR/CVaR/ML/attribution/correlation
- no NAV/P&L mutation from GET/report/dashboard pages
- no paper apply/approve changes unless explicitly scoped
- no backend changes in UI-only PRs
- no generated data/** or output/** staged
- no live trading

## Maintenance rule
Every future GPT PR verdict with CAUTION must either:
1. add a new item to this file, or
2. mark an existing item as resolved by PR number.
