"""
Daily news cache pre-warmer.

Fetches recent news for a hot-list of popular tickers and stores it in a JSON
cache at src/knowledge_graph/data/news_cache.json. Briefs for these tickers
will read the cache when it is fresh (<24h old) and fall back to live fetch
otherwise.

Run: uv run python scripts/refresh_news_cache.py
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.tools.news import get_recent_news

OUT_PATH = ROOT / "src" / "knowledge_graph" / "data" / "news_cache.json"

# Hot-list: tickers most likely to be requested. Keep small — each entry costs
# ~3 article-text fetches. This is a pre-warm, not a full index.
HOT_TICKERS = [
    "NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "AMD",
    "AVGO", "NFLX", "JPM", "V", "MA", "XOM", "WMT", "KO", "DIS",
    "BA", "LMT", "SPY",
]


def refresh() -> dict:
    print(f"Pre-warming news cache for {len(HOT_TICKERS)} tickers...")
    cache = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tickers": {},
    }
    for ticker in HOT_TICKERS:
        try:
            items = get_recent_news(ticker, days=7, fetch_content=True)
            cache["tickers"][ticker] = items
            print(f"  {ticker}: {len(items)} items")
        except Exception as e:
            print(f"  {ticker}: failed — {e}")
            cache["tickers"][ticker] = []
    return cache


def main():
    cache = refresh()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(cache, f, indent=2)
    print(f"\nCache saved to {OUT_PATH}")
    print(f"  Generated at: {cache['generated_at']}")
    print(f"  Tickers: {len(cache['tickers'])}")


if __name__ == "__main__":
    main()
