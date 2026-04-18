from datetime import datetime, timedelta
from typing import Any

import yfinance as yf


def get_price_action(ticker: str, days: int = 7) -> dict[str, Any]:
    """Fetch recent price action for a ticker: change %, volume, high/low."""
    t = yf.Ticker(ticker)
    end = datetime.now()
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


def get_earnings_data(ticker: str) -> dict[str, Any]:
    """Fetch earnings and key fundamental data for a ticker via yfinance."""
    t = yf.Ticker(ticker)

    try:
        info = t.info
    except Exception as e:
        return {"error": str(e)}

    result: dict[str, Any] = {
        "eps_trailing_12m": info.get("trailingEps"),
        "eps_forward": info.get("forwardEps"),
        "pe_ratio": info.get("trailingPE"),
        "revenue_growth_yoy": info.get("revenueGrowth"),
        "earnings_growth_yoy": info.get("earningsGrowth"),
        "profit_margin": info.get("profitMargins"),
        "next_earnings_date": None,
        "recent_quarterly_eps": [],
    }

    # Next earnings date
    try:
        ed = t.earnings_dates
        if ed is not None and not ed.empty:
            import pandas as pd
            future = ed[ed.index > pd.Timestamp.now(tz="UTC")]
            if not future.empty:
                result["next_earnings_date"] = str(future.index[-1].date())
    except Exception:
        pass

    # Last 4 quarters of EPS actuals vs estimates
    try:
        ed = t.earnings_dates
        if ed is not None and not ed.empty:
            past = ed[["EPS Estimate", "Reported EPS"]].dropna(how="all").head(4)
            result["recent_quarterly_eps"] = past.reset_index().rename(
                columns={"Earnings Date": "date", "EPS Estimate": "estimate", "Reported EPS": "actual"}
            ).to_dict("records")
    except Exception:
        pass

    return result
