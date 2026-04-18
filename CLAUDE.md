# CLAUDE.md — DinoDigest MVP

This file gives Claude Code the context it needs to work productively in this repo. Keep it short, keep it honest, update it when things change.

## What we're building

**DinoDigest MVP** — a throwaway prototype to generate personalized stock briefs for first-year investors. The brief answers three questions for a given ticker:

1. What happened recently (factual)
2. Why the price moved (cited to primary sources)
3. What it means for someone new to investing (plain English, no jargon)

**This MVP exists to support customer discovery calls, not to launch.** It will be rewritten. Optimize for speed-to-demo, not for production quality.

## Target user (keep this in mind for every decision)

"Alex" — 22–28, invested for <18 months, holds 3–8 positions, $500–$15k portfolio, learns from TikTok/Reddit, feels mild anxiety about not understanding what they own. Plain English, no condescension, no jargon without inline definitions.

## Non-goals (explicit)

- Not building auth, accounts, payments, email delivery, or scheduling
- Not building a database — JSON files or in-memory is fine
- Not handling options, derivatives, crypto, or technical analysis
- Not giving trade recommendations ("buy", "sell", "hold" — avoid)
- Not optimizing for latency below ~30 seconds per brief
- Not building tests beyond smoke tests for the agent pipeline

## Architecture

```
financial_advisor/
├── CLAUDE.md                       # this file
├── README.md                       # setup + run instructions
├── pyproject.toml                  # deps via uv
├── .env.example                    # required env vars, no secrets
├── src/
│   ├── agent.py                    # orchestrator: parallel fetch → single Gemini call
│   ├── api.py                      # FastAPI app, one endpoint: POST /brief
│   ├── tools/
│   │   ├── news.py                 # recent news (headlines + body text)
│   │   ├── filings.py              # latest SEC 10-K/10-Q/8-K (8-Ks include extracted text)
│   │   ├── price.py                # price, earnings, market context, analyst, insider,
│   │   │                           # balance sheet, valuation, technical levels
│   │   ├── context.py              # knowledge graph → live 7-day perf for related tickers
│   │   └── brief_writer.py         # parse Gemini markdown into structured JSON
│   ├── prompts/
│   │   ├── system.md               # system prompt (tone + how-to-use-data rules)
│   │   └── brief_template.md       # output structure
│   ├── knowledge_graph/
│   │   ├── graph.py                # KnowledgeGraph loader + query API (singleton)
│   │   ├── _relationships.py       # curated supplier/customer/competitor EDGES
│   │   ├── _macro.py               # MACRO_FACTORS + sector/company macro sensitivity
│   │   └── data/sp500_graph.json   # compiled graph (checked in)
│   └── web/
│       └── index.html              # single-page UI, vanilla JS, calls /brief
├── scripts/
│   ├── smoke_test.py               # runs the agent on 3 known tickers
│   └── build_knowledge_graph.py    # rebuilds sp500_graph.json from S&P 500 + curated edges
└── logs/
    └── briefs.jsonl                # append-only request log (ts, ticker, experience_level)
```

## Stack

- **Python 3.11+**, FastAPI, uv for dep management
- **LLM:** Google Gemini via `google-genai` — `gemini-2.5-flash`, with the `GoogleSearch` tool enabled for verification. (We started on Claude but switched to Gemini for the built-in Search tool and cost.)
- **Data sources:**
  - News: web scraping via `httpx` + `beautifulsoup4` / `lxml`
  - Filings: SEC EDGAR (free, no key) — `https://data.sec.gov/submissions/CIK{cik}.json`
  - Prices + fundamentals + analyst + insider + balance sheet + valuation + technicals: `yfinance`
  - Knowledge graph: curated JSON compiled from S&P 500 constituents + hand-written supplier/customer/competitor/macro edges
- **Frontend:** one HTML file, vanilla JS fetch, Tailwind via CDN. No build step.

Env var required: `GEMINI_API_KEY`.

If you're considering adding a dependency, ask first. We're keeping the surface area small.

## Agent design

The agent is **not** a tool-calling loop. It's an orchestrator:

1. User submits `{ticker, experience_level}` to `POST /brief`
2. `agent.run_agent` checks that the ticker has price data, then fans out 11 data fetches in parallel via a `ThreadPoolExecutor`:
   - `get_recent_news`, `get_latest_filing`, `get_price_action`, `get_earnings_data`, `get_market_context`, `get_analyst_data`, `get_insider_transactions`, `get_balance_sheet`, `get_valuation_context`, `get_technical_levels`, `get_knowledge_context`
3. All results are serialized into a single user message and sent to Gemini along with the system prompt
4. Gemini has the `GoogleSearch` tool available to verify or expand anything
5. `parse_brief` splits the response into `{what_happened, why_moved, what_it_means, sources_text, full_brief, disclaimer}` and the API returns it

If a ticker has no price data (invalid/delisted), the agent skips the enhanced fetches, disables Google Search, and lets Gemini write a graceful "data unavailable" brief.

