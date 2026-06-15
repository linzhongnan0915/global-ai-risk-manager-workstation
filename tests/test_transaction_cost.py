from src.risk.transaction_cost import TransactionCostModel


def test_transaction_cost_5_bps_buy_and_sell():
    model = TransactionCostModel(buy_bps=5, sell_bps=5)

    assert model.cost_for_trade(1_000_000, "buy") == 500
    assert model.cost_for_trade(1_000_000, "sell") == 500
    assert model.round_trip_cost(1_000_000) == 1_000


def test_rebalance_cost_uses_buy_and_sell_side():
    model = TransactionCostModel(buy_bps=5, sell_bps=5)
    current = {"A": 0.6, "B": 0.4}
    target = {"A": 0.5, "B": 0.5}

    assert round(model.rebalance_cost(current, target, 1_000_000), 6) == 100
