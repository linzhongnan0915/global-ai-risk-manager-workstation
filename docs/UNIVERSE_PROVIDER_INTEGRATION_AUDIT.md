# Universe Provider Integration Audit

## Scope

This audit covers Phase 2A provider integration readiness in `D:\Global_Ai\release_global_ai_risk_manager_workstation`.
It does not use the old `Risk_Manager_Platform` repository and does not change strategy definitions, accounting logic, Combined/N semantics, WQ_ALPHA_018 admission status, optimizer behavior, or brokerage execution semantics.

## Current Provider Abstractions

- `src/universe/providers.py` defines `UniverseDataProvider` and `ProviderResponse`.
- `BossApiUniverseProvider` is a placeholder for future approved boss/API access. It returns structured unavailable/TODO status and does not fetch or fabricate data.
- `ExistingArtifactUniverseProvider` reads committed local reference artifacts, including the current S&P-derived dashboard artifact when present. It labels them current-membership-only/provisional.
- `PublicFallbackUniverseProvider` is intentionally unavailable for production-grade membership.
- `PrioritizedUniverseProvider` attempts boss API, existing artifacts, then provisional public fallback.
- Phase 2A adds `FileUniverseProvider` in `src/universe/file_provider.py` for staged approved CSV/parquet extracts before the final API is available.

## Current Artifact Schema

Generated universe artifacts live under `data/universe/`:

- `security_master.csv` and optional `security_master.parquet`
  - One row per provider security candidate after validation/deduplication.
  - Key fields include `security_id`, `ticker`, `company_name`, `exchange`, `asset_type`, `country`, `currency`, `sector`, `industry`, `price`, `adv_20d`, `adv_60d`, `market_cap`, `is_active`, `data_source`, and `last_updated`.
- `universe_membership.csv` and optional `universe_membership.parquet`
  - Included securities after configured filters.
  - Fields include `universe_name`, `security_id`, `ticker`, `membership_start_date`, `membership_end_date`, `as_of_date`, `source`, `version`, `inclusion_reason`, and `exclusion_reason`.
- `current_universe_snapshot.json`
  - Bundle with `schema_version`, `as_of_date`, `generated_at`, `version`, `point_in_time_status`, `source_status`, `data_source`, provider metadata, per-universe counts, exclusions, warnings, and summaries.
- `universe_quality_report.json`
  - Provider status, parquet fallback status, included/candidate counts, aggregate exclusion reasons, and warnings.
- `universe_refresh_log.jsonl`
  - Append-only refresh metadata for each run.

## Required Fields For Inclusion

The current filters in `src/universe/universe_filters.py` require:

- Active security: `is_active == true`.
- Included asset type: `COMMON_STOCK` or `REIT_COMMON_EQUITY` depending on the universe definition.
- Excluded asset-type flags remain excluded: ETF, ADR, preferred, warrant, unit, closed-end fund, SPAC/shell.
- `price` present and above the configured `min_price`.
- `adv_20d` present and above the configured `min_adv_20d`.
- `adv_60d` present and above the configured `min_adv_60d`.
- `market_cap` present when a universe defines `min_market_cap` or `max_market_cap`, such as `US_SMALL_CAP`.
- `last_updated` present and not stale under `global_settings.stale_data_threshold_days`.

For the first populated current universe, the provider must also supply the release-readiness fields requested by the contract:

`security_id`, `ticker`, `company_name`, `exchange`, `asset_type`, `country`, `currency`, `price`, `adv_20d`, `adv_60d`, `market_cap`, `sector`, `industry`, `is_active`, `data_source`, `last_updated`.

## Why Included Count Is Currently Zero

The existing generated artifacts contain current S&P-derived candidates, but those rows do not contain production-grade price, ADV, market cap, and full provider freshness fields.
The filters correctly exclude those candidates instead of inventing missing values. The dominant current exclusions are missing quantitative gate fields, especially `missing_price`, followed by missing ADV/market-cap gates where reached.

This is correct release behavior: no boss/API market data has been supplied, and current membership is not survivor-bias-free historical membership.

## Exact Fields Needed From Boss/API

Minimum current population fields:

- Stable identity: `security_id`, `ticker`, `company_name`, `exchange`, `asset_type`, `country`, `currency`.
- Current trading status: `is_active`, `delisting_date` if applicable.
- Current price and liquidity: `price`, `adv_20d`, `adv_60d`.
- Size: `market_cap`, preferably `shares_outstanding`.
- Classification: `sector`, `industry`, and classification system if available.
- Membership: `index_name`, `membership_start_date`, `membership_end_date` when known, `as_of_date`.
- Governance labels: `data_source`, `last_updated`, provider status/source label.
- Later PIT/research controls: historical membership, delistings, ticker changes, corporate actions, and revision timestamps.

## Files Modified For Phase 2A

- `src/universe/provider_validation.py`
- `src/universe/file_provider.py`
- `src/universe/universe_refresh_service.py`
- `src/universe/__init__.py`
- `scripts/refresh_universe.py`
- `data/provider_inputs/universe/templates/*.csv`
- `tests/test_universe_file_provider.py`
- `tests/test_universe_provider_validation.py`
- `tests/test_refresh_universe_script.py`
- `tests/test_universe_api_contract.py`
- `docs/BOSS_API_UNIVERSE_PROVIDER_CONTRACT.md`
- `docs/UNIVERSE_PROVIDER_INTEGRATION_AUDIT.md`

## Risks

- Current-membership-only files can be misused for historical research if the provisional label is ignored.
- Provider extracts can drift in schema; missing required columns now fail loudly.
- Bad numeric rows can reduce population unexpectedly; those rows are rejected and surfaced as warnings.
- Sparse price/ADV/market-cap data can make counts look low while still being correct.
- Sector/industry coverage is not an inclusion gate today, but it is required for boss-presentable data coverage and risk-manager interpretation.
- Sample templates must never be copied into production input files; rows marked `SAMPLE_TEMPLATE_ONLY` are rejected.
- Boss API credentials, paid data, or local secrets must remain outside source control.
