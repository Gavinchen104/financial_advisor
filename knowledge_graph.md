# Knowledge Graph — Logic, Data, Structure & Backend

A walkthrough of how the Stockify knowledge graph was built, based on [_relationships.py](src/knowledge_graph/_relationships.py), [_macro.py](src/knowledge_graph/_macro.py), [build_knowledge_graph.py](scripts/build_knowledge_graph.py), [graph.py](src/knowledge_graph/graph.py), and [context.py](src/tools/context.py).

## Core thesis

A first-year investor reading a brief about NVDA needs to understand it doesn't move in isolation — its price reflects TSMC's fab capacity, Microsoft's AI capex, ASML's EUV monopoly, and the 10-year yield. So the graph models **economic adjacency** that the LLM (and the UI) can lean on instead of inventing relationships.

## Data sources — three tiers, layered intentionally

1. **S&P 500 constituents** ([build_knowledge_graph.py:25-97](scripts/build_knowledge_graph.py#L25-L97)) — pulled from a GitHub-hosted CSV with a Wikipedia HTML fallback. Provides tickers, names, GICS sector, GICS sub-industry. This is the "free" data — no curation needed.
2. **Curated external nodes** ([build_knowledge_graph.py:100-117](scripts/build_knowledge_graph.py#L100-L117)) — 10 non-S&P names (TSM, ASML, NVO, SAP, GOLD, etc.) bolted on because the brief can't talk about NVDA without TSM, or LLY without NVO. Pragmatic patch over the S&P-only universe.
3. **Hand-curated edges** ([_relationships.py](src/knowledge_graph/_relationships.py)) — ~250 supply-chain, customer, partner, and rivalry edges with weights and plain-English labels. The actual IP of the graph; where domain knowledge lives.

## Structure — nodes + edge types

**Nodes** carry: `ticker, name, gics_sector, gics_sub_industry, sp500` (boolean).

**Edges** are tuples `(source, target, type, weight 0–1, label)`. Five types, each with different semantics:

| Type | Direction | Example |
|---|---|---|
| `supplies_to` | directional (upstream → downstream) | ASML → TSM (1.0) |
| `competes_with` | symmetric | KO ↔ PEP (0.95) |
| `major_customer` | directional (revenue concentration) | AAPL → QCOM (0.8) |
| `strategic_partner` | symmetric (JV/licensing) | MO ↔ PM (0.8) |
| `macro_sensitivity` | directional (ticker → factor) with `direction: positive/inverse` | XOM → WTI_CRUDE_OIL (0.9, positive) |

**Weights aren't arbitrary** — defined in the docstring at [_relationships.py:14-19](src/knowledge_graph/_relationships.py#L14-L19):

- 0.9+ = existential dependency (TSM cannot make leading-edge chips without ASML)
- 0.7–0.89 = top-3 revenue
- 0.5–0.69 = meaningful
- 0.3–0.49 = notable

This makes the graph queryable by importance, not just connectivity.

## Three layers of edges, combined at build time

[build_knowledge_graph.py:222-226](scripts/build_knowledge_graph.py#L222-L226) merges three independently-generated edge sets:

1. **Curated edges** (~250) — the hand-written `EDGES` list.
2. **Auto-generated competitors** ([build_knowledge_graph.py:120-148](scripts/build_knowledge_graph.py#L120-L148)) — every pair of tickers in the same GICS sub-industry gets a `competes_with` edge at weight 0.5. Cheap, broad, low-confidence baseline.
3. **Macro edges** ([build_knowledge_graph.py:168-199](scripts/build_knowledge_graph.py#L168-L199)) — every ticker inherits its sector's macro sensitivities (e.g., all Energy tickers link to WTI), then `COMPANY_MACRO_OVERRIDES` adds or replaces with a stronger ticker-specific signal (XOM → WTI at 0.9, UAL → WTI at 0.9 inverse).

The override pattern at [graph.py:82-90](src/knowledge_graph/graph.py#L82-L90) is the elegant bit — a two-pass dedupe where `override=True` edges replace sector defaults on the same factor.

## Macro layer — 10 tradeable indicators

In [_macro.py:10-107](src/knowledge_graph/_macro.py#L10-L107) each macro factor is mapped to a real `yfinance` ticker:

| Factor | Ticker |
|---|---|
| US 10Y Yield | `^TNX` |
| Fed Funds proxy | `^IRX` |
| VIX | `^VIX` |
| WTI Crude | `CL=F` |
| USD Index | `DX-Y.NYB` |
| Gold | `GC=F` |
| Copper | `HG=F` |
| Natural Gas | `NG=F` |
| S&P 500 | `^GSPC` |

That's the trick that lets the graph come alive: at request time you can fetch a current value for *every* macro factor the same way you fetch a stock price. No separate FRED integration, no API keys.

Each factor also has a `description` written in the same plain-English voice as the briefs, ready to drop into the LLM prompt.

## Backend logic — three layers

### 1. Build (offline, weekly cron)
[build_knowledge_graph.py](scripts/build_knowledge_graph.py) compiles everything into a single `sp500_graph.json` checked into the repo. No DB, no runtime fetching of S&P constituents.

### 2. Load (once per process)
[graph.py:152-160](src/knowledge_graph/graph.py#L152-L160) is a module-level singleton. On first import it loads the JSON and builds an **adjacency index** keyed by source ticker. Symmetric edges (`competes_with`, `strategic_partner`) get inserted in both directions ([graph.py:33-35](src/knowledge_graph/graph.py#L33-L35)) so lookups are O(1) regardless of which side you query from.

### 3. Query + enrich (per request)
[context.py:58-160](src/tools/context.py#L58-L160) is where the static graph meets live market data:

- `graph.get_supply_chain(ticker)` returns competitors/suppliers/customers as edges (sorted by weight, deduped).
- `graph.get_macro_sensitivity(ticker)` returns macro edges with sector-default + company-override merged.
- All related tickers (competitors + suppliers + customers + macro yf-tickers) get collected into one list and fanned out to a `ThreadPoolExecutor` with up to 12 workers fetching 7-day price changes from yfinance in parallel ([context.py:93-99](src/tools/context.py#L93-L99)).
- A second parallel batch fetches valuation multiples (P/E, EV/EBITDA, revenue growth) for the target plus top 3 competitors to build a peer-comparison table ([context.py:121-131](src/tools/context.py#L121-L131)).
- Everything is zipped back together into a single dict that's both LLM-friendly (gets stuffed into the Gemini prompt) and frontend-friendly (D3 renders it as the force-directed graph).

## Design optimizations

- **Build offline, query fast** — the graph is a JSON blob, not a Neo4j or graph DB. Loads in milliseconds, no infra.
- **Static structure + live values** — relationships are slow-changing (curated quarterly), but every render fetches fresh prices. Best of both.
- **Weighted everything** — every edge has a weight, so `top-N` queries return *important* relationships, not just *any* relationships. This is what makes the brief feel curated rather than cluttered.
- **Sector defaults + company overrides** — covers the long tail of S&P 500 cheaply (every Energy stock gets oil sensitivity for free) while letting you hand-tune the names that matter (UAL is *more* sensitive to oil than the average industrial).
- **Auto-edges as a safety net** — the GICS sub-industry rule means even tickers without curated entries (XYL, IDXX, etc.) still get peer competitors from the same sub-industry, just at lower confidence (0.5) than curated ones (0.7–0.95).

## Honest limitation

Outside S&P 500 + the 10 curated externals, the graph degrades gracefully but partially. The CLAUDE.md acknowledges this rather than pretending otherwise.
