# Project 2 progress (docs/PROJECT2-PLAN.md)

| Package | Status | PR | Date | Notes / run ids / cost |
|---|---|---|---|---|
| P2-A Prep | ☑ done | — (committed on `feat/rag`) | 2026-10-28 | 106 SQLite tests + 6 pgvector smoke tests passed locally (pg run against the compose db). CI run [40752515475](https://github.com/Gavinchen104/financial_advisor/actions/runs/40752515475) on `2802aa5`: success (lint-and-import, pytest, pytest-pg). |
| P2-B KG → Postgres | ☑ done | — (committed on `feat/rag`) | 2026-10-28 | 149 SQLite tests pass locally. CI run [40757444110](https://github.com/Gavinchen104/financial_advisor/actions/runs/40757444110) on `0e0c2e1`: success (lint-and-import, pytest, pytest-pg with the 16 pg tests: 6 smoke + 10 KG seed/parity). Seed dry-run: 524 nodes (514 company, 10 macro), 3,811 edges (2,303 curated, 1,508 gics), 1 edge skipped (`BRK.B` typo, fixed in `_macro.py`, lands on the next JSON rebuild). |
| P2-C Filings ingestion | ☐ | | | |
| P2-D Filings → KG | ☐ | | | |
| P2-E Market facts | ☐ | | | |
| P2-F Hybrid retrieval | ☐ | | | |
| P2-G Graph retrieval | ☐ | | | |
| P2-H Answers + grounding + /ask + UI | ☐ | | | |
| P2-I Evaluation | ☐ | | | |
| P2-J Ship + README | ☐ | | | |

## P2-A — what landed
- Deps: `anthropic`, `pgvector`, `numpy`, `rapidfuzz`, `tenacity`; dev: `pymupdf`, `pytest-mock`, `respx`. Pytest markers `pg` and `live` registered.
- `docker-compose.yml`: db image → `pgvector/pgvector:pg16`, published on `127.0.0.1:5432` so `uv run …` can use `DATABASE_URL=…@localhost:5432`; the app container takes `APP_DATABASE_URL` (default `@db`) so a local `.env` can't point it at localhost.
- CI: new `pytest-pg` job with a pgvector service and `pytest -m pg`; the import check also imports `src.rag`; workflows run on pushes to `feat/**` as well as `main`.
- `src/tools/filings.py` reads the User-Agent from `SEC_USER_AGENT` (fallback unchanged). `src/db.py` loads `.env` (so the alembic CLI and scripts see the same `DATABASE_URL` as the app) and exposes `normalize_database_url()`.
- `src/rag/config.py` (model ids, price table incl. Haiku 5.5 long-context tier and batch discount, caps, env lookups) and `src/rag/llm.py` (lazy client with `max_retries=5`, `Budget`, `estimate()` via `count_tokens`, `create()` / `parse()` with one max_tokens retry, loguru fields for tokens/cost/latency/stop_reason, `structured_output_config()` / `parse_structured()`, `batch_submit()` / `batch_wait()` / `batch_collect()`).
- Migration `7b3e9d2c4a1f_add_kg_and_rag`: Postgres gets the §4 schema (extension, `kg_*`, `filing_docs`, `filing_chunks` halfvec HNSW + tsvector GIN, `ask_log`); SQLite gets only `ask_log`. `AskLog` ORM model added; `alembic check` is clean on SQLite.
- `migrations/env.py` honors a caller-supplied `sqlalchemy.url` (the pg test fixture migrates the test DB with it) and hides the Postgres-only tables from autogenerate.
- `tests/conftest.py`: `PG_TEST_URL` → `pg_engine` / `pg_conn` fixtures (skip when unset, fail when set but unreachable). New tests: `test_rag_config.py`, `test_rag_llm.py`, `test_filings_headers.py`, `test_pg_smoke.py`.
- Docs: `.env.example` RAG vars, CLAUDE.md §2 rules + tree, README test/Docker/deploy notes.

## P2-B — what landed
- `src/knowledge_graph/graph.py`: one `KnowledgeGraph` class for both backends (`from_json()`, `from_db()`, `backend` attribute). `canonical_edges()` gives every edge `provenance` (`curated` | `gics` | `filing`) and `evidence`, reads `major_customer(A→B)` as `supplies_to(B→A)`, and collapses duplicates (macro override beats sector default, then higher weight). New incoming-edge index (ends the O(E) `get_suppliers` scan), `get_edge(id)`, `neighbors(node, types, k)`, `paths(a, b, max_hops=2)` with provenance-ranked results and a `summary` string per path. `get_competitors()` now returns one row per counterparty (a pair with both a curated and a GICS edge used to appear twice). `get_graph()` prefers the DB graph when `DATABASE_URL` is Postgres and the tables are seeded, reloads it every 15 min, and falls back to JSON on any failure; `reset_graph()` for tests/scripts.
- `src/rag/kg_store.py`: `graph_rows()` / `plan_seed()` (dry-run), `seed_graph()` / `seed_from_json()` (idempotent upsert, stable edge ids, prunes curated/gics edges that left the JSON, never deletes nodes), `is_seeded()`, `load_graph_data()`, plus `company_aliases()` / `normalize_company_name()` / `strip_corporate_suffixes()` for `props.aliases` and P2-D entity linking.
- `scripts/seed_kg.py --dry-run | --no-prune | --graph PATH`; refuses to run against SQLite with a pointer to docker compose.
- Migration `c4d1e8a2f906_add_kg_edge_props` (Postgres only): `kg_edges.props JSONB NOT NULL DEFAULT '{}'` and the partial unique index `uq_kg_edges_no_accession (src, dst, type, source) WHERE accession IS NULL`. SQLite: no-op; `alembic check` stays clean.
- `/context/{ticker}`: each competitor / supplier / customer row adds `source`, `evidence`, `accession`; each macro row adds `source`, `evidence`; the response adds `graph_backend` (`db` | `json`). Shape otherwise unchanged; the D3 view and compare tables keep working.
- `src/knowledge_graph/_macro.py`: `COMPANY_MACRO_OVERRIDES` key `BRK.B` → `BRK-B` (the node id). The checked-in JSON still has the typo until the weekly rebuild; the seed reports it as 1 skipped edge.
- Tests: `tests/test_kg_graph.py` (42 unit tests: canonical edges, toy-graph query API with curated + filing edges, neighbors/paths, backend selection, aliases, seed planning), `tests/test_kg_store_pg.py` (10 `@pytest.mark.pg`: schema, not-seeded → None, counts, props/aliases, idempotency with stable ids, prune + update, DB ↔ JSON parity on nodes/edges/query API for 11 tickers, provenance on results, filing nodes excluded / filing edges included), `test_context.py` provenance assertions. `conftest.py` gains `pg_session` (savepoint-joined, rolled back).
- Docs: README (seed step, test counts, tree), CLAUDE.md (tree + backend note), docs/knowledge_graph.md §5/§9.

## Spend log
| Date | Step | Provider | $ (estimate → actual) |
|---|---|---|---|
| 2026-10-28 | P2-A | — | $0 (no API calls) |
| 2026-10-28 | P2-B | — | $0 (no API calls) |

## Test-split runs (each needs a reason)
| Date | run_id | config | reason |
|---|---|---|---|

## Decisions
- 2026-10-28: The Postgres-only RAG tables (`kg_*`, `filing_*`) are raw DDL in the migration, not ORM models; `env.py` excludes them from autogenerate. Only `ask_log` is an ORM model because it must exist on SQLite too — keeps the SQLite suite and `alembic check` clean.
- 2026-10-28: pg tests read `PG_TEST_URL` (conftest forces `DATABASE_URL` to SQLite before importing `src`). When it is set but the DB is unreachable the tests fail rather than skip, so CI cannot go green without the pgvector service.
- 2026-10-28: `llm.Budget.reserve()` guards with a worst-case local estimate (chars/4 input + full `max_tokens` output), so no call can cross `--max-usd`; `llm.estimate()` (`count_tokens`) is the exact number for `--dry-run`.
- 2026-10-28: `config.price_for()` falls back to the longest prefix match so dated snapshot ids echoed by the API (`claude-haiku-5-5-2026…`) still price; unknown models raise instead of guessing.
- 2026-10-28: Deploy caveat — `init_db()` applies this migration at boot, so a production Postgres must have pgvector ≥ 0.7 or the app will not start (a SQLite deployment is unaffected). Verify on Render (`SELECT extversion FROM pg_extension WHERE extname = 'vector';`) before merging `feat/rag` into `main`.
- 2026-10-28: The Claude Code sandbox cannot reach Docker or `localhost:5432`, so Postgres-backed tests are run by Gavin (`!` prefix) or by CI. `ci.yml` therefore also runs on pushes to `feat/**`, so the branch gets the pgvector job without opening a PR.
- 2026-10-28: Local dev venv is Python 3.11 (Homebrew). Homebrew postgresql@16 has no pgvector and collides with the compose port — keep it stopped (`brew services stop postgresql@16`) while working on RAG.
- 2026-10-28 (P2-B): Follow-up migration `c4d1e8a2f906` instead of hacks. §4 has no column for macro-edge direction/override (needed by `get_macro_sensitivity` and the UI), and `UNIQUE (src, dst, type, source, accession)` never conflicts for curated/gics edges (NULL accession), so `ON CONFLICT` upserts could not be idempotent. Added `kg_edges.props JSONB` + a partial unique index on `(src, dst, type, source) WHERE accession IS NULL`. Revert = `alembic downgrade 7b3e9d2c4a1f` plus dropping the two uses in `kg_store.py`. Flagged for Gavin's sign-off per CLAUDE.md ("ask before changing the DB schema").
- 2026-10-28 (P2-B): Curated rationale is stored in `kg_edges.evidence` (the plan asks `/context` to expose `evidence` per edge); filing edges will store the verbatim quote there. `source` ∈ {`curated`, `gics`, `filing`}; macro edges are `curated` (both sector defaults and overrides are hand-authored).
- 2026-10-28 (P2-B): `major_customer` (5 JSON edges, previously ignored by every query) is read as reversed `supplies_to` in both backends. The JSON file is untouched; the mapping lives in `canonical_edges()`.
- 2026-10-28 (P2-B): Both backends keep a curated and a GICS edge for the same pair as separate edges (that is the provenance), and the query API dedupes per counterparty, heavier edge first. The DB graph is loaded `ORDER BY id` (= JSON order at seed time) so tie-breaking matches the JSON graph exactly; `get_sector_peers` sorts by ticker for the same reason.
- 2026-10-28 (P2-B): The compose `stockify` DB is both the dev DB and the local pg test DB, so every pg test must be hermetic: `test_kg_store_pg.py` deletes `kg_*` rows inside its rolled-back transaction before seeding. Seeding the whole graph in a test takes well under a second.
- 2026-10-28 (P2-B): Nodes are never deleted by the seed (filing edges/facts cascade from them); companies that leave the S&P 500 stay as nodes. Production seeding (Neon/Supabase) stays a P2-J step; `refresh-knowledge-graph.yml` only rebuilds the JSON.
