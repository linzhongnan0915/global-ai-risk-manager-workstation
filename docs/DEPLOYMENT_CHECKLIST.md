# Deployment Checklist

Use this checklist before creating a staging deployment from the clean release repository.

## Repository Cleanliness

- [ ] `git status --short` is clean except expected ignored local output.
- [ ] No files under `output/` are staged.
- [ ] No screenshots, logs, browser temp files, or cache directories are staged.
- [ ] No `.env` files are staged.
- [ ] No secrets, API keys, tokens, passwords, or private credentials are committed.
- [ ] Production runtime does not depend on `D:\Global_Ai`, `C:\Users`, or another developer-local path.

## Verification

- [ ] Focused tests pass:

```powershell
python -m pytest tests/test_phase1_foundation.py tests/test_operational_snapshot.py tests/test_shadow_live_dashboard.py tests/test_production_operational_semantics.py tests/test_wq_alpha018_integration.py -q
```

- [ ] Browser verifier passes:

```powershell
python scripts/verify_dashboard_browser.py --no-screenshots
```

- [ ] JavaScript syntax passes:

```powershell
node --check dashboard/foundation-app.js
```

- [ ] Local dashboard loads:

```powershell
python scripts/run_workstation_server.py
```

- [ ] Browser console has zero errors.
- [ ] API health check returns OK:

```text
GET /api/health
```

- [ ] Manual refresh calls `POST /api/refresh`.
- [ ] Manual refresh preserves the Official Daily Ledger and updates Intraday Estimated NAV/P&L only when delayed data is available.
- [ ] Strategy Monitor summary cards show numeric counts, not N/A.
- [ ] Combined Strategy Monitor row shows derived daily P&L, cumulative P&L, current drawdown, intraday estimated P&L/NAV, and `DERIVED_COMPLETE`.
- [ ] Ordinary active strategy rows show row-level intraday estimated P&L/NAV when delayed refresh data is available.
- [ ] Combined Strategy Detail matches the Strategy Monitor row for NAV/P&L/drawdown/data state/provenance.
- [ ] WQ_ALPHA_018 remains `PRE_OPERATIONAL` / `APPROVED_PENDING` with current sleeve N/A and no current intraday estimate.

## Render Staging Placeholders

- Root directory: repository root
- Runtime: Python 3.12
- Build command placeholder:

```bash
pip install -r requirements.txt
```

- Start command placeholder:

```bash
python scripts/run_workstation_server.py --host 0.0.0.0 --port $PORT
```

- Health check path:

```text
/api/health
```

- Public URL smoke test:

```text
/dashboard/index.html
```

## Required Disclosure In Staging Review

- Initial Shadow Capital: `$1,000,000`
- Real Funded Brokerage Capital: `$0`
- Brokerage Execution: Disabled
- No Live Brokerage Fills
- Official Daily Ledger is distinct from Intraday Estimate.
- Intraday Estimate uses delayed `yfinance` market data.
- A price staleness warning means the portfolio estimate updated but some delayed quote timestamps are stale.
- Daily Performance updates show official daily records plus separate delayed intraday estimates; intraday estimates do not rewrite official daily ledger records.
- Combined strategy NAV/P&L/return rows are derived from real ordinary strategy operational ledgers, not placeholder values.
- WQ_ALPHA_018 remains pending and has no current operational NAV/P&L.

## Page Readiness

READY:

- Command Center
- Strategy Monitor
- Strategy Detail
- Strategy Library & Workflow

MVP_READY:

- Allocation & Rebalance
- Backtesting & Research Lab
- Daily Risk Report

IN_DEVELOPMENT:

- Risk Factors & Exposure
- Correlation & Diversification
- Market & Macro Monitor

BLOCKED:

- none
