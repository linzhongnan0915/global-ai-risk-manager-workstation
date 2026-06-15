"""Portfolio construction rules for WorldQuant Alpha #2 research."""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_LONG_QUANTILE = 0.20
DEFAULT_SHORT_QUANTILE = 0.20


def signal_to_dollar_neutral_weights(
    signal: pd.DataFrame,
    *,
    long_quantile: float = DEFAULT_LONG_QUANTILE,
    short_quantile: float = DEFAULT_SHORT_QUANTILE,
) -> pd.DataFrame:
    """Convert Alpha #2 signal ranks into equal-weight long/short portfolio weights.

    Research rule
    -------------
    - Cross-sectionally rank securities by the Alpha #2 signal on each date.
    - Long the strongest signal group and short the weakest signal group.
    - Equal weight within each side.
    - Target gross exposure of 1.0 with net exposure near zero (+0.5 long, -0.5 short).

    Signal direction
    ----------------
    Alpha #2 is ``-correlation(...)``. Higher alpha means a more positive expected
    signal, so the long book takes the highest alpha names and the short book takes
    the lowest alpha names.
    """
    if not 0 < long_quantile < 1 or not 0 < short_quantile < 1:
        raise ValueError("long_quantile and short_quantile must be between 0 and 1")

    weights = pd.DataFrame(0.0, index=signal.index, columns=signal.columns)
    for date in signal.index:
        row = signal.loc[date].dropna()
        count = len(row)
        if count < 2:
            continue

        long_count = max(1, int(np.floor(count * long_quantile)))
        short_count = max(1, int(np.floor(count * short_quantile)))
        if long_count + short_count > count:
            short_count = max(1, count - long_count)

        ranked = row.sort_values(ascending=False)
        long_tickers = ranked.head(long_count).index
        short_tickers = ranked.tail(short_count).index

        long_weight = 0.5 / len(long_tickers)
        short_weight = -0.5 / len(short_tickers)
        weights.loc[date, long_tickers] = long_weight
        weights.loc[date, short_tickers] = short_weight

    return weights
