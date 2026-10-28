"""Knowledge graph in Postgres — P2-B acceptance (docs/PROJECT2-PLAN.md).

    docker compose up -d db
    PG_TEST_URL=postgresql+psycopg://stockify:stockify_dev@localhost:5432/stockify uv run pytest -m pg

Every test runs inside a transaction that conftest rolls back, so seeding the
full graph here never leaks into the development database.
"""

import copy
import json

import pytest
from sqlalchemy import text

from src.knowledge_graph.graph import _GRAPH_PATH, KnowledgeGraph, canonical_edges
from src.rag import kg_store

pytestmark = pytest.mark.pg

SAMPLE_TICKERS = ("NVDA", "AAPL", "QCOM", "TSM", "ASML", "XOM", "JPM", "NEE", "NEM", "WDAY", "MO")


@pytest.fixture(scope="module")
def json_data() -> dict:
    with open(_GRAPH_PATH) as f:
        return json.load(f)


@pytest.fixture(autouse=True)
def _empty_graph(pg_session):
    """The compose database doubles as the dev DB and may already be seeded. Clear the
    graph inside this test's transaction (rolled back afterwards) so counts are exact."""
    for table in ("kg_facts", "kg_edges", "kg_nodes"):
        pg_session.execute(text(f"DELETE FROM {table}"))
    pg_session.commit()


@pytest.fixture
def seeded(pg_session, json_data):
    report = kg_store.seed_graph(pg_session, json_data)
    pg_session.commit()
    return report


def _edge_key(e: dict) -> tuple:
    return (e["source"], e["target"], e["type"], e["provenance"], round(e["weight"], 6), e["label"])


def _rows(graph: KnowledgeGraph, ticker: str) -> dict:
    """Backend-independent view of the query API for one ticker."""
    pick = lambda r: (r["other_ticker"], r["type"], round(r["weight"], 6), r["provenance"], r["label"])  # noqa: E731
    return {
        "competitors": [pick(r) for r in graph.get_competitors(ticker, max_results=10)],
        "suppliers": [pick(r) for r in graph.get_suppliers(ticker)],
        "customers": [pick(r) for r in graph.get_customers(ticker)],
        "macro": [
            (m["target"], m["direction"], round(m["weight"], 6), m["factor_name"], m["yfinance_ticker"], m["label"])
            for m in graph.get_macro_sensitivity(ticker)
        ],
        "peers": graph.get_sector_peers(ticker),
        "node": graph.get_node(ticker) and {
            k: graph.get_node(ticker)[k] for k in ("ticker", "name", "gics_sector", "gics_sub_industry", "sp500")
        },
    }


