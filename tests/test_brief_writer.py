"""Tests for src.tools.brief_writer.parse_brief.

The parser is fragile — it does markdown-splitting on ## headers. These tests
pin the current behavior so we can detect regressions when we swap to Gemini's
structured output mode (see the roadmap in CLAUDE.md).
"""

from pathlib import Path

from src.tools.brief_writer import DISCLAIMER, parse_brief


def _read_fixture(brief_fixture_dir: Path, name: str) -> str:
    return (brief_fixture_dir / name).read_text()


def test_parse_happy_path(brief_fixture_dir):
    text = _read_fixture(brief_fixture_dir, "happy.md")
    result = parse_brief(text, "NVDA")

    assert result["ticker"] == "NVDA"
    assert "NVIDIA closed the week up 4.2%" in result["what_happened"]
    assert "hyperscaler partnerships" in result["why_moved"]
    assert "AI data center GPUs" in result["what_it_means"]
    assert "nvidia.com/gtc/keynote" in result["sources_text"]
    assert result["disclaimer"] == DISCLAIMER
    # Full brief gets the disclaimer appended after a horizontal rule
    assert result["full_brief"].endswith(f"*{DISCLAIMER}*")
    assert "---" in result["full_brief"]


def test_parse_accepts_shortened_header(brief_fixture_dir):
    """The parser accepts '## What it means' as an alias for '## What it means
    for a first-year investor'. This keeps Gemini robust against minor drift."""
    text = _read_fixture(brief_fixture_dir, "alt_headers.md")
    result = parse_brief(text, "KO")

    assert result["ticker"] == "KO"
    assert "Coca-Cola traded sideways" in result["what_happened"]
    assert "Quiet weeks are common" in result["what_it_means"]
    # Make sure the alt header didn't spill into why_moved
    assert "Quiet weeks" not in result["why_moved"]


def test_parse_missing_section_returns_empty_string(brief_fixture_dir):
    """When the model omits a section (e.g., invalid ticker brief), the field
    is an empty string rather than raising or returning None."""
    text = _read_fixture(brief_fixture_dir, "missing_section.md")
    result = parse_brief(text, "ZZZZ")

    assert result["ticker"] == "ZZZZ"
    assert "does not appear in our price data" in result["what_happened"]
    assert result["why_moved"] == ""  # section absent → empty
    assert result["what_it_means"] == ""
    assert "finance.yahoo.com/lookup" in result["sources_text"]


def test_parse_empty_input(brief_fixture_dir):
    """Empty model output shouldn't crash — every field is empty, disclaimer
    still appended, ticker still echoed."""
    text = _read_fixture(brief_fixture_dir, "empty.md")
    result = parse_brief(text, "AAPL")

    assert result["ticker"] == "AAPL"
    assert result["what_happened"] == ""
    assert result["why_moved"] == ""
    assert result["what_it_means"] == ""
    assert result["sources_text"] == ""
    assert result["disclaimer"] == DISCLAIMER
    # Even with empty text, the rendered brief includes the disclaimer block
    assert DISCLAIMER in result["full_brief"]


def test_ticker_normalized_to_upper():
    result = parse_brief("## What happened\nbody", "nvda")
    assert result["ticker"] == "NVDA"


def test_content_before_first_heading_is_dropped():
    """The parser is section-driven. Stray preamble before the first ## should
    not leak into any section. This catches models that add apologetic intros."""
    text = (
        "Here is the brief you asked for:\n\n"
        "## What happened\nthe actual content\n"
    )
    result = parse_brief(text, "AAPL")
    assert result["what_happened"] == "the actual content"
    assert "Here is the brief" not in result["what_happened"]
    assert "Here is the brief" not in result["why_moved"]
