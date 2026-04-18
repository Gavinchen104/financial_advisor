"""
One-time build script: fetches the S&P 500 company list from Wikipedia,
merges in curated supply-chain and macro edges, and saves the compiled graph
to src/knowledge_graph/data/sp500_graph.json.

Run: uv run python scripts/build_knowledge_graph.py
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.knowledge_graph._relationships import EDGES
from src.knowledge_graph._macro import MACRO_FACTORS, SECTOR_MACRO_SENSITIVITY, COMPANY_MACRO_OVERRIDES

OUT_PATH = ROOT / "src" / "knowledge_graph" / "data" / "sp500_graph.json"


def fetch_sp500_companies() -> dict[str, dict]:
    """
    Fetch S&P 500 company list. Tries two sources in order:
    1. GitHub-hosted constituents CSV (fast, reliable)
    2. Wikipedia via httpx with lxml parsing
    """
    import io
    import httpx

    # Source 1: GitHub datasets (reliable, no bot blocking)
    sources = [
        "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv",
        "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv",
    ]
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

    df = None
    for url in sources:
        try:
            print(f"Fetching S&P 500 list from {url[:60]}...")
            resp = httpx.get(url, headers=headers, timeout=30, follow_redirects=True)
            resp.raise_for_status()
            df = pd.read_csv(io.StringIO(resp.text))
            print(f"  Fetched {len(df)} rows")
            break
        except Exception as e:
            print(f"  Source failed: {e}")

    # Source 2: Wikipedia HTML table fallback
    if df is None:
        print("Falling back to Wikipedia...")
        resp = httpx.get(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            headers={**headers, "Accept": "text/html,application/xhtml+xml", "Accept-Language": "en-US,en"},
            timeout=30, follow_redirects=True,
        )
        resp.raise_for_status()
        tables = pd.read_html(io.StringIO(resp.text), header=0)
        df = tables[0]

    # Normalize column names across sources (Wikipedia vs GitHub CSV have different column names)
    df.columns = [c.strip() for c in df.columns]
    print(f"  Columns: {list(df.columns)}")

    col_map = {}
    for col in df.columns:
        lc = col.lower()
        if any(k in lc for k in ("symbol", "ticker")):
            col_map["ticker"] = col
        elif any(k in lc for k in ("security", "company", "name")):
            col_map["name"] = col
        elif "gics sector" in lc or lc == "sector":
            col_map["sector"] = col
        elif "sub-industry" in lc or "sub industry" in lc or "subindustry" in lc or lc == "sub-industry":
            col_map["sub_industry"] = col
        elif "industry" in lc and "sub" not in lc and "group" not in lc:
            col_map.setdefault("sub_industry", col)  # GitHub CSV uses "Industry" not "GICS Sub-Industry"

    nodes: dict[str, dict] = {}
    for _, row in df.iterrows():
        ticker = str(row.get(col_map.get("ticker", "Symbol"), "")).strip().replace(".", "-")
        if not ticker:
            continue
        nodes[ticker] = {
            "ticker": ticker,
            "name": str(row.get(col_map.get("name", "Security"), "")).strip(),
            "gics_sector": str(row.get(col_map.get("sector", "GICS Sector"), "")).strip(),
            "gics_sub_industry": str(row.get(col_map.get("sub_industry", "GICS Sub-Industry"), "")).strip(),
            "sp500": True,
        }

    print(f"  Loaded {len(nodes)} S&P 500 companies")
    return nodes


def add_external_nodes(nodes: dict[str, dict]) -> None:
    """Add important non-S&P 500 tickers referenced in curated edges."""
    EXTERNAL = {
        "TSM":  {"name": "Taiwan Semiconductor Manufacturing (TSMC)", "gics_sector": "Information Technology", "gics_sub_industry": "Semiconductors", "sp500": False},
        "ASML": {"name": "ASML Holding", "gics_sector": "Information Technology", "gics_sub_industry": "Semiconductor Equipment", "sp500": False},
        "NVO":  {"name": "Novo Nordisk", "gics_sector": "Health Care", "gics_sub_industry": "Pharmaceuticals", "sp500": False},
        "SNAP": {"name": "Snap Inc.", "gics_sector": "Communication Services", "gics_sub_industry": "Interactive Media & Services", "sp500": False},
        "PINS": {"name": "Pinterest", "gics_sector": "Communication Services", "gics_sub_industry": "Interactive Media & Services", "sp500": False},
        "ABNB": {"name": "Airbnb", "gics_sector": "Consumer Discretionary", "gics_sub_industry": "Hotels & Lodging", "sp500": False},
        "GOLD": {"name": "Barrick Gold", "gics_sector": "Materials", "gics_sub_industry": "Gold", "sp500": False},
        "SCCO": {"name": "Southern Copper", "gics_sector": "Materials", "gics_sub_industry": "Copper", "sp500": False},
        "SAP":  {"name": "SAP SE", "gics_sector": "Information Technology", "gics_sub_industry": "Application Software", "sp500": False},
        "MSCI": {"name": "MSCI Inc.", "gics_sector": "Financials", "gics_sub_industry": "Financial Exchanges & Data", "sp500": False},
    }
    for ticker, attrs in EXTERNAL.items():
        if ticker not in nodes:
            nodes[ticker] = {"ticker": ticker, **attrs}
    print(f"  Added {len(EXTERNAL)} external (non-S&P 500) reference nodes")


def build_auto_competitor_edges(nodes: dict[str, dict]) -> list[dict]:
    """Auto-generate competitor edges for companies in the same GICS sub-industry."""
    from collections import defaultdict
    buckets: dict[str, list[str]] = defaultdict(list)
    for ticker, node in nodes.items():
        sub = node.get("gics_sub_industry", "")
        if sub and sub.lower() not in ("", "nan", "none"):
            buckets[sub].append(ticker)

    edges = []
    seen: set[frozenset] = set()
    for sub, tickers in buckets.items():
        if len(tickers) < 2:
            continue
        for i, a in enumerate(tickers):
            for b in tickers[i + 1:]:
                key = frozenset([a, b])
                if key in seen:
                    continue
                seen.add(key)
                edges.append({
                    "source": a, "target": b,
                    "type": "competes_with",
                    "weight": 0.5,
                    "label": f"Both in GICS sub-industry: {sub}",
                    "auto_generated": True,
                })
    print(f"  Auto-generated {len(edges)} competitor edges from GICS sub-industry grouping")
    return edges


def build_curated_edges(nodes: dict[str, dict]) -> list[dict]:
    """Convert the curated EDGES list into dicts and register any missing node stubs."""
    edges = []
    for source, target, etype, weight, label in EDGES:
        # Auto-register unknown tickers as stubs so graph stays consistent
        for t in (source, target):
            if t not in nodes:
                nodes[t] = {"ticker": t, "name": t, "gics_sector": "Unknown", "gics_sub_industry": "Unknown", "sp500": False}
        edges.append({
            "source": source, "target": target,
            "type": etype, "weight": weight, "label": label,
            "auto_generated": False,
        })
    print(f"  Loaded {len(edges)} curated relationship edges")
    return edges


def build_macro_edges(nodes: dict[str, dict]) -> list[dict]:
    """Build macro sensitivity edges from sector mappings and company-level overrides."""
    edges = []
    # Sector-level edges
    for ticker, node in nodes.items():
        sector = node.get("gics_sector", "")
        sensitivities = SECTOR_MACRO_SENSITIVITY.get(sector, [])
        for s in sensitivities:
            edges.append({
                "source": ticker,
                "target": s["factor"],
                "type": "macro_sensitivity",
                "direction": s["direction"],
                "weight": s["strength"],
                "label": s["reason"],
            })

    # Company-specific overrides (add or strengthen)
    for ticker, overrides in COMPANY_MACRO_OVERRIDES.items():
        for o in overrides:
            edges.append({
                "source": ticker,
                "target": o["factor"],
                "type": "macro_sensitivity",
                "direction": o["direction"],
                "weight": o["strength"],
                "label": o["reason"],
                "override": True,
            })

    print(f"  Built {len(edges)} macro sensitivity edges")
    return edges


def compile_graph(nodes: dict[str, dict], all_edges: list[dict]) -> dict:
    return {
        "metadata": {
            "built_at": datetime.now(timezone.utc).isoformat(),
            "node_count": len(nodes),
            "edge_count": len(all_edges),
            "sp500_count": sum(1 for n in nodes.values() if n.get("sp500")),
        },
        "nodes": nodes,
        "edges": all_edges,
        "macro_factors": MACRO_FACTORS,
    }


def main():
    print("Building S&P 500 knowledge graph...")

    nodes = fetch_sp500_companies()
    add_external_nodes(nodes)

    auto_edges = build_auto_competitor_edges(nodes)
    curated_edges = build_curated_edges(nodes)
    macro_edges = build_macro_edges(nodes)

    all_edges = curated_edges + auto_edges + macro_edges

    graph = compile_graph(nodes, all_edges)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(graph, f, indent=2)

    meta = graph["metadata"]
    print(f"\nGraph saved to {OUT_PATH}")
    print(f"  Nodes : {meta['node_count']} ({meta['sp500_count']} S&P 500 + {meta['node_count'] - meta['sp500_count']} external)")
    print(f"  Edges : {meta['edge_count']}")
    print(f"    Curated     : {len(curated_edges)}")
    print(f"    Auto (GICS) : {len(auto_edges)}")
    print(f"    Macro       : {len(macro_edges)}")


if __name__ == "__main__":
    main()
