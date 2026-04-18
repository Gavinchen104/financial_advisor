# Knowledge Graph — Technical Design

How Stockify models the web of relationships around each stock, and how that model is built, queried, and joined with live market data at request time.

---

## 1. What kind of graph is it

A **heterogeneous directed graph** over publicly-traded companies and macro-economic factors.

- **Heterogeneous** — nodes and edges carry *types*. Nodes are either a `Company` or a `MacroFactor`. Edges are one of `competes_with`, `supplies_to`, or `macro_sensitivity`.
- **Directed** — most edges are asymmetric: a supplier → customer edge means something different from the reverse. A couple of relation types are logically symmetric (peers, strategic partners); we still store them as two directed edges indexed on both sides so lookup is O(1) from either end.
- **Weighted** — every edge carries a `weight ∈ [0, 1]` reflecting how load-bearing the relationship is: 0.9–1.0 existential, 0.7–0.9 top-three, 0.5–0.7 meaningful, 0.3–0.5 notable.

The compiled graph lives in a single JSON file (`src/knowledge_graph/data/sp500_graph.json`), checked into git. It's small (~500 nodes, ~4000 edges) and loads in milliseconds.

---

## 2. Node structure

Each company node is a dict keyed by ticker:

```json
"NVDA": {
  "name": "NVIDIA",
  "gics_sector": "Information Technology",
  "gics_industry_group": "Semiconductors & Semiconductor Equipment",
  "gics_industry": "Semiconductors & Semiconductor Equipment",
  "gics_sub_industry": "Semiconductors"
}
```

- **Ticker is the primary key** — normalized to yfinance form (dots become dashes, so `BRK.B` → `BRK-B`).
- **GICS taxonomy** (Global Industry Classification Standard) gives us four-level classification — sector, industry group, industry, sub-industry — from broadest to narrowest. We use sub-industry to auto-generate peer edges.
- **Scope**: all S&P 500 constituents plus ~30 hand-curated non-S&P externals that matter for supply chains (TSM, ASML, NVO, etc.). Non-S&P tickers are added explicitly in `scripts/build_knowledge_graph.py`.

Macro-factor nodes live in a separate dict and carry a yfinance ticker we can price:

```python
"10y_treasury_yield": {"name": "10-year Treasury yield", "yf_ticker": "^TNX"},
"crude_oil": {"name": "Crude oil (WTI)", "yf_ticker": "CL=F"},
"vix": {"name": "VIX volatility index", "yf_ticker": "^VIX"},
```

---

## 3. Edge sources — the three layers

The graph is built from three different *kinds* of knowledge, each authored differently.

### 3a. Auto-generated competitor edges (bulk, cheap)

For every pair of companies sharing the same `gics_sub_industry`, we emit a `competes_with` edge with weight 0.5. This is pure taxonomic inference — no human judgment.

```python
# scripts/build_knowledge_graph.py
for sub_industry, tickers in sub_industry_groups.items():
    for a, b in itertools.combinations(tickers, 2):
        edges.append((a, "competes_with", b, 0.5))
```

This gives broad coverage (every company gets *some* peers) with zero manual effort. The trade-off: the graph can't tell you NVDA's *most important* competitor — just that AMD and INTC are in the same sub-industry. We patch this with curated overrides (below).

### 3b. Curated supply-chain + strategic edges (small, hand-authored)

In `src/knowledge_graph/_relationships.py` we keep a flat tuple list of directed edges:

```python
EDGES = [
    ("ASML", "supplies_to", "TSM", 0.95),      # existential
    ("TSM",  "supplies_to", "NVDA", 0.90),
    ("NVDA", "supplies_to", "MSFT", 0.70),     # top-3 customer
    ("NVDA", "competes_with", "AMD", 0.85),    # curated override, replaces auto 0.5
    ...
]
```

