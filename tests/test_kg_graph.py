"""KnowledgeGraph internals that need no database (docs/PROJECT2-PLAN.md P2-B).

- canonical_edges: provenance, major_customer → supplies_to, duplicate collapsing
- query API on a toy graph with curated, GICS and filing-sourced edges
- neighbors() / paths() traversal with per-edge provenance
- get_graph() backend selection: DB when available, JSON fallback otherwise
- company name normalization / aliases used by the seed and entity linking
"""

import copy

import pytest

from src.knowledge_graph import graph as graph_module
from src.knowledge_graph.graph import KnowledgeGraph, canonical_edges, get_graph, reset_graph
from src.rag import kg_store

ACCESSION = "0000320193-25-000079"

TOY = {
    "metadata": {"built_at": "2026-10-28T00:00:00+00:00"},
    "nodes": {
        "AAPL": {"ticker": "AAPL", "name": "Apple Inc.", "gics_sector": "Information Technology",
                 "gics_sub_industry": "Technology Hardware, Storage & Peripherals", "sp500": True},
        "TSM": {"ticker": "TSM", "name": "Taiwan Semiconductor Manufacturing (TSMC)",
                "gics_sector": "Information Technology", "gics_sub_industry": "Semiconductors", "sp500": False},
        "ASML": {"ticker": "ASML", "name": "ASML Holding", "gics_sector": "Information Technology",
                 "gics_sub_industry": "Semiconductor Equipment", "sp500": False},
        "QCOM": {"ticker": "QCOM", "name": "Qualcomm", "gics_sector": "Information Technology",
                 "gics_sub_industry": "Semiconductors", "sp500": True},
        "AMD": {"ticker": "AMD", "name": "Advanced Micro Devices", "gics_sector": "Information Technology",
                "gics_sub_industry": "Semiconductors", "sp500": True},
        "org:foxconn": {"ticker": "org:foxconn", "name": "Hon Hai Precision Industry (Foxconn)", "node_type": "org"},
    },
    "macro_factors": {
        "US_10Y_YIELD": {"name": "US 10-Year Treasury Yield", "yfinance_ticker": "^TNX", "unit": "% yield",
                         "description": "Benchmark rate."},
    },
    "edges": [
        {"source": "ASML", "target": "TSM", "type": "supplies_to", "weight": 1.0,
         "label": "Sole supplier of EUV lithography machines", "auto_generated": False},
        {"source": "TSM", "target": "AAPL", "type": "supplies_to", "weight": 0.9,
         "label": "TSMC fabricates Apple's A-series chips", "auto_generated": False},
        # The same relationship, as extracted from Apple's 10-K: filing provenance, with a quote.
        {"source": "TSM", "target": "AAPL", "type": "supplies_to", "weight": 0.95, "provenance": "filing",
         "accession": ACCESSION, "evidence": "substantially all of our SoCs are manufactured by a single foundry",
         "confidence": "high", "edge_id": 501},
        # "AAPL is a major customer of QCOM" → canonical form is QCOM supplies_to AAPL ...
        {"source": "AAPL", "target": "QCOM", "type": "major_customer", "weight": 0.8,
         "label": "Apple is Qualcomm's largest 5G modem customer", "auto_generated": False},
        # ... which collides with this weaker curated edge → one edge, weight 0.8.
        {"source": "QCOM", "target": "AAPL", "type": "supplies_to", "weight": 0.6,
         "label": "Qualcomm supplies 5G modems to iPhone", "auto_generated": False},
        {"source": "AMD", "target": "QCOM", "type": "competes_with", "weight": 0.5,
         "label": "Both in GICS sub-industry: Semiconductors", "auto_generated": True},
        {"source": "AMD", "target": "QCOM", "type": "competes_with", "weight": 0.7,
         "label": "Rivals in PC and mobile silicon", "auto_generated": False},
        {"source": "org:foxconn", "target": "AAPL", "type": "supplies_to", "weight": 0.85, "provenance": "filing",
         "accession": ACCESSION, "evidence": "outsourcing partners located primarily in Asia", "confidence": "medium",
         "edge_id": 502},
        {"source": "AAPL", "target": "US_10Y_YIELD", "type": "macro_sensitivity", "direction": "inverse",
         "weight": 0.85, "label": "Sector default: duration asset"},
        {"source": "AAPL", "target": "US_10Y_YIELD", "type": "macro_sensitivity", "direction": "inverse",
         "weight": 0.7, "label": "Company override: large cash pile offsets", "override": True},
    ],
}


@pytest.fixture
def toy() -> KnowledgeGraph:
    return KnowledgeGraph(copy.deepcopy(TOY), backend="test")


@pytest.fixture(autouse=True)
def _isolate_singleton():
    reset_graph()
    yield
    reset_graph()


