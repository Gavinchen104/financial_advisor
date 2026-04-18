"""Watchlist + holdings endpoints. Requires authenticated user.

Live prices are fetched via yfinance and merged into responses so the frontend
can render P&L and 7-day changes without a second round-trip.
"""

import concurrent.futures
from datetime import datetime, timedelta
from typing import Annotated

import yfinance as yf
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .models import Holding, User, WatchlistItem
from .tools.risk import get_risk_metrics

router = APIRouter(tags=["portfolio"])


# ---------- schemas ----------
class WatchlistAdd(BaseModel):
    ticker: str = Field(min_length=1, max_length=10)


class WatchlistItemOut(BaseModel):
    ticker: str
    current_price: float | None
    pct_change_7d: float | None


class HoldingAdd(BaseModel):
    ticker: str = Field(min_length=1, max_length=10)
    shares: float = Field(gt=0)
    cost_basis: float = Field(gt=0)  # per-share avg cost in USD


class HoldingUpdate(BaseModel):
    shares: float | None = Field(default=None, gt=0)
    cost_basis: float | None = Field(default=None, gt=0)


class HoldingOut(BaseModel):
    id: int
    ticker: str
    shares: float
    cost_basis: float
    current_price: float | None
    market_value: float | None
    total_cost: float
    unrealized_pnl: float | None
    unrealized_pnl_pct: float | None


class SectorExposure(BaseModel):
    sector: str
    weight_pct: float
    market_value: float


class ConcentrationLabel(BaseModel):
    level: str  # "diversified" | "moderate" | "concentrated"
    message: str


class PortfolioRisk(BaseModel):
    portfolio_beta: float | None
    concentration_hhi: float
    concentration: ConcentrationLabel
    top_position: dict | None  # {"ticker": str, "weight_pct": float}
    sector_exposure: list[SectorExposure]
    coverage_pct: float  # % of portfolio value where beta/sector were resolvable


class PortfolioSummary(BaseModel):
    total_cost: float
    total_value: float | None
    total_pnl: float | None
    total_pnl_pct: float | None
    position_count: int
    holdings: list[HoldingOut]
    risk_profile: PortfolioRisk | None = None


# ---------- price helpers ----------
def _fetch_one(ticker: str) -> dict:
    """Best-effort current price + 7d change. Returns {} on failure."""
    try:
        t = yf.Ticker(ticker)
        end = datetime.now()
        start = end - timedelta(days=14)
        hist = t.history(start=start, end=end)
        if hist.empty:
            return {}
        tail = hist.tail(7)
        last = float(tail.iloc[-1]["Close"])
        first = float(tail.iloc[0]["Close"])
        pct = round(((last - first) / first) * 100, 2) if first else None
        return {"current_price": round(last, 4), "pct_change_7d": pct}
    except Exception:
        return {}


def _fetch_many(tickers: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not tickers:
        return out
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(tickers), 8)) as ex:
        futures = {ex.submit(_fetch_one, t): t for t in tickers}
        for fut in concurrent.futures.as_completed(futures):
            out[futures[fut]] = fut.result()
    return out


def _norm(ticker: str) -> str:
    return ticker.strip().upper()


# ---------- analytics caches (process-lifetime, keyed by ticker) ----------
# Sectors change almost never, so we cache them for the life of the process.
# Betas drift slowly; cache for 1h so /portfolio stays responsive without
# re-running a 1-year daily fetch on every page load.
_SECTOR_CACHE: dict[str, str | None] = {}
_BETA_CACHE: dict[str, tuple[float | None, datetime]] = {}
_BETA_TTL = timedelta(hours=1)


def _get_sector(ticker: str) -> str | None:
    if ticker in _SECTOR_CACHE:
        return _SECTOR_CACHE[ticker]
    sector: str | None = None
    try:
        sector = yf.Ticker(ticker).info.get("sector") or None
    except Exception:
        sector = None
    _SECTOR_CACHE[ticker] = sector
    return sector


def _get_beta(ticker: str) -> float | None:
    cached = _BETA_CACHE.get(ticker)
    if cached and (datetime.now() - cached[1]) < _BETA_TTL:
        return cached[0]
    beta = get_risk_metrics(ticker).get("beta_1y")
    _BETA_CACHE[ticker] = (beta, datetime.now())
    return beta


