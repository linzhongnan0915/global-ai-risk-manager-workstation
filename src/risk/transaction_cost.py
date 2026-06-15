"""Transaction cost assumptions used by backtests and rebalances."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


BPS_DIVISOR = 10_000


@dataclass(frozen=True)
class TransactionCostModel:
    """Simple notional-based transaction cost model.

    Default policy: 5 bps on buys and 5 bps on sells, equal to 10 bps for a
    complete buy/sell round trip.
    """

    buy_bps: float = 5.0
    sell_bps: float = 5.0

    def cost_for_trade(self, notional: float, side: str) -> float:
        if notional < 0:
            raise ValueError("notional must be non-negative")
        normalized_side = side.lower()
        if normalized_side not in {"buy", "sell"}:
            raise ValueError("side must be 'buy' or 'sell'")
        bps = self.buy_bps if normalized_side == "buy" else self.sell_bps
        return notional * bps / BPS_DIVISOR

    def round_trip_cost(self, notional: float) -> float:
        return self.cost_for_trade(notional, "buy") + self.cost_for_trade(notional, "sell")

    def rebalance_cost(
        self,
        current_weights: Mapping[str, float],
        target_weights: Mapping[str, float],
        capital: float,
    ) -> float:
        if capital < 0:
            raise ValueError("capital must be non-negative")
        strategy_ids = set(current_weights) | set(target_weights)
        total = 0.0
        for strategy_id in strategy_ids:
            delta = target_weights.get(strategy_id, 0.0) - current_weights.get(strategy_id, 0.0)
            if delta > 0:
                total += self.cost_for_trade(delta * capital, "buy")
            elif delta < 0:
                total += self.cost_for_trade(abs(delta) * capital, "sell")
        return total


DEFAULT_TRANSACTION_COST_MODEL = TransactionCostModel()

