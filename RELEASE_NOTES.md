# Release Notes

## Final Local Release Candidate: `47a3a88241a642ab67a6b4956b73cad0e7d9f687`

This release packages the Phase 1 Risk Manager Workstation for a clean GitHub repository and Render staging preparation after the final Strategy Monitor Combined and intraday row binding hotfix.

## Highlights

- Command Center now presents official daily NAV/P&L separately from delayed intraday estimates.
- Strategy Monitor and Strategy Detail use the accepted count contract: 16 ordinary active strategies plus the active Combined strategy, with WQ_ALPHA_018 pending.
- Strategy Monitor summary cards show explicit numeric counts: total registry entities, ordinary active, current top-level active, pending candidates, Combined constituents, top-level sleeve weight, and Combined internal weight.
- Combined is modeled as its own active top-level strategy sleeve and derives real daily P&L, cumulative P&L, current drawdown, return, and intraday estimate fields from ordinary strategy operational ledgers.
- Ordinary active strategy rows bind row-level intraday estimated P&L/NAV when delayed refresh data is available instead of showing blanket N/A.
- Historical Research is connected from repository-relative canonical artifacts and remains separate from operational records.
- Strategy Library & Workflow documents data inputs, research artifacts, membership, paper execution, holdings, Combined, and dashboard contract state.
- Refresh / intraday P&L estimates use delayed market data and show coverage plus price staleness warnings when quote timestamps are stale.
- Daily Performance preserves official daily records while delayed intraday estimates update separately; refreshed intraday values never overwrite the official ledger.
- Incomplete pages are gated honestly with `IN_DEVELOPMENT` readiness and unavailable/blocker fields rather than fake charts or zero-filled values.

## Current Count Contract

- ordinary active strategies: 16
- Combined active strategy: 1
- current top-level active sleeves: 17
- pending candidates: 1
- total registry entities: 18
- top-level sleeve weight: 5.8823529%
- Combined internal constituents: 16
- Combined internal weight: 6.25%
- WQ_ALPHA_018 proposed post-admission sleeve: 5.5555556%

## Final Accepted State

- Command Center: READY
- Strategy Monitor: READY
- Strategy Detail: READY
- Strategy Library & Workflow: READY
- Refresh / Intraday P&L: PASS
- Combined derived ledger: PASS
- Combined row metrics: PASS
- Ordinary strategy intraday rows: PASS
- WQ_ALPHA_018: PRE_OPERATIONAL / APPROVED_PENDING
- Browser console: 0 errors

## Known Caveats

- Brokerage execution remains disabled.
- Real funded brokerage capital remains `$0`.
- There are no live brokerage fills.
- Intraday estimates use delayed `yfinance` quotes and are not official ledger entries.
- A full portfolio estimate may be available while some quote timestamps are stale; the UI labels this as `PRICE STALENESS WARNING`.
- VaR, expected shortfall, macro regime, and operational correlation are gated until canonical data/model artifacts exist.
- WQ_ALPHA_018 is research-connected but remains `PRE_OPERATIONAL` / `APPROVED_PENDING` until canonical signal, target, price, trade, position, and verified execution evidence exist.

## Verification

- Focused tests: `40 passed`
- Browser validation: PASS
- JavaScript syntax: PASS
- Console errors: `0`

See `docs/reviews/LOCAL_RELEASE_AUDIT.md` for the detailed audit.