# ---------- schema ----------
def test_migration_added_edge_props_and_upsert_index(pg_conn):
    cols = {
        r[0]
        for r in pg_conn.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = 'kg_edges'")
        )
    }
    assert "props" in cols
    indexes = {r[0] for r in pg_conn.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'kg_edges'"))}
    assert "uq_kg_edges_no_accession" in indexes


# ---------- seeding ----------
def test_not_seeded_means_no_db_graph(pg_session):
    assert kg_store.is_seeded(pg_session) is False
    assert kg_store.load_graph_data(pg_session) is None
    assert KnowledgeGraph.from_db(pg_session) is None


def test_seed_writes_every_node_and_edge(pg_session, seeded, json_data):
    expected_edges = len(kg_store.graph_rows(json_data)[1])
    assert seeded.nodes == len(json_data["nodes"]) + len(json_data["macro_factors"])
    assert seeded.nodes_new == seeded.nodes
    assert seeded.edges == expected_edges and seeded.edges_new == expected_edges
    assert seeded.edges_pruned == 0
    assert set(seeded.edges_by_source) == {"curated", "gics"}

    assert pg_session.execute(text("SELECT count(*) FROM kg_nodes")).scalar_one() == seeded.nodes
    assert pg_session.execute(text("SELECT count(*) FROM kg_edges")).scalar_one() == seeded.edges
    assert kg_store.is_seeded(pg_session) is True

    # provenance columns are filled, filing columns are not
    row = pg_session.execute(
        text("SELECT source, evidence, accession, confidence, props FROM kg_edges WHERE src = 'ASML' AND dst = 'TSM'")
    ).one()
    assert row.source == "curated" and "EUV" in row.evidence
    assert row.accession is None and row.confidence is None and row.props == {}

    macro = pg_session.execute(
        text("SELECT props, evidence FROM kg_edges WHERE src = 'NEM' AND dst = 'macro:GOLD'")
    ).one()
    assert macro.props == {"direction": "positive", "override": True}


def test_seed_stores_gics_fields_and_aliases_in_props(pg_session, seeded):
    props = pg_session.execute(text("SELECT props FROM kg_nodes WHERE id = 'AAPL'")).scalar_one()
    assert props["gics_sector"] == "Information Technology" and props["sp500"] is True
    assert "Apple" in props["aliases"]
    assert "TSMC" in pg_session.execute(text("SELECT props->'aliases' FROM kg_nodes WHERE id = 'TSM'")).scalar_one()
    macro = pg_session.execute(text("SELECT type, name, props FROM kg_nodes WHERE id = 'macro:WTI_CRUDE_OIL'")).one()
    assert macro.type == "macro" and macro.props["yfinance_ticker"] == "CL=F"


def test_seed_is_idempotent_and_keeps_edge_ids(pg_session, seeded, json_data):
    ids_before = {r[0] for r in pg_session.execute(text("SELECT id FROM kg_edges"))}

    again = kg_store.seed_graph(pg_session, json_data)
    pg_session.commit()

    assert again.nodes_new == 0 and again.edges_new == 0 and again.edges_pruned == 0
    assert pg_session.execute(text("SELECT count(*) FROM kg_edges")).scalar_one() == seeded.edges
    assert {r[0] for r in pg_session.execute(text("SELECT id FROM kg_edges"))} == ids_before


def test_seed_updates_weights_and_prunes_edges_that_left_the_json(pg_session, seeded, json_data):
    # A filing edge (P2-D) must survive re-seeding untouched.
    pg_session.execute(text("INSERT INTO kg_nodes (id, type, name) VALUES ('org:foxconn', 'org', 'Foxconn')"))
    pg_session.execute(
        text(
            "INSERT INTO kg_edges (src, dst, type, weight, source, accession, evidence, confidence) "
            "VALUES ('org:foxconn', 'AAPL', 'supplies_to', 0.85, 'filing', '0000320193-25-000079', 'quote', 'medium')"
        )
    )
    pg_session.commit()

    data = copy.deepcopy(json_data)
    idx = next(i for i, e in enumerate(data["edges"]) if (e["source"], e["target"], e["type"]) == ("ASML", "TSM", "supplies_to"))
    removed = data["edges"].pop(idx)
    tsm_nvda = next(e for e in data["edges"] if (e["source"], e["target"], e["type"]) == ("TSM", "NVDA", "supplies_to"))
    tsm_nvda["weight"] = 0.42
    tsm_nvda["label"] = "updated rationale"
    nvda_id_before = pg_session.execute(
        text("SELECT id FROM kg_edges WHERE src = 'TSM' AND dst = 'NVDA' AND type = 'supplies_to'")
    ).scalar_one()

    report = kg_store.seed_graph(pg_session, data)
    pg_session.commit()

    assert report.edges_pruned == 1 and report.edges_new == 0
    assert pg_session.execute(
        text("SELECT count(*) FROM kg_edges WHERE src = :s AND dst = :d AND type = 'supplies_to'"),
        {"s": removed["source"], "d": removed["target"]},
    ).scalar_one() == 0
    updated = pg_session.execute(
        text("SELECT id, weight, evidence FROM kg_edges WHERE src = 'TSM' AND dst = 'NVDA' AND type = 'supplies_to'")
    ).one()
    assert updated.id == nvda_id_before and updated.weight == pytest.approx(0.42) and updated.evidence == "updated rationale"
    assert pg_session.execute(text("SELECT count(*) FROM kg_edges WHERE source = 'filing'")).scalar_one() == 1
    assert pg_session.execute(text("SELECT count(*) FROM kg_nodes WHERE id = 'org:foxconn'")).scalar_one() == 1


def test_seed_from_json_reads_the_checked_in_file(pg_session):
    report = kg_store.seed_from_json(pg_session, prune=False)
    assert report.nodes > 500 and report.edges > 3000


# ---------- parity: DB graph == JSON graph ----------
def test_db_graph_matches_json_graph(pg_session, seeded, json_data):
    db_graph = KnowledgeGraph.from_db(pg_session)
    json_graph = KnowledgeGraph.from_json()
    assert db_graph is not None and db_graph.backend == "db"

    assert set(db_graph.nodes) == set(json_graph.nodes)
    assert set(db_graph.macro_factors) == set(json_graph.macro_factors)
    for factor_id, meta in json_graph.macro_factors.items():
        assert db_graph.macro_factors[factor_id]["yfinance_ticker"] == meta["yfinance_ticker"]
        assert db_graph.macro_factors[factor_id]["name"] == meta["name"]

    # Every curated / GICS edge the seed can store (endpoints exist) is in the DB, nothing else.
    _, expected_rows, _ = kg_store.graph_rows(json_data)
    expected = {
        (r["src"], kg_store.factor_id_from_node(r["dst"]), r["type"], r["source"], round(r["weight"], 6), r["evidence"] or "")
        for r in expected_rows
    }
    assert {_edge_key(e) for e in db_graph.edges} == expected
    assert all(isinstance(e["edge_id"], int) for e in db_graph.edges)

    for ticker in SAMPLE_TICKERS:
        assert _rows(db_graph, ticker) == _rows(json_graph, ticker), ticker


def test_db_graph_exposes_provenance_on_query_results(pg_session, seeded):
    g = KnowledgeGraph.from_db(pg_session)
    comps = g.get_competitors("WDAY")
    assert comps[0]["provenance"] == "curated" and comps[0]["evidence"]
    assert any(c["provenance"] == "gics" for c in comps)
    assert g.get_edge(comps[0]["edge_id"])["target"] in {comps[0]["other_ticker"], "WDAY"}

    macro = g.get_macro_sensitivity("NEE")
    by_factor = {m["target"]: m for m in macro}
    assert by_factor["US_10Y_YIELD"]["direction"] == "inverse" and by_factor["US_10Y_YIELD"]["override"] is True

    paths = g.paths("ASML", "NVDA")
    assert paths[0]["nodes"] == ["ASML", "TSM", "NVDA"]
    assert all(s["edge"]["edge_id"] for s in paths[0]["steps"])


def test_db_graph_includes_filing_edges_but_not_filing_nodes(pg_session, seeded):
    pg_session.execute(
        text("INSERT INTO kg_nodes (id, type, name, props) VALUES ('filing:0000320193-25-000079', 'filing', 'AAPL 10-K FY2025', CAST(:p AS jsonb))"),
        {"p": json.dumps({"form": "10-K"})},
    )
    pg_session.execute(text("INSERT INTO kg_nodes (id, type, name) VALUES ('org:foxconn', 'org', 'Hon Hai Precision Industry (Foxconn)')"))
    pg_session.execute(
        text(
            "INSERT INTO kg_edges (src, dst, type, weight, source, accession) "
            "VALUES ('AAPL', 'filing:0000320193-25-000079', 'filed', 1.0, 'filing', '0000320193-25-000079')"
        )
    )
    pg_session.execute(
        text(
            "INSERT INTO kg_edges (src, dst, type, weight, source, accession, evidence, confidence) "
            "VALUES ('org:foxconn', 'AAPL', 'supplies_to', 0.85, 'filing', '0000320193-25-000079', "
            "'outsourcing partners located primarily in Asia', 'medium')"
        )
    )
    pg_session.commit()

    g = KnowledgeGraph.from_db(pg_session)
    assert "filing:0000320193-25-000079" not in g.nodes
    assert g.get_node("org:foxconn")["node_type"] == "org"
    assert not any(e["type"] == "filed" for e in g.edges)

    suppliers = {s["other_ticker"]: s for s in g.get_suppliers("AAPL")}
    fox = suppliers["org:foxconn"]
    assert fox["provenance"] == "filing" and fox["accession"] == "0000320193-25-000079"
    assert fox["evidence"].startswith("outsourcing partners") and fox["label"] == fox["evidence"]
    assert fox["other_name"].startswith("Hon Hai")
