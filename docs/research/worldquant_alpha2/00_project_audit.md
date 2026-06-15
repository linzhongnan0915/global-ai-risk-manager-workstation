# WorldQuant Alpha #2 — Phase 0 Project Audit

**Date:** 2026-06-06  
**Scope:** Read-only audit. No strategy implementation in this phase.  
**Target formula:**

```text
alpha2 = -1 * correlation(
    rank(delta(log(volume), 2)),
    rank((close - open) / open),
    6
)
```

**Operator definitions (research spec):**

| Operator | Meaning |
|----------|---------|
| `rank(x)` | Cross-sectional rank across stocks on the same date |
| `delta(x, 2)` | Current value minus value two trading days ago |
| `correlation(x, y, 6)` | Rolling time-series correlation over previous six trading days per stock |

---

## 1. Project structure

Concise tree (production-relevant paths only; excludes `.venv`, `node_modules`, caches, Playwright artifacts).

```text
risk_manager_platform/
├── data/
│   ├── config/                    # Strategy registry, universe, limits, platform YAML/JSON
│   ├── raw/                       # Gitignored; yfinance CSV landing zone (.gitkeep only in repo)
│   ├── processed/                 # Gitignored; normalized price panel (.gitkeep only in repo)
│   └── samples/                   # Mock market/news snapshots
├── docs/                          # Workflow, contracts, literature intake (this audit lives here)
├── dashboard/                     # Static workstation UI (HTML/CSS/JS)
├── output/                        # Generated artifacts, tables, literature extracts (partially gitignored)
├── scripts/                       # CLI runners: backtests, artifact gen, server, validation
├── src/
│   ├── allocation/                # Portfolio weight proposal, rebalance simulation/gates
│   ├── backtesting/               # Placeholder backtest skeleton (not main research engine)
│   ├── governance/                # Decision workflow
│   ├── market/                    # yfinance fetch, intraday refresh, live overlay
│   ├── portfolio/                 # Return alignment, ledger validation
│   ├── reporting/                 # Dashboard artifact generator
│   ├── replication/               # HF clone research helper
│   ├── risk/                      # Limits, performance, transaction costs, correlation
│   └── strategies/                # Registry loader, literature ETF prototypes, research catalog
├── tests/                         # Pytest suite (alignment, literature backtests, deployment, UI scripts)
├── requirements.txt
├── requirements-dev.txt
└── render.yaml
```

| Area | Primary location |
|------|------------------|
| Strategy definitions (research prototypes) | `src/strategies/literature_backtests.py` |
| Strategy registry (20 placeholder STRAT rows) | `data/config/strategy_registry.json` + `src/strategies/registry.py` |
| Data loaders | `src/market/yfinance_client.py`, `src/market/api_client.py`, `src/strategies/literature_backtests.py::load_price_returns` |
| Backtesting engine (real) | `src/strategies/literature_backtests.py::run_strategy_backtest` |
| Backtesting engine (skeleton) | `src/backtesting/engine.py::run_placeholder_backtest` |
| Portfolio construction | `src/allocation/optimizer.py`, weight builders in `literature_backtests.py`, `src/reporting/artifact_generator.py` |
| Transaction costs | `src/risk/transaction_cost.py`; applied in `literature_backtests.py` |
| Performance metrics | `src/risk/performance.py`, `src/risk/engine.py` |
| Dashboard / API | `dashboard/*`, `scripts/run_workstation_server.py`, `src/reporting/artifact_generator.py` |
| Tests | `tests/` (notably `test_literature_backtests.py`, `test_backtest_alignment.py`, `test_transaction_cost.py`) |
| Saved data | `data/raw/`, `data/processed/` (gitignored when populated), committed `output/dashboard_artifact.json` |
| Saved outputs | `output/literature_strategy_backtests.json` (gitignored), `output/risk_manager_tables/`, `output/literature_extracts/` |

---

## 2. Existing strategy architecture

### How the “20 strategies” are stored

The workstation dashboard’s **20 live strategy rows** come from **literature ETF prototype backtests**, not directly from `strategy_registry.json`.

| Layer | Count | IDs | Role |
|-------|-------|-----|------|
| Literature prototypes | 20 | `PROTO_*`, `CAND_*` | Runnable backtests with `builder` functions |
| Registry placeholders | 20 | `STRAT_001` … `STRAT_020` | Metadata, weights, governance fields; mostly placeholders |
| Dashboard artifact | 20 | Literature IDs embedded in `output/dashboard_artifact.json` | Production seed consumed by UI |

