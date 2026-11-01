"""
Ingest SEC filings into Postgres: latest 10-K + 2 10-Qs per ticker → text →
sections → ~450-token chunks → gemini-embedding-001 vectors → filing_docs /
filing_chunks, plus a filing node and a `filed` edge in the knowledge graph.
See docs/PROJECT2-PLAN.md P2-C.

Accessions already in filing_docs are skipped, so re-running is cheap and the
weekly job only pays for new filings. Raw documents are cached under
data/raw/edgar/ and never re-downloaded.

    uv run python scripts/ingest_filings.py --tickers NVDA,AAPL --dry-run   # fetch + chunk, estimate cost; no DB, no money
    uv run python scripts/ingest_filings.py --tickers NVDA,AAPL --max-usd 1  # embed + store (Postgres + GEMINI_API_KEY)
    uv run python scripts/ingest_filings.py --universe --max-usd 5           # the 50-ticker list in data/universe.txt

Writes results/ingest_summary.md (filings, chunks, section-split rate, tokens, cost).
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.rag import config  # noqa: E402
from src.rag.edgar import EdgarClient  # noqa: E402
from src.rag.ingest import FilingReport, load_universe, run_ingestion, write_summary  # noqa: E402


def _parse_forms(spec: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for part in spec.split(","):
        form, _, n = part.strip().partition("=")
        if not form:
            continue
        out[form.strip().upper()] = int(n) if n else 1
    return out


def _print_report(r: FilingReport) -> None:
    if r.status == "error":
        print(f"  {r.title:<34} ERROR  {r.error}")
        return
    sections = "full (fallback)" if r.fallback else f"{r.split_mode}: " + ",".join(s.removeprefix("item_") for s in r.sections)
    if r.supplements:
        sections += f" +{len(r.supplements)} sibling doc"
    extra = "" if r.status == "skipped" else f"{r.n_chunks:>4} chunks  ~{r.est_tokens:>7,} tok  ${r.est_cost_usd:.4f}  [{sections}] {r.coverage:.0%}"
    cached = " (cached)" if r.cached else ""
    print(f"  {r.title:<34} {r.status:<8} {extra}{cached}  {r.seconds:.1f}s")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    who = parser.add_mutually_exclusive_group(required=True)
    who.add_argument("--tickers", help="comma-separated tickers, e.g. NVDA,AAPL")
    who.add_argument("--universe", action="store_true", help=f"every ticker in {config.UNIVERSE_PATH.relative_to(config.ROOT)}")
    parser.add_argument("--forms", default="10-K=1,10-Q=2", help="filings per form (default: 10-K=1,10-Q=2)")
    parser.add_argument("--dry-run", action="store_true", help="fetch, clean and chunk; print token and $ estimates; write nothing")
    parser.add_argument("--max-usd", type=float, default=None, help="stop before the embedding batch that would cross this spend")
    parser.add_argument("--corpus", default="live", help="filing_docs.corpus (default live; evals use financebench)")
    parser.add_argument("--refetch", action="store_true", help="ignore the on-disk HTML cache")
    parser.add_argument("--replace", action="store_true", help="re-ingest accessions that are already stored")
    parser.add_argument("--summary", type=Path, default=config.RESULTS_DIR / "ingest_summary.md", help="markdown summary path")
    parser.add_argument("--no-summary", action="store_true", help="do not write the summary file")
    args = parser.parse_args()

    tickers = load_universe() if args.universe else [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    form_counts = _parse_forms(args.forms)

    from src.rag.config import uses_postgres

    engine = None
    if uses_postgres():
        from src.db import engine as _engine

        engine = _engine
    if not args.dry_run:
        if engine is None:
            print("DATABASE_URL is not Postgres; filings need pgvector. Use --dry-run, or point DATABASE_URL at the compose db.", file=sys.stderr)
            return 2
        if not config.gemini_api_key():
            print("GEMINI_API_KEY is not set; embeddings need it. Add it to .env or use --dry-run.", file=sys.stderr)
            return 2

    label = "universe" if args.universe else ",".join(tickers)
    mode = "DRY RUN" if args.dry_run else "LIVE"
    print(f"[{mode}] {len(tickers)} ticker(s), forms {form_counts}" + (f", budget ${args.max_usd:.2f}" if args.max_usd is not None else ""))
    if engine is None:
        print("(no Postgres configured: already-ingested filings cannot be detected)")

    edgar = EdgarClient()
    reports = run_ingestion(
        tickers,
        edgar=edgar,
        engine=engine,
        form_counts=form_counts,
        dry_run=args.dry_run,
        corpus=args.corpus,
        max_usd=args.max_usd,
        refetch=args.refetch,
        replace=args.replace,
        on_report=_print_report,
    )

    processed = [r for r in reports if r.status in ("ingested", "dry-run")]
    errors = [r for r in reports if r.status == "error"]
    tokens = sum(r.est_tokens for r in processed)
    cost = sum(r.est_cost_usd for r in processed)
    print()
    print(
        f"{len(processed)} filing(s) {'planned' if args.dry_run else 'ingested'}, "
        f"{sum(1 for r in reports if r.status == 'skipped')} skipped, {len(errors)} error(s); "
        f"{sum(r.n_chunks for r in processed):,} chunks, ~{tokens:,} embedding tokens, "
        f"{'estimated' if args.dry_run else 'estimated spend'} ${cost:.4f}; {edgar.requests} SEC requests"
    )
    if args.dry_run:
        print("Dry run: nothing was embedded or stored. Re-run without --dry-run (add --max-usd) to ingest.")
    if not args.no_summary:
        write_summary(reports, args.summary, dry_run=args.dry_run, label=label)
        print(f"Summary written to {args.summary}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
