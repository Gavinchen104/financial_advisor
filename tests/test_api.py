"""End-to-end tests for the FastAPI app via TestClient.

We never call the real Gemini or yfinance:
- /brief is exercised via the cache-hit path (prepopulate BriefCache).
- Watchlist/holdings/alerts mock out src.portfolio._fetch_many and _fetch_one.
- /context mocks src.tools.context._pct_change_7d.
"""

import pytest

from src.api import _store_cached_brief


SAMPLE_BRIEF = {
    "ticker": "NVDA",
    "what_happened": "NVDA up 4%",
    "why_moved": "AI demand",
    "what_it_means": "sector move",
    "sources_text": "- [GTC](https://nvidia.com/gtc)",
    "full_brief": "full brief text",
    "disclaimer": "not investment advice",
    "cached": False,
    "earnings_window": "quiet",
    "days_until_earnings": None,
    "days_since_last_earnings": None,
    "next_earnings_date": None,
    "last_earnings_date": None,
}


@pytest.fixture
def mock_prices(monkeypatch):
    """Stub out yfinance calls used by the portfolio + alerts routes."""
    from src import portfolio as portfolio_module

    canned = {
        "NVDA": {"current_price": 500.0, "pct_change_7d": 6.0},
        "KO":   {"current_price": 60.0,  "pct_change_7d": 1.0},
        "AAPL": {"current_price": 190.0, "pct_change_7d": -8.0},
    }

    def fake_one(ticker: str) -> dict:
        return canned.get(ticker, {"current_price": 100.0, "pct_change_7d": 0.0})

    def fake_many(tickers):
        return {t: fake_one(t) for t in tickers}

    monkeypatch.setattr(portfolio_module, "_fetch_one", fake_one)
    monkeypatch.setattr(portfolio_module, "_fetch_many", fake_many)


@pytest.fixture
def mock_context_prices(monkeypatch):
    """Stub _pct_change_7d in the knowledge-graph context module."""
    from src.tools import context as context_module

    def fake_pct(ticker: str):
        return {"ticker": ticker, "current_price": 100.0, "pct_change_7d": 1.0}

    monkeypatch.setattr(context_module, "_pct_change_7d", fake_pct)


# ---------- health ----------
def test_health_returns_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "ts" in body


# ---------- /brief (cache path — no LLM call) ----------
def test_brief_returns_cached_payload(client, db):
    """If a fresh cache row exists, /brief returns it without invoking the agent."""
    _store_cached_brief(db, "NVDA", SAMPLE_BRIEF)
    r = client.post("/brief", json={"ticker": "NVDA"})
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "NVDA"
    assert body["what_happened"] == "NVDA up 4%"
    assert body["cached"] is True


def test_brief_cache_is_case_insensitive(client, db):
    _store_cached_brief(db, "NVDA", SAMPLE_BRIEF)
    r = client.post("/brief", json={"ticker": "nvda"})
    assert r.status_code == 200
    assert r.json()["ticker"] == "NVDA"


def test_brief_rejects_invalid_ticker(client):
    r = client.post("/brief", json={"ticker": "NOT_A_TICKER_123"})
    assert r.status_code == 400
    assert "invalid ticker" in r.json()["detail"].lower()


def test_brief_rejects_empty_ticker(client):
    r = client.post("/brief", json={"ticker": "   "})
    assert r.status_code == 400


# ---------- /context ----------
def test_context_returns_graph_shape(client, mock_context_prices):
    r = client.get("/context/NVDA")
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "NVDA"
    assert "competitors" in body
    assert "key_suppliers" in body
    assert "macro_factors" in body


def test_context_rejects_bad_ticker(client):
    r = client.get("/context/123")
    assert r.status_code == 400


# ---------- watchlist ----------
def test_watchlist_requires_auth(client):
    assert client.get("/watchlist").status_code == 401
    assert client.post("/watchlist", json={"ticker": "NVDA"}).status_code == 401


def test_watchlist_add_list_delete_roundtrip(authed_client, mock_prices):
    # Initially empty
    r = authed_client.get("/watchlist")
    assert r.status_code == 200
    assert r.json() == []

    # Add
    r = authed_client.post("/watchlist", json={"ticker": "nvda"})  # lowercase in
    assert r.status_code == 201
    assert r.json() == {"ok": True, "already_present": False}

    # List — returns enriched item (ticker uppercased, price merged)
    r = authed_client.get("/watchlist")
    items = r.json()
    assert len(items) == 1
    assert items[0]["ticker"] == "NVDA"
    assert items[0]["current_price"] == 500.0

    # Dedup on re-add
    r = authed_client.post("/watchlist", json={"ticker": "NVDA"})
    assert r.status_code == 201
    assert r.json()["already_present"] is True

    # Delete
    r = authed_client.delete("/watchlist/NVDA")
    assert r.status_code == 204
    assert authed_client.get("/watchlist").json() == []


