"""iXBRL / HTML filings → clean text, and the 10-K / 10-Q section splitter
(docs/PROJECT2-PLAN.md P2-C).

html_to_text():
- deletes ix:header (hidden XBRL facts, contexts, units) and anything styled
  display:none BEFORE extracting text, then drops scripts/styles/head
- tables become one line per row, cells joined with " | ": empty spacer cells
  are dropped, a lone "$" is merged into the next cell, a trailing ")" / "%" into
  the previous one, header rows (years) are kept
- block elements become line breaks; inline elements (span, ix:nonnumeric, b, …)
  stay inline, so sentences survive iXBRL's span soup
- unicode is NFKC-normalized; non-breaking spaces, dashes, curly quotes and
  zero-width characters are normalized

split_sections(): 10-K Items 1, 1A, 7, 7A, 8; 10-Q Part I Items 1 and 2. For
each item the occurrence followed by the most text wins, which skips the table
of contents and the short Part II items of a 10-Q. When a required section is
missing the whole text is kept as section 'full' and the fallback is counted.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable

from lxml import html as lxml_html

# Tags whose subtree is never text: hidden XBRL machinery, scripts, styles, head.
SKIP_TAGS = frozenset({
    "script", "style", "head", "title", "noscript", "meta", "link",
    "ix:header", "ix:hidden", "ix:references", "ix:resources",
})
BLOCK_TAGS = frozenset({
    "p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "td", "th",
    "thead", "tbody", "tfoot", "caption", "section", "article", "hr", "blockquote", "pre",
    "body", "html", "center", "dd", "dt", "dl", "address", "figure", "figcaption", "main",
    "header", "footer", "nav", "aside", "form", "fieldset", "legend",
})
CURRENCY_CELLS = frozenset({"$", "US$", "USD", "€", "£", "¥"})
SUFFIX_CELLS = frozenset({")", ")%", "%", "%)"})

_DISPLAY_NONE = re.compile(r"display\s*:\s*none", re.I)
_XML_DECL = re.compile(r"^\s*<\?xml[^>]*\?>", re.I)
_HSPACE = re.compile(r"[ \t\f\v\r]+")
_TRANSLATE = {
    **dict.fromkeys(map(ord, "‐‑‒–—―−"), "-"),
    **{ord("‘"): "'", ord("’"): "'", ord("‚"): "'", ord("′"): "'"},
    **{ord("“"): '"', ord("”"): '"', ord("„"): '"', ord("″"): '"'},
    **dict.fromkeys(map(ord, "​‌‍⁠﻿­"), None),
}


# ---------- normalization ----------
def normalize_text(text: str) -> str:
    """NFKC (also turns non-breaking spaces into spaces), ASCII dashes and quotes,
    zero-width characters removed. Whitespace is left alone."""
    return unicodedata.normalize("NFKC", text).translate(_TRANSLATE).replace("\xa0", " ")


def clean_text(raw: str) -> str:
    """normalize_text + one space between words, stripped lines, at most one blank line."""
    lines = [_HSPACE.sub(" ", line).strip() for line in normalize_text(raw).split("\n")]
    out: list[str] = []
    blank = True  # swallow leading blanks
    for line in lines:
        if line:
            out.append(line)
            blank = False
        elif not blank:
            out.append("")
            blank = True
    while out and not out[-1]:
        out.pop()
    return "\n".join(out) + ("\n" if out else "")


# ---------- HTML → text ----------
def parse_html(html: str) -> lxml_html.HtmlElement:
    html = _XML_DECL.sub("", html, count=1)
    parser = lxml_html.HTMLParser(huge_tree=True)
    return lxml_html.document_fromstring(html or "<html></html>", parser=parser)


def strip_hidden(root: lxml_html.HtmlElement) -> int:
    """Remove ix:header and friends, scripts/styles/head, and display:none elements.
    Returns how many elements were dropped."""
    doomed = []
    for el in root.iter():
        tag = el.tag
        if not isinstance(tag, str):
            continue  # comments, processing instructions
        if tag in SKIP_TAGS or _DISPLAY_NONE.search(el.get("style") or ""):
            doomed.append(el)
    for el in reversed(doomed):  # children before parents
        if el.getparent() is not None:
            el.drop_tree()
    return len(doomed)


def merge_cells(cells: list[str]) -> list[str]:
    """Drop empty spacer cells; glue a lone currency symbol to the next cell and a
    lone ')' / '%' to the previous one, so '$ | (1,234 | )' → '$(1,234)'."""
    out: list[str] = []
    pending: str | None = None
    for cell in cells:
        cell = cell.strip()
        if not cell:
            continue
        if cell in CURRENCY_CELLS:
            pending = pending or cell
            continue
        if cell in SUFFIX_CELLS:  # attaches to the previous cell; meaningless on its own
            if out:
                out[-1] += cell
            continue
        if pending:
            if not cell.startswith(pending):
                cell = pending + cell
            pending = None
        out.append(cell)
    return out


def _cell_text(cell) -> str:
    """Inline children concatenate directly ("(" + "2" → "(2"); block children and
    nested table rows become single spaces."""
    parts: list[str] = []
    for child in cell:
        _walk(child, parts)
    raw = (cell.text or "") + "".join(parts)
    return re.sub(r"\s+", " ", normalize_text(raw)).strip()


def table_rows(table) -> list[str]:
    """One string per row, cells joined with ' | '. Nested tables are flattened
    into their parent cell's text."""
    rows: list[str] = []
    for tr in table.xpath("./tr | ./thead/tr | ./tbody/tr | ./tfoot/tr"):
        cells = [_cell_text(c) for c in tr if isinstance(c.tag, str) and c.tag in ("td", "th")]
        merged = merge_cells(cells)
        if merged:
            rows.append(" | ".join(merged))
    return rows


