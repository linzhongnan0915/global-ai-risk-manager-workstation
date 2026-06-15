# Risk Manager Platform: Current State

As of: 2026-06-08 (Platform Remediation v1)

## What This System Is

This project is a multi-strategy portfolio risk management workstation. It helps an independent risk manager review 20 strategies together, challenge a portfolio manager's allocation proposal, document a human decision, and monitor expected versus realized outcomes.

It is not an execution system and it is not a retail investment dashboard.

## Current MVP

- 20 simultaneous monitored strategies with registry, hypothesis, universe, signal, rebalance rule, failure modes, and evidence status.
- 10 strategies pass research-quality eligibility and receive allocation; 10 remain research-only at zero weight.
- Long-history ETF-proxy backtests using yfinance (`strategy_return_source = literature_backtest_net_returns_yfinance_proxy`).
- One-trading-day signal lag and turnover-based transaction costs (5 bps buy / 5 bps sell).
- Full strategy risk packets (summary, distribution, tail risk, drawdown, stability, regimes, benchmark comparison, positions, costs, factor exposure, decision packet).
- Walk-forward out-of-sample evidence attached to all 20 strategies.
- Portfolio risk, proposed allocation, transaction-cost estimate, and expected-impact comparison.
- Independent risk review with blocking objections, warnings, required modifications, and double-check gate.
- Four-stage governance workflow: proposal → independent review → human decision → execution monitoring.
- Nine-tab interactive dashboard with sortable/filterable strategy monitor, strategy detail workspace, editable rebalance simulation, audit log, and daily report exports.
- Tested Python rebalance simulation module embedded in `output/dashboard_artifact.json` and available through `POST /api/simulate` when using `scripts/run_workstation_server.py`.

## Current Decision State

- System conclusion: `Modify Then Human Review`
- Human decision: Not recorded in server-side workflow (local browser audit log supported)
- Execution authorized: No
- Realized outcome: Awaiting authorized execution

Friday portfolio daily PnL is approximately **-$6,893** on allocated strategies. Positive offsets include Event-Driven Sector Risk Proxy (+$430), Managed Futures Trend Proxy (+$44), and Commodity Inflation Shock Sleeve (+$44). Seven allocated strategies lost money. Allocated strategy-level live breaches: **0**. Current hard portfolio/factor breaches: **equity beta** and **credit spread**.

## Data Status

| Layer | Status |
| --- | --- |
| Strategy returns | Real yfinance ETF-proxy literature backtests |
| Portfolio risk window | Common overlapping net-return window across allocated strategies |
| Factor model | Transparent proxy aggregation (provisional, not Barra) |
| Risk limits | Provisional research thresholds in `data/config/risk_limits.yaml` |
| Market monitor | yfinance snapshot when API unavailable |
| News/event risk | Sample snapshot unless boss API configured |
| Positions | ETF-proxy position packets from backtest engine, not live fills |

## Verification Baseline

- `python -m pytest -q` → **29 passed**
- `python scripts/validate_framework.py` → pass
- `python scripts/audit_dashboard_data_contract.py` → **100% coverage**
- `python scripts/verify_dashboard_browser.py` → pass (9 tabs, interactions, exports)

## Run The Workstation

```powershell
python scripts/run_workstation_server.py
```

Open: `http://127.0.0.1:8765/dashboard/index.html`

## Source Of Truth

- Dashboard artifact: `output/dashboard_artifact.json`
- Strategy and risk outputs: `output/risk_manager_tables/`
- Requirements traceability: `docs/REQUIREMENTS_TRACEABILITY.md`
- Institutional workflow: `docs/institutional_decision_workflow.md`
- System workflow image: `output/workflows/risk_manager_platform_workflow.png`
