"""Knowledge graph ↔ Postgres (docs/PROJECT2-PLAN.md P2-B).

Tables (migrations 7b3e9d2c4a1f, c4d1e8a2f906):
    kg_nodes(id, type, name, props)
    kg_edges(id, src, dst, type, weight, source, accession, evidence, confidence, props, created_at)

- seed_graph() / seed_from_json(): idempotent upsert of the compiled JSON graph —
  company + macro nodes, curated + GICS edges (source = 'curated' | 'gics', the
  rationale as `evidence`, macro direction/override in `props`). Prunes curated/gics
  edges that disappeared from the JSON. Never deletes nodes: filing-derived edges
  and facts (P2-C/P2-D) hang off them.
- load_graph_data(): rows → the dict KnowledgeGraph expects, so
  KnowledgeGraph.from_db() exposes the same query API as the JSON graph.
- company_aliases() / normalize_company_name(): the name forms stored in
  props.aliases and used by P2-D entity linking.

Callers pass a SQLAlchemy Session or Connection and own the transaction.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

from src.knowledge_graph.graph import _GRAPH_PATH, MACRO_EDGE_TYPE, canonical_edges

MACRO_PREFIX = "macro:"
SEEDED_SOURCES = ("curated", "gics")  # edge sources this module owns


def macro_node_id(factor_id: str) -> str:
    return f"{MACRO_PREFIX}{factor_id}"


def factor_id_from_node(node_id: str) -> str:
    return node_id[len(MACRO_PREFIX):] if node_id.startswith(MACRO_PREFIX) else node_id


# ---------- company names ----------
_PAREN_RE = re.compile(r"\s*\(([^)]*)\)")
_CLASS_RE = re.compile(r"^class\s+[a-z]$", re.IGNORECASE)
_ACRONYM_RE = re.compile(r"^[A-Z0-9&.]{2,6}$")
_SUFFIXES = (
    r"(?:Inc|Incorporated|Corp|Corporation|Co|Company|Companies|plc|Ltd|Limited|LLC|LP|L\.P"
    r"|Holdings?|Group|N\.V|NV|S\.A|SA|SE|AG)"
)
_SUFFIX_RE = re.compile(rf"(?:\s*,)?\s+(?:&\s+)?{_SUFFIXES}\.?\s*$", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[^\w\s]")


def _clean(name: str) -> str:
    name = unicodedata.normalize("NFKC", name or "").replace(" ", " ")
    return re.sub(r"\s+", " ", name).strip()


def strip_corporate_suffixes(name: str) -> str:
    """'Block, Inc.' → 'Block'; 'Arthur J. Gallagher & Co.' → 'Arthur J. Gallagher';
    'Citizens Financial Group, Inc.' → 'Citizens Financial'. Case is kept."""
    name = _clean(name)
    while True:
        stripped = _SUFFIX_RE.sub("", name).rstrip(" ,")
        if stripped == name or not stripped:
            return name
        name = stripped


def company_aliases(name: str) -> list[str]:
    """Alternative surface forms of a company name, for props.aliases.

    'Taiwan Semiconductor Manufacturing (TSMC)' → ['TSMC', 'Taiwan Semiconductor Manufacturing']
    'Coca-Cola Company (The)' → ['Coca-Cola', 'Coca-Cola Company', 'The Coca-Cola Company']
    'Alphabet Inc. (Class A)' → ['Alphabet', 'Alphabet Inc.']
    The name itself is not repeated. Sorted for a stable seed.
    """
    name = _clean(name)
    base = _clean(_PAREN_RE.sub("", name))
    forms: set[str] = set()
    if base:
        forms.add(base)
        forms.add(strip_corporate_suffixes(base))
    for inner in _PAREN_RE.findall(name):
        inner = inner.strip()
        if not inner or _CLASS_RE.match(inner):
            continue
        if _ACRONYM_RE.match(inner):
            forms.add(inner)
        elif " " not in inner and base:  # '(The)', '(Eli)' → leading word
            forms.add(f"{inner} {base}")
    return sorted(f for f in forms if f and f != name and len(f) >= 2)


def normalize_company_name(name: str) -> str:
    """Matching key for entity linking: parentheticals and corporate suffixes removed,
    lower-cased, punctuation dropped. 'Apple Inc.' and 'APPLE, INC' → 'apple'."""
    base = strip_corporate_suffixes(_PAREN_RE.sub("", _clean(name)))
    return re.sub(r"\s+", " ", _PUNCT_RE.sub(" ", base)).strip().lower()


# ---------- JSON → rows ----------
def graph_rows(data: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """(node_rows, edge_rows, skipped_edges) ready for the upsert statements.
    `props` is already JSON-encoded. Edges whose endpoints are not nodes are skipped."""
    node_rows: list[dict] = []
    for ticker, node in data["nodes"].items():
        props = {
            k: node.get(k) for k in ("gics_sector", "gics_sub_industry", "sp500") if node.get(k) is not None
        }
        props["aliases"] = company_aliases(node.get("name") or ticker)
        node_rows.append({
            "id": ticker,
            "type": node.get("node_type") or "company",
            "name": node.get("name") or ticker,
            "props": json.dumps(props),
        })
    for factor_id, meta in data.get("macro_factors", {}).items():
        props = {"factor_id": factor_id}
        props.update({k: meta.get(k) for k in ("yfinance_ticker", "unit", "description") if meta.get(k) is not None})
        node_rows.append({
            "id": macro_node_id(factor_id),
            "type": "macro",
            "name": meta.get("name") or factor_id,
            "props": json.dumps(props),
        })
    node_ids = {r["id"] for r in node_rows}

    edge_rows: list[dict] = []
    skipped: list[dict] = []
    for e in canonical_edges(data["edges"]):
        dst = macro_node_id(e["target"]) if e["type"] == MACRO_EDGE_TYPE else e["target"]
        if e["source"] not in node_ids or dst not in node_ids:
            skipped.append(e)
            continue
        props = {k: e[k] for k in ("direction", "override") if k in e}
        edge_rows.append({
            "src": e["source"],
            "dst": dst,
            "type": e["type"],
            "weight": e["weight"],
            "source": e["provenance"],
            "evidence": e.get("evidence"),
            "props": json.dumps(props),
        })
    return node_rows, edge_rows, skipped


# ---------- seeding ----------
_UPSERT_NODE = text(
    """
    INSERT INTO kg_nodes (id, type, name, props)
    VALUES (:id, :type, :name, CAST(:props AS jsonb))
    ON CONFLICT (id) DO UPDATE SET
        type  = EXCLUDED.type,
        name  = EXCLUDED.name,
        props = kg_nodes.props || EXCLUDED.props
    """
)

# Conflict target = the partial unique index uq_kg_edges_no_accession (migration
# c4d1e8a2f906): the table's UNIQUE (src, dst, type, source, accession) never fires
# for curated/gics edges because their accession is NULL.
_UPSERT_EDGE = text(
    """
    INSERT INTO kg_edges (src, dst, type, weight, source, evidence, props)
    VALUES (:src, :dst, :type, :weight, :source, :evidence, CAST(:props AS jsonb))
    ON CONFLICT (src, dst, type, source) WHERE accession IS NULL DO UPDATE SET
        weight   = EXCLUDED.weight,
        evidence = EXCLUDED.evidence,
        props    = EXCLUDED.props
    """
)

_COUNT_SEEDED_NODES = text("SELECT count(*) FROM kg_nodes WHERE type IN ('company', 'macro')")
_COUNT_SEEDED_EDGES = text(
    "SELECT count(*) FROM kg_edges WHERE accession IS NULL AND source IN ('curated', 'gics')"
)
_SELECT_SEEDED_EDGE_KEYS = text(
    "SELECT id, src, dst, type, source FROM kg_edges WHERE accession IS NULL AND source IN ('curated', 'gics')"
)
_DELETE_EDGES = text("DELETE FROM kg_edges WHERE id = ANY(:ids)")


@dataclass
class SeedReport:
    nodes: int = 0
    nodes_new: int = 0
    nodes_by_type: dict[str, int] = field(default_factory=dict)
    edges: int = 0
    edges_new: int = 0
    edges_pruned: int = 0
    edges_skipped: int = 0
    edges_by_source: dict[str, int] = field(default_factory=dict)
    edges_by_type: dict[str, int] = field(default_factory=dict)
    skipped_examples: list[str] = field(default_factory=list)
    built_at: str | None = None
    dry_run: bool = False

    def summary(self) -> str:
        lines = [
            f"{'Would seed' if self.dry_run else 'Seeded'} knowledge graph"
            + (f" (JSON built {self.built_at})" if self.built_at else ""),
            f"  nodes : {self.nodes}" + ("" if self.dry_run else f" ({self.nodes_new} new)")
            + "  " + ", ".join(f"{k}={v}" for k, v in sorted(self.nodes_by_type.items())),
            f"  edges : {self.edges}" + ("" if self.dry_run else f" ({self.edges_new} new, {self.edges_pruned} pruned)")
            + "  " + ", ".join(f"{k}={v}" for k, v in sorted(self.edges_by_source.items())),
            "          " + ", ".join(f"{k}={v}" for k, v in sorted(self.edges_by_type.items())),
        ]
        if self.edges_skipped:
            lines.append(
                f"  skipped: {self.edges_skipped} edge(s) whose endpoint is not a node: "
                + ", ".join(self.skipped_examples)
                + (" …" if self.edges_skipped > len(self.skipped_examples) else "")
            )
        return "\n".join(lines)


def plan_seed(data: dict) -> tuple[SeedReport, list[dict], list[dict]]:
    """Rows + a report, without touching a database (used by --dry-run)."""
    node_rows, edge_rows, skipped = graph_rows(data)
    report = SeedReport(
        nodes=len(node_rows),
        nodes_by_type=dict(Counter(r["type"] for r in node_rows)),
        edges=len(edge_rows),
        edges_skipped=len(skipped),
        skipped_examples=[f"{e['source']} -{e['type']}-> {e['target']}" for e in skipped[:3]],
        edges_by_source=dict(Counter(r["source"] for r in edge_rows)),
        edges_by_type=dict(Counter(r["type"] for r in edge_rows)),
        built_at=(data.get("metadata") or {}).get("built_at"),
        dry_run=True,
    )
    return report, node_rows, edge_rows


def seed_graph(conn, data: dict, *, prune: bool = True) -> SeedReport:
    """Upsert the compiled graph into kg_nodes / kg_edges. Idempotent: a second run
    changes nothing and keeps every edge id. With `prune`, curated/gics edges that are
    no longer in `data` are deleted (filing edges are never touched)."""
    report, node_rows, edge_rows = plan_seed(data)
    report.dry_run = False

    nodes_before = conn.execute(_COUNT_SEEDED_NODES).scalar_one()
    edges_before = conn.execute(_COUNT_SEEDED_EDGES).scalar_one()

    if node_rows:
        conn.execute(_UPSERT_NODE, node_rows)
    if edge_rows:
        conn.execute(_UPSERT_EDGE, edge_rows)

    if prune:
        wanted = {(r["src"], r["dst"], r["type"], r["source"]) for r in edge_rows}
        stale = [
            row.id
            for row in conn.execute(_SELECT_SEEDED_EDGE_KEYS)
            if (row.src, row.dst, row.type, row.source) not in wanted
        ]
        if stale:
            conn.execute(_DELETE_EDGES, {"ids": stale})
        report.edges_pruned = len(stale)

    nodes_after = conn.execute(_COUNT_SEEDED_NODES).scalar_one()
    edges_after = conn.execute(_COUNT_SEEDED_EDGES).scalar_one()
    report.nodes_new = max(0, nodes_after - nodes_before)
    report.edges_new = max(0, edges_after + report.edges_pruned - edges_before)
    return report


def seed_from_json(conn, path: Path = _GRAPH_PATH, *, prune: bool = True) -> SeedReport:
    with open(path) as f:
        data = json.load(f)
    return seed_graph(conn, data, prune=prune)


def is_seeded(conn) -> bool:
    return bool(conn.execute(text("SELECT EXISTS (SELECT 1 FROM kg_nodes WHERE type = 'company')")).scalar_one())


# ---------- loading ----------
_SELECT_NODES = text("SELECT id, type, name, props FROM kg_nodes WHERE type <> 'filing' ORDER BY id")
# Insertion order (= JSON order at seed time) keeps tie-breaking identical to the JSON graph.
_SELECT_EDGES = text(
    "SELECT id, src, dst, type, weight, source, accession, evidence, confidence, props "
    "FROM kg_edges WHERE type <> 'filed' ORDER BY id"
)


def _props(value: Any) -> dict:
    if value is None:
        return {}
    if isinstance(value, (str, bytes)):
        return json.loads(value)
    return dict(value)


def load_graph_data(conn=None) -> dict | None:
    """The {metadata, nodes, edges, macro_factors} dict KnowledgeGraph takes, read from
    Postgres. None when no company node exists (not seeded). Filing nodes and `filed`
    edges are left out: they are not relationships."""
    if conn is None:
        from src.db import SessionLocal

        with SessionLocal() as session:
            return _load(session)
    return _load(conn)


def _load(conn) -> dict | None:
    nodes: dict[str, dict] = {}
    macro_factors: dict[str, dict] = {}
    for row in conn.execute(_SELECT_NODES):
        props = _props(row.props)
        if row.type == "macro":
            factor_id = props.get("factor_id") or factor_id_from_node(row.id)
            macro_factors[factor_id] = {
                "name": row.name,
                **{k: props.get(k) for k in ("yfinance_ticker", "unit", "description")},
            }
        else:
            nodes[row.id] = {**props, "ticker": row.id, "name": row.name, "node_type": row.type}
    if not any(n["node_type"] == "company" for n in nodes.values()):
        return None

    edges: list[dict] = []
    for row in conn.execute(_SELECT_EDGES):
        props = _props(row.props)
        target = factor_id_from_node(row.dst) if row.dst.startswith(MACRO_PREFIX) else row.dst
        edges.append({
            **props,
            "edge_id": row.id,
            "source": row.src,
            "target": target,
            "type": row.type,
            "weight": row.weight,
            "label": row.evidence or "",
            "provenance": row.source,
            "evidence": row.evidence,
            "accession": row.accession,
            "confidence": row.confidence,
        })

    return {
        "metadata": {
            "backend": "db",
            "loaded_at": datetime.now(timezone.utc).isoformat(),
            "node_count": len(nodes) + len(macro_factors),
            "edge_count": len(edges),
        },
        "nodes": nodes,
        "edges": edges,
        "macro_factors": macro_factors,
    }
