# Boss Literature Intake

Created: 2026-06-05

## Boss Request

Richard asked us to become familiar with hedge fund alpha signals, hedge fund replication, and regime-based investing, then incorporate these ideas into the portfolio allocation, risk, and optimization process. He also noted that hedge fund replication can become a strategy or set of strategies inside the dashboard.

## Files Reviewed

- `GlobalAi26- DOC- QuantFin_RiskManagement (1).docx`
- `Paper - 101 Alphas - WorldQuant World Quant.pdf`
- `Markov Regimes - JPM Regime-based investing.pdf`
- `Markov Regimes - How Regimes Affect Asset Allocation - By Ang and Bekaert.pdf`
- `Macro Regimes -Dynamic_Asset_Allocation_Through_the_Business_Cycle.pdf`
- `Hedge Fund Replication - Can Hedge Fund Returns be Replicated.pdf`

Extracted text is stored under `output/literature_extracts/` for internal project review.

## Platform Interpretation

The papers imply that the platform should not be only a static multi-strategy monitor. It should become a research-to-allocation system with four institutional research layers:

1. Alpha signal research: build and validate formulaic alphas with strict timing, turnover, cost, and correlation controls.
2. Hedge fund replication: decompose hedge-fund-style returns into liquid factor exposures and residual alpha; build fixed and rolling clone candidates.
3. Macro and business-cycle regimes: classify the market environment and use it to interpret strategy performance and allocation fit.
4. Markov regime risk: use regime probabilities to adjust covariance, correlation, and defensive allocation logic.

## Paper Notes

### WorldQuant 101 Formulaic Alphas

Main message:

- Formulaic alphas can be written as explicit code-like expressions using market data.
- Many signals use open, high, low, close, returns, volume, VWAP, ADV, market cap, ranks, delays, rolling correlations, rolling covariances, and industry neutralization.
- The paper separates delay-0 and delay-1 alphas, which is critical for no-look-ahead backtesting.
- Alphas are short horizon, with average holding periods roughly from intraday/one-day style horizons to several days.
- The average pairwise alpha correlation is low, so value comes from combining many weak signals into an alpha portfolio.
- Turnover alone does not explain alpha correlations, but turnover remains important for cost, capacity, and risk.

Platform implication:

- Build an `Alpha Signal Lab`.
- Do not trade a single formula blindly.
- Start with selected alphas only after the platform supports operators, data fields, delay handling, cost, turnover, and correlation diagnostics.

### Hedge Fund Replication

Main message:

- Hedge fund returns can be separated into common risk factor premia and manager-specific residual alpha.
- The paper uses six factors: USD, bonds, credit spread, S&P 500, commodities, and change in VIX.
- A linear regression can estimate factor exposures and residual alpha.
- Clone portfolios can be built with liquid instruments.
- Fixed-weight clones are useful for explanation but contain look-ahead bias when estimated on full history.
- Rolling-window clones are more realistic but have estimation error and higher rebalancing needs.
- Replication works better for some hedge fund categories than others. It is less effective where illiquidity and event-specific skill dominate.

Platform implication:

- Add a `Hedge Fund Replication Clone Strategy`.
- Track factor beta contribution, residual alpha, R-squared, autocorrelation, liquidity gap, and clone-vs-target risk packet.
- Treat replication as transparent, scalable, lower-cost portable beta, not a full replacement for skilled hedge fund managers.

### JPM Regime-Based Investing

Main message:

- Different asset classes respond differently to growth, inflation, monetary policy, and labor-market conditions.
- No static all-weather portfolio is optimal in every regime.
- Asset behavior is state-dependent and non-linear.
- Regime-based allocation can reduce drawdowns and improve distribution shape, but requires economic foresight.
- The approach should adjust around strategic benchmark weights rather than replace benchmark discipline.

Platform implication:

- Add macro regime labels and confidence.
- Add regime-aware allocation tilts with constraints.
- Show preferred and avoided exposures for each regime.

### Ang and Bekaert Markov Regime Switching

Main message:

- Equity markets can be modeled as normal and high-volatility bear regimes.
- Bear regimes have lower expected returns, higher volatility, and higher cross-market correlations.
- Regimes are persistent but uncertain, so the model should output probabilities.
- Regime-aware allocation can improve out-of-sample performance in illustrative tests.
- High-volatility regimes often justify shifting toward cash or lower-volatility assets.
- Practical use must include constraints, transaction costs, and higher-order risk preferences.

Platform implication:

- Add a Markov regime probability engine.
- Use high-volatility probability to change covariance, correlation, risk-budget, and defensive allocation assumptions.
- Show regime probability, transition risk, and stress-correlation warnings.

### Business Cycle Dynamic Allocation

Main message:

- Valuation is useful over long horizons but weak over short horizons.
- Business-cycle regime analysis is more useful for short and medium-term allocation.
- Four regimes are defined by growth level relative to trend and growth direction: recovery, expansion, slowdown, contraction.
- Financial markets respond more to acceleration/deceleration than the absolute level of growth.
- Risk assets perform best when growth accelerates; government bonds perform best in contraction; slowdown is uncertain and often unattractive.

Platform implication:

- Add a business-cycle regime clock.
- Add regime fit scores for strategies.
- Add allocation reason codes such as recovery risk-on tilt, contraction defensive tilt, or slowdown neutral stance.

### QuantFin Implementation Doc

Main message:

- Boss provided resources around NautilusTrader, Qlib, TradingAgents, Kronos, volatility surface modeling, crypto arbitrage, and prediction-market tools.
- Near-term, Qlib is most relevant for research and backtesting.
- NautilusTrader is more relevant later if the project moves toward execution architecture.
- AI agents should support research and monitoring, not authorize trading decisions.

Platform implication:

- Keep the platform as risk management and decision support.
- Use Qlib-style experiment management later for alpha model research.
- Keep execution-oriented tools as future modules until strategy specs, data, and risk controls are mature.

## Immediate Deployment Plan

1. Add literature modules to `data/config/literature_modules.json`.
2. Expose those modules in dashboard artifacts and the Research Lab.
3. Add Hedge Fund Replication as a named strategy module.
4. Add Alpha Signal Lab as a research module, not an approved strategy yet.
5. Add regime-aware allocation and Markov regime probability to the roadmap.
6. Keep all modules in human-review mode until data, backtests, WFO, costs, and risk packets are complete.

