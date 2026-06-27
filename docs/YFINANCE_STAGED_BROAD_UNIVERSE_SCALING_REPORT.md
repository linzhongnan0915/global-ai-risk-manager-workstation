# YFinance Staged Broad Universe Scaling Report

## Scope

This report covers controlled staged yfinance provisional broad-universe scaling for `US_ALL_COMMON_RESEARCH` as of `2026-06-23`.

Completed stages:

| Stage | Max tickers | Status | Candidates | Included | Excluded |
|---|---:|---|---:|---:|---:|
| Stage 1 | 500 | complete | 500 | 361 | 139 |
| Stage 2 | 1500 | complete | 1500 | 1060 | 440 |
| Stage 3 | 3000 | complete | 3000 | 2116 | 884 |

No 5000-name refresh was run. No Strategy Factory work, 16-strategy migration audit, migration backtest, ML work, optimizer work, official strategy performance change, paper ledger change, Combined/N semantic change, strategy promotion, or live brokerage change was started.

## Required Labels

- `DATA_SOURCE = YFINANCE_PUBLIC_FALLBACK`
- `POINT_IN_TIME_STATUS = CURRENT_MEMBERSHIP_ONLY_PROVISIONAL`
- `RESEARCH_USE = PROTOTYPE_ONLY`
- `NOT_SURVIVOR_BIAS_FREE = true`

## Post-Stage 3 Stability Checks

All requested post-run stability checks passed after the 3000-name refresh:

- `python -m pytest tests/test_yfinance_provisional_provider.py tests/test_refresh_universe_yfinance_provisional.py tests/test_universe_provisional_status.py -q`  
  Result: 9 passed.
- `python -m pytest tests/test_universe_file_provider.py tests/test_universe_provider_validation.py tests/test_refresh_universe_script.py tests/test_universe_api_contract.py -q`  
  Result: 10 passed.
- `python -m pytest tests/test_workstation_server.py tests/test_operational_snapshot.py -q`  
  Result: 52 passed.
- `python scripts/verify_dashboard_browser.py --no-screenshots`  
  Result: passed; console errors: 0.
- `node --check dashboard/foundation-app.js`  
  Result: plain `node` was unavailable on PATH.
- `C:\Users\linzh\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe --check dashboard/foundation-app.js`  
  Result: passed.

## Stage 3 Command

```powershell
python scripts\refresh_universe.py --provider yfinance-provisional --universe US_ALL_COMMON_RESEARCH --max-tickers 3000 --as-of-date 2026-06-23 --use-cache
```

## Stage 3 Result

- 3000-name scaling status: complete.
- Largest successful scale so far: 3000 candidates.
- Universe: `US_ALL_COMMON_RESEARCH`
- As-of date: `2026-06-23`
- Provider status: `LOADED_YFINANCE_PUBLIC_FALLBACK_PROVISIONAL`
- Elapsed time: 2264.6 seconds
- Candidate count: 3000
- Included count: 2116
- Excluded count: 884
- YFinance failures: 0
- Missing price count: 0
- Missing ADV 20D count: 12
- Missing ADV 60D count: 12
- Missing market cap count: 3
- Missing sector count: 5
- Missing industry count: 5

Top exclusion reasons:

| Reason | Count |
|---|---:|
| `min_adv_20d` | 557 |
| `min_price` | 312 |
| `missing_adv_20d` | 12 |
| `min_adv_60d` | 3 |

## Stage 3 Cache Behavior

- Exact full cache hit: no.
- Cache hit count: 1500 same-date partial rows.
- Cache miss count: 1500 rows.
- Partial cache reuse count: 1500 rows.
- Price rows loaded from yfinance during the run: 1500.
- Fundamental rows loaded from yfinance during the run: 1500.

Cache reuse helped by avoiding re-fetching the 1500 overlapping rows from the same as-of date. Latency remained material because the other 1500 rows still required public yfinance fetches.

## Stage 3 Data Quality

Coverage remained acceptable for prototype-only research use:

