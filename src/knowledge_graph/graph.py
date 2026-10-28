"""
KnowledgeGraph: the in-memory relationship graph behind /context, /search and
the RAG graph retrieval (docs/PROJECT2-PLAN.md P2-B / P2-G).

Two backends build the same object:

- JSON  — src/knowledge_graph/data/sp500_graph.json, compiled by
          scripts/build_knowledge_graph.py. Always available.
- DB    — kg_nodes / kg_edges in Postgres, seeded from that JSON by
          scripts/seed_kg.py (src/rag/kg_store.py) and later extended with
          filing-derived edges that carry a verbatim quote as evidence.

Both go through canonical_edges(), so every edge has the same shape and the
query API behaves identically. get_graph() prefers the DB graph when Postgres
is configured and seeded and falls back to JSON otherwise.

Edge shape (after canonical_edges):
    source, target   node ids: ticker | macro factor id | 'org:<slug>'
    type             competes_with | supplies_to | strategic_partner | macro_sensitivity
    weight           0..1
    label            human-readable rationale (curated/gics) or the quote (filing)
    provenance       curated | gics | filing
    evidence         rationale / verbatim quote (None when unknown)
    accession, confidence, edge_id   set on DB-backed edges when known
    direction, override              macro edges only
"""

from __future__ import annotations

import json
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from loguru import logger

_GRAPH_PATH = Path(__file__).parent / "data" / "sp500_graph.json"

SYMMETRIC_TYPES = frozenset({"competes_with", "strategic_partner"})
COMPANY_EDGE_TYPES = frozenset({"competes_with", "supplies_to", "strategic_partner"})
MACRO_EDGE_TYPE = "macro_sensitivity"
PROVENANCE_RANK = {"filing": 0, "curated": 1, "gics": 2}

# How long a DB-backed graph is served before get_graph() reloads it, so a
# re-seed or a new ingestion shows up without a restart.
DB_REFRESH_SECONDS = 15 * 60


def _provenance_rank(edge: dict) -> int:
    return PROVENANCE_RANK.get(edge.get("provenance", ""), 9)


def canonical_edges(raw_edges: Iterable[dict]) -> list[dict]:
    """Normalize raw edges (JSON or DB rows) into the shape documented above.

    - `major_customer(A → B)` ("A is a customer of B") becomes `supplies_to(B → A)`,
      the canonical form the rest of the graph and the filing extractor use.
    - `provenance` is derived from `auto_generated` for JSON edges (gics vs curated)
      and kept as-is for DB edges.
    - `evidence` defaults to the label.
    - Duplicates with the same (source, target, type, provenance, accession) collapse
      to one edge: a macro override beats its sector default, then the higher weight.
      The original order is otherwise preserved so tie-breaking is deterministic.
    Idempotent: canonical input comes out unchanged.
    """
    prepared: list[dict] = []
    for idx, raw in enumerate(raw_edges):
        e = dict(raw)
        if e["type"] == "major_customer":
            e["source"], e["target"] = e["target"], e["source"]
            e["type"] = "supplies_to"
        e["provenance"] = e.get("provenance") or ("gics" if e.pop("auto_generated", False) else "curated")
        e.pop("auto_generated", None)
        e["weight"] = float(e.get("weight") or 0.0)
        e["label"] = e.get("label") or ""
        if e.get("evidence") is None:
            e["evidence"] = e["label"] or None
        e["_order"] = idx
        prepared.append(e)

    # Preferred duplicate first: override, then weight.
    prepared.sort(key=lambda e: (0 if e.get("override") else 1, -e["weight"], e["_order"]))
    seen: set[tuple] = set()
    kept: list[dict] = []
    for e in prepared:
        key = (e["source"], e["target"], e["type"], e["provenance"], e.get("accession"))
        if key in seen:
            continue
        seen.add(key)
        kept.append(e)
    kept.sort(key=lambda e: e["_order"])
    for e in kept:
        del e["_order"]
    return kept


def _norm_id(node_id: str) -> str:
    """Tickers are upper-case; namespaced ids ('macro:x', 'org:slug') are kept as-is."""
    node_id = (node_id or "").strip()
    return node_id if ":" in node_id else node_id.upper()


