# Risk Manager Workstation

Current local staging MVP is ready to commit after final QA. Last pushed `main` remains `a12fb5f` until this staging update is committed and pushed. The app presents a Shadow-Live Paper Portfolio, strategy-level operating records, date-effective membership, delayed intraday estimates, and research evidence without granting brokerage authority.

## Operating Model

- Initial Shadow Capital: `$1,000,000`
- Real Funded Brokerage Capital: `$0`
- Brokerage Execution: Disabled
- Live Brokerage Fills: None
- Execution records: Paper Execution / Paper Fill or explicitly reconstructed paper backfill
- Official Daily Ledger: immutable reconciled close-of-day operating record
- Intraday Estimate: separate delayed-market-data estimate that never rewrites the official ledger
- Daily Performance: official daily records are preserved and delayed intraday NAV/P&L updates are shown separately when refreshed

This repository is not a live brokerage system, not investment advice, and not proof of funded trading.

## Current Release State

Canonical current counts:

- ordinary active strategies: `16`
- Combined active strategy: `1`
- current top-level active sleeves: `17`
- pending candidates: `1`
- total registry entities: `18`

Combined Strategy:

- active top-level sleeve: `1/17 = 5.8823529%`
- definition: a separate active strategy that equal-weights all currently active ordinary strategies
- internal constituents: `16`
- internal equal weight: `1/16 = 6.25%`
- data state: `DERIVED_COMPLETE`
- Strategy Monitor row metrics: derived daily P&L, cumulative P&L, current drawdown, intraday estimated P&L, and intraday estimated NAV
- Strategy Detail metrics: bound to the same derived Combined ledger as the Strategy Monitor row
- cost treatment: derived from ordinary strategy net returns; no separate Combined trade ledger; no cost double count

WQ_ALPHA_018 / `#000018`:

- status: `PRE_OPERATIONAL` / `APPROVED_PENDING`
- current sleeve weight: `N/A`
- proposed post-admission sleeve: `1/18 = 5.5555556%`
- no current operational NAV, P&L, holdings, trades, or paper fills until canonical evidence exists

## Data Sources And Boundaries

- Operational data is loaded from committed canonical dashboard data under `dashboard/data/`.
- Combined operational NAV/P&L/return records are derived from the real ordinary strategy operational ledgers; they are not placeholder or fabricated chart values.
- Historical research artifacts are loaded from repository-relative canonical research files under `data/research/canonical/`.
- Research evidence remains separate from operational records.
- Delayed market data is sourced through `yfinance` for intraday estimates.
- Delayed quotes may be stale; the UI labels this as a price staleness warning when the portfolio estimate updates but some quote timestamps are old.

## Page Readiness

READY:

- Command Center
- Strategy Monitor
- Strategy Detail
- Strategy Library & Governance

MVP_READY:

- Allocation & Rebalance
- Backtesting & Research Lab
- Daily Risk Report
- Workflow & Shadow-Live Testing

IN_DEVELOPMENT:

- Risk Factors & Exposure
- Correlation & Diversification

BLOCKED:

- none

## Local Run

```powershell
pip install -r requirements.txt
python scripts/run_workstation_server.py
```

Open locally:

```text
http://127.0.0.1:8765/dashboard/index.html
```

The local server also accepts deployment-style host and port flags:

```bash
python scripts/run_workstation_server.py --host 0.0.0.0 --port $PORT
```

## Focused Verification

```powershell
python -m pytest tests/test_phase1_foundation.py tests/test_operational_snapshot.py tests/test_shadow_live_dashboard.py tests/test_production_operational_semantics.py tests/test_wq_alpha018_integration.py -q
python scripts/verify_dashboard_browser.py --no-screenshots
node --check dashboard/foundation-app.js
```

Expected final focused result: `47 passed`, browser verifier PASS, JavaScript syntax PASS, browser console `0` errors.

## Release Docs

- Local release audit: `docs/reviews/LOCAL_RELEASE_AUDIT.md`
- Release manifest: `docs/reviews/RELEASE_MANIFEST.md`
- Deployment checklist: `docs/DEPLOYMENT_CHECKLIST.md`
- Release notes: `RELEASE_NOTES.md`

## Repository Hygiene

Generated runtime output, screenshots, logs, caches, `.env` files, and local browser artifacts are ignored. The clean release source lives in `dashboard/`, `src/`, `scripts/`, `data/config/`, `data/research/canonical/`, `docs/`, and `tests/`.
