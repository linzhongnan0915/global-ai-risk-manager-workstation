# Strategy Factory V0 Closeout

Date: 2026-06-26

Status: Frozen V0 local prototype. Do not treat this as institutional validation, portfolio admission, or live trading readiness.

## What Now Works

Strategy Factory V0 can run a local, artifact-bound research workflow for a selected current_run:

- Upload or select research material into the Strategy Factory material library.
- Run a selected batch to create a current_run candidate, research card, test spec, and artifact lineage.
- Check local market data availability through the Strategy Factory data provider interface.
- Use public/proxy local data for a copper proxy backtest when usable symbols exist.
- Generate real prototype backtest artifacts from local data, including metrics, daily returns, equity curve, drawdown, and charts.
- Run ML diagnostics from the same current_run artifacts using chronological train/test split only.
- Generate an evidence report from the same artifact set.
- Run the whole current-run sequence from one local API/dashboard action.
- Record truthful blocked states when data or artifacts are missing. V0 does not fake Sharpe, charts, ML output, returns, or recommendation state.

## Local Server

From the workstation root:

```powershell
cd D:\Global_Ai\release_global_ai_risk_manager_workstation
python scripts\run_workstation_server.py
```

Default local URL:

```text
http://127.0.0.1:8765/dashboard/index.html
```

This is local only. Do not deploy for V0 closeout.

## Run Selected Batch

Dashboard path:

1. Open the local dashboard.
2. Go to `Strategy Factory`.
3. In `Material Library / Inbox + Current Batch`, select one or more materials.
4. Click `Run Selected Batch`.
5. Confirm that a current_run candidate appears in `Candidate Outputs`.

API equivalent:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8765/api/strategy-factory/run `
  -ContentType application/json `
  -Body '{"selected_material_ids":["MAT_CONTROLLED_COPPER_STRATEGY_MATERIAL_001_C39E867D88"]}'
```

## Run Full Current-Run Pipeline

Dashboard path:

1. Open `Strategy Factory`.
2. Confirm a current_run exists.
3. In the `Full Pipeline` panel, click `Run Full Pipeline`.
4. Review Full Pipeline, Backtest, ML, Evidence, Recommendation, and Report Link fields.

API equivalent:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8765/api/strategy-factory/jobs/run-full-current-run `
  -ContentType application/json `
  -Body '{"run_id":"SF_RUN_20260626T000528Z_37A53397"}'
```

The full pipeline runs:

1. Data availability check
2. `backtest-current-run`
3. ML diagnostics
4. Evidence report generation

If any stage is blocked, `job_status.json` records the exact blocked stage and reason.

## API Endpoints

- `GET /api/strategy-factory`
  - Dashboard Strategy Factory state, latest current_run, candidate state, stage statuses, data status, and artifact paths.
- `POST /api/strategy-factory/upload`
  - Upload local research materials.
- `POST /api/strategy-factory/run`
  - Run selected material batch and create current_run artifacts.
- `POST /api/strategy-factory/backtest-current-run`
  - Run current-run data availability, backtest, ML diagnostics, and evidence generation through the existing runner.
- `POST /api/strategy-factory/jobs/run-full-current-run`
  - One-button full current-run job wrapper. Writes `job_status.json` and `run_log.txt`.
- `GET /api/strategy-factory/data/status`
  - Data provider mode, available symbols, latest date, missing data.
- `GET /api/strategy-factory/data/inventory`
  - Local market data inventory.
- `POST /api/strategy-factory/data/refresh-proxies`
  - Safe small proxy refresh path. Do not use for broad 5,000-symbol universe expansion.
- `GET /api/strategy-factory/report/{strategy_id}`
  - Current candidate report/evidence markdown view.

## Artifact Locations

Market data root:

```text
D:\Global_Ai\data\strategy_factory_market_data
```

Core market data artifacts:

- `prices\daily_ohlcv.parquet`
- `prices\daily_returns.parquet`
- `manifests\data_inventory.json`
- `manifests\data_quality_report.json`
- `manifests\provider_status.json`
- `configs\proxy_mapping.yaml`
- `configs\universe_definitions.yaml`

Strategy Factory output root:

```text
D:\Global_Ai\release_global_ai_risk_manager_workstation\output\strategy_factory
```

Latest copper current_run:

```text
SF_RUN_20260626T000528Z_37A53397
```

Latest copper run directory:

```text
D:\Global_Ai\release_global_ai_risk_manager_workstation\output\strategy_factory\runs\SF_RUN_20260626T000528Z_37A53397
```

Generated current-run artifacts:

- `run_manifest.json`
- `batch_manifest.json`
- `selected_materials.json`
- `current_run_candidate.json`
- `current_run_report.md`
- `data_requirements.json`
- `data_availability.json`
- `proxy_mapping_used.json`
- `testability_decision.json`
- `backtest_run.json`
- `metrics.json`
- `daily_returns.csv`
- `equity_curve.csv`
- `equity_curve.svg`
- `drawdown.csv`
- `drawdown.svg`
- `monthly_returns.csv`
- `monthly_returns_table.md`
- `ml_diagnostics_run.json`
- `feature_importance.csv`
- `feature_importance.json`
- `prediction_quality.json`
- `train_test_split.json`
- `leakage_check.json`
- `evidence_report.md`
- `job_status.json`
- `run_log.txt`

Latest full-pipeline status:

- `job_status.json`: `COMPLETED`
- Recommendation: `Watch`
- Stages completed:
  - `DATA_AVAILABILITY_CHECK`
  - `BACKTEST_CURRENT_RUN`
  - `ML_DIAGNOSTICS`
  - `EVIDENCE_REPORT`

Latest copper prototype metrics:

- Data decision: proxy-based current-run evidence
- Benchmark: `DBC`
- Date range: `2018-04-05 to 2026-06-25`
- Annual return: `0.031023037816325205`
- Volatility: `0.12176972649659476`
- Sharpe: `0.31179888189318433`
- Max drawdown: `-0.18250067499821387`
- Turnover: `0.015965166908563134`

## Current Limitations

- Public/proxy data only. V0 uses local public fallback/proxy data, not boss/API/vendor institutional data.
- Current recommendation is `Watch`, not `Candidate`, not paper portfolio admission, and not approval for shadow or live trading.
- Not institutional validation. V0 proves that the local data, backtest, ML diagnostics, evidence report, dashboard, and API pipeline can work end to end.
- Not point-in-time clean. Current data inventory remains prototype-only and not survivorship-bias-free.
- ML diagnostics are diagnostic only. They do not prove causality or persistent alpha.
- No broad universe expansion. V0 intentionally avoids downloading the full 5,000-symbol universe.
- No deployment. V0 is local workstation-only.
- No live trading. Brokerage execution remains disabled.

## Next Phase

Automation V1 should focus on:

- Scheduled current-run pipeline execution.
- Job queue/history for Strategy Factory runs.
- Broader but staged market data refresh with safety limits.
- Boss/API/vendor data provider replacement behind the existing provider interface.
- More complete datasets, including point-in-time security master, corporate actions, delistings, and benchmark history.
- Stronger validation gates before any admission workflow.
- Clear separation between research-only evidence and operational/paper portfolio records.

## 5-Minute Boss Demo Script

1. Open dashboard
   - Start the local server.
   - Open `http://127.0.0.1:8765/dashboard/index.html`.
   - Navigate to `Strategy Factory`.

2. Select material
   - In `Material Library / Inbox + Current Batch`, select `controlled_copper_strategy_material.md` or another copper material.
   - Explain: "This selected batch scopes the run. Historical uploads are not silently mixed into the current_run."

3. Run Selected Batch
   - Click `Run Selected Batch`.
   - Show the current_run candidate and artifact lineage.
   - Explain: "This creates a research card, test spec, selected material manifest, and current-run candidate."

4. Run Full Pipeline
   - In `Full Pipeline`, click `Run Full Pipeline`.
   - Show statuses for Full Pipeline, Backtest, ML, Evidence, Recommendation, and Report Link.
   - Explain: "The pipeline stops or labels blocked stages honestly. It does not fake metrics."

5. Show metrics/charts/ML/evidence report
   - Open candidate details.
   - Show `Backtest`, `Charts`, `ML`, and `Report`.
   - Open the evidence report link.
   - Point to:
     - `metrics.json`
     - `equity_curve.svg`
     - `drawdown.svg`
     - `ml_diagnostics_run.json`
     - `feature_importance.json`
     - `evidence_report.md`

6. Explain recommendation Watch
   - Say: "The current copper result is Watch, not Candidate. It has a low Sharpe, proxy-only data, and prototype data limitations. The evidence is useful, but it does not support portfolio admission."

7. Explain next step
   - Say: "Next is Automation V1: scheduled pipeline runs, broader staged data, and replacing the local parquet provider with boss/API or vendor data through the same interface."

## Focused Regression Check

For this closeout, run the focused Strategy Factory checks:

```powershell
python -m pytest tests/test_strategy_factory_data_layer.py -q
```

This confirms the local data providers, availability decisions, current-run runner, ML diagnostics, evidence report, and full current-run job behavior.