class KnowledgeGraph:
    def __init__(self, data: dict, *, backend: str = "json"):
        self.backend = backend
        self.metadata: dict = data.get("metadata", {})
        self.nodes: dict[str, dict] = data["nodes"]
        self.macro_factors: dict[str, dict] = data.get("macro_factors", {})
        self.edges: list[dict] = canonical_edges(data["edges"])
        self._build_indexes()

    # ---------- construction ----------
    @classmethod
    def from_json(cls, path: Path = _GRAPH_PATH) -> "KnowledgeGraph":
        if not path.exists():
            raise FileNotFoundError(
                f"Knowledge graph not found at {path}. "
                "Run: uv run python scripts/build_knowledge_graph.py"
            )
        with open(path) as f:
            data = json.load(f)
        return cls(data, backend="json")

    @classmethod
    def from_db(cls, session=None) -> "KnowledgeGraph | None":
        """Graph from kg_nodes / kg_edges. None when the tables hold no company nodes
        (not seeded yet). `session` may be a SQLAlchemy Session or Connection; when
        omitted a short-lived session on the app engine is used."""
        from src.rag.kg_store import load_graph_data

        data = load_graph_data(session)
        return cls(data, backend="db") if data else None

    def _build_indexes(self) -> None:
        # _adj: node → edges where node is the source, plus a reversed copy of each
        # symmetric edge so competitors/partners are found from either side.
        # _in:  node → edges where node is the target (original orientation only).
        self._adj: dict[str, list[dict]] = defaultdict(list)
        self._in: dict[str, list[dict]] = defaultdict(list)
        self._by_id: dict[int, dict] = {}
        for uid, edge in enumerate(self.edges):
            edge["_uid"] = uid
            self._adj[edge["source"]].append(edge)
            self._in[edge["target"]].append(edge)
            if edge["type"] in SYMMETRIC_TYPES:
                reverse = {**edge, "source": edge["target"], "target": edge["source"], "_reversed": True}
                self._adj[edge["target"]].append(reverse)
            if edge.get("edge_id") is not None:
                self._by_id[int(edge["edge_id"])] = edge

    # ---------- node lookups ----------
    def get_node(self, ticker: str) -> dict | None:
        return self.nodes.get(_norm_id(ticker))

    def get_edge(self, edge_id: int) -> dict | None:
        """DB edge by primary key (for kg://edge/<id> evidence). None on the JSON backend."""
        return self._by_id.get(int(edge_id))

    # ---------- relationship queries ----------
    def get_competitors(self, ticker: str, max_results: int = 6) -> list[dict]:
        """Top competitors by weight. One row per counterparty: when a curated and a
        GICS edge both exist, the heavier (curated) one wins."""
        ticker = _norm_id(ticker)
        edges = [e for e in self._adj.get(ticker, []) if e["type"] == "competes_with"]
        return self._top(edges, ticker)[:max_results]

    def get_suppliers(self, ticker: str) -> list[dict]:
        """Companies that supply to this ticker (incoming supplies_to edges)."""
        ticker = _norm_id(ticker)
        edges = [e for e in self._in.get(ticker, []) if e["type"] == "supplies_to"]
        return self._top(edges, ticker)

    def get_customers(self, ticker: str) -> list[dict]:
        """Companies this ticker supplies to (outgoing supplies_to edges)."""
        ticker = _norm_id(ticker)
        edges = [e for e in self._adj.get(ticker, []) if e["type"] == "supplies_to"]
        return self._top(edges, ticker)

    def get_macro_sensitivity(self, ticker: str) -> list[dict]:
        """Macro factors affecting this ticker. A company override replaces the
        sector default for the same factor (canonical_edges already collapses them;
        this keeps the rule explicit for hand-built graphs)."""
        ticker = _norm_id(ticker)
        macro_edges = [e for e in self._adj.get(ticker, []) if e["type"] == MACRO_EDGE_TYPE]
        macro_edges.sort(key=lambda e: (0 if e.get("override") else 1, -e["weight"]))
        seen: dict[str, dict] = {}
        for e in macro_edges:
            seen.setdefault(e["target"], e)
        results = sorted(seen.values(), key=lambda e: -e["weight"])

        enriched = []
        for e in results:
            factor_meta = self.macro_factors.get(e["target"], {})
            enriched.append({
                **e,
                "factor_name": factor_meta.get("name", e["target"]),
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
        ticker = _norm_id(ticker)
        node = self.nodes.get(ticker)
        if not node:
            return []
        sector = node.get("gics_sector")
        sub = node.get("gics_sub_industry")

        # Prefer same sub-industry, then fill with same sector. Sorted by ticker so the
        # result does not depend on node order (JSON file order vs DB order).
        same_sub = [
            n for t, n in sorted(self.nodes.items())
            if t != ticker and n.get("gics_sub_industry") == sub and n.get("sp500")
        ]
        same_sector = [
            n for t, n in sorted(self.nodes.items())
            if t != ticker and n.get("gics_sector") == sector and n.get("sp500")
            and n.get("gics_sub_industry") != sub
        ]
        combined = same_sub[:max_results] + same_sector[:max_results]
        return [{"ticker": n["ticker"], "name": n["name"], "sub_industry": n.get("gics_sub_industry")}
                for n in combined[:max_results]]

    # ---------- traversal (RAG graph retrieval) ----------
    def neighbors(self, node_id: str, types: Iterable[str] | None = None, k: int = 10) -> list[dict]:
        """Edges touching `node_id` in either direction, heaviest first, at most `k`.

        Each item is the enriched edge plus:
          other_id            the node at the far end
          relation_direction  'out' (node → other), 'in' (other → node) or 'both' (symmetric)
        `types` filters edge types (default: all, macro included).
        """
        node_id = _norm_id(node_id)
        wanted = set(types) if types else None
        seen: set[int] = set()
        items: list[dict] = []
        for e in self._touching(node_id):
            if wanted and e["type"] not in wanted:
                continue
            if e["_uid"] in seen:
                continue
            seen.add(e["_uid"])
            other = e["target"] if e["source"] == node_id else e["source"]
            if e["type"] in SYMMETRIC_TYPES:
                direction = "both"
            else:
                direction = "out" if e["source"] == node_id else "in"
            items.append({**self._enrich(e, node_id), "other_id": other, "relation_direction": direction})
        items.sort(key=lambda it: (-it["weight"], _provenance_rank(it)))
        return items[:k]

    def paths(
        self,
        a: str,
        b: str,
        max_hops: int = 2,
        types: Iterable[str] | None = None,
        k: int = 10,
    ) -> list[dict]:
        """Simple paths from `a` to `b` over at most `max_hops` edges, ignoring edge
        direction. Default edge types are the company relationships (no macro).

        Each path: {hops, nodes, steps:[{from, to, traversed, edge}], score, summary}.
        Ranking: fewer hops first, then paths with filing-sourced edges before curated
        before GICS, then the product of the edge weights. Every step keeps the full
        edge, so callers can cite its provenance (source, evidence, accession).
        """
        a, b = _norm_id(a), _norm_id(b)
        if a == b or a not in self.nodes or b not in self.nodes:
            return []
        wanted = set(types) if types else set(COMPANY_EDGE_TYPES)
        found: list[list[dict]] = []

        def dfs(node: str, visited: set[str], steps: list[dict]) -> None:
            for e in self._touching(node):
                if e["type"] not in wanted:
                    continue
                other = e["target"] if e["source"] == node else e["source"]
                if other in visited:
                    continue
                step = {
                    "from": node,
                    "to": other,
                    "traversed": "forward" if e["source"] == node else "reverse",
                    "edge": self._public(e),
                }
                if other == b:
                    found.append(steps + [step])
                elif len(steps) + 1 < max_hops:
                    dfs(other, visited | {other}, steps + [step])

        dfs(a, {a}, [])

        def rank(path: list[dict]):
            best_prov = min(_provenance_rank(s["edge"]) for s in path)
            weight = 1.0
            for s in path:
                weight *= s["edge"]["weight"]
            return (len(path), best_prov, -weight)

        found.sort(key=rank)
        out = []
        for path in found[:k]:
            weight = 1.0
            for s in path:
                weight *= s["edge"]["weight"]
            out.append({
                "hops": len(path),
                "nodes": [a] + [s["to"] for s in path],
                "steps": path,
                "score": round(weight, 4),
                "summary": " ; ".join(self.describe_step(s) for s in path),
            })
        return out

    def describe_step(self, step: dict) -> str:
        """One hop as text with its provenance, e.g.
        "AAPL ←supplies_to– TSM (curated: 'TSMC fabricates Apple's A-series…')"."""
        e = step["edge"]
        arrow = f"–{e['type']}→" if step["traversed"] == "forward" else f"←{e['type']}–"
        prov = e.get("provenance", "unknown")
        if e.get("accession"):
            prov = f"{prov} {e['accession']}"
        evidence = (e.get("evidence") or "").strip()
        if len(evidence) > 140:
            evidence = evidence[:137].rstrip() + "…"
        detail = f"{prov}: '{evidence}'" if evidence else prov
        return f"{step['from']} {arrow} {step['to']} ({detail})"

    # ---------- internals ----------
    def _touching(self, node_id: str) -> list[dict]:
        """Every edge incident to node_id in its original orientation, once each."""
        out = [e for e in self._adj.get(node_id, []) if not e.get("_reversed")]
        return out + self._in.get(node_id, [])

    def _top(self, edges: list[dict], query_ticker: str) -> list[dict]:
        """Enrich, sort by weight (then provenance), one row per counterparty."""
        enriched = [self._enrich(e, query_ticker) for e in edges]
        enriched.sort(key=lambda e: (-e["weight"], _provenance_rank(e)))
        seen: set[str] = set()
        deduped = []
        for r in enriched:
            if r["other_ticker"] in seen:
                continue
            seen.add(r["other_ticker"])
            deduped.append(r)
        return deduped

    def _enrich(self, edge: dict, query_ticker: str) -> dict:
        """Add the 'other' node's metadata to an edge. other = whichever side isn't the query ticker."""
        other = edge["target"] if edge["source"] == query_ticker else edge["source"]
        node = self.nodes.get(other) or {}
        if not node and other in self.macro_factors:
            node = {"name": self.macro_factors[other].get("name", other)}
        return {
            **self._public(edge),
            "other_ticker": other,
            "other_name": node.get("name", other),
            "other_sector": node.get("gics_sector", ""),
            "other_sub_industry": node.get("gics_sub_industry", ""),
        }

    @staticmethod
    def _public(edge: dict) -> dict:
        return {k: v for k, v in edge.items() if not k.startswith("_")}


# ---------- process-wide instance ----------
_lock = threading.Lock()
_instance: KnowledgeGraph | None = None
_loaded_at: float = 0.0


def _db_configured() -> bool:
    try:
        from src.rag.config import uses_postgres

        return uses_postgres()
    except Exception:  # pragma: no cover — import problems should never take /context down
        return False


def _load_db_graph() -> KnowledgeGraph | None:
    """DB-backed graph, or None when Postgres is not configured, not seeded, or unreachable."""
    if not _db_configured():
        return None
    try:
        return KnowledgeGraph.from_db()
    except Exception as e:  # tables missing, connection refused, ...
        logger.warning(f"knowledge graph: DB load failed, falling back to JSON ({e.__class__.__name__}: {e})")
        return None


def _refresh_due() -> bool:
    return _db_configured() and (time.monotonic() - _loaded_at) > DB_REFRESH_SECONDS


def get_graph() -> KnowledgeGraph:
    """The shared graph. DB-backed when Postgres is configured and seeded (reloaded
    every DB_REFRESH_SECONDS so re-seeds and new ingestions show up), else JSON."""
    global _instance, _loaded_at
    if _instance is not None and not _refresh_due():
        return _instance
    with _lock:
        if _instance is None or _refresh_due():
            graph = _load_db_graph()
            if graph is None:
                graph = _instance if (_instance is not None and _instance.backend == "json") else KnowledgeGraph.from_json()
            elif _instance is None or _instance.backend != "db":
                logger.info(f"knowledge graph: serving DB-backed graph ({len(graph.nodes)} nodes, {len(graph.edges)} edges)")
            _instance = graph
            _loaded_at = time.monotonic()
    return _instance


def reset_graph() -> None:
    """Forget the cached instance (tests, and scripts that just re-seeded the DB)."""
    global _instance, _loaded_at
    with _lock:
        _instance = None
        _loaded_at = 0.0
