# Boss/API Universe Provider Contract

## Purpose

This contract defines the minimum approved data needed to populate the Risk Manager Workstation universe artifacts without fabricating missing values.
Current membership files may populate a current universe, but unless approved historical membership is supplied, every result must remain labeled:

`CURRENT_MEMBERSHIP_ONLY_PROVISIONAL`

Do not label current-only results survivor-bias-free.

## Staging File Layout

The file provider reads from `data/provider_inputs/universe/`:

- `security_master.csv`
- `index_membership.csv`
- `prices_volume_snapshot.csv`
- `sector_industry.csv`

CSV is required to work. Parquet with the same stem is allowed when local parquet dependencies are available.
Files inside `data/provider_inputs/universe/templates/` are examples only and are not read by the provider.
Rows with `data_source` equal to `SAMPLE_TEMPLATE_ONLY` are rejected.

## Source And Status Labels

Every provider table must include:

- `data_source`: human-readable source label such as `boss_security_master_api_v1`.
- `last_updated`: provider extraction or observation freshness date in `YYYY-MM-DD`.

Provider-level statuses used by the workstation include:

- `LOADED_FILE_PROVIDER`
- `UNAVAILABLE`
- `NO_VALID_SECURITY_MASTER_ROWS`
- `NO_VALID_FILE_PROVIDER_RECORDS`
- `CURRENT_MEMBERSHIP_ONLY_PROVISIONAL`

## Minimum Fields For First Populated Current Universe

Required across the staged files:

`security_id`, `ticker`, `company_name`, `exchange`, `asset_type`, `country`, `currency`, `price`, `adv_20d`, `adv_60d`, `market_cap`, `sector`, `industry`, `is_active`, `data_source`, `last_updated`.

Missing price, ADV, market cap, sector, or membership fields must not be filled with fake values.

## 1. Security Master

Required fields:

| Field | Type | Rule |
| --- | --- | --- |
| `security_id` | string | Stable provider identifier; must not be blank. |
| `ticker` | string | Normalized to uppercase. |
| `company_name` | string | Must not be blank. |
| `exchange` | string | Listing exchange. |
| `asset_type` | string | Example: `COMMON_STOCK`, `REIT_COMMON_EQUITY`, `ETF`. |
| `country` | string | ISO-style country label, expected `US` for this phase. |
| `currency` | string | Expected `USD` for U.S. common equity. |
| `is_active` | boolean | `true/false`, `1/0`, `yes/no`, or `active/inactive`. |
| `data_source` | string | Source label. |
| `last_updated` | date | `YYYY-MM-DD`. |

Optional fields:

`ipo_date`, `delisting_date`, `is_common_stock`, `is_adr`, `is_etf`, `is_reit`, `is_preferred`, `is_warrant`, `is_unit`, `is_closed_end_fund`, `is_spac_shell`, `price`, `adv_20d`, `adv_60d`, `market_cap`, `sector`, `industry`, `shares_outstanding`.

Example row:

```csv
SEC-A,AAA,Alpha Provider Corp,NYSE,COMMON_STOCK,US,USD,true,boss_security_master_api_v1,2026-06-22
```

Missing behavior:

- Missing required columns fail the contract.
- Rows with blank required fields are rejected.
- Template rows are rejected.

## 2. Index Membership

Required fields:

| Field | Type | Rule |
| --- | --- | --- |
| `security_id` | string | Joins to security master. |
| `ticker` | string | Uppercase normalized fallback join. |
| `index_name` | string | Provider index or approved universe source. |
| `membership_start_date` | date | Start date for current or historical membership. |
| `as_of_date` | date | Membership extract/effective date. |
| `data_source` | string | Source label. |
| `last_updated` | date | Extract freshness. |

Optional fields:

`membership_end_date`, `membership_status`, `weight`.

Example row:

```csv
SEC-A,AAA,BOSS_APPROVED_CURRENT_UNIVERSE,2026-01-01,,2026-06-22,current,0.0215,boss_index_membership_api_v1,2026-06-22
```

Validation rule:

- Active membership is `membership_start_date <= as_of_date` and `membership_end_date` blank or greater than the refresh date.
- If this file is missing, the file provider uses security-master rows as current candidates and warns.

Missing behavior:

- No historical membership means the snapshot remains `CURRENT_MEMBERSHIP_ONLY_PROVISIONAL`.
- Do not call the result point-in-time clean.

## 3. Price And Volume History

Preferred API history fields:

| Field | Type | Rule |
| --- | --- | --- |
| `security_id` | string | Stable join key. |
| `ticker` | string | Uppercase normalized fallback join. |
| `date` | date | Observation date. |
| `close` | float | Close or adjusted close, documented by source. |
| `volume` | float | Shares traded. |
| `currency` | string | Price currency. |
| `data_source` | string | Source label. |
| `last_updated` | date | Extract freshness. |