# ---------- canonical_edges ----------
def test_canonical_edges_derive_provenance_and_evidence():
    edges = canonical_edges(copy.deepcopy(TOY["edges"]))
    by_key = {(e["source"], e["target"], e["type"], e["provenance"]): e for e in edges}

    gics = by_key[("AMD", "QCOM", "competes_with", "gics")]
    curated = by_key[("AMD", "QCOM", "competes_with", "curated")]
    assert gics["evidence"] == gics["label"] == "Both in GICS sub-industry: Semiconductors"
    assert curated["weight"] == 0.7
    assert "auto_generated" not in gics and "auto_generated" not in curated

    filing = by_key[("TSM", "AAPL", "supplies_to", "filing")]
    assert filing["accession"] == ACCESSION and filing["confidence"] == "high"
    assert filing["label"] == ""  # no human label; the evidence quote is the citation


def test_canonical_edges_flip_major_customer_and_collapse_duplicates():
    edges = canonical_edges(copy.deepcopy(TOY["edges"]))
    assert not any(e["type"] == "major_customer" for e in edges)

    qcom_aapl = [e for e in edges if (e["source"], e["target"], e["type"]) == ("QCOM", "AAPL", "supplies_to")]
    assert len(qcom_aapl) == 1
    assert qcom_aapl[0]["weight"] == 0.8  # the heavier of the two curated duplicates
    assert qcom_aapl[0]["label"].startswith("Apple is Qualcomm's largest")

    macro = [e for e in edges if e["type"] == "macro_sensitivity"]
    assert len(macro) == 1
    assert macro[0]["override"] is True and macro[0]["weight"] == 0.7  # override beats the heavier default


def test_canonical_edges_is_idempotent_and_order_preserving():
    once = canonical_edges(copy.deepcopy(TOY["edges"]))
    twice = canonical_edges(copy.deepcopy(once))
    assert twice == once
    assert [e["source"] for e in once][:2] == ["ASML", "TSM"]  # original order kept after dedupe


# ---------- query API on the toy graph ----------
def test_competitors_one_row_per_counterparty_prefers_heavier_edge(toy):
    comps = toy.get_competitors("AMD")
    assert [(c["other_ticker"], c["weight"], c["provenance"]) for c in comps] == [("QCOM", 0.7, "curated")]
    # symmetric: visible from the other side too
    assert [c["other_ticker"] for c in toy.get_competitors("QCOM")] == ["AMD"]


def test_suppliers_merge_curated_and_filing_edges(toy):
    rows = toy.get_suppliers("AAPL")
    assert [(r["other_ticker"], r["weight"], r["provenance"]) for r in rows] == [
        ("TSM", 0.95, "filing"),
        ("org:foxconn", 0.85, "filing"),
        ("QCOM", 0.8, "curated"),
    ]
    tsm = rows[0]
    assert tsm["accession"] == ACCESSION
    assert "single foundry" in tsm["evidence"]
    assert tsm["other_name"].startswith("Taiwan Semiconductor")
    assert rows[1]["other_name"].startswith("Hon Hai")


def test_customers_follow_outgoing_supplies_to(toy):
    assert [c["other_ticker"] for c in toy.get_customers("TSM")] == ["AAPL"]
    assert [c["other_ticker"] for c in toy.get_customers("QCOM")] == ["AAPL"]  # from the flipped major_customer
    assert toy.get_customers("AAPL") == []


def test_macro_sensitivity_uses_override_and_factor_metadata(toy):
    macros = toy.get_macro_sensitivity("aapl")
    assert len(macros) == 1
    m = macros[0]
    assert m["target"] == "US_10Y_YIELD" and m["direction"] == "inverse" and m["weight"] == 0.7
    assert m["factor_name"] == "US 10-Year Treasury Yield" and m["yfinance_ticker"] == "^TNX"
    assert m["provenance"] == "curated"


def test_get_node_and_get_edge(toy):
    assert toy.get_node("aapl")["name"] == "Apple Inc."
    assert toy.get_node("org:foxconn")["node_type"] == "org"  # namespaced ids are not upper-cased
    assert toy.get_node("ZZZZ") is None
    assert toy.get_edge(501)["source"] == "TSM"
    assert toy.get_edge(999) is None


def test_public_edges_hide_internal_keys(toy):
    for row in toy.get_suppliers("AAPL") + toy.get_competitors("AMD") + toy.neighbors("AAPL"):
        assert not any(k.startswith("_") for k in row)


