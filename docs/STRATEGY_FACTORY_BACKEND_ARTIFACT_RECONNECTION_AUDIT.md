# Strategy Factory Backend Artifact Reconnection Audit

Date: 2026-06-25

## Scope

This audit covers the local Workstation Strategy Factory tab in:

- `D:\Global_Ai\release_global_ai_risk_manager_workstation`

and the existing Strategy Factory backend/artifact system in:

- `D:\Global_Ai\alpha_research`
- `D:\Global_Ai\alpha_research\strategy_factory`
- `D:\Global_Ai\alpha_research\strategy_factory_workbench`
- `D:\Global_Ai\alpha_research\experiments`

No online deployment is in scope. Brokerage execution remains disabled.

## Existing Code And Artifacts Found

### Intake And Upload Registry

Found under:

- `D:\Global_Ai\alpha_research\strategy_factory_workbench\workbench_data\upload_batches\BATCH_*.json`
- `D:\Global_Ai\alpha_research\strategy_factory_workbench\workbench_data\uploads\...`
- `D:\Global_Ai\alpha_research\strategy_factory_workbench\workbench_data\intake_items.json`
- `D:\Global_Ai\alpha_research\strategy_factory_workbench\workbench_data\dedup\material_hash_registry.json`

The batch JSON schema records `batch_id`, `job_id`, upload root, per-file `material_id`, stored path, extraction status, analysis path, source classification, review status, data readiness, and candidate portfolio status.

### Extraction Outputs

Found under:

- `D:\Global_Ai\alpha_research\strategy_factory_workbench\workbench_data\material_text\*.txt`

Existing statuses include `EXTRACTED_TEXT`, `CSV_HEADER_PREVIEW`, `PDF_TEXT_PREVIEW`, metadata-only states, and unsupported/blocked states. Valid extraction should be counted only when an extracted text artifact exists and has non-zero characters.

### Material Summaries / Analysis

Found under:

- `D:\Global_Ai\alpha_research\strategy_factory_workbench\workbench_data\material_analysis\*.json`

These JSON artifacts include deterministic `RULES_ONLY` classification, detected keywords, candidate ideas, required data, timing risks, survivorship warnings, blockers, testability, and next action.

### Candidate Ideas

Found under:

- `D:\Global_Ai\alpha_research\strategy_factory_workbench\workbench_data\candidate_idea_registry.json`

Records include `idea_id`, title, source batch/material IDs, classification, data required, evidence status, research card/test spec/run plan status, and candidate portfolio default status.

### Research Cards

Found under:

- `D:\Global_Ai\alpha_research\strategy_factory\research_cards\*.md`

Includes named strategy cards such as `JPM_MACRO_ML_SECTOR_ROTATION_V0_research_card.md` and intake drafts such as `INTAKE_*_research_card_draft.md`.

### Test Specs

Found under:

- `D:\Global_Ai\alpha_research\strategy_factory\codex_test_specs\*.md`

Includes strategy test specs and generated intake drafts.

### Run Plans

Found under:

- `D:\Global_Ai\alpha_research\strategy_factory_workbench\workbench_data\run_plans\RUNPLAN_*.json`
- experiment-local run plans such as `D:\Global_Ai\alpha_research\strategy_factory\experiments\*\run_plan\baseline_run_plan.md`

Run plans explicitly state allowed runner, ML policy, prohibited actions, data readiness, and review requirements.

### Backtest, Robustness, ML Diagnostics

Found under:

- `D:\Global_Ai\alpha_research\strategy_factory\experiments\*\outputs\baseline_summary.json`
- `D:\Global_Ai\alpha_research\strategy_factory\experiments\*\outputs\robustness_summary.json`
- `D:\Global_Ai\alpha_research\strategy_factory\experiments\*\outputs\ml_diagnostics_summary.json`
- `D:\Global_Ai\alpha_research\experiments\*\outputs\baseline_summary.json`
- `D:\Global_Ai\alpha_research\experiments\*\outputs\robustness_summary.json`
- `D:\Global_Ai\alpha_research\experiments\*\outputs\ml_diagnostics_summary.json`

Also found associated CSV outputs for portfolio metrics, feature importance, model performance, leakage checks, walk-forward windows, cost sensitivity, liquidity, and beta stability.

### Evidence Reports And Decisions

Found under:

