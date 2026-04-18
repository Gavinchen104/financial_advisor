import yfinance as yf
from typing import Any


def get_recent_news(ticker: str, days: int = 7) -> list[dict[str, Any]]:
    """Fetch recent news headlines for a ticker via yfinance."""
    t = yf.Ticker(ticker)
    try:
        news = t.news
    except Exception as e:
        return [{"error": str(e)}]

    if not news:
        return []

    results = []
    for item in news[:10]:
        results.append({
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "source": item.get("publisher", ""),
            "published_at": item.get("providerPublishTime", ""),
        })
    return results
