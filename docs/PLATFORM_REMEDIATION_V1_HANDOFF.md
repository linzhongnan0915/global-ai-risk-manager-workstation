# Platform Remediation v1 — Handoff

**Branch:** `milestone/platform-remediation-v1`  
**Build ID:** `p0a-20260608T010959Z` (from `output/dashboard_artifact.json`)  
**Artifact path:** `output/dashboard_artifact.json`  
**Market as of:** 2026-06-05 | **Operating period:** 2026-06-04 → 2026-06-05  
**Review status:** Milestone complete — ready for **independent GPT review**. Not production-ready.

## Commits by Phase

| Phase | Message | SHA |
|-------|---------|-----|
| 1 | `fix: establish financial truth model and canonical risk status` | `893a43c` |
| 2 | `fix: enforce rebalance risk gates and proposal consistency` | `f544d7c` |
| 3 | `fix: strengthen backtest alignment and model-risk controls` | `b9c4ced` |
| 4 | `refactor: rebuild institutional workstation shell` | `e736cf0` |
| 5 | `refactor: rebuild nine-tab risk manager workflow` | `28dbf25` |
| 6 | `test: complete workstation remediation QA` | `031be28` |

## Major Financial-Logic Changes

1. **Data classification** — Explicit prototype / research / operating-period labels; removed misleading “live portfolio” framing.
2. **Metric availability** — Sharpe, vol, VaR, ES, max DD gated by observation counts; insufficient history → N/A with obs/min obs.
3. **Canonical risk status** — Single backend `risk_status_summary` with deduplicated headline counts; research-quality vs allocated-model breaches separated.
4. **Cash semantics** — Treasury-bill proxy exposure vs unallocated residual cash tracked separately.
5. **Since-investment max drawdown** — Fixed to use return-path drawdown minimum.
6. **Rebalance gates** — Block new hard breaches; flag worsened breaches; no-op when turnover is zero.
7. **Return alignment** — Inner-join on calendar dates; non-zero weight strategies only; no `fillna(0)` on missing returns.
8. **Static reconstruction disclosure** — Documented in `data_quality.static_current_weight_reconstruction`.

## Major UI and Workflow Changes

1. **Single nine-tab navigation** — Removed duplicate left nav rail; collapsible risk status drawer (default collapsed).
2. **Global status bar** — Canonical breach/warn counts, build trace, operating period, market-as-of.
3. **Portfolio Command Center** — Operating-period KPIs with N/A states; historical research banner separated from PnL.
4. **Allocation & Rebalance** — Proposal gates, optimizer label, residual cash vs TBill notes, approval blocking.
5. **Strategy Library & Workflow** — Expanded lifecycle columns with gate statuses.
6. **Decision Log** — localStorage limitation explicitly labeled; execution not authorized.

## Tests and Validation

| Command | Result |
|---------|--------|
| `python -m pytest -q` | **54 passed** |
| `python scripts/validate_framework.py` | **Passed** |
| `python scripts/audit_dashboard_data_contract.py` | **Passed** (100% coverage) |
| `python scripts/generate_dashboard_artifact.py` | **Success** |
| `python scripts/verify_dashboard_browser.py` | **All checks passed**, 0 console errors |

## Screenshots

Location: `output/browser_verification/`

- Nine tabs @ 1440×900: `1440x900_01_*.png` … `1440x900_09_*.png`
- Portfolio Command Center: `command_center_1920x1080.png`, `command_center_1440x900.png`, `command_center_1366x768.png`
- Full-page @ 1920×1080: `01_portfolio_command_center.png` … `09_daily_risk_report_decision_log.png`

## Items Requiring Boss Data or Human Policy

- Formal risk limit thresholds and exception approval authority.
- Live position/NAV/fill feed for true operating-period accounting.
- Approved factor model and macro regime inputs.
- Server-side audit persistence and execution workflow integration.

## Independent Review Recommendation

Review in this order:

1. `output/dashboard_artifact.json` — `data_classification`, `build_metadata`, `operating_period_risk`, `risk_status_summary`, `cash_semantics`.
2. Rebalance simulation — `rebalance_simulation.official_optimizer.proposal_gates`.
3. Dashboard @ 1440×900 — all nine tabs for hierarchy, N/A labels, and research vs operating separation.
4. `tests/test_financial_truth_model.py`, `tests/test_rebalance_gates.py`, `tests/test_backtest_alignment.py`.

See also: [PLATFORM_REMEDIATION_V1_LIMITATIONS.md](./PLATFORM_REMEDIATION_V1_LIMITATIONS.md)
