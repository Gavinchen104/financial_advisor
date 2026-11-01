"""Gemini embeddings for chunks and questions (docs/PROJECT2-PLAN.md P2-C).

All embedding calls go through here. gemini-embedding-001 at 768 dimensions,
RETRIEVAL_DOCUMENT for indexed chunks and RETRIEVAL_QUERY for questions, every
vector L2-normalized (required below 3072 dims). Batches of EMBED_BATCH_SIZE,
tenacity retries on 429 / 5xx, and a Budget so --max-usd holds. Never mix
embedding models in one index: filing_docs records embed_model / embed_dim.

Token counts are estimated as characters / 4 (the Developer API returns no
usage for embeddings); the same estimate feeds --dry-run and the budget.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Any

import numpy as np
from loguru import logger
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential

from . import config
from .llm import Budget, BudgetExceeded  # noqa: F401 — re-exported for callers

MODEL = config.EMBED_MODEL
DIM = config.EMBED_DIM
BATCH_SIZE = config.EMBED_BATCH_SIZE
MAX_CHARS = config.EMBED_MAX_INPUT_TOKENS * config.CHARS_PER_TOKEN  # hard guard; the chunker stays far below
RETRY_WAIT_MAX = 30.0  # tests set 0
RETRY_ATTEMPTS = 5

DOCUMENT_TASK = "RETRIEVAL_DOCUMENT"
QUERY_TASK = "RETRIEVAL_QUERY"


class EmbedError(RuntimeError):
    pass


class MissingAPIKeyError(EmbedError):
    pass


# ---------- client ----------
_client: Any = None
_client_lock = threading.Lock()


def get_client():
    """Lazy google-genai client, so importing src.rag never needs a key."""
    global _client
    with _client_lock:
        if _client is None:
            key = config.gemini_api_key()
            if not key:
                raise MissingAPIKeyError("GEMINI_API_KEY is not set; embeddings need it")
            from google import genai

            _client = genai.Client(api_key=key)
        return _client


def set_client(client: Any) -> None:
    """Inject a client (tests pass a fake). None resets to lazy construction."""
    global _client
    with _client_lock:
        _client = client


# ---------- budget ----------
_budget = Budget()


def get_budget() -> Budget:
    return _budget


def set_budget(budget: Budget) -> None:
    global _budget
    _budget = budget


# ---------- helpers ----------
def estimate_tokens(texts: list[str]) -> int:
    return sum(math.ceil(len(t) / config.CHARS_PER_TOKEN) for t in texts)


def estimate_cost_usd(texts: list[str], *, batch: bool = False) -> float:
    return config.embed_cost_usd(estimate_tokens(texts), batch=batch)


def normalize(values) -> list[float]:
    """Unit-length copy of a vector (gemini-embedding-001 below 3072 dims is not normalized)."""
    a = np.asarray(values, dtype=np.float32)
    n = float(np.linalg.norm(a))
    return (a / n).tolist() if n else a.tolist()


def _retryable(exc: BaseException) -> bool:
    try:
        from google.genai import errors as genai_errors
    except ImportError:  # pragma: no cover
        genai_errors = None
    if genai_errors is not None and isinstance(exc, genai_errors.APIError):
        return getattr(exc, "code", None) in (408, 429, 500, 502, 503, 504)
    return isinstance(exc, (ConnectionError, TimeoutError))


def _embed_batch(texts: list[str], task: str) -> list[list[float]]:
    from google.genai import types

    client = get_client()
    for attempt in Retrying(
        retry=retry_if_exception(_retryable),
        stop=stop_after_attempt(RETRY_ATTEMPTS),
        wait=wait_exponential(multiplier=1, max=RETRY_WAIT_MAX),
        reraise=True,
    ):
        with attempt:
            response = client.models.embed_content(
                model=MODEL,
                contents=texts,
                config=types.EmbedContentConfig(task_type=task, output_dimensionality=DIM),
            )
            vectors = [normalize(e.values) for e in response.embeddings]
            if len(vectors) != len(texts):
                raise EmbedError(f"embed_content returned {len(vectors)} vectors for {len(texts)} texts")
            if any(len(v) != DIM for v in vectors):
                raise EmbedError(f"embed_content returned a vector that is not {DIM}-d")
            return vectors
    raise EmbedError("unreachable")  # pragma: no cover


def _embed(texts: list[str], task: str) -> list[list[float]]:
    out: list[list[float]] = []
    truncated = 0
    for start in range(0, len(texts), BATCH_SIZE):
        batch = []
        for t in texts[start:start + BATCH_SIZE]:
            if len(t) > MAX_CHARS:
                truncated += 1
                t = t[:MAX_CHARS]
            batch.append(t)
        cost = estimate_cost_usd(batch)
        _budget.reserve(cost)
        t0 = time.perf_counter()
        out.extend(_embed_batch(batch, task))
        _budget.charge(cost)
        logger.bind(
            model=MODEL, task=task, texts=len(batch), est_tokens=estimate_tokens(batch),
            est_cost_usd=round(cost, 6), latency_ms=int((time.perf_counter() - t0) * 1000),
        ).debug("embed batch")
    if truncated:
        logger.warning(f"embed: truncated {truncated} text(s) longer than {MAX_CHARS} chars")
    return out


def embed_documents(texts: list[str]) -> list[list[float]]:
    """Normalized 768-d vectors for chunks to index."""
    return _embed(list(texts), DOCUMENT_TASK) if texts else []


def embed_query(text: str) -> list[float]:
    """Normalized 768-d vector for a question."""
    return _embed([text], QUERY_TASK)[0]
