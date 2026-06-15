from src.portfolio.ledger import validate_weights


def test_portfolio_weights_sum_to_one():
    assert validate_weights({"A": 0.25, "B": 0.25, "C": 0.50})