Staging snapshot fields in `prices_volume_snapshot.csv`:

`security_id`, `ticker`, `as_of_date`, `price`, `adv_20d`, `adv_60d`, `market_cap`, `data_source`, `last_updated`.

Example snapshot row:

```csv
SEC-A,AAA,2026-06-22,110.50,25000000,21000000,120000000000,USD,boss_price_volume_api_v1,2026-06-22
```

Missing behavior:

- Missing snapshot file does not create fake values.
- Missing price or ADV causes universe exclusion by `missing_price`, `missing_adv_20d`, or `missing_adv_60d`.
- Bad numeric values reject the affected provider row.

## 4. ADV Calculation Inputs

Required raw inputs when ADV is calculated internally:

| Field | Type | Rule |
| --- | --- | --- |
| `security_id` | string | Stable join key. |
| `date` | date | Trading date. |
| `close` | float | Positive or zero close; source-adjustment documented. |
| `volume` | float | Non-negative shares traded. |
| `currency` | string | Currency of close. |
| `data_source` | string | Source label. |

Validation rule:

- `adv_20d` should be the rolling 20 trading-day average dollar volume.
- `adv_60d` should be the rolling 60 trading-day average dollar volume.
- Rows with invalid close or volume are rejected from ADV calculation.

Missing behavior:

- If ADV cannot be calculated, leave `adv_20d` or `adv_60d` missing and let filters exclude.

## 5. Market Cap And Shares Outstanding

Required fields:

| Field | Type | Rule |
| --- | --- | --- |
| `security_id` | string | Stable join key. |
| `as_of_date` | date | Observation date. |
| `market_cap` | float | Non-negative current market capitalization. |
| `data_source` | string | Source label. |
| `last_updated` | date | Extract freshness. |

Optional fields:

`shares_outstanding`, `free_float_shares`, `float_market_cap`, `price_used`.

Example row:

```csv
SEC-A,AAA,2026-06-22,120000000000,1085972851,boss_market_cap_api_v1,2026-06-22
```

Missing behavior:

- Universes with market-cap gates exclude rows with missing `market_cap`.
- Do not infer market cap from ticker or sector.

## 6. Sector And Industry Classification

Required fields in `sector_industry.csv`:

| Field | Type | Rule |
| --- | --- | --- |
| `security_id` | string | Stable join key. |
| `ticker` | string | Uppercase normalized fallback join. |
| `sector` | string | Must not be blank for boss-presentable coverage. |
| `industry` | string | Must not be blank for boss-presentable coverage. |
| `data_source` | string | Source label. |
| `last_updated` | date | Classification freshness. |

Optional fields:

`classification_system`, `sub_industry`, `industry_group`.

Example row:

```csv
SEC-A,AAA,Information Technology,Software,GICS,boss_sector_api_v1,2026-06-22
```

Missing behavior:

- Missing classification should be surfaced as coverage warnings.
- Do not fabricate sector or industry from ticker name.

## 7. Historical Membership And Point-In-Time Membership

Preferred historical fields:

| Field | Type | Rule |
| --- | --- | --- |
| `security_id` | string | Stable join key. |
| `ticker` | string | Ticker at the membership date. |
| `index_name` | string | Index/universe source. |
| `membership_start_date` | date | Effective start. |
| `membership_end_date` | date or blank | Effective end. |
| `as_of_date` | date | Extract date. |
| `data_source` | string | Source label. |
| `last_updated` | date | Extract freshness. |

Validation rule:

- For any signal date, active membership is `start <= signal_date < end`, with blank end treated as current.
- Historical membership must include removals and additions; current constituents alone are not enough.

Missing behavior:

- If historical membership is unavailable, current universe refresh is allowed only as `CURRENT_MEMBERSHIP_ONLY_PROVISIONAL`.
- Do not describe current-only data as survivor-bias-free.

## 8. Delisting Status And Ticker Changes

Required when available:

| Field | Type | Rule |
| --- | --- | --- |
| `security_id` | string | Stable entity key across ticker changes. |
| `ticker` | string | Current or event ticker. |
| `previous_ticker` | string | Previous ticker, if applicable. |
| `effective_date` | date | Change or delisting date. |
| `event_type` | string | `ticker_change`, `delisting`, `merger`, `bankruptcy`, etc. |
| `is_active` | boolean | Current activity state. |
| `data_source` | string | Source label. |
| `last_updated` | date | Extract freshness. |

Example row:

```csv
SEC-X,NEWX,OLDX,2025-11-14,ticker_change,true,boss_corporate_actions_api_v1,2026-06-22
```

Missing behavior:

- If delisting and ticker-change history is unavailable, disclose it as a PIT/research limitation.
- Do not merge historical returns across tickers unless the stable `security_id` and corporate-action mapping support it.