**WorldQuant relevance:** `STRAT_013` in the registry is named “WorldQuant Formulaic Alpha Basket” (`data/config/strategy_registry.json`, ~L376–420) with `backtest_status: pending_operator_library_and_point_in_time_data`. The closest **running** prototype is `PROTO_WQ_ALPHA_ETF` in `literature_backtests.py` (~L96–105), which is an **ETF momentum/reversal basket**, not Alpha #2.

There is **no base strategy class or ABC**. The common contract is:

### Interface pattern

| Component | Path | Symbol | Lines (approx.) | Explanation |
|-----------|------|--------|-----------------|-------------|
| Prototype record | `src/strategies/literature_backtests.py` | `StrategyPrototype` dataclass | 70–80 | Holds metadata + a `builder: Callable[[pd.DataFrame], pd.DataFrame]` that maps **return panel → daily weights** |
| Registry record | `src/strategies/registry.py` | `StrategyRecord` dataclass | 30–39 | Config row with target/min/max weights; no signal code |
| Registry loader | `src/strategies/registry.py` | `load_strategy_registry()` | 42–65 | Validates required JSON fields and returns list of `StrategyRecord` |
| Prototype list | `src/strategies/literature_backtests.py` | `strategy_prototypes()` | 93–315 | Returns all 20 research prototypes |

### Registration and IDs

- **Literature IDs** are hard-coded in each `StrategyPrototype(...)` constructor (e.g. `PROTO_WQ_ALPHA_ETF`).
- **Registry IDs** are in `data/config/strategy_registry.json` (`STRAT_001`, etc.).
- **Dashboard integration** loads `output/literature_strategy_backtests.json` when present; otherwise falls back to registry-only artifact path (`artifact_generator.py` ~L1381–1386).

### Required inputs (one strategy)

For a **literature prototype**:

1. **Input to builder:** `returns: pd.DataFrame` — wide daily simple returns, index = dates, columns = tickers (`load_price_returns`, L83–90).
2. **Builder output:** `weights: pd.DataFrame` — same shape, rows = dates, columns = tickers, values = portfolio weights (may include negatives for pseudo market-neutral sleeves).
3. **Backtest input:** prototype + same `returns` panel.

Registry rows require JSON fields listed in `REQUIRED_FIELDS` (`registry.py`, L11–27): weights, rebalance frequency, cost bps, statuses, etc. **No signal code.**

### Expected output format

`run_strategy_backtest()` (`literature_backtests.py`, L643–689) returns a dict including:

- Identity: `strategy_id`, `name`, `universe`, `signal_summary`
- Metrics: `gross_metrics`, `net_metrics`
- Series: `return_series.dates`, `gross_returns`, `net_returns`
- Packets: `risk_packet`, `position_packet`, `factor_exposure`
- Turnover/cost: `turnover.average_daily_turnover`, `annualized_cost_drag`
- Governance: `action` recommendation dict

Batch output: `run_all_literature_backtests()` → JSON written by `scripts/run_literature_strategy_backtests.py`.

### How returns reach the portfolio layer

```text
literature backtest net_returns (per strategy_id, dated)
  → series_map_from_literature_results()          [return_alignment.py L36–53]
  → align_strategy_series / align_strategy_series_for_weights  [L56–111]
  → weighted_portfolio_series()                     [L114–137]
  → dashboard artifact portfolio_series             [artifact_generator.py L651–652]
```

Portfolio layer consumes **aligned daily net return series** and **strategy weights** — not raw signals.

### Signals vs positions vs weights vs returns

| Stage | What exists today |
|-------|-------------------|
| Signal | Implicit inside each `weights_*()` builder (scores, ranks, regime flags) |
| Weights | Explicit daily `pd.DataFrame` from builder |
| Positions | Derived from weights × capital in artifact rows / `position_packet` |
| Returns | Computed in `run_strategy_backtest`: `(shifted_weights * returns).sum(axis=1)` |

Strategies do **not** expose a separate signal API; the builder combines signal + portfolio rule.

---

## 3. Market-data architecture

### Where OHLCV comes from

