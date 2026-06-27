# Universe Foundation Audit

## Scope

This audit covers the production release repository at `D:\Global_Ai\release_global_ai_risk_manager_workstation`.
It does not use or modify the old `Risk_Manager_Platform` repository.

## Existing Data Folders

- `data/config/` contains platform, strategy, risk, dashboard, intraday, allocation, and market proxy configuration.
- `data/raw/` contains local raw market or SEC cache landing areas.
- `data/processed/` contains processed yfinance market price history.
- `data/reference/` exists but currently has no shared production security master artifact committed.
- `data/research/canonical/` contains historical research artifacts, kept separate from operational records.
- `dashboard/data/` contains committed operational dashboard artifacts, including canonical operational data, shadow-live bundle, market proxy cache, and a current S&P 500 reference artifact.
- `output/` is generated runtime output and should remain unstaged.

## Existing Config Files

- `data/config/market_universe.json` is an ETF/index proxy universe used by the current yfinance fallback layer.
- `data/config/strategy_registry.json`, `strategy_research_mapping.json`, `strategy_research_catalog.json`, and `retained_strategy_registry.json` describe strategy registry/research mappings.
- `data/config/platform_config.yaml`, `risk_limits.yaml`, `intraday_refresh.yaml`, `missing_data_policy.yaml`, and allocation/dashboard contracts govern platform behavior.
- No shared `universe_definitions.yaml` exists yet for formal U.S. equity universe tiers.

## Existing Strategy Registry And Universe Logic

- Strategy registry entries currently contain per-strategy ETF/proxy ticker lists or migrated strategy metadata.
- `src/strategies/worldquant/universe.py` builds a current-listed U.S. security master from Nasdaq Trader symbol-directory text and explicitly warns that it is current-listed only.
- `src/strategies/worldquant/research_universe.py` filters that master into a WorldQuant-specific research universe.
- `src/strategies/worldquant/pilot_universe.py` creates a deterministic 500-security pilot sample for validation; this is not a production broad-market universe.
- `src/strategies/universe_foundation.py` contains earlier point-in-time helper functions and diagnostic broad/small-cap membership utilities, but it is strategy/research scoped rather than a shared platform universe service.

## Existing API Snapshot Structure

- `scripts/run_workstation_server.py` serves the dashboard with `http.server`.
- The default dashboard load uses `GET /api/operational-snapshot`.
- Existing routes include `/api/health`, `/api/live-summary`, `/api/artifact/bootstrap`, `/api/artifact/research`, `/api/paper-rebalance`, `/api/refresh/status`, `/api/snapshot/latest`, `/api/refresh-data`, and `/api/simulate`.
- There are no `/api/universe/*` endpoints yet.

## Existing Dashboard Tabs

- The foundation app currently has these workflow tabs: Portfolio Command Center, Strategy Monitor, Allocation & Rebalance, Risk Factors & Exposure, Correlation & Diversification, Workflow & Shadow-Live Testing, Backtesting & Research Lab, Strategy Library & Governance, and Daily Risk Report.
- The left rail maps `Data` to Workflow & Shadow-Live Testing.
- There is no dedicated Universe & Data Coverage tab.

## Existing Tests

- The test suite is broad and includes operational snapshot, dashboard, strategy registry, market data, WorldQuant Alpha #2, point-in-time, and deployment readiness coverage.
- Existing universe-related tests include `tests/test_universe_foundation.py`, WorldQuant security master/research/pilot universe tests, and S&P 500 reference artifact tests.
- There are no shared `src/universe` tests yet for config-driven definitions, filters, builder output, API contract, or dashboard universe coverage.

## Existing Market Data Services

- `src/market/yfinance_client.py` reads `data/config/market_universe.json` and fetches ETF/index proxy market data through yfinance.
- `src/market/api_client.py` is a small market snapshot adapter with environment-variable hooks for a future boss-provided market API.
- `src/market/intraday_refresh_service.py` uses yfinance fallback data for delayed intraday marks and keeps official ledger data separate.
- No production-grade universe provider interface exists for a future boss-provided security master, index membership, prices/volume, market cap, and sector/industry service.

## Current Universe Implementation

Current universe logic is fragmented:

- Operational dashboard holdings are derived from committed shadow-live/operational artifacts.
- Market monitoring uses a static ETF/index proxy list.
- WorldQuant Alpha #2 has a useful current-listed security master builder and pilot universe, but it is scoped to one research stream and explicitly not survivor-bias-free.
- The S&P 500 reference artifact in `dashboard/data/universes/sp500_current.json` is a current constituent reference, not a point-in-time membership source.

## Current Risks

- Broad U.S. equity research may accidentally inherit ETF proxy assumptions or current-listed-only membership.
- Current constituent lists can create survivorship bias if used as historical membership.
- There is no shared versioned universe snapshot contract for strategies, API, dashboard, and future ML.
- Data quality gates for price, ADV, market cap, asset type, stale data, and source status are not centralized.
- Future boss APIs do not have a dedicated universe-provider seam.
- Dashboard users cannot see universe coverage, excluded counts, data source state, or point-in-time status in one place.

## Files Likely Affected

- New docs: `docs/UNIVERSE_POINT_IN_TIME_POLICY.md`, `docs/ALPHA_RESEARCH_AND_ML_AFTER_UNIVERSE_ROADMAP.md`, `GPT_REPORT_UNIVERSE_FOUNDATION.md`.
- New config: `data/config/universe_definitions.yaml`, `data/config/strategy_universe_mapping.yaml`.
- New modules under `src/universe/`.
- New generated universe artifacts under `data/universe/`.
- API extensions in `scripts/run_workstation_server.py`.
- Dashboard extensions in `dashboard/foundation-app.js` and possibly `dashboard/foundation.css`.
- New focused tests under `tests/test_universe_*.py`.

## Proposed Implementation Plan

1. Add config-driven universe definitions and global universe refresh/source settings.
2. Add typed security master, membership, and snapshot dataclasses.
3. Add provider abstractions for boss API, existing artifacts, and clearly provisional public fallback data.
4. Build filtering, builder, quality report, refresh service, and point-in-time helpers under `src/universe`.
5. Write CSV/JSON universe artifacts and gracefully skip parquet when dependencies are unavailable.
6. Expose `/api/universe/summary`, `/api/universe/snapshot`, `/api/universe/quality`, and `/api/universe/members`.
7. Add a dark workstation-style Universe & Data Coverage tab that labels provisional and current-membership-only states.
8. Add focused unit/API/dashboard contract tests without changing strategy definitions, accounting logic, Combined/N semantics, WQ_ALPHA_018 admission status, or brokerage execution.

## Assumptions

- Boss-provided API credentials/endpoints are not available in this task; placeholders must return structured unavailable status rather than fake data.
- Public/yfinance fallback is provisional only and must not be presented as final production membership.
- Historical index membership is not currently available; point-in-time status must therefore be labeled `CURRENT_MEMBERSHIP_ONLY_PROVISIONAL` when using current artifacts.
- Universe foundation work is limited to data contracts, filtering, snapshots, dashboard/API visibility, and documentation. It does not promote strategies, run optimizer work, or alter live/paper execution semantics.