def _walk(el, out: list[str]) -> None:
    tag = el.tag
    if not isinstance(tag, str):  # comment / PI: keep only the tail text
        if el.tail:
            out.append(el.tail)
        return
    if tag == "table":
        rows = table_rows(el)
        if rows:
            out.append("\n" + "\n".join(rows) + "\n")
        if el.tail:
            out.append(el.tail)
        return
    if tag == "br":
        out.append("\n")
        if el.tail:
            out.append(el.tail)
        return
    block = tag in BLOCK_TAGS
    if block:
        out.append("\n")
    if el.text:
        out.append(el.text)
    for child in el:
        _walk(child, out)
    if block:
        out.append("\n")
    if el.tail:
        out.append(el.tail)


def html_to_text(html: str) -> str:
    """Readable text of a filing with tables as rows. No ix:/us-gaap: residue."""
    root = parse_html(html)
    strip_hidden(root)
    parts: list[str] = []
    _walk(root, parts)
    return clean_text("".join(parts))


# ---------- sections ----------
SECTION_TITLES: dict[str, dict[str, str]] = {
    "10-K": {
        "item_1": "Item 1. Business",
        "item_1a": "Item 1A. Risk Factors",
        "item_7": "Item 7. Management's Discussion and Analysis",
        "item_7a": "Item 7A. Quantitative and Qualitative Disclosures About Market Risk",
        "item_8": "Item 8. Financial Statements and Supplementary Data",
    },
    "10-Q": {
        "item_1": "Part I, Item 1. Financial Statements",
        "item_2": "Part I, Item 2. Management's Discussion and Analysis",
    },
}
REQUIRED_SECTIONS: dict[str, tuple[str, ...]] = {
    "10-K": ("item_1", "item_1a", "item_7", "item_8"),  # 7A is optional (often "not applicable")
    "10-Q": ("item_1", "item_2"),
}
FULL_SECTION = "full"
FULL_TITLE = "Full filing"
# A section must hold at least this much text. Shorter matches are table-of-contents
# lines, "Not applicable" items, or the 200–400-character stubs wrapper filings
# (Wells Fargo, IBM, JPMorgan) keep under each Item ("see pages 12–47 of the Annual
# Report"); none of them is worth a labelled chunk.
MIN_SECTION_CHARS = 600
# A split must cover this share of the text. Cross-reference indexes ("Item 1.
# Financial Statements — see page 3", Wells Fargo / JPMorgan style) yield sections
# of a few hundred characters that would otherwise pass as a success.
MIN_COVERAGE = {"10-K": 0.30, "10-Q": 0.15}
# When the statements section is missing or is only a pointer ("see page 58"), the
# statements are rescued from a statements heading: after the last heading (Disney,
# Chevron, Oracle), inside the MD&A section (PepsiCo), after the MD&A (Morgan Stanley
# 10-Qs), before the MD&A (Netflix, Linde, Abbott 10-Qs) or after the pointer itself.
# A real statements section of a large company runs well past 20k characters; a
# shorter one is a pointer or an index block, and a rescued block must beat it.
POINTER_RESCUE_MIN_CHARS = 20_000

