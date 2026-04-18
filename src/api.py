"""FastAPI application.

Mounts: static frontend, auth router, portfolio router, brief + context endpoints,
health check. Adds rate limiting (slowapi) and structured logging (loguru).
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

load_dotenv()

from .auth import current_user, optional_user, router as auth_router
from .db import get_db, init_db
from .logging_config import configure_logging
from .models import BriefCache, User, WatchlistItem
from .portfolio import router as portfolio_router

configure_logging()
init_db()

LOGS_DIR = Path(__file__).parent.parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)
LOG_FILE = LOGS_DIR / "briefs.jsonl"

WEB_DIR = Path(__file__).parent / "web"

BRIEF_CACHE_TTL_HOURS = 4

limiter = Limiter(key_func=get_remote_address, default_limits=["200/hour"])

app = FastAPI(title="Stockify", version="0.2.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.include_router(auth_router)
app.include_router(portfolio_router)

# Static assets served under /static
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")


# ---------- schemas ----------
class BriefRequest(BaseModel):
    ticker: str
    experience_level: str = "first_year"


class RiskMetrics(BaseModel):
    beta_1y: float | None = None
    volatility_30d_annualized_pct: float | None = None
    volatility_label: str | None = None
    max_drawdown_1y_pct: float | None = None
    sharpe_1y: float | None = None


class BriefResponse(BaseModel):
    ticker: str
    what_happened: str
    why_moved: str
    what_it_means: str
    sources_text: str
    full_brief: str
    disclaimer: str
    cached: bool = False
    earnings_window: str = "quiet"
    days_until_earnings: int | None = None
    days_since_last_earnings: int | None = None
    next_earnings_date: str | None = None
    last_earnings_date: str | None = None
    risk_metrics: RiskMetrics = RiskMetrics()


# ---------- helpers ----------
def _validate_ticker(ticker: str) -> str:
    ticker = ticker.strip().upper()
    if not ticker or not ticker.replace(".", "").replace("-", "").isalpha() or len(ticker) > 5:
        raise HTTPException(status_code=400, detail="Invalid ticker symbol. Use 1–5 letters (e.g. NVDA).")
    return ticker


def _log_request(ticker: str, user_id: int | None, experience_level: str, cached: bool) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "ticker": ticker,
        "user_id": user_id,
        "experience_level": experience_level,
        "cached": cached,
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _read_cached_brief(db: Session, ticker: str) -> dict | None:
    row = db.query(BriefCache).filter(BriefCache.ticker == ticker).first()
    if row is None:
        return None
    age = datetime.now(timezone.utc) - row.generated_at.replace(tzinfo=timezone.utc)
    if age > timedelta(hours=BRIEF_CACHE_TTL_HOURS):
        return None
    try:
        return json.loads(row.payload)
    except Exception:
        return None


def _store_cached_brief(db: Session, ticker: str, payload: dict) -> None:
    row = db.query(BriefCache).filter(BriefCache.ticker == ticker).first()
    payload_json = json.dumps(payload)
    now = datetime.now(timezone.utc)
    if row is None:
        db.add(BriefCache(ticker=ticker, payload=payload_json, generated_at=now))
    else:
        row.payload = payload_json
        row.generated_at = now
    db.commit()


# ---------- page routes ----------
@app.get("/")
def serve_index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/app")
def serve_app():
    return FileResponse(WEB_DIR / "app.html")


# ---------- brief ----------
@app.post("/brief", response_model=BriefResponse)
@limiter.limit("20/hour")
def generate_brief(
    request: Request,
    req: BriefRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User | None, Depends(optional_user)] = None,
):
    ticker = _validate_ticker(req.ticker)
    uid = user.id if user else None

    cached = _read_cached_brief(db, ticker)
    if cached is not None:
        logger.info(f"brief cache hit ticker={ticker} user={uid}")
        cached["cached"] = True
        _log_request(ticker, uid, req.experience_level, cached=True)
        return BriefResponse(**cached)

    logger.info(f"brief generate ticker={ticker} user={uid}")
    from .agent import run_agent
    result = run_agent(ticker, req.experience_level)
    if "error" in result and not result.get("what_happened"):
        raise HTTPException(status_code=500, detail=result["error"])
    result["cached"] = False
    _store_cached_brief(db, ticker, result)
    _log_request(ticker, uid, req.experience_level, cached=False)
    return BriefResponse(**result)


@app.get("/context/{ticker}")
@limiter.limit("60/hour")
def get_context(request: Request, ticker: str):
    """Knowledge graph context for the given ticker (competitors, suppliers,
    customers, macro factors, each with live 7-day pct change)."""
    ticker = _validate_ticker(ticker)
    from .tools.context import get_knowledge_context
    return get_knowledge_context(ticker)


# ---------- search ----------
@app.get("/search")
@limiter.limit("120/hour")
def search_tickers(request: Request, q: str = "", limit: int = 8):
    """Type-ahead search over the knowledge graph.

    Matches by ticker exact/prefix and company-name prefix/substring so a user
    can type "microsoft" and find MSFT. Returns [{ticker, name, sector}, ...].
    """
    q = (q or "").strip()
    if len(q) < 1:
        return {"results": []}

    from .knowledge_graph.graph import get_graph
    graph = get_graph()
    ql = q.lower()
    limit = max(1, min(limit, 20))

    scored: list[tuple[int, dict]] = []
    for ticker, node in graph.nodes.items():
        name = (node.get("name") or "")
        tl = ticker.lower()
        nl = name.lower()

        score = 0
        if tl == ql:
            score = 1000
        elif tl.startswith(ql):
            score = 500 + max(0, 10 - len(ticker))
        elif nl.startswith(ql):
            score = 300 + max(0, 40 - len(name))
        elif f" {ql}" in f" {nl}":  # word-boundary substring
            score = 180 + max(0, 40 - len(name))
        elif ql in nl:
            score = 120

        if score > 0:
            scored.append((score, {
                "ticker": ticker,
                "name": name,
                "sector": node.get("gics_sector", ""),
            }))

    scored.sort(key=lambda s: (-s[0], s[1]["ticker"]))
    return {"results": [r for _, r in scored[:limit]]}


# ---------- alerts ----------
@app.get("/alerts")
def list_alerts(user: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]):
    """Watchlist tickers that moved more than 5% in the past 7 days."""
    items = db.query(WatchlistItem).filter(WatchlistItem.user_id == user.id).all()
    if not items:
        return {"alerts": []}
    from .portfolio import _fetch_many
    prices = _fetch_many([i.ticker for i in items])
    alerts = []
    for item in items:
        data = prices.get(item.ticker, {})
        pct = data.get("pct_change_7d")
        if pct is not None and abs(pct) >= 5:
            alerts.append({
                "ticker": item.ticker,
                "pct_change_7d": pct,
                "direction": "up" if pct > 0 else "down",
            })
    alerts.sort(key=lambda a: abs(a["pct_change_7d"]), reverse=True)
    return {"alerts": alerts}


# ---------- health ----------
@app.get("/health")
def health():
    return {"status": "ok", "version": app.version, "ts": datetime.now(timezone.utc).isoformat()}