def _fetch_sectors_and_betas(tickers: list[str]) -> tuple[dict[str, str | None], dict[str, float | None]]:
    """Parallel resolve sector + beta for a batch of tickers."""
    sectors: dict[str, str | None] = {}
    betas: dict[str, float | None] = {}
    if not tickers:
        return sectors, betas
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(tickers) * 2, 12)) as ex:
        sec_futs = {ex.submit(_get_sector, t): t for t in tickers}
        beta_futs = {ex.submit(_get_beta, t): t for t in tickers}
        for fut in concurrent.futures.as_completed(sec_futs):
            sectors[sec_futs[fut]] = fut.result()
        for fut in concurrent.futures.as_completed(beta_futs):
            betas[beta_futs[fut]] = fut.result()
    return sectors, betas


def _label_concentration(hhi: float, n: int) -> ConcentrationLabel:
    """HHI on position weights. For n holdings, min HHI = 1/n (evenly weighted)."""
    if n <= 1:
        return ConcentrationLabel(level="concentrated", message="Single-position portfolio.")
    if hhi < 0.15:
        return ConcentrationLabel(level="diversified", message="Well-diversified across positions.")
    if hhi < 0.30:
        return ConcentrationLabel(level="moderate", message="Moderately concentrated in top positions.")
    return ConcentrationLabel(level="concentrated", message="Heavily concentrated — one or two positions dominate.")


def _compute_risk_profile(holdings_out: list[HoldingOut]) -> PortfolioRisk | None:
    """Given priced holdings, compute beta, HHI, concentration, sector exposure."""
    priced = [h for h in holdings_out if h.market_value is not None and h.market_value > 0]
    if not priced:
        return None
    total_value = sum(h.market_value for h in priced)
    if total_value <= 0:
        return None

    tickers = sorted({h.ticker for h in priced})
    sectors_map, betas_map = _fetch_sectors_and_betas(tickers)

    # Weights
    weights = [(h, h.market_value / total_value) for h in priced]

    # HHI on position weights
    hhi = sum(w ** 2 for _, w in weights)

    # Top position
    top_h, top_w = max(weights, key=lambda x: x[1])
    top_position = {"ticker": top_h.ticker, "weight_pct": round(top_w * 100, 1)}

    # Portfolio beta — weighted, coverage-adjusted so one missing beta doesn't silently skew it
    beta_num = 0.0
    beta_cov_value = 0.0
    for h, _ in weights:
        b = betas_map.get(h.ticker)
        if b is not None:
            beta_num += b * h.market_value
            beta_cov_value += h.market_value
    portfolio_beta = round(beta_num / beta_cov_value, 2) if beta_cov_value > 0 else None
    coverage_pct = round((beta_cov_value / total_value) * 100, 1)

    # Sector exposure — group by sector, sum weights
    sector_values: dict[str, float] = {}
    for h, _ in weights:
        sec = sectors_map.get(h.ticker) or "Unknown"
        sector_values[sec] = sector_values.get(sec, 0.0) + h.market_value
    sector_exposure = [
        SectorExposure(
            sector=sec,
            weight_pct=round((val / total_value) * 100, 1),
            market_value=round(val, 2),
        )
        for sec, val in sorted(sector_values.items(), key=lambda x: x[1], reverse=True)
    ]

    return PortfolioRisk(
        portfolio_beta=portfolio_beta,
        concentration_hhi=round(hhi, 3),
        concentration=_label_concentration(hhi, len(priced)),
        top_position=top_position,
        sector_exposure=sector_exposure,
        coverage_pct=coverage_pct,
    )


# ---------- watchlist ----------
@router.get("/watchlist", response_model=list[WatchlistItemOut])
def list_watchlist(user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]):
    items = db.query(WatchlistItem).filter(WatchlistItem.user_id == user.id).order_by(WatchlistItem.added_at.desc()).all()
    tickers = [i.ticker for i in items]
    prices = _fetch_many(tickers)
    return [
        WatchlistItemOut(
            ticker=i.ticker,
            current_price=prices.get(i.ticker, {}).get("current_price"),
            pct_change_7d=prices.get(i.ticker, {}).get("pct_change_7d"),
        )
        for i in items
    ]


@router.post("/watchlist", status_code=201)
def add_watchlist(body: WatchlistAdd, user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]):
    ticker = _norm(body.ticker)
    existing = db.query(WatchlistItem).filter_by(user_id=user.id, ticker=ticker).first()
    if existing:
        return {"ok": True, "already_present": True}
    db.add(WatchlistItem(user_id=user.id, ticker=ticker))
    db.commit()
    return {"ok": True, "already_present": False}


