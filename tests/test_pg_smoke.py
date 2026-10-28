"""Postgres + pgvector smoke tests — P2-A acceptance (docs/PROJECT2-PLAN.md).

Run against the docker-compose database:

    docker compose up -d db
    PG_TEST_URL=postgresql+psycopg://stockify:stockify_dev@localhost:5432/stockify uv run pytest -m pg

They skip without PG_TEST_URL and fail (not skip) when it is set but unreachable.
Every test runs inside a transaction that conftest rolls back.
"""

import json

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.pg

ACCESSION = "0000000000-26-000001"
DIM = 768


def _halfvec_literal(values: list[float]) -> str:
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


def _one_hot(pos: int) -> list[float]:
    v = [0.0] * DIM
    v[pos] = 1.0
    return v


def _insert_filing_doc(conn) -> None:
    conn.execute(
        text(
            "INSERT INTO filing_docs (accession, ticker, cik, form, source_url, corpus, embed_model, embed_dim) "
            "VALUES (:acc, 'TEST', '0000000000', '10-K', 'https://www.sec.gov/test', 'test', 'gemini-embedding-001', :dim)"
        ),
        {"acc": ACCESSION, "dim": DIM},
    )


def _insert_chunk(conn, ord_: int, body: str, embedding: list[float]) -> None:
    conn.execute(
        text(
            "INSERT INTO filing_chunks (accession, ticker, corpus, section, ord, text, embedding) "
            "VALUES (:acc, 'TEST', 'test', 'item_7', :ord, :body, CAST(:emb AS halfvec(768)))"
        ),
        {"acc": ACCESSION, "ord": ord_, "body": body, "emb": _halfvec_literal(embedding)},
    )


def test_pgvector_extension_is_new_enough_for_halfvec(pg_conn):
    row = pg_conn.execute(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")).first()
    assert row is not None, "vector extension missing — the migration runs CREATE EXTENSION"
    major, minor = (int(x) for x in row[0].split(".")[:2])
    assert (major, minor) >= (0, 7), f"pgvector {row[0]} is too old; halfvec needs >= 0.7"


def test_migration_created_rag_tables(pg_conn):
    names = {r[0] for r in pg_conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))}
    assert {"kg_nodes", "kg_edges", "kg_facts", "filing_docs", "filing_chunks", "ask_log"} <= names

    indexes = {r[0] for r in pg_conn.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'filing_chunks'"))}
    assert {"ix_filing_chunks_embedding", "ix_filing_chunks_tsv"} <= indexes


def test_halfvec_insert_and_cosine_nearest_neighbor(pg_conn):
    _insert_filing_doc(pg_conn)
    for ord_, pos in enumerate((0, 1, 2)):
        _insert_chunk(pg_conn, ord_, f"chunk {pos}", _one_hot(pos))

    query = [0.0] * DIM
    query[1], query[2] = 0.9, 0.1  # closest to the chunk at position 1
    rows = pg_conn.execute(
        text(
            "SELECT ord, embedding <=> CAST(:q AS halfvec(768)) AS dist "
            "FROM filing_chunks WHERE corpus = 'test' ORDER BY dist LIMIT 3"
        ),
        {"q": _halfvec_literal(query)},
    ).all()

    assert [r[0] for r in rows] == [1, 2, 0]
    assert rows[0][1] < rows[1][1] < rows[2][1]
    assert rows[0][1] == pytest.approx(0.0, abs=1e-2)  # 0.9 vs 1.0 along one axis is near-identical


def test_tsvector_is_generated_and_searchable(pg_conn):
    _insert_filing_doc(pg_conn)
    _insert_chunk(pg_conn, 0, "Revenue increased 12% in fiscal 2025 driven by data center demand.", _one_hot(0))
    _insert_chunk(pg_conn, 1, "Our competitors include large technology companies.", _one_hot(1))

    hits = pg_conn.execute(
        text(
            "SELECT ord FROM filing_chunks "
            "WHERE corpus = 'test' AND tsv @@ websearch_to_tsquery('english', :q)"
        ),
        {"q": "revenue increased"},
    ).all()
    assert [r[0] for r in hits] == [0]


def test_kg_node_jsonb_props_and_edge_provenance(pg_conn):
    pg_conn.execute(
        text("INSERT INTO kg_nodes (id, type, name, props) VALUES ('TEST', 'company', 'Test Corp', CAST(:p AS jsonb))"),
        {"p": json.dumps({"gics_sector": "Information Technology", "aliases": ["Test"]})},
    )
    pg_conn.execute(text("INSERT INTO kg_nodes (id, type, name) VALUES ('org:acme', 'org', 'Acme Ltd')"))
    pg_conn.execute(
        text(
            "INSERT INTO kg_edges (src, dst, type, weight, source, accession, evidence, confidence) "
            "VALUES ('org:acme', 'TEST', 'supplies_to', 0.8, 'filing', :acc, 'Acme supplies substantially all of our widgets.', 'high')"
        ),
        {"acc": ACCESSION},
    )

    sector = pg_conn.execute(text("SELECT props->>'gics_sector' FROM kg_nodes WHERE id = 'TEST'")).scalar_one()
    assert sector == "Information Technology"

    edge = pg_conn.execute(
        text("SELECT src, dst, source, accession, evidence FROM kg_edges WHERE dst = 'TEST'")
    ).one()
    assert edge[0] == "org:acme" and edge[2] == "filing" and edge[3] == ACCESSION
    assert "widgets" in edge[4]

    # Deleting a node cascades to its edges.
    pg_conn.execute(text("DELETE FROM kg_nodes WHERE id = 'org:acme'"))
    assert pg_conn.execute(text("SELECT count(*) FROM kg_edges")).scalar_one() == 0


def test_ask_log_uses_native_array_and_jsonb(pg_conn):
    new_id = pg_conn.execute(
        text(
            "INSERT INTO ask_log (question, tickers, intent, citations, cost_usd) "
            "VALUES ('What is NVDA revenue?', :tickers, 'single_company', CAST(:cit AS jsonb), 0.001234) RETURNING id"
        ),
        {"tickers": ["NVDA", "AMD"], "cit": json.dumps([{"n": 1, "title": "NVIDIA 10-K FY2025"}])},
    ).scalar_one()

    row = pg_conn.execute(
        text("SELECT tickers, citations->0->>'title', cost_usd, created_at FROM ask_log WHERE id = :id"),
        {"id": new_id},
    ).one()
    assert list(row[0]) == ["NVDA", "AMD"]
    assert row[1] == "NVIDIA 10-K FY2025"
    assert float(row[2]) == pytest.approx(0.001234)
    assert row[3] is not None  # server default now()