# ---------- traversal ----------
def test_neighbors_cover_both_directions_and_report_relation_direction(toy):
    items = toy.neighbors("AAPL")
    by_other = {it["other_id"]: it for it in items}
    assert by_other["TSM"]["relation_direction"] == "in"  # TSM supplies AAPL
    assert by_other["US_10Y_YIELD"]["relation_direction"] == "out"
    assert by_other["US_10Y_YIELD"]["other_name"] == "US 10-Year Treasury Yield"
    assert [it["weight"] for it in items] == sorted((it["weight"] for it in items), reverse=True)

    assert toy.neighbors("QCOM", types=["competes_with"])[0]["relation_direction"] == "both"
    assert {it["type"] for it in toy.neighbors("AAPL", types=["supplies_to"])} == {"supplies_to"}
    assert len(toy.neighbors("AAPL", k=2)) == 2
    # a macro factor is a node too: who is sensitive to it?
    assert [it["other_id"] for it in toy.neighbors("US_10Y_YIELD")] == ["AAPL"]


def test_neighbors_do_not_double_count_symmetric_or_duplicate_edges(toy):
    items = toy.neighbors("AMD")
    assert len(items) == 2  # curated + gics competes_with to QCOM, each once
    assert {it["provenance"] for it in items} == {"curated", "gics"}


def test_paths_two_hops_with_provenance_ranking(toy):
    paths = toy.paths("ASML", "AAPL", max_hops=2)
    assert paths, "ASML → TSM → AAPL should be found"
    best = paths[0]
    assert best["hops"] == 2 and best["nodes"] == ["ASML", "TSM", "AAPL"]
    # Two parallel TSM→AAPL edges exist; the filing-sourced one ranks first.
    assert best["steps"][1]["edge"]["provenance"] == "filing"
    assert best["steps"][1]["edge"]["accession"] == ACCESSION
    assert paths[1]["steps"][1]["edge"]["provenance"] == "curated"
    assert best["steps"][0]["traversed"] == "forward" and best["steps"][1]["traversed"] == "forward"
    assert "ASML –supplies_to→ TSM" in best["summary"]
    assert f"filing {ACCESSION}" in best["summary"]
    assert best["score"] == pytest.approx(1.0 * 0.95)


def test_paths_can_traverse_edges_in_reverse_and_respect_hop_limit(toy):
    # AAPL ←supplies_to– QCOM –competes_with– AMD
    paths = toy.paths("AAPL", "AMD", max_hops=2)
    assert paths and paths[0]["nodes"] == ["AAPL", "QCOM", "AMD"]
    assert paths[0]["steps"][0]["traversed"] == "reverse"
    assert "AAPL ←supplies_to– QCOM" in paths[0]["summary"]

    assert toy.paths("ASML", "AAPL", max_hops=1) == []
    assert toy.paths("AAPL", "AAPL") == []
    assert toy.paths("AAPL", "ZZZZ") == []


def test_paths_exclude_macro_edges_unless_asked(toy):
    assert toy.paths("AAPL", "US_10Y_YIELD") == []  # factor ids are not company nodes


def test_paths_limit_k(toy):
    assert len(toy.paths("ASML", "AAPL", k=1)) == 1


# ---------- the checked-in JSON graph ----------
def test_json_graph_is_canonical():
    g = get_graph()
    assert g.backend == "json"
    assert {e["provenance"] for e in g.edges} == {"curated", "gics"}
    assert not any(e["type"] == "major_customer" for e in g.edges)
    assert all(e["evidence"] for e in g.edges if e["provenance"] == "gics")
    # major_customer edges now surface as customers of the supplier
    assert "AAPL" in {c["other_ticker"] for c in g.get_customers("QCOM")}


def test_json_graph_competitors_never_repeat_a_counterparty():
    g = get_graph()
    for ticker in ("WDAY", "NVDA", "MSFT", "JPM", "XOM"):
        others = [c["other_ticker"] for c in g.get_competitors(ticker, max_results=20)]
        assert len(others) == len(set(others)), ticker


def test_json_graph_two_hop_supply_chain_path():
    g = get_graph()
    paths = g.paths("ASML", "NVDA")
    assert paths and paths[0]["nodes"] == ["ASML", "TSM", "NVDA"]
    assert all(s["edge"]["provenance"] == "curated" for s in paths[0]["steps"])


# ---------- get_graph() backend selection ----------
def test_get_graph_falls_back_to_json_when_db_has_no_graph(monkeypatch):
    monkeypatch.setattr(graph_module, "_db_configured", lambda: True)
    monkeypatch.setattr(graph_module.KnowledgeGraph, "from_db", classmethod(lambda cls, session=None: None))
    g = get_graph()
    assert g.backend == "json"
    assert get_graph() is g


def test_get_graph_falls_back_to_json_when_db_load_raises(monkeypatch):
    monkeypatch.setattr(graph_module, "_db_configured", lambda: True)

    def boom(cls, session=None):
        raise RuntimeError("relation \"kg_nodes\" does not exist")

    monkeypatch.setattr(graph_module.KnowledgeGraph, "from_db", classmethod(boom))
    assert get_graph().backend == "json"


