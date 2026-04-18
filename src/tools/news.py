import concurrent.futures
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yfinance as yf
from bs4 import BeautifulSoup

_FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

_CACHE_PATH = Path(__file__).parent.parent / "knowledge_graph" / "data" / "news_cache.json"
_CACHE_MAX_AGE_HOURS = 24


def _read_cache(ticker: str) -> list[dict[str, Any]] | None:
    """Return cached news for ticker if cache is fresh (<24h old), else None."""
    if not _CACHE_PATH.exists():
        return None
    try:
        with open(_CACHE_PATH) as f:
            cache = json.load(f)
        generated_at = datetime.fromisoformat(cache["generated_at"])
        age_hours = (datetime.now(timezone.utc) - generated_at).total_seconds() / 3600
        if age_hours > _CACHE_MAX_AGE_HOURS:
            return None
        return cache.get("tickers", {}).get(ticker)
    except Exception:
        return None


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
    """Fetch recent news for a ticker. fetch_content=True also pulls article body text.

    If the daily news cache has a fresh entry for this ticker, use it.
    Otherwise fall back to a live yfinance fetch.
    """
    ticker = ticker.upper()
    cached = _read_cache(ticker)
    if cached is not None:
        return cached

    t = yf.Ticker(ticker)
    try:
        news = t.news
    except Exception as e:
        return [{"error": str(e)}]

    if not news:
        return []

    items = []
    for item in news[:10]:
        url = item.get("link", "")
        # Skip S3 / CDN / non-public URLs that users can't open
        if not url or "s3.amazonaws.com" in url or "s3-" in url or not url.startswith("http"):
            continue
        items.append({
            "title": item.get("title", ""),
            "url": url,
            "source": item.get("publisher", ""),
            "published_at": item.get("providerPublishTime", ""),
            "content": "",
        })
        if len(items) == 5:
            break

    if fetch_content:
        urls = [item["url"] for item in items[:3]]
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(_fetch_article_text, urls))
        for i, text in enumerate(results):
            items[i]["content"] = text

    return items
