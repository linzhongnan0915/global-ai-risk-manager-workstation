# Strategy Factory Gate 3B All Variant Evaluation

Status: PASS

Gate 3B evaluated every generated copper variant from the Gate 2 registry. It did not rank variants, change dashboard layout, deploy, touch live trading, or mutate the paper ledger.

## Source

- Source run id: `SF_RUN_20260626T135231Z_37A53397`
- Registry: `output/strategy_factory/runs/SF_RUN_20260626T135231Z_37A53397/variants/variant_registry.json`
- Variants attempted: `6`
- Variants evaluated: `6`
- Data mode: local Strategy Factory provider only
- Data limitation: public/proxy data only, prototype research evidence

## Command Used

```powershell
@'
from pathlib import Path
from src.strategies.strategy_factory_variant_evaluation import evaluate_all_variants

root = Path(r"D:\Global_Ai\release_global_ai_risk_manager_workstation")
evaluate_all_variants(root, "SF_RUN_20260626T135231Z_37A53397")
'@ | python -
```

## Per-Variant Results

| Variant | Status | Sharpe | Annual Return | Max Drawdown | ML | Robustness | Decision |
| --- | --- | ---: | ---: | ---: | --- | --- | --- |
| `COPPER_CPER_MOMENTUM_21_63_V1` | `COMPLETED` | `0.187976` | `0.017074` | `-0.243112` | `COMPLETED`, ridge IC `-0.029457`, hit `0.712903` | `WATCH` | `Modify` |
| `COPPER_CPER_MOMENTUM_VOL_FILTER_V1` | `COMPLETED` | `0.473320` | `0.052937` | `-0.182501` | `COMPLETED`, ridge IC `-0.017742`, hit `0.806452` | `WATCH` | `Watch` |
| `COPPER_CPER_DBC_RELATIVE_STRENGTH_V1` | `COMPLETED` | `0.169582` | `0.013984` | `-0.312236` | `COMPLETED`, ridge IC `0.045962`, hit `0.658065` | `WATCH` | `Modify` |
| `COPPER_CPER_UUP_USD_FILTER_V1` | `COMPLETED` | `0.134100` | `0.008931` | `-0.297681` | `COMPLETED`, ridge IC `0.059134`, hit `0.856452` | `WATCH` | `Modify` |
| `COPPER_EQUITY_PROXY_TREND_COPX_XME_V1` | `COMPLETED` | `0.908552` | `0.171695` | `-0.258421` | `COMPLETED`, ridge IC `0.082834`, hit `0.758065` | `WATCH` | `Watch` |
| `COMMODITY_BASKET_REGIME_FILTER_V1` | `COMPLETED` | `0.281852` | `0.030587` | `-0.294642` | `COMPLETED`, ridge IC `-0.029870`, hit `0.783871` | `WATCH` | `Watch` |

No variant was marked `Candidate`. This is intentional: all evidence is still proxy-only, robustness is `WATCH`, and several variants have weak Sharpe or material drawdowns.

## Artifact Check

Each variant now has an `evaluation/` folder containing:

- `variant_backtest_run.json`
- `variant_metrics.json`
- `variant_daily_returns.csv`
- `variant_ml_diagnostics_run.json`
- `variant_robustness_run.json`
- `variant_evidence_report.md`
- `variant_decision.json`

Additional diagnostic files may also exist, including feature importance, train/test split, leakage check, equity curve, and drawdown CSVs.

## Pass / Fail

PASS:

- All variants in `variant_registry.json` were attempted.
- Every variant has an evaluation folder.
- Every variant has metrics or a truthful blocked reason.
- Every variant has `variant_decision.json`.
- No ranking artifact was created.
- No live trading, deployment, dashboard layout change, or paper ledger mutation was performed.

## Remaining Limitations

- Results use public/proxy data and are not point-in-time clean.
- ML diagnostics are research diagnostics, not alpha proof.
- Robustness is not strong enough to support admission.
- This gate records independent evaluations only; it does not choose a winner.

## Next Gate Recommendation

Gate 4 can compare and rank evaluated variants, but only after preserving the distinction between evidence quality and performance. Ranking should penalize proxy-only data, weak robustness, drawdowns, and ML results that do not add clear incremental value.
