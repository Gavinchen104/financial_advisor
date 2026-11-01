"""Filings ingestion orchestrator (docs/PROJECT2-PLAN.md P2-C).

EDGAR → html_text → sections → chunks → embeddings → filing_docs / filing_chunks,
plus a `filing:<accession>` node and a `filed` edge from the company in the
knowledge graph. One transaction per filing (the caller opens it), so a crash
mid-run keeps everything finished so far and the next run skips those
accessions.

Money: embeddings are the only paid step. `dry_run=True` does everything but
embed and write, and reports the estimated tokens / cost; `max_usd` installs an
embed.Budget that refuses the batch that would cross the cap.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from loguru import logger
from sqlalchemy import text

from . import config, embed
from .chunk import Chunk, chunk_filing
from .edgar import EdgarClient, Filing
from .html_text import SectionSplit, form_key, html_to_text, split_sections
from .kg_store import company_aliases
from .llm import Budget, BudgetExceeded

Embedder = Callable[[list[str]], list[list[float]]]


class IngestError(RuntimeError):
    pass


@dataclass
class Prepared:
    filing: Filing
    text_chars: int
    split: SectionSplit
    chunks: list[Chunk]

    @property
    def est_tokens(self) -> int:
        return embed.estimate_tokens([c.text for c in self.chunks])

    @property
    def est_cost_usd(self) -> float:
        return config.embed_cost_usd(self.est_tokens)


@dataclass
class FilingReport:
    ticker: str
    accession: str
    form: str
    period_end: date | None
    title: str
    url: str
    status: str  # ingested | dry-run | skipped | error
    n_chunks: int = 0
    est_tokens: int = 0
    est_cost_usd: float = 0.0
    sections: list[str] = field(default_factory=list)
    fallback: bool = False
    split_mode: str = ""  # item | title | full
    coverage: float = 0.0
    supplements: list[str] = field(default_factory=list)  # sibling documents pulled in for a thin primary
    text_chars: int = 0
    cached: bool = False
    error: str | None = None
    seconds: float = 0.0

    @classmethod
    def for_filing(cls, filing: Filing, status: str) -> "FilingReport":
        return cls(
            ticker=filing.ticker, accession=filing.accession, form=filing.form,
            period_end=filing.period_end, title=filing.title, url=filing.url, status=status,
        )


# ---------- pure steps ----------
def prepare_text(filing: Filing, text: str) -> Prepared:
    """Clean text → sections → chunks. No network, no database, no money."""
    split = split_sections(text, filing.form)
    chunks = chunk_filing(
        split.sections,
        company=filing.company_name or filing.ticker,
        form=filing.form,
        period=filing.fiscal_label,
    )
    return Prepared(filing=filing, text_chars=len(text), split=split, chunks=chunks)


def prepare_filing(filing: Filing, html: str, supplements: Iterable[str] = ()) -> Prepared:
    """HTML (plus any sibling documents) → text → sections → chunks."""
    texts = [html_to_text(html)] + [html_to_text(s) for s in supplements]
    return prepare_text(filing, "\n".join(t for t in texts if t))


def is_thin(text: str, form: str) -> bool:
    return len(text) < config.THIN_TEXT_CHARS[form_key(form)]


def vector_literal(vector: Iterable[float]) -> str:
    return "[" + ",".join(f"{float(x):.6f}" for x in vector) + "]"


# ---------- database ----------
def already_ingested(conn, accession: str) -> bool:
    return conn.execute(
        text("SELECT 1 FROM filing_docs WHERE accession = :a LIMIT 1"), {"a": accession}
    ).first() is not None


_UPSERT_COMPANY = text(
    """
    INSERT INTO kg_nodes (id, type, name, props)
    VALUES (:id, 'company', :name, CAST(:props AS jsonb))
    ON CONFLICT (id) DO NOTHING
    """
)
_UPSERT_FILING_NODE = text(
    """
    INSERT INTO kg_nodes (id, type, name, props)
    VALUES (:id, 'filing', :name, CAST(:props AS jsonb))
    ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, props = kg_nodes.props || EXCLUDED.props
    """
)
_INSERT_FILED_EDGE = text(
    """
    INSERT INTO kg_edges (src, dst, type, weight, source, accession)
    VALUES (:src, :dst, 'filed', 1.0, 'filing', :accession)
    ON CONFLICT (src, dst, type, source, accession) DO NOTHING
    """
)
_INSERT_DOC = text(
    """
    INSERT INTO filing_docs
        (accession, ticker, cik, form, period_end, filed_at, source_url, corpus, embed_model, embed_dim, n_chunks)
    VALUES
        (:accession, :ticker, :cik, :form, :period_end, :filed_at, :source_url, :corpus, :embed_model, :embed_dim, :n_chunks)
    """
)
_INSERT_CHUNK = text(
    """
    INSERT INTO filing_chunks (accession, ticker, corpus, section, page, ord, text, embedding)
    VALUES (:accession, :ticker, :corpus, :section, :page, :ord, :text, CAST(:embedding AS halfvec(768)))
    """
)
_DELETE_DOC = text("DELETE FROM filing_docs WHERE accession = :a")  # chunks cascade


def store_filing(conn, prepared: Prepared, vectors: list[list[float]], *, corpus: str = "live") -> None:
    f = prepared.filing
    if len(vectors) != len(prepared.chunks):
        raise IngestError(f"{f.title}: {len(vectors)} vectors for {len(prepared.chunks)} chunks")
    import json

    # The company may sit outside the seeded S&P 500 graph (on-demand ingestion).
    conn.execute(_UPSERT_COMPANY, {
        "id": f.ticker,
        "name": f.company_name or f.ticker,
        "props": json.dumps({"sp500": False, "aliases": company_aliases(f.company_name or f.ticker), "cik": f.cik}),
    })
    conn.execute(_UPSERT_FILING_NODE, {
        "id": f.node_id,
        "name": f.title,
        "props": json.dumps({
            "ticker": f.ticker, "form": f.form, "accession": f.accession,
            "period_end": f.period_end.isoformat() if f.period_end else None,
            "filed_at": f.filed_at.isoformat() if f.filed_at else None,
            "url": f.url, "sections": prepared.split.found, "fallback": prepared.split.fallback,
            "split_mode": prepared.split.mode, "coverage": prepared.split.coverage,
        }),
    })
    conn.execute(_INSERT_FILED_EDGE, {"src": f.ticker, "dst": f.node_id, "accession": f.accession})
    conn.execute(_INSERT_DOC, {
        "accession": f.accession, "ticker": f.ticker, "cik": f.cik, "form": f.form,
        "period_end": f.period_end, "filed_at": f.filed_at, "source_url": f.url, "corpus": corpus,
        "embed_model": embed.MODEL, "embed_dim": embed.DIM, "n_chunks": len(prepared.chunks),
    })
    rows = [
        {
            "accession": f.accession, "ticker": f.ticker, "corpus": corpus, "section": c.section,
            "page": c.page, "ord": c.ord, "text": c.text, "embedding": vector_literal(v),
        }
        for c, v in zip(prepared.chunks, vectors)
    ]
    if rows:
        conn.execute(_INSERT_CHUNK, rows)


# ---------- one filing ----------
def ingest_filing(
    conn,
    filing: Filing,
    *,
    edgar: EdgarClient,
    embedder: Embedder = embed.embed_documents,
    corpus: str = "live",
    dry_run: bool = False,
    refetch: bool = False,
    replace: bool = False,
) -> FilingReport:
    """Fetch (cached), prepare, embed and store one filing. `conn` may be None for a
    dry run without a database. BudgetExceeded propagates so the caller can stop."""
    t0 = time.perf_counter()
    report = FilingReport.for_filing(filing, "dry-run" if dry_run else "ingested")
    try:
        if conn is not None and not replace and already_ingested(conn, filing.accession):
            report.status = "skipped"
            return report
        report.cached = edgar.is_cached(filing)
        html = edgar.fetch_document(filing, refetch=refetch)
        text_ = html_to_text(html)
        if is_thin(text_, filing.form):
            # a wrapper document: the report body is a sibling file in the filing folder
            siblings = edgar.supplemental_documents(filing)
            if siblings:
                report.supplements = [name for name, _ in siblings]
                text_ = "\n".join([text_] + [html_to_text(h) for _, h in siblings])
        prepared = prepare_text(filing, text_)
        report.n_chunks = len(prepared.chunks)
        report.est_tokens = prepared.est_tokens
        report.est_cost_usd = prepared.est_cost_usd
        report.sections = list(prepared.split.sections)
        report.fallback = prepared.split.fallback
        report.split_mode = prepared.split.mode
        report.coverage = prepared.split.coverage
        report.text_chars = prepared.text_chars
        if dry_run:
            return report
        if conn is None:
            raise IngestError("a Postgres connection is required to ingest; use --dry-run without one")
        vectors = embedder([c.text for c in prepared.chunks])
        if replace:
            conn.execute(_DELETE_DOC, {"a": filing.accession})
        store_filing(conn, prepared, vectors, corpus=corpus)
        logger.info(f"ingest: stored {filing.title}: {len(prepared.chunks)} chunks, ~{report.est_tokens} tokens")
    except BudgetExceeded:
        raise
    except Exception as e:  # one bad filing must not stop the run
        report.status = "error"
        report.error = f"{e.__class__.__name__}: {e}"
        logger.warning(f"ingest: {filing.title} failed: {report.error}")
    finally:
        report.seconds = round(time.perf_counter() - t0, 2)
    return report


# ---------- a run ----------
def load_universe(path: Path = config.UNIVERSE_PATH) -> list[str]:
    """Tickers from data/universe.txt: one per line, '#' comments, duplicates dropped."""
    out: list[str] = []
    for line in Path(path).read_text().splitlines():
        ticker = line.split("#", 1)[0].strip().upper()
        if ticker and ticker not in out:
            out.append(ticker)
    return out


def run_ingestion(
    tickers: list[str],
    *,
    edgar: EdgarClient,
    engine=None,
    embedder: Embedder = embed.embed_documents,
    form_counts: dict[str, int] | None = None,
    dry_run: bool = False,
    corpus: str = "live",
    max_usd: float | None = None,
    refetch: bool = False,
    replace: bool = False,
    on_report: Callable[[FilingReport], None] | None = None,
) -> list[FilingReport]:
    """Ingest the latest filings of every ticker. With `engine`, each filing gets
    its own transaction; without one only a dry run is possible. Stops at the first
    BudgetExceeded and records it as an error on that filing."""
    if max_usd is not None:
        embed.set_budget(Budget(max_usd=max_usd))
    reports: list[FilingReport] = []

    def emit(report: FilingReport) -> None:
        reports.append(report)
        if on_report:
            on_report(report)

    if engine is not None and dry_run:
        try:  # a dry run only needs the DB to report "skipped"; carry on without it
            with engine.connect():
                pass
        except Exception as e:
            logger.warning(f"ingest: database unreachable, dry run continues without skip detection ({e.__class__.__name__})")
            engine = None

    for ticker in tickers:
        try:
            filings = edgar.list_filings(ticker, form_counts)
        except Exception as e:
            emit(FilingReport(ticker=ticker, accession="", form="", period_end=None, title=f"{ticker} filings",
                              url="", status="error", error=f"list_filings: {e.__class__.__name__}: {e}"))
            continue
        if not filings:
            emit(FilingReport(ticker=ticker, accession="", form="", period_end=None, title=f"{ticker} filings",
                              url="", status="error", error="no 10-K / 10-Q found in recent filings"))
            continue
        for filing in filings:
            kwargs = dict(edgar=edgar, embedder=embedder, corpus=corpus, dry_run=dry_run, refetch=refetch, replace=replace)
            try:
                if engine is None:
                    report = ingest_filing(None, filing, **kwargs)
                elif dry_run:
                    with engine.connect() as conn:
                        report = ingest_filing(conn, filing, **kwargs)
                else:
                    with engine.begin() as conn:
                        report = ingest_filing(conn, filing, **kwargs)
            except BudgetExceeded as e:
                report = FilingReport.for_filing(filing, "error")
                report.error = f"BudgetExceeded: {e}"
                emit(report)
                logger.warning(f"ingest: stopping, {e}")
                return reports
            emit(report)
    return reports


# ---------- summary ----------
def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5, cwd=config.ROOT
        ).stdout.strip() or "unknown"
    except Exception:  # pragma: no cover
        return "unknown"


def summarize(reports: list[FilingReport], *, dry_run: bool, label: str = "") -> str:
    """Markdown summary: totals, section-split success rate, tokens and cost, one row
    per filing. Written to results/ingest_summary.md by the script."""
    processed = [r for r in reports if r.status in ("ingested", "dry-run")]
    skipped = [r for r in reports if r.status == "skipped"]
    errors = [r for r in reports if r.status == "error"]
    n_chunks = sum(r.n_chunks for r in processed)
    tokens = sum(r.est_tokens for r in processed)
    cost = sum(r.est_cost_usd for r in processed)
    split_ok = sum(1 for r in processed if not r.fallback)
    rate = f"{split_ok}/{len(processed)} ({100 * split_ok / len(processed):.0f}%)" if processed else "n/a"
    by_title = sum(1 for r in processed if r.split_mode == "title")
    with_supplements = sum(1 for r in processed if r.supplements)
    tickers = sorted({r.ticker for r in reports})

    lines = [
        "# Filings ingestion summary",
        "",
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · git `{_git_sha()}` · "
        f"mode: **{'dry-run (nothing embedded or stored)' if dry_run else 'live'}**"
        + (f" · {label}" if label else ""),
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Tickers | {len(tickers)} |",
        f"| Filings {'planned' if dry_run else 'ingested'} | {len(processed)} |",
        f"| Filings skipped (already stored) | {len(skipped)} |",
        f"| Filings with errors | {len(errors)} |",
        f"| Chunks | {n_chunks:,} |",
        f"| Section split succeeded (no `full` fallback) | {rate} |",
        f"| … of which via title-only headings | {by_title} |",
        f"| Filings that needed a sibling document (thin primary) | {with_supplements} |",
        f"| Embedding tokens (estimate, chars/4) | {tokens:,} |",
        f"| Embedding cost (estimate, {embed.MODEL} @ ${config.EMBED_PRICE_PER_MTOK}/MTok) | ${cost:.4f} |",
        "",
        "| Ticker | Form | Period end | Status | Chunks | Split | Sections | Coverage | Tokens (est) | Cost (est) | Cached |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(reports, key=lambda r: (r.ticker, r.form, str(r.period_end))):
        if r.status == "error":
            sections, mode, cov = "—", "—", "—"
        else:
            sections = "`full`" if r.fallback else ", ".join(s.removeprefix("item_") for s in r.sections) or "—"
            mode = (r.split_mode or "—") + (f" +{len(r.supplements)} sibling" if r.supplements else "")
            cov = f"{r.coverage:.0%}" if r.status != "skipped" else "—"
        lines.append(
            f"| {r.ticker} | {r.form or '—'} | {r.period_end or '—'} | {r.status} | {r.n_chunks} | {mode} | {sections} | {cov} | "
            f"{r.est_tokens:,} | ${r.est_cost_usd:.4f} | {'yes' if r.cached else 'no'} |"
        )
    if errors:
        lines += ["", "## Errors", ""]
        lines += [f"- {r.title}: {r.error}" for r in errors]
    return "\n".join(lines) + "\n"


def write_summary(reports: list[FilingReport], path: Path, *, dry_run: bool, label: str = "") -> str:
    md = summarize(reports, dry_run=dry_run, label=label)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(md)
    return md
