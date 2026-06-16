# Release Notes - Staging MVP

## Summary

This release turns the dashboard into a polished shadow-live paper portfolio workstation with clear official-vs-intraday separation, workflow/governance tabs, intraday overlay support, and guarded official promotion readiness.

The workstation is not a live brokerage trading system. Real Funded Brokerage Capital is `$0`, Brokerage Execution is `Disabled`, and no live brokerage fill is represented.

## Major Changes

1. Command Center polish and official/delayed estimate separation.
2. Delayed intraday overlay via `/api/refresh` and `output/operational_intraday_overlay.json`.
3. Trading-session lifecycle states that distinguish official ledger records from delayed estimates.
4. Official promotion readiness and dry-run only controls, with current state `BLOCKED_SAFE`.
5. New `Workflow & Shadow-Live Testing` tab for strategy development, paper-only testing, admission gates, risk review, and release control.
6. New `Strategy Library & Governance` tab for canonical inputs, transformation lineage, evidence gates, operating authority, and blocked gaps.
7. Real left rail navigation synchronized with top-level dashboard tabs.
8. `STYLE / FAMILY EXPOSURE PROXY` wording to avoid fabricated factor exposure claims.
9. `Paper Provenance Pending` boss-visible label for incomplete paper provenance.
10. Strategy drawer KPI cleanup with long execution/provenance context moved into narrative panels.
11. Combined strategy semantic protection.
12. WQ_ALPHA_018 / #000018 pending/pre-operational protection.
13. Risk, correlation, research lab, and daily report staging polish.
14. Mojibake and corrupted separator cleanup in dashboard-visible sources.

## Data Integrity Notes

- Official ledger records use `portfolio_daily.date`.
- Delayed estimate data is represented as an overlay only.
- Delayed estimate data does not mutate `portfolio_daily`.
- No delayed estimate is shown as an official ledger record.
- Official promotion is blocked until required canonical inputs are complete.
- NEXT_OPEN_TO_OPEN accounting remains unchanged.

## Portfolio and Strategy Semantics

- Initial Shadow Capital: `$1,000,000`
- Real Funded Brokerage Capital: `$0`
- Brokerage Execution: `Disabled`
- No Live Brokerage Fill
- Active top-level sleeves: `17`
- Ordinary active strategies: `16`
- Active Combined strategy: `1`
- Combined is an independent active top-level sleeve.
- Combined derives from 16 ordinary active strategies with internal weight `1/16 = 6.25%`.
- Combined has no separate paper fills and no cost double count.
- WQ_ALPHA_018 / #000018 remains `APPROVED_PENDING / PRE_OPERATIONAL`.
- #000018 has no current sleeve, no operational NAV/P&L, no paper fill, and no live brokerage fill.

## Known Limitations

- Official ledger promotion execute mode is deferred.
- Official promotion is currently `BLOCKED_SAFE`.
- A prior guarded official attempt found a SEC/fundamental facts schema issue: `KeyError: 'ticker'`.
- The official daily ledger pipeline must be repaired before safe official pipeline execution.
- VaR remains blocked/not loaded.
- Expected Shortfall remains blocked/not loaded.
- Validated factor model and factor contribution remain blocked/not loaded.
- Scenario shock analytics remain blocked/not loaded.
- Macro regime classification remains blocked/not loaded.
- Correlation requires sufficient operational history.
- Bloomberg, Morningstar, Factiva, and CRSP feeds are not represented as loaded.
- External institutional data research is tracked separately.

## Validation Summary

- Main dashboard and operational semantic suite: `47 passed`
- Intraday/server/EOD promotion suite: `43 passed`
- Browser verifier: passed
- Browser console errors: `0`
- Geometry pass: `true`
- JavaScript syntax checks: passed
- Python compile checks: passed

## Deployment Note

This staging MVP has not yet been committed, pushed, or deployed.