| Source | Path | Role |
|--------|------|------|
| Primary fetch | `src/market/yfinance_client.py::fetch_yfinance_prices()` L25–87 | Downloads daily OHLCV for tickers in `data/config/market_universe.json` |
| CLI | `scripts/fetch_yfinance_market_data.py` | Writes CSV + `output/market_snapshot.json` |
| Boss API (optional) | `src/market/api_client.py::load_market_snapshot()` L25–39 | Env `RMP_MARKET_API_URL`; falls back to yfinance snapshot or mock |
| Backtest read | `literature_backtests.py::load_price_returns()` L83–90 | Reads `data/processed/market_price_history.csv` |

### Multi-stock daily data?

**Partially, but not for Alpha #2 research.**

- The normalized panel is **multi-ticker**, but the configured universe is **~37 liquid ETFs/index proxies**, not a US equity cross-section (`market_universe.json`).
- `load_price_returns()` pivots **`adj_close` only** and computes **simple daily returns** — Open and Volume from CSV are **ignored** in the backtest path.

### Format and columns

**Long format** (one row per date × ticker) written by yfinance client:

| Column | Present | Used in backtest |
|--------|---------|------------------|
| `date` | Yes (ISO date string) | Yes |
| `ticker` | Yes (alias, e.g. `VIX`) | Yes |
| `source_ticker` | Yes | No |
| `name`, `bucket`, `role` | Yes | No |
| `open`, `high`, `low`, `close` | Yes | **No** (not loaded by `load_price_returns`) |
| `adj_close` | Yes | **Yes** (only price field used) |
| `volume` | Yes | **No** |
| `source` | Yes (`yfinance`) | No |

**Wide format** inside backtests: after pivot, `prices` and `returns` DataFrames — index = `DatetimeIndex`, columns = tickers.

Example (column names only):

```text
# Long CSV (data/processed/market_price_history.csv)
date | ticker | source_ticker | open | high | low | close | adj_close | volume | ...

# Wide returns passed to strategy builders
index: date (Timestamp)
columns: SPY, QQQ, IWM, ...
values: daily simple returns from adj_close.pct_change()
```

### Date index, frequency, timezone

- Dates parsed with `pd.to_datetime` (`yfinance_client.py` L64, `literature_backtests.py` L87).
- Frequency: **daily** (`interval="1d"` in yfinance download, L37).
- Timezone: **not explicitly stored**; dates are calendar dates (`.date().isoformat()`), implicitly US market calendar via yfinance trading days.
- Missing rows: skipped at fetch if `close` is NaN (L59–61); panel sorted by `date`, `ticker`.

### Adjustments

- yfinance called with `auto_adjust=False` (L38).
- Both `close` and `Adj Close` stored; backtest uses **`adj_close`** for return construction.

### Open, Close, Volume availability

- **In CSV pipeline:** yes, all three are fetched and stored.
- **In backtest pipeline:** only **`adj_close` → returns**; Open/Close/Volume **not available** to strategy builders today.

### Delisted securities / point-in-time universe

| Feature | Status |
|---------|--------|
| Delisted stocks | **Not supported** |
| Point-in-time universe | **Not supported** |
| Survivorship disclosure | Explicit in backtest metadata (`_backtest_evidence`, L1013) |

---

## 4. Current stock-universe logic

### Where defined

| File | What it defines |
|------|-----------------|
| `data/config/market_universe.json` | Static ETF/index proxy list (~37 tickers) |
| Per-strategy `universe` lists | In each `StrategyPrototype` and registry JSON row |
| `STRAT_013` registry row | Declares intended `US_EQUITY_LIQUID_UNIVERSE` + OHLCV requirements (metadata only) |

### Static vs dynamic

| | Current implementation | Missing | Research limitation |
|---|------------------------|---------|---------------------|
| Universe membership | **Static** list in JSON; no date-varying membership | Point-in-time constituent files | Alpha #2 needs daily cross-section; static ETF list is wrong grain |
| Liquidity filter | **None** on stocks; ETFs assumed liquid | ADV, price, history filters for equities | WQ paper uses liquid US stocks; platform has no ADV gate |
| Data completeness | Inner-join alignment drops missing dates (`return_alignment.py` L68) | Per-date minimum coverage rules for cross-section | Rank needs sufficient names per day |
| Sector/industry | Bucket tags on ETFs (`bucket` field) | GICS/subindustry for `indneutralize` | Alpha #2 does not require industry neutralization, but WQ library does for other alphas |
| Rebalance | Per-strategy: daily/weekly/monthly via `_rebalance_only()` | Universe rebalance schedule | N/A for static ETF list |

### Survivorship bias

