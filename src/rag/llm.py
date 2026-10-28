"""Anthropic client wrapper — every Claude call in src/rag/ goes through here.

One place for: lazy client construction, request logging (tokens, cost,
latency, stop_reason as loguru fields → JSON in prod), the SDK retry policy,
the max_tokens retry, a per-process spend Budget that raises *before* a call,
pre-flight cost estimates for --dry-run, structured outputs, and the Message
Batches API (50% off; used for offline extraction and judging).

    from src.rag import llm
    llm.set_budget(llm.Budget(max_usd=5.00))                       # --max-usd
    est = llm.estimate(model=m, max_tokens=800, messages=msgs)     # --dry-run
    msg = llm.create(model=m, max_tokens=800, messages=msgs)       # cited answers
    res = llm.parse(Relations, model=m, max_tokens=800, messages=msgs).value

Citations (search_result blocks) and structured outputs can't share one
request, so answers use create() while extraction / intent / judging use
parse() — or, in batches, structured_output_config() + parse_structured().
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

import anthropic
from loguru import logger
from pydantic import BaseModel, ValidationError

from . import config

T = TypeVar("T", bound=BaseModel)

SDK_MAX_RETRIES = 5  # SDK-level retries with backoff on 429 / 5xx / connection errors
CUSTOM_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")  # Batch API constraint
BATCH_POLL_SECONDS = 30.0


class LLMError(RuntimeError):
    """Base class for errors raised by this module."""


class MissingAPIKeyError(LLMError):
    pass


class BudgetExceeded(LLMError):
    pass


class ParseError(LLMError):
    pass


class BatchError(LLMError):
    pass


# ---------- client ----------
_client: Any = None
_client_lock = threading.Lock()


def get_client() -> anthropic.Anthropic:
    """Lazy singleton, so importing src.rag never needs a key (tests, brief-only deploys)."""
    global _client
    with _client_lock:
        if _client is None:
            key = config.anthropic_api_key()
            if not key:
                raise MissingAPIKeyError("ANTHROPIC_API_KEY is not set; the Ask / RAG feature needs it")
            _client = anthropic.Anthropic(api_key=key, max_retries=SDK_MAX_RETRIES)
        return _client


def set_client(client: Any) -> None:
    """Inject a client (tests pass a fake). None resets to lazy construction."""
    global _client
    with _client_lock:
        _client = client


# ---------- budget ----------
@dataclass
class Budget:
    """Per-process spend cap.

    reserve() raises BudgetExceeded *before* a request when the worst-case
    estimate would cross the cap; charge() records the actual cost afterwards.
    max_usd=None means unlimited (the default for the API process — the daily
    /ask cap is enforced from ask_log, not here).
    """

    max_usd: float | None = None
    spent_usd: float = 0.0
    calls: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    @property
    def remaining_usd(self) -> float | None:
        return None if self.max_usd is None else max(self.max_usd - self.spent_usd, 0.0)

    def reserve(self, estimated_usd: float) -> None:
        if self.max_usd is None:
            return
        with self._lock:
            if self.spent_usd + estimated_usd > self.max_usd + 1e-9:
                raise BudgetExceeded(
                    f"refusing call: estimated ${estimated_usd:.4f} + spent ${self.spent_usd:.4f} "
                    f"exceeds budget ${self.max_usd:.2f}"
                )

    def charge(self, usd: float) -> None:
        with self._lock:
            self.spent_usd += usd
            self.calls += 1


_budget = Budget()


def get_budget() -> Budget:
    return _budget


def set_budget(budget: Budget) -> None:
    global _budget
    _budget = budget


# ---------- usage, cost, logging ----------
@dataclass(frozen=True)
class Usage:
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    batch: bool = False

    @property
    def cost_usd(self) -> float:
        return config.cost_usd(
            self.model,
            self.input_tokens,
            self.output_tokens,
            cache_read_tokens=self.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens,
            batch=self.batch,
        )


def usage_from(message: Any, *, model: str | None = None, batch: bool = False) -> Usage:
    """Usage from a Message. Pass the requested `model` when you have it; the
    response's model id may be a dated snapshot (config.price_for handles both)."""
    u = message.usage
    return Usage(
        model=model or message.model,
        input_tokens=u.input_tokens or 0,
        output_tokens=u.output_tokens or 0,
        cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
        cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
        batch=batch,
    )


def _log(op: str, usage: Usage, latency_ms: int | None, stop_reason: str | None, **extra: Any) -> None:
    cost = usage.cost_usd
    logger.bind(
        provider="anthropic",
        op=op,
        model=usage.model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        cost_usd=round(cost, 6),
        latency_ms=latency_ms,
        stop_reason=stop_reason,
        budget_spent_usd=round(_budget.spent_usd, 6),
        **extra,
    ).info(
        f"llm {op} model={usage.model} in={usage.input_tokens} out={usage.output_tokens} "
        f"cost=${cost:.5f} latency_ms={latency_ms} stop={stop_reason}"
    )


