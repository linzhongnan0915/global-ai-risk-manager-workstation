# GPT Report: Universe Provider Integration

## 1. Summary

Implemented Phase 2A Universe Provider Integration & Population Readiness for the production release repository.

The workstation now has a validated file-based provider path for approved boss/API extracts before the final API adapter is available. It loads staged provider files, validates the contract, rejects invalid rows, preserves stable `security_id`, keeps source labels, applies the existing universe filters, writes the existing universe artifact schema, and leaves point-in-time status provisional unless approved historical membership is supplied.

No boss/API data was fabricated. No strategy definitions, accounting logic, Combined/N semantics, WQ_ALPHA_018 admission status, brokerage execution semantics, optimizer behavior, alpha research, or ML work was changed.

## 2. Files Changed

- `src/universe/provider_validation.py`
- `src/universe/file_provider.py`
- `src/universe/universe_refresh_service.py`
- `src/universe/__init__.py`
- `scripts/refresh_universe.py`
- `data/provider_inputs/universe/templates/security_master_template.csv`
- `data/provider_inputs/universe/templates/index_membership_template.csv`
- `data/provider_inputs/universe/templates/prices_volume_snapshot_template.csv`
- `data/provider_inputs/universe/templates/sector_industry_template.csv`
- `docs/UNIVERSE_PROVIDER_INTEGRATION_AUDIT.md`
- `docs/BOSS_API_UNIVERSE_PROVIDER_CONTRACT.md`
- `tests/test_universe_provider_validation.py`
- `tests/test_universe_file_provider.py`
- `tests/test_refresh_universe_script.py`
- `tests/test_universe_api_contract.py`

## 3. Provider Contract Created

Created `docs/BOSS_API_UNIVERSE_PROVIDER_CONTRACT.md`.

It documents required and optional fields, data types, example rows, validation rules, missing-data behavior, and source/status labels for:

- Security master
- Index membership
- Price and volume history
- ADV calculation inputs
- Market cap / shares outstanding
- Sector and industry classification
- Historical membership / point-in-time membership
- Delisting status and ticker changes

The contract explicitly states that current-only membership remains `CURRENT_MEMBERSHIP_ONLY_PROVISIONAL` and must not be labeled survivor-bias-free.

## 4. CLI Refresh Command

Added `scripts/refresh_universe.py`.

Supported commands:

```powershell
python scripts/refresh_universe.py --provider file --input-dir data/provider_inputs/universe --as-of-date YYYY-MM-DD
python scripts/refresh_universe.py --provider existing-artifacts
python scripts/refresh_universe.py --provider boss-api
```

The CLI writes `data/universe` artifacts, quality report, refresh log, and prints provider, date, counts, exclusions, PIT status, and warnings.

## 5. Tests Run And Results

- `python -m pytest tests/test_universe_provider_validation.py tests/test_universe_file_provider.py tests/test_refresh_universe_script.py tests/test_universe_api_contract.py -q`
  - Result: `10 passed`
- `python -m pytest tests/test_universe_*.py -q`
  - PowerShell did not expand the wildcard, so pytest reported the literal path missing.
- Expanded PowerShell equivalent:
  - `$files = Get-ChildItem tests\test_universe_*.py | ForEach-Object { $_.FullName }; python -m pytest $files -q`
  - Result: `29 passed`
- `python -m pytest tests/test_workstation_server.py tests/test_operational_snapshot.py -q`
  - Result: `52 passed`
- `python scripts/verify_dashboard_browser.py --no-screenshots`
  - Result: passed, console errors `0`
- `node --check dashboard/foundation-app.js`
  - Plain `node` was not on PATH.
- Bundled Node equivalent:
  - `C:\Users\linzh\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe --check dashboard\foundation-app.js`
  - Result: passed
- Release guardrail tests:
  - `python -m pytest tests/test_phase1_foundation.py tests/test_operational_snapshot.py tests/test_shadow_live_dashboard.py tests/test_production_operational_semantics.py tests/test_wq_alpha018_integration.py -q`
  - Result: `74 passed`

## 6. Current Universe Population Status

The committed current universe artifacts remain correctly unpopulated because no real provider price/ADV/market-cap data has been supplied.

Current `data/universe/current_universe_snapshot.json` status:

- `as_of_date`: `2026-06-22`
- `source_status`: `LOADED_CURRENT_MEMBERSHIP_ONLY_PROVISIONAL`
- `data_source`: `existing_internal_artifacts`
- `point_in_time_status`: `CURRENT_MEMBERSHIP_ONLY_PROVISIONAL`
- Each configured universe has `total_candidates: 503`, `included_count: 0`, and `excluded_count: 503`.
- Current top exclusion reason: `missing_price: 503`.

This is correct behavior. The system is ready to populate only when approved provider files supply required fields.

## 7. Remaining Blocker

Production population is blocked on boss/API or approved provider files with complete minimum fields. Historical membership is still required before any result can be described as point-in-time clean or survivor-bias-free.

## 8. Exact Data/API Fields Needed From Boss

Minimum current universe fields:

`security_id`, `ticker`, `company_name`, `exchange`, `asset_type`, `country`, `currency`, `price`, `adv_20d`, `adv_60d`, `market_cap`, `sector`, `industry`, `is_active`, `data_source`, `last_updated`.

Preferred PIT/research fields:

`index_name`, `membership_start_date`, `membership_end_date`, `as_of_date`, historical additions/removals, `delisting_date`, ticker-change mapping, corporate-action status, `shares_outstanding`, and source freshness metadata.

## 9. Next Step Before Alpha Research And ML

Place approved boss/API extracts in `data/provider_inputs/universe/`, run:

```powershell
python scripts/refresh_universe.py --provider file --input-dir data/provider_inputs/universe --as-of-date YYYY-MM-DD
```

Then inspect the Universe & Data Coverage dashboard tab and quality report. Alpha research and ML should remain gated until the universe is populated with approved data and its current-only or PIT status is explicitly understood.
