"""Section-bounded chunker (docs/PROJECT2-PLAN.md P2-C).

- ~450 tokens per chunk, approximated as characters / 4, with ~15% overlap
- chunks never cross a section boundary and never split a table row
  (a line containing " | ", as html_text.table_rows emits them)
- long paragraphs are split into sentences first so chunks pack tightly
- every chunk starts with "{company} {form} {period} — {section title}\\n", which
  helps both the embedding and keyword search know what the passage is about
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from . import config
from .html_text import section_title

TARGET_CHARS = config.CHUNK_TARGET_TOKENS * config.CHARS_PER_TOKEN  # 1800
OVERLAP_CHARS = int(TARGET_CHARS * config.CHUNK_OVERLAP)  # 270
HARD_MAX_CHARS = 7000  # ≈ 1750 tokens; keeps every chunk under the 2,048-token embedding limit
MAX_PARAGRAPH_UNIT = 600  # longer paragraphs are split into sentences

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\"'])")


@dataclass(frozen=True)
class Unit:
    text: str
    is_row: bool
    continues: bool = False  # a sentence that continues the previous unit's paragraph


@dataclass
class Chunk:
    text: str
    section: str
    ord: int
    page: int | None = None

    @property
    def est_tokens(self) -> int:
        return math.ceil(len(self.text) / config.CHARS_PER_TOKEN)


def chunk_prefix(company: str, form: str, period: str, section: str) -> str:
    return f"{company} {form} {period} — {section_title(form, section)}\n"


def _units(text: str) -> list[Unit]:
    units: list[Unit] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if " | " in line:
            units.append(Unit(line, is_row=True))
        elif len(line) <= MAX_PARAGRAPH_UNIT:
            units.append(Unit(line, is_row=False))
        else:
            sentences = [s for s in _SENTENCE_SPLIT.split(line) if s.strip()]
            units.extend(Unit(s, is_row=False, continues=i > 0) for i, s in enumerate(sentences))
    return units


def _hard_split(text: str, limit: int) -> list[str]:
    """Last resort for a single unit longer than HARD_MAX_CHARS: split at whitespace."""
    pieces, cur = [], ""
    for word in text.split(" "):
        if cur and len(cur) + 1 + len(word) > limit:
            pieces.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}" if cur else word
    if cur:
        pieces.append(cur)
    return pieces


def _render(units: list[Unit]) -> str:
    """Source lines (paragraphs, headings, table rows) keep their line breaks; the
    sentences of one long paragraph are re-joined with spaces."""
    out = ""
    for i, u in enumerate(units):
        if i == 0:
            out = u.text
        else:
            out += (" " if u.continues and not units[i - 1].is_row else "\n") + u.text
    return out


def chunk_text(
    text: str,
    *,
    prefix: str = "",
    target_chars: int = TARGET_CHARS,
    overlap_chars: int = OVERLAP_CHARS,
    hard_max_chars: int = HARD_MAX_CHARS,
) -> list[str]:
    """Greedy packing of lines / sentences / table rows into chunks of about
    `target_chars` (prefix included), carrying whole trailing units of about
    `overlap_chars` into the next chunk. Rows are never split; a single unit longer
    than `hard_max_chars` is split at whitespace (pathological rows only)."""
    budget = max(target_chars - len(prefix), 200)
    units = _units(text)
    chunks: list[str] = []
    cur: list[Unit] = []
    cur_len = 0

    def flush() -> None:
        nonlocal cur, cur_len
        if cur:
            chunks.append(prefix + _render(cur))
        # overlap: keep trailing whole units up to overlap_chars (never the whole chunk)
        keep: list[Unit] = []
        size = 0
        for u in reversed(cur[1:]):
            if size + len(u.text) > overlap_chars:
                break
            keep.insert(0, u)
            size += len(u.text) + 1
        cur, cur_len = keep, size

    for unit in units:
        length = len(unit.text) + (1 if cur else 0)
        if cur and cur_len + length > budget:
            flush()
            length = len(unit.text) + (1 if cur else 0)
            if cur and cur_len + length > budget:  # overlap alone is too big for this unit
                cur, cur_len = [], 0
                length = len(unit.text)
        if len(unit.text) > budget:  # oversize unit: its own chunk(s)
            if cur:
                chunks.append(prefix + _render(cur))
                cur, cur_len = [], 0
            pieces = [unit.text] if len(unit.text) <= hard_max_chars else _hard_split(unit.text, hard_max_chars)
            chunks.extend(prefix + p for p in pieces)
            continue
        cur.append(unit)
        cur_len += length
    if cur:
        chunks.append(prefix + _render(cur))
    return chunks


def chunk_filing(
    sections: dict[str, str],
    *,
    company: str,
    form: str,
    period: str,
) -> list[Chunk]:
    """Chunks for every section of one filing, `ord` increasing across the filing."""
    out: list[Chunk] = []
    for section, text in sections.items():
        prefix = chunk_prefix(company, form, period, section)
        for piece in chunk_text(text, prefix=prefix):
            out.append(Chunk(text=piece, section=section, ord=len(out)))
    return out
