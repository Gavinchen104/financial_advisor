"""Section-bounded chunker (P2-C)."""

import math

from src.rag import config
from src.rag.chunk import HARD_MAX_CHARS, TARGET_CHARS, Chunk, chunk_filing, chunk_prefix, chunk_text

PREFIX = "Acme Widgets, Inc. 10-K FY2025 — Item 7. Management's Discussion and Analysis\n"


def _paragraph(i: int, sentences: int = 3) -> str:
    return " ".join(
        f"Sentence {i}-{j} explains that revenue in segment {j} changed because of pricing and mix." for j in range(sentences)
    )


def _row(i: int) -> str:
    return f"Line item {i} | ${i * 1000:,} | ({i} | )% | ${i * 900:,}".replace("({i} | )%", f"({i})%")


SECTION = "\n".join([_paragraph(i) for i in range(12)] + [_row(i) for i in range(40)] + [_paragraph(i) for i in range(12, 20)])
ROWS = {_row(i) for i in range(40)}


def _body(chunk: str) -> str:
    assert chunk.startswith(PREFIX)
    return chunk[len(PREFIX):]


def test_every_chunk_has_prefix_and_respects_target_size():
    chunks = chunk_text(SECTION, prefix=PREFIX)
    assert len(chunks) > 3
    for c in chunks:
        assert c.startswith(PREFIX)
        assert len(c) <= TARGET_CHARS
        assert math.ceil(len(c) / config.CHARS_PER_TOKEN) <= config.CHUNK_TARGET_TOKENS


def test_table_rows_are_never_split():
    chunks = chunk_text(SECTION, prefix=PREFIX)
    seen_rows = []
    for c in chunks:
        for line in _body(c).split("\n"):
            if " | " in line:
                assert line in ROWS, f"partial row: {line!r}"
                seen_rows.append(line)
    assert set(seen_rows) == ROWS  # every row survives, whole


def test_consecutive_chunks_overlap_by_whole_units():
    chunks = [_body(c) for c in chunk_text(SECTION, prefix=PREFIX)]
    for prev, nxt in zip(chunks, chunks[1:]):
        first_line = nxt.split("\n")[0]
        assert first_line and first_line in prev, "the next chunk should start with units carried over from the previous one"


def test_source_lines_keep_their_breaks_but_split_sentences_rejoin():
    heading = "Item 7. Management's Discussion"
    long_paragraph = " ".join(f"Sentence {i} of a paragraph that is long enough to be split into sentences first." for i in range(10))
    assert len(long_paragraph) > 600
    chunks = [_body(c) for c in chunk_text(f"{heading}\n{long_paragraph}\nShort closing line.", prefix=PREFIX)]
    assert len(chunks) == 1
    lines = chunks[0].split("\n")
    assert lines[0] == heading and lines[-1] == "Short closing line."
    assert lines[1] == long_paragraph  # sentences re-joined on one line


def test_overlap_is_bounded():
    chunks = [_body(c) for c in chunk_text(SECTION, prefix=PREFIX)]
    total = sum(len(c) for c in chunks)
    assert total < len(SECTION) * 1.45  # 15% overlap target, generous bound


def test_long_paragraph_is_split_at_sentence_boundaries():
    paragraph = " ".join(f"This is sentence number {i} of a very long paragraph about margins." for i in range(120))
    assert len(paragraph) > 3 * TARGET_CHARS
    chunks = [_body(c) for c in chunk_text(paragraph, prefix=PREFIX)]
    assert len(chunks) >= 3
    for c in chunks:
        assert c.endswith("."), "chunks end on a sentence boundary"
        assert len(PREFIX) + len(c) <= TARGET_CHARS


def test_oversize_row_becomes_its_own_chunk_and_pathological_rows_are_hard_split():
    big_row = " | ".join(f"cell {i}" for i in range(400))  # ~3,500 chars, above the target, under the hard max
    chunks = chunk_text(f"intro line\n{big_row}\noutro line", prefix=PREFIX)
    bodies = [_body(c) for c in chunks]
    assert big_row in bodies  # intact, alone
    assert bodies[0] == "intro line"

    huge_row = " | ".join(f"cell {i}" for i in range(1200))
    assert len(huge_row) > HARD_MAX_CHARS
    pieces = [_body(c) for c in chunk_text(huge_row, prefix=PREFIX)]
    assert len(pieces) >= 2 and all(len(p) <= HARD_MAX_CHARS for p in pieces)
    assert " ".join(pieces) == huge_row


def test_empty_or_blank_section_yields_no_chunks():
    assert chunk_text("", prefix=PREFIX) == []
    assert chunk_text("\n\n  \n", prefix=PREFIX) == []


def test_chunk_filing_metadata_and_ordering():
    sections = {"item_1": _paragraph(1) + "\n" + _paragraph(2), "item_7": SECTION}
    chunks = chunk_filing(sections, company="Acme Widgets, Inc.", form="10-K", period="FY2025")
    assert [c.ord for c in chunks] == list(range(len(chunks)))
    assert chunks[0].section == "item_1" and chunks[-1].section == "item_7"
    assert chunks[0].text.startswith("Acme Widgets, Inc. 10-K FY2025 — Item 1. Business\n")
    assert chunks[-1].text.startswith(PREFIX)
    assert all(isinstance(c, Chunk) and c.page is None for c in chunks)
    assert chunks[0].est_tokens == math.ceil(len(chunks[0].text) / 4)
    sections_seen = {c.section for c in chunks}
    assert sections_seen == {"item_1", "item_7"}


def test_chunk_prefix_uses_section_titles():
    assert chunk_prefix("Acme", "10-Q", "quarter ended 2025-06-28", "item_2") == (
        "Acme 10-Q quarter ended 2025-06-28 — Part I, Item 2. Management's Discussion and Analysis\n"
    )
    assert chunk_prefix("Acme", "10-K", "FY2025", "full") == "Acme 10-K FY2025 — Full filing\n"
