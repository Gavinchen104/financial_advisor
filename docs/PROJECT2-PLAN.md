# Project 2 — RAG-Powered Financial Knowledge Graph

**Repo:** `Gavinchen104/financial_advisor` (Stockify) · **Plan date:** 2026-10-28 · **For:** Claude Code, one work package per session
**LLM:** Anthropic API (Claude), paid from your Max plan's monthly API credits · **Embeddings:** Gemini `gemini-embedding-001` · **Briefs:** stay on Gemini, unchanged

> Copy this file into the repo as `docs/PROJECT2-PLAN.md`. It replaces §3 of `PROJECT-GAP-FILL.md` for implementation.
> **The resume is the ground truth.** Every phrase below must end up backed by code + a committed artifact.

---

## Contents

0. [Goal and definition of done](#0-goal-and-definition-of-done)
1. [Before you start (accounts, keys, repo setup)](#1-before-you-start-accounts-keys-repo-setup)
2. [Rules for Claude Code (append to CLAUDE.md)](#2-rules-for-claude-code-append-to-claudemd)
3. [Architecture](#3-architecture)
4. [Data model (Alembic migration)](#4-data-model-alembic-migration)
5. [Work packages P2-A … P2-J](#5-work-packages)
6. [Evaluation methodology](#6-evaluation-methodology)
7. [Cost and budget](#7-cost-and-budget)
8. [Schedule](#8-schedule)
9. [Resume phrase → artifact checklist](#9-resume-phrase--artifact-checklist)
10. [Interview talking points this produces](#10-interview-talking-points-this-produces)
- [Appendix A — Claude Code kickoff prompts](#appendix-a--claude-code-kickoff-prompts)
- [Appendix B — Prompts](#appendix-b--prompts)
- [Appendix C — XBRL concept map](#appendix-c--xbrl-concept-map)
- [Appendix D — API reference notes (checked 2026-10-28)](#appendix-d--api-reference-notes-checked-2026-10-28)
- [Appendix E — PROGRESS.md template](#appendix-e--progressmd-template)

---

## 0. Goal and definition of done

**Resume text (ground truth):**

> **RAG-Powered Financial Knowledge Graph** · March 2026 – May 2026
> *Python, NLP, information retrieval, vector search, knowledge graph, LLM APIs*
> - Built an information-retrieval assistant that ingests SEC filings and market data into a knowledge graph and answers grounded natural-language questions on equities, valuations and sector relationships with source citations.
> - Designed a hybrid retrieval layer (chunking, embeddings, vector search plus knowledge-graph traversal) so every answer is grounded in and cites its source filings rather than the model's parametric memory, so users can verify every claim.

**What Stockify has today:**
- per-ticker Gemini briefs
- a curated knowledge graph (`sp500_graph.json`, ~500 nodes / ~4,000 edges)
- a latest-filing fetch that drops all tables and truncates to 3,000 chars

**What it's missing:** filing ingestion, a filing-fed KG, chunking, embeddings, vector search, hybrid and graph retrieval, Q&A, passage-level citations, and any grounding measurement.

**Done =**
1. `POST /ask` and an "Ask" panel answer questions about equities, valuations and sector relationships, citing exact filing passages, KG facts and market data.
2. Filings (10-K/10-Q text + XBRL facts + extracted relationships) and market data are in a Postgres knowledge graph with provenance.
3. Retrieval = chunks → Gemini embeddings → pgvector + Postgres full-text (RRF) + KG traversal.
4. A grounding check runs on every answer, so no uncited number can reach the user.
5. A committed scorecard (FinanceBench 10-K subset + a Stockify question set) shows accuracy per question type, citation support, grounding-pass rate and an ablation.
6. The README links each resume phrase to its artifact (§9). The existing brief feature and all existing tests still work.

---

## 1. Before you start (accounts, keys, repo setup)

1. **Claim your Max plan's API credits.** In claude.ai: Settings → Billing → API credits → **Link organization**. Pick or create a Console organization; this is available after 7 days on Max. Max 5x gets $100/month, Max 20x $200/month. Credits expire each cycle. If they run out with no purchased credits or auto-reload, API calls stop instead of being charged.
2. **In that Console organization**, create two workspaces with spend limits: **`stockify-eval`** (eval + ingestion jobs) and **`stockify-prod`** (the live `/ask`, with a low limit such as $15/month). Create one API key in each. All keys in the organization share the credit balance; the workspace limits keep the public demo from using up eval money.
3. **Gemini:** reuse the existing `GEMINI_API_KEY` for `gemini-embedding-001`.
4. **SEC:** pick a real User-Agent string, `"Zhihan Chen <your email>"`. EDGAR fair-access policy requires one.
5. **Repo:**
   ```bash
   gh repo clone Gavinchen104/financial_advisor && cd financial_advisor
   git checkout -b feat/rag
   mkdir -p docs && cp "$HOME/Desktop/Job Search/PROJECT2-STOCKIFY-RAG.md" docs/PROJECT2-PLAN.md
   ```
6. **`.env`** (gitignored; also add the new keys to `.env.example` without values):
   ```
   GEMINI_API_KEY=...
   ANTHROPIC_API_KEY=...            # stockify-eval key locally; stockify-prod key on Render
   SEC_USER_AGENT="Zhihan Chen you@example.com"
   DATABASE_URL=postgresql+psycopg://stockify:stockify_dev@localhost:5432/stockify
   ASK_MODEL_DEFAULT=claude-haiku-5-5
   ASK_MODEL_AUTHED=claude-sonnet-5-5
   ASK_DAILY_USD_CAP=1.00
   ```
7. **Keep `ANTHROPIC_API_KEY` out of your shell profile.** Claude Code in VS Code should run on your Max subscription, not the API key.
8. Create `docs/PROGRESS.md` from Appendix E.

---

## 2. Rules for Claude Code (append to `CLAUDE.md`)

```markdown
## RAG / Ask feature (docs/PROJECT2-PLAN.md is the source of truth)
- New code lives in src/rag/. The Gemini brief pipeline (agent.py, prompts/system.md) is untouched
  except the SEC User-Agent fix in tools/filings.py.
- All Claude calls go through src/rag/llm.py (logging, cost, retries, budget). All embedding calls go
  through src/rag/embed.py. No direct SDK calls elsewhere.
- Embeddings: gemini-embedding-001, output_dimensionality=768, task_type RETRIEVAL_DOCUMENT for chunks
  and RETRIEVAL_QUERY for questions, L2-normalize every vector (required below 3072 dims). Never mix
  embedding models in one index.
- Postgres + pgvector is required for RAG. SQLite stays for the existing tests; RAG tests are marked
  @pytest.mark.pg and run against the docker-compose Postgres (and the CI Postgres service).
- Any command that spends money supports --dry-run (token count + $ estimate) and --max-usd.
- Never tune prompts or retrieval on the eval TEST split. README numbers come only from committed
  scorecards in evals/qa/results/.
- Citations (search_result blocks) and structured outputs can't share one request. Answers are
  cited text; structured outputs are only for extraction, intent and judging.
- In tool loops, append response.content unchanged (thinking blocks must round-trip).
- SEC: send SEC_USER_AGENT, ≤5 requests/second, cache raw downloads, never refetch an accession.
- Keep Stockify's policy: never buy/sell/hold/price-target language, in answers too.
```

---

## 3. Architecture

```mermaid
flowchart LR
  subgraph Ingest[Ingestion jobs - scripts + weekly GitHub Action]
    E[EDGAR submissions + primary docs] --> H[html_text: tables as rows, sections]
    H --> C[chunk: section-bounded ~450 tokens]
    C --> EM[embed: gemini-embedding-001, 768d, normalized]
    X[XBRL companyfacts] --> F[kg_facts source=xbrl]
    H --> R[relation extraction: Claude Haiku, Batch, structured output, quote-verified]
    R --> KE[kg_edges source=filing]
    Y[yfinance valuation snapshot] --> MF[kg_facts source=yfinance]
  end
  EM --> PG[(Postgres: filing_chunks halfvec HNSW + tsvector)]
  F & KE & MF --> KG[(Postgres KG: kg_nodes, kg_edges, kg_facts)]
  subgraph Ask[POST /ask]
    Q[question] --> RS[resolve: tickers + intent]
    RS --> HY[hybrid: vector + FTS → RRF]
    RS --> GT[graph: facts, 1-hop expansion, 2-hop paths]
    HY & GT --> EV[evidence → search_result blocks]
    EV --> CL[Claude: cited answer + calculate tool]
    CL --> GC[grounding check → regenerate once or abstain]
    GC --> UI[Ask panel: citation chips → EDGAR]
  end
  PG --> HY
  KG --> GT
```

**New modules**

```
src/rag/
  config.py          # env, model ids, prices, caps
  llm.py             # Anthropic client wrapper: create/parse/batch, cost, retries, budget, logging
  embed.py           # Gemini embeddings (documents/queries), normalization, batching
  edgar.py           # submissions → filings list → download + cache
  html_text.py       # iXBRL cleanup, tables → rows, section splitter
  chunk.py           # section-bounded chunker
  ingest.py          # orchestrates edgar → text → chunks → embeddings → DB, + filing nodes
  kg_store.py        # KG tables access; seed from JSON; KnowledgeGraph.from_db()
  xbrl.py            # companyfacts → kg_facts
  relations.py       # relation extraction (batch), quote verification, entity linking
  market_facts.py    # yfinance snapshot → kg_facts
  resolve.py         # entity + intent resolution
  retrieve.py        # hybrid vector + FTS with RRF
  graph_retrieve.py  # KG facts, neighbor expansion, path search
  evidence.py        # Evidence dataclass + → search_result blocks
  answer.py          # Claude call, calculate tool loop, citation parsing
  grounding.py       # grounding check
  calculator.py      # safe arithmetic evaluator
scripts/ingest_filings.py, scripts/seed_kg.py, scripts/extract_relations.py, scripts/refresh_market_facts.py
evals/qa/            # financebench.py, custom_set.jsonl, run.py, judge.py, label.py, stats.py, results/
```

---

## 4. Data model (Alembic migration)

One migration, `add_kg_and_rag`, **dialect-aware**:
- On PostgreSQL it creates everything below.
- On SQLite (tests) it creates only `ask_log`, using generic SQLAlchemy types (`JSON` instead of `JSONB`/`TEXT[]`, `Integer` autoincrement instead of `BIGSERIAL`), and skips the vector/KG tables. Existing tests keep passing.
- Requires **pgvector ≥ 0.7** (for `halfvec`). The `pgvector/pgvector:pg16` image has it; check the version on your hosted Postgres with `SELECT extversion FROM pg_extension WHERE extname='vector';`.

```sql
CREATE EXTENSION IF NOT EXISTS vector;

-- Knowledge graph with provenance
CREATE TABLE kg_nodes (
  id    TEXT PRIMARY KEY,               -- 'NVDA' | 'macro:10y_treasury_yield' | 'filing:<accession>' | 'org:<slug>'
  type  TEXT NOT NULL,                  -- company | macro | filing | org
  name  TEXT NOT NULL,
  props JSONB NOT NULL DEFAULT '{}'     -- gics_*, aliases[], form, period_end, url, ...
);
CREATE TABLE kg_edges (
  id         BIGSERIAL PRIMARY KEY,
  src        TEXT NOT NULL REFERENCES kg_nodes ON DELETE CASCADE,
  dst        TEXT NOT NULL REFERENCES kg_nodes ON DELETE CASCADE,
  type       TEXT NOT NULL,             -- competes_with | supplies_to | strategic_partner | macro_sensitivity | filed
  weight     REAL,
  source     TEXT NOT NULL,             -- curated | gics | filing
  accession  TEXT,                      -- filing supporting the edge (source='filing')
  evidence   TEXT,                      -- verbatim quote from that filing
  confidence TEXT,                      -- low | medium | high
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (src, dst, type, source, accession)
);
CREATE INDEX ON kg_edges (src); CREATE INDEX ON kg_edges (dst); CREATE INDEX ON kg_edges (type);
CREATE TABLE kg_facts (
  id            BIGSERIAL PRIMARY KEY,
  node_id       TEXT NOT NULL REFERENCES kg_nodes ON DELETE CASCADE,
  metric        TEXT NOT NULL,          -- revenue | net_income | eps_diluted | price | trailing_pe | ...
  value         NUMERIC NOT NULL,
  unit          TEXT NOT NULL,          -- USD | USD/shares | shares | ratio
  period_end    DATE,
  fiscal_period TEXT,                   -- FY2024 | Q2-2025 | snapshot
  source        TEXT NOT NULL,          -- xbrl | yfinance
  accession     TEXT,
  as_of         TIMESTAMPTZ NOT NULL,
  UNIQUE (node_id, metric, fiscal_period, source)
);

-- Filings and chunks
CREATE TABLE filing_docs (
  accession   TEXT PRIMARY KEY,
  ticker      TEXT NOT NULL, cik TEXT NOT NULL, form TEXT NOT NULL,
  period_end  DATE, filed_at DATE, source_url TEXT NOT NULL,
  corpus      TEXT NOT NULL DEFAULT 'live',     -- 'live' | 'financebench' (local eval only)
  embed_model TEXT NOT NULL, embed_dim INT NOT NULL,
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(), n_chunks INT
);
CREATE TABLE filing_chunks (
  id        BIGSERIAL PRIMARY KEY,
  accession TEXT NOT NULL REFERENCES filing_docs ON DELETE CASCADE,
  ticker    TEXT NOT NULL,
  corpus    TEXT NOT NULL,
  section   TEXT,                       -- item_1 | item_1a | item_7 | item_7a | item_8 | ... | page (PDF)
  page      INT,                        -- FinanceBench PDFs only (1-indexed)
  ord       INT NOT NULL,
  text      TEXT NOT NULL,
  embedding halfvec(768) NOT NULL,
  tsv       tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
);
CREATE INDEX ON filing_chunks USING hnsw (embedding halfvec_cosine_ops);
CREATE INDEX ON filing_chunks USING gin (tsv);
CREATE INDEX ON filing_chunks (corpus, ticker, section);

-- Ask log (also on SQLite)
CREATE TABLE ask_log (
  id BIGSERIAL PRIMARY KEY, question TEXT NOT NULL, tickers TEXT[], intent TEXT, answer TEXT,
  abstained BOOLEAN, grounding_passed BOOLEAN, regenerated BOOLEAN, citations JSONB, evidence_ids JSONB,
  model TEXT, input_tokens INT, output_tokens INT, cost_usd NUMERIC(10,6), latency_ms INT,
  user_id INT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**Storage budget (free Postgres tiers are ~0.5 GB):**
- ~450-token chunks → a 10-K ≈ 230 chunks, a 10-Q ≈ 90.
- At about 6 KB/chunk (halfvec + text + tsvector + index), **production** gets the live universe only: 50 tickers × (1 10-K + 2 10-Qs) ≈ 20k chunks ≈ 120 MB.
- The **FinanceBench corpus** (≈ 15k chunks) stays in your **local** Postgres only.

---

## 5. Work packages

Each package: one branch off `feat/rag` → PR → CI green → merge. Mark it done in `docs/PROGRESS.md`.

### P2-A — Prep (½ day)
- **Dependencies** (`uv add`): `anthropic`, `pgvector`, `numpy`, `rapidfuzz`, `tenacity`. Dev group: `pymupdf`, `pytest-mock`, `respx`.
- **Postgres:** `docker-compose.yml` `db` image `postgres:16-alpine` → **`pgvector/pgvector:pg16`**.
- **CI** (`ci.yml`): add a `pgvector/pgvector:pg16` service container and a `pytest -m pg` step with `DATABASE_URL` pointing at it. Keep the existing SQLite test job as is.
- **`src/tools/filings.py`:** read the User-Agent from `SEC_USER_AGENT` (currently `"Financial Advisor MVP contact@example.com"`). Leave its brief-oriented text extraction alone; RAG gets its own extractor in P2-C.
- **`src/rag/config.py`:**
  - model ids (`ASK_MODEL_DEFAULT`, `ASK_MODEL_AUTHED`, `EXTRACT_MODEL=claude-haiku-5-5`, `JUDGE_MODEL=claude-sonnet-5-5`)
  - price table (per MTok): Haiku 5.5 $0.10/$0.50 for prompts ≤100k tokens (above that $0.50/$2.50); Sonnet 5.5 $2/$10; Batch = 50% off; Gemini embedding $0.15/M ($0.075 batch, per Google's 2025 posts; recheck)
  - caps
- **`src/rag/llm.py`:**
  - `create()`, `parse(schema)`, `batch_submit()`, `batch_collect()`
  - logs tokens, cost, latency and stop_reason (loguru JSON)
  - SDK `max_retries=5`; on `stop_reason == "max_tokens"`, retry once with double `max_tokens`
  - per-process `Budget(max_usd)` that raises before spending; `estimate()` via `client.messages.count_tokens`
- Alembic migration from §4. Append §2 to `CLAUDE.md` and add `src/rag/` to its architecture tree.
- **Acceptance:** `docker compose up -d db && uv run alembic upgrade head` works; `uv run pytest` (SQLite) passes unchanged; `uv run pytest -m pg` passes with a smoke test that inserts and queries a halfvec.

### P2-B — Knowledge graph into Postgres, with provenance (1 day)
- `scripts/seed_kg.py`: load `src/knowledge_graph/data/sp500_graph.json` → `kg_nodes` (company and macro nodes; copy GICS fields into `props`; seed `props.aliases` with the company name with Inc./Corp./Co./plc stripped) + `kg_edges` (`source='curated'` for `_relationships.py` edges, `'gics'` for auto-generated peer edges; keep the `weight`). Idempotent (upsert).
- `src/rag/kg_store.py`: `KnowledgeGraph.from_db(session)` exposing the **same query API** as `src/knowledge_graph/graph.py` (`get_node`, `get_competitors`, `get_suppliers`, `get_supply_chain`, `get_macro_sensitivity`) plus `neighbors(node, types, k)` and `paths(a, b, max_hops=2)`.
- `get_graph()` returns the DB-backed graph when Postgres is configured and seeded, and falls back to JSON otherwise. `/context/{ticker}` keeps its response shape and adds `source` and `evidence` per edge. The D3 view keeps working.
- **Tests:** a parity test (DB graph == JSON graph for curated edges); path search on a toy graph; fallback when tables are empty.

### P2-C — SEC filings ingestion: text, sections, chunks, embeddings (1½ days)
- **`src/rag/edgar.py`:**
  - `https://data.sec.gov/submissions/CIK{cik:010d}.json` → parallel arrays in `filings.recent` (`form`, `accessionNumber`, `reportDate`, `filingDate`, `primaryDocument`)
  - keep `form` exactly `10-K` / `10-Q`; default **latest 1 10-K + 2 10-Qs** (configurable)
  - primary doc URL: `https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_no_dashes}/{primaryDocument}`
  - CIK from `company_tickers.json` (port `_load_cik_map` from `tools/filings.py`)
  - cache raw HTML under `data/raw/edgar/{cik}/{accession}.html` (gitignored); skip accessions already in `filing_docs`; ≤5 req/s with tenacity backoff
- **`src/rag/html_text.py`:**
  - delete `ix:header` and any `display:none` element **before** extracting text; strip tags **and attributes** (no `us-gaap:`/`ix:` strings may remain)
  - **tables → one line per row**, cells joined with ` | `, empty spacer cells dropped, a lone `$` cell merged into the next cell, `(1,234` + `)` merged; keep header rows (years)
  - normalize unicode (NFKC), non-breaking spaces and dashes
  - **section splitter:** 10-K Items 1, 1A, 7, 7A, 8; 10-Q Part I Items 1, 2. For each Item, use the occurrence followed by the most text (skips the table of contents). Fall back to `section='full'` when splitting fails, and count fallbacks.
- **`src/rag/chunk.py`:** section-bounded chunks of ~450 tokens (approximate with characters/4) with 15% overlap; **never split a table row**; prefix each chunk with `"{company} {form} {period} — {section title}\n"` (helps embeddings and keyword search).
- **`src/rag/embed.py`** (sketch):
  ```python
  import os, numpy as np
  from google import genai
  from google.genai import types

  MODEL, DIM = "gemini-embedding-001", 768
  _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

  def _norm(v):  # required for gemini-embedding-001 below 3072 dims
      a = np.asarray(v, dtype=np.float32); n = np.linalg.norm(a)
      return (a / n).tolist() if n else a.tolist()

  def _embed(texts: list[str], task: str) -> list[list[float]]:
      out = []
      for i in range(0, len(texts), 50):                      # conservative batch size
          r = _client.models.embed_content(
              model=MODEL, contents=texts[i:i + 50],
              config=types.EmbedContentConfig(task_type=task, output_dimensionality=DIM))
          out += [_norm(e.values) for e in r.embeddings]
      return out

  def embed_documents(texts): return _embed(texts, "RETRIEVAL_DOCUMENT")
  def embed_query(text): return _embed([text], "RETRIEVAL_QUERY")[0]
  ```
  Each text must be ≤ 2,048 tokens (the model limit); the chunk size keeps that true. Add tenacity retries on 429/5xx. Store `embed_model`/`embed_dim` on `filing_docs`. Don't switch to `gemini-embedding-2` later without re-embedding everything: its vector space is incompatible.
- **`src/rag/ingest.py` + `scripts/ingest_filings.py --tickers NVDA,AAPL --dry-run`:** fetch → text → sections → chunks → embeddings → insert. Also create a `filing:<accession>` node + a `filed` edge from the company.
- **Default universe:** the 50 largest S&P 500 names by market cap. Read it from the KG (by market cap if present, else a committed `data/universe.txt`). Tickers outside it are ingested on demand when `/ask` sees them (P2-H).
- `.github/workflows/refresh-filings.yml`: weekly cron, `uv run python scripts/ingest_filings.py --universe`. Secrets: `DATABASE_URL`, `GEMINI_API_KEY`, `SEC_USER_AGENT`. Match the existing refresh workflows.
- **Tests:**
  - normalizer fixtures: tables kept as rows; no `us-gaap:` or `ix:`; split `$` / paren cells merged
  - section splitter: 3 HTML fixtures, one with a tricky table of contents
  - chunker: no row splits; metadata complete
  - `embed.py`: mocked client, normalization (unit norm), batching
- **Acceptance:** 50 tickers ingested locally; `results/ingest_summary.md` with filings, chunks, section-split success rate, embedding tokens and cost.

### P2-D — Filings into the knowledge graph (1½ days)
1. **XBRL facts** (`src/rag/xbrl.py`):
   - source: `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json` → `facts["us-gaap"][concept]["units"][unit]`, a list of `{start?, end, val, accn, fy, fp, form, filed}`
   - for each ingested filing, keep facts with `accn == accession`, and match the period:
     - duration metrics: `end == period_end` and duration ≈ 1 year for 10-K (350–380 days) or ≈ 1 quarter for 10-Q (80–100 days)
     - instant metrics: `end == period_end`
   - write to `kg_facts` (`source='xbrl'`, accession, `fiscal_period` like `FY2024`/`Q2-2025`); aliases from Appendix C
   - also backfill annual facts for the FinanceBench companies and years (local eval DB)
2. **Relationships from filing text** (`src/rag/relations.py`, `scripts/extract_relations.py --dry-run`):
   - input: 10-K Items 1, 1A and 7 (one request per section; split sections > 60k tokens)
   - **Claude Haiku 5.5 through the Batch API** (50% off), structured output (`output_config.format` with the JSON schema of `Relations`, Appendix B1), `effort: "low"`
   - **verify** each `evidence_quote`: normalize both sides (NFKC, whitespace, quotes) and require a substring match in the section text; drop failures and count them
   - **entity linking:** normalize the counterparty name (strip Inc./Corp./Ltd./plc/Co./Holdings) → exact match on KG node names + `props.aliases` → `rapidfuzz.fuzz.token_sort_ratio ≥ 92` → otherwise create `org:<slug>` (so TSMC, Foxconn and other non-S&P names enter the graph)
   - **edge mapping (filer = F, counterparty = C):** `customer` → `F –supplies_to→ C`; `supplier` → `C –supplies_to→ F`; `competitor` → `competes_with` (store both directions); `partner` → `strategic_partner`
   - insert with `source='filing'`, `accession`, `evidence`, `confidence`
   - batch flow: persist `batch_id`, poll until `processing_status == "ended"`, stream results, map by `custom_id` (`^[a-zA-Z0-9_-]{1,64}$`, so use short hashes), and handle `errored`/`expired`
3. **Report** `results/kg_ingest.md` (generated):
   - sections processed; relations extracted → verified → linked; new `org:` nodes
   - overlap with curated edges (agreement rate where both exist)
   - **[GAVIN]** labels 30 random new edges (correct / wrong) → precision with a Wilson 95% CI
4. **Tests:** XBRL period selection (duration vs. instant vs. prior-year comparatives excluded); quote verification; name normalization and fuzzy linking fixtures; edge-direction mapping.

### P2-E — Market data into the graph (½ day)
- `src/rag/market_facts.py`: reuse `get_valuation_context` / `get_price_action` from `src/tools/price.py`. Snapshot `price, market_cap, trailing_pe, forward_pe, price_to_book, 52w_high, 52w_low, change_7d` into `kg_facts` (`source='yfinance'`, `fiscal_period='snapshot'`, `as_of`).
- `scripts/refresh_market_facts.py --universe`, added to the existing daily `refresh-news-cache.yml` (or a new daily workflow). `/ask` refreshes a ticker's snapshot on demand if it's older than 24 h.
- Valuation answers cite both the market snapshot and the XBRL fundamentals (e.g., P/E = price ÷ diluted EPS through `calculate`, both inputs cited).

### P2-F — Hybrid retrieval: vector + full-text with RRF (1 day)
- `src/rag/retrieve.py` runs one SQL query (bind `:qvec` as `halfvec(768)`; `SET LOCAL hnsw.ef_search = 40`):
  ```sql
  WITH v AS (
    SELECT id, row_number() OVER (ORDER BY embedding <=> :qvec) AS r
    FROM filing_chunks
    WHERE corpus = :corpus AND ticker = ANY(:tickers)
    ORDER BY embedding <=> :qvec LIMIT 50),
  k AS (
    SELECT c.id, row_number() OVER (ORDER BY ts_rank_cd(c.tsv, q) DESC) AS r
    FROM filing_chunks c, websearch_to_tsquery('english', :qtext) q
    WHERE c.corpus = :corpus AND c.ticker = ANY(:tickers) AND c.tsv @@ q
    ORDER BY ts_rank_cd(c.tsv, q) DESC LIMIT 50)
  SELECT id, SUM(1.0 / (60 + r)) AS rrf
  FROM (SELECT * FROM v UNION ALL SELECT * FROM k) u
  GROUP BY id ORDER BY rrf DESC LIMIT :k;
  ```
- Modes for the ablation: `vector`, `fts`, `hybrid` (default k = 8). Optional filters: form, section, period range.
- Returns `Evidence(kind='filing_chunk', text, source_url, accession, section, page, score)`.
- **Tests:** RRF math (pure Python reference); filters; a `@pytest.mark.pg` integration test on a 3-filing fixture corpus with **precomputed embeddings committed as JSON** (no API calls in CI) that must retrieve a planted passage in the top 3.

### P2-G — Knowledge-graph traversal inside retrieval (1 day)
- **`src/rag/resolve.py`:**
  - tickers: regex for `$NVDA`/`NVDA`, KG names + aliases, then `rapidfuzz`
  - intent via a cheap **Haiku structured output** (Appendix B3), `effort: "low"`: `single_company | comparative | relationship | valuation | sector | unknown`, plus periods mentioned and `needs_calculation`
  - rules short-circuit obvious cases to save calls
- **`src/rag/graph_retrieve.py`:**
  - **single_company / valuation:** `kg_facts` for the entity and periods (XBRL + market snapshot) + top-weighted edges → `Evidence(kind='kg_fact' | 'kg_edge')`
  - **comparative / sector:** expand to **1-hop neighbors** by relevant edge type, top 3 by weight; run P2-F over the expanded ticker set; add facts for each
  - **relationship** ("How exposed is AAPL to TSMC?"): **BFS ≤ 2 hops** over `kg_edges` between the resolved entities. Each path becomes evidence with per-edge provenance: `"AAPL ←supplies_to– TSM (source: AAPL 10-K 2025, Item 1A: '…')"`. Filing-sourced edges rank above curated ones.
- **Evidence budget:** dedupe and cap at 12 items (≤ 8 filing chunks, ≤ 4 KG items) in a stable order.
- **Tests:** intent fixtures (rules path); expansion caps and ordering; path search with provenance on a toy graph.

### P2-H — Cited answers, grounding check, `/ask`, UI (1½ days)
- **`src/rag/evidence.py` → `search_result` blocks:**
  ```python
  def to_search_result(ev: Evidence) -> dict:
      return {
          "type": "search_result",
          "source": ev.source,   # EDGAR URL#item_7 | kg://edge/<id> | xbrl://<cik>/<metric>/<period> | market://<ticker>/<as_of>
          "title": ev.title,     # "NVIDIA 10-K FY2025 — Item 7 MD&A" | "Market data (Yahoo Finance) as of 2026-10-28"
          "content": [{"type": "text", "text": t} for t in ev.blocks],  # sentences / table rows = citable units
          "citations": {"enabled": True},
      }
  ```
- **`src/rag/answer.py`:**
  - request: system = Appendix B2; user content = `[*search_results, {"type": "text", "text": question}]`; `tools=[CALCULATE]`; `output_config={"effort": "medium"}`; `max_tokens=4000`
  - loop ≤ 3 times on `stop_reason == "tool_use"`: append `response.content` unchanged, answer `calculate` with a plain-text `tool_result`
  - parse the final text blocks: each block's `citations[]` (`search_result_location`: `search_result_index`, `cited_text`, block range) maps back to `evidence[search_result_index]`, giving `{n, title, url, cited_text, kind}`
  - `abstained = text.startswith("INSUFFICIENT_EVIDENCE")`
- **`src/rag/calculator.py`:** an AST evaluator allowing numbers, `+ - * /`, `**`, parentheses, `round/abs/min/max`. Never `eval`. It records every computation (inputs → output) for the grounding check.
- **`src/rag/grounding.py`** (the "every answer is grounded" guarantee):
  - extract numbers per text block. Ignore years (1990–2035), quarter labels (Q1–Q4), list numbering and citation markers.
  - every block containing a number must have ≥ 1 citation
  - every number must appear in that block's `cited_text` (normalized: commas, `$`, `%`, `(x)` → `-x`, "billion"/"million" scaling, rounding to the printed precision) **or** equal a `calculate` output whose inputs appear in cited text
  - on failure: regenerate **once** with the failures listed in a follow-up user turn; if it fails again, return `INSUFFICIENT_EVIDENCE` with the reason
  - record `grounding_passed` and `regenerated`
- **`POST /ask`** (in `src/api.py`, router `src/rag/router.py`):
  - request `{question: str (≤ 500 chars), ticker?: str}`
  - response `{answer, abstained, citations:[{n,title,url,cited_text,kind}], tickers, intent, grounding_passed, model, latency_ms, cost_usd}`
  - **models:** anonymous → `ASK_MODEL_DEFAULT` (Haiku); logged-in (`optional_user`) → `ASK_MODEL_AUTHED` (Sonnet)
  - **limits:** slowapi `10/hour` anonymous, `60/day` per user; **daily spend cap** = sum of `ask_log.cost_usd` for today ≥ `ASK_DAILY_USD_CAP` → HTTP 429 with a friendly message
  - **cache:** key = (normalized question, ticker set, latest accession set); TTL 24 h (reuse the `BriefCache` pattern or a new table)
  - **on-demand ingestion:** an unknown ticker inside the KG triggers ingestion if it finishes within ~20 s; otherwise return "indexing this company's filings, try again in a minute" and finish in a background task
  - log everything to `ask_log`
- **UI** (`src/web/app.html`, `static/app.js`, `style.css`):
  - an "Ask about {TICKER}" box on the ticker page + a global Ask route
  - answer rendered with numbered citation chips; hover shows `cited_text`; click opens the EDGAR document (or a KG/market popover)
  - an abstention state, plus a footer: "Answers come only from cited filings and data. Not investment advice."
- **Tests:**
  - mocked-Anthropic API tests: citation mapping, abstention, tool loop
  - grounding unit tests: pass; fail → regenerate → pass; fail twice → abstain; years and quarters ignored; billion/million scaling
  - rate limit and spend cap
  - one `@pytest.mark.live` end-to-end test, skipped in CI

### P2-I — Evaluation (2 days) — turns the bullets into measured claims
See §6 for metrics and statistics.
- **FinanceBench, 10-K subset — 112 questions over 64 filings from 31 companies:**
  - sparse-checkout `https://github.com/patronus-ai/financebench`: `data/financebench_open_source.jsonl`, `data/financebench_document_information.jsonl`, and **only the 64 PDFs** with `doc_type == "10k"` that those questions use (`pdfs/{doc_name}.pdf`)
  - don't commit their PDFs; check the dataset license
  - `evals/qa/financebench.py`: PyMuPDF page text → page-bounded chunks (`section='page'`, `page` 1-indexed) → `corpus='financebench'` in **local** Postgres
  - map FinanceBench company names to KG tickers (hand table; Activision is delisted)
  - backfill XBRL `kg_facts` for those companies and years so KG traversal can help
  - **check page indexing:** fuzzy-match `evidence_text` against pages N−1/N/N+1 to see whether `evidence_page_num` is 0- or 1-indexed, then normalize
- **Stockify set — `evals/qa/custom_set.jsonl` (40 items; [GAVIN] approves gold answers and sources):**
  - 15 sector-relationship questions (need the KG)
  - 10 valuation questions (XBRL + market snapshot; freeze `as_of` for eval)
  - 5 multi-company comparisons
  - 10 unanswerable (metric not reported, company not in filings, future period)
- **Splits** (seed 20261028): FinanceBench 34 dev / 78 test, stratified by `question_type`; custom set 12 dev / 28 test, stratified by category. Iterate on dev only.
- **Configs (ablation):**

  | id | retrieval | KG traversal | grounding check |
  |---|---|---|---|
  | R1 | vector only | no | no |
  | R2 | hybrid (vector + FTS, RRF) | no | no |
  | R3 | hybrid | yes | no |
  | R4 | hybrid | yes | yes (**the shipped system**) |

  Answer model for the headline numbers: **Sonnet 5.5**; Haiku 5.5 also reported for R4 (the public-demo model).
- `evals/qa/run.py --config R4 --split dev|test --model … --dry-run --max-usd 15` writes `evals/qa/results/<run_id>/{answers.jsonl, scorecard.md, scorecard.json}` with git SHA, config, models and date.
- `evals/qa/judge.py` uses **Claude Sonnet 5.5 via Batch**, structured output (Appendix B4). It's blind to the config. A deterministic numeric check runs first for `metrics-generated` items.
- `evals/qa/label.py`: a terminal labeling tool. **[GAVIN]** labels ~50 judged answers → agreement + Cohen's κ (target ≥ 0.7; if lower, refine the rubric on **dev** only).
- `evals/qa/stats.py`: bootstrap 95% CIs (10k resamples, seeded); McNemar's exact test R1→R2→R3→R4; 3 repeats of R4 on dev for run-to-run variance.
- **CI smoke** (`pytest -m pg`, no API calls): the fixture-corpus retrieval test (P2-F) + grounding unit tests. A label-triggered workflow can run 10 live dev questions on Haiku (≤ $0.10).

### P2-J — Ship and document (½ day)
- **Production Postgres** (Neon or Supabase): `CREATE EXTENSION vector;` → `alembic upgrade head` → `scripts/seed_kg.py` → `ingest_filings.py --universe` → `extract_relations.py --universe` → `refresh_market_facts.py --universe`.
- **Render:** add `ANTHROPIC_API_KEY` (the `stockify-prod` key) and `SEC_USER_AGENT`; `ASK_DAILY_USD_CAP=1.00`. Check memory stays under 512 MB (all model calls are remote).
- **README:**
  - "Ask Stockify" section with a GIF
  - the mermaid architecture diagram (§3)
  - **Results** table copied from the test scorecard, with run id
  - `kg_ingest.md` summary
  - "How grounding works" in 5 lines
  - limitations: FinanceBench n = 112 and the open sample only; judge from the same model family (calibrated with κ); universe size; filings lag
  - cold-start note (free Render instance sleeps after 15 min)
- Add §9 as a "Resume ↔ evidence" table in `docs/`.

---

## 6. Evaluation methodology

| Metric | Definition |
|---|---|
| Retrieval recall@8 | FinanceBench: any gold evidence page among retrieved chunk pages. Custom set: any gold source among evidence |
| Answer accuracy | judged `correct` / answerable items. Numeric items: deterministic check first (within 1% or at the question's precision) |
| Accuracy by type | equities / valuations / sector relationships (+ FinanceBench `question_type`) |
| Citation support | share of citations whose `cited_text` supports the sentence it's attached to (judge, sample ≤ 300 citations per config) |
| Grounding-pass rate | share of non-abstained answers passing `grounding.py` on the first try, and after one regeneration |
| Abstention P/R | on the unanswerable items |
| Over-abstention | abstained / answerable |
| Latency, cost | p50/p95 end-to-end; $/question from logged usage |
| Judge validity | agreement and Cohen's κ vs. Gavin's labels |
| Uncertainty | bootstrap 95% CIs; McNemar for paired config comparisons; std over 3 dev repeats |

Hygiene: dev for iteration and test for reporting; record every test run in `PROGRESS.md` with a reason. Never edit gold answers to fit outputs. Report n next to every percentage.

---

## 7. Cost and budget

Claude usage comes from the **Max plan API credits**; Gemini is billed separately. Estimates — replace with `--dry-run` output:

| Item | Model | Est. cost |
|---|---|---|
| Embeddings: live universe (~8M tokens) + FinanceBench (~7M) | gemini-embedding-001 | ~$2 (≈ $1 via Gemini Batch; free tier may cover it) |
| Relation extraction, ~50 10-Ks × 3 sections, Batch | Haiku 5.5 | < $1 |
| Intent classification (eval + live) | Haiku 5.5 | < $0.50 |
| Dev iteration (~500 answers) | Haiku 5.5 | ~$1–2 |
| Ablation R1–R4 on 152 questions | Sonnet 5.5 (~$0.05/question) | ~$30 |
| R4 on Haiku (demo model) | Haiku 5.5 | ~$1 |
| 3 dev repeats of R4 | Sonnet 5.5 | ~$7 |
| Judge + citation-support checks, Batch | Sonnet 5.5 | ~$10 |
| **Total** | | **≈ $50 Claude + ≈ $2 Gemini** |

**Live `/ask` after launch:** ≈ $0.003–0.005/question on Haiku, ≈ $0.04–0.06 on Sonnet. It's capped by `ASK_DAILY_USD_CAP` and the `stockify-prod` workspace limit.

**Lean path (~$20):** run the R1–R4 ablation on Haiku, run only R4 on Sonnet, and skip the dev repeats.

---

## 8. Schedule

About 10 working days (evenings and weekends ≈ 2½–3 weeks).

| Day | Work |
|---|---|
| 1 | P2-A prep; P2-B start |
| 2 | P2-B done; P2-C start (EDGAR + HTML normalizer + tests) |
| 3 | P2-C done (chunker, embeddings, ingest 50 tickers) |
| 4–5 | P2-D (XBRL facts, relation extraction batch, linking, `kg_ingest.md`); P2-E |
| 6 | P2-F hybrid retrieval + fixture test |
| 7 | P2-G graph retrieval |
| 8 | P2-H answer + grounding + `/ask` + UI |
| 9–10 | P2-I eval (FinanceBench load, custom set, judge calibration, ablation, test run); P2-J ship + README |

---

## 9. Resume phrase → artifact checklist

| Resume phrase | Artifact in `financial_advisor` |
|---|---|
| information-retrieval assistant | `POST /ask` + Ask UI (README GIF) |
| ingests SEC filings | `src/rag/edgar.py`, `html_text.py`, `chunk.py`, `ingest.py`; `filing_docs`/`filing_chunks`; `refresh-filings.yml`; `results/ingest_summary.md` |
| and market data | `src/rag/market_facts.py`; `kg_facts` `source='yfinance'` |
| into a knowledge graph | `kg_nodes`/`kg_edges`/`kg_facts` with provenance; `filing:` nodes; XBRL facts; filing-extracted edges with quotes; `results/kg_ingest.md` |
| answers grounded natural-language questions on equities, valuations and sector relationships | scorecard accuracy by type (custom set) + FinanceBench accuracy |
| with source citations | `citations[]` in the API and UI chips linking to EDGAR |
| hybrid retrieval layer: chunking | `src/rag/chunk.py` |
| embeddings | `src/rag/embed.py` (gemini-embedding-001, 768d) |
| vector search | pgvector HNSW on `filing_chunks.embedding`; `retrieve.py` |
| plus knowledge-graph traversal | `src/rag/graph_retrieve.py` (neighbor expansion + 2-hop paths); R2→R3 ablation row |
| every answer grounded in and cites its source filings, not parametric memory | `src/rag/grounding.py`; grounding-pass rate + citation support in the scorecard |
| users can verify every claim | hover `cited_text` + EDGAR links in the UI |
| Stack: Python, NLP, IR, vector search, KG, LLM APIs | all of the above (Claude API + Gemini embeddings) |

---

## 10. Interview talking points this produces

- **Why hybrid + RRF:** filings mix exact tokens (tickers, line items, "Item 1A") with paraphrase. The R1→R2 delta shows how much keyword search adds.
- **Why a KG on top of vectors:** relationship and valuation questions need structured facts and multi-hop paths that chunks don't encode. The R2→R3 delta shows it; every filing-derived edge carries its own quote.
- **Grounding as code, not just prompting:** the number-level check and regenerate-or-abstain policy; grounding-pass rate before and after.
- **Citations vs. structured outputs:** they can't share a request, so extraction uses verified quotes and answers use citations.
- **Eval rigor:** a public benchmark plus a product-specific set; dev/test discipline; judge calibrated with κ; bootstrap CIs and McNemar.
- **Cost engineering:** Batch for offline work, Haiku for the public demo, spend caps, halfvec to fit the free Postgres tier.

---

## Appendix A — Claude Code kickoff prompts

Open the repo in VS Code and use the Claude Code panel. **One package per session; `/clear` between them.**

```
/plan Read docs/PROJECT2-PLAN.md §1–§4 and work package P2-A. Respect the existing stack (FastAPI,
SQLAlchemy 2 + Alembic, Gemini briefs, slowapi, loguru, pytest with SQLite in conftest.py). Propose the
file-level plan, then implement with tests. Do not change the brief pipeline except the SEC User-Agent.
```
Then, for each following package:
```
/plan Read docs/PROJECT2-PLAN.md §2 and work package P2-<X>. Check docs/PROGRESS.md for what's done.
Propose the plan, implement with tests, run `uv run pytest` and `uv run pytest -m pg`, update PROGRESS.md.
```
Before any paid bulk step (P2-C embeddings, P2-D batch, P2-I runs), first run:
```
Run the command with --dry-run and show me the token count and $ estimate. Don't run it for real until I say go.
```

---

## Appendix B — Prompts

### B1. Relation extraction (Haiku 5.5, Batch, structured output)
```python
class Relation(BaseModel):
    counterparty_name: str = Field(description="Company name exactly as written in the text")
    relation: Literal["customer", "supplier", "competitor", "partner"] = Field(
        description="Counterparty's role relative to the filing company")
    evidence_quote: str = Field(description="Verbatim contiguous span from the text, at most ~300 characters, naming the counterparty")
    confidence: Literal["low", "medium", "high"]

class Relations(BaseModel):
    relations: list[Relation]
```
System prompt:
```
You extract business relationships from one section of a company's SEC filing.
Return only relationships the text states explicitly about named companies: customers,
suppliers, competitors, or partners of the filing company. Skip generic mentions
("our competitors include large technology companies"), government agencies, and
subsidiaries of the filer. evidence_quote must be copied verbatim from the text.
If there are none, return an empty list.
```

### B2. Answer system prompt (Sonnet 5.5 / Haiku 5.5, citations on)
```
You answer questions about public companies using ONLY the search results provided:
SEC filing passages, knowledge-graph facts and edges (each with its own source), and
market-data snapshots. Do not use outside knowledge.

- Lead with a direct answer in 1–2 sentences, then the supporting detail.
- Every number must come from a search result or from the calculate tool. When you
  compute something (growth, margins, P/E), call calculate and state the formula.
- State the fiscal period and the source type (10-K, 10-Q, market data as of <date>).
- For relationship questions, describe the path between the companies and its sources.
- If the results don't contain what's needed, reply exactly
  "INSUFFICIENT_EVIDENCE: <what is missing>" and nothing else.
- Plain English for newer investors. Never say buy, sell, hold, or give price targets.
```

### B3. Intent classification (Haiku 5.5, structured output, effort low)
```python
class Intent(BaseModel):
    tickers: list[str]          # only tickers present in the provided candidate list
    intent: Literal["single_company", "comparative", "relationship", "valuation", "sector", "unknown"]
    periods: list[str]          # e.g. ["FY2024", "Q2-2025"]; empty if none
    needs_calculation: bool
```

### B4. Judge rubric (Sonnet 5.5, Batch, structured output)
```
You grade an answer to a financial question. You see the question, the gold answer (and its
justification if any) and the candidate answer. You do not know which system produced it.
verdict:
- "correct": key facts and numbers agree with the gold (rounding within 1% or at the precision
  the question asks for); for qualitative questions, the conclusion matches and nothing contradicts the gold.
- "incorrect": a key number or conclusion is wrong, missing, or contradicts the gold.
- "abstained": the candidate declined (INSUFFICIENT_EVIDENCE).
Ignore style and length. Return {verdict, key_facts_matched: bool, rationale: one sentence}.
```
Citation-support check (separate Batch request per sampled citation): given a sentence and the `cited_text`, return `{supported: bool, rationale}`.

---

## Appendix C — XBRL concept map

| metric | unit | period | us-gaap concept aliases (in order) |
|---|---|---|---|
| revenue | USD | duration | `RevenueFromContractWithCustomerExcludingAssessedTax`, `Revenues`, `SalesRevenueNet` |
| operating_income | USD | duration | `OperatingIncomeLoss` |
| net_income | USD | duration | `NetIncomeLoss` |
| eps_diluted | USD/shares | duration | `EarningsPerShareDiluted` |
| operating_cash_flow | USD | duration | `NetCashProvidedByUsedInOperatingActivities` |
| capex | USD | duration | `PaymentsToAcquirePropertyPlantAndEquipment` |
| total_assets | USD | instant | `Assets` |
| cash_and_equivalents | USD | instant | `CashAndCashEquivalentsAtCarryingValue` |
| stockholders_equity | USD | instant | `StockholdersEquity` |
| shares_outstanding | shares | instant | `dei:EntityCommonStockSharesOutstanding` (from the `dei` taxonomy; it's dated at the cover page, not the period end, so match it **by accession only**) |

Print a coverage table (metric × company) after the first run and extend the aliases where needed, logging each change.

---

## Appendix D — API reference notes (checked 2026-10-28)

**Anthropic (Claude API)**
- **Models and prices per MTok:**
  - `claude-haiku-5-5`: $0.10 in / $0.50 out for prompts ≤100k tokens; $0.50/$2.50 above
  - `claude-sonnet-5-5`: $2/$10
  - `claude-opus-5-5`: $4/$20
  - Batch is 50% off. Cache reads cost 0.05× base on Sonnet 5.5 and 0.1× on Haiku 5.5.
- **Thinking:** on by default on 5.5 models and billed as output. Control it with `output_config={"effort": "low"|"medium"|"high"}`. Sonnet 5.5 rejects `thinking: {"type": "disabled"}`.
- **Structured outputs:** `client.messages.parse(output_format=Model)` (sync), or raw `output_config={"format": {"type": "json_schema", "schema": …}}` in Batch requests. Unsupported in schemas: numeric/string-length constraints, recursion, `additionalProperties` ≠ false. Always validate locally with Pydantic.
- **Search results + citations:**
  - `search_result` blocks go in user turns (top level or inside `tool_result`)
  - citations come back as `search_result_location` with `search_result_index`, `start_block_index`, `end_block_index`, `cited_text`
  - whole-block granularity, so split content into small blocks
  - the citation setting must be the same for every search result in a request
  - **can't be combined with structured outputs** in one request (400)
- **Batch API:** ≤100k requests or 256 MB per batch; most finish within 1 hour; results kept 29 days; `custom_id` matches `^[a-zA-Z0-9_-]{1,64}$`.
- **Max plan API credits:** $100 (5x) / $200 (20x) monthly, claimed by linking a Console organization. They cover the Messages API, Batches and the Agent SDK, not embeddings.
- **Docs:** platform.claude.com/docs/en/build-with-claude/{search-results, citations, structured-outputs, batch-processing, effort, thinking} · about-claude/pricing · support.claude.com article 17154008 (Max API credits).

**Google (Gemini embeddings)**
- **Model:** `gemini-embedding-001`, text only. Default output is 3072 dims; supported range 128–3072; Google recommends 768, 1536 or 3072.
- **Normalization:** outputs below 3072 dims **must be L2-normalized** by you.
- **Task types:** `RETRIEVAL_DOCUMENT` for indexed chunks, `RETRIEVAL_QUERY` for questions.
- **Limits:** 2,048 input tokens per text. The Batch API is supported at 50% of the standard price.
- **Upgrading:** `gemini-embedding-2` exists, but its vector space is incompatible with 001, so switching requires re-embedding everything.
- **Call shape:** `client.models.embed_content(model="gemini-embedding-001", contents=[...], config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT", output_dimensionality=768))`.
- **Pricing:** $0.15 per 1M input tokens, $0.075 via Batch (from Google's 2025 announcement posts; recheck the current pricing page).
- **Docs:** ai.google.dev/gemini-api/docs/embeddings.

**SEC EDGAR**
- `data.sec.gov/submissions/CIK##########.json` · `data.sec.gov/api/xbrl/companyfacts/CIK##########.json` · `www.sec.gov/files/company_tickers.json`.
- Send a descriptive User-Agent with contact info; stay ≤ 10 requests/second (this plan uses 5).

---

## Appendix E — PROGRESS.md template

```markdown
# Project 2 progress (docs/PROJECT2-PLAN.md)
| Package | Status | PR | Date | Notes / run ids / cost |
|---|---|---|---|---|
| P2-A Prep | ☐ | | | |
| P2-B KG → Postgres | ☐ | | | |
| P2-C Filings ingestion | ☐ | | | |
| P2-D Filings → KG | ☐ | | | |
| P2-E Market facts | ☐ | | | |
| P2-F Hybrid retrieval | ☐ | | | |
| P2-G Graph retrieval | ☐ | | | |
| P2-H Answers + grounding + /ask + UI | ☐ | | | |
| P2-I Evaluation | ☐ | | | |
| P2-J Ship + README | ☐ | | | |

## Spend log
| Date | Step | Provider | $ (estimate → actual) |
|---|---|---|---|

## Test-split runs (each needs a reason)
| Date | run_id | config | reason |
|---|---|---|---|

## Decisions
- YYYY-MM-DD: <decision> — <why>
```
