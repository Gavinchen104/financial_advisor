"""
KnowledgeGraph: loads the compiled sp500_graph.json and provides query methods.
The graph is loaded once at import time (module-level singleton).
"""

import json
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

_GRAPH_PATH = Path(__file__).parent / "data" / "sp500_graph.json"


class KnowledgeGraph:
    def __init__(self, path: Path = _GRAPH_PATH):
        if not path.exists():
            raise FileNotFoundError(
                f"Knowledge graph not found at {path}. "
                "Run: uv run python scripts/build_knowledge_graph.py"
            )
        with open(path) as f:
            data = json.load(f)

        self.nodes: dict[str, dict] = data["nodes"]
        self.macro_factors: dict[str, dict] = data["macro_factors"]

        # Build adjacency index for fast lookups
        self._adj: dict[str, list[dict]] = defaultdict(list)
        for edge in data["edges"]:
            self._adj[edge["source"]].append(edge)
            # competes_with and strategic_partner are symmetric — index both directions
            if edge["type"] in ("competes_with", "strategic_partner"):
                reverse = {**edge, "source": edge["target"], "target": edge["source"]}
                self._adj[edge["target"]].append(reverse)

    def get_node(self, ticker: str) -> dict | None:
        return self.nodes.get(ticker.upper())

    def get_competitors(self, ticker: str, max_results: int = 6) -> list[dict]:
        """Return top competitors sorted by relationship weight."""
        ticker = ticker.upper()
        edges = [e for e in self._adj.get(ticker, []) if e["type"] == "competes_with"]
        edges.sort(key=lambda e: e["weight"], reverse=True)
        return [self._enrich(e, ticker) for e in edges[:max_results]]

    def get_suppliers(self, ticker: str) -> list[dict]:
        """Return companies that supply to this ticker."""
        ticker = ticker.upper()
        results = []
        for edges in self._adj.values():
            for e in edges:
                if e["type"] == "supplies_to" and e["target"] == ticker:
                    results.append(self._enrich(e, ticker))
        results.sort(key=lambda e: e["weight"], reverse=True)
        # Deduplicate by other_ticker
        seen: set[str] = set()
        deduped = []
        for r in results:
            if r["other_ticker"] not in seen:
                seen.add(r["other_ticker"])
                deduped.append(r)
        return deduped

    def get_customers(self, ticker: str) -> list[dict]:
        """Return companies this ticker supplies to."""
        ticker = ticker.upper()
        edges = [e for e in self._adj.get(ticker, []) if e["type"] == "supplies_to"]
        edges.sort(key=lambda e: e["weight"], reverse=True)
        return [self._enrich(e, ticker) for e in edges]

    def get_macro_sensitivity(self, ticker: str) -> list[dict]:
        """Return macro factors affecting this ticker, merging sector defaults + company overrides."""
        ticker = ticker.upper()
        node = self.nodes.get(ticker)
        sector = node.get("gics_sector") if node else None

        # Collect all macro edges for this ticker
        macro_edges = [e for e in self._adj.get(ticker, []) if e["type"] == "macro_sensitivity"]

        # De-duplicate: company overrides (override=True) take precedence over sector defaults
        seen_factors: dict[str, dict] = {}
        # First pass: sector defaults
        for e in macro_edges:
            if not e.get("override"):
                seen_factors.setdefault(e["target"], e)
        # Second pass: overrides replace
        for e in macro_edges:
            if e.get("override"):
                seen_factors[e["target"]] = e

        results = list(seen_factors.values())
        results.sort(key=lambda e: e["weight"], reverse=True)

        # Enrich with macro factor metadata
        enriched = []
        for e in results:
            factor_id = e["target"]
            factor_meta = self.macro_factors.get(factor_id, {})
            enriched.append({
                **e,
                "factor_name": factor_meta.get("name", factor_id),
                "yfinance_ticker": factor_meta.get("yfinance_ticker"),
                "factor_description": factor_meta.get("description", ""),
            })
        return enriched

    def get_supply_chain(self, ticker: str) -> dict[str, list[dict]]:
        """Return full supply chain context: suppliers, customers, and competitors."""
        return {
            "competitors": self.get_competitors(ticker),
            "suppliers": self.get_suppliers(ticker),
            "customers": self.get_customers(ticker),
        }

    def get_sector_peers(self, ticker: str, max_results: int = 5) -> list[dict]:
        """Return same-sector peers from S&P 500 (for context, not just direct competitors)."""
        ticker = ticker.upper()
        node = self.nodes.get(ticker)
        if not node:
            return []
        sector = node.get("gics_sector")
        sub = node.get("gics_sub_industry")

        # Prefer same sub-industry, then fill with same sector
        same_sub = [
            n for t, n in self.nodes.items()
            if t != ticker and n.get("gics_sub_industry") == sub and n.get("sp500")
        ]
        same_sector = [
            n for t, n in self.nodes.items()
            if t != ticker and n.get("gics_sector") == sector and n.get("sp500")
            and n.get("gics_sub_industry") != sub
        ]
        combined = same_sub[:max_results] + same_sector[:max_results]
        return [{"ticker": n["ticker"], "name": n["name"], "sub_industry": n.get("gics_sub_industry")}
                for n in combined[:max_results]]

    def _enrich(self, edge: dict, query_ticker: str) -> dict:
        """Add the 'other' node's metadata to an edge. other = whichever side isn't the query ticker."""
        other = edge["target"] if edge["source"] == query_ticker else edge["source"]
        node = self.nodes.get(other, {})
        return {
            **edge,
            "other_ticker": other,
            "other_name": node.get("name", other),
            "other_sector": node.get("gics_sector", ""),
            "other_sub_industry": node.get("gics_sub_industry", ""),
        }


# Module-level singleton — loaded once, reused across requests
_instance: KnowledgeGraph | None = None


def get_graph() -> KnowledgeGraph:
    global _instance
    if _instance is None:
        _instance = KnowledgeGraph()
    return _instance
