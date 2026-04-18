# Financial Advisor

Plain-English stock briefs for first-year investors. Answers three questions for any US ticker:

1. What happened recently
2. Why the price moved (with sources)
3. What it means for someone new to investing

## Setup

**Requirements:** Python 3.11+, [uv](https://github.com/astral-sh/uv)

```bash
# Install dependencies
uv sync

# Copy and fill in your API key
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY=sk-...
```

## Run

```bash
# Start the API server
uv run uvicorn src.api:app --reload

# Open the UI
open http://localhost:8000
```

The frontend is served at `http://localhost:8000`. Enter any US stock ticker and click "Get Brief". Expect ~30–60 seconds per request.

## Smoke test

```bash
uv run python scripts/smoke_test.py
```

Runs the agent against NVDA (active stock), KO (quiet stock), and ZZZZ (invalid ticker). Prints pass/fail for each.

## Architecture

```
src/
  agent.py          — agent loop (Anthropic SDK tool use)
  api.py            — FastAPI, POST /brief endpoint
  tools/
    news.py         — recent headlines via yfinance
    filings.py      — SEC EDGAR 10-K/10-Q/8-K lookup
    price.py        — price action via yfinance
    brief_writer.py — parse agent output into structured fields
  prompts/
    system.md       — agent system prompt
    brief_template.md
  web/
    index.html      — single-page UI
scripts/
  smoke_test.py
logs/
  briefs.jsonl      — append-only request log (no PII)
```

## API

**POST /brief**

```json
{ "ticker": "NVDA", "experience_level": "first_year" }
```

Returns:

```json
{
  "ticker": "NVDA",
  "what_happened": "...",
  "why_moved": "...",
  "what_it_means": "...",
  "sources_text": "...",
  "full_brief": "...(full markdown)...",
  "disclaimer": "This is educational information..."
}
```

## Disclaimer

Financial Advisor is for educational purposes only and does not constitute investment advice.
