"""Risk metrics for a ticker: beta vs SPY, realized volatility, max drawdown, Sharpe.

All computed from 1-year daily returns via yfinance. Returns None for any metric
that can't be computed (insufficient history, zero variance, etc.) rather than raising.
"""

import logging
from typing import Any

import numpy as np
import yfinance as yf

logging.getLogger("yfinance").setLevel(logging.CRITICAL)

_TRADING_DAYS = 252
_RISK_FREE_RATE = 0.045  # 1y T-bill proxy; update if rate regime changes materially


def _label_volatility(vol_annualized_pct: float | None) -> str | None:
    """Plain-English bucket for first-year investors."""
    if vol_annualized_pct is None:
        return None
    if vol_annualized_pct < 20:
        return "low"
    if vol_annualized_pct < 35:
        return "moderate"
    if vol_annualized_pct < 55:
        return "high"
    return "very high"


def get_risk_metrics(ticker: str) -> dict[str, Any]:
    """Fetch 1y daily returns and compute risk metrics. Fetches SPY alongside for beta."""
    result: dict[str, Any] = {
        "beta_1y": None,
        "volatility_30d_annualized_pct": None,
        "volatility_label": None,
        "max_drawdown_1y_pct": None,
        "sharpe_1y": None,
        "trading_days_used": None,
        "source_url": f"https://finance.yahoo.com/quote/{ticker}/history",
    }

    try:
        hist = yf.Ticker(ticker).history(period="1y", auto_adjust=True)
    except Exception as e:
        result["error"] = str(e)
        return result

    if hist.empty or len(hist) < 60:
        result["error"] = "insufficient price history (need at least 60 trading days)"
        return result

    returns = hist["Close"].pct_change().dropna()
    result["trading_days_used"] = int(len(returns))

    # 30d realized volatility, annualized
    if len(returns) >= 30:
        vol_30d = float(returns.tail(30).std() * np.sqrt(_TRADING_DAYS))
        vol_pct = round(vol_30d * 100, 1)
        result["volatility_30d_annualized_pct"] = vol_pct
        result["volatility_label"] = _label_volatility(vol_pct)

    # 1y max drawdown (peak-to-trough)
    cum = (1 + returns).cumprod()
    running_max = cum.cummax()
    drawdown = (cum / running_max) - 1
    result["max_drawdown_1y_pct"] = round(float(drawdown.min()) * 100, 1)

    # Annualized Sharpe over 1y
    mean_daily = float(returns.mean())
    std_daily = float(returns.std())
    if std_daily > 0:
        annualized_return = (1 + mean_daily) ** _TRADING_DAYS - 1
        annualized_vol = std_daily * np.sqrt(_TRADING_DAYS)
        result["sharpe_1y"] = round((annualized_return - _RISK_FREE_RATE) / annualized_vol, 2)

    # Beta vs SPY — needs SPY history aligned to the same dates
    try:
        spy_hist = yf.Ticker("SPY").history(period="1y", auto_adjust=True)
        if not spy_hist.empty:
            spy_returns = spy_hist["Close"].pct_change().dropna()
            common = returns.index.intersection(spy_returns.index)
            if len(common) >= 60:
                r = returns.loc[common].values
                m = spy_returns.loc[common].values
                var_m = float(np.var(m))
                if var_m > 0:
                    cov = float(np.cov(r, m)[0, 1])
                    result["beta_1y"] = round(cov / var_m, 2)
    except Exception:
        pass

    return result
