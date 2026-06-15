# Platform Remediation v1 — Known Limitations

**Status:** Ready for independent GPT review — **not** institutional or production readiness.

## Data and Financial Truth

- Portfolio metrics use **ETF proxy research data** via yfinance, not boss live positions, fills, or NAV.
- Operating-period metrics (Sharpe, vol, VaR, ES) show **N/A** when observation counts are below configured minimums (e.g., 2-day operating window since 2026-06-04).
- Long-history portfolio charts apply **static current-weight reconstruction** — research diagnostic only, not an investable live track record.
- Treasury-bill / liquidity proxy exposure (e.g., BIL in defensive sleeves) is **not** unallocated residual cash; labels are separated but proxy mapping remains approximate.

## Workflow and Governance

- Human decision events persist in **browser localStorage only**; no server-side audit database.
- Execution authorization remains **disabled**; approval is a human decision record, not trade routing.
- Optimizer is labeled **heuristic score-based proposal, not fully constrained** — not a production portfolio optimizer.
- Risk limits and thresholds in config are **prototype defaults**, not formally approved policy.

## Model and Research

- Walk-forward, stress, and benchmark panels depend on literature backtest artifacts; coverage varies by strategy.
- Factor exposure uses simplified signed proxy loadings, not a validated commercial factor model (Barra/Axioma).
- Macro regime labels are **proxy-level diagnostics** with explicit uncertainty; not release-timed macro inputs.

## UI and Operations

- Risk status drawer is **collapsed by default**; users must open via topbar toggle.
- Some dense tables still scroll horizontally on 1366×768; matrix views use controlled scroll regions.
- Live market/news overlay refresh depends on yfinance availability and network access.

## Out of Scope (Deferred)

- Boss live positions, realized PnL, production execution APIs.
- Authentication, role-based access control, encrypted secrets management.
- Persistent audit trail, report archival, email/Slack alerting.
- Automatic trade execution or broker connectivity.
