"""RAG / Ask configuration: env lookups, model ids, price table, caps.

Every RAG module reads settings through this file (never `os.environ`
directly) so tests override one place and cost math has one price table.
Prices are USD per million tokens, from docs/PROJECT2-PLAN.md Appendix D
(checked 2026-10-28). Recheck them when that date gets old.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# ---------- model ids ----------
EXTRACT_MODEL = "claude-haiku-5-5"  # relation extraction (Batch, structured output)
JUDGE_MODEL = "claude-sonnet-5-5"  # eval judge (Batch, structured output)
EMBED_MODEL = "gemini-embedding-001"
EMBED_DIM = 768  # below 3072 dims the vectors must be L2-normalized (embed.py does it)
EMBED_MAX_INPUT_TOKENS = 2048  # per text; the chunker keeps chunks well under this

SEC_MAX_RPS = 5  # EDGAR allows 10/s; we stay at half
_DEFAULT_SEC_USER_AGENT = "Financial Advisor MVP contact@example.com"


def ask_model_default() -> str:
    """Model for anonymous /ask callers (cheap)."""
    return os.environ.get("ASK_MODEL_DEFAULT", "claude-haiku-5-5")


def ask_model_authed() -> str:
    """Model for signed-in /ask callers."""
    return os.environ.get("ASK_MODEL_AUTHED", "claude-sonnet-5-5")


def ask_daily_usd_cap() -> float:
    """Hard daily spend cap for /ask. Beyond it the API returns 429."""
    try:
        return float(os.environ.get("ASK_DAILY_USD_CAP", "1.00"))
    except ValueError:
        return 1.00


def anthropic_api_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY") or None


def sec_user_agent() -> str:
    """EDGAR fair-access policy: a descriptive User-Agent with contact info."""
    return os.environ.get("SEC_USER_AGENT") or _DEFAULT_SEC_USER_AGENT


def uses_postgres() -> bool:
    """The RAG tables (pgvector chunks, KG) exist only on Postgres; SQLite gets ask_log only."""
    from ..db import DATABASE_URL

    return DATABASE_URL.startswith("postgresql")


# ---------- prices (USD per million tokens) ----------
@dataclass(frozen=True)
class ModelPrice:
    input: float
    output: float
    cache_read_mult: float = 0.1  # multiplier on `input` for cache-read tokens
    cache_write_mult: float = 1.25  # multiplier on `input` for cache-write tokens (5-min cache)
    # Prompts above this many tokens are billed at the long_* rates (Haiku 5.5 only, today).
    long_context_threshold: int | None = None
    long_input: float | None = None
    long_output: float | None = None

    def rates(self, prompt_tokens: int) -> tuple[float, float]:
        """(input, output) rate for a prompt of this size."""
        if (
            self.long_context_threshold is not None
            and prompt_tokens > self.long_context_threshold
            and self.long_input is not None
            and self.long_output is not None
        ):
            return self.long_input, self.long_output
        return self.input, self.output


PRICES: dict[str, ModelPrice] = {
    "claude-haiku-5-5": ModelPrice(
        input=0.10, output=0.50, cache_read_mult=0.1,
        long_context_threshold=100_000, long_input=0.50, long_output=2.50,
    ),
    "claude-sonnet-5-5": ModelPrice(input=2.00, output=10.00, cache_read_mult=0.05),
    "claude-opus-5-5": ModelPrice(input=4.00, output=20.00, cache_read_mult=0.1),
}
BATCH_DISCOUNT = 0.5  # Message Batches API: 50% off
EMBED_PRICE_PER_MTOK = 0.15  # gemini-embedding-001, standard
EMBED_BATCH_PRICE_PER_MTOK = 0.075  # via Gemini Batch


class UnknownModelError(KeyError):
    """Raised when a model has no PRICES entry — add one rather than guessing."""


def price_for(model: str) -> ModelPrice:
    """Exact match first, else the longest PRICES key that prefixes `model`, so
    the dated snapshot ids the API echoes back (claude-haiku-5-5-2026xxxx)
    still price correctly."""
    if model in PRICES:
        return PRICES[model]
    for key in sorted(PRICES, key=len, reverse=True):
        if model.startswith(key):
            return PRICES[key]
    raise UnknownModelError(f"No price entry for model {model!r}; add it to src/rag/config.py PRICES")


def cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    *,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    batch: bool = False,
) -> float:
    """Cost of one request in USD.

    `input_tokens` is the uncached input count as the API's usage block reports
    it; cache reads/writes are reported (and priced) separately. The long-context
    tier is decided on the whole prompt, cached or not.
    """
    p = price_for(model)
    in_rate, out_rate = p.rates(input_tokens + cache_read_tokens + cache_write_tokens)
    cost = (
        input_tokens * in_rate
        + output_tokens * out_rate
        + cache_read_tokens * in_rate * p.cache_read_mult
        + cache_write_tokens * in_rate * p.cache_write_mult
    ) / 1_000_000
    if batch:
        cost *= BATCH_DISCOUNT
    return cost


def embed_cost_usd(tokens: int, *, batch: bool = False) -> float:
    rate = EMBED_BATCH_PRICE_PER_MTOK if batch else EMBED_PRICE_PER_MTOK
    return tokens * rate / 1_000_000
