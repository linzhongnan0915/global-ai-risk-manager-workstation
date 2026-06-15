"""Fetch yfinance fallback market data and build dashboard snapshot."""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.market.yfinance_client import refresh_yfinance_market_data


def main() -> None:
    snapshot = refresh_yfinance_market_data()
    print(f"Fetched yfinance market snapshot for {snapshot['as_of']} with {len(snapshot['markets'])} tickers")
    print("Wrote data/raw/yfinance_price_history.csv")
    print("Wrote data/processed/market_price_history.csv")
    print("Wrote output/market_snapshot.json")


if __name__ == "__main__":
    main()
