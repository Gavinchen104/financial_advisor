"""Tests for the BriefCache behavior in src.api.

Cache policy: shared across users (content is not user-specific), TTL is
BRIEF_CACHE_TTL_HOURS hours, upsert-on-write (one row per ticker).
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from freezegun import freeze_time

from src.api import _read_cached_brief, _store_cached_brief, BRIEF_CACHE_TTL_HOURS
from src.models import BriefCache


SAMPLE_PAYLOAD = {
    "ticker": "NVDA",
    "what_happened": "up 4%",
    "why_moved": "AI demand",
    "what_it_means": "sector-wide",
    "sources_text": "- [GTC](https://nvidia.com/gtc)",
    "full_brief": "full text",
    "disclaimer": "not investment advice",
    "cached": False,
    "earnings_window": "quiet",
    "days_until_earnings": None,
    "days_since_last_earnings": None,
    "next_earnings_date": None,
    "last_earnings_date": None,
}


def test_cache_miss_returns_none_when_empty(db):
    assert _read_cached_brief(db, "NVDA") is None


def test_cache_hit_after_store(db):
    _store_cached_brief(db, "NVDA", SAMPLE_PAYLOAD)
    cached = _read_cached_brief(db, "NVDA")
    assert cached is not None
    assert cached["ticker"] == "NVDA"
    assert cached["what_happened"] == "up 4%"


def test_cache_store_upserts_existing_row(db):
    """Second store for the same ticker should overwrite, not duplicate."""
    _store_cached_brief(db, "NVDA", SAMPLE_PAYLOAD)
    updated = {**SAMPLE_PAYLOAD, "what_happened": "updated content"}
    _store_cached_brief(db, "NVDA", updated)

    rows = db.query(BriefCache).filter(BriefCache.ticker == "NVDA").all()
    assert len(rows) == 1
    assert _read_cached_brief(db, "NVDA")["what_happened"] == "updated content"


def test_cache_is_ticker_scoped(db):
    _store_cached_brief(db, "NVDA", SAMPLE_PAYLOAD)
    _store_cached_brief(db, "KO", {**SAMPLE_PAYLOAD, "ticker": "KO", "what_happened": "boring"})
    assert _read_cached_brief(db, "NVDA")["what_happened"] == "up 4%"
    assert _read_cached_brief(db, "KO")["what_happened"] == "boring"


def test_cache_expires_after_ttl(db):
    """TTL is BRIEF_CACHE_TTL_HOURS (4h by default). One second past → miss."""
    t0 = datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)
    with freeze_time(t0):
        _store_cached_brief(db, "NVDA", SAMPLE_PAYLOAD)
        # Fresh — hit
        assert _read_cached_brief(db, "NVDA") is not None

    # One hour in — still a hit
    with freeze_time(t0 + timedelta(hours=1)):
        assert _read_cached_brief(db, "NVDA") is not None

    # One second past TTL — miss
    with freeze_time(t0 + timedelta(hours=BRIEF_CACHE_TTL_HOURS, seconds=1)):
        assert _read_cached_brief(db, "NVDA") is None


def test_cache_returns_none_on_corrupted_payload(db):
    """If the stored JSON is corrupt (schema migration mid-flight, etc.), we
    return None rather than raising — caller treats it as a cache miss."""
    db.add(BriefCache(
        ticker="BAD",
        payload="this is not valid json {",
        generated_at=datetime.now(timezone.utc),
    ))
    db.commit()
    assert _read_cached_brief(db, "BAD") is None


def test_cache_payload_is_json_encoded(db):
    """Payload column is Text — we need to encode/decode JSON ourselves."""
    _store_cached_brief(db, "NVDA", SAMPLE_PAYLOAD)
    row = db.query(BriefCache).filter(BriefCache.ticker == "NVDA").one()
    # It's stored as a JSON string, not a Python dict or SQLAlchemy JSON type
    assert isinstance(row.payload, str)
    assert json.loads(row.payload)["ticker"] == "NVDA"
