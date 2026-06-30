# Global AI Dashboard Project — Master Context Document

> **Purpose of this file.** Paste this document into any new agent conversation to
> bootstrap full project context. It defines what the system is, what it must
> become, how every tab should behave, the non-negotiable safety / source-of-truth
> / no-hardcode rules, the current build status, and the sequenced roadmap.
> It is the single source of product intent. When it conflicts with ad-hoc
> instructions, raise the conflict explicitly before acting.
>
> **Status:** v1.2 (2026-06-29). Boss research corpus (§3.5). Combined semantics
> resolved (§4.1). Operator-clarity vs cosmetic UI clarified (§1). UI recovery
> sequenced (§14–§16). Tab deprecations, not deletions (§10).

---

## 1. Project Identity

- **Name:** GlobalAI AI Research & Portfolio Risk Platform / Risk Manager Workstation.
- **Local repo:** `D:\Global_Ai\release_global_ai_risk_manager_workstation`
- **Production URL:** `https://global-ai-risk-manager-workstation.onrender.com/dashboard/index.html`
- **Local dev URL:** `http://127.0.0.1:8765/dashboard/index.html`
- **Nature:** paper / shadow portfolio + AI research workstation. **NOT a live
  trading system.** No live brokerage, no live fills, no real money.
- **Current stage goal:** a prototype / paper-shadow system that is genuinely
  usable, logically correct, with a clear backend/artifact source of truth —
  good enough for boss demos and daily internal use, while laying a clean
  foundation for the long-term Quant Research Factory.
- **Boss operating directive (priority order):** the boss does **not** review the
  UI and considers **visual polish** (themes, spacing, animations, cockpit
  cosmetics) low priority. **Information clarity is mandatory:** an operator must
  be able to read what the system knows, what is missing, and what to do next.
  **Misleading or broken UI is a correctness issue, not cosmetic polish** — an
  empty page that looks broken, a stale candidate shown as current output, or a
  missing proposal masked by an old approved plan is as wrong as bad backend
  data. **Correct backend/data and honest information come first;** spend effort
  on underlying state, evidence, and pipeline correctness before decorative
  work. When UI work is needed, it is **operator-clarity recovery** (§14–§15),
  not a beauty pass.

---

## 2. Core Product Vision (the loop the system must close)

The platform is a **Quant Research Factory**, not a static dashboard. The
end-to-end loop:

1. **Ingest research material** (papers, filings, earnings calls, macro/Bloomberg
   notes, boss notes, news, GDELT, Google Trends, …). Long-term this is a
   large-document RAG-for-Alpha system, not a single-PDF summarizer.
2. **Strategy Factory** reads material → extracts hypotheses / signal ideas →
   generates candidate signals → runs **backtest → optimization → ML →
   robustness tests** → produces a *complete strategy* with comparison tables,
   evidence, charts, and factor exposures.
3. **Human review:** the analyst inspects feasible candidates (comparison +
   evidence + charts + factors), then clicks **Proceed** to admit a candidate
   into the **candidate registry** (ACTIVE_UNALLOCATED, 0 current weight).
4. **Allocation** scores all current strategies with a strong, explainable
   scoring logic → recommends next-period add/reduce → transaction cost updates
   accordingly. The analyst can manually adjust the target, or accept the
   recommended target.
5. **Rebalance cadence:** every two weeks the system proposes a rebalance based on
   the recommended target. Apply is **paper-only** and requires explicit human
   approval (see §6 safety).
6. **Monitoring is live and linked:** when a strategy is admitted or a target
   changes, **Strategy Monitor, Command Center, Risk Factors, Workflow** all
   update from the same backend state. No tab may show a different "truth".
7. **Strategy Intelligence** opens the ML black box: from *"what to buy"* to
   *"why buy, where it makes money, where it loses money, what the real exposures
   are"* — mechanism, P&L source, return/risk attribution, factor exposure,
   regime behavior, drawdown explanation, what ML found, what ML did **not**
   prove, and what evidence is missing.
8. **Automation (long-term end state):** drop in many papers → the system
   auto-analyzes, produces outputs and tests, runs the full pipeline → the
   analyst reviews details and manually approves whether to proceed → eventually
   the whole loop runs fully automatically, with a daily dynamic view the analyst
   can read **on a phone**.

**Guiding principle:** every material conclusion cites generated numerical
evidence; missing evidence is shown honestly; prototype evidence is labeled
prototype, not hidden as "Missing".

---

## 3. Quant Research Pipeline Requirements (anti-overfit + regime fit)

The Factory must not become a data-mining machine. Every document-derived signal
and every strategy must carry an **audit trail** and satisfy:

