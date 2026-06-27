# ETF Momentum Rotation Material

Objective: cross-asset ETF momentum rotation.

Universe: SPY, QQQ, IWM, EFA, EEM, TLT, GLD.

Benchmark: SPY.

Signal: compute 63d momentum plus 126d momentum for each ETF at the monthly rebalance date.

Portfolio construction: hold the top 2 or top 3 ETFs equal-weight for the next month.

Rebalance: monthly.

Evidence requirements: use ETF-specific daily adjusted OHLCV, record the input data path, date range, feature definition, benchmark, transaction-cost assumption, and output artifact paths. Do not reuse copper, COPX, XME, or commodity proxy metrics.

ML status: no ML evidence is available unless a separate ETF-specific feature matrix, target definition, train/test split, fitted model, out-of-sample metrics, and saved artifacts are produced.