| Field | Covered | Total | Ratio |
|---|---:|---:|---:|
| price | 3000 | 3000 | 100.00% |
| ADV 20D | 2988 | 3000 | 99.60% |
| ADV 60D | 2988 | 3000 | 99.60% |
| market cap | 2997 | 3000 | 99.90% |
| sector | 2995 | 3000 | 99.83% |
| industry | 2995 | 3000 | 99.83% |

Asset type distribution:

| Asset type | Count |
|---|---:|
| `COMMON_STOCK` | 2994 |
| `REIT_COMMON_EQUITY` | 6 |

Exchange distribution:

| Exchange | Count |
|---|---:|
| `NASDAQ` | 2984 |
| `NYSE` | 16 |

Exchange coverage remains skewed and Nasdaq-dominant. This is acceptable for the staged provider scaling test, but it is a limitation for treating the current 3000-name set as a representative broad U.S. equity universe.

## Candidate Source

No committed broad WorldQuant current-listed artifact was available for this stage. The provider used Nasdaq Trader current-listed symbol-directory utilities:

- Nasdaq-listed rows: 5,525
- Other-exchange rows: 7,339
- Current eligible candidate count from symbol-directory classification: 5,097
- Provider candidate count after broad common-stock construction: 4,986
- Stage 3 cap used: 3000

The stage result is current-listed only and not survivor-bias-free. It does not include delisted securities or historical point-in-time membership.

## Warnings

- Broad candidate pool was generated from current Nasdaq Trader symbol-directory utilities; historical delistings are absent.
- Broad current-listed WorldQuant security master artifacts were not found.
- Loaded 1500 ticker rows from same-date yfinance provisional partial cache.
- Point-in-time status is `CURRENT_MEMBERSHIP_ONLY_PROVISIONAL` until historical membership is supplied.
- The broad research pool is not a direct optimizer/trading universe; use `US_TRADABLE_LIQUID` or approved strategy-specific universes for that purpose.
- This universe is current-membership-only and not survivor-bias-free.
- `US_ALL_COMMON_RESEARCH`: one or more required fields are missing for candidates.
- `US_LARGE_CAP_CORE` uses the current S&P 500 reference artifact when available; this is not historical index membership.
- YFinance/public fallback data is prototype-only and not institutional-grade.
- 12 of 3000 provisional yfinance records are missing ADV 20D.
- 12 of 3000 provisional yfinance records are missing ADV 60D.
- 3 of 3000 provisional yfinance records are missing market cap.
- 5 of 3000 provisional yfinance records are missing sector.
- 5 of 3000 provisional yfinance records are missing industry.
- yfinance emitted missing-price stderr warnings for `MAGH`, `MAMK`, `MCTA`, `NUTR`, `OST`, `PC`, `PLTS`, `PTNM`, `QMMM`, `SDM`, `SVA`, and `UCFI`, but the provider recorded 0 yfinance failures and final price coverage was complete.

## Latency / Rate-Limit Assessment

The 3000-name run completed in 2264.6 seconds, about 37.7 minutes. No hard yfinance rate-limit failure appeared, no repeated network failure was recorded, and recorded yfinance failures were 0. Public/yfinance latency risk is now material and should be expected to worsen at 5000.

It is safe to attempt 5000 later only as a separate controlled scaling test with cache enabled, unchanged universe gates, explicit stop conditions, and the same diagnostics. The current provider candidate count is 4,986, so a `--max-tickers 5000` run may not produce exactly 5000 candidates unless candidate sources expand. The current exchange skew should be addressed before treating the result as a representative broad-market universe.

## Conclusion

- 3000-name scaling: complete.
- Largest successful scale so far: 3000 candidates.
- Included/excluded counts: 2116 included, 884 excluded.
- Data quality status: acceptable for prototype-only research use.
- Cache reuse status: helped; 1500 partial same-date rows reused.
- Latency/rate-limit status: no hard rate-limit failure; latency material at 2264.6 seconds.
- API/dashboard stability: stable after post-run tests and browser verification.
- Safe to attempt 5000 later: conditional yes, as a separate controlled stage with the caveats above.
- 5000 still not attempted.
- Strategy Factory still not started.
- Migration audit and migration backtests still not started.
- ML and optimizer still blocked by the roadmap sequence.
