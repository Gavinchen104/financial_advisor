# Stockify

Plain-English stock briefs for first-year investors.

**Live:** <https://stockify-qtnj.onrender.com/>

Enter any US ticker. Get three things in plain English:

1. **What happened** — a factual summary of the past week
2. **Why it moved** — cited analysis from earnings, analyst consensus, filings, insider activity, and a curated knowledge graph
3. **What it means** — a plain-English takeaway, never a recommendation

Plus: accounts, a watchlist, a portfolio tracker with live P&L, weekly-move alerts, a side-by-side compare view, a ticker-name autocomplete, and an interactive D3 knowledge graph of each stock's competitors, suppliers, customers, and macro sensitivities.

---

## Who it's for

"Alex" — 22–28, first 18 months of investing, 3–8 positions, $500–$15k portfolio, learns from TikTok and Reddit, wants to feel less in the dark about what they own. Briefs are written to meet that user: plain English, inline term definitions, zero jargon without glossing, and zero "should I buy" advice. The system prompt forbids the words *buy*, *sell*, *hold*, *price target*, *recommend*.

## What makes it different

- **Three-layer brief format** — not a news feed, not an analyst report. Facts / reasoning / plain-English framing, with required primary-source citations.
- **Knowledge graph** — every brief is written with the context of the stock's competitors, suppliers, customers, and macro factors. The same graph powers an interactive force-directed viz.
- **No recommendations, ever** — enforced in the system prompt and verified by evals. Stockify is educational, not advisory.
- **Fast** — 11 data fetches run in parallel, then a single Gemini call. Briefs land in ~30 s and are cached for 4 hours.
- **Honest sourcing** — every claim in "Why it moved" must cite a primary source. Sources render as clickable links.

---

## Stack

- **Backend:** Python 3.11+, FastAPI, SQLAlchemy 2.x, Alembic migrations
- **LLM:** Google Gemini 2.5 Flash via `google-genai`, with `GoogleSearch` tool enabled for primary-source verification
- **Database:** SQLite for local dev, Postgres (psycopg v3) in production
- **Auth:** email + password, bcrypt, JWT in an httpOnly cookie
- **Frontend:** vanilla JS SPA (no build step), Tailwind-free custom CSS tokens, D3 v7 for the graph, `marked` for markdown
- **Rate limiting:** slowapi (per-IP anon, per-user authed)
- **Logging:** loguru (pretty in dev, structured JSON in prod)
- **Tests:** pytest + freezegun + FastAPI TestClient, 67 tests covering auth, brief cache TTL, knowledge graph, API endpoints, and parser
- **Deploy:** Docker + Render (Postgres + web service)

---

## Sample brief

```
## What happened
NVIDIA closed the week up 4.2%, touching a fresh intraday high after
announcing deeper AI-chip partnerships with three major cloud providers
at its GTC developer conference.

## Why the price moved
Management raised data-center revenue guidance for the coming quarter,
citing continued demand for its Blackwell-generation GPUs from
hyperscalers (large cloud providers like AWS, Azure, and Google Cloud)
[1]. Most analysts responded with upward price-target revisions, though
a few flagged valuation concerns at a forward P/E (price-to-earnings
ratio based on expected future profits) near 36 [2].

## What it means for a first-year investor
Moves like this — several percent in a week on forward-looking guidance
— are typical for large-cap names at the center of a major theme like
AI. The stock's day-to-day price tends to track investor expectations
about future AI-hardware demand more than today's earnings number.

## Sources
- [NVIDIA GTC keynote](https://www.nvidia.com/gtc/)
- [Analyst revisions via MarketWatch](https://www.marketwatch.com/investing/stock/nvda/analystestimates)
```

A disclaimer ("This is educational information, not investment advice…") is appended to every brief.

---

## Quick start

