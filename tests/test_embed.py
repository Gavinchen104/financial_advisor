"""Gemini embedding wrapper with a fake client: batching, task types, normalization,
retries, budget (P2-C). No network."""

import math

import pytest
from google.genai import errors as genai_errors

from src.rag import config, embed
from src.rag.llm import Budget, BudgetExceeded


class _Embedding:
    def __init__(self, values):
        self.values = values


class _Response:
    def __init__(self, embeddings):
        self.embeddings = embeddings


class FakeModels:
    def __init__(self, *, fail_with: list[Exception] | None = None, dim: int = embed.DIM, short: bool = False):
        self.calls: list[dict] = []
        self.fail_with = list(fail_with or [])
        self.dim = dim
        self.short = short

    def embed_content(self, *, model, contents, config):
        self.calls.append({
            "model": model, "contents": list(contents),
            "task": config.task_type, "dim": config.output_dimensionality,
        })
        if self.fail_with:
            raise self.fail_with.pop(0)
        n = len(contents) - (1 if self.short else 0)
        # deliberately NOT unit length: value depends on the text index
        return _Response([_Embedding([float(i + 1)] * self.dim) for i in range(n)])


class FakeClient:
    def __init__(self, **kwargs):
        self.models = FakeModels(**kwargs)


@pytest.fixture
def fake(monkeypatch):
    client = FakeClient()
    embed.set_client(client)
    embed.set_budget(Budget())
    monkeypatch.setattr(embed, "RETRY_WAIT_MAX", 0)
    yield client
    embed.set_client(None)
    embed.set_budget(Budget())


def test_documents_are_batched_with_document_task(fake):
    texts = [f"chunk {i}" for i in range(120)]
    vectors = embed.embed_documents(texts)
    assert len(vectors) == 120
    assert [len(c["contents"]) for c in fake.models.calls] == [50, 50, 20]
    assert {c["task"] for c in fake.models.calls} == {"RETRIEVAL_DOCUMENT"}
    assert {c["dim"] for c in fake.models.calls} == {768}
    assert {c["model"] for c in fake.models.calls} == {"gemini-embedding-001"}


def test_vectors_are_unit_length_768d(fake):
    for v in embed.embed_documents(["a", "b", "c"]):
        assert len(v) == 768
        assert math.sqrt(sum(x * x for x in v)) == pytest.approx(1.0, abs=1e-5)


def test_query_uses_query_task(fake):
    v = embed.embed_query("What was NVIDIA's revenue?")
    assert len(v) == 768
    assert fake.models.calls[0]["task"] == "RETRIEVAL_QUERY"
    assert fake.models.calls[0]["contents"] == ["What was NVIDIA's revenue?"]


def test_empty_input_makes_no_call(fake):
    assert embed.embed_documents([]) == []
    assert fake.models.calls == []


def test_retries_on_429_and_5xx_then_succeeds(monkeypatch):
    client = FakeClient(fail_with=[
        genai_errors.APIError(429, {"error": {"message": "quota"}}),
        genai_errors.APIError(503, {"error": {"message": "unavailable"}}),
    ])
    embed.set_client(client)
    monkeypatch.setattr(embed, "RETRY_WAIT_MAX", 0)
    try:
        assert len(embed.embed_documents(["x"])) == 1
        assert len(client.models.calls) == 3
    finally:
        embed.set_client(None)


def test_does_not_retry_client_errors(monkeypatch):
    client = FakeClient(fail_with=[genai_errors.APIError(400, {"error": {"message": "bad request"}})])
    embed.set_client(client)
    monkeypatch.setattr(embed, "RETRY_WAIT_MAX", 0)
    try:
        with pytest.raises(genai_errors.APIError):
            embed.embed_documents(["x"])
        assert len(client.models.calls) == 1
    finally:
        embed.set_client(None)


def test_budget_refuses_before_spending(fake):
    embed.set_budget(Budget(max_usd=1e-9))
    with pytest.raises(BudgetExceeded):
        embed.embed_documents(["some text"] * 3)
    assert fake.models.calls == []


def test_budget_is_charged_the_estimate(fake):
    texts = ["x" * 400] * 60  # 100 tokens each → 6,000 tokens → 2 batches
    budget = Budget(max_usd=1.0)
    embed.set_budget(budget)
    embed.embed_documents(texts)
    assert budget.calls == 2
    assert budget.spent_usd == pytest.approx(config.embed_cost_usd(6000))


def test_estimates_use_chars_over_four():
    assert embed.estimate_tokens(["abcd", "abcde"]) == 1 + 2
    assert embed.estimate_cost_usd(["x" * 4_000_000]) == pytest.approx(config.EMBED_PRICE_PER_MTOK)


def test_wrong_vector_count_raises(monkeypatch):
    client = FakeClient(short=True)
    embed.set_client(client)
    monkeypatch.setattr(embed, "RETRY_WAIT_MAX", 0)
    try:
        with pytest.raises(embed.EmbedError):
            embed.embed_documents(["a", "b"])
    finally:
        embed.set_client(None)


def test_overlong_texts_are_truncated_to_the_model_limit(fake):
    embed.embed_documents(["y" * (embed.MAX_CHARS + 500)])
    assert len(fake.models.calls[0]["contents"][0]) == embed.MAX_CHARS


def test_missing_api_key_is_a_clear_error(monkeypatch):
    embed.set_client(None)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(embed.MissingAPIKeyError):
        embed.get_client()
