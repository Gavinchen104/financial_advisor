# CLAUDE.md — Stockify

This file gives Claude Code the context it needs to work productively in this repo. Keep it short, keep it honest, update it when things change.

## What we're building

**Stockify** — a plain-English stock brief platform for first-year investors. Given a ticker, the brief answers three questions:

1. What happened recently (factual)
2. Why the price moved (cited to primary sources)
3. What it means for someone new to investing (plain English, no jargon)

Users can create an account, build a watchlist, track holdings, and view a visual knowledge graph of each stock's competitors, suppliers, customers, and macro sensitivities.

**The product is past the throwaway-MVP stage.** It's moving toward production-ready: accounts, persistence, rate limiting, Docker. Still not at scale (a few hundred users), but the code should be shippable.

## Target user

"Alex" — 22–28, invested for <18 months, holds 3–8 positions, $500–$15k portfolio, learns from TikTok/Reddit, feels mild anxiety about not understanding what they own. Plain English, no condescension, no jargon without inline definitions.

## Non-goals (explicit)

- Not handling options, derivatives, crypto, or technical analysis
- Not giving trade recommendations ("buy", "sell", "hold" — avoid)
- Not supporting non-US tickers
- Not building native mobile apps (responsive web only)
- Not processing payments yet (accounts are free)

## Architecture

```
financial_advisor/
├── CLAUDE.md                       # this file
├── README.md                       # setup + run instructions
├── pyproject.toml                  # deps via uv
├── Dockerfile                      # production image
├── docker-compose.yml              # one-command spin-up
├── .env.example                    # required env vars, no secrets
├── src/
│   ├── agent.py                    # orchestrator: parallel fetch → single Gemini call
│   ├── api.py                      # FastAPI app (brief + context + auth + user features)
│   ├── auth.py                     # signup/login/logout/me, JWT cookie, password hashing
│   ├── db.py                       # SQLAlchemy engine, session, Base
│   ├── models.py                   # User, WatchlistItem, Holding, BriefCache
│   ├── logging_config.py           # loguru setup (structured JSON logs)
│   ├── tools/
│   │   ├── news.py                 # recent news + daily cache
│   │   ├── filings.py              # latest SEC 10-K/10-Q/8-K
│   │   ├── price.py                # price + fundamentals + analyst + insider + balance + valuation + technicals
│   │   ├── context.py              # knowledge graph → live 7-day perf
│   │   └── brief_writer.py         # parse Gemini markdown → structured JSON
│   ├── prompts/
│   │   └── system.md               # system prompt (tone + how-to-use-data rules)
│   ├── knowledge_graph/
│   │   ├── graph.py                # KnowledgeGraph loader + query API (singleton)
│   │   ├── _relationships.py       # curated supplier/customer/competitor EDGES
│   │   ├── _macro.py               # MACRO_FACTORS + sector/company macro sensitivity
│   │   └── data/sp500_graph.json   # compiled graph (checked in)
│   └── web/
│       ├── index.html              # landing / signed-out
│       ├── app.html                # signed-in single-page app
│       └── static/
│           ├── style.css           # Claude-aesthetic design tokens
│           └── app.js              # SPA routes, auth, watchlist, graph viz
├── scripts/
│   ├── smoke_test.py               # runs the agent on 3 known tickers
│   ├── build_knowledge_graph.py    # rebuilds sp500_graph.json
│   └── refresh_news_cache.py       # daily pre-warm of hot-list news
├── .github/workflows/
│   ├── ci.yml                      # lint, import check, smoke test
│   ├── refresh-knowledge-graph.yml # weekly cron
│   └── refresh-news-cache.yml      # daily cron
├── data/
│   └── app.db                      # SQLite (gitignored)
└── logs/
    └── briefs.jsonl                # append-only request log
```

## Stack