**Requirements:** Python 3.11+ and [uv](https://github.com/astral-sh/uv).

```bash
uv sync                                                  # install deps
cp .env.example .env                                     # set GEMINI_API_KEY + SECRET_KEY
uv run python scripts/build_knowledge_graph.py           # one-time: compile the graph
uv run alembic upgrade head                              # create local SQLite tables
uv run uvicorn src.api:app --reload                      # start the API + frontend
```

Open <http://localhost:8000>, sign up, and you're in the app.

## Docker

```bash
docker compose up --build
```

Brings up Postgres + the web service. App on `:8000`, Postgres on `:5432`.

---

## Database & migrations

Alembic is authoritative for schema. By default `DATABASE_URL` points at SQLite (`./data/app.db`); set it to a Postgres URL in prod:

```
postgresql+psycopg://user:pass@host:5432/dbname
```

Render hands out `postgres://…` — `src/db.py` normalizes that to the SQLAlchemy 2.x + psycopg v3 form automatically, and adds `pool_pre_ping` so idle-dropped connections recover cleanly.

Migrations run on app startup via `init_db()`. Common commands:

```bash
uv run alembic upgrade head                              # apply pending
uv run alembic revision --autogenerate -m "what changed" # after editing models.py
uv run alembic downgrade -1                              # roll back one
```

---

## Testing

```bash
uv run pytest -q                                         # 67 tests, ~10s
uv run pytest --cov=src --cov-report=term-missing        # with coverage
```

CI runs lint + import check + pytest on every push. A smoke test against the real Gemini API runs optionally when `vars.RUN_SMOKE_TESTS=true`.

```bash
uv run python scripts/smoke_test.py                      # end-to-end against real API
```

---

## Architecture

```
src/
  api.py            FastAPI app — routes for brief, context, auth, portfolio, alerts, search, health
  auth.py           Signup/login/logout/me, bcrypt, JWT session cookie
  portfolio.py      Watchlist + holdings endpoints with live price enrichment
  agent.py          Orchestrator — 11 parallel data fetches → single Gemini call
  db.py             SQLAlchemy engine, session, Base, DATABASE_URL normalization
  models.py         User, WatchlistItem, Holding, BriefCache
  logging_config.py loguru setup (dev pretty / prod JSON)
  tools/            news, filings, price, context, brief_writer
  prompts/          system prompt — tone rules, output format, safety
  knowledge_graph/  compiled S&P 500 graph, curated edges, macro factors
  web/              index.html (landing + sample brief + demo graph), app.html (SPA shell), static/ (CSS + JS + D3)
scripts/
  smoke_test.py                   end-to-end against real Gemini
  build_knowledge_graph.py        (re)compile the graph into sp500_graph.json
  refresh_news_cache.py           daily cron — pre-warm hot-list news
migrations/                       Alembic schema history
tests/                            pytest suite + fixtures
.github/workflows/
  ci.yml                          lint, import, pytest, optional smoke
  refresh-knowledge-graph.yml     weekly cron
  refresh-news-cache.yml          daily cron
```

The agent is **not** a tool-calling loop. It's an orchestrator: pre-check the ticker has price data → fan out 11 data fetches via `ThreadPoolExecutor` → concatenate into one user message → single Gemini call with `GoogleSearch` enabled → parse the markdown response into a structured `BriefResponse`. Per-ticker brief results are cached in the `brief_cache` table for 4 hours.

For graph internals, see [docs/knowledge_graph.md](docs/knowledge_graph.md).

---

## API

**Public:**

| Method | Path | Purpose |
|---|---|---|
| POST | `/brief` | Generate the 3-layer brief (cached 4h, rate-limited 20/hour) |
| GET | `/context/{ticker}` | Knowledge-graph context with live 7-day prices |
| GET | `/search?q=…` | Type-ahead over 500+ company names → tickers |
| GET | `/health` | Liveness check |

**Authenticated (session cookie):**

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/signup` | Create account, returns user + sets cookie |
| POST | `/auth/login` | Log in, sets cookie |
| POST | `/auth/logout` | Clear cookie |
| GET | `/auth/me` | Current user |
| GET | `/watchlist` | Watchlist with live 7d prices |
| POST | `/watchlist` | Add ticker |
| DELETE | `/watchlist/{ticker}` | Remove ticker |
| GET | `/portfolio` | Holdings + totals + unrealized P&L |
| POST | `/holdings` | Add or merge a holding (weighted-avg cost basis) |
| PATCH | `/holdings/{id}` | Update shares or cost |
| DELETE | `/holdings/{id}` | Remove |
| GET | `/alerts` | Watchlist tickers moving more than 5% in 7 days |

---

## Deploying to Render

1. Create a Postgres instance on Render (free tier is fine).
2. Create a web service from this repo, Python build command `uv sync`, start command `uv run uvicorn src.api:app --host 0.0.0.0 --port $PORT`.
3. Environment variables:
   - `GEMINI_API_KEY` — required
   - `SECRET_KEY` — any long random string
   - `DATABASE_URL` — the **Internal Database URL** from the Postgres instance (same region)
   - `ENV=prod`
4. Deploy. `init_db()` runs `alembic upgrade head` on boot, so the schema is created on first deploy and migrated on every subsequent deploy.

---

## Known limitations

- `yfinance` is unofficial and occasionally flaky — accepted for now.
- SEC EDGAR has a 10 req/sec limit — fine for Stockify's volume.
- The knowledge graph covers the S&P 500 plus ~40 curated non-S&P externals (TSM, ASML, NVO, etc.). Tickers outside that set return a partial brief.
- SQLite is single-writer (fine for local dev); prod runs on Postgres.

## Disclaimer

Stockify is educational information, not investment advice. It does not recommend buying or selling any security. Do your own research and consider consulting a licensed financial advisor.

## License

MIT — see [LICENSE](LICENSE).
