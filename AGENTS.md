# Agent Notes

This repository is a clean release candidate for the Risk Manager Workstation.

## Guardrails

- Do not change strategy definitions.
- Do not change accounting logic.
- Do not change Combined/N semantics.
- Do not change WQ_ALPHA_018 admission status.
- Do not fabricate execution evidence, trades, holdings, NAV, P&L, or research metrics.
- Keep Historical Research separate from Operational records.
- Keep brokerage execution disabled unless a future explicit task changes the release scope.

## Verification

Run the focused release checks before committing:

```powershell
python -m pytest tests/test_phase1_foundation.py tests/test_operational_snapshot.py tests/test_shadow_live_dashboard.py tests/test_production_operational_semantics.py tests/test_wq_alpha018_integration.py -q
python scripts/verify_dashboard_browser.py --no-screenshots
node --check dashboard/foundation-app.js
```

## Generated Files

`output/`, screenshots, logs, caches, `.env` files, and local browser artifacts are ignored and should not be staged.
