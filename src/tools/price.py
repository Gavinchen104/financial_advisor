import json
import logging
from datetime import datetime, timedelta
from typing import Any

import yfinance as yf

logging.getLogger("yfinance").setLevel(logging.CRITICAL)

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


def _yf_url(ticker: str, tab: str = "") -> str:
    base = f"https://finance.yahoo.com/quote/{ticker}"
    return f"{base}/{tab}" if tab else base


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
        "source_url": _yf_url(ticker),
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
        "source_url": _yf_url(ticker, "financials"),
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
        "source_url": _yf_url("SPY"),
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
        "source_url": _yf_url(ticker, "analysis"),
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


_SECTOR_PE_REFERENCE = {
    "Technology": 35,
    "Healthcare": 25,
    "Financial Services": 15,
    "Consumer Cyclical": 22,
    "Consumer Defensive": 22,
    "Industrials": 25,
    "Energy": 12,
    "Basic Materials": 15,
    "Real Estate": 40,
    "Communication Services": 20,
    "Utilities": 18,
}


def get_balance_sheet(ticker: str) -> dict[str, Any]:
    """Fetch balance sheet health: cash, debt, FCF, and key liquidity ratios."""
    t = yf.Ticker(ticker)
    result: dict[str, Any] = {
        "market_cap": None,
        "total_cash": None,
        "total_debt": None,
        "debt_to_equity": None,
        "current_ratio": None,
        "quick_ratio": None,
        "free_cash_flow": None,
        "operating_cash_flow": None,
        "fcf_yield_pct": None,
        "source_url": _yf_url(ticker, "balance-sheet"),
    }

    try:
        info = t.info
        result["market_cap"] = info.get("marketCap")
        result["total_cash"] = info.get("totalCash")
        result["total_debt"] = info.get("totalDebt")
        result["debt_to_equity"] = info.get("debtToEquity")
        result["current_ratio"] = info.get("currentRatio")
        result["quick_ratio"] = info.get("quickRatio")
        result["free_cash_flow"] = info.get("freeCashflow")
        result["operating_cash_flow"] = info.get("operatingCashflow")

        fcf = result["free_cash_flow"]
        mc = result["market_cap"]
        if fcf and mc and mc > 0:
            result["fcf_yield_pct"] = round((fcf / mc) * 100, 2)
    except Exception as e:
        result["error"] = str(e)

    return result


def get_valuation_context(ticker: str) -> dict[str, Any]:
    """Fetch valuation multiples with sector average comparison."""
    t = yf.Ticker(ticker)
    result: dict[str, Any] = {
        "trailing_pe": None,
        "forward_pe": None,
        "peg_ratio": None,
        "price_to_sales": None,
        "price_to_book": None,
        "ev_to_ebitda": None,
        "sector": None,
        "sector_avg_pe_reference": None,
        "pe_vs_sector_pct": None,
        "source_url": _yf_url(ticker, "financials"),
    }

    try:
        info = t.info
        result["trailing_pe"] = info.get("trailingPE")
        result["forward_pe"] = info.get("forwardPE")
        result["peg_ratio"] = info.get("pegRatio")
        result["price_to_sales"] = info.get("priceToSalesTrailing12Months")
        result["price_to_book"] = info.get("priceToBook")
        result["ev_to_ebitda"] = info.get("enterpriseToEbitda")

        sector = info.get("sector")
        result["sector"] = sector
        ref_pe = _SECTOR_PE_REFERENCE.get(sector) if sector else None
        result["sector_avg_pe_reference"] = ref_pe

        trailing_pe = result["trailing_pe"]
        if trailing_pe and ref_pe:
            result["pe_vs_sector_pct"] = round(((trailing_pe - ref_pe) / ref_pe) * 100, 1)
    except Exception as e:
        result["error"] = str(e)

    return result


def get_technical_levels(ticker: str) -> dict[str, Any]:
    """Fetch 50/200-day moving averages, 52-week range position, and short interest."""
    t = yf.Ticker(ticker)
    result: dict[str, Any] = {
        "ma_50": None,
        "ma_200": None,
        "price_vs_ma50_pct": None,
        "price_vs_ma200_pct": None,
        "fifty_two_week_high": None,
        "fifty_two_week_low": None,
        "pct_from_52w_high": None,
        "pct_from_52w_low": None,
        "short_percent_of_float": None,
        "short_ratio_days_to_cover": None,
        "source_url": _yf_url(ticker, "history"),
    }

    try:
        info = t.info
        current_price = info.get("currentPrice") or info.get("regularMarketPrice")
        result["fifty_two_week_high"] = info.get("fiftyTwoWeekHigh")
        result["fifty_two_week_low"] = info.get("fiftyTwoWeekLow")
        result["short_percent_of_float"] = info.get("shortPercentOfFloat")
        result["short_ratio_days_to_cover"] = info.get("shortRatio")

        if current_price and result["fifty_two_week_high"]:
            result["pct_from_52w_high"] = round(
                ((current_price - result["fifty_two_week_high"]) / result["fifty_two_week_high"]) * 100, 1
            )
        if current_price and result["fifty_two_week_low"]:
            result["pct_from_52w_low"] = round(
                ((current_price - result["fifty_two_week_low"]) / result["fifty_two_week_low"]) * 100, 1
            )

        hist = t.history(period="1y")
        if not hist.empty and current_price:
            closes = hist["Close"]
            if len(closes) >= 50:
                ma50 = float(closes.rolling(50).mean().iloc[-1])
                result["ma_50"] = round(ma50, 2)
                result["price_vs_ma50_pct"] = round(((current_price - ma50) / ma50) * 100, 1)
            if len(closes) >= 200:
                ma200 = float(closes.rolling(200).mean().iloc[-1])
                result["ma_200"] = round(ma200, 2)
                result["price_vs_ma200_pct"] = round(((current_price - ma200) / ma200) * 100, 1)
    except Exception as e:
        result["error"] = str(e)

    return result


def get_insider_transactions(ticker: str) -> dict[str, Any]:
    """Fetch recent insider buy/sell transactions and ownership percentages."""
    t = yf.Ticker(ticker)
    result: dict[str, Any] = {
        "insider_ownership_pct": None,
        "institutional_ownership_pct": None,
        "recent_transactions": [],
        "source_url": _yf_url(ticker, "insider-transactions"),
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
