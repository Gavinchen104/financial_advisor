"""Filings ingestion against Postgres + pgvector (P2-C acceptance). A fake embedder
produces deterministic unit vectors, so no API calls are made.

    PG_TEST_URL=postgresql+psycopg://stockify:stockify_dev@localhost:5432/stockify uv run pytest -m pg
"""

import hashlib
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text

from src.knowledge_graph.graph import KnowledgeGraph
from src.rag import ingest
from src.rag.edgar import Filing

pytestmark = pytest.mark.pg

FIXTURES = Path(__file__).parent / "fixtures" / "edgar"
K = Filing("ACME", "0000123456", "10-K", "0000123456-25-000001", "acme-20250927.htm", date(2025, 9, 27), date(2025, 11, 1), "Acme Widgets, Inc.")
Q = Filing("ACME", "0000123456", "10-Q", "0000123456-25-000002", "acme-20250628.htm", date(2025, 6, 28), date(2025, 8, 1), "Acme Widgets, Inc.")


class FakeEdgar:
    def __init__(self):
        self.html = {K.accession: (FIXTURES / "mini_10k.html").read_text(), Q.accession: (FIXTURES / "mini_10q.html").read_text()}

    def list_filings(self, ticker, form_counts=None):
        return [K, Q]

    def is_cached(self, filing):
        return True

    def fetch_document(self, filing, *, refetch=False):
        return self.html[filing.accession]

    def supplemental_documents(self, filing):
        return []


def fake_embed(texts: list[str]) -> list[list[float]]:
    """One-hot unit vectors: position = hash of the text."""
    out = []
    for t in texts:
        v = [0.0] * 768
        v[int(hashlib.sha1(t.encode()).hexdigest(), 16) % 768] = 1.0
        out.append(v)
    return out


@pytest.fixture(autouse=True)
def _empty_tables(pg_session):
    for table in ("filing_chunks", "filing_docs", "kg_facts", "kg_edges", "kg_nodes"):
        pg_session.execute(text(f"DELETE FROM {table}"))
    pg_session.commit()


def _count(conn, table: str, where: str = "TRUE", **params) -> int:
    return conn.execute(text(f"SELECT count(*) FROM {table} WHERE {where}"), params).scalar_one()


def test_ingest_filing_stores_doc_chunks_and_graph_links(pg_session):
    report = ingest.ingest_filing(pg_session, K, edgar=FakeEdgar(), embedder=fake_embed)
    pg_session.commit()
    assert report.status == "ingested", report.error
    assert report.n_chunks > 0 and not report.fallback

    doc = pg_session.execute(text("SELECT * FROM filing_docs WHERE accession = :a"), {"a": K.accession}).one()
    assert doc.ticker == "ACME" and doc.cik == "0000123456" and doc.form == "10-K" and doc.corpus == "live"
    assert doc.period_end == date(2025, 9, 27) and doc.filed_at == date(2025, 11, 1)
    assert doc.embed_model == "gemini-embedding-001" and doc.embed_dim == 768
    assert doc.n_chunks == report.n_chunks == _count(pg_session, "filing_chunks", "accession = :a", a=K.accession)
    assert doc.source_url.startswith("https://www.sec.gov/Archives/edgar/data/123456/000012345625000001/")

    sections = {r[0] for r in pg_session.execute(text("SELECT DISTINCT section FROM filing_chunks WHERE accession = :a"), {"a": K.accession})}
    assert sections == {"item_1", "item_1a", "item_7", "item_7a", "item_8"}
    ords = [r[0] for r in pg_session.execute(text("SELECT ord FROM filing_chunks WHERE accession = :a ORDER BY ord"), {"a": K.accession})]
    assert ords == list(range(report.n_chunks))

    # full-text index works on the stored text (generated tsvector)
    hits = pg_session.execute(
        text("SELECT section FROM filing_chunks WHERE accession = :a AND tsv @@ websearch_to_tsquery('english', 'single supplier')"),
        {"a": K.accession},
    ).all()
    assert hits and all(h[0] == "item_1a" for h in hits)

    # knowledge graph: a minimal company node (the company was not seeded), the filing node and the filed edge
    company = pg_session.execute(text("SELECT type, name, props FROM kg_nodes WHERE id = 'ACME'")).one()
    assert company.type == "company" and company.name == "Acme Widgets, Inc." and company.props["sp500"] is False
    assert "Acme Widgets" in company.props["aliases"]
    node = pg_session.execute(text("SELECT type, name, props FROM kg_nodes WHERE id = :id"), {"id": K.node_id}).one()
    assert node.type == "filing" and node.name == "ACME 10-K FY2025"
    assert node.props["form"] == "10-K" and node.props["period_end"] == "2025-09-27" and node.props["sections"] == report.sections
    assert node.props["split_mode"] == "item" and 0 < node.props["coverage"] <= 1
    edge = pg_session.execute(text("SELECT src, dst, type, source, accession FROM kg_edges WHERE dst = :id"), {"id": K.node_id}).one()
    assert (edge.src, edge.type, edge.source, edge.accession) == ("ACME", "filed", "filing", K.accession)

    # the in-memory graph loads the company but neither the filing node nor the filed edge
    graph = KnowledgeGraph.from_db(pg_session)
    assert graph is not None and "ACME" in graph.nodes and K.node_id not in graph.nodes
    assert not any(e["type"] == "filed" for e in graph.edges)


