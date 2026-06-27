# U.S. Stock Low Vol Defensive Material

Theme: us_stock_low_vol_defensive

Objective: Build a defensive U.S. equity stock strategy that ranks stocks by lower realized volatility and seeks steadier participation versus SPY.

Universe: U.S. equity universe of active common stocks with daily adjusted OHLCV coverage.

Benchmark: SPY

Signal:
- Compute 63d realized volatility from daily adjusted returns.
- Compute 126d realized volatility from daily adjusted returns.
- Rank stocks by lower realized volatility, with lower risk receiving a higher defensive score.
- Optional beta filter if benchmark-relative returns are available.

Rebalance: monthly

Portfolio construction:
- Equal-weight the top defensive / lower-volatility basket.
- Use monthly rebalance dates.
- Keep missing beta or incomplete price history as Missing Evidence rather than substituting another signal.

Evidence requirements:
- Source material path and hash.
- U.S. stock universe and ticker list.
- SPY benchmark path.
- Realized-volatility feature definition.
- Monthly rebalance method.
- Output backtest artifact paths or DATA_MISSING.
- No ML summary unless a fitted model and out-of-sample artifact exist.
