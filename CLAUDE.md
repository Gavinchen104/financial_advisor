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
dinodigest/
├── CLAUDE.md                  # this file
├── README.md                  # setup + run instructions
├── pyproject.toml             # deps via uv or poetry
├── .env.example               # required env vars, no secrets
├── src/
│   ├── agent.py               # main agent loop using Claude Agent SDK
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── news.py            # fetch recent news for a ticker
│   │   ├── filings.py         # fetch latest SEC filing (10-K/10-Q/8-K)
│   │   ├── price.py           # fetch recent price action
│   │   └── brief_writer.py    # format the final 3-layer brief
│   ├── prompts/
│   │   ├── system.md          # agent system prompt
│   │   └── brief_template.md  # output structure
│   ├── api.py                 # FastAPI app, one endpoint: POST /brief
│   └── web/
│       └── index.html         # single-page UI, vanilla JS, calls /brief
└── scripts/
    └── smoke_test.py          # runs the agent on 3 known tickers, prints output
```

## Stack

- **Python 3.11+**, FastAPI, uv for dep management
- **Anthropic Claude** via the Agent SDK (`claude-agent-sdk`) — use `claude-sonnet-4-5` or latest Sonnet
- **Data sources:**
  - News: web search via Anthropic's web search tool OR a free tier API (NewsAPI, Finnhub free tier)
  - Filings: SEC EDGAR (free, no key) — `https://data.sec.gov/submissions/CIK{cik}.json`
  - Prices: Yahoo Finance via `yfinance` library (no key, good enough for MVP)
- **Frontend:** one HTML file, vanilla JS fetch, Tailwind via CDN. No build step.

If you're considering adding a dependency, ask first. We're keeping the surface area small.

## Agent design

The agent uses tool use in a loop. System prompt lives in `src/prompts/system.md`. Rough shape:

1. User submits `{ticker: "NVDA", experience_level: "first_year"}` to `POST /brief`
2. Agent is given the request and these tools:
   - `get_recent_news(ticker, days=7)` → list of headlines + snippets + URLs
   - `get_latest_filing(ticker)` → most recent 10-K/10-Q/8-K summary + URL
   - `get_price_action(ticker, days=7)` → price changes, volume, notable moves
3. Agent decides which tools to call (usually all three, but let it decide)
4. Agent writes the brief using the 3-layer template
5. API returns structured JSON: `{what_happened, why_moved, what_it_means, sources: [...]}`

Keep the tool surface small. If the agent "needs" a fourth tool, push back — we probably don't need it for MVP.

## Output format — the 3-layer brief

Every brief must have exactly these sections. The prompt enforces this.

```
## What happened
1–2 sentences. Factual. No interpretation.

## Why the price moved
2–3 sentences. Must cite at least one primary source (filing, earnings call, verified news).
Inline citations like [1], [2]. Sources list at the end.

## What it means for a first-year investor
1–2 sentences. Plain English. Contextualize — is this normal volatility, a
material business change, a sector-wide move? Never recommend action.
If a technical term appears, define it inline in parentheses.

## Sources
[1] Title — URL
[2] Title — URL
```

## Voice and tone rules (enforce in the system prompt)

- Plain English. If a term like "EPS" or "guidance" appears, define it inline the first time.
- Never use: "buy", "sell", "hold", "strong buy", "price target", "should", "recommend"
- Okay to use: "tends to", "historically", "one way to think about this", "some investors view"
- No hype. No FOMO language. No emojis. No exclamation marks.
- If the agent doesn't have enough info to answer a layer confidently, it says so explicitly rather than making things up.

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
# add ANTHROPIC_API_KEY

# run API
uv run uvicorn src.api:app --reload

# open frontend
open src/web/index.html  # or serve via the FastAPI app at /

# smoke test
uv run python scripts/smoke_test.py
```

## Smoke test cases

`scripts/smoke_test.py` runs the agent on these tickers and prints output. Useful for catching regressions and sanity-checking tone.

- `NVDA` — high-news stock, should have lots to say
- `KO` — boring stock, should gracefully say "not much happened"
- `ZZZZ` — invalid ticker, should fail gracefully

## What "done" looks like for MVP

- [ ] `POST /brief` returns a valid 3-layer brief for any real US ticker in <60s
- [ ] Frontend has a ticker input, a submit button, and renders the brief as markdown
- [ ] Smoke test passes on NVDA, KO, and handles ZZZZ gracefully
- [ ] Disclaimer appears on every brief
- [ ] README tells a new person how to run it in <5 minutes

That's it. If you're adding more, you're building the wrong thing.

## Things Claude Code should ask before doing

- Adding a new dependency
- Adding a new tool to the agent
- Changing the output schema
- Adding any form of persistence beyond a JSON file
- Touching anything auth/payment/email related (we said no)

## Things Claude Code should just do

- Fix bugs
- Improve the system prompt to enforce tone rules
- Refactor within a file
- Add inline documentation
- Improve error handling and graceful failures
- Write the smoke test

## Known limitations we're accepting for MVP

- No rate limiting — this runs locally or on a cheap VPS, fine for <100 users
- No caching — every request hits the APIs fresh
- Yahoo Finance (`yfinance`) is unofficial and occasionally flaky — acceptable for MVP
- SEC EDGAR has a 10 req/sec limit — fine for our volume
- No support for non-US tickers

## Current open questions (update as we learn)

- Should the agent try to detect earnings weeks and handle them differently? (Probably yes, but post-MVP)
- Do we return markdown or rendered HTML from the API? (Decision: markdown, frontend renders)
- Do we log briefs for later review/eval? (Decision: yes, append-only JSONL in `/logs`, no PII)
