# GPT Report: YFinance Staged Universe Scaling Step 2

## Result

1500-name scaling: complete.

Largest successful scale so far: 1500 candidates for `US_ALL_COMMON_RESEARCH`.

## Command Run

```powershell
python scripts\refresh_universe.py --provider yfinance-provisional --universe US_ALL_COMMON_RESEARCH --max-tickers 1500 --as-of-date 2026-06-23 --use-cache
```

## Required Labels

- `DATA_SOURCE = YFINANCE_PUBLIC_FALLBACK`
- `POINT_IN_TIME_STATUS = CURRENT_MEMBERSHIP_ONLY_PROVISIONAL`
- `RESEARCH_USE = PROTOTYPE_ONLY`
- `NOT_SURVIVOR_BIAS_FREE = true`

## Scaling Diagnostics

- Universe used: `US_ALL_COMMON_RESEARCH`
- Elapsed time: 1111.2 seconds
- Candidate count: 1500
- Included count: 1060
- Excluded count: 440
- YFinance failures: 0
- Missing price count: 0
- Missing ADV 20D count: 2
- Missing ADV 60D count: 2
- Missing market cap count: 3
- Missing sector count: 2
- Missing industry count: 2
- Cache hit count: 500 same-date partial rows
- Cache miss count: 1000 rows
- Partial cache reuse count: 500 rows

Top exclusion reasons:

| Reason | Count |
|---|---:|
| `min_adv_20d` | 279 |
| `min_price` | 156 |
| `min_adv_60d` | 3 |
| `missing_adv_20d` | 2 |

## Data Quality

Data quality remained acceptable for prototype-only research use. Price coverage was complete. ADV, market cap, sector, and industry gaps were small and remained explicitly warned in the artifacts.

yfinance emitted missing-price stderr warnings for `EFTY`, `EMPG`, `HCHL`, `INHD`, and `JDZG`, but the provider recorded 0 yfinance failures and final price coverage was complete.

## Stability Checks

All requested post-run checks passed:

- Focused yfinance/provider tests: 9 passed.
- Universe file/provider/API tests: 10 passed.
- Workstation server and operational snapshot tests: 52 passed.
- Dashboard browser verifier: passed with 0 console errors.
- Plain `node` was unavailable; bundled Node syntax check for `dashboard/foundation-app.js` passed.

## Proceed / Block Decision

It is safe to proceed later to a 3000-name stage as a separate controlled task with cache enabled, unchanged gates, explicit stop conditions, and latency/rate-limit monitoring.

Do not jump directly to 5000. Public yfinance latency remains material: the 1500-name stage took about 18.5 minutes even with 500 partial cache hits.

## Explicit Non-Starts

- 3000-name stage was not started.
- 5000-name stage was not attempted.
- 16-strategy migration audit was not started.
- Migration backtests were not started.
- Strategy Factory was not started yet.
- ML was not started.
- Optimizer/allocation engine was not started.
- Official strategy performance was not altered.
- Paper ledger was not overwritten.
- Combined/N semantics were not changed.
- No strategy was promoted.
- Live brokerage semantics were not touched.