- Explicit **signal date, execution date, return period**; no look-ahead, no
  ambiguous same-bar execution.
- **Gross and net reported separately**; documented transaction costs deducted;
  slippage modeled.
- Train / validation / test; **walk-forward**; purged CV + embargo where
  applicable; OOS.
- **Overfitting controls:** placebo, random-label, shuffled-timestamp tests;
  multiple-testing warning; **deflated Sharpe** warning; sector/size/liquidity
  controls.
- **Current regime relevance (boss priority):** not just historical Sharpe.
  Report recent 3/6/12-month rolling IC, rolling Sharpe, hit rate, drawdown vs
  history, volatility regime, correlation regime, factor crowding, macro regime,
  signal decay. Final question every strategy report must answer: *"Is this
  strategy still suitable for the current market, and why?"*
- **Documents as alternative data (long-term):** topic frequency, sentiment, risk
  disclosure intensity, management-tone change, event counts, theme momentum,
  uncertainty score, geopolitical stress — each with point-in-time timestamp, lag
  assumption, coverage, missingness, provenance, leakage check.

---

## 3.5 Boss Research Corpus (regime-focused) — Strategy Factory inputs

The boss supplied a document corpus (`d:\Global_Ai\Documents\`) to seed the
Strategy Factory's RAG-for-alpha pipeline: ingest a large number of documents,
explore them as alternative data, avoid overfitting, and — ideally — produce
strategies tagged with the **regime(s) in which they work** (the boss's stated
special interest).

- **Regime-based asset allocation (top priority theme):**
  - *Dynamic Asset Allocation Through the Business Cycle* (macro regimes)
  - *How Regimes Affect Asset Allocation* — Ang & Bekaert (Markov regimes)
  - *JPM Regime-based investing* (Markov regimes)
  - → First-class output: for each strategy, identify which regime (bull / bear /
    recovery, plus vol / correlation / macro regime) it works in, and why.
- **Alternative data / commodity forecasting:**
  - *Copper Price Forecasting with Heterogeneous Data* (econometric)
  - two student copper papers (one explicitly using **Google Trends** as a signal)
  - *ETF-DataInputSymbols* (xlsx universe/symbol inputs)
  - → Documents/alt-data become features with point-in-time, lag, and leakage checks.
- **Methodology / factor library:**
  - *JP Morgan — Big Data and AI Strategies*
  - *Financial Machine Learning* (Lopez de Prado school: CPCV, deflated Sharpe)
  - *101 Alphas — WorldQuant* (formulaic alphas; `WQ_ALPHA_018` already exists)
  - *Hedge Fund Replication — Can Hedge Fund Returns be Replicated*

**How the corpus maps to the build:** the Factory should (1) RAG-index these docs
with `document_id` / `material_hash` / `chunk_id` / source / timestamp;
(2) extract candidate signal ideas (regime signals, copper + Google-Trends,
formulaic alphas); (3) run prototype backtest → walk-forward → ML → robustness
with the anti-overfit controls in §3; (4) **tag regime fit**; (5) emit research
cards + evidence for human Proceed review. This is a **prototype on public /
low-cost data**, not an institutional system (see §11.3).

---

## 4. Key Domain Semantics (must be encoded, never hardcoded)

### 4.1 The Combined strategy (RESOLVED 2026-06-29)
- **Combined is ONE sleeve, treated exactly like any other strategy** at the
  allocation/portfolio layer. It is scored, weighted, and increased/reduced by
  the same strong logic as every other sleeve (treat it like a regular strategy).
- Its **internal rule** is **equal-weight across all currently active
  strategies** — this is the boss's requirement and is dynamic by definition.
- Therefore the master paper portfolio = the **score-weighted target across all
  sleeves, including Combined as one of them**. (There is no conflict between
  "Combined = EW" and "score each sleeve": the EW rule lives *inside* the
  Combined sleeve; the scoring/weighting lives *at the portfolio layer* across
  all sleeves.)
- **NEVER hardcode** Combined's member count, weights (e.g. 5.88%, 5.26%), or
  member IDs. When the active set changes (admit/retire), Combined re-derives EW
  automatically. Drive it from `is_combined` metadata + the live active set, not
  literal branches like `COMBINED_PORTFOLIO`.

### 4.2 State vocabulary (keep these strictly separate)
- **Current actual paper portfolio** — what is funded now. Source:
  `/api/operational-snapshot`.
- **Active-unallocated candidate** — admitted via Factory Proceed, **0 current
  weight**, awaiting paper review/funding.
- **P0 proposed target** — the new paper allocation proposal/report artifact
  (suggested + editable target). NOT the current portfolio.
- **Existing approved paper plan** — legacy/current approved rebalance state in
  `data/paper_rebalance/approved_rebalance_plans.json`. **Different from** the P0
  proposal. If the proposal is missing, show "proposal missing / generate first",
  never substitute the old approved plan.

### 4.3 Allocation scoring → add/reduce
- A strong, explainable scorecard ranks strategies (return / risk / evidence /
  diversification / cost / data quality). Top scores → INCREASE, bottom → REDUCE,
  middle → HOLD, candidates → small starter target (generic 2% policy constant,
  not per-strategy hardcode).
- Targets sum to 100%; existing sleeves scale proportionally to make room for
  candidate starters; no fake cash row.
- The analyst can edit targets manually; biweekly rebalance executes the approved
  target on paper only, after explicit approval.

> **Resolved (2026-06-29):** the master portfolio is the **score-weighted target
> across all sleeves, with Combined as one ordinary sleeve** among them (option c).
> Combined's EW rule applies only *inside* the Combined sleeve. See §4.1.

---

## 5. Source-of-Truth Map (backend/artifact-driven; frontend never defines truth)

| State | Source |
|---|---|
| Current actual paper portfolio | `/api/operational-snapshot` |
| P0 proposed target | latest paper allocation proposal/report artifact (`data/automation/allocation_proposals/`, `allocation_reports/`) |
| Existing approved plan | `data/paper_rebalance/approved_rebalance_plans.json` (≠ P0 proposal) |
| Strategy Factory jobs | `data/strategy_factory/jobs/<job_id>.json` |
| Strategy Intelligence | `/api/strategy-intelligence` + local strategy evidence cards |
| Risk Factors | backend risk rows / artifacts; missing must be explicit |
| Daily Report | real portfolio/allocation/factory/risk artifacts; no static pretty memo |

Every tab reads the **same** state logic. If evidence is missing → show
"Missing / Not Available". If it is prototype/public-fallback → label it
"Prototype only / Public fallback / Institutional Validation Pending". Do **not**
show everything as Missing just because the data is not institutional-grade.

---

## 6. Safety Rules (highest priority — never violate)

1. No live trading. No live brokerage. No live fills.
2. No NAV/P&L mutation from any GET / proposal / report / dashboard refresh.
3. No ledger/accounting mutation except an explicit, approved, effective paper
   apply.
4. No approved plan unless explicit user action.
5. No paper apply unless explicit user action **and** effective-date condition.
6. proposal/report endpoints are **review-only**; GET endpoints must not mutate
   financial state.
7. Proof/automation scripts must not create approved plans or apply events, and
   must not pollute runtime state.
8. Generated proof artifacts must not be committed. Canonical artifacts in
   `data/paper_rebalance/` must not be deleted to hide UI issues.
9. No deploy before approval. No merge before PR audit approval.

> **Known safety issue (tracked, see §11):** the background intraday scheduler
> (`run_workstation_server.py`, `_intraday_scheduler_loop`) calls
> `apply_due_approved_rebalance_plan` with **no env gate**, auto-applying due
> approved plans (flips `APPLIED_PAPER`, books transaction cost) without an
> apply-time user action. Pending policy decision (`p1-paper-apply-safety`).

---

## 7. No-Hardcode Rules

**Forbidden in production logic:** strategy names; strategy IDs; Copper / Low Vol
/ C3A / WQ special branches; `COMBINED_PORTFOLIO` literal branch logic; fixed
counts (16/17/18/19); fixed weights (5.88%, 5.26%); display-name identity;
filename identity; frontend-defined active strategy count / weights / status.

**Allowed:** a single generic `2.00%` active-unallocated candidate starter target
(policy constant); test fixtures containing legacy IDs **only if** clearly
labeled fixture/legacy.

**Must use:** `strategy_uid`, `candidate_id`, `material_hash`, `job_id`,
activation lineage, metadata flags (e.g. `is_combined`).

---

## 8. The Five AI Agents (must be real, artifact-backed — not status cards)

- **Research Agent** — literature/papers, factor taxonomy, strategy thesis.
- **Data Agent** — ingestion, validation, freshness, schema drift, missingness.
- **Backtesting Agent** — backtests, CPCV/OOS, robustness, costs, deflated Sharpe.
- **Execution Agent** — turnover, slippage, market impact, capacity, TCA.
- **Risk Agent** — VaR/CVaR, drawdown, exposure, stress tests, regime, alerts.

Do not fake agents with decorative status cards. Each agent's dashboard surface
must be backed by real artifacts it produced.

---

## 9. Long-Term Roadmap (boss's two-track / three-stage progression)

**Track A — Traditional Equity → Macro-ML → Advanced AI** (current focus):
- **A1 Linear Benchmarks:** momentum / value / low-vol / quality;
  OLS/Ridge/LASSO/Elastic Net; Fama-French; basic backtest, cost, turnover;
  Working Paper #1 + Dashboard #1.
- **A2 ML White-Box:** Random Forest, XGBoost/LightGBM, SHAP; walk-forward; HMM
  regime; stress test; HRP; Black-Litterman; factor exposure; Working Paper #2 +
  Dashboard #2.
- **A3 Causality / Derivatives / AI Economy:** DoWhy/CausalML, Granger,
  CausalImpact, DAG; NLP (FinBERT); agent-based macro simulation; CVaR
  optimization; derivatives attribution; Working Paper #3 + Dashboard #3.

**Track B — Crypto / prediction markets / sophisticated systems:** future branch
only. **Do not build now** unless the boss gives clearer requirements.

Each stage produces a Working Paper (academic format) + a Live Dashboard, with
daily data refresh via GitHub Actions and public/low-cost data sources only
(Yahoo, FRED, Alpha Vantage, Polygon, Binance, SEC EDGAR, GDELT, Google Trends,
World Bank, IMF).

---

## 10. Tab Inventory — current state, problems, target, disposition

> Dispositions reflect the analyst's 2026-06-29 review. "REBUILD" = keep the slot,
> redesign content. Mentor pushback is flagged where the analyst's call needs a
> second look.

| # | Tab | Disposition | Target / fix |
|---|---|---|---|
| 1 | Portfolio Command Center | **KEEP + fix** | Open straight to portfolio overview — remove the "Load Details" gate (it is busywork). Architecture is good; ensure every shown value is backed and, where relevant, adjustable. Boss-facing compact KPI strip on top (NAV, Daily P&L, Cumulative/MTD, Drawdown, Sharpe/Vol or "Insufficient History", VaR/ES or "Missing Risk Model", Risk Status, Freshness). Below: Current Membership & Allocation, Strategy Family Mix, Top Contributors/Detractors, Human Review Alerts, compact Master Performance chart, Rebalance Decision Center. No status wall, no oversized chart, no fake Sharpe/VaR/ES. Branch: `p1-command-center-cockpit`. |
| 2 | Strategy Monitor | **KEEP, make live** | Must reflect actual paper state; current active-unallocated = 0% (do not mix with proposed 2%). Linked to the same backend state. |
| 3 | Strategy Intelligence | **REBUILD (priority)** | Not built today. Must open the ML black box: mechanism, why it may profit, where it loses, P&L source, return/risk attribution, factor exposure, regime behavior, drawdown explanation, what ML found vs did not prove, missing evidence, cost/capacity/liquidity risk. Real agent-driven analysis, not chip walls or memo dumps. Master-detail/card layout; prototype evidence labeled prototype; institutional validation pending labeled explicitly. Anchored by the boss's 130-page advanced reference (to be ingested). |
| 4 | Allocation & Rebalance | **SIMPLIFY** | Over-built. Keep one comprehensive strategy table (Current % / Suggested % / editable Target % / Delta / Score / Action / Reason), manual target input, and a right-side interactive panel that **actually works**: Apply Suggested → editable Target only; Normalize/Reset; Save Draft (no mutation); Generate Report uses editable target; Approve is explicit and does not auto-apply; existing approved plan shown separately; proposal-missing state honest. Approve must really drive the portfolio target. |
| 5 | Risk Factors | **KEEP, make live** | Table must auto-add a row with that strategy's values when a new strategy is admitted. Do not fake beta/corr/vol — missing = "Missing / Not Available / Prototype". Candidate rows must not appear as funded portfolio risk. Current factors are too simple; richer factors are a later enhancement. Branch: future risk cleanup, not P0. |
| 6 | Correlation & Diversification | **DEPRECATE / HIDE LATER** | No real content now ("Not Enough Live History"). Do **not** delete this tab in unrelated PRs. Hide or deprecate only in a dedicated, scoped change once there is a replacement or genuine operational correlation history to show. |
| 7 | Universe & Data Coverage | **KEEP, clarify purpose** | Backend should simply know how much data exists; update when the boss API / vendor PIT data arrives. If kept, the page must clearly state its purpose, what data/coverage it shows, and that current data is public-fallback / prototype / current-membership-only (not survivorship-bias-free). |
| 8 | Workflow & Shadow-Live Testing | **KEEP, make live** | Must show the real strategies, where their data comes from, and what each pipeline stage actually did — a living card/grid: Material Intake → Safe Storage → Metadata → Idea Extraction → Research Card → Test Spec → Experiment/Evidence → Candidate Registry → Paper Review → Portfolio Monitor. Counts/status from backend artifacts. State clearly: research pass ≠ live approval; paper monitoring ≠ live trading; public-fallback status; missing evidence explicit. |
| 9 | Strategy Factory | **KEEP — UI structure useful; clarity gaps must be fixed** | The overall workbench layout (material selection, batch panel, stages, outputs) is useful and should be kept. **Not acceptable yet:** (a) stale existing research candidates shown as if they were the current selected-batch output; (b) no clear distinction between "no batch run this session" and "latest job output"; (c) primary button labeled **MODIFY** (must become Review Candidate / Prepare Paper Review / etc.). Backend must actually run the selected-batch chain with multi-select truth; remove hardcode. Long-term: backtest → walk-forward → ML → robustness per §3. |
| 10 | Strategy Library & Governance | **DEPRECATE / HIDE LATER** | Low value as a separate tab today. Do **not** delete in unrelated PRs. Fold essential governance facts into Settings/Strategies when needed; hide or deprecate the tab only in a dedicated, scoped change. |
| 11 | Daily Risk Report / Decision Log | **REBUILD — do NOT delete (mentor override)** | Analyst leaned delete because the current page is unclear, but this tab IS the boss's "Working Paper / daily refresh" deliverable AND the analyst's own "view daily dynamics on a phone" goal. Rebuild it as a clean, boss-facing English daily summary generated from real artifacts (portfolio state, daily P&L, allocation proposal, strategy changes, factory jobs, risk warnings, next actions, missing evidence). No static template, no faked completeness. See §11. |

---

## 11. Open Design Questions & Mentor Notes (resolve before building)

1. **Combined vs scored allocation — RESOLVED (§4.1).** Combined is one ordinary
   sleeve; portfolio = score-weighted across all sleeves; EW lives inside the
   Combined sleeve. No remaining conflict.
2. **Daily Report — RESOLVED: keep + rebuild.** The boss does not read the UI, so
   keep it minimal and clear, but the underlying daily summary must be generated
   from real artifacts and be correct. Do not delete (it is the daily-overview /
   mobile-view deliverable); rebuild for information correctness, not visuals.
3. **Strategy Factory is an explicit PAPER-ONLY PROTOTYPE.** It is unrealistic to
   produce institution-grade alpha from yfinance/public data alone, and the boss
   has not provided vendor data — so do **not** over-engineer realism. The goal is
   to build the full *flow* end to end: ingest many papers → research card →
   backtest → walk-forward optimization → ML → robustness test → output + regime
   tag → human Proceed. Existing bugs/hardcode are real and must be removed, but
   they are small relative to "nothing built yet"; prioritize building the correct
   flow. Anti-overfit *labeling* (§3) stays mandatory; never fake completeness.
4. **Paper-apply automation (§6).** Decide policy: gate the background
   auto-apply behind an env flag + explicit UI action (recommended), or accept
   auto-execution of already-approved plans with clear UI disclosure.
5. **Strategy-detail metric scoping.** In strategy detail cards, verify that
   metrics are strategy-scoped vs combined-scoped (e.g. a single strategy showing
   "Combined Drawdown" or an EW weight is suspect). Audit before trusting.

---

## 12. Engineering Discipline & PR Workflow

- Feature branch only; PR only; no direct `main` commits; no merge/deploy without
  user + audit approval.
- **One objective per PR.** Do not let one PR touch five tabs. Do not let the
  agent act as PM + UI designer + QA + engineer simultaneously.
- Atomic instructions: one blocker, exact files allowed, exact files forbidden,
  expected proof, no broad analysis.
- Generated artifacts stay untracked unless explicitly a labeled test fixture.
- Tests must prove behavior, not echo self-reported flags. Safety properties
  (no GET mutation, no ledger pollution, no auto approve/apply) require observed
  before/after evidence (e.g. byte-hash of canonical files).
- After merge: local smoke on `main` → Render smoke → only then decide deploy.

**Audit principle:** trust PR diff, screenshots, artifacts, tests, git status,
and backend endpoint responses — not self-reported PASS. No PR diff → no PASS.
No artifact → not "backend real". No safety proof → not merge-ready.

**Test evidence format (mandatory when citing results):** always record **exact
command**, **commit SHA** (or branch + SHA), and **test scope** (which files).
Example: `commit 31b1788 | python -m pytest tests/test_p0_....py -q | 6 passed`.
Do **not** use standalone summaries like "88 passed" without command + SHA + scope.

---

## 13. Current Build Status (as of 2026-06-29)

- **PR #1** (`p0-allocation-factory-pr`): scope-crept (mixed Command Center, Risk
  Factors, verifier, tests, UI). **Salvage/reference only — do not merge.**
- **PR #2** (`p0-clean-allocation-factory-foundation`,
  https://github.com/linzhongnan0915/global-ai-risk-manager-workstation/pull/2):
  clean P0 foundation = 7 files (paper allocation proposal/report, factory
  selected batch job, `__init__` exports, server endpoints, minimal UI wiring,
  P0 tests). Scope verified clean via `git diff --name-status main...HEAD`.
  - **Audit result:** backend genuinely clean; source-of-truth separation
    correct; no-hardcode compliant; GET read-only.
  - **Fixes applied (commit `7316029`):** real before/after byte-hash no-mutation
    test (`test_p0_generation_paths_do_not_mutate_canonical_paper_state`); `.gitignore`
    rules for generated P0 artifact dirs.
    - Evidence: `7316029` · `python -m pytest tests/test_p0_paper_allocation_and_factory_job.py -q` · 6 passed.
  - **Further fix (commit `31b1788`):** removed dead duplicate `allocationPage()`;
    updated `test_phase1_foundation.py` markers.
    - Evidence: `31b1788` · `python -m pytest tests/test_phase1_foundation.py tests/test_operational_snapshot.py tests/test_shadow_live_dashboard.py tests/test_production_operational_semantics.py tests/test_wq_alpha018_integration.py tests/test_p0_paper_allocation_and_factory_job.py -q` · 88 passed, 0 failed.
  - **Browser verifier (user-run, local):** `python scripts/verify_dashboard_browser.py --no-screenshots` on PR #2 branch after Playwright chromium install — `geometry_pass: true`; `no_console_errors: false` due to 2 expected 404s on missing proposal/job artifacts (see §16.1).
  - **Residual:** multi-select proven only at wrapper layer (real `run_factory`
    multi-material processing untested) — track.
- **P0 endpoints:** `GET/POST .../paper-allocation-proposal/{latest,generate}`,
  `POST .../paper-allocation-report/generate`,
  `POST /api/strategy-factory/run-selected-batch`,
  `GET /api/strategy-factory/jobs/{latest,<job_id>}`.

---

## 14. Suggested PR Sequencing

**Our build order intentionally differs from the boss's A1/A2/A3 stage order.**
Per the boss directive (§1): backend/data correctness first; **visual polish is
low priority, but operator information clarity is mandatory** — misleading UI is
a correctness defect, not cosmetics.

1. **PR #2** — clean P0 allocation proposal/report + factory selected batch
   foundation. Merge as backend foundation when audit + verification complete.
2. **`p0-ui-recovery-core-tabs`** — **operator-clarity recovery** immediately
   after PR #2. Scoped **only** to Strategy Intelligence, Allocation & Rebalance,
   and Strategy Factory (§15). One tab per atomic PR slice. Fixes misleading
   empty states, master-detail layout, stale-vs-current batch distinction, and
   unacceptable MODIFY wording — not a cockpit beauty pass.
3. `p1-paper-apply-safety` — gate/disclose the background auto-apply (§6, §11.4).
4. `p1-global-state-contract` — unified cross-tab state contract (current /
   proposed / approved / candidate / risk / freshness) so all tabs read one truth.
5. Strategy Factory flow + regime tagging — real end-to-end prototype flow on
   public data; remove hardcode; anti-overfit labeling (§3, §3.5, §10 #9).
6. Strategy Intelligence deep rebuild — open the ML black box beyond layout
   recovery (§10 #3), anchored by boss research corpus (§3.5).
7. Daily Report rebuild from real artifacts (§10 #11); Risk Factors live +
   regime/richer factors (§10 #5).
8. `p1-command-center-cockpit` — Command Center polish (§10 #1). **Lowest
   priority** among near-term UI; cosmetic relative to operator-clarity work.
9. **Tab deprecations (not deletions in unrelated PRs):** Correlation (#6),
   Strategy Library (#10) — hide/deprecate only in a dedicated scoped change.
10. Long-term: large-document RAG-for-alpha → documents-as-alternative-data →
   regime-conditioned strategies → A2 ML white-box → A3 advanced → full automation
   + mobile daily view.

---

## 15. UI Recovery Plan & Audit Gates (immediate next phase, 2026-06-29)

**Near-term step #2 in §14:** `p0-ui-recovery-core-tabs` is an **operator-clarity
recovery** pass after PR #2 — not cosmetic polish. PR #2 reverted the UI to an
early baseline; three core tabs are currently *misleading* (stale candidates look
current, empty pages look broken, MODIFY implies the wrong action). That is a
**correctness defect** under §1. Recovery is scoped **only** to Strategy
Intelligence, Allocation & Rebalance, and Strategy Factory.

### 15.1 Branch & merge sequence
1. Run `python -m playwright install chromium`, then
   `python scripts/verify_dashboard_browser.py --no-screenshots` on PR #2 to
   confirm no runtime JS regression from the `allocationPage()` dedup.
2. **Merge PR #2 first** as the clean backend foundation. UI-not-demo-ready is
   *not* a blocker for a foundation merge; misleading core-tab UI is addressed
   in step 2 (`p0-ui-recovery-core-tabs`), not by blocking the backend merge.
3. Open **`p0-ui-recovery-core-tabs`** (base = `main` after PR #2 merge).
4. Audit the UI recovery PR (diff + screenshots + tests + git status), then decide
   merge → local smoke → Render smoke → deploy decision.

### 15.2 Scope lock (UI recovery)
- **Touch only 3 tabs:** Strategy Intelligence, Allocation & Rebalance,
  Strategy Factory.
- **Allowed files:** `dashboard/foundation-app.js`; `dashboard/foundation.css`
  only if truly needed.
- **Forbidden tabs:** Command Center, Risk Factors, Correlation, Universe,
  Workflow, Strategy Library, Daily Report.
- **Forbidden files:** `scripts/run_workstation_server.py` (endpoints),
  `src/automation/*`, backend allocation/factory logic, `data/**` generated
  artifacts, `REVIEW_*`, proof files, `GLOBAL_PROJECT_SNAPSHOT.md`.
- **Rule:** render existing backend truth more honestly/readably; do NOT invent
  new frontend-defined state (so it won't fight the future state-contract).

### 15.3 Per-tab recovery acceptance (honest + readable + non-misleading; NOT final cockpit)
- **Strategy Intelligence (worst, highest priority):** readable master-detail —
  top summary cards; left strategy list at proper width (no narrow strip); right
  detail (mechanism / why it may make money / where it may lose / evidence / ML /
  attribution / missing evidence; sources collapsed). No fake ML/attribution/causality.
- **Allocation & Rebalance:** intentional P0 workbench — clear empty state +
  "Generate Proposal" CTA before generation; after generation a table of
  Strategy / Current% / Suggested% / editable Target% / Delta / Score / Action /
  Reason + ops panel; "Existing Approved Paper Plan" in its own section labeled
  "Not current P0 proposal"; legacy tool collapsed and titled
  "Legacy / Manual Draft Tool — Not Current P0 Proposal". Never fill a missing
  proposal with the old approved plan; no auto approve/apply.
- **Strategy Factory:** keep the existing workbench **structure** (selection,
  batch panel, stages, outputs). **Must fix clarity gaps:** explicit "no selected
  batch run this session" state; stale candidate quarantined in "Existing / Stale
  Research Candidate", never shown as current output; after a run show
  job_id / selected_material_count / selected_material_ids / stages / outputs;
  **MODIFY is not acceptable** — primary action → "Review Candidate" /
  "Prepare Paper Review". No hardcoded strategy/file names; no fake admission.

### 15.4 Honesty-label vocabulary (allowed, must be used instead of faking)
`Paper Only` · `Public Fallback` · `Prototype Only` · `Research Evidence
Available` · `Institutional Validation Pending` · `Missing ML Evidence` ·
`Missing Attribution` · `Not PIT` · `Not survivor-bias-free`.

> **Core rule:** Prototype is allowed. Paper-only is allowed. Public fallback is
> allowed. **Fake truth is not allowed.** Block ONLY fake / hardcoded / unsafe /
> misleading work — never block merely because it is paper, prototype, public
> data, or has incomplete ML/attribution/causality.

### 15.5 Merge-gate audit checklist (do not trust self-reported PASS)
- No PR diff → no PASS.
- No screenshots → cannot claim "UI fixed".
- No artifact → cannot claim "backend real".
- Any generated file staged → no merge.
- Any new hardcode → no merge.
- Old approved plan / P0 proposal confused → no merge.
- Any fake ML / attribution / causality → no merge.
- Any live-trading implication → no merge.
- Always inspect: diff, screenshots, artifacts, tests, `git status`, endpoint responses.

---

## 16. Locked decisions & first Codex task (2026-06-29)

### 16.1 Locked decisions
- **PR #2: APPROVED to merge** as the clean backend foundation.
  - Test evidence: commit `31b1788` on `p0-clean-allocation-factory-foundation` ·
    `python -m pytest tests/test_phase1_foundation.py tests/test_operational_snapshot.py tests/test_shadow_live_dashboard.py tests/test_production_operational_semantics.py tests/test_wq_alpha018_integration.py tests/test_p0_paper_allocation_and_factory_job.py -q` ·
    88 passed, 0 failed.
  - Browser evidence (user-run): `python scripts/verify_dashboard_browser.py --no-screenshots` ·
    `geometry_pass: true`; `no_console_errors: false` — two **expected** 404s when
    proposal/job artifacts are missing; **not a merge/safety blocker** (see below).
- **Known follow-up (not a blocker; separate small change, NOT in UI-recovery scope):**
  `/api/automation-intelligence/paper-allocation-proposal/latest` and
  `/api/strategy-factory/jobs/latest` currently return HTTP **404** when no
  artifact exists yet (run_workstation_server.py lines ~762/772). They SHOULD
  return **200 with `{ok:false, status:"MISSING_ARTIFACT"}`** so an empty-but-valid
  state is not an HTTP error and the dashboard has no console noise. Requires the
  frontend to read the body flag, not `r.ok`.
- **Next branch:** `p0-ui-recovery-core-tabs` (base = `main` after PR #2 merge).
  Do **one tab at a time**; first slice = **Strategy Intelligence only**.

### 16.2 First Codex task — Strategy Intelligence layout recovery (atomic)
**Goal:** turn the current squeezed table into a readable master-detail research
view. Do NOT change backend, endpoints, or any other tab.

**Allowed files:** `dashboard/foundation-app.js`; `dashboard/foundation.css` (only
the Strategy Intelligence layout rules).

**Current code to work from (do not rewrite the whole file):**
- `strategyIntelligencePage()` (~line 1341) — page composition.
- `strategyIntelligenceMetricCards(p)` (~1333) — KEEP the 6 summary cards on top.
- `strategyIntelligenceRows(p)` (~1339) — currently one wide `span-12` table; this
  is the squeezed element to replace with a master-detail layout.
- `strategyIntelligenceEvidencePanel(card)` (~1337) — REUSE as the right-side detail.

**Do:**
1. Add `state.selectedIntelligenceUid` (default = first card's `strategy_uid`).
2. Replace the single wide table with a two-column layout inside the page:
   - LEFT: a readable strategy list from `p.cards` (each row: `strategy_name`,
     `strategy_uid`, today action/status, evidence + ML status badges), each row
     clickable via `data-intel-uid`. Proper column width (~320–380px), not a strip.
   - RIGHT: detail for the selected card = `strategyIntelligenceEvidencePanel(card)`
     plus the already-present fields used in `strategyIntelligenceRows` (family,
     mechanism, edge thesis, research decision) and an explicit "Missing Evidence"
     block. Use only fields already on the card object — do not invent ML /
     attribution / causality.
3. Add `bindIntelligenceControls()` (mirror `bindP0AllocationControls`) to wire the
   `data-intel-uid` clicks to set `state.selectedIntelligenceUid` and `render()`.
4. Add CSS for `.strategy-intelligence-layout{display:grid;grid-template-columns:
   minmax(320px,380px) 1fr;gap:16px}` (and make the page fill width — no huge right
   whitespace). Keep `.strategy-intelligence-kpis` on top.

**Honesty:** missing evidence → use labels from §15.4 (Missing ML Evidence /
Missing Attribution / Prototype Only / Institutional Validation Pending / Not PIT).
Never fake numbers, ML, attribution, or causality. Keep the empty state
("Pending Detail" / no cards) honest.

**Forbidden:** backend logic, `run_workstation_server.py`, `src/automation/*`,
generated artifacts (`data/**`), other tabs, `REVIEW_*`, proof files, hardcoded
strategy names/IDs/counts/weights, `git add .`.

**Verify (must show, do not self-report PASS):** cite **command + commit SHA +
scope** for every test run (§12).
- `node --check dashboard/foundation-app.js`
- `python -m pytest tests/test_phase1_foundation.py -q` (scope: phase1 foundation only)
- `python scripts/verify_dashboard_browser.py --no-screenshots` → report
  `geometry_pass: true`; no NEW console errors beyond the known 2 expected 404s.
- Screenshots of Strategy Intelligence at 1440x900 and 1920x1080 (left list filled,
  right detail populated, no narrow strip, no large empty area).
- `git status` clean of generated/artifact files; diff limited to the 2 allowed files.

---

## 17. How to Use This Document in a New Conversation

1. Paste this file at the start.
2. State the **single** objective for that session (one PR / one blocker).
3. Name the exact files allowed and forbidden.
4. State the expected proof and required evidence to return.
5. Require the agent to act as strict auditor: independent judgment, no scope
   creep, no fake completeness, no self-reported PASS, surface conflicts with
   this document before acting.
