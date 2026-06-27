# Strategy Factory Functionality Audit

Date: 2026-06-25  
Scope: local Strategy Factory selected-batch path in `D:\Global_Ai\release_global_ai_risk_manager_workstation`, connected to `D:\Global_Ai\alpha_research`.

## Executive Result

PASS: Strategy Factory can take a selected text/markdown material and produce real current-run research output.

The smoke test used the same backend plugin path that the dashboard calls:

1. `save_uploaded_materials(...)`
2. `run_factory(..., selected_material_ids=[...])`
3. `base_state(...)` equivalent payload for `/api/strategy-factory`

The run produced extraction, material analysis, material-derived ideas, research card draft, test spec draft, current-run candidate, current-run report, run manifest, batch manifest, and run log artifacts.

Backtest and ML are not wired for this current-run path. They are truthfully marked `NOT_IMPLEMENTED / BLOCKED`; no Sharpe, charts, or ML diagnostics were fabricated.

## Controlled Input

Test material:

`D:\Global_Ai\release_global_ai_risk_manager_workstation\output\strategy_factory_functionality_audit\controlled_copper_strategy_material.md`

Content included:

- copper price forecasting
- 3-month momentum
- volatility filter
- USD trend
- inventory signal
- copper ETF/proxy universe
- broad commodities or SPY benchmark
- monthly rebalance
- no leverage

Reusable smoke command:

```powershell
python scripts\strategy_factory_functionality_smoke.py
```

Smoke result JSON:

`D:\Global_Ai\release_global_ai_risk_manager_workstation\output\strategy_factory_functionality_audit\smoke_result_after_fix.json`

## Run Identity

- `material_id`: `MAT_CONTROLLED_COPPER_STRATEGY_MATERIAL_001_C39E867D88`
- `run_id`: `SF_RUN_20260626T000528Z_37A53397`
- `batch_id`: `BATCH_SCOPE_SF_RUN_20260626T000528Z_37A53397`
- `candidate_id`: `RUN_SCOPED_CANDIDATE_SF_RUN_20260626T000528Z_37A53397`
- `candidate_name`: `Current Run: Etf Proxy Research Idea`

## PASS / FAIL Matrix

| Stage | Status | Evidence |
| --- | --- | --- |
| Extraction | PASS | Text extraction artifact exists and material shows `Extracted`. |
| Material analysis | PASS | `material_summary.json` exists and analysis includes material-derived themes/ideas. |
| Idea generation | PASS | `extracted_ideas.json` exists and includes ETF proxy, commodities, momentum, and volatility ideas. |
| Research card | PASS | Research card draft exists in alpha_research. |
| Test spec | PASS | Test spec draft exists in alpha_research. |
| Report generation | PASS | `current_run_report.md` exists. |
| Dashboard visibility | PASS | Payload contains `latest_run`, `latest_run_output`, and `current_run_candidates`. |
| Backtest | BLOCKED | Current-run backtest runner is not implemented/wired. No metrics or charts generated. |
| ML | BLOCKED | Current-run ML diagnostics runner is not implemented/wired. No ML artifact generated. |

## Artifact Paths

| Artifact | Exists | Path |
| --- | --- | --- |
| controlled material | PASS | `D:\Global_Ai\release_global_ai_risk_manager_workstation\output\strategy_factory_functionality_audit\controlled_copper_strategy_material.md` |
| stored material | PASS | `D:\Global_Ai\alpha_research\strategy_factory_workbench\workbench_data\uploads\BATCH_20260626T000518Z_83490BCF\001_controlled_copper_strategy_material.md` |
| extracted text | PASS | `D:\Global_Ai\alpha_research\strategy_factory_workbench\workbench_data\material_text\MAT_CONTROLLED_COPPER_STRATEGY_MATERIAL_001_C39E867D88.txt` |
| selected materials | PASS | `D:\Global_Ai\release_global_ai_risk_manager_workstation\output\strategy_factory\runs\SF_RUN_20260626T000528Z_37A53397\selected_materials.json` |
| material summary | PASS | `D:\Global_Ai\release_global_ai_risk_manager_workstation\output\strategy_factory\runs\SF_RUN_20260626T000528Z_37A53397\material_summary.json` |
| extracted ideas | PASS | `D:\Global_Ai\release_global_ai_risk_manager_workstation\output\strategy_factory\runs\SF_RUN_20260626T000528Z_37A53397\extracted_ideas.json` |
| research card | PASS | `D:\Global_Ai\alpha_research\strategy_factory\research_cards\INTAKE_MAT_CONTROLLED_COPPER_STRATEGY_MATERIAL_001_C39E867D88_research_card_draft.md` |
| test spec | PASS | `D:\Global_Ai\alpha_research\strategy_factory\codex_test_specs\INTAKE_MAT_CONTROLLED_COPPER_STRATEGY_MATERIAL_001_C39E867D88_test_spec_draft.md` |
| current run candidate | PASS | `D:\Global_Ai\release_global_ai_risk_manager_workstation\output\strategy_factory\runs\SF_RUN_20260626T000528Z_37A53397\current_run_candidate.json` |
| current run report | PASS | `D:\Global_Ai\release_global_ai_risk_manager_workstation\output\strategy_factory\runs\SF_RUN_20260626T000528Z_37A53397\current_run_report.md` |
| run manifest | PASS | `D:\Global_Ai\release_global_ai_risk_manager_workstation\output\strategy_factory\runs\SF_RUN_20260626T000528Z_37A53397\run_manifest.json` |
| batch manifest | PASS | `D:\Global_Ai\release_global_ai_risk_manager_workstation\output\strategy_factory\runs\SF_RUN_20260626T000528Z_37A53397\batch_manifest.json` |
| run log | PASS | `D:\Global_Ai\release_global_ai_risk_manager_workstation\output\strategy_factory\runs\SF_RUN_20260626T000528Z_37A53397\run_log.txt` |

## Content Quality Check

Required terms from the controlled material were found in generated output:

| Term | Status |
| --- | --- |
| copper | PASS |
| commodities | PASS |
| momentum | PASS |
| volatility | PASS |
| benchmark | PASS |
| rebalance | PASS |

The output was not the old prototype seed as the main current-run result. The generated current-run candidate was:

`RUN_SCOPED_CANDIDATE_SF_RUN_20260626T000528Z_37A53397`

The candidate source label was:

`SELECTED_BATCH_ARTIFACT_LINEAGE`

## Dashboard Payload Check

`/api/strategy-factory` equivalent payload contains:

| Field | Status |
| --- | --- |
| `latest_run` | PASS |
| `latest_run_output` | PASS |
| `current_run_candidates` | PASS |
| selected material names | PASS |
| research card path | PASS |
| test spec path | PASS |
| report path | PASS |

## Backtest / ML Truth

Backtest:

`NOT_IMPLEMENTED / BLOCKED`

Reason: the selected-batch path currently generates research artifacts and a test spec, but does not invoke an executable candidate-specific backtest runner.

ML:

`NOT_IMPLEMENTED / BLOCKED`

Reason: the selected-batch path currently does not invoke a candidate-specific ML diagnostics runner.

No Sharpe, returns, drawdown, charts, or ML metrics were generated or fabricated by this audit.

## Conclusion

Strategy Factory V0 is no longer only displaying historical/prototype artifacts for selected materials. It can ingest a selected text/markdown material and produce current-run research output through material summary, extracted ideas, research card draft, test spec draft, current-run candidate, and current-run report.

The next functional gap before automation is the execution layer after test spec: candidate-specific backtest and ML diagnostic jobs are still blocked/not implemented.