def test_second_run_skips_stored_accessions_and_replace_reingests(pg_session):
    first = ingest.ingest_filing(pg_session, K, edgar=FakeEdgar(), embedder=fake_embed)
    pg_session.commit()
    again = ingest.ingest_filing(pg_session, K, edgar=FakeEdgar(), embedder=fake_embed)
    assert first.status == "ingested" and again.status == "skipped"
    assert _count(pg_session, "filing_docs") == 1

    replaced = ingest.ingest_filing(pg_session, K, edgar=FakeEdgar(), embedder=fake_embed, replace=True)
    pg_session.commit()
    assert replaced.status == "ingested"
    assert _count(pg_session, "filing_docs") == 1
    assert _count(pg_session, "filing_chunks") == first.n_chunks
    assert _count(pg_session, "kg_edges", "type = 'filed'") == 1


def test_dry_run_writes_nothing(pg_session):
    report = ingest.ingest_filing(pg_session, Q, edgar=FakeEdgar(), embedder=fake_embed, dry_run=True)
    assert report.status == "dry-run" and report.n_chunks > 0
    assert _count(pg_session, "filing_docs") == 0 and _count(pg_session, "filing_chunks") == 0
    assert _count(pg_session, "kg_nodes") == 0


def test_seeded_company_node_is_kept_not_overwritten(pg_session):
    pg_session.execute(
        text("INSERT INTO kg_nodes (id, type, name, props) VALUES ('ACME', 'company', 'ACME from the S&P list', CAST(:p AS jsonb))"),
        {"p": '{"sp500": true, "gics_sector": "Industrials"}'},
    )
    ingest.ingest_filing(pg_session, Q, edgar=FakeEdgar(), embedder=fake_embed)
    pg_session.commit()
    row = pg_session.execute(text("SELECT name, props FROM kg_nodes WHERE id = 'ACME'")).one()
    assert row.name == "ACME from the S&P list" and row.props["sp500"] is True


def test_vector_search_finds_the_planted_chunk(pg_session):
    ingest.ingest_filing(pg_session, K, edgar=FakeEdgar(), embedder=fake_embed)
    pg_session.commit()
    target = pg_session.execute(
        text("SELECT id, text FROM filing_chunks WHERE accession = :a AND section = 'item_7a' ORDER BY ord LIMIT 1"), {"a": K.accession}
    ).one()
    qvec = ingest.vector_literal(fake_embed([target.text])[0])
    nearest = pg_session.execute(
        text("SELECT id FROM filing_chunks WHERE accession = :a ORDER BY embedding <=> CAST(:q AS halfvec(768)) LIMIT 1"),
        {"a": K.accession, "q": qvec},
    ).scalar_one()
    assert nearest == target.id