**Yes — research limitation acknowledged in code.** ETF proxy universe uses **currently listed** instruments; `_backtest_evidence` notes this (L1013). No historical index membership or delisting handling.

---

## 5. Backtest timing and alignment

### Data flow (implemented path)

```text
market_price_history.csv (adj_close)
  → load_price_returns() → prices wide, returns wide (simple pct_change)
  → strategy.builder(returns) → signal weights DataFrame
  → run_strategy_backtest():
        shifted = weights.shift(1)           # execution lag
        gross = (shifted * returns).sum(axis=1)
        turnover = shifted.diff().abs().sum(axis=1)
        cost = turnover * (BUY_BPS + SELL_BPS) / 2 / 10_000
        net = gross - cost
  → net return series → artifact / portfolio alignment
```

### Timing details

| Question | Answer | Location |
|----------|--------|----------|
| Signal price | Derived from **past return window** inside builders (not explicit OHLC); same-day return row used to form weights | Various `weights_*` functions |
| Execution assumption | Weights computed on day **t** apply to returns on day **t+1** | `run_strategy_backtest` L645–647: `shifted = weights.shift(1)` |
| Return credited | **Close-to-close simple return** on `adj_close` for day t+1 | `load_price_returns` L89 |
| Shift | **Yes — 1 trading day** on weights | L646 |
| Look-ahead control | Explicit comment + shift | L645–646, metadata L770–772 |
| NaN / warm-up | `fillna(0.0)` on shifted weights; `_active_strategy_index()` trims to first non-zero weight row | L646, L965–970 |
| First dates | Rolling windows produce NaN scores; builders often skip empty rows; lag adds another day |

### Look-ahead: key line

```python
# src/strategies/literature_backtests.py ~L645–647
shifted = weights.shift(1).fillna(0.0)
gross = (shifted * returns).sum(axis=1, min_count=1)
```

Weights available at end of day **t** (from data through **t**) affect returns on **t+1** only.

### Small date example (current convention)

Assume builder sets equal weight on SPY for 2024-01-03 from data through that close.

| Date | Weight used (shifted) | Return applied | Notes |
|------|----------------------|----------------|-------|
| 2024-01-02 | 0 (shift) | — | First day after signal |
| 2024-01-03 | 0 | r(Jan-3) | Signal computed Jan-3, not yet active |
| 2024-01-04 | w(Jan-3) | r(Jan-4) | First PnL day for Jan-3 signal |

Return `r(Jan-4)` is `(adj_close Jan-4 / adj_close Jan-3) - 1`.

**Alpha #2 note:** Formula uses **open and close same day** for `(close-open)/open`. Current engine does **not** implement open/close intraday return; would need a separate return definition and likely **additional lag** (signal at close → trade next open).

---

## 6. Transaction costs and portfolio rules

### Transaction costs

| Item | Value | Source |
|------|-------|--------|
| Buy | 5 bps | `BUY_BPS = 5.0`, `platform_config.yaml`, `TransactionCostModel` |
| Sell | 5 bps | `SELL_BPS = 5.0` |
| Application in backtest | `turnover * (BUY_BPS + SELL_BPS) / 2 / 10_000` per day | `run_strategy_backtest` L648–649 |
| Interpretation | **Per-side bps** on traded notional; daily cost uses half sum (effective blended) | Not identical to `TransactionCostModel.rebalance_cost()` but same bps policy |

### Turnover formula

```text
turnover_t = sum_i |w_{i,t} - w_{i,t-1}|     # first day: sum |w_{i,0}|
```

(`literature_backtests.py` L648)

### Long/short, exposure, leverage

| Rule | Support |
|------|---------|
| Short weights | **Partial** — some builders assign negative weights (e.g. `weights_equity_market_neutral` L427–437) |
| Gross exposure | Tracked in `position_packet` (`latest_gross_exposure = sum abs weights`) |
| Net exposure | Tracked (`sum weights`) |
| Dollar-neutral | **Partial** — manual allocation dicts, not generic long-short quantile portfolio |
| Leverage limits | **No explicit leverage cap** in backtest; weights sometimes normalized to sum to 1 (long-only) |
| Weight normalization | Long-only builders use `row / row.sum()`; market-neutral uses fixed long/short splits |
| Portfolio rebalance | Per strategy: `_rebalance_only(every=N)` or daily weight updates |

### Can the existing engine support Alpha #2 portfolio spec?

