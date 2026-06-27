# GPT Report: YFinance Provisional Universe

## 1. Short Summary

Implemented Phase 2B-lite provisional yfinance/public fallback universe population.

The implementation builds tier-aware, rules-based current-listed U.S. equity research universes, not a random 5,000-stock sample. The broad research pool is explicitly separated from the tradable subset and optimizer use.

Required labels are carried through provider output, snapshots, diagnostics, API payloads, dashboard copy, and reports:

- `DATA_SOURCE = YFINANCE_PUBLIC_FALLBACK`
- `POINT_IN_TIME_STATUS = CURRENT_MEMBERSHIP_ONLY_PROVISIONAL`
- `RESEARCH_USE = PROTOTYPE_ONLY`
- `NOT_SURVIVOR_BIAS_FREE = true`

## 2. Files Changed

- `src/universe/yfinance_provider.py`
- `src/universe/universe_builder.py`
- `src/universe/universe_refresh_service.py`
- `src/universe/quality_report.py`
- `src/universe/models.py`
- `src/universe/__init__.py`
- `scripts/refresh_universe.py`
- `data/config/universe_definitions.yaml`
- `dashboard/foundation-app.js`
- `docs/YFINANCE_PROVISIONAL_UNIVERSE_AUDIT.md`
- `docs/YFINANCE_PROVISIONAL_UNIVERSE_COVERAGE_REPORT.md`
- `tests/test_yfinance_provisional_provider.py`
- `tests/test_refresh_universe_yfinance_provisional.py`
- `tests/test_universe_provisional_status.py`

## 3. Provider Implementation Details

Added `YFinanceProvisionalUniverseProvider` as a `UniverseDataProvider`.

Provider behavior:

- Uses current S&P 500 reference candidates for `US_LARGE_CAP_CORE`.
- Uses existing current-listed WorldQuant/Nasdaq Trader security-master utilities for broad common-stock candidates when available.
- Falls back to Nasdaq Trader symbol-directory download for broad candidates when artifacts are absent and download is allowed.
- Applies deterministic candidate ranking: S&P current constituents first, then primary exchanges by ticker.
- Caps candidate pools through `--max-tickers` or config, with no random sampling.
- Fetches yfinance price/volume in chunks.
- Computes latest price, `adv_20d`, and `adv_60d` from real downloaded close and volume rows.
- Fetches best-effort market cap, sector, and industry through `fast_info` / `info`.
- Preserves missing values and reports warnings instead of fabricating data.
- Continues partial refreshes when some tickers fail.
- Writes machine-readable diagnostics to `data/universe/yfinance_provisional_diagnostics.json`.

## 4. Refresh Commands Run

Focused mocked tests used in-process yfinance mocks; no live network dependency.

Live smoke refresh run:

```powershell
python scripts\refresh_universe.py --provider yfinance-provisional --universe US_LARGE_CAP_CORE --max-tickers 50 --as-of-date 2026-06-23 --force-refresh --no-use-cache --output-dir output\yfinance_smoke_universe
```

The full 5,000-name live refresh was not forced. The 50-name public yfinance smoke run took about one minute; a 5,000-name run would be rate-limit and latency sensitive in this environment.

## 5. Universe Included / Excluded Counts

Live smoke output:

- `US_LARGE_CAP_CORE`: candidates = 50, included = 50, excluded = 0.
- Top exclusion reasons: none.
- YFinance failures: 0.

## 6. Coverage Metrics

Live smoke coverage:

- Price coverage: 50/50.
- ADV 20D coverage: 50/50.
- ADV 60D coverage: 50/50.
- Market cap coverage: 50/50.
- Sector coverage: 50/50.
- Industry coverage: 50/50.

Human coverage report:

- `docs/YFINANCE_PROVISIONAL_UNIVERSE_COVERAGE_REPORT.md`

Machine-readable diagnostics:

- `data/universe/yfinance_provisional_diagnostics.json`

## 7. Warnings And Limitations

- This universe is current-membership-only and not survivor-bias-free.
- YFinance/public fallback data is prototype-only and not institutional-grade.
- Current S&P membership is not historical S&P membership.
- Broad current-listed candidates omit delisted, merged, and bankrupt names.
- Market cap, sector, and industry are current/best-effort fields.
- The 5,000-name pool is for research discovery, AI strategy search, and pipeline testing, not direct optimizer input.
- Optimizer/trading workflows should use `US_TRADABLE_LIQUID` or approved strategy-specific universes.

## 8. API Verification

The universe API helpers now expose:

- `data_source`
- `point_in_time_status`
- `research_use`
- `not_survivor_bias_free`
- per-universe coverage summaries
- asset type and exchange distributions

Verified by:

```powershell
python -m pytest tests/test_universe_*.py -q
python -m pytest tests/test_workstation_server.py tests/test_operational_snapshot.py -q
```

## 9. Dashboard Verification

The Universe & Data Coverage tab keeps the provisional warning visible and shows:

- included counts
- exclusion reasons
- yfinance/public fallback source status
- `CURRENT_MEMBERSHIP_ONLY_PROVISIONAL`
- `PROTOTYPE_ONLY`
- not-survivor-bias-free warning
- last refresh time and universe version where present

Verified by:

```powershell
python scripts\verify_dashboard_browser.py --no-screenshots
node --check dashboard/foundation-app.js
```

Plain `node` was not on PATH, so the bundled Node executable was used for the actual check.

## 10. Tests Run And Results

```powershell
python -m pytest tests/test_yfinance_provisional_provider.py tests/test_refresh_universe_yfinance_provisional.py tests/test_universe_provisional_status.py -q
```

Result: 9 passed.

```powershell
python -m pytest tests/test_universe_*.py -q
```

PowerShell did not expand the glob, so the expanded file list was used.

Result: 31 passed.

```powershell
python -m pytest tests/test_workstation_server.py tests/test_operational_snapshot.py -q
```

Result: 52 passed.

```powershell
python -m pytest tests/test_phase1_foundation.py tests/test_operational_snapshot.py tests/test_shadow_live_dashboard.py tests/test_production_operational_semantics.py tests/test_wq_alpha018_integration.py -q
```

Result: 74 passed.

```powershell
python scripts\verify_dashboard_browser.py --no-screenshots
```

Result: passed, no console errors.

```powershell
C:\Users\linzh\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe --check dashboard\foundation-app.js
```

Result: passed.

## 11. Provisional Alpha Workflow Testing

Provisional workflow testing can begin for dashboard/API/pipeline coverage only.

This does not authorize final alpha conclusions, final ML training/admission, optimizer deployment, or live brokerage execution.

## 12. What Still Requires Boss/API Data

- Institutional security master.
- Historical point-in-time index and universe membership.
- Delisting coverage.
- Corporate action and identifier mapping.
- Production-grade market cap, sector, and industry history.
- Final research universe used for institutional backtests and admission.
- Any final optimizer/trading universe approval.

## Required Conclusion

- Universe foundation: complete
- Provider integration: complete
- YFinance provisional population: complete for provider, mocked tests, and 50-name live large-cap smoke; full 5,000-name public refresh not forced due public endpoint/rate-limit risk
- Final institutional universe: blocked on boss/API data
- Alpha research: allowed only for provisional workflow testing, not final conclusions
- ML: still not allowed for final training/admission
- Optimizer: still not allowed
