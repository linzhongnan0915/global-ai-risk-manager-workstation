# Requirements Traceability Matrix

As of: 2026-06-06  
Artifact date: 2026-06-06  
Strategy count: 20

This matrix maps institutional workstation requirements to contract/config fields, backend implementation, dashboard surface, tests, and verified status. **Partial** and **missing** items are listed explicitly.

Legend: **complete** | **partial** | **missing**

---

## Platform Truths

| Requirement | Contract / Config | Backend | Dashboard | Test | Status |
| --- | --- | --- | --- | --- | --- |
| Initial capital $1,000,000 | `dashboard_artifact_contract.json` metadata.initial_capital; artifact `initial_capital` | `artifact_generator.py` | Header capital KPI | `validate_framework.py` | complete |
| Start date 2026-06-04 | metadata.start_date | registry / artifact metadata | Header date | framework validation | complete |
| Monitor 20 strategies, scale to 30-40 | `strategy_registry.json`; `strategy_scaling_model.md` | `registry.py`, `artifact_generator.py` | Strategy Monitor table (20 rows) | `test_strategy_registry.py` | complete |
| 10 allocated / 10 research-only | `strategy_registry.json` weights | eligibility in `artifact_generator.py` | Allocation editor disables ineligible | artifact audit | complete |
| 5 bps buy / 5 bps sell | registry cost fields; `risk_limits.yaml` | `transaction_cost.py`, backtests | Allocation cost columns | `test_transaction_cost.py`, `test_rebalance_simulation.py` | complete |
| No automatic execution | `decision_governance.yaml` | `decision_workflow.py`, `decision_engine.py` | Approve buttons set `execution_authorized: false` | `test_decision_workflow.py` | complete |
| Human approval + audit trail | UI contract interaction_requirements | `decision_workflow.py` audit_trail (generated); browser `localStorage` only | Approve/modify/reject + localStorage log | browser verify | **partial** — no server-side persistent audit DB |
| Research failures ≠ live breaches | `risk_limits.yaml` research_quality_limits | `evaluate_research_quality_limits` | Sidebar excludes research-only live breaches | `test_risk_limits.py` | complete |
| Historical max DD ≠ auto live breach | workstation contract | strategy vs portfolio limit scopes | Drawer separates max vs current DD | risk limit tests | complete |

---

## Task 1: Documentation And Contract Audit

| Requirement | Contract / Config | Backend | Dashboard | Test | Status |
| --- | --- | --- | --- | --- | --- |
| README reflects real vs provisional | README.md | n/a | n/a | manual review | complete |
| PROJECT_STATE current metrics | PROJECT_STATE.md | artifact metrics | n/a | pytest + artifact inspect | complete |
| NEXT_ACTIONS prioritized | NEXT_ACTIONS.md | n/a | n/a | manual review | complete |
| Artifact contract reconciled | `dashboard_artifact_contract.json` | `artifact_generator.py` | artifact-driven render | `audit_dashboard_data_contract.py` | complete |
| UI contract: no fake risk donuts | `workstation_ui_contract.json` forbidden_patterns | n/a | KPI/limit tables only | UI review | complete |
| Requirements traceability doc | this file | n/a | n/a | manual review | complete |

---

## Task 2: Risk Logic

