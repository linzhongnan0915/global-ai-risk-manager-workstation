# YFinance Provisional Universe Coverage Report

- DATA_SOURCE = YFINANCE_PUBLIC_FALLBACK
- POINT_IN_TIME_STATUS = CURRENT_MEMBERSHIP_ONLY_PROVISIONAL
- RESEARCH_USE = PROTOTYPE_ONLY
- NOT_SURVIVOR_BIAS_FREE = true

This universe is current-membership-only and not survivor-bias-free.

The 5,000-name pool, when available, is for research discovery, AI strategy search, and pipeline testing. It is not the direct optimizer/trading universe.

## Provider Summary

- Status: LOADED_YFINANCE_PUBLIC_FALLBACK_PROVISIONAL
- As-of date: 2026-06-23
- Version: universe_foundation_v1_20260623
- Candidate source counts: `{'sp500_current': {'path': 'D:\\Global_Ai\\release_global_ai_risk_manager_workstation\\dashboard\\data\\universes\\sp500_current.json', 'count': 503, 'as_of_date': '2026-06-17', 'status': 'CURRENT_MEMBERSHIP_ONLY_PROVISIONAL'}, 'worldquant_current_listed_artifact': {'count': 0}, 'nasdaq_trader_symbol_directory': {'status': 'DOWNLOADED_CURRENT_LISTED', 'count': 4986, 'summary': {'nasdaq_listed_rows': 5525, 'other_exchange_rows': 7339, 'total_unique_symbols': 12864, 'total_rows': 12864, 'etf_exclusions': 5372, 'test_issue_exclusions': 33, 'non_common_security_exclusions': 1972, 'non_common_exclusions_by_reason': {'warrant': 473, 'preferred_share': 442, 'units': 302, 'closed_end_fund': 239, 'spac_shell': 212, 'notes_debt': 174, 'rights': 128, 'fund_trust': 2}, 'adr_count': 487, 'needs_review_count': 390, 'eligible_candidate_count': 5097, 'reit_common_equity_count': 29, 'fund_closed_end_exclusion_count': 241, 'duplicate_symbol_rows': 0}}, 'candidate_counts_by_universe': {'US_ALL_COMMON_RESEARCH': 3000}}`
- YFinance failures: 0

## Universe Coverage

### US_ALL_COMMON_RESEARCH

- Total candidates: 3000
- Included count: 2116
- Excluded count: 884
- Top exclusion reasons: {'min_adv_20d': 557, 'min_price': 312, 'missing_adv_20d': 12, 'min_adv_60d': 3}
- Price coverage: 3000/3000 (100.0%)
- ADV 20D coverage: 2988/3000 (99.6%)
- ADV 60D coverage: 2988/3000 (99.6%)
- Market cap coverage: 2997/3000 (99.9%)
- Sector coverage: 2995/3000 (99.8%)
- Industry coverage: 2995/3000 (99.8%)
- Asset type distribution: `{'COMMON_STOCK': 2994, 'REIT_COMMON_EQUITY': 6}`
- Exchange distribution: `{'NASDAQ': 2984, 'NYSE': 16}`
- Data source: YFINANCE_PUBLIC_FALLBACK
- Point-in-time status: CURRENT_MEMBERSHIP_ONLY_PROVISIONAL
- Warnings: 14

## Warnings

- Broad candidate pool was generated from current Nasdaq Trader symbol-directory utilities; historical delistings are absent.
- Broad current-listed WorldQuant security master artifacts were not found.
- Loaded 1500 ticker rows from same-date yfinance provisional partial cache.
- Point-in-time status is CURRENT_MEMBERSHIP_ONLY_PROVISIONAL until historical membership is supplied.
- The broad research pool is not a direct optimizer/trading universe; use US_TRADABLE_LIQUID or approved strategy-specific universes for that purpose.
- This universe is current-membership-only and not survivor-bias-free.
- US_ALL_COMMON_RESEARCH: one or more required fields are missing for candidates.
- US_LARGE_CAP_CORE uses the current S&P 500 reference artifact when available; this is not historical index membership.
- YFinance/public fallback data is prototype-only and not institutional-grade.
- missing_adv_20d: 12 of 3000 provisional yfinance records are missing this field.
- missing_adv_60d: 12 of 3000 provisional yfinance records are missing this field.
- missing_industry: 5 of 3000 provisional yfinance records are missing this field.
- missing_market_cap: 3 of 3000 provisional yfinance records are missing this field.
- missing_sector: 5 of 3000 provisional yfinance records are missing this field.