| Requirement | Verdict |
|-------------|---------|
| Long top 20% of Alpha #2 scores | **Partially** — `_top_n_weights()` does top-N on ETFs, not cross-sectional quantiles on stocks |
| Short bottom 20% | **Missing** as generic quantile short book |
| +50% / −50% exposure | **Partially** — manual weights possible; no standard 50/50 DNE constructor |
| Dollar-neutral | **Partially** |
| Daily signal updates | **Yes** — builders can emit daily rows; costs applied daily |
| Lagged execution | **Yes** — `shift(1)` |

---

## 7. Alpha #2 compatibility assessment

| # | Capability | Status | Evidence |
|---|------------|--------|----------|
| 1 | `log(volume)` by ticker | **Partially supported** | Volume stored in CSV (`yfinance_client.py` L75); not loaded into backtest panel |
| 2 | Two-day time-series `delta` by ticker | **Partially supported** | `pandas.Series.diff(2)` pattern used implicitly (`growth_change = growth.diff(21)` L351); no reusable `delta(x,2)` operator |
| 3 | Intraday return `(close-open)/open` | **Partially supported** | OHLC in CSV; not computed anywhere in `src/` today |
| 4 | Cross-sectional `rank` per date | **Partially supported** | `score.rank(axis=1, pct=True)` in `weights_worldquant_inspired_alpha` L323; ETF columns only, not stock universe |
| 5 | Six-day rolling `correlation` per ticker | **Missing** | No rolling ts correlation helper; pandas can do it but not implemented as operator |
| 6 | Final Alpha #2 score | **Missing** | No alpha2 module |
| 7 | Daily cross-sectional portfolio weights | **Partially supported** | Weight DataFrame pattern exists; quantile long/short constructor missing |
| 8 | Lagged executable positions | **Already supported** | `weights.shift(1)` in `run_strategy_backtest` |
| 9 | Turnover and transaction costs | **Already supported** | L648–650 |
| 10 | Daily net strategy returns | **Already supported** | L647–650 |

---

## 8. Recommended implementation plan

**Do not create these files in Phase 0.** Smallest safe future set:

### Create (new, isolated)

| File | Purpose |
|------|---------|
| `src/strategies/worldquant/operators.py` | Reusable WQ operators: `rank_cs`, `delta_ts`, `correlation_ts`, `log_safe` |
| `src/strategies/worldquant/alpha2.py` | Alpha #2 signal on wide OHLCV panel → daily score panel |
| `src/strategies/worldquant/universe.py` | Equity universe filters (placeholder until PIT data exists) |
| `src/strategies/worldquant/portfolio.py` | Long top 20% / short bottom 20%, gross targets, lag wrapper |
| `src/strategies/worldquant/data_loader.py` | Load long CSV → wide open/close/volume/adj_close; validate columns |
| `data/config/worldquant_alpha2.yaml` | Universe path, lag days, quantiles, cost bps, date range |
| `scripts/run_worldquant_alpha2_backtest.py` | CLI: load data → signal → portfolio → net returns → CSV/JSON |
| `tests/test_worldquant_alpha2_operators.py` | Unit tests for rank/delta/correlation on synthetic panel |
| `tests/test_worldquant_alpha2_alignment.py` | No look-ahead: signal at t does not affect return at t |
| `tests/test_worldquant_alpha2_signal.py` | Golden-value test on tiny 5-stock × 10-day fixture |
| `output/research/worldquant_alpha2/` (gitignored or documented) | CSV backtest outputs |

### Modify (later phases only, after validation)

| File | Purpose |
|------|---------|
| `src/strategies/literature_backtests.py` | Optional: register `PROTO_WQ_ALPHA_2` builder **only after** isolated validation |
| `data/config/strategy_registry.json` | Update `STRAT_013` backtest status / link to prototype ID |
| `scripts/run_literature_strategy_backtests.py` | Wire in new prototype when promoted |
| `src/reporting/artifact_generator.py` | Dashboard integration **last** — after research sign-off |

### Leave untouched (until explicit promotion)

- `dashboard/*` (UI)
- Existing 19 other `weights_*` builders
- `src/risk/limits.py`, allocation weights on main
- `output/dashboard_artifact.json` (production seed)
- Intraday refresh / Render deployment configs

### Required eventual deliverables (checklist)