@router.delete("/watchlist/{ticker}", status_code=204)
def remove_watchlist(ticker: str, user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]):
    item = db.query(WatchlistItem).filter_by(user_id=user.id, ticker=_norm(ticker)).first()
    if item:
        db.delete(item)
        db.commit()


# ---------- holdings / portfolio ----------
@router.get("/portfolio", response_model=PortfolioSummary)
def get_portfolio(user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]):
    rows = db.query(Holding).filter(Holding.user_id == user.id).order_by(Holding.added_at.desc()).all()
    prices = _fetch_many([r.ticker for r in rows])

    out: list[HoldingOut] = []
    total_cost = 0.0
    total_value: float | None = 0.0

    for r in rows:
        price = prices.get(r.ticker, {}).get("current_price")
        cost = r.shares * r.cost_basis
        total_cost += cost
        mv = (r.shares * price) if price is not None else None
        if mv is not None and total_value is not None:
            total_value += mv
        else:
            total_value = None  # any missing price invalidates the total
        pnl = (mv - cost) if mv is not None else None
        pnl_pct = (pnl / cost * 100) if (pnl is not None and cost > 0) else None
        out.append(HoldingOut(
            id=r.id, ticker=r.ticker, shares=r.shares, cost_basis=r.cost_basis,
            current_price=price, market_value=mv, total_cost=cost,
            unrealized_pnl=pnl, unrealized_pnl_pct=pnl_pct,
        ))

    total_pnl = (total_value - total_cost) if total_value is not None else None
    total_pnl_pct = (total_pnl / total_cost * 100) if (total_pnl is not None and total_cost > 0) else None

    risk_profile = _compute_risk_profile(out) if out else None

    return PortfolioSummary(
        total_cost=total_cost,
        total_value=total_value,
        total_pnl=total_pnl,
        total_pnl_pct=total_pnl_pct,
        position_count=len(out),
        holdings=out,
        risk_profile=risk_profile,
    )


@router.post("/holdings", status_code=201, response_model=HoldingOut)
def add_holding(body: HoldingAdd, user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]):
    ticker = _norm(body.ticker)
    existing = db.query(Holding).filter_by(user_id=user.id, ticker=ticker).first()
    if existing:
        # Re-adding same ticker → update (avg cost + add shares)
        new_shares = existing.shares + body.shares
        new_cost = ((existing.shares * existing.cost_basis) + (body.shares * body.cost_basis)) / new_shares
        existing.shares = new_shares
        existing.cost_basis = round(new_cost, 4)
        db.commit()
        db.refresh(existing)
        h = existing
    else:
        h = Holding(user_id=user.id, ticker=ticker, shares=body.shares, cost_basis=body.cost_basis)
        db.add(h)
        db.commit()
        db.refresh(h)
    price = _fetch_one(ticker).get("current_price")
    cost = h.shares * h.cost_basis
    mv = (h.shares * price) if price is not None else None
    pnl = (mv - cost) if mv is not None else None
    return HoldingOut(
        id=h.id, ticker=h.ticker, shares=h.shares, cost_basis=h.cost_basis,
        current_price=price, market_value=mv, total_cost=cost,
        unrealized_pnl=pnl,
        unrealized_pnl_pct=(pnl / cost * 100) if (pnl is not None and cost > 0) else None,
    )


@router.patch("/holdings/{holding_id}", response_model=HoldingOut)
def update_holding(holding_id: int, body: HoldingUpdate, user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]):
    h = db.get(Holding, holding_id)
    if h is None or h.user_id != user.id:
        raise HTTPException(404, "Holding not found.")
    if body.shares is not None:
        h.shares = body.shares
    if body.cost_basis is not None:
        h.cost_basis = body.cost_basis
    db.commit()
    db.refresh(h)
    price = _fetch_one(h.ticker).get("current_price")
    cost = h.shares * h.cost_basis
    mv = (h.shares * price) if price is not None else None
    pnl = (mv - cost) if mv is not None else None
    return HoldingOut(
        id=h.id, ticker=h.ticker, shares=h.shares, cost_basis=h.cost_basis,
        current_price=price, market_value=mv, total_cost=cost,
        unrealized_pnl=pnl,
        unrealized_pnl_pct=(pnl / cost * 100) if (pnl is not None and cost > 0) else None,
    )


@router.delete("/holdings/{holding_id}", status_code=204)
def delete_holding(holding_id: int, user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]):
    h = db.get(Holding, holding_id)
    if h is None or h.user_id != user.id:
        raise HTTPException(404, "Holding not found.")
    db.delete(h)
    db.commit()
