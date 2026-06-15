"""WorldQuant-style formulaic alpha operators (research module)."""

from src.strategies.worldquant.alpha2 import (
    compute_alpha2,
    compute_alpha2_components,
    compute_intraday_return,
)
from src.strategies.worldquant.operators import (
    correlation_ts,
    delta_ts,
    log_safe,
    rank_cs,
)

__all__ = [
    "compute_alpha2",
    "compute_alpha2_components",
    "compute_intraday_return",
    "correlation_ts",
    "delta_ts",
    "log_safe",
    "rank_cs",
]
