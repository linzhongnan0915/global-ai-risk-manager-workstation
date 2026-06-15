# Build Sequence

Created: 2026-06-05

## Why This Exists

The project became unfocused because strategy research, data ingestion, backtesting, risk analytics, decision logic, and dashboard design were all being built at the same time.

From now on, we build in this order:

1. Strategy universe
2. Data contract
3. Backtest and evidence packet
4. Risk limits and recommendations
5. Dashboard artifact
6. UI layout and polish

UI polish must wait until the underlying data contract is coherent.

## Phase 1: Strategy Universe

Goal: decide what strategies exist and why.

Inputs:

- WorldQuant 101 Alphas
- Hedge Fund Replication
- JPM regime investing
- Ang and Bekaert Markov regimes
- Business-cycle dynamic allocation
- QuantFin implementation note

Output:

- Strategy catalog
- ETF proxy universe
- Strategy hypothesis
- Signal definition
- Rebalance frequency
- Risk limits
- Failure modes
- Evidence status

Do not optimize UI in this phase.

## Phase 2: Data Contract

Goal: make yfinance/OpenBB/boss API interchangeable.

Every data adapter must output:

- Source
- Timestamp
- Ticker / field coverage
- Row count
- Missing values
- Stale data flag
- Price/return panel
- Data quality status

Current fallback:

- yfinance for ETF and market proxies

Next:

- OpenBB adapter
- Boss API adapter if provided

## Phase 3: Backtest Evidence

Every strategy must output:

- Backtest start date
- Backtest end date
- Number of years
- In-sample period
- Out-of-sample period
- Walk-forward train window
- Walk-forward test window
- Number of WFO windows
- Positive OOS window rate
- Average OOS Sharpe
- Transaction cost included
- No-look-ahead check
- Bias notes

Default prototype WFO:

- Train window: 504 trading days
- Test window: 126 trading days

This is an initial rolling evaluation standard, not final parameter optimization.

## Phase 4: Risk Limits And Recommendations

Every strategy and portfolio must expose:

- Current value
- Watch threshold
- Warning threshold
- Breach threshold
- Utilization
- Status
- Recommended action
- Human approval flag

Status colors:

- Green: ok
- Yellow: watch
- Orange: warning
- Red: breach

Allowed actions:

- Keep
- Watch
- Reduce
- Hedge
- Pause
- Rebalance
- Research Hold
- Human Review Required

## Phase 5: Dashboard Artifact

The dashboard consumes only `output/dashboard_artifact.json`.

The UI should not invent:

- Risk scores
- Correlation values
- Factor exposure
- Breach counts
- PnL
- Backtest status
- Walk-forward status
- Recommendations

If a field does not exist in the artifact, the UI should show `Pending evidence`, not fake data.

## Phase 6: UI Workstation Polish

Only after phases 1-5 are stable, redesign the interface against the user's screenshot requirements:

- Dense institutional workstation
- Bloomberg / BlackRock / Bridgewater inspired
- Compact KPI cards
- Dense sortable tables
- Risk badges
- Heatmaps with labels and thresholds
- Drill-down strategy drawer
- Backtest and WFO evidence panels
- Risk limit monitor
- Decision log

## Current Priority

Current priority is not final UI.

Current priority:

1. Finalize strategy catalog from boss papers.
2. Mark which strategies are runnable with ETF/yfinance now.
3. Mark which strategies need OpenBB, macro data, Qlib, or boss API later.
4. Build evidence packets strategy by strategy.
5. Connect risk limits and recommendations to artifact.

