# GPT Report: Universe Foundation

## Short Summary

Built the Universe Management System foundation for the Risk Manager Workstation:

- Added config-driven U.S. equity universe definitions.
- Added typed universe models, provider interfaces, filters, builder, point-in-time helper, quality report, and refresh/API payload services under `src/universe/`.
- Added read-only universe API endpoints.
- Added a dashboard tab: `Universe & Data Coverage`.
- Added point-in-time policy, roadmap, strategy-universe mapping, generated universe artifacts, and focused tests.

No strategy definitions, accounting logic, Combined/N semantics, WQ_ALPHA_018 status, optimizer behavior, or brokerage execution semantics were changed.

## Git Diff Summary

Primary created/modified files:

- `data/config/universe_definitions.yaml`
- `data/config/strategy_universe_mapping.yaml`
- `src/universe/`
- `data/universe/`
- `docs/UNIVERSE_FOUNDATION_AUDIT.md`
- `docs/UNIVERSE_POINT_IN_TIME_POLICY.md`
- `docs/ALPHA_RESEARCH_AND_ML_AFTER_UNIVERSE_ROADMAP.md`
- `scripts/run_workstation_server.py`
- `dashboard/foundation-app.js`
- `dashboard/foundation.css`
- `scripts/verify_dashboard_browser.py`
- `tests/test_universe_definitions.py`
- `tests/test_universe_filters.py`
- `tests/test_universe_builder.py`
- `tests/test_universe_point_in_time.py`
- `tests/test_universe_quality_report.py`
- `tests/test_workstation_server.py`
- `tests/test_phase1_foundation.py`

Pre-existing unrelated dirty files were present at start and were not part of the universe implementation scope:

- `dashboard/data/performance/paper_portfolio_daily.json`
- `dashboard/data/performance/paper_strategy_daily.json`
- `docs/dashboard_data_contract_audit.md`

## Architecture Summary

The new foundation separates universe engineering from strategy research and operations:

- `UniverseDataProvider` defines the future boss API seam.
- `BossApiUniverseProvider` returns structured unavailable/TODO status and does not fake data.
- `ExistingArtifactUniverseProvider` reads committed local artifacts when available and labels them current-membership-only/provisional.
- `PublicFallbackUniverseProvider` is present but explicitly provisional only.
- `UniverseBuilder` loads definitions, applies asset, price, ADV, market cap, stale-data, and data-quality gates, writes versioned snapshots, and emits transparent exclusion reasons.
- `get_universe_members()` enforces `membership_start_date <= signal_date` and `signal_date < membership_end_date` for expired members.

## Universe Definitions Added

- `US_LARGE_CAP_CORE`
- `US_BROAD_MARKET`
- `US_SMALL_CAP`
- `US_ALL_COMMON_RESEARCH`
- `US_TRADABLE_LIQUID`

Global settings include `max_universe_size: 5000`, download chunk size, retry policy, stale-data threshold, PIT default status, and source priority.

## API Endpoints Added

- `GET /api/universe/summary`
- `GET /api/universe/snapshot`
- `GET /api/universe/quality`
- `GET /api/universe/members?universe=US_LARGE_CAP_CORE`

## Dashboard Changes

Added `Universe & Data Coverage` as a top workflow tab and mapped the left-rail `Data` button to it. The tab displays universe counts, candidates, exclusions by reason, data source status, PIT status, last refresh, version, sector coverage, liquidity/market-cap coverage, and warnings.

## Tests Run

- `python -m pytest tests/test_universe_definitions.py tests/test_universe_filters.py tests/test_universe_builder.py tests/test_universe_point_in_time.py tests/test_universe_quality_report.py -q`
  - Result: `18 passed`
- `python -m pytest tests/test_universe_definitions.py tests/test_universe_filters.py tests/test_universe_builder.py tests/test_universe_point_in_time.py tests/test_universe_quality_report.py tests/test_workstation_server.py tests/test_operational_snapshot.py -q`
  - Result: `70 passed`
- `python -m pytest tests/test_phase1_foundation.py tests/test_operational_snapshot.py tests/test_shadow_live_dashboard.py tests/test_production_operational_semantics.py tests/test_wq_alpha018_integration.py -q`
  - Result: `74 passed`
- `python scripts/verify_dashboard_browser.py --no-screenshots`
  - Result: passed, console errors `0`
- Bundled Node check:
  - `C:\Users\linzh\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe --check dashboard/foundation-app.js`
  - Result: passed

## Generated Files

- `data/universe/security_master.csv`
- `data/universe/security_master.parquet`
- `data/universe/universe_membership.csv`
- `data/universe/universe_membership.parquet`
- `data/universe/current_universe_snapshot.json`
- `data/universe/universe_quality_report.json`
- `data/universe/universe_refresh_log.jsonl`

## Known Limitations And Warnings

- Boss universe API is not configured.
- Current committed artifacts provide 503 current S&P-derived candidates, not broad U.S. equity coverage.
- Price, ADV, and market cap are unavailable from committed artifacts, so all configured universes currently have `included_count: 0` and exclusions are driven by missing quantitative fields.
- PIT status is `CURRENT_MEMBERSHIP_ONLY_PROVISIONAL`.
- Current membership is not survivor-bias-free.
- Public/yfinance fallback is not treated as production-grade membership.

## Blockers

No code blocker remains for the foundation. Production-grade population of the universes is blocked on boss-provided or otherwise approved security master, membership, price/volume, market cap, and sector/industry data.

## Clear Next Step

Integrate the boss-provided universe API contract, enrich candidates with price, ADV, market cap, and PIT membership history, then rerun the universe refresh and inspect `Universe & Data Coverage` before starting new alpha research or ML work.