# Mode 1 — "Item 1.", "ITEM 1A —", "Part I. Item 2:", "Item 7 | Management's…" at a
# line start. The optional "Part I" prefix must sit on the same line, so a "PART I"
# line of its own is not swallowed into the section text.
_ITEM_HEADING = re.compile(
    r"^(?:part[ \t]+(?:i{1,3}|iv)\b[ \t.,:\-|]*)?items?[ \t]+(\d{1,2}[a-c]?)(?=[\s.:\-|)]|$)",
    re.I | re.M,
)

# Mode 2 — title-only headings (Morgan Stanley, McDonald's, GE and the banks label
# sections by name and keep the Item numbers in an index). Whole-line matches only,
# so table rows such as "Business | 1,234" are never headings.
_MDA = (
    r"management'?s? discussion and analysis(?: of (?:financial condition and )?results of operations)?"
    r"(?: \(md&a\))?|md&a|management'?s? discussion|financial review"
)


def _title_re(*alternatives: str) -> re.Pattern:
    body = "|".join(alternatives)
    # An optional trailing page cell ("Risk Factors | 24-31") covers filers whose
    # headings are table rows (GE); rows with several numeric cells never match.
    return re.compile(
        rf"^(?:item[ \t]+\d{{1,2}}[a-c]?[ \t.:\-|]*)?(?:{body})[ \t.:]*(?:\|[ \t]*\d{{1,3}}(?:[ \t]*-[ \t]*\d{{1,3}})?)?$",
        re.I | re.M,
    )


_TITLE_HEADINGS: dict[str, dict[str, re.Pattern]] = {
    "10-K": {
        "item_1": _title_re(
            r"business(?: overview| summary)?", r"our business", r"description of (?:the )?business",
            r"about [a-z0-9&' -]{2,40}",  # "About GE Aerospace"
        ),
        "item_1a": _title_re(r"risk factors"),
        "item_7": _title_re(_MDA),
        "item_7a": _title_re(r"quantitative and qualitative disclosures? about (?:market )?risks?"),
        "item_8": _title_re(
            r"financial statements and supplementary data",
            r"(?:audited |consolidated )?financial statements(?: and (?:notes|supplementary data))?",
        ),
    },
    "10-Q": {
        "item_1": _title_re(r"(?:condensed )?(?:consolidated )?financial statements(?: \(unaudited\))?(?: and notes)?"),
        "item_2": _title_re(_MDA),
    },
}
# Other section titles: they close a section but are not kept. Form-aware, because a
# 10-Q's "Risk Factors" (Part II) or "Quantitative and Qualitative Disclosures" (Item 3)
# is a boundary while the same title is a section of a 10-K.
_COMMON_TERMINATORS = (
    r"unresolved staff comments", r"cybersecurity", r"properties", r"legal proceedings",
    r"mine safety disclosures?", r"controls and procedures", r"changes in and disagreements with accountants.*",
    r"other information", r"exhibits?(?: and financial statement schedules)?", r"signatures?",
    r"market for (?:the )?registrant'?s common equity.*", r"selected financial data", r"\[?reserved\]?",
    r"directors,? executive officers.*", r"executive compensation", r"security ownership.*",
    r"certain relationships.*", r"principal accountant fees and services", r"form 10-k summary",
    r"defaults upon senior securities", r"unregistered sales of equity securities.*", r"forward-looking statements",
    r"glossary(?: of terms)?",
)
_TITLE_TERMINATORS: dict[str, re.Pattern] = {
    "10-K": _title_re(*_COMMON_TERMINATORS),
    "10-Q": _title_re(
        *_COMMON_TERMINATORS, r"risk factors", r"business",
        r"quantitative and qualitative disclosures? about (?:market )?risks?",
    ),
}
# Statements printed after Part IV start with one of these lines.
# Exact statement titles only (plus the auditor's report and the statements index),
# optionally followed by "(Unaudited)", "(in millions)" or " - Quarters Ended …".
# MD&A sub-headings such as "Consolidated balance sheets analysis" do not match.
_STATEMENTS_HEADING = re.compile(
    r"^(?:report of independent registered public accounting firm[^|]*"
    r"|index to (?:consolidated )?financial statements[^|]*"
    r"|(?:condensed )?consolidated (?:"
    r"statements? of (?:income|operations|earnings|comprehensive (?:income|earnings|loss)(?: \(loss\))?|cash flows?"
    r"|financial (?:position|condition)|(?:changes in )?(?:stockholders'?|shareholders'?|total )?equity)"
    r"|balance sheets?|income statements?|cash flows? statements?|comprehensive income statements?"
    r"|statements? of changes in total equity)"
    r"(?:\s*\([^)|]{1,40}\))*(?:\s*-\s*[^|]{1,80})?\.?)$",
    re.I | re.M,
)


