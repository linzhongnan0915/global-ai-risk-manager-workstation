# U.S. Stock Momentum + Quality Screen Material

Theme: us_stock_cross_sectional_momentum_quality.

Objective: U.S. stock cross-sectional momentum research with an explicit quality evidence check.

Universe: use the available U.S. equity universe/provider fallback. If a full broad U.S. stock universe is unavailable, use the current available U.S. equity fallback and label the universe limitation clearly.

Benchmark: SPY.

Signal:
- 12-1 momentum, defined as 252d price momentum excluding the most recent 21 trading days, when enough history exists.
- 6-1 momentum, defined as 126d price momentum excluding the most recent 21 trading days, as a shorter-horizon comparison.
- Quality proxy only when source fields exist, such as profitability, ROE, or gross margin. If those fields are unavailable, display Missing Evidence for quality.

Liquidity filter:
- Minimum price if available.
- Minimum dollar volume if available.
- If volume or dollar-volume fields are missing, display Missing Evidence for the liquidity filter.

Portfolio construction: rank U.S. stocks cross-sectionally and hold the top basket equal-weight, using top 20 or top 50 depending on available universe size.

Rebalance: monthly.

Evidence requirements: input universe path, tickers used, date range, signal definition, benchmark, cost assumption, source data paths, and output artifact paths.

ML status: no ML evidence is available unless a U.S. stock-specific feature matrix, target definition, train/test split, fitted model, out-of-sample metrics, and saved artifacts are produced.
