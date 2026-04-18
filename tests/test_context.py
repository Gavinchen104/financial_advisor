"""Tests for the knowledge-graph context module.

We mock yfinance so tests are offline-safe and deterministic. Fast unit tests
for the graph query API itself, plus one integration-shaped test that runs
get_knowledge_context end-to-end with a mocked price fetch.
"""

import pytest

from src.knowledge_graph.graph import get_graph
from src.tools import context as context_module


@pytest.fixture
def mock_price_fetch(monkeypatch):
    """Replace the yfinance-backed _pct_change_7d with a deterministic stub.
    Any ticker 'A', 'B', ... gets a predictable move; unknown tickers return
    an error dict to simulate the yfinance flakiness we accept per CLAUDE.md."""
    def fake_pct(ticker: str):
        canned = {
            "AMD":  {"ticker": "AMD",  "current_price": 180.0, "pct_change_7d": 2.5},
            "INTC": {"ticker": "INTC", "current_price": 32.0,  "pct_change_7d": -1.2},
            "TSM":  {"ticker": "TSM",  "current_price": 195.0, "pct_change_7d": 3.1},
            "ASML": {"ticker": "ASML", "current_price": 820.0, "pct_change_7d": 1.4},
            "^TNX": {"ticker": "^TNX", "current_price": 4.25,  "pct_change_7d": 0.1},
            "CL=F": {"ticker": "CL=F", "current_price": 82.0,  "pct_change_7d": -0.5},
        }
        return canned.get(ticker, {"ticker": ticker, "current_price": 100.0, "pct_change_7d": 0.0})

    monkeypatch.setattr(context_module, "_pct_change_7d", fake_pct)


# ---------- KnowledgeGraph query API ----------
def test_graph_loads_at_least_sp500():
    graph = get_graph()
    # sanity bounds — somewhere around 500 constituents plus curated externals
    assert len(graph.nodes) > 400
    assert "NVDA" in graph.nodes
    assert graph.nodes["NVDA"]["gics_sector"] == "Information Technology"


def test_get_competitors_returns_sorted_by_weight():
    graph = get_graph()
    comps = graph.get_competitors("NVDA", max_results=5)
    assert len(comps) > 0
    # Each competitor edge has the 'other_ticker' field from _enrich
    assert all("other_ticker" in c for c in comps)
    # Sorted descending by weight
    weights = [c["weight"] for c in comps]
    assert weights == sorted(weights, reverse=True)
    # 'other_ticker' is not the query ticker itself
    assert all(c["other_ticker"] != "NVDA" for c in comps)


def test_get_macro_sensitivity_includes_factor_metadata():
    graph = get_graph()
    macros = graph.get_macro_sensitivity("XOM")  # energy stock
    assert len(macros) > 0
    # Each edge gets enriched with factor_name and yfinance_ticker from MACRO_FACTORS
    first = macros[0]
    assert "factor_name" in first
    assert "yfinance_ticker" in first


def test_get_node_returns_none_for_unknown_ticker():
    graph = get_graph()
    assert graph.get_node("ZZZZ") is None


def test_get_supply_chain_has_three_keys():
    graph = get_graph()
    chain = graph.get_supply_chain("NVDA")
    assert set(chain.keys()) == {"competitors", "suppliers", "customers"}


# ---------- get_knowledge_context end-to-end (with mocked prices) ----------
def test_get_knowledge_context_shape(mock_price_fetch):
    ctx = context_module.get_knowledge_context("NVDA")
    # Top-level keys the frontend graph viz depends on
    assert ctx["ticker"] == "NVDA"
    assert "company_name" in ctx
    assert "sector" in ctx
    assert "competitors" in ctx
    assert "key_suppliers" in ctx
    assert "key_customers" in ctx
    assert "macro_factors" in ctx
    assert ctx["source_url"].endswith("/quote/NVDA")


def test_get_knowledge_context_competitors_enriched_with_pct_change(mock_price_fetch):
    ctx = context_module.get_knowledge_context("NVDA")
    assert len(ctx["competitors"]) > 0
    c = ctx["competitors"][0]
    # Shape required by the D3 graph viz
    assert {"ticker", "name", "relationship", "weight", "pct_change_7d", "current_price"} <= c.keys()


def test_get_knowledge_context_unknown_ticker_returns_error(mock_price_fetch):
    """A ticker outside the S&P 500 + curated externals returns a structured
    error dict — the agent relies on this to write a graceful brief."""
    ctx = context_module.get_knowledge_context("ZZZZ")
    assert "error" in ctx


def test_get_knowledge_context_uppercases_input(mock_price_fetch):
    ctx_lower = context_module.get_knowledge_context("nvda")
    ctx_upper = context_module.get_knowledge_context("NVDA")
    assert ctx_lower["ticker"] == "NVDA" == ctx_upper["ticker"]