def form_key(form: str) -> str:
    return "10-Q" if form.upper().startswith("10-Q") else "10-K"


def section_title(form: str, section: str) -> str:
    if section == FULL_SECTION:
        return FULL_TITLE
    return SECTION_TITLES[form_key(form)].get(section, section)


@dataclass
class SectionSplit:
    form: str
    mode: str = "full"  # item | title | full
    sections: dict[str, str] = field(default_factory=dict)  # section id → text, document order
    found: list[str] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    coverage: float = 0.0  # share of the text inside the kept sections (1.0 for full)
    fallback: bool = False

    def summary(self) -> str:
        if self.fallback:
            gaps = f"missing {', '.join(self.missing_required)}" if self.missing_required else f"coverage {self.coverage:.0%}"
            return f"fallback=full ({gaps})"
        return f"{self.mode}: " + ", ".join(self.found)


Heading = tuple[int, str | None]  # (position, section id or None for a boundary-only heading)


# A heading line that ends in a page number ("Item 1. | Business | 3", "Item 2. Properties 15")
# is a table-of-contents row: it closes a section but never starts one, so the last
# row of a TOC cannot swallow the body that follows it.
_TOC_ROW_END = re.compile(r"(?:\|\s*|\s)\d{1,3}(?:\s*-\s*\d{1,3})?\s*$")


def _item_headings(text: str) -> list[Heading]:
    out: list[Heading] = []
    for m in _ITEM_HEADING.finditer(text):
        line_end = text.find("\n", m.start())
        line = text[m.start():line_end if line_end >= 0 else len(text)]
        out.append((m.start(), None if _TOC_ROW_END.search(line) else f"item_{m.group(1).lower()}"))
    return out


def _title_headings(text: str, key: str) -> list[Heading]:
    found: list[Heading] = [(m.start(), None) for m in _TITLE_TERMINATORS[key].finditer(text)]
    for section, pattern in _TITLE_HEADINGS[key].items():
        found += [(m.start(), section) for m in pattern.finditer(text)]
    found.sort(key=lambda h: (h[0], h[1] is None))
    deduped: list[Heading] = []
    for pos, section in found:  # one heading per line start; a titled match beats a boundary
        if deduped and deduped[-1][0] == pos:
            continue
        deduped.append((pos, section))
    return deduped


def _choose(headings: list[Heading], wanted: Iterable[str], text_len: int) -> dict[str, tuple[int, int]]:
    """For each wanted section, the occurrence followed by the most text (skips tables
    of contents and the short Part II items of a 10-Q); anything under
    MIN_SECTION_CHARS, such as a cross-reference stub, does not count."""
    chosen: dict[str, tuple[int, int]] = {}
    for section in wanted:
        best: tuple[int, int] | None = None
        for idx, (pos, item) in enumerate(headings):
            if item != section:
                continue
            end = text_len
            for pos2, item2 in headings[idx + 1:]:
                if item2 != section:  # the next heading of anything else closes this one
                    end = pos2
                    break
            if end - pos >= MIN_SECTION_CHARS and (best is None or end - pos > best[1] - best[0]):
                best = (pos, end)
        if best:
            chosen[section] = best
    return chosen