If you're thinking of adding another data source, ask first — the prompt is already dense.

## Knowledge graph

`src/knowledge_graph/` holds a compiled graph of S&P 500 companies plus curated non-S&P external nodes (TSM, ASML, NVO, etc.). Edges are three types:

- `competes_with` — auto-generated from shared GICS sub-industry (weight 0.5) + curated overrides with higher weights
- `supplies_to` — hand-curated supplier → customer edges
- `macro_sensitivity` — sector-default sensitivities (e.g., Energy ↔ crude oil) plus company-specific overrides

At request time, `get_knowledge_context(ticker)` pulls the top competitors/suppliers/customers/macro factors from the graph and enriches each with a live 7-day `pct_change` from yfinance. The system prompt instructs Gemini to only mention relationships where the move is meaningful (>2%) and where it helps explain the week's price action.

Rebuild with: `uv run python scripts/build_knowledge_graph.py`

## Output format — the 3-layer brief

Every brief must have exactly these sections. The system prompt enforces this.

```
## What happened
1–2 sentences. Factual. No interpretation.

## Why the price moved
2–3 sentences. Must cite at least one primary source. Inline citations [1], [2].

## What it means for a first-year investor
1–2 sentences. Plain English. Contextualize — normal volatility, material
business change, sector-wide move? Never recommend action.
Define technical terms inline in parentheses.

## Sources
- [Title of source 1](https://full-url-here)
- [Title of source 2](https://full-url-here)
```

Sources must be proper markdown links `[Title](URL)` — never bare URLs. Every input section has a `source_url` field; Gemini is instructed to use those exact URLs and never fabricate.

## Voice and tone rules (enforced in system prompt)

- Plain English. Define terms inline on first use: "EPS (earnings per share)", "P/E (price divided by annual earnings)".
- Forbidden: "buy", "sell", "hold", "strong buy", "price target", "should", "recommend", "must", "need to"
- Acceptable: "tends to", "historically", "one way to think about this", "some investors view"
- No hype, no FOMO, no emojis, no exclamation marks.
- If a section can't be answered confidently, say so — never invent facts.

## Disclaimers (non-negotiable, auto-appended to every brief)

```
This is educational information, not investment advice. DinoDigest does not
recommend buying or selling any security. Do your own research and consider
consulting a licensed financial advisor.
```

## Running it

```bash
# install
uv sync

# set env
cp .env.example .env
# add GEMINI_API_KEY

# (one-time) build the knowledge graph
uv run python scripts/build_knowledge_graph.py

# run API (serves frontend at /)
uv run uvicorn src.api:app --reload

# smoke test
uv run python scripts/smoke_test.py
```

## Smoke test cases

`scripts/smoke_test.py` runs the agent on these tickers and prints output. Useful for catching regressions and sanity-checking tone.

- `NVDA` — high-news stock, should have lots to say
- `KO` — boring stock, should gracefully say "not much happened"
- `ZZZZ` — invalid ticker, should fail gracefully

## What "done" looks like for MVP

- [x] `POST /brief` returns a valid 3-layer brief for any real US ticker in <60s
- [x] Frontend has a ticker input, a submit button, and renders the brief as markdown
- [x] Smoke test passes on NVDA, KO, and handles ZZZZ gracefully
- [x] Disclaimer appears on every brief
- [x] README tells a new person how to run it in <5 minutes

That's it. If you're adding more, you're building the wrong thing.

## Things Claude Code should ask before doing

- Adding a new dependency
- Adding a new data-fetch tool to the parallel fan-out
- Changing the output schema (`BriefResponse` in `api.py`)
- Adding any form of persistence beyond JSONL logs
- Modifying the knowledge graph schema or rebuilding `sp500_graph.json`
- Touching anything auth/payment/email related (we said no)

## Things Claude Code should just do

- Fix bugs
- Improve the system prompt to enforce tone rules
- Refactor within a file
- Add inline documentation
- Improve error handling and graceful failures
- Keep the smoke test passing

## Known limitations we're accepting for MVP

- No rate limiting — runs locally or on a cheap VPS, fine for <100 users
- No caching per request — every brief re-fetches (knowledge graph itself is loaded once as a module singleton)
- Yahoo Finance (`yfinance`) is unofficial and occasionally flaky — acceptable
- SEC EDGAR has a 10 req/sec limit — fine for our volume
- No support for non-US tickers
- Knowledge graph only covers S&P 500 + a handful of curated externals; tickers outside that set get `{"error": "... not found in knowledge graph"}` and the brief is written without that context

## Current open questions (update as we learn)

- Should the agent try to detect earnings weeks and handle them differently? (Probably yes, but post-MVP)
- Do we return markdown or rendered HTML from the API? (Decision: markdown, frontend renders)
- Do we log briefs for later review/eval? (Decision: yes, append-only JSONL in `/logs`, no PII — currently logging only ts/ticker/experience_level, not the brief body)