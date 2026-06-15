# Release Manifest

Final release candidate SHA: `47a3a88241a642ab67a6b4956b73cad0e7d9f687`
Clean package commit: `ada52873adcd3c361557f548a8151e0e1d93de84`
Final binding hotfix commit: `47a3a88241a642ab67a6b4956b73cad0e7d9f687`
Phase: Final Release Package Refresh
Branch: `ui/phase1-foundation`

## Release Pages

- Command Center
- Strategy Monitor
- Allocation & Rebalance
- Risk Factors & Exposure
- Correlation & Diversification
- Market & Macro Monitor
- Backtesting & Research Lab
- Strategy Library & Workflow
- Daily Risk Report

## Data Sources

- `dashboard/data/canonical_operational.json`
- `dashboard/data/shadow_live_bundle.json`
- `data/config/strategy_research_mapping.json`
- `data/research/canonical/`
- delayed market data through `yfinance` for intraday estimates

## Final Accepted State

- Command Center: READY
- Strategy Monitor: READY
- Strategy Detail: READY
- Strategy Library & Workflow: READY
- Refresh / Intraday P&L: PASS
- Combined derived ledger: PASS
- Combined row metrics: PASS
- Ordinary strategy intraday rows: PASS
- WQ_ALPHA_018: `PRE_OPERATIONAL` / `APPROVED_PENDING`
- Browser console: `0` errors
- Focused tests: `40 passed`

## Current Counts

- ordinary active strategies: `16`
- Combined active strategy: `1`
- current top-level active sleeves: `17`
- pending candidates: `1`
- total registry entities: `18`
- top-level sleeve weight: `5.8823529%`
- Combined internal constituents: `16`
- Combined internal equal weight: `6.25%`
- WQ_ALPHA_018 proposed post-admission sleeve: `5.5555556%`

## Strategy Monitor Binding

- Combined row data state: `DERIVED_COMPLETE`
- Combined row metrics: derived daily P&L, cumulative P&L, current drawdown, intraday estimated P&L, and intraday estimated NAV
- Ordinary active intraday rows: populated from delayed refresh snapshot when priced holdings are available
- WQ_ALPHA_018 row: current sleeve `N/A`; intraday estimate `N/A`; status remains `PRE_OPERATIONAL` / `APPROVED_PENDING`
- Daily Performance: official daily ledger remains immutable; delayed intraday estimates update separately
- Combined operational records: derived from ordinary strategy operational ledgers, not placeholder charts or fabricated values

## Intended Release Files

- `dashboard/`
- `src/`
- `scripts/` required for runtime and validation
- `data/config/`
- `data/research/canonical/`
- `docs/reviews/`
- `tests/`
- `README.md`
- `RELEASE_NOTES.md`
- `AGENTS.md`
- `docs/DEPLOYMENT_CHECKLIST.md`
- `pyproject.toml`
- `requirements.txt`
- `requirements-dev.txt`
- `render.yaml`

## Ignored / Excluded Generated Files

- `output/`
- screenshots
- logs
- browser temp files
- Python caches
- pytest/mypy/ruff caches
- `node_modules/`
- `.env` and `.env.*`
- local-only market data caches
- large raw legacy data

## Known Blockers And Caveats

- No release blockers for local staging review.
- Intraday estimates are delayed market-data estimates and are never official ledger records.
- Price staleness warning can appear when all holdings are priced but some quote timestamps are stale.
- WQ_ALPHA_018 is research-connected but remains `PRE_OPERATIONAL` / `APPROVED_PENDING`.
- VaR, expected shortfall, macro regime, and operational correlation remain gated until canonical artifacts exist.

## No Push / Deploy Confirmation

- Pushed: NO
- Deployed: NO
- Render service modified: NO
- Repository `render.yaml` staging defaults updated: YES