def test_get_graph_serves_db_graph_and_refreshes_after_ttl(monkeypatch):
    monkeypatch.setattr(graph_module, "_db_configured", lambda: True)
    db_graph = KnowledgeGraph(copy.deepcopy(TOY), backend="db")
    monkeypatch.setattr(graph_module.KnowledgeGraph, "from_db", classmethod(lambda cls, session=None: db_graph))

    g = get_graph()
    assert g is db_graph and g.backend == "db"
    assert get_graph() is db_graph  # cached

    # after the TTL a reload happens; a DB that went away keeps the last good graph? No:
    # it falls back to JSON, since the DB graph may be stale.
    monkeypatch.setattr(graph_module, "_loaded_at", -1e9)
    monkeypatch.setattr(graph_module.KnowledgeGraph, "from_db", classmethod(lambda cls, session=None: None))
    assert get_graph().backend == "json"


def test_get_graph_never_touches_db_without_postgres(monkeypatch):
    monkeypatch.setattr(graph_module, "_db_configured", lambda: False)

    def boom(cls, session=None):
        raise AssertionError("from_db must not be called")

    monkeypatch.setattr(graph_module.KnowledgeGraph, "from_db", classmethod(boom))
    assert get_graph().backend == "json"


# ---------- names and aliases ----------
@pytest.mark.parametrize(
    "name, expected",
    [
        ("Apple Inc.", ["Apple"]),
        ("Alphabet Inc. (Class A)", ["Alphabet", "Alphabet Inc."]),
        ("Coca-Cola Company (The)", ["Coca-Cola", "Coca-Cola Company", "The Coca-Cola Company"]),
        ("Taiwan Semiconductor Manufacturing (TSMC)", ["TSMC", "Taiwan Semiconductor Manufacturing"]),
        ("Arthur J. Gallagher & Co.", ["Arthur J. Gallagher"]),
        ("Block, Inc.", ["Block"]),
        ("Lilly (Eli)", ["Eli Lilly", "Lilly"]),
        ("SAP SE", ["SAP"]),
        ("Aon plc", ["Aon"]),
        ("NVIDIA", []),
        ("3M", []),
    ],
)
def test_company_aliases(name, expected):
    assert kg_store.company_aliases(name) == expected


@pytest.mark.parametrize(
    "name, key",
    [
        ("Apple Inc.", "apple"),
        ("APPLE, INC", "apple"),
        ("Taiwan Semiconductor Manufacturing Co., Ltd.", "taiwan semiconductor manufacturing"),
        ("Hon Hai Precision Industry Co. Ltd.", "hon hai precision industry"),
        ("Micron Technology, Inc.", "micron technology"),
        ("J.M. Smucker Company (The)", "j m smucker"),
        ("Costco Wholesale", "costco wholesale"),  # 'Co' inside a word is not a suffix
    ],
)
def test_normalize_company_name(name, key):
    assert kg_store.normalize_company_name(name) == key


# ---------- seed planning (no DB) ----------
def test_graph_rows_shape_and_skips_dangling_edges():
    data = copy.deepcopy(TOY)
    data["edges"].append({"source": "BRK.B", "target": "US_10Y_YIELD", "type": "macro_sensitivity",
                          "direction": "positive", "weight": 0.7, "label": "typo: node is BRK-B"})
    node_rows, edge_rows, skipped = kg_store.graph_rows(data)

    assert {r["id"] for r in node_rows} == set(TOY["nodes"]) | {"macro:US_10Y_YIELD"}
    by_id = {r["id"]: r for r in node_rows}
    assert by_id["org:foxconn"]["type"] == "org"
    assert by_id["macro:US_10Y_YIELD"]["type"] == "macro"
    assert '"aliases": ["TSMC", "Taiwan Semiconductor Manufacturing"]' in by_id["TSM"]["props"]

    assert [e["source"] for e in skipped] == ["BRK.B"]
    macro_rows = [r for r in edge_rows if r["type"] == "macro_sensitivity"]
    assert macro_rows == [{
        "src": "AAPL", "dst": "macro:US_10Y_YIELD", "type": "macro_sensitivity", "weight": 0.7,
        "source": "curated", "evidence": "Company override: large cash pile offsets",
        "props": '{"direction": "inverse", "override": true}',
    }]
    assert {r["source"] for r in edge_rows} == {"curated", "gics", "filing"}


def test_plan_seed_counts_the_real_graph():
    report, node_rows, edge_rows = kg_store.plan_seed(_json_data())
    assert report.dry_run
    assert report.nodes == len(node_rows) and report.nodes_by_type["company"] > 500 and report.nodes_by_type["macro"] == 10
    assert report.edges == len(edge_rows) > 3000
    assert set(report.edges_by_source) == {"curated", "gics"}
    assert "Would seed" in report.summary()


def _json_data() -> dict:
    import json

    with open(graph_module._GRAPH_PATH) as f:
        return json.load(f)
