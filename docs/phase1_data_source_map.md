# Phase 1 Canonical Data-Source Map

Current operational rendering reads only
`dashboard/data/canonical_operational.json`, generated from the committed local
`dashboard/data/shadow_live_bundle.json`.

| Source | File / API location | Primary key | Date field | Strategy ID field | Expected consumers | Classification |
|---|---|---|---|---|---|---|
| Current strategy registry | `shadow_live.strategy_summary` and `shadow_live.strategy_details` in `dashboard/data/shadow_live_bundle.json` | `strategy_id` | `date` / `membership_effective_date` | `strategy_id` | Strategies, preview drawer | Canonical operational |
| Combined Portfolio membership | `shadow_live.membership_timeline` plus current executed registry | effective date + strategy ID | `effective_date` | `strategy_added` / derived member IDs | Top bar, Combined Portfolio, Daily Performance | Canonical operational |
| Portfolio daily ledger | `shadow_live.portfolio_ledger` | `date` + `run_id` | `date` | N/A | Preview metrics and chart, Daily Performance | Canonical operational |
| Strategy daily ledger | `shadow_live.strategy_summary` | `strategy_id` + `date` + `run_id` | `date` | `strategy_id` | Strategies, Daily Performance | Canonical operational |
| Holdings | `shadow_live.holdings` | `date` + `strategy_id` + `ticker` + `run_id` | `date` | `strategy_id` | Combined Portfolio, strategy detail | Canonical operational |
| Trade Log | `shadow_live.trades` | `trade_id` | `execution_date` | `strategy_id` | Trade Log | Canonical operational |
| Operational status | top-level operational flags plus `shadow_live` status fields | `last_successful_run` | `latest_raw_data_timestamp` | N/A | Top status bar, alerts | Canonical operational |
| Pending strategy membership | `shadow_live.membership_timeline`, `strategy_details`, `pending_targets` | `strategy_id` + effective date | `membership_effective_date` / `expected_execution_date` | `strategy_id` | Top bar, Strategies, drawer | Canonical operational |
| Research evidence availability | presence of accepted evidence in `shadow_live.strategy_details` | `strategy_id` | evidence-specific | object key / `strategy_id` | Strategies and drawer availability state | Canonical availability only |

## Legacy Sources Blocked From Current Rendering

The following remain in the repository for history or non-Phase-1 workflows,
but are not loaded by the default application entry:

| Legacy source or behavior | Location / marker | Block |
|---|---|---|
| Monolithic dashboard artifact and proxy NAV/P&L | `output/dashboard_artifact.json` | Default page and server startup do not load it |
| Legacy ETF/proxy registry | `data/config/strategy_registry.json` | Excluded by canonical builder validation |
| Old fixed allocations | `target_weight` values in legacy registry | Not read; membership weights come from date-effective operational source |
| Monitored-20 / allocated-10 model | legacy dashboard semantics | Fields absent from canonical contract and shell |
| Market/news refresh overlays | `/api/live-summary`, refresh services, `output/live_overlay.json` | Not called or initialized on default page load |
| Stale fallback objects | legacy `dashboard/app.js` fallback data | Legacy script is not loaded by default entry |
| Research catalog and retained proxy registries | `data/config/strategy_research_catalog.json`, `retained_strategy_registry.json` | Not read by canonical operational builder |

Historical files are intentionally retained.