| Requirement | Contract / Config | Backend | Dashboard | Test | Status |
| --- | --- | --- | --- | --- | --- |
| Consistent portfolio before/after metrics | allocation.before_after | `portfolio_risk_summary`, `rebalance_simulation.py` | Risk before/after panel | `test_rebalance_simulation.py` | complete |
| No front-end approximation as official optimizer | rebalance_simulation in artifact | `build_simulation_context` | Uses artifact/API, removed delta approximation | rebalance + browser | complete |
| Python rebalance simulation module | `rebalance_simulation` contract section | `src/allocation/rebalance_simulation.py` | `/api/simulate` + embedded official_optimizer | `test_rebalance_simulation.py` | complete |
| Gross vs net return in research | backtest_evidence fields; `return_series.gross_returns` | `literature_backtests.py` | `drawGrossNetEquityChart` in Research Lab | `test_literature_backtests.py` | complete (requires regenerated `literature_strategy_backtests.json`) |
| Turnover + 5 bps per-side cost | rebalance_limits | `TransactionCostModel.rebalance_cost` | Allocation editor cost column | `test_rebalance_simulation.py` | complete |
| VaR sign convention (positive loss magnitude) | portfolio_limits | `historical_var` abs | KPI VaR display | `test_rebalance_simulation.py` | complete |
| ES sign convention | portfolio_limits | `expected_shortfall` abs | KPI ES display | `test_rebalance_simulation.py` | complete |
| Current vs historical drawdown | strategy drilldown contract | `performance.drawdown_series` | Drawer + review dialog | `test_performance.py` | complete |
| Rolling windows / OOS walk-forward | backtest_evidence + walk_forward | `literature_backtests.py` | Walk-forward tables | `test_literature_backtests.py` | complete |
| Factor exposure aggregation | factors module data | `_portfolio_factor_analytics` | Factor matrix heatmap | artifact audit | complete |
| Factor limit utilization | factor_limits | `evaluate_factor_limits` | Factor limit alerts | `test_risk_limits.py` | complete |
| Correlation duplicate / hedge classification | correlation_limits | `strategy_correlation_report` | Correlation pairs table | `test_correlation.py` | complete |
| Rebalance shows benefit, confidence, limitations | decision_review.expected_impact | `decision_engine.py` | Allocation KPI + simulation checks | `test_decision_engine.py` | complete |
| Correlation before/after on weight change | allocation.correlation_before_after | fixed historical correlations only | Allocation tab documents limitation | n/a | **partial** |
| Common dated return window (portfolio/risk/corr/sim) | `workstation_ui_contract.json` data_alignment_policy | `return_alignment.py`, `artifact_generator.py` | portfolio chart + risk KPIs share window | `test_return_alignment.py` | complete |
| Residual cash / under-investment | `workstation_ui_contract.json` cash_policy | `rebalance_simulation.py`, `engine.py` | Cash sleeve in simulation checks | `test_rebalance_simulation.py`, browser + API verify | complete |
| Factor exposure before vs after (simulation) | rebalance_simulation factor fields | `_factor_analytics_for_weights` | Factor → grid in `#simulationChecks` | `test_rebalance_simulation.py` | complete |
| Simulation guards on decision/report | simulation_policy | n/a | `recordDecision` / `generateDailyReport` abort on sim failure | browser verify | complete |
| Workstation API path traversal protection | n/a | `run_workstation_server._resolve_static_path` | n/a | `test_workstation_server.py` | complete |

---

## Task 3: Workstation Operability

### Portfolio Command Center

| Requirement | Backend | Dashboard | Test | Status |
| --- | --- | --- | --- | --- |
| Today / why / offsets / losses | strategy PnL in artifact | contributors/detractors + daily explanation | browser verify | complete |
| Live breaches vs research concerns | risk_limits scopes | sidebar + alerts split | browser verify | complete |
| Cumulative return & drawdown chart | portfolio_series | pnlCanvas dual-axis chart | browser screenshots | complete |
| Alert / row drilldown links | strategies + allocation | table-link + data-open-strategy | browser verify | complete |

### Strategy Monitor And Detail

| Requirement | Backend | Dashboard | Test | Status |
| --- | --- | --- | --- | --- |
| Sortable/filterable 20+ table | strategy rows | search + filters + column sort | browser verify | complete |
| Strategy detail workspace | risk_packet per strategy | drawer tabs + review dialog | browser verify | complete |
| Full risk packet sections | literature_backtests risk packet | drawer + checklist + charts | artifact audit 100% | complete |

### Allocation And Rebalance

| Requirement | Backend | Dashboard | Test | Status |
| --- | --- | --- | --- | --- |
| Editable target weights | optimizer proposal base | weight inputs | browser verify | complete |
| Block research-only allocation | eligibility | disabled inputs | browser verify | complete |
| Invested weight + cash display | ledger validation | weight total state | rebalance simulation test | complete |
| Backend-consistent simulation | rebalance_simulation | runSimulation artifact/API | browser + pytest | complete |
| Hard blockers / warnings | limits + simulation checks | simulationChecks panel | pytest + browser | complete |
| Reviewer + note required | governance | decision form validation | browser verify | complete |
| Approve/modify/reject audit log | workflow + localStorage | decisionLog | browser verify | **partial** — browser-only persistence |
| Approval ≠ execution | decision_workflow | status messaging | `test_decision_workflow.py` | complete |