# ---------- estimates ----------
def rough_input_tokens(messages: Any, system: Any = None, tools: Any = None) -> int:
    """~4 chars/token, counted over the JSON-serialized request so search
    results and tool schemas are included. Free and offline; used to guard the
    Budget before every call. estimate() is the exact version."""
    blob = json.dumps({"messages": messages, "system": system, "tools": tools}, default=str)
    return max(1, len(blob) // 4)


def rough_estimate_usd(
    model: str, max_tokens: int, messages: Any, system: Any = None, tools: Any = None, *, batch: bool = False
) -> float:
    """Worst case: rough input count plus the full max_tokens of output."""
    return config.cost_usd(model, rough_input_tokens(messages, system, tools), max_tokens, batch=batch)


@dataclass(frozen=True)
class Estimate:
    model: str
    input_tokens: int
    output_tokens: int
    usd: float
    batch: bool = False


def estimate(
    *,
    model: str,
    max_tokens: int,
    messages: list[Any],
    system: Any = None,
    tools: Any = None,
    expected_output_tokens: int | None = None,
    batch: bool = False,
) -> Estimate:
    """Pre-flight for --dry-run: exact input tokens via count_tokens (free), and
    the cost assuming `expected_output_tokens` (default: all of max_tokens)."""
    kw: dict[str, Any] = {"model": model, "messages": messages}
    if system is not None:
        kw["system"] = system
    if tools is not None:
        kw["tools"] = tools
    n_in = get_client().messages.count_tokens(**kw).input_tokens
    n_out = max_tokens if expected_output_tokens is None else expected_output_tokens
    return Estimate(model, n_in, n_out, config.cost_usd(model, n_in, n_out, batch=batch), batch)


# ---------- messages ----------
def create(
    *,
    model: str,
    max_tokens: int,
    messages: list[Any],
    estimated_usd: float | None = None,
    retry_on_max_tokens: bool = True,
    **kwargs: Any,
) -> Any:
    """messages.create with budget guard, logging and one max_tokens retry.

    kwargs pass straight through (system, tools, output_config, ...). Returns
    the SDK Message; callers read .content / .stop_reason / .usage as usual.
    """
    budget = get_budget()
    if estimated_usd is None:
        estimated_usd = rough_estimate_usd(model, max_tokens, messages, kwargs.get("system"), kwargs.get("tools"))
    budget.reserve(estimated_usd)

    t0 = time.perf_counter()
    message = get_client().messages.create(model=model, max_tokens=max_tokens, messages=messages, **kwargs)
    latency_ms = int((time.perf_counter() - t0) * 1000)
    usage = usage_from(message, model=model)
    budget.charge(usage.cost_usd)
    _log("messages.create", usage, latency_ms, message.stop_reason, max_tokens=max_tokens)

    if message.stop_reason == "max_tokens" and retry_on_max_tokens:
        logger.warning(f"llm messages.create hit max_tokens={max_tokens}; retrying once with {max_tokens * 2}")
        return create(
            model=model, max_tokens=max_tokens * 2, messages=messages, retry_on_max_tokens=False, **kwargs
        )
    return message


@dataclass(frozen=True)
class ParseResult(Generic[T]):
    value: T
    message: Any
    usage: Usage


def parse(
    output_format: type[T],
    *,
    model: str,
    max_tokens: int,
    messages: list[Any],
    estimated_usd: float | None = None,
    retry_on_max_tokens: bool = True,
    **kwargs: Any,
) -> ParseResult[T]:
    """Structured output: messages.parse(output_format=<pydantic model>).

    The SDK validates the JSON into `output_format` (Pydantic); a response
    with nothing parseable (refusal, empty) raises ParseError. Don't combine
    with search_result citations in one request — the API rejects that.
    """
    budget = get_budget()
    if estimated_usd is None:
        estimated_usd = rough_estimate_usd(model, max_tokens, messages, kwargs.get("system"), kwargs.get("tools"))
    budget.reserve(estimated_usd)

    t0 = time.perf_counter()
    message = get_client().messages.parse(
        model=model, max_tokens=max_tokens, messages=messages, output_format=output_format, **kwargs
    )
    latency_ms = int((time.perf_counter() - t0) * 1000)
    usage = usage_from(message, model=model)
    budget.charge(usage.cost_usd)
    _log(
        "messages.parse", usage, latency_ms, message.stop_reason,
        max_tokens=max_tokens, output_format=output_format.__name__,
    )

    if message.stop_reason == "max_tokens" and retry_on_max_tokens:
        logger.warning(f"llm messages.parse hit max_tokens={max_tokens}; retrying once with {max_tokens * 2}")
        return parse(
            output_format, model=model, max_tokens=max_tokens * 2, messages=messages,
            retry_on_max_tokens=False, **kwargs,
        )

    value = getattr(message, "parsed_output", None)
    if value is None:
        raise ParseError(f"no {output_format.__name__} in response (stop_reason={message.stop_reason})")
    return ParseResult(value=value, message=message, usage=usage)


# ---------- structured outputs for raw / batch requests ----------
def structured_output_config(output_format: type[BaseModel], *, effort: str | None = None) -> dict[str, Any]:
    """`output_config` for a raw request (Batch API) that must return `output_format` JSON.

    Unsupported in these schemas: numeric / string-length constraints,
    recursion, additionalProperties other than false. Keep the Pydantic models
    simple (Literal, str, bool, list[...]) and validate with parse_structured().
    """
    try:
        from anthropic import transform_schema  # strips what the API rejects, when the SDK has it

        schema = transform_schema(output_format)
    except ImportError:
        schema = output_format.model_json_schema()
    cfg: dict[str, Any] = {"format": {"type": "json_schema", "schema": schema}}
    if effort:
        cfg["effort"] = effort
    return cfg


def parse_structured(output_format: type[T], message: Any) -> T:
    """Validate a raw Message's text into `output_format` (Batch results aren't auto-parsed)."""
    text = "".join(getattr(b, "text", "") for b in message.content if getattr(b, "type", None) == "text")
    if not text.strip():
        raise ParseError(f"empty response for {output_format.__name__} (stop_reason={message.stop_reason})")
    try:
        return output_format.model_validate_json(text)
    except ValidationError as e:
        raise ParseError(f"response is not a valid {output_format.__name__}: {e}") from e


# ---------- batches ----------
@dataclass(frozen=True)
class BatchResult:
    custom_id: str
    status: str  # succeeded | errored | canceled | expired
    message: Any = None
    usage: Usage | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "succeeded"


def batch_submit(requests: list[dict[str, Any]], *, estimated_usd: float | None = None) -> str:
    """Submit a Message Batch. Each request is {"custom_id": str, "params": {model, max_tokens, messages, ...}}.

    custom_id must match ^[a-zA-Z0-9_-]{1,64}$ and be unique (use short hashes).
    Reserves the rough worst-case estimate at batch (50% off) rates. Returns the batch id;
    persist it — results are kept for 29 days and most batches finish within an hour.
    """
    if not requests:
        raise BatchError("empty batch")
    ids = [r.get("custom_id") for r in requests]
    bad = [i for i in ids if not isinstance(i, str) or not CUSTOM_ID_RE.match(i)]
    if bad:
        raise BatchError(f"invalid custom_id(s) {bad[:3]}: must match {CUSTOM_ID_RE.pattern}")
    if len(set(ids)) != len(ids):
        raise BatchError("custom_id values must be unique within a batch")

    if estimated_usd is None:
        estimated_usd = sum(
            rough_estimate_usd(
                p["model"], p["max_tokens"], p["messages"], p.get("system"), p.get("tools"), batch=True
            )
            for p in (r["params"] for r in requests)
        )
    get_budget().reserve(estimated_usd)

    batch = get_client().messages.batches.create(requests=requests)
    logger.bind(
        provider="anthropic", op="batches.create", batch_id=batch.id,
        n_requests=len(requests), estimated_usd=round(estimated_usd, 4),
    ).info(f"llm batches.create id={batch.id} n={len(requests)} est=${estimated_usd:.4f}")
    return batch.id


def batch_wait(
    batch_id: str, *, poll_seconds: float = BATCH_POLL_SECONDS, timeout_seconds: float | None = None
) -> Any:
    """Poll until processing_status == 'ended'. Returns the final MessageBatch."""
    client = get_client()
    t0 = time.monotonic()
    while True:
        batch = client.messages.batches.retrieve(batch_id)
        if batch.processing_status == "ended":
            return batch
        if timeout_seconds is not None and time.monotonic() - t0 >= timeout_seconds:
            raise BatchError(f"batch {batch_id} still {batch.processing_status} after {timeout_seconds}s")
        logger.info(
            f"llm batch {batch_id} {batch.processing_status}; counts={getattr(batch, 'request_counts', None)}"
        )
        time.sleep(poll_seconds)


def batch_collect(
    batch_id: str,
    *,
    wait: bool = True,
    poll_seconds: float = BATCH_POLL_SECONDS,
    timeout_seconds: float | None = None,
) -> dict[str, BatchResult]:
    """Stream a batch's results, keyed by custom_id. Charges the Budget at batch rates.

    Non-succeeded entries (errored / canceled / expired) come back with
    status + error so callers can retry just those.
    """
    if wait:
        batch_wait(batch_id, poll_seconds=poll_seconds, timeout_seconds=timeout_seconds)

    out: dict[str, BatchResult] = {}
    budget = get_budget()
    total = 0.0
    for item in get_client().messages.batches.results(batch_id):
        r = item.result
        if r.type == "succeeded":
            usage = usage_from(r.message, batch=True)
            budget.charge(usage.cost_usd)
            total += usage.cost_usd
            out[item.custom_id] = BatchResult(item.custom_id, "succeeded", message=r.message, usage=usage)
        else:
            err = getattr(r, "error", None)
            out[item.custom_id] = BatchResult(
                item.custom_id, r.type, error=str(err) if err is not None else r.type
            )

    n_ok = sum(1 for b in out.values() if b.ok)
    logger.bind(
        provider="anthropic", op="batches.results", batch_id=batch_id,
        n_results=len(out), n_succeeded=n_ok, cost_usd=round(total, 6),
    ).info(f"llm batches.results id={batch_id} ok={n_ok}/{len(out)} cost=${total:.4f}")
    return out
