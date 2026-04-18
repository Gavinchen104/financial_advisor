from datetime import datetime, timedelta
from typing import Any

import yfinance as yf


def get_price_action(ticker: str, days: int = 7) -> dict[str, Any]:
    """Fetch recent price action for a ticker: change %, volume, high/low."""
    t = yf.Ticker(ticker)
    end = datetime.now()
    # Fetch extra days to account for weekends/holidays
    start = end - timedelta(days=days + 7)

    try:
        hist = t.history(start=start, end=end)
    except Exception as e:
        return {"error": str(e)}

    if hist.empty:
        return {"error": f"No price data found for {ticker}. It may be an invalid ticker."}

    hist = hist.tail(days)
    first_close = float(hist.iloc[0]["Close"])
    last_close = float(hist.iloc[-1]["Close"])
    pct_change = ((last_close - first_close) / first_close) * 100

    avg_vol = float(hist["Volume"].mean())
    last_vol = float(hist.iloc[-1]["Volume"])

    return {
        "ticker": ticker.upper(),
        "current_price": round(last_close, 2),
        "price_7d_ago": round(first_close, 2),
        "pct_change_7d": round(pct_change, 2),
        "week_high": round(float(hist["High"].max()), 2),
        "week_low": round(float(hist["Low"].min()), 2),
        "last_volume": int(last_vol),
        "avg_volume_7d": int(avg_vol),
        "volume_vs_avg": round(last_vol / avg_vol, 2) if avg_vol else None,
    }
