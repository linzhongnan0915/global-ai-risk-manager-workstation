from src.news.live_news import build_live_news_snapshot, headlines_from_market_moves
from src.risk.recommendation_engine import build_recommendations


def test_headlines_from_market_moves_creates_news_items():
    snapshot = {
        "markets": [
            {"ticker": "SPY", "daily_return": -0.02, "bucket": "equity_beta", "risk_interpretation": "Equity selloff"},
            {"ticker": "BIL", "daily_return": 0.0001, "bucket": "cash", "risk_interpretation": "Stable"},
        ]
    }
    items = headlines_from_market_moves(snapshot, threshold=0.012)
    assert len(items) == 1
    assert items[0]["topic"] == "equity"
    assert items[0]["severity"] == "medium"


def test_build_recommendations_includes_factor_breach():
    recs = build_recommendations(
        market_summary=[],
        news_risk={"watch_level": "normal", "news_risk_score": 0},
        allocation_summary={"approval_required": False},
        factor_checks=[
            {
                "status": "breach",
                "metric": "equity_beta",
                "action": "Reduce equity beta exposure before approval.",
            }
        ],
        factor_exposure={"equity_beta": 0.42},
    )
    assert any(rec["category"] == "factor_risk" for rec in recs)
    assert any("equity_beta" in rec["action"].lower() or "equity beta" in rec["action"].lower() for rec in recs)


def test_build_live_news_snapshot_uses_market_moves_when_no_api(monkeypatch):
    monkeypatch.setattr("src.news.live_news.fetch_yfinance_news", lambda max_items=12: [])
    payload = build_live_news_snapshot(
        {
            "markets": [
                {"ticker": "TLT", "daily_return": -0.03, "bucket": "rates_duration", "risk_interpretation": "Duration pressure"},
            ]
        }
    )
    assert payload["items"]
    assert payload["items"][0]["source"] == "market_move_proxy"