Weight convention:
- **0.9–1.0** — if this edge broke, revenue would collapse (ASML's EUV monopoly)
- **0.7–0.9** — top-three counterparty
- **0.5–0.7** — meaningful but substitutable
- **0.3–0.5** — notable enough to mention, not critical

Curated `competes_with` edges overwrite the auto-generated 0.5 peer edges when present. This is how we encode "NVDA and AMD are a bigger deal to each other than NVDA and some other semi".

Coverage is heavy in tech/semis (where supply chains matter and are documented) and sparse everywhere else — a deliberate trade-off.

### 3c. Macro sensitivity — sector defaults + company overrides

`src/knowledge_graph/_macro.py` uses a two-layer pattern.

**Sector defaults** — every company in a sector inherits a baseline macro exposure:

```python
SECTOR_MACRO = {
    "Energy":            [("crude_oil", 0.9), ("usd_index", 0.4)],
    "Information Technology": [("10y_treasury_yield", 0.7), ("vix", 0.5)],
    "Financials":        [("10y_treasury_yield", 0.8), ("vix", 0.6)],
    ...
}
```

**Company overrides** — where sector defaults don't capture the nuance, we patch per-ticker:

```python
COMPANY_MACRO_OVERRIDES = {
    "NVDA": [("10y_treasury_yield", 0.85), ("vix", 0.6), ("usd_index", 0.5)],
    "XOM":  [("crude_oil", 0.95), ("usd_index", 0.4)],
    ...
}
```

At build time, a company with an override uses only its override list. Otherwise it uses its sector's defaults. This gives us good coverage without having to hand-author macro edges for all 500 names.

---

## 4. The build pipeline

`scripts/build_knowledge_graph.py` runs in four stages and emits one JSON file.

**Stage 1 — Fetch S&P 500 constituents.** Pull the current list from the Wikipedia CSV. Normalize tickers (`BRK.B` → `BRK-B`). Each row gives us ticker, name, and all four GICS levels.

**Stage 2 — Add external nodes.** Append hand-curated non-S&P tickers (TSM, ASML, NVO, SAP, TM, etc.) that appear in supply-chain edges but aren't index members. Without this step, edges like `ASML → TSM` would reference non-existent nodes.

**Stage 3 — Build edges in three passes.**

1. Competitor edges from sub-industry combinations (weight 0.5).
2. Curated edges from `_relationships.py` — apply as-is; curated `competes_with` edges overwrite the auto 0.5.
3. Macro edges from `_macro.py` — for each company, compute its macro sensitivity list and emit one edge per macro factor.

**Stage 4 — Serialize.** Write `{nodes: {...}, macro_nodes: {...}, edges: [...]}` as indented JSON. The file is small enough (~500 KB) to check into git and diff meaningfully in PRs.

The script runs weekly via GitHub Actions (`.github/workflows/refresh-knowledge-graph.yml`) to catch S&P 500 constituent changes.

---

## 5. Runtime — loading, indexing, querying

`src/knowledge_graph/graph.py` defines a `KnowledgeGraph` class, exposed via a `get_graph()` singleton.

**Loading.** On first call, read the JSON into memory. Single file, single parse.

**Indexing.** We build adjacency-list indexes once at load time so lookups are O(degree), not O(edges):

```python
self._out: dict[str, list[Edge]] = defaultdict(list)  # ticker → outgoing edges
self._in_by_relation: dict[str, dict[str, list[Edge]]] = ...  # for reverse lookups
```

**Symmetric-edge trick.** For relation types that are logically symmetric (competitors, strategic partners), we index the edge under *both* endpoints. Storage is 2× but lookup is O(1) from either side — which matters on the hot path (every brief query).

**Query API.** Four methods:

- `get_competitors(ticker)` — direct index lookup
- `get_suppliers(ticker)` — reverse scan over `supplies_to` edges (O(E) but E ≈ 4000 and results are cached)
- `get_customers(ticker)` — forward lookup from the `supplies_to` adjacency
- `get_macro_sensitivities(ticker)` — direct lookup, returns macro factors with weights

The `get_suppliers` O(E) scan is a known wart. Acceptable at current scale; trivial to fix by building a reverse adjacency at load time if it ever shows up in profiling.

---

## 6. Request-time enrichment — joining static graph with live prices

The static graph tells you *who's related to whom*. The brief needs to know *which of these relationships are moving right now*. That join happens in `src/tools/context.py::get_knowledge_context(ticker)`:

1. Query the graph for top competitors, suppliers, customers, and macro factors (by edge weight).
2. Collect all tickers (S&P companies + yf-tickers for macro factors) into one set.
3. Fetch 7-day % change for every ticker in parallel via `ThreadPoolExecutor` on yfinance.
4. Enrich each relationship row with `pct_change_7d`, `price`, and (for companies) name + sector.
5. Return a shape ready for both the LLM prompt and the front-end D3 visualization.

**Filtering rule in the system prompt**: only mention relationships where `pct_change_7d` is non-null AND |change| > 2%. Irrelevant background moves get dropped before they reach the user.

---

## 7. Where the graph shows up in the product

1. **Brief prompt context** — `## Knowledge Graph Context` section in the Gemini user message. The model is instructed (in `src/prompts/system.md`) how to read it: competitor moves signal sector strength or share loss; supplier moves raise upstream concerns; customer results are demand signals; macro factors contextualize against rates, oil, VIX.
2. **Ticker page visualization** — `src/web/static/app.js` renders a D3 force-directed graph with the target in the center, competitors/suppliers/customers/macro factors as neighbors, node color by type, edge thickness by weight, node border color by live 7-day direction (green up, red down).
3. **Peer valuation card** — uses `get_competitors()` to pick the top 3 peers, fetches market cap / P/E / EV/EBITDA for target + peers in parallel, renders a comparison table.

The same graph feeds all three. One source of truth, three surfaces.

---

## 8. Tradeoffs, limits, honest shortcomings

- **Coverage gap.** Heavy in tech/semis, thin elsewhere. Supply-chain edges are hand-authored — we have what we have.
- **Static weights.** A supplier's importance shifts over time (Apple pulling chip design in-house). Weights don't update automatically.
- **No ownership edges.** We don't model "Berkshire owns 5% of Apple". Could matter for a few names; out of scope for now.
- **Coarse macro mapping.** Sector defaults are blunt — a software company and a hardware company both map to "IT sector macro exposure" even though they behave differently to rates.
- **Ticker normalization is fragile.** Anything beyond dots-to-dashes (class shares, foreign listings, renames) would need code changes.
- **`get_suppliers` is O(E).** Acceptable at 4000 edges, not at 40000.

---

## 9. The mental model

> A curated, versioned, hand-weighted directed graph over S&P 500 + externals and macro factors — built offline from three sources (GICS taxonomy, expert-authored edges, sector/company macro overrides), loaded once into process memory with adjacency indexes, and joined with live yfinance data at request time to highlight *which relationships are moving this week*.

That's the whole thing. The graph itself is small and boring. The leverage comes from pairing it with real-time prices and a prompt that tells the model how to read the join.