- **Python 3.11+**, FastAPI, uv for dep management
- **LLM:** Google Gemini via `google-genai` — `gemini-2.5-flash` with `GoogleSearch` tool
- **DB:** SQLite via SQLAlchemy 2.x. Easy to swap to Postgres later (change `DATABASE_URL`).
- **Auth:** email + password, bcrypt via passlib, JWT in httpOnly cookie
- **Rate limiting:** slowapi (per-IP for unauth, per-user for auth)
- **Logging:** loguru, JSON output in prod
- **Frontend:** vanilla JS SPA (no build step), Tailwind via CDN, D3 for graph viz, marked for markdown

Env vars required: `GEMINI_API_KEY`, `SECRET_KEY` (JWT signing), `DATABASE_URL` (defaults to SQLite).

## Knowledge graph

`src/knowledge_graph/` holds a compiled graph of S&P 500 companies plus curated non-S&P externals (TSM, ASML, NVO, etc.). Three edge types:

- `competes_with` — auto-generated from shared GICS sub-industry (weight 0.5) + curated overrides
- `supplies_to` — hand-curated supplier → customer edges
- `macro_sensitivity` — sector-default sensitivities (e.g., Energy ↔ crude oil) + company-specific overrides

At request time, `get_knowledge_context(ticker)` pulls top relationships and enriches each with live 7-day `pct_change` from yfinance. The frontend renders a visual D3 force-directed graph using the same data.

Rebuild with: `uv run python scripts/build_knowledge_graph.py` (also runs weekly via GitHub Actions).

## Agent design

The agent is **not** a tool-calling loop. It's an orchestrator:

1. `agent.run_agent` pre-checks the ticker has price data, then fans out 11 data fetches in parallel via `ThreadPoolExecutor`
2. All results serialized into one user message and sent to Gemini with the system prompt
3. Gemini has `GoogleSearch` available for verification
4. `parse_brief` splits the response into `{what_happened, why_moved, what_it_means, sources_text, full_brief, disclaimer}`

Per-user brief results are cached in the `brief_cache` table for 4 hours so re-viewing a stock doesn't re-pay Gemini.

## Output format — the 3-layer brief

```
## What happened
1–2 sentences. Factual. No interpretation.

## Why the price moved
2–3 sentences. Must cite at least one primary source. Inline citations [1], [2].

## What it means for a first-year investor
1–2 sentences. Plain English. Contextualize.
Define technical terms inline in parentheses.

## Sources
- [Title of source 1](https://full-url-here)
- [Title of source 2](https://full-url-here)
```

## Voice and tone rules (enforced in system prompt)

- Plain English. Define terms inline on first use.
- Forbidden: "buy", "sell", "hold", "strong buy", "price target", "should", "recommend", "must", "need to"
- Acceptable: "tends to", "historically", "one way to think about this", "some investors view"
- No hype, no FOMO, no emojis, no exclamation marks.

## Disclaimers (non-negotiable, auto-appended to every brief)

```
This is educational information, not investment advice. Stockify does not
recommend buying or selling any security. Do your own research and consider
consulting a licensed financial advisor.
```

## Things Claude Code should ask before doing

- Adding a new top-level dependency
- Changing the DB schema (write a migration, don't silently mutate)
- Changing the brief output schema (`BriefResponse`)
- Modifying the knowledge graph schema or rebuilding `sp500_graph.json`
- Adding payment, email delivery, or third-party OAuth

## Things Claude Code should just do

- Fix bugs, improve error handling, refactor within a file
- Improve the system prompt for tone/clarity
- Improve the design system or component polish
- Keep the smoke test passing

## Running it

```bash
# install
uv sync

# set env
cp .env.example .env
# fill in GEMINI_API_KEY + SECRET_KEY

# (one-time) build the knowledge graph
uv run python scripts/build_knowledge_graph.py

# run API (serves frontend at /)
uv run uvicorn src.api:app --reload

# or via docker
docker compose up --build

# smoke test
uv run python scripts/smoke_test.py
```

## Known limitations

- `yfinance` is unofficial and occasionally flaky — acceptable
- SEC EDGAR has a 10 req/sec limit — fine for our volume
- Knowledge graph only covers S&P 500 + curated externals; tickers outside get a partial brief
- SQLite is single-writer; good for ~100 concurrent users, swap to Postgres if that becomes a constraint