def test_watchlist_is_user_scoped(client, mock_prices):
    # User A adds NVDA
    client.post("/auth/signup", json={
        "email": "a@example.com", "password": "hunter2hunter2"})
    client.post("/watchlist", json={"ticker": "NVDA"})

    # User B signs up fresh — starts with empty watchlist
    client.post("/auth/logout")
    client.cookies.clear()
    client.post("/auth/signup", json={
        "email": "b@example.com", "password": "hunter2hunter2"})
    r = client.get("/watchlist")
    assert r.status_code == 200
    assert r.json() == []


# ---------- holdings / portfolio ----------
def test_portfolio_requires_auth(client):
    assert client.get("/portfolio").status_code == 401
    assert client.post("/holdings", json={
        "ticker": "NVDA", "shares": 1, "cost_basis": 100}).status_code == 401


def test_add_holding_and_get_portfolio(authed_client, mock_prices):
    r = authed_client.post("/holdings", json={
        "ticker": "NVDA", "shares": 10, "cost_basis": 400})
    assert r.status_code == 201
    h = r.json()
    assert h["ticker"] == "NVDA"
    assert h["shares"] == 10
    assert h["cost_basis"] == 400
    assert h["current_price"] == 500.0
    # Market value: 10 * 500 = 5000; cost: 10 * 400 = 4000; pnl: 1000
    assert h["market_value"] == 5000.0
    assert h["total_cost"] == 4000.0
    assert h["unrealized_pnl"] == 1000.0
    assert h["unrealized_pnl_pct"] == 25.0

    r = authed_client.get("/portfolio")
    assert r.status_code == 200
    p = r.json()
    assert p["position_count"] == 1
    assert p["total_cost"] == 4000.0
    assert p["total_value"] == 5000.0
    assert p["total_pnl"] == 1000.0


def test_add_same_ticker_twice_averages_cost(authed_client, mock_prices):
    """Re-adding a ticker should merge into a single row with weighted avg cost."""
    authed_client.post("/holdings", json={
        "ticker": "NVDA", "shares": 10, "cost_basis": 400})
    authed_client.post("/holdings", json={
        "ticker": "NVDA", "shares": 10, "cost_basis": 600})

    p = authed_client.get("/portfolio").json()
    assert p["position_count"] == 1
    h = p["holdings"][0]
    assert h["shares"] == 20
    assert h["cost_basis"] == 500.0  # (10*400 + 10*600) / 20


def test_update_holding(authed_client, mock_prices):
    r = authed_client.post("/holdings", json={
        "ticker": "NVDA", "shares": 10, "cost_basis": 400})
    hid = r.json()["id"]
    r = authed_client.patch(f"/holdings/{hid}", json={"shares": 20})
    assert r.status_code == 200
    assert r.json()["shares"] == 20
    assert r.json()["cost_basis"] == 400  # unchanged


def test_update_other_users_holding_returns_404(client, mock_prices):
    """A holding id belonging to user A must not be editable by user B."""
    # A creates a holding
    client.post("/auth/signup", json={
        "email": "a@example.com", "password": "hunter2hunter2"})
    hid = client.post("/holdings", json={
        "ticker": "NVDA", "shares": 10, "cost_basis": 400}).json()["id"]

    # B tries to update it
    client.post("/auth/logout")
    client.cookies.clear()
    client.post("/auth/signup", json={
        "email": "b@example.com", "password": "hunter2hunter2"})
    r = client.patch(f"/holdings/{hid}", json={"shares": 999})
    assert r.status_code == 404


def test_delete_holding(authed_client, mock_prices):
    hid = authed_client.post("/holdings", json={
        "ticker": "NVDA", "shares": 10, "cost_basis": 400}).json()["id"]
    r = authed_client.delete(f"/holdings/{hid}")
    assert r.status_code == 204
    assert authed_client.get("/portfolio").json()["position_count"] == 0


# ---------- alerts ----------
def test_alerts_requires_auth(client):
    assert client.get("/alerts").status_code == 401


def test_alerts_flags_only_large_moves(authed_client, mock_prices):
    """mock_prices sets NVDA at +6% (flagged), KO at +1% (quiet), AAPL at -8% (flagged)."""
    for t in ["NVDA", "KO", "AAPL"]:
        authed_client.post("/watchlist", json={"ticker": t})

    r = authed_client.get("/alerts")
    assert r.status_code == 200
    alerts = r.json()["alerts"]
    tickers = {a["ticker"] for a in alerts}
    assert tickers == {"NVDA", "AAPL"}  # KO excluded (<5%)
    # Sorted by absolute magnitude descending: AAPL (-8) before NVDA (+6)
    assert alerts[0]["ticker"] == "AAPL"
    assert alerts[0]["direction"] == "down"
    assert alerts[1]["ticker"] == "NVDA"
    assert alerts[1]["direction"] == "up"
