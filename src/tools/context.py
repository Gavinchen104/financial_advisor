"""
get_knowledge_context(ticker) — queries the knowledge graph for related companies
and macro factors, then fetches their live 7-day performance via yfinance.
Returns a structured dict ready to pass into the Gemini prompt.
"""

import concurrent.futures
import logging
from datetime import datetime, timedelta
from typing import Any

import yfinance as yf

logging.getLogger("yfinance").setLevel(logging.CRITICAL)


def _pct_change_7d(ticker: str) -> dict[str, Any]:
    """Fetch 7-day price change for a given ticker. Returns minimal dict."""
    try:
        end = datetime.now()
        start = end - timedelta(days=14)
        hist = yf.Ticker(ticker).history(start=start, end=end)
        if hist.empty or len(hist) < 2:
            return {"ticker": ticker, "error": "no data"}
        hist = hist.tail(7)
        first = float(hist.iloc[0]["Close"])
        last = float(hist.iloc[-1]["Close"])
        pct = round(((last - first) / first) * 100, 2)
        return {"ticker": ticker, "current_price": round(last, 4), "pct_change_7d": pct}
    except Exception:
        return {"ticker": ticker, "error": "fetch failed"}


def _valuation_row(ticker: str, name: str | None = None, is_target: bool = False) -> dict[str, Any]:
    """Fetch valuation multiples for a single ticker. Returns one row of the peer table."""
    row: dict[str, Any] = {
        "ticker": ticker,
        "name": name or ticker,
        "is_target": is_target,
        "market_cap": None,
        "trailing_pe": None,
        "forward_pe": None,
        "ev_to_ebitda": None,
        "revenue_growth_yoy": None,
    }
    try:
        info = yf.Ticker(ticker).info
        row["market_cap"] = info.get("marketCap")
        row["trailing_pe"] = info.get("trailingPE")
        row["forward_pe"] = info.get("forwardPE")
        row["ev_to_ebitda"] = info.get("enterpriseToEbitda")
        row["revenue_growth_yoy"] = info.get("revenueGrowth")
    except Exception:
        pass
    return row


def get_knowledge_context(ticker: str) -> dict[str, Any]:
    """
    Returns a structured knowledge-graph context block for the given ticker:
      - competitors: top 5 with live 7-day performance
      - suppliers: upstream supply chain with live performance
      - customers: downstream customers with live performance
      - macro_factors: relevant macro indicators with current values and direction
    """
    ticker = ticker.upper()

    try:
        from src.knowledge_graph.graph import get_graph
        graph = get_graph()
    except FileNotFoundError as e:
        return {"error": str(e)}

    node = graph.get_node(ticker)
    if not node:
        return {"error": f"{ticker} not found in knowledge graph"}

    chain = graph.get_supply_chain(ticker)
    macro_edges = graph.get_macro_sensitivity(ticker)

    # Collect all tickers to fetch in one parallel batch
    competitor_tickers = [e["other_ticker"] for e in chain["competitors"][:5]]
    supplier_tickers   = [e["other_ticker"] for e in chain["suppliers"][:4]]
    customer_tickers   = [e["other_ticker"] for e in chain["customers"][:4]]
    macro_yf_tickers   = [
        e["yfinance_ticker"] for e in macro_edges[:5] if e.get("yfinance_ticker")
    ]

    all_tickers = list(dict.fromkeys(
        competitor_tickers + supplier_tickers + customer_tickers + macro_yf_tickers
    ))

    # Fetch all in parallel
    price_data: dict[str, dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(all_tickers) + 1, 12)) as ex:
        futures = {ex.submit(_pct_change_7d, t): t for t in all_tickers}
        for fut in concurrent.futures.as_completed(futures):
            result = fut.result()
            price_data[result["ticker"]] = result

    def enrich_with_price(edges: list[dict], tickers: list[str]) -> list[dict]:
        out = []
        for edge, t in zip(edges, tickers):
            live = price_data.get(t, {})
            out.append({
                "ticker": t,
                "name": edge.get("other_name", t),
                "relationship": edge["type"],
                "relationship_label": edge.get("label", ""),
                "weight": edge.get("weight"),
                "pct_change_7d": live.get("pct_change_7d"),
                "current_price": live.get("current_price"),
            })
        return out

    enriched_competitors = enrich_with_price(chain["competitors"][:5], competitor_tickers)
    enriched_suppliers   = enrich_with_price(chain["suppliers"][:4],   supplier_tickers)
    enriched_customers   = enrich_with_price(chain["customers"][:4],   customer_tickers)

    # Peer valuation — target + top 3 competitors in parallel
    peer_rows: list[dict[str, Any]] = []
    peer_fetch: list[tuple[str, str | None, bool]] = [(ticker, node.get("name"), True)]
    for comp in enriched_competitors[:3]:
        peer_fetch.append((comp["ticker"], comp["name"], False))
    if peer_fetch:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(peer_fetch)) as ex:
            futures = [ex.submit(_valuation_row, t, n, is_t) for t, n, is_t in peer_fetch]
            for fut in concurrent.futures.as_completed(futures):
                peer_rows.append(fut.result())
        # preserve target-first ordering
        peer_rows.sort(key=lambda r: (not r["is_target"], r["ticker"]))

    # Macro factors with live current values
    enriched_macro = []
    for e in macro_edges[:5]:
        yf_ticker = e.get("yfinance_ticker")
        live = price_data.get(yf_ticker, {}) if yf_ticker else {}
        enriched_macro.append({
            "factor_id": e["target"],
            "factor_name": e.get("factor_name", e["target"]),
            "yfinance_ticker": yf_ticker,
            "direction": e.get("direction"),
            "weight": e.get("weight"),
            "reason": e.get("label", ""),
            "current_value": live.get("current_price"),
            "pct_change_7d": live.get("pct_change_7d"),
        })

    return {
        "ticker": ticker,
        "company_name": node.get("name"),
        "sector": node.get("gics_sector"),
        "sub_industry": node.get("gics_sub_industry"),
        "competitors": enriched_competitors,
        "key_suppliers": enriched_suppliers,
        "key_customers": enriched_customers,
        "macro_factors": enriched_macro,
        "peer_valuation": peer_rows,
        "source_url": f"https://finance.yahoo.com/quote/{ticker}",
    }
