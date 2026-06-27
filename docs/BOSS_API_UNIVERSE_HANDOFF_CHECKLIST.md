# Boss/API Universe Handoff Checklist

## Purpose

This checklist defines the data needed to replace yfinance provisional fallback artifacts with boss/API or vendor-backed universe data.

YFinance fallback remains labeled:

- `DATA_SOURCE = YFINANCE_PUBLIC_FALLBACK`
- `POINT_IN_TIME_STATUS = CURRENT_MEMBERSHIP_ONLY_PROVISIONAL`
- `RESEARCH_USE = PROTOTYPE_ONLY`
- `NOT_SURVIVOR_BIAS_FREE = true`

Boss/API data should include source metadata, point-in-time availability, and survivorship-bias-free status for every table. Do not fabricate missing values.

## 1. Security Master

Required fields:

- `security_id`
- `ticker`
- `company_name`
- `exchange`
- `country`
- `currency`
- `asset_type`
- `active/inactive status`
- `ipo_date`
- `delisting_date` if available
- `ticker history / identifier mapping` if available

Implementation notes:

- `security_id` must be stable across ticker changes.
- `ticker` should be uppercase-normalized for display and fallback joins.
- `asset_type` must distinguish common stock, REIT common equity, ETF, preferred share, warrant, unit, ADR, closed-end fund, SPAC/shell, and debt-like instruments where possible.
- Inactive and delisted securities must be preserved for historical research.

## 2. Historical Membership

Required fields:

- `universe/index name`
- `security_id`
- `ticker`
- `membership_start_date`
- `membership_end_date`
- `as_of_date`
- `source/vendor metadata`

Implementation notes:

- Active membership for a signal date must satisfy `membership_start_date <= signal_date` and `signal_date < membership_end_date`, with blank end dates treated as current.
- Historical membership must include additions and removals.
- Current constituents alone are not point-in-time clean and must remain provisional.

## 3. Market Data

Required fields:

- `date`
- `security_id/ticker`
- `open`
- `high`
- `low`
- `close`
- `adjusted close`
- `volume`
- `corporate-action adjustment status`
- `delisting return` if available

Implementation notes:

- Prices must specify whether they are raw, split-adjusted, dividend-adjusted, total-return adjusted, or vendor-adjusted.
- Each observation should preserve source and timestamp metadata.
- Delisting returns should be supplied rather than inferred.

## 4. Liquidity

Required fields:

- `ADV 20D`
- `ADV 60D`
- `dollar volume`
- `spread/slippage proxy` if available

Implementation notes:

- ADV should be based on documented price and volume definitions.
- Liquidity values should carry observation date and source timestamp.
- Missing ADV should remain missing and should trigger exclusions or warnings, not fake fills.

## 5. Fundamental / Reference Data

Required fields:

- `market cap history`
- `shares outstanding`
- `sector`
- `industry`
- `classification effective date`

Implementation notes:

- Market cap should be historical and date-aware.
- Shares outstanding should preserve split and corporate-action treatment.
- Sector and industry must include effective dates and classification source, such as GICS, NAICS, SIC, or vendor taxonomy.

## 6. Metadata

Required fields:

- `source`
- `data timestamp`
- `update timestamp`
- `PIT availability flag`
- `survivorship-bias-free flag`

Implementation notes:

- `source` should identify the API, vendor, table, and extraction process.
- `data timestamp` should describe observation availability, not just file write time.
- `update timestamp` should describe when the local extract was produced.
- `PIT availability flag` must distinguish true historical availability from current-only data.
- `survivorship-bias-free flag` must be false unless inactive, delisted, removed, and ticker-changed securities are covered.

## 7. Acceptance Checks For Boss/API Ingestion

Before boss/API data replaces fallback status:

- Security master includes active and inactive securities.
- Historical membership includes start and end dates.
- Ticker mapping supports historical joins.
- Delisting dates and delisting returns are present where available.
- Price, volume, and adjusted close histories are corporate-action documented.
- Market cap, shares, sector, and industry are date-aware.
- Data source, observation timestamp, update timestamp, PIT flag, and survivorship flag are present.
- Universe artifacts pass provider validation tests.
- Dashboard/API endpoints serve the new source without changing official performance semantics.
- Provisional labels are removed only when PIT and survivorship requirements are actually met.

## 8. Current Deployment Boundary

The Workstation universe framework is ready to ingest boss/API data. Final institutional universe validation, 30-40 year point-in-time backtesting, final strategy admission, ML admission, and optimizer work remain blocked until this checklist is satisfied.