- `D:\Global_Ai\alpha_research\strategy_factory\evidence_reports\*\evidence_report.md`
- `D:\Global_Ai\alpha_research\strategy_factory\evidence_reports\*\missing_evidence.json`
- `D:\Global_Ai\alpha_research\strategy_factory\experiments\*\outputs\decision_memo.md`
- `D:\Global_Ai\alpha_research\experiments\*\docs\decision_memo.md`

### Candidate Registry / Dashboard Summary Exports

Found references in `strategy_factory_workbench\app.py` for:

- `strategy_factory\candidate_results\strategy_candidate_registry.json`
- `strategy_factory\candidate_results\batch01_candidate_registry.json`
- `strategy_factory\candidate_results\experiment_run_registry.csv`
- `strategy_factory\candidate_results\candidate_ranking_v0.json`
- `strategy_factory\exports\control_plane\...`
- `strategy_factory\exports\latest_strategy_factory_summary.json`
- `strategy_factory\exports\strategy_candidate_registry_summary.json`
- `strategy_factory\exports\candidate_portfolio_summary.json`
- `strategy_factory\exports\latest_research_pipeline_status.json`

Some export paths are optional/freshness-gated by the workbench app.

### Candidate Portfolio And Allocation Drafts

Existing alpha workbench exposes a candidate portfolio registry path:

- `D:\Global_Ai\alpha_research\strategy_factory\candidate_portfolio\candidate_portfolio_registry.csv`

The Workstation local paper workflow currently writes paper-only draft artifacts under:

- `output\strategy_factory\candidates\*\candidate_portfolio_draft.json`
- `output\strategy_factory\candidates\*\allocation_draft.json`
- `output\strategy_factory\combined_recompute.json`

Those are Workstation local/test portfolio workflow artifacts, not alpha research evidence.

## What The Workstation Tab Previously Read

Before this reconnection pass, the Workstation Strategy Factory tab primarily read and wrote its own isolated local demo tree:

- `output\strategy_factory\intake\manifest.json`
- `output\strategy_factory\pipeline\*.json`
- `output\strategy_factory\candidates\AI_SECTOR_MOMENTUM_RISK_FILTER_V0\candidate.json`
- generated demo charts under `output\strategy_factory\candidates\...\charts\*.svg`
- generated demo report under `output\strategy_factory\candidates\...\report.md`

That made the tab readable but not truly connected to `alpha_research`.

## Missing / Still Limited

- There is not yet a full backend runner invocation from the Workstation tab for production-grade backtest/ML/evidence generation.
- PDF extraction remains dependent on the available local parser. If no extracted text artifact exists, PDF upload must remain blocked and must not count as analysis.
- Candidate portfolio and allocation drafts are still local/test Workstation paper workflow artifacts, not live or official portfolio records.
- Existing alpha dashboard export freshness is not yet surfaced as a first-class freshness banner in the Workstation tab.
- Real chart embedding from alpha experiment CSV/JSON outputs is not fully mapped yet; chart previews still use existing Workstation chart rendering when local backtest artifacts are created.

## What Can Be Connected Immediately

The new adapter can immediately connect:

- workbench upload batches
- material text extraction artifacts
- material analysis JSON summaries
- candidate idea registry
- research card markdown files
- test spec markdown files
- run plan JSON files
- experiment baseline summaries
- robustness summaries
- ML diagnostic summaries
- evidence report markdown files
- decision memo markdown files

The Workstation stage counters now use these actual artifacts rather than fabricated demo progress. Extract requires non-zero extracted text. Analyze requires a real material analysis artifact and non-zero extracted text. Backtest, ML, evidence, and decision counts require their corresponding real artifact files.

## Reconnection Implemented In This Pass

- Added `src/strategies/strategy_factory_artifact_adapter.py`.
- Workstation upload now writes to the alpha workbench intake layout when `alpha_research` is available.
- TXT/MD/CSV uploads create real alpha-compatible extraction, material analysis, candidate idea, research card draft, test spec draft, and run plan draft artifacts.
- The Workstation Strategy Factory state reads alpha artifacts through the adapter and normalizes them into the existing dashboard payload.
- Stage counters are artifact-truthful and do not count failed/zero-character extraction as analysis.
- The prototype seed remains labeled `PROTOTYPE_SEED_NOT_DERIVED_FROM_UPLOADS`.

