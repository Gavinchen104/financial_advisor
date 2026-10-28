# Project 2 progress (docs/PROJECT2-PLAN.md)

| Package | Status | PR | Date | Notes / run ids / cost |
|---|---|---|---|---|
| P2-A Prep | ☑ done | — (committed on `feat/rag`) | 2026-10-28 | 106 SQLite tests + 6 pgvector smoke tests passed locally (pg run against the compose db). CI `pytest-pg` on the push: see Actions for `feat/rag`. |
| P2-B KG → Postgres | ☐ | | | |
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

## Spend log
| Date | Step | Provider | $ (estimate → actual) |
|---|---|---|---|
| 2026-10-28 | P2-A | — | $0 (no API calls) |

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
