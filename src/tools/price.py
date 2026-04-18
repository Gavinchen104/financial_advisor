import json
from datetime import datetime, timedelta
from typing import Any

import yfinance as yf

_SECTOR_ETF_MAP = {
    "Technology": "XLK",
    "Healthcare": "XLV",
    "Financial Services": "XLF",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Industrials": "XLI",
    "Energy": "XLE",
    "Basic Materials": "XLB",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
    "Utilities": "XLU",
}


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

    try:
        ed = t.earnings_dates
        if ed is not None and not ed.empty:
            import pandas as pd
            future = ed[ed.index > pd.Timestamp.now(tz="UTC")]
            if not future.empty:
                result["next_earnings_date"] = str(future.index[-1].date())
    except Exception:
        pass

    try:
        ed = t.earnings_dates
        if ed is not None and not ed.empty:
            past = ed[["EPS Estimate", "Reported EPS"]].dropna(how="all").head(4)
            records = json.loads(past.reset_index().to_json(orient="records", date_format="iso"))
            # Enrich each quarter with explicit beat/miss context
            for r in records:
                est = r.get("EPS Estimate")
                act = r.get("Reported EPS")
                if est is not None and act is not None:
                    try:
                        surprise_pct = ((float(act) - float(est)) / abs(float(est))) * 100
                        r["surprise_pct"] = round(surprise_pct, 1)
                        r["result"] = "beat" if surprise_pct > 0 else "missed"
                    except (TypeError, ZeroDivisionError):
                        pass
            result["recent_quarterly_eps"] = records
    except Exception:
        pass

    return result


def get_market_context(ticker: str, days: int = 7) -> dict[str, Any]:
    """Fetch S&P 500 (SPY) and sector ETF performance for relative comparison."""
    t = yf.Ticker(ticker)
    end = datetime.now()
    start = end - timedelta(days=days + 7)

    result: dict[str, Any] = {
        "spy_pct_change": None,
        "sector": None,
        "sector_etf": None,
        "sector_etf_pct_change": None,
    }

    try:
        info = t.info
        sector = info.get("sector")
        result["sector"] = sector
        result["sector_etf"] = _SECTOR_ETF_MAP.get(sector) if sector else None
    except Exception:
        pass

    try:
        hist = yf.Ticker("SPY").history(start=start, end=end).tail(days)
        if not hist.empty:
            result["spy_pct_change"] = round(
                ((float(hist.iloc[-1]["Close"]) - float(hist.iloc[0]["Close"])) / float(hist.iloc[0]["Close"])) * 100, 2
            )
    except Exception:
        pass

    if result["sector_etf"]:
        try:
            hist = yf.Ticker(result["sector_etf"]).history(start=start, end=end).tail(days)
            if not hist.empty:
                result["sector_etf_pct_change"] = round(
                    ((float(hist.iloc[-1]["Close"]) - float(hist.iloc[0]["Close"])) / float(hist.iloc[0]["Close"])) * 100, 2
                )
        except Exception:
            pass

    return result


def get_analyst_data(ticker: str) -> dict[str, Any]:
    """Fetch analyst price targets, recent upgrades/downgrades, and recommendation trends."""
    t = yf.Ticker(ticker)
    result: dict[str, Any] = {
        "price_target_mean": None,
        "price_target_high": None,
        "price_target_low": None,
        "price_target_current": None,
        "recent_upgrades_downgrades": [],
        "recommendation_summary": [],
    }

    try:
        targets = t.analyst_price_targets
        if targets:
            result["price_target_mean"] = targets.get("mean")
            result["price_target_high"] = targets.get("high")
            result["price_target_low"] = targets.get("low")
            result["price_target_current"] = targets.get("current")
    except Exception:
        pass

    try:
        ud = t.upgrades_downgrades
        if ud is not None and not ud.empty:
            recent = ud.head(5).reset_index()
            result["recent_upgrades_downgrades"] = json.loads(
                recent.to_json(orient="records", date_format="iso")
            )
    except Exception:
        pass

    try:
        rec = t.recommendations_summary
        if rec is not None and not rec.empty:
            result["recommendation_summary"] = json.loads(
                rec.head(3).to_json(orient="records", date_format="iso")
            )
    except Exception:
        pass

    return result


def get_insider_transactions(ticker: str) -> dict[str, Any]:
    """Fetch recent insider buy/sell transactions and ownership percentages."""
    t = yf.Ticker(ticker)
    result: dict[str, Any] = {
        "insider_ownership_pct": None,
        "institutional_ownership_pct": None,
        "recent_transactions": [],
    }

    try:
        info = t.info
        result["insider_ownership_pct"] = info.get("heldPercentInsiders")
        result["institutional_ownership_pct"] = info.get("heldPercentInstitutions")
    except Exception:
        pass

    try:
        txns = t.insider_transactions
        if txns is not None and not txns.empty:
            recent = txns.head(5).reset_index()
            result["recent_transactions"] = json.loads(
                recent.to_json(orient="records", date_format="iso")
            )
    except Exception:
        pass

    return result
