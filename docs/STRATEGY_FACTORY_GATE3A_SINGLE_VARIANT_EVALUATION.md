# Strategy Factory Gate 3A Single Variant Evaluation

Status: PASS

Gate 3A evaluated exactly one generated copper variant. It did not evaluate all variants, rank variants, change dashboard layout, deploy, touch live trading, or mutate the paper ledger.

## Source

- Source run id: `SF_RUN_20260626T135231Z_37A53397`
- Variant id: `COPPER_CPER_MOMENTUM_21_63_V1`
- Variant name: `CPER Momentum 21/63`
- Variant spec: `output/strategy_factory/runs/SF_RUN_20260626T135231Z_37A53397/variants/COPPER_CPER_MOMENTUM_21_63_V1/variant_spec.json`
- Data mode: local Strategy Factory provider only
- Proxy/universe: `CPER`
- Benchmark: `DBC`

## Command Used

```powershell
@'
from pathlib import Path
from src.strategies.strategy_factory_variant_evaluation import evaluate_single_variant

root = Path(r"D:\Global_Ai\release_global_ai_risk_manager_workstation")
evaluate_single_variant(root, "SF_RUN_20260626T135231Z_37A53397", "COPPER_CPER_MOMENTUM_21_63_V1")
'@ | python -
```

## Generated Artifacts

Evaluation folder:

`output/strategy_factory/runs/SF_RUN_20260626T135231Z_37A53397/variants/COPPER_CPER_MOMENTUM_21_63_V1/evaluation/`

- `variant_backtest_run.json`
- `variant_metrics.json`
- `variant_daily_returns.csv`
- `variant_equity_curve.csv`
- `variant_drawdown.csv`
- `variant_ml_diagnostics_run.json`
- `variant_feature_importance.csv`
- `variant_feature_importance.json`
- `variant_prediction_quality.json`
- `variant_train_test_split.json`
- `variant_leakage_check.json`
- `variant_robustness_run.json`
- `variant_evidence_report.md`
- `variant_decision.json`

## Metrics

- Status: `COMPLETED`
- Date range: `2018-01-03` to `2026-06-25`
- Rows: `2130`
- Annual return: `0.017074`
- Benchmark annual return: `0.079467`
- Sharpe: `0.187976`
- Volatility: `0.150528`
- Max drawdown: `-0.243112`
- Turnover: `39.0`
- Cost assumption: `5 bps` per side

These are real local-data prototype metrics. They are not portfolio admission evidence and are not institutional validation.

## ML Result

- ML status: `COMPLETED`
- Primary model: `ridge_regression_numpy`
- Split: chronological, no shuffle
- Train dates: `2018-04-05` to `2024-01-02`
- Test dates: `2024-01-03` to `2026-06-24`
- Sample count: `2066`
- Ridge Spearman IC: `-0.029457`
- Ridge direction hit rate: `0.358065`
- Logistic direction hit rate: `0.712903`
- Leakage check: `PASS`
- Random forest / gradient boosting: `BLOCKED`, because `sklearn` is unavailable locally

The ML diagnostics are mixed: the direction classifier has a high hit rate on this return stream, but the primary ridge return IC is negative. This does not support Candidate status.

## Robustness Result

- Robustness status: `COMPLETED`
- Overall: `WATCH`
- Cost sensitivity: `PASS`
- Lookback sensitivity: `PASS`
- Benchmark comparison: `WATCH`
- High-vol period Sharpe: `-0.753402`
- Recent period Sharpe: `0.410666`
- DBC benchmark annual return exceeded the variant annual return over the tested period.

## Final Decision

Recommendation: `Modify`

Reason: weak risk-adjusted performance, proxy-only data, and robustness that does not clearly beat the benchmark. The variant can be evaluated end-to-end, but the evidence does not justify Candidate status.

## Pass / Fail

PASS:

- Variant spec was read correctly.
- Evaluation artifacts were created.
- Metrics are numeric because the backtest ran on local CPER/DBC data.
- ML artifact exists and uses a chronological split.
- Robustness artifact exists.
- Evidence report exists.
- No live trading, no deployment, no dashboard layout change, no paper ledger mutation, no all-variant evaluation, and no variant ranking were performed.

## Next Gate Recommendation

Gate 3B can scale this same evaluation contract across the remaining generated variants, but it should still avoid ranking until each variant has truthful backtest, ML, robustness, and decision artifacts.
