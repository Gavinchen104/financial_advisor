"""src/rag/config.py — price table math and env lookups."""

import pytest

from src.rag import config


# ---------- cost_usd ----------
def test_haiku_standard_tier():
    # 10k in @ $0.10/M + 1k out @ $0.50/M
    assert config.cost_usd("claude-haiku-5-5", 10_000, 1_000) == pytest.approx(0.0010 + 0.0005)


def test_haiku_long_context_tier_above_100k_tokens():
    # 150k in @ $0.50/M + 1k out @ $2.50/M
    assert config.cost_usd("claude-haiku-5-5", 150_000, 1_000) == pytest.approx(0.075 + 0.0025)


def test_haiku_tier_boundary_is_exclusive():
    at = config.cost_usd("claude-haiku-5-5", 100_000, 0)
    above = config.cost_usd("claude-haiku-5-5", 100_001, 0)
    assert at == pytest.approx(0.01)
    assert above == pytest.approx(100_001 * 0.50 / 1_000_000)


def test_long_tier_is_decided_on_the_whole_prompt_including_cache():
    # 60k uncached + 60k cache reads = 120k prompt → long rates; cache reads at 0.1×
    cost = config.cost_usd("claude-haiku-5-5", 60_000, 0, cache_read_tokens=60_000)
    assert cost == pytest.approx((60_000 * 0.50 + 60_000 * 0.50 * 0.1) / 1_000_000)


def test_sonnet_rates_and_cache_read_multiplier():
    assert config.cost_usd("claude-sonnet-5-5", 1_000_000, 0) == pytest.approx(2.00)
    assert config.cost_usd("claude-sonnet-5-5", 0, 1_000_000) == pytest.approx(10.00)
    assert config.cost_usd("claude-sonnet-5-5", 0, 0, cache_read_tokens=1_000_000) == pytest.approx(0.10)


def test_batch_discount_halves_the_cost():
    full = config.cost_usd("claude-sonnet-5-5", 500_000, 50_000)
    assert config.cost_usd("claude-sonnet-5-5", 500_000, 50_000, batch=True) == pytest.approx(full / 2)


def test_unknown_model_raises_instead_of_guessing():
    with pytest.raises(config.UnknownModelError):
        config.cost_usd("claude-9-ultra", 1, 1)


def test_snapshot_model_ids_price_by_prefix():
    assert config.price_for("claude-haiku-5-5-20260401") is config.PRICES["claude-haiku-5-5"]
    assert config.price_for("claude-sonnet-5-5-20260601") is config.PRICES["claude-sonnet-5-5"]


def test_embedding_cost():
    assert config.embed_cost_usd(1_000_000) == pytest.approx(0.15)
    assert config.embed_cost_usd(1_000_000, batch=True) == pytest.approx(0.075)


# ---------- env lookups ----------
def test_model_defaults_and_overrides(monkeypatch):
    monkeypatch.delenv("ASK_MODEL_DEFAULT", raising=False)
    monkeypatch.delenv("ASK_MODEL_AUTHED", raising=False)
    assert config.ask_model_default() == "claude-haiku-5-5"
    assert config.ask_model_authed() == "claude-sonnet-5-5"

    monkeypatch.setenv("ASK_MODEL_DEFAULT", "claude-sonnet-5-5")
    assert config.ask_model_default() == "claude-sonnet-5-5"


def test_daily_cap_parses_and_falls_back(monkeypatch):
    monkeypatch.setenv("ASK_DAILY_USD_CAP", "2.50")
    assert config.ask_daily_usd_cap() == 2.5
    monkeypatch.setenv("ASK_DAILY_USD_CAP", "not-a-number")
    assert config.ask_daily_usd_cap() == 1.0
    monkeypatch.delenv("ASK_DAILY_USD_CAP")
    assert config.ask_daily_usd_cap() == 1.0


def test_sec_user_agent(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "Zhihan Chen zc@example.com")
    assert config.sec_user_agent() == "Zhihan Chen zc@example.com"
    monkeypatch.setenv("SEC_USER_AGENT", "")
    assert config.sec_user_agent() == "Financial Advisor MVP contact@example.com"


def test_anthropic_key_empty_is_none(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    assert config.anthropic_api_key() is None


def test_tests_run_on_sqlite_so_rag_is_off():
    assert config.uses_postgres() is False