### Risk Factors And Correlation

| Requirement | Backend | Dashboard | Test | Status |
| --- | --- | --- | --- | --- |
| Labeled factor matrix + tooltips | factor analytics | renderRealMatrix titles | artifact audit | complete |
| Limit utilization explanations | evaluate_factor_limits | factorLimitAlerts | test_risk_limits | complete |
| Correlation matrix with names | correlation report | correlationMatrix | test_correlation | complete |
| Duplicate / hedge alerts | correlation summary | correlationPairs | test_correlation | complete |
| Allocated-only vs full-research view | correlation on allocated subset | summary counts both scopes | partial | partial |

### Research Lab

| Requirement | Backend | Dashboard | Test | Status |
| --- | --- | --- | --- | --- |
| Strategy picker updates main research panels | literature_strategy_backtests | literature table click → `renderResearchLabPanels` + caption | browser verify `research_lab_updates_on_selection` | complete |
| Gross/net, equity, DD, distribution, rolling, regimes, WFO | literature_backtests | Research Lab panels | test_literature_backtests | complete |
| IS/OOS dates, bias, cost assumptions | backtest_evidence | bias checklist + meta | artifact audit | complete |

### Daily Report

| Requirement | Backend | Dashboard | Test | Status |
| --- | --- | --- | --- | --- |
| Decision-ready daily memo | decision_review + strategies | generateReport | browser verify | complete |
| JSON / CSV export | n/a | exportJson/exportCsv | browser verify | complete |
| Print / PDF layout | CSS print styles | printReport | browser manual | partial |

---

## Task 4: Institutional UX

| Requirement | Contract | Dashboard | Test | Status |
| --- | --- | --- | --- | --- |
| Dense institutional layout | workstation_ui_contract.json | styles.css compact tables | screenshots 1920x1080 | complete |
| No meaningless donuts / fake scores | forbidden_patterns | removed legacy placeholder KPI block | code audit | complete |
| Risk colors green/yellow/orange/red | risk_colors | statusBadge | visual review | complete |
| Readable charts with axes/legends | UI contract | drawDualAxisChart labels | screenshots | complete |
| Sticky identifiers / scroll discipline | UI contract | monitor table + sidebar | visual review | partial |
| 1600x900 / 1920x1080 / narrow desktop | n/a | responsive CSS | 1920 verified; others partial | partial |

---

## Known Partial / Missing Items (Explicit)

1. **Server-side persistent audit log** — browser `localStorage` only; workflow artifact trail is read-only generated. Status: **partial**
2. **Correlation before/after on weight change** — correlations fixed; allocation note documents limitation. Status: **partial**
3. **Allocated-only correlation view toggle** — matrix shows full research set. Status: **partial**
4. **Boss live data / positions / fills** — still ETF-proxy research. Status: **missing** (intentionally pending)
5. **Production risk limit calibration** — provisional thresholds. Status: **partial**
6. **Print/PDF polish** — print works; PDF styling not production-grade. Status: **partial**
7. **Multi-viewport responsive QA** — 1920 verified; 1600 and narrow not automated. Status: **partial**

---

## Browser Verification (Strengthened)

Script `scripts/verify_dashboard_browser.py` spawns `run_workstation_server.py` on port **8767** and asserts:

| Check | Status |
| --- | --- |
| Custom weight edit triggers simulation | complete |
| Under-investment shows cash sleeve | complete |
| Over-investment blocked in checks | complete |
| Hard breach blocks approval | complete |
| Factor before→after visible | complete |
| Research Lab selection updates panels | complete |
| API under/over-investment + factor numeric checks | complete |

---

## Verification Commands

```powershell
python -m pytest -q
python scripts/validate_framework.py
python scripts/audit_dashboard_data_contract.py
python scripts/generate_dashboard_artifact.py
python scripts/run_literature_strategy_backtests.py
python scripts/run_workstation_server.py
python scripts/verify_dashboard_browser.py
```
