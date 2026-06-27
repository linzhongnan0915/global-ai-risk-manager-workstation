# Strategy Factory Gate 2 Variant Generation

Date: 2026-06-26

Result: PASS

## Source Run

```text
SF_RUN_20260626T135231Z_37A53397
```

Source material:

```text
MAT_CONTROLLED_COPPER_STRATEGY_MATERIAL_001_C39E867D88
controlled_copper_strategy_material.md
```

Strategy type:

```text
commodity trend / macro proxy
```

## Command Used

Generated specifications only:

```powershell
python - <<'PY'
from pathlib import Path
from src.strategies.strategy_factory_variants import generate_strategy_variants

root = Path(r"D:\Global_Ai\release_global_ai_risk_manager_workstation")
generate_strategy_variants(root, "SF_RUN_20260626T135231Z_37A53397")
PY
```

No backtests, ML diagnostics, rankings, deployment, live trading, or paper-ledger mutation were performed.

## Output Folder

```text
D:\Global_Ai\release_global_ai_risk_manager_workstation\output\strategy_factory\runs\SF_RUN_20260626T135231Z_37A53397\variants
```

Generated:

- `variant_registry.json`
- `variant_generation_report.md`
- `variants/<variant_id>/variant_spec.json` for each variant

## Variants

| Variant | Testability | Data / Proxy Used |
|---|---|---|
| CPER Momentum 21/63 | PROXY_ONLY | CPER, DBC |
| CPER Momentum + Volatility Filter | PROXY_ONLY | CPER, DBC |
| CPER vs DBC Relative Strength | PROXY_ONLY | CPER, DBC |
| CPER Momentum + UUP/USD Filter | PROXY_ONLY | CPER, DBC, UUP |
| COPX/XME Copper Equity Proxy Trend | PROXY_ONLY | COPX, XME, SPY |
| Commodity Basket Regime Filter | PROXY_ONLY | CPER, DBC |

Number of variants: `6`

## Pass / Fail

PASS:

- `variant_registry.json` exists.
- At least 3 variants generated.
- Each variant has a `variant_spec.json`.
- Variants use distinct signal logic or risk filters.
- At least one local copper/proxy variant is testable as `PROXY_ONLY`.
- No Gate 2 backtest, ML, or ranking artifacts were generated inside the variants folder.

## Remaining Limits

- All variants are `PROXY_ONLY` because Gate 2 uses local public/proxy data.
- No variant is marked Candidate.
- Variants are hypotheses/specifications only.
- Institutional data, point-in-time controls, and actual performance evaluation remain future gates.

## Next Gate Recommendation

Gate 3 should run controlled variant evaluation:

- backtest each variant with the same data provider interface
- run robustness and stress checks per variant
- compare variants without tuning on the final test window
- keep recommendation conservative until performance, robustness, ML lift, and data quality support it
