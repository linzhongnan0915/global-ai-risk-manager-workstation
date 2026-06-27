# YFinance Provisional Universe Audit

As of the pre-Phase 2B-lite state, the universe foundation artifacts are structurally valid but not populated for trading or research coverage:

- `data/universe/current_universe_snapshot.json` has `included_count = 0` for the configured universes.
- The top exclusion reason is `missing_price = 503`.
- The 503 candidates come from the committed current S&P 500 reference artifact.
- The existing artifact provider does not provide price, ADV, or market cap fields, so the configured filters correctly exclude every candidate rather than fabricating values.

## Available Candidates

- `dashboard/data/universes/sp500_current.json` is available and currently has 503 current S&P-derived constituents.
- `data/reference/worldquant_alpha2_research_universe_v1.csv`, `data/reference/worldquant_alpha2_common_stock_candidates.csv`, and `data/reference/worldquant_alpha2_us_security_master.csv` are supported by the code but were not committed in the starting release candidate.
- Existing current-listed U.S. security master utilities are available in `src/strategies/worldquant/universe.py` and `src/strategies/worldquant/research_universe.py`.
- Those utilities can build a current-listed common-stock/REIT candidate pool from Nasdaq Trader symbol-directory files when network access is available.

## YFinance Availability

- `requirements.txt` includes `yfinance>=0.2`.
- Local import check found yfinance available as version `1.4.1`.
- Existing market fallback code already uses yfinance in `src/market/yfinance_client.py`.

## Fields YFinance Can Provide For Prototype Use

YFinance/public fallback can usually provide:

- Recent daily close prices.
- Recent daily share volume.
- Derived latest price.
- Derived 20-day average dollar volume (`adv_20d`).
- Derived 60-day average dollar volume (`adv_60d`).
- Best-effort current market cap through `fast_info` or `info`.
- Best-effort current sector and industry through `info`.
- Best-effort quote type.

## Fields YFinance Cannot Reliably Provide

YFinance/public fallback cannot reliably provide:

- Historical index membership.
- Historical current-listed universe membership as of each past date.
- Delisted securities coverage.
- Corporate action and identifier mapping suitable for institutional backtests.
- Fully reconciled market cap history.
- Stable sector/industry history.
- Institutional-grade exchange/security master validation.
- Guaranteed complete coverage across 5,000 names.

## Required Labels

All yfinance-generated universe rows and reports must remain labeled:

- `DATA_SOURCE = YFINANCE_PUBLIC_FALLBACK`
- `POINT_IN_TIME_STATUS = CURRENT_MEMBERSHIP_ONLY_PROVISIONAL`
- `RESEARCH_USE = PROTOTYPE_ONLY`
- `NOT_SURVIVOR_BIAS_FREE = true`

## Tiered Universe Intent

The goal is a rules-based broad U.S. equity research universe, not a random 5,000-stock sample.

- `US_LARGE_CAP_CORE`: S&P 500-style large-cap core, sourced from the current S&P reference artifact when available.
- `US_BROAD_MARKET`: Russell 3000-style broad current-listed U.S. common-equity research universe.
- `US_SMALL_CAP`: Russell 2000-style / small-cap research subset, filtered by available market cap.
- `US_ALL_COMMON_RESEARCH`: broad current-listed U.S. common-stock research discovery pool, up to around 5,000 names when data support it.
- `US_TRADABLE_LIQUID`: filtered tradable subset based on price, ADV, market cap, asset type, and data quality.

The 5,000-name pool is for research discovery, AI strategy search, and pipeline testing. It is not the direct optimizer/trading universe. Optimizer work should use `US_TRADABLE_LIQUID` or approved strategy-specific universes.

## Key Risks

- Survivorship bias: current-listed securities omit delisted, merged, and bankrupt names.
- Missing delistings: yfinance and current symbol directories do not reconstruct historical availability.
- Current-membership-only membership: broad and S&P pools are provisional current snapshots.
- Market cap instability: market cap is current/best-effort and can be missing or stale.
- Sector/industry instability: yfinance classifications are current/best-effort.
- Coverage gaps: yfinance can return missing prices, missing volumes, or failed tickers.
- Rate limits: a full 5,000-name refresh can be slow or unstable.

## Implementation Plan

1. Add `src/universe/yfinance_provider.py` as a provisional `UniverseDataProvider`.
2. Load current S&P candidates for `US_LARGE_CAP_CORE`.
3. Load existing WorldQuant current-listed artifacts when present, otherwise use the existing Nasdaq Trader symbol-directory utilities when allowed.
4. Enrich candidates in chunks with yfinance recent price/volume.
5. Compute latest price, `adv_20d`, and `adv_60d` from real downloaded rows only.
6. Fetch best-effort market cap, sector, and industry without fabricating missing values.
7. Preserve missing values and surface structured warnings.
8. Keep candidate pools tier-aware so the broad research pool is separate from the tradable liquid subset.
9. Extend `scripts/refresh_universe.py` with `--provider yfinance-provisional`, `--max-tickers`, repeated `--universe`, `--force-refresh`, and `--use-cache`.
10. Write machine-readable diagnostics and a human coverage report.
11. Keep API/dashboard provisional warnings visible.
12. Add mocked tests that do not depend on live network calls.
