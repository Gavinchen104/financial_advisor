"""Ingestion orchestration without a database: preparation, dry runs, error and
budget handling, the SQL issued by store_filing, universe file, summary (P2-C)."""

from datetime import date
from pathlib import Path

import pytest

from src.rag import config, ingest
from src.rag.edgar import Filing
from src.rag.llm import BudgetExceeded

FIXTURES = Path(__file__).parent / "fixtures" / "edgar"
HTML_10K = (FIXTURES / "mini_10k.html").read_text()
HTML_10Q = (FIXTURES / "mini_10q.html").read_text()

K = Filing("ACME", "0000123456", "10-K", "0000123456-25-000001", "acme-20250927.htm", date(2025, 9, 27), date(2025, 11, 1), "Acme Widgets, Inc.")
Q = Filing("ACME", "0000123456", "10-Q", "0000123456-25-000002", "acme-20250628.htm", date(2025, 6, 28), date(2025, 8, 1), "Acme Widgets, Inc.")


class FakeEdgar:
    """Offline stand-in for EdgarClient."""

    def __init__(self, filings=None, html=None, fail_for=()):
        self.filings = filings or {"ACME": [K, Q]}
        self.html = html or {K.accession: HTML_10K, Q.accession: HTML_10Q}
        self.fail_for = set(fail_for)
        self.requests = 0

    def list_filings(self, ticker, form_counts=None):
        if ticker in self.fail_for:
            raise RuntimeError("SEC says no")
        return self.filings.get(ticker, [])

    def is_cached(self, filing):
        return True

    def fetch_document(self, filing, *, refetch=False):
        return self.html[filing.accession]

    def supplemental_documents(self, filing):
        self.supplement_calls = getattr(self, "supplement_calls", 0) + 1
        return list(getattr(self, "siblings", []))


class StubResult:
    def __init__(self, first=None):
        self._first = first

    def first(self):
        return self._first


class StubConn:
    """Records every statement; `already_ingested` sees nothing stored."""

    def __init__(self):
        self.calls: list[tuple[str, object]] = []

    def execute(self, stmt, params=None):
        self.calls.append((str(stmt).strip(), params))
        return StubResult(first=None)


def test_prepare_filing_builds_chunks_from_sections():
    prepared = ingest.prepare_filing(K, HTML_10K)
    assert prepared.split.found == ["item_1", "item_1a", "item_7", "item_7a", "item_8"]
    assert prepared.chunks and {c.section for c in prepared.chunks} <= set(prepared.split.found)
    assert all(c.text.startswith("Acme Widgets, Inc. 10-K FY2025 — ") for c in prepared.chunks)
    assert prepared.text_chars > 3000
    assert prepared.est_tokens == sum(c.est_tokens for c in prepared.chunks)
    assert prepared.est_cost_usd == pytest.approx(prepared.est_tokens * config.EMBED_PRICE_PER_MTOK / 1e6)


def test_dry_run_without_a_database_reports_estimates():
    report = ingest.ingest_filing(None, K, edgar=FakeEdgar(), dry_run=True)
    assert report.status == "dry-run" and report.error is None
    assert report.n_chunks > 0 and report.est_tokens > 0 and report.est_cost_usd > 0
    assert report.sections == ["item_1", "item_1a", "item_7", "item_7a", "item_8"] and not report.fallback
    assert report.cached is True and report.title == "ACME 10-K FY2025"
    assert report.seconds >= 0


def test_thin_primary_document_pulls_in_sibling_documents(monkeypatch):
    """A wrapper document (Wells Fargo, IBM) has little text; the report body is a
    sibling file, which is appended before splitting."""
    wrapper = "<html><body><p>FORM 10-K</p><p>Item 8. Financial Statements and Supplementary Data</p>" \
              "<p>Incorporated by reference to Exhibit 13.</p></body></html>"
    edgar = FakeEdgar(html={K.accession: wrapper, Q.accession: HTML_10Q})
    edgar.siblings = [("acme-ex13.htm", HTML_10K)]
    report = ingest.ingest_filing(None, K, edgar=edgar, dry_run=True)
    assert report.status == "dry-run", report.error
    assert report.supplements == ["acme-ex13.htm"] and edgar.supplement_calls == 1
    assert report.sections == ["item_1", "item_1a", "item_7", "item_7a", "item_8"]
    assert report.split_mode == "item" and 0 < report.coverage <= 1

    # a normal-sized primary never asks for siblings
    monkeypatch.setitem(config.THIN_TEXT_CHARS, "10-K", 1_000)
    edgar2 = FakeEdgar()
    report2 = ingest.ingest_filing(None, K, edgar=edgar2, dry_run=True)
    assert report2.supplements == [] and getattr(edgar2, "supplement_calls", 0) == 0


def test_live_run_without_a_database_is_an_error_not_a_crash():
    report = ingest.ingest_filing(None, K, edgar=FakeEdgar(), dry_run=False, embedder=lambda texts: [])
    assert report.status == "error"
    assert "Postgres connection" in report.error


def test_bad_html_is_reported_per_filing():
    edgar = FakeEdgar(html={K.accession: HTML_10K, Q.accession: HTML_10Q})

    def boom(filing, *, refetch=False):
        raise RuntimeError("corrupt download")

    edgar.fetch_document = boom
    report = ingest.ingest_filing(None, K, edgar=edgar, dry_run=True)
    assert report.status == "error" and "corrupt download" in report.error


