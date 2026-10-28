"""src/rag/llm.py against a fake Anthropic client — no network, no spend."""

from types import SimpleNamespace

import anthropic
import pytest
from pydantic import BaseModel

from src.rag import config, llm

HAIKU = "claude-haiku-5-5"
MSGS = [{"role": "user", "content": "What was revenue in fiscal 2025?"}]


# ---------- fakes ----------
def _usage(inp, out, cache_read=0, cache_write=0):
    return SimpleNamespace(
        input_tokens=inp, output_tokens=out,
        cache_read_input_tokens=cache_read, cache_creation_input_tokens=cache_write,
    )


def _message(*, inp=1000, out=100, stop_reason="end_turn", model=HAIKU, text="hello", parsed_output=None):
    return SimpleNamespace(
        model=model, stop_reason=stop_reason, usage=_usage(inp, out),
        content=[SimpleNamespace(type="text", text=text)], parsed_output=parsed_output,
    )


class FakeBatches:
    def __init__(self):
        self.created = []
        self.statuses = []  # popped by retrieve(); "ended" once exhausted
        self.results_by_id = {}

    def create(self, *, requests):
        self.created.append(requests)
        return SimpleNamespace(id="msgbatch_1", processing_status="in_progress")

    def retrieve(self, batch_id):
        status = self.statuses.pop(0) if self.statuses else "ended"
        return SimpleNamespace(id=batch_id, processing_status=status, request_counts=None)

    def results(self, batch_id):
        return iter(self.results_by_id.get(batch_id, []))


class FakeMessages:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.calls = []  # (method, kwargs)
        self.count_tokens_calls = []
        self.batches = FakeBatches()

    def create(self, **kw):
        self.calls.append(("create", kw))
        return self.responses.pop(0)

    def parse(self, **kw):
        self.calls.append(("parse", kw))
        return self.responses.pop(0)

    def count_tokens(self, **kw):
        self.count_tokens_calls.append(kw)
        return SimpleNamespace(input_tokens=1234)


class FakeClient:
    def __init__(self, responses=()):
        self.messages = FakeMessages(responses)


@pytest.fixture(autouse=True)
def _isolate_llm_state():
    llm.set_client(None)
    llm.set_budget(llm.Budget())
    yield
    llm.set_client(None)
    llm.set_budget(llm.Budget())


def _install(responses=()):
    client = FakeClient(responses)
    llm.set_client(client)
    return client


# ---------- client ----------
def test_get_client_requires_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    with pytest.raises(llm.MissingAPIKeyError):
        llm.get_client()


