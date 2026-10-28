"""SEC EDGAR User-Agent comes from SEC_USER_AGENT (fair-access policy)."""

import importlib

import pytest

import src.tools.filings as filings


@pytest.fixture
def restore_filings_module():
    """Reload the module after the test so HEADERS reflects conftest's env again.

    Request this fixture BEFORE monkeypatch so it tears down AFTER monkeypatch
    has restored the environment.
    """
    yield
    importlib.reload(filings)


def test_conftest_user_agent_is_in_effect():
    assert filings.HEADERS["User-Agent"] == "Stockify tests test@example.com"


def test_user_agent_read_from_env(restore_filings_module, monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "Zhihan Chen zc@example.com")
    importlib.reload(filings)
    assert filings.HEADERS["User-Agent"] == "Zhihan Chen zc@example.com"


def test_user_agent_falls_back_when_unset(restore_filings_module, monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    importlib.reload(filings)
    assert filings.HEADERS["User-Agent"] == "Financial Advisor MVP contact@example.com"