def _rescue_statements(text: str, chosen: dict[str, tuple[int, int]], headings: list[Heading], key: str) -> None:
    """Find the financial statements when the statements section is missing or only a
    pointer. 10-K: item_8 (companion item_7); 10-Q: item_1 (companion item_2)."""
    target, companion = ("item_8", "item_7") if key == "10-K" else ("item_1", "item_2")
    current = chosen.get(target)
    if current and current[1] - current[0] >= POINTER_RESCUE_MIN_CHARS:
        return

    def closing(pos: int) -> int:
        for p, item in headings:
            if p > pos and item != target:
                return p
        return len(text)

    # (a) after the last heading: statements printed after Part IV (Disney, Chevron, Oracle)
    anchors = [max((p for p, _ in headings), default=0)]
    for anchor in anchors:
        m = _STATEMENTS_HEADING.search(text, anchor)
        if m and closing(m.start()) - m.start() >= POINTER_RESCUE_MIN_CHARS:
            chosen[target] = (m.start(), closing(m.start()))
            return
    # (b) inside the MD&A section (PepsiCo prints MD&A and statements under Item 7)
    if companion in chosen:
        start, end = chosen[companion]
        m = _STATEMENTS_HEADING.search(text, start, end)
        if m and m.start() - start >= MIN_SECTION_CHARS and end - m.start() >= POINTER_RESCUE_MIN_CHARS:
            chosen[companion] = (start, m.start())
            chosen[target] = (m.start(), end)
            return
    # (e) before the MD&A: the usual 10-Q order when Item 1 is never labelled in the
    # body (Netflix, Linde, Abbott) — the statements run from their first heading to the MD&A
    if key == "10-Q" and companion in chosen:
        start = chosen[companion][0]
        taken = [span for sid, span in chosen.items() if sid != companion]
        m = _STATEMENTS_HEADING.search(text, 0, start)
        while m and any(b <= m.start() < e for b, e in taken):
            m = _STATEMENTS_HEADING.search(text, m.end(), start)
        if m and start - m.start() >= POINTER_RESCUE_MIN_CHARS:
            chosen[target] = (m.start(), start)
            return
    # (c) after the MD&A (Morgan Stanley 10-Qs), then (d) after the pointer itself
    anchors = ([chosen[companion][1]] if companion in chosen else []) + [p for p, item in headings if item == target][-1:]
    for anchor in anchors:
        m = _STATEMENTS_HEADING.search(text, anchor)
        if m and closing(m.start()) - m.start() >= POINTER_RESCUE_MIN_CHARS:
            chosen[target] = (m.start(), closing(m.start()))
            return


def _attempt(text: str, key: str, mode: str) -> tuple[dict[str, tuple[int, int]], list[str], float]:
    headings = _item_headings(text) if mode == "item" else _title_headings(text, key)
    chosen = _choose(headings, SECTION_TITLES[key], len(text))
    _rescue_statements(text, chosen, headings, key)
    missing = [s for s in REQUIRED_SECTIONS[key] if s not in chosen]
    coverage = sum(end - start for start, end in chosen.values()) / max(len(text), 1)
    return chosen, missing, coverage


def split_sections(text: str, form: str) -> SectionSplit:
    """Item-labelled headings first, title-only headings second; whichever first finds
    every required section with enough coverage wins. Otherwise the whole text is
    kept as section 'full' and the fallback is counted."""
    key = form_key(form)
    attempts = []
    for mode in ("item", "title"):
        chosen, missing, coverage = _attempt(text, key, mode)
        attempts.append((mode, chosen, missing, coverage))
        if not missing and coverage >= MIN_COVERAGE[key]:
            split = SectionSplit(form=form, mode=mode, coverage=round(coverage, 4))
            split.found = [s for s in SECTION_TITLES[key] if s in chosen]
            for section, (start, end) in sorted(chosen.items(), key=lambda kv: kv[1][0]):
                split.sections[section] = text[start:end].strip() + "\n"
            return split

    # Report the gaps of the closest attempt (fewest missing sections, then coverage).
    _, _, missing, coverage = max(attempts, key=lambda a: (-len(a[2]), a[3]))
    return SectionSplit(
        form=form, mode="full", sections={FULL_SECTION: text}, missing_required=missing,
        coverage=round(coverage, 4), fallback=True,
    )


def html_to_sections(html: str, form: str) -> tuple[str, SectionSplit]:
    text = html_to_text(html)
    return text, split_sections(text, form)