def test_get_client_builds_sdk_client_with_retries(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-real")
    client = llm.get_client()
    assert isinstance(client, anthropic.Anthropic)
    assert client.max_retries == 5
    assert llm.get_client() is client  # singleton


# ---------- create ----------
def test_create_returns_message_and_charges_budget():
    client = _install([_message(inp=1000, out=100)])
    budget = llm.Budget(max_usd=1.0)
    llm.set_budget(budget)

    msg = llm.create(model=HAIKU, max_tokens=200, messages=MSGS, system="sys", output_config={"effort": "low"})

    assert msg.stop_reason == "end_turn"
    method, kw = client.messages.calls[0]
    assert method == "create"
    assert kw["model"] == HAIKU and kw["max_tokens"] == 200 and kw["messages"] == MSGS
    assert kw["system"] == "sys" and kw["output_config"] == {"effort": "low"}
    assert budget.spent_usd == pytest.approx(config.cost_usd(HAIKU, 1000, 100))
    assert budget.calls == 1


def test_create_retries_once_with_double_max_tokens():
    client = _install([_message(stop_reason="max_tokens"), _message(stop_reason="max_tokens")])
    msg = llm.create(model=HAIKU, max_tokens=200, messages=MSGS)

    assert [kw["max_tokens"] for _, kw in client.messages.calls] == [200, 400]
    assert msg.stop_reason == "max_tokens"  # second attempt is returned as-is, no third call
    assert llm.get_budget().calls == 2  # both attempts are paid for and counted


def test_create_retry_can_be_disabled():
    client = _install([_message(stop_reason="max_tokens")])
    llm.create(model=HAIKU, max_tokens=200, messages=MSGS, retry_on_max_tokens=False)
    assert len(client.messages.calls) == 1


def test_create_uses_cache_token_fields_in_cost():
    client = _install([_message(inp=100, out=10)])
    client.messages.responses[0].usage = _usage(100, 10, cache_read=10_000)
    llm.create(model=HAIKU, max_tokens=50, messages=MSGS)
    assert llm.get_budget().spent_usd == pytest.approx(config.cost_usd(HAIKU, 100, 10, cache_read_tokens=10_000))


# ---------- budget ----------
def test_budget_blocks_before_the_api_is_called():
    client = _install([_message()])
    llm.set_budget(llm.Budget(max_usd=0.000001))
    with pytest.raises(llm.BudgetExceeded):
        llm.create(model=HAIKU, max_tokens=4000, messages=MSGS)
    assert client.messages.calls == []


def test_budget_accounting():
    b = llm.Budget(max_usd=1.0)
    b.charge(0.25)
    assert b.remaining_usd == pytest.approx(0.75)
    b.reserve(0.75)  # exactly fits
    with pytest.raises(llm.BudgetExceeded):
        b.reserve(0.76)


def test_unlimited_budget_never_raises():
    b = llm.Budget()
    b.reserve(1e9)
    assert b.remaining_usd is None


def test_rough_estimate_is_worst_case_on_output():
    est = llm.rough_estimate_usd(HAIKU, 1000, MSGS)
    n_in = llm.rough_input_tokens(MSGS)
    assert n_in >= 1
    assert est == pytest.approx(config.cost_usd(HAIKU, n_in, 1000))


# ---------- parse ----------
class Intent(BaseModel):
    intent: str
    needs_calculation: bool


def test_parse_returns_pydantic_value_and_usage():
    client = _install([_message(parsed_output=Intent(intent="valuation", needs_calculation=True))])
    res = llm.parse(Intent, model=HAIKU, max_tokens=100, messages=MSGS, output_config={"effort": "low"})

    assert res.value.intent == "valuation" and res.value.needs_calculation is True
    assert res.usage.cost_usd == pytest.approx(config.cost_usd(HAIKU, 1000, 100))
    method, kw = client.messages.calls[0]
    assert method == "parse" and kw["output_format"] is Intent
    assert kw["output_config"] == {"effort": "low"}


def test_parse_without_parsed_output_raises():
    _install([_message(parsed_output=None)])
    with pytest.raises(llm.ParseError):
        llm.parse(Intent, model=HAIKU, max_tokens=100, messages=MSGS)


def test_parse_retries_once_on_max_tokens():
    client = _install([
        _message(stop_reason="max_tokens"),
        _message(parsed_output=Intent(intent="sector", needs_calculation=False)),
    ])
    res = llm.parse(Intent, model=HAIKU, max_tokens=100, messages=MSGS)
    assert res.value.intent == "sector"
    assert [kw["max_tokens"] for _, kw in client.messages.calls] == [100, 200]


# ---------- estimate ----------
def test_estimate_uses_count_tokens_and_max_tokens_worst_case():
    client = _install()
    est = llm.estimate(model=HAIKU, max_tokens=500, messages=MSGS, system="sys")

    assert est.input_tokens == 1234 and est.output_tokens == 500
    assert est.usd == pytest.approx(config.cost_usd(HAIKU, 1234, 500))
    kw = client.messages.count_tokens_calls[0]
    assert kw["system"] == "sys" and "tools" not in kw


def test_estimate_batch_rate_and_expected_output():
    _install()
    full = llm.estimate(model=HAIKU, max_tokens=500, messages=MSGS, expected_output_tokens=50)
    half = llm.estimate(model=HAIKU, max_tokens=500, messages=MSGS, expected_output_tokens=50, batch=True)
    assert full.usd == pytest.approx(config.cost_usd(HAIKU, 1234, 50))
    assert half.usd == pytest.approx(full.usd / 2)


# ---------- structured outputs for batch ----------
class Relation(BaseModel):
    counterparty_name: str
    confidence: str


def test_structured_output_config_shape():
    cfg = llm.structured_output_config(Relation, effort="low")
    assert cfg["format"]["type"] == "json_schema"
    assert "counterparty_name" in cfg["format"]["schema"]["properties"]
    assert cfg["effort"] == "low"
    assert "effort" not in llm.structured_output_config(Relation)


def test_parse_structured_validates_text():
    good = _message(text='{"counterparty_name": "TSMC", "confidence": "high"}')
    assert llm.parse_structured(Relation, good).counterparty_name == "TSMC"

    with pytest.raises(llm.ParseError):
        llm.parse_structured(Relation, _message(text='{"counterparty_name": 1}'))
    with pytest.raises(llm.ParseError):
        llm.parse_structured(Relation, _message(text=""))


# ---------- batches ----------
def _request(custom_id, **params):
    base = {"model": HAIKU, "max_tokens": 100, "messages": MSGS}
    base.update(params)
    return {"custom_id": custom_id, "params": base}


def test_batch_submit_validates_custom_ids_before_calling_api():
    client = _install()
    with pytest.raises(llm.BatchError):
        llm.batch_submit([_request("has space")])
    with pytest.raises(llm.BatchError):
        llm.batch_submit([_request("x" * 65)])
    with pytest.raises(llm.BatchError):
        llm.batch_submit([_request("dup"), _request("dup")])
    with pytest.raises(llm.BatchError):
        llm.batch_submit([])
    assert client.messages.batches.created == []


def test_batch_submit_reserves_budget_and_returns_id():
    client = _install()
    llm.set_budget(llm.Budget(max_usd=1.0))
    reqs = [_request("a-1"), _request("b_2")]

    assert llm.batch_submit(reqs) == "msgbatch_1"
    assert client.messages.batches.created == [reqs]

    llm.set_budget(llm.Budget(max_usd=0.0000001))
    with pytest.raises(llm.BudgetExceeded):
        llm.batch_submit(reqs)


def test_batch_collect_waits_maps_by_custom_id_and_charges_half_price():
    client = _install()
    budget = llm.Budget(max_usd=10.0)
    llm.set_budget(budget)
    client.messages.batches.statuses = ["in_progress", "in_progress"]
    client.messages.batches.results_by_id["msgbatch_1"] = [
        SimpleNamespace(
            custom_id="a",
            result=SimpleNamespace(type="succeeded", message=_message(inp=1_000_000, out=0, model="claude-sonnet-5-5-20260601")),
        ),
        SimpleNamespace(custom_id="b", result=SimpleNamespace(type="errored", error=SimpleNamespace(type="invalid_request"))),
        SimpleNamespace(custom_id="c", result=SimpleNamespace(type="expired")),
    ]

    out = llm.batch_collect("msgbatch_1", poll_seconds=0)

    assert set(out) == {"a", "b", "c"}
    assert out["a"].ok and out["a"].usage.batch is True
    assert out["a"].usage.cost_usd == pytest.approx(1.00)  # 1M Sonnet input tokens: $2.00 → 50% off
    assert out["b"].status == "errored" and "invalid_request" in out["b"].error
    assert out["c"].status == "expired" and not out["c"].ok
    assert budget.spent_usd == pytest.approx(1.00)


def test_batch_wait_times_out():
    client = _install()
    client.messages.batches.statuses = ["in_progress"] * 10
    with pytest.raises(llm.BatchError):
        llm.batch_wait("msgbatch_1", poll_seconds=0, timeout_seconds=0)


def test_usage_from_prices_snapshot_model_ids():
    usage = llm.usage_from(_message(inp=1_000_000, out=0, model="claude-sonnet-5-5-20260601"))
    assert usage.cost_usd == pytest.approx(2.00)