- [ ] Isolated Alpha #2 signal calculation  
- [ ] Portfolio construction (quantile long/short)  
- [ ] YAML configuration  
- [ ] Data validation  
- [ ] Signal-alignment tests  
- [ ] Unit tests  
- [ ] Baseline backtest script + CSV outputs  
- [ ] Registry integration  
- [ ] Dashboard integration **only after validation**

---

## 9. Risks and blockers

### Data blocker

| Blocker | Severity | Detail |
|---------|----------|--------|
| No US equity cross-section panel in repo | **High** | Universe is ETF proxies; Alpha #2 is stock-level |
| `load_price_returns()` drops Open/Volume | **High** | Backtest path cannot compute Alpha #2 without new loader |
| Processed CSV gitignored | **Medium** | Reproducibility depends on local fetch or external data drop |
| No adjusted volume / split handling documented for volume | **Medium** | `log(volume)` may need split-adjusted volume policy |

### Universe blocker

| Blocker | Severity | Detail |
|---------|----------|--------|
| No point-in-time universe | **High** | Registry acknowledges requirement for STRAT_013; not implemented |
| Survivorship bias | **High** | Acknowledged for ETFs; unacceptable for stock alpha research without mitigation |
| Liquidity filters missing | **Medium** | No ADV/price/history gates |

### Architecture blocker

| Blocker | Severity | Detail |
|---------|----------|--------|
| No formulaic alpha operator library | **High** | Listed in `literature_modules.json` L19–20 as pending |
| Two parallel ID systems (STRAT vs PROTO) | **Medium** | Must map Alpha #2 to `STRAT_013` and/or new `PROTO_WQ_ALPHA_2` deliberately |
| Builders consume **returns**, not OHLCV | **High** | Alpha #2 needs price/volume level panel |

### Execution-timing blocker

| Blocker | Severity | Detail |
|---------|----------|--------|
| Intraday `(close-open)/open` vs close-to-close PnL | **High** | Must define: same-bar signal with close-to-close PnL is inconsistent; need explicit delay convention matching WQ delay-1 |
| Rolling correlation warm-up (6 days) + delta(2) + rank | **Medium** | Minimum history per stock ~8+ trading days before valid scores |

### Testing blocker

| Blocker | Severity | Detail |
|---------|----------|--------|
| No cross-sectional signal tests | **High** | Existing tests use synthetic `adj_close`-only panel (`test_literature_backtests.py`) |
| No golden Alpha #2 fixture | **Medium** | Needed for regression |

### Dashboard-integration blocker

| Blocker | Severity | Detail |
|---------|----------|--------|
| Dashboard tied to literature JSON artifact | **Medium** | Premature integration would affect production seed |
| Research Lab expects full backtest packet shape | **Low** | Pattern exists once `run_strategy_backtest`-compatible output is produced |

---

## 10. Exact next action

### Single safest first implementation step

**Create an isolated operator + data-validation module with unit tests on a synthetic multi-stock OHLCV panel** — prove `rank`, `delta(·,2)`, `log(volume)`, `(close-open)/open`, and 6-day rolling `correlation` per ticker **before** touching portfolio construction or registry.

### First file to create

`src/strategies/worldquant/operators.py`  
(and fixture helper `tests/fixtures/worldquant_alpha2_panel.csv` or inline synthetic DataFrame in test)

### Test that must accompany it

`tests/test_worldquant_alpha2_operators.py` — assert known values on a 5-ticker × 12-day synthetic panel (hand-calculated correlation on last rows).

### Command to run (future)

```powershell
python -m pytest tests/test_worldquant_alpha2_operators.py -q
```

### Questions that must be answered before code

1. **Data source:** Will Alpha #2 use boss-provided US equity OHLCV, or a vendor (Bloomberg/OpenBB), or a research subset (e.g. S&P 500 PIT)?
2. **Universe rules:** Minimum price, ADV, listing history, and **point-in-time** membership source?
3. **Execution convention:** WQ delay-0 vs delay-1 for Alpha #2 — confirm signal at close **t**, trade close **t+1** (align with existing `shift(1)`) or open **t+1**?
4. **Volume treatment:** Split-adjusted volume or raw? Zero/missing volume → NaN or exclude from rank?
5. **Portfolio mapping:** Exact long/short quantile (20/20?), gross/net targets (+50/−50?), and rebalance frequency (daily?)?
6. **Integration target:** Promote as new `PROTO_WQ_ALPHA_2` only, or replace/augment `PROTO_WQ_ALPHA_ETF` and `STRAT_013`?

---

*End of Phase 0 audit.*
