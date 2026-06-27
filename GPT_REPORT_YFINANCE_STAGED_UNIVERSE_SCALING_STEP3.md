# GPT Report: YFinance Staged Universe Scaling Step 3

## Result

3000-name scaling: complete.

Largest successful scale so far: 3000 candidates for `US_ALL_COMMON_RESEARCH`.

## Command Run

```powershell
python scripts\refresh_universe.py --provider yfinance-provisional --universe US_ALL_COMMON_RESEARCH --max-tickers 3000 --as-of-date 2026-06-23 --use-cache
```

## Required Labels

- `DATA_SOURCE = YFINANCE_PUBLIC_FALLBACK`
- `POINT_IN_TIME_STATUS = CURRENT_MEMBERSHIP_ONLY_PROVISIONAL`
- `RESEARCH_USE = PROTOTYPE_ONLY`
- `NOT_SURVIVOR_BIAS_FREE = true`

## Scaling Diagnostics

- Universe used: `US_ALL_COMMON_RESEARCH`
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
- Cache hit count: 1500 same-date partial rows
- Cache miss count: 1500 rows
- Partial cache reuse count: 1500 rows

Top exclusion reasons:

| Reason | Count |
|---|---:|
| `min_adv_20d` | 557 |
| `min_price` | 312 |
| `missing_adv_20d` | 12 |
| `min_adv_60d` | 3 |

## Data Quality

Data quality remained acceptable for prototype-only research use. Price coverage was complete. ADV coverage was 99.60%, market-cap coverage was 99.90%, and sector/industry coverage was 99.83%.

Exchange coverage remains skewed: `NASDAQ` 2984 and `NYSE` 16. This is acceptable for a provider scaling test, but it limits claims that the current 3000-name artifact is representative of the full broad U.S. equity market.

yfinance emitted ticker-level missing-price stderr warnings for `MAGH`, `MAMK`, `MCTA`, `NUTR`, `OST`, `PC`, `PLTS`, `PTNM`, `QMMM`, `SDM`, `SVA`, and `UCFI`, but the provider recorded 0 yfinance failures and final price coverage was complete.

## Stability Checks

All requested post-run checks passed:

- Focused yfinance/provider tests: 9 passed.
- Universe file/provider/API tests: 10 passed.
- Workstation server and operational snapshot tests: 52 passed.
- Dashboard browser verifier: passed with 0 console errors.
- Plain `node` was unavailable; bundled Node syntax check for `dashboard/foundation-app.js` passed.

## Proceed / Block Decision

It is safe to attempt 5000 later only as a separate controlled stage with cache enabled, unchanged gates, explicit stop conditions, and latency/rate-limit monitoring.

Caveats: public yfinance latency is material at 3000 names, the current provider candidate count is 4,986, and exchange coverage remains Nasdaq-dominant. A future 5000 run should remain a scaling test, not a direct trading universe or optimizer input.

## Explicit Non-Starts

- 5000-name stage was not attempted.
- Strategy Factory was not started.
- 16-strategy migration audit was not started.
- Migration backtests were not started.
- ML was not started.
- Optimizer/allocation engine was not started.
- Official strategy performance was not altered.
- Paper ledger was not overwritten.
- Combined/N semantics were not changed.
- No strategy was promoted.
- Live brokerage semantics were not touched.
