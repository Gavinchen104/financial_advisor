# Stockify

Plain-English stock briefs for first-year investors. Enter a US ticker, get:

1. **What happened** — factual summary of the past week
2. **Why it moved** — cited analysis (earnings, analyst, filings, macro)
3. **What it means** — plain English takeaway, never a recommendation

Plus: accounts, a watchlist, a simple portfolio tracker, weekly-move alerts, a side-by-side compare view, and an interactive D3 knowledge graph that shows each stock's competitors, suppliers, customers, and macro sensitivities.

## Setup

**Requirements:** Python 3.11+, [uv](https://github.com/astral-sh/uv)

```bash
# Install dependencies
uv sync

# Copy and fill in env vars
cp .env.example .env
# Edit .env — set GEMINI_API_KEY and SECRET_KEY

# One-time: build the knowledge graph
uv run python scripts/build_knowledge_graph.py
```

## Run

**Local:**
```bash
uv run uvicorn src.api:app --reload
# Open http://localhost:8000
```

**Docker:**
```bash
docker compose up --build
# Open http://localhost:8000
```

Sign up from the landing page, then you're in the app. Dashboard is at `/app`.

## Smoke test

```bash
uv run python scripts/smoke_test.py
```

Runs the agent on NVDA (active), KO (quiet), and ZZZZ (invalid) and prints pass/fail.

## Architecture

```
src/
  api.py            FastAPI app: routes for brief, context, auth, portfolio, alerts, health
  auth.py           Signup/login/logout/me, bcrypt, JWT session cookie
  portfolio.py      Watchlist + holdings endpoints with live price enrichment
  agent.py          Orchestrator: parallel fetch → single Gemini call
  db.py             SQLAlchemy engine, session, Base
  models.py         User, WatchlistItem, Holding, BriefCache
  logging_config.py loguru setup (dev pretty / prod JSON)
  tools/            news, filings, price, context, brief_writer
  prompts/          system prompt
  knowledge_graph/  compiled S&P 500 graph + curated edges + macro
  web/              index.html (landing), app.html (SPA shell), static/ (CSS+JS+D3)
scripts/
  smoke_test.py
  build_knowledge_graph.py
  refresh_news_cache.py
.github/workflows/
  ci.yml
  refresh-knowledge-graph.yml     weekly cron
  refresh-news-cache.yml          daily cron
```

## API

Authenticated (session cookie):

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/signup` | Create account, returns user + sets cookie |
| POST | `/auth/login` | Log in, sets cookie |
| POST | `/auth/logout` | Clear cookie |
| GET | `/auth/me` | Current user |
| GET | `/watchlist` | List watchlist with live 7d prices |
| POST | `/watchlist` | Add ticker |
| DELETE | `/watchlist/{ticker}` | Remove ticker |
| GET | `/portfolio` | Holdings + totals + P&L |
| POST | `/holdings` | Add/merge holding (averages cost basis) |
| PATCH | `/holdings/{id}` | Update shares/cost |
| DELETE | `/holdings/{id}` | Remove |
| GET | `/alerts` | Watchlist tickers moving >5% |

Public:

| Method | Path | Purpose |
|---|---|---|
| POST | `/brief` | Generate the 3-layer brief (cached 4h in DB) |
| GET | `/context/{ticker}` | Knowledge graph context with live 7d prices |
| GET | `/health` | Liveness check |

## Disclaimer

Stockify is educational information, not investment advice.
