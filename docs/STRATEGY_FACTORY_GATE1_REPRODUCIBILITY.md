# Strategy Factory Gate 1 Reproducibility

Date: 2026-06-26

Result: PASS

## Command / API Used

Local API server was started in-process against:

```text
D:\Global_Ai\release_global_ai_risk_manager_workstation
```

Selected controlled copper material:

```text
MAT_CONTROLLED_COPPER_STRATEGY_MATERIAL_001_C39E867D88
controlled_copper_strategy_material.md
```

API calls:

```text
POST /api/strategy-factory/run
Body: {"selected_material_ids":["MAT_CONTROLLED_COPPER_STRATEGY_MATERIAL_001_C39E867D88"]}

POST /api/strategy-factory/jobs/run-full-current-run
Body: {"run_id":"SF_RUN_20260626T135231Z_37A53397"}
```

Both API calls returned HTTP `201`.

## Run ID

```text
SF_RUN_20260626T135231Z_37A53397
```

Run directory:

```text
D:\Global_Ai\release_global_ai_risk_manager_workstation\output\strategy_factory\runs\SF_RUN_20260626T135231Z_37A53397
```

## Artifacts Found

- `run_manifest.json`: found
- `current_run_candidate.json`: found
- `data_availability.json`: found
- `backtest_run.json`: found
- `metrics.json`: found
- `ml_diagnostics_run.json`: found
- `evidence_report.md`: found
- `job_status.json`: found
- `run_log.txt`: found

## Metrics Summary

- `job_status`: `COMPLETED`
- Recommendation: `Watch`
- Metrics status: `COMPLETED`
- Sharpe: `0.31179888189318433`
- Annual return: `0.031023037816325205`
- Max drawdown: `-0.18250067499821387`
- Volatility: `0.12176972649659476`
- Benchmark: `DBC`
- Date range: `2018-04-05 to 2026-06-25`

No fake metrics check: PASS. Core metrics are numeric and artifact-backed.

## Safety Checks

- Live trading: not run
- Deploy: not run
- Paper ledger mutation: PASS

Paper ledger SHA-256 hashes were unchanged before/after the API run:

- `dashboard\data\performance\paper_portfolio_daily.json`
- `dashboard\data\performance\paper_strategy_daily.json`

## Remaining Blockers

- Data remains public/proxy-only.
- Recommendation remains `Watch`, not portfolio admission.
- Current evidence is prototype research only, not institutional validation.
- Broader data, scheduled automation, and variant generation remain future phases.

## Gate 1 Decision

PASS: The controlled copper Strategy Factory current-run pipeline is reproducible end-to-end through the local API before variant generation.
