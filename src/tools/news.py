import concurrent.futures
from typing import Any

import httpx
import yfinance as yf
from bs4 import BeautifulSoup

_FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}


def _fetch_article_text(url: str, max_chars: int = 2000) -> str:
    """Fetch and extract readable text from an article URL."""
    try:
        resp = httpx.get(url, headers=_FETCH_HEADERS, timeout=6, follow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "iframe"]):
            tag.decompose()
        text = " ".join(soup.get_text(separator=" ").split())
        return text[:max_chars]
    except Exception:
        return ""


def get_recent_news(ticker: str, days: int = 7, fetch_content: bool = True) -> list[dict[str, Any]]:
    """Fetch recent news for a ticker. fetch_content=True also pulls article body text."""
    t = yf.Ticker(ticker)
    try:
        news = t.news
    except Exception as e:
        return [{"error": str(e)}]

    if not news:
        return []

    items = []
    for item in news[:5]:
        items.append({
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "source": item.get("publisher", ""),
            "published_at": item.get("providerPublishTime", ""),
            "content": "",
        })

    if fetch_content:
        urls = [item["url"] for item in items[:3]]
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(_fetch_article_text, urls))
        for i, text in enumerate(results):
            items[i]["content"] = text

    return items