def test_store_filing_issues_graph_doc_and_chunk_statements():
    prepared = ingest.prepare_filing(Q, HTML_10Q)
    conn = StubConn()
    vectors = [[0.0] * 767 + [1.0] for _ in prepared.chunks]
    ingest.store_filing(conn, prepared, vectors, corpus="live")

    sql = [c[0] for c in conn.calls]
    assert "INSERT INTO kg_nodes" in sql[0] and conn.calls[0][1]["id"] == "ACME"  # company node if missing
    assert "'filing'" in sql[1] and conn.calls[1][1]["id"] == "filing:0000123456-25-000002"
    assert "INSERT INTO kg_edges" in sql[2] and conn.calls[2][1] == {"src": "ACME", "dst": "filing:0000123456-25-000002", "accession": Q.accession}
    assert "INSERT INTO filing_docs" in sql[3]
    doc = conn.calls[3][1]
    assert doc["embed_model"] == "gemini-embedding-001" and doc["embed_dim"] == 768
    assert doc["n_chunks"] == len(prepared.chunks) and doc["form"] == "10-Q" and doc["corpus"] == "live"
    assert "INSERT INTO filing_chunks" in sql[4]
    rows = conn.calls[4][1]
    assert len(rows) == len(prepared.chunks)
    assert rows[0]["embedding"].startswith("[0.000000,") and rows[0]["embedding"].endswith(",1.000000]")
    assert [r["ord"] for r in rows] == list(range(len(rows)))
    assert {r["section"] for r in rows} == {"item_1", "item_2"}


def test_store_filing_rejects_vector_count_mismatch():
    prepared = ingest.prepare_filing(Q, HTML_10Q)
    with pytest.raises(ingest.IngestError):
        ingest.store_filing(StubConn(), prepared, [[1.0] * 768])


def test_run_ingestion_dry_run_collects_reports_and_list_errors():
    edgar = FakeEdgar(filings={"ACME": [K, Q], "EMPTY": []}, fail_for={"BAD"})
    reports = ingest.run_ingestion(["ACME", "BAD", "EMPTY"], edgar=edgar, dry_run=True)
    assert [(r.ticker, r.status) for r in reports] == [("ACME", "dry-run"), ("ACME", "dry-run"), ("BAD", "error"), ("EMPTY", "error")]
    assert "SEC says no" in reports[2].error
    assert "no 10-K / 10-Q" in reports[3].error


def test_run_ingestion_stops_at_budget_exceeded():
    class FakeEngine:
        def begin(self):
            from contextlib import contextmanager

            @contextmanager
            def cm():
                yield StubConn()

            return cm()

    def broke(texts):
        raise BudgetExceeded("refusing call: over budget")

    seen = []
    reports = ingest.run_ingestion(["ACME"], edgar=FakeEdgar(), engine=FakeEngine(), embedder=broke, on_report=seen.append)
    assert len(reports) == 1 and reports[0].status == "error" and "BudgetExceeded" in reports[0].error
    assert seen == reports  # the second filing was never attempted


def test_load_universe_parses_comments_and_duplicates(tmp_path):
    p = tmp_path / "universe.txt"
    p.write_text("# header\nnvda\nAAPL # apple\n\nMSFT\nnvda\n")
    assert ingest.load_universe(p) == ["NVDA", "AAPL", "MSFT"]


def test_committed_universe_has_fifty_sec_style_tickers():
    tickers = ingest.load_universe()
    assert len(tickers) == 50 and len(set(tickers)) == 50
    assert "BRK-B" in tickers and "BRK.B" not in tickers
    assert all(t.replace("-", "").isalpha() for t in tickers)


def test_summary_markdown_has_totals_rate_and_errors():
    ok = ingest.FilingReport.for_filing(K, "dry-run")
    ok.n_chunks, ok.est_tokens, ok.est_cost_usd, ok.sections = 12, 5000, 0.00075, ["item_1", "item_7"]
    fb = ingest.FilingReport.for_filing(Q, "dry-run")
    fb.n_chunks, fb.est_tokens, fb.est_cost_usd, fb.sections, fb.fallback = 3, 1000, 0.00015, ["full"], True
    err = ingest.FilingReport(ticker="BAD", accession="", form="", period_end=None, title="BAD filings", url="", status="error", error="SEC says no")
    skipped = ingest.FilingReport.for_filing(K, "skipped")

    ok.split_mode, ok.coverage, fb.split_mode, fb.coverage = "title", 0.61, "full", 1.0
    ok.supplements = ["acme-ex13.htm"]

    md = ingest.summarize([ok, fb, err, skipped], dry_run=True, label="test")
    assert "| Filings planned | 2 |" in md
    assert "| Filings skipped (already stored) | 1 |" in md
    assert "| Chunks | 15 |" in md
    assert "| Section split succeeded (no `full` fallback) | 1/2 (50%) |" in md
    assert "| … of which via title-only headings | 1 |" in md
    assert "| Filings that needed a sibling document (thin primary) | 1 |" in md
    assert "| Embedding tokens (estimate, chars/4) | 6,000 |" in md
    assert "$0.0009" in md
    assert "| title +1 sibling | 1, 7 | 61% |" in md
    assert "| full | `full` | 100% |" in md
    assert "## Errors" in md and "BAD filings: SEC says no" in md
    assert "dry-run" in md


def test_write_summary_creates_parent_dirs(tmp_path):
    path = tmp_path / "results" / "ingest_summary.md"
    ingest.write_summary([], path, dry_run=True)
    assert path.read_text().startswith("# Filings ingestion summary")


def test_vector_literal_formats_for_halfvec_cast():
    assert ingest.vector_literal([0, 0.5, -1]) == "[0.000000,0.500000,-1.000000]"
