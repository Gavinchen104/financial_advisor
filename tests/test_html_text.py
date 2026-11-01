"""iXBRL → text normalizer and the 10-K / 10-Q section splitter (P2-C)."""

import re
from pathlib import Path

import pytest

from src.rag.html_text import (
    clean_text,
    html_to_sections,
    html_to_text,
    merge_cells,
    normalize_text,
    section_title,
    split_sections,
)

FIXTURES = Path(__file__).parent / "fixtures" / "edgar"


@pytest.fixture(scope="module")
def k_text() -> str:
    return html_to_text((FIXTURES / "mini_10k.html").read_text())


@pytest.fixture(scope="module")
def q_text() -> str:
    return html_to_text((FIXTURES / "mini_10q.html").read_text())


# ---------- normalizer ----------
def test_hidden_xbrl_machinery_leaves_no_residue(k_text):
    for residue in ("ix:", "us-gaap:", "iso4217", "xbrli", "dei:", "SECRET HIDDEN", "0000123456", "Scripted", "display"):
        assert residue not in k_text, residue


def test_tables_become_rows_with_merged_cells(k_text):
    assert "Widgets | $201,183 | (2)% | $205,489" in k_text  # lone $ merged, "(" "2" ")%" merged, spacer cells dropped
    assert "Services | $96,169 | 13% | $85,200" in k_text  # lone % merged
    assert "Net loss on hedges | $(1,234) | $(987)" in k_text  # split parentheses merged
    assert "2025 | Change | 2024" in k_text  # header row (years) kept
    assert "Diluted earnings per share | $6.08 | $6.13 | $6.11" in k_text


def test_unicode_whitespace_and_punctuation_normalized(k_text):
    assert "Management's Discussion" in k_text  # curly apostrophe → '
    assert "52- or 53-week" in k_text
    assert "\xa0" not in k_text and "’" not in k_text and "—" not in k_text
    assert "September 27, 2025" in k_text  # &#160; → space, single spacing


def test_inline_spans_do_not_break_sentences(k_text):
    assert "designs, manufactures and markets widgets and related services." in k_text


def test_headings_start_their_own_line(k_text):
    assert re.search(r"^Item 1A\. Risk Factors$", k_text, re.M)
    assert re.search(r"^Item 7\. Management's Discussion", k_text, re.M)


def test_table_of_contents_rows_are_kept_as_rows(k_text):
    assert "Item 1A. | Risk Factors | 6" in k_text


def test_clean_text_collapses_whitespace_and_blank_runs():
    assert clean_text("\n\n a \t b  \n\n\n\nc d\n\n") == "a b\n\nc d\n"
    assert clean_text("") == ""


def test_normalize_text_dashes_quotes_zero_width():
    assert normalize_text("“Risk” – 2024—now​") == '"Risk" - 2024-now'


@pytest.mark.parametrize(
    "cells, expected",
    [
        (["", "$", "1,234", "", "(5", ")", "12", "%", "$"], ["$1,234", "(5)", "12%"]),
        (["Revenue", "$", "$", "9"], ["Revenue", "$9"]),  # doubled currency cells
        ([")", "%"], []),  # nothing to attach to
        (["(1,234", ")%", "—"], ["(1,234)%", "—"]),
        (["$", "(987", ")"], ["$(987)"]),
    ],
)
def test_merge_cells(cells, expected):
    assert merge_cells(cells) == expected


def test_html_to_text_handles_xml_declaration_and_bare_fragments():
    assert html_to_text('<?xml version="1.0" encoding="utf-8"?><html><body><p>Hello</p></body></html>') == "Hello\n"
    assert html_to_text("<div>A<br/>B</div>") == "A\nB\n"
    assert html_to_text("") == ""


# ---------- section splitter ----------
def test_split_10k_sections_skip_the_table_of_contents(k_text):
    split = split_sections(k_text, "10-K")
    assert not split.fallback
    assert split.found == ["item_1", "item_1a", "item_7", "item_7a", "item_8"]
    assert list(split.sections) == split.found  # document order

    item_1 = split.sections["item_1"]
    assert item_1.startswith("Item 1. Business")
    assert "Company Background" in item_1 and "Globex Corporation" in item_1
    assert "see Item 1A. Risk Factors below" in item_1  # cross-reference mid-paragraph stays put
    assert "single supplier" not in item_1  # that is Item 1A
    assert "| Business | 3" not in item_1  # not the TOC row

    item_1a = split.sections["item_1a"]
    assert item_1a.startswith("Item 1A. Risk Factors")
    assert "single supplier, Foundry Co., Ltd." in item_1a
    assert "Cupertino-on-Thames" not in item_1a  # Item 2 (Properties) is excluded via the Item 1B boundary

    item_7 = split.sections["item_7"]
    assert "Widgets | $201,183 | (2)% | $205,489" in item_7
    assert "interest rate swap sensitivity" not in item_7  # Item 7A

    assert "interest rate swap sensitivity" in split.sections["item_7a"]
    item_8 = split.sections["item_8"]
    assert "CONSOLIDATED STATEMENTS OF OPERATIONS" in item_8
    assert "Net income | $93,736 | $96,995 | $99,803" in item_8
    assert "disclosure controls were effective" not in item_8  # Item 9A


def test_split_10q_prefers_part_i_over_part_ii(q_text):
    split = split_sections(q_text, "10-Q")
    assert not split.fallback
    assert split.found == ["item_1", "item_2"]
    item_1 = split.sections["item_1"]
    assert "CONDENSED CONSOLIDATED STATEMENTS OF OPERATIONS" in item_1
    assert "Net sales | $94,036 | $85,777" in item_1
    assert "putative class action" not in item_1  # Part II, Item 1 (Legal Proceedings)
    item_2 = split.sections["item_2"]
    assert "Gross margin percentage was 46.5%" in item_2
    assert "repurchased 95 million shares" not in item_2  # Part II, Item 2
    assert "no material changes to the Company's market risk" not in item_2  # Item 3


def test_split_tricky_toc_uppercase_headings_and_continued_marker():
    text, split = html_to_sections((FIXTURES / "tricky_toc.html").read_text(), "10-K")
    assert not split.fallback
    assert split.found == ["item_1", "item_1a", "item_7", "item_8"]  # 7A absent and optional
    assert "item_7a" not in split.sections
    item_1a = split.sections["item_1a"]
    assert "cyclical and sensitive to commodity prices" in item_1a
    assert "Vandelay Industries, could delay" in item_1a  # the "(continued)" line did not cut the section
    assert "None." not in item_1a  # Item 1B
    assert split.sections["item_7"].startswith("ITEM 7 - MANAGEMENT'S DISCUSSION")
    assert "$14,200 million" in split.sections["item_8"]
    assert "Free cash flow" not in split.sections["item_8"]


def test_fallback_when_no_headings_at_all():
    text = "Just prose without any item headings.\n" * 40
    split = split_sections(text, "10-K")
    assert split.fallback
    assert split.sections == {"full": text}
    assert split.missing_required == ["item_1", "item_1a", "item_7", "item_8"]
    assert split.summary().startswith("fallback=full")


def test_fallback_when_a_required_section_is_missing(k_text):
    without_item_8 = k_text.replace("Item 8. Financial Statements and Supplementary Data\n", "Financials\n", 1)
    # the TOC row still mentions Item 8, but it is too short to count as a section
    split = split_sections(without_item_8, "10-K")
    assert split.fallback and split.missing_required == ["item_8"]
    assert list(split.sections) == ["full"]


def _paras(topic: str, n: int) -> str:
    return "<p>" + " ".join(
        f"{topic} sentence {i} describes the operations in enough detail to count as a real section paragraph." for i in range(n)
    ) + "</p>"


TITLE_ONLY_10K = f"""<html><body>
<p>FORM 10-K</p>
<p>BUSINESS</p>{_paras("Business", 8)}
<p>RISK FACTORS</p>{_paras("Risk", 8)}
<p>PROPERTIES</p>{_paras("Property", 1)}
<p>MANAGEMENT'S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS</p>{_paras("MD&A", 6)}
<table><tr><td>Business</td><td>1,250</td><td>1,310</td></tr><tr><td>Total</td><td>2,500</td><td>2,600</td></tr></table>
<p>QUANTITATIVE AND QUALITATIVE DISCLOSURES ABOUT MARKET RISK</p>{_paras("Market risk", 7)}
<p>FINANCIAL STATEMENTS AND SUPPLEMENTARY DATA</p>{_paras("Statements", 8)}
<p>CONTROLS AND PROCEDURES</p>{_paras("Controls", 1)}
<table><tr><td>Item 1</td><td>Business</td><td>Page 3</td></tr><tr><td>Item 1A</td><td>Risk Factors</td><td>Page 9</td></tr>
<tr><td>Item 7</td><td>Management's Discussion and Analysis</td><td>Page 20</td></tr><tr><td>Item 8</td><td>Financial Statements and Supplementary Data</td><td>Page 40</td></tr></table>
</body></html>"""

POINTER_ITEM_8_10K = f"""<html><body>
<p>Item 1. Business</p>{_paras("Business", 8)}
<p>Item 1A. Risk Factors</p>{_paras("Risk", 8)}
<p>Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations</p>{_paras("MD&A", 6)}
<p>Item 8. Financial Statements and Supplementary Data</p>
<p>See Index to Financial Statements and Supplemental Data on page 58.</p>
<p>Item 9. Changes in and Disagreements with Accountants on Accounting and Financial Disclosure</p><p>None.</p>
<p>Item 15. Exhibits and Financial Statement Schedules</p>{_paras("Exhibit list", 2)}
<p>SIGNATURES</p><p>Signed by the officers.</p>
<p>Report of Independent Registered Public Accounting Firm</p>{_paras("Auditor", 3)}
<p>CONSOLIDATED STATEMENTS OF INCOME</p>
<table><tr><td>Revenues</td><td>$</td><td>91,361</td><td>$</td><td>88,898</td></tr><tr><td>Net income</td><td>$</td><td>12,401</td><td>$</td><td>4,972</td></tr></table>
{_paras("Notes to the consolidated financial statements", 220)}
</body></html>"""

STUB_INDEX_10Q = f"""<html><body>
<p>FORM 10-Q</p>
<p>Form 10-Q Cross-Reference Index</p>
<p>Part I. Item 1. Financial Statements | 45</p>
<p>Part I. Item 2. Management's Discussion and Analysis of Financial Condition and Results of Operations | 3</p>
<p>Part II. Item 1. Legal Proceedings | 80</p>
<p>Management's Discussion and Analysis</p>{_paras("MD&A", 12)}
<p>Consolidated Financial Statements (Unaudited)</p>
<table><tr><td>Net interest income</td><td>$</td><td>11,950</td><td>$</td><td>11,790</td></tr></table>{_paras("Notes", 12)}
<p>Legal Proceedings</p>{_paras("Legal", 1)}
</body></html>"""


def test_title_only_headings_are_used_when_items_live_in_an_index():
    text, split = html_to_sections(TITLE_ONLY_10K, "10-K")
    assert split.mode == "title" and not split.fallback
    assert split.found == ["item_1", "item_1a", "item_7", "item_7a", "item_8"]
    assert split.coverage > 0.5
    assert "Business sentence 0" in split.sections["item_1"] and "MD&A sentence" not in split.sections["item_1"]
    assert "Property sentence" not in split.sections["item_1a"]
    assert "Business | 1,250 | 1,310" in split.sections["item_7"]  # a table row never starts a section
    assert "Controls sentence" not in split.sections["item_8"]
    assert split.summary().startswith("title: item_1")


def test_pointer_item_8_is_rescued_from_statements_after_part_iv():
    text, split = html_to_sections(POINTER_ITEM_8_10K, "10-K")
    assert split.mode == "item" and not split.fallback
    assert "item_8" in split.found
    item_8 = split.sections["item_8"]
    assert item_8.startswith("Report of Independent Registered Public Accounting Firm")
    assert "Revenues | $91,361 | $88,898" in item_8 and "Notes to the consolidated financial statements sentence 219" in item_8
    assert "Revenues |" not in split.sections["item_7"] and "Exhibit list" not in item_8


def test_cross_reference_stubs_fail_coverage_and_titles_take_over():
    text, split = html_to_sections(STUB_INDEX_10Q, "10-Q")
    assert split.mode == "title" and split.found == ["item_1", "item_2"]
    assert "Net interest income | $11,950 | $11,790" in split.sections["item_1"]
    assert "MD&A sentence 11" in split.sections["item_2"] and "Net interest income" not in split.sections["item_2"]
    assert "Legal sentence" not in split.sections["item_1"]


def test_low_coverage_split_falls_back_to_full():
    text = (
        "Item 1. Financial Statements\n" + ("statement line\n" * 60)
        + "Item 2. Management's Discussion and Analysis\n" + ("discussion line\n" * 60)
        + "Item 3. Quantitative and Qualitative Disclosures About Market Risk\n" + ("other line\n" * 3000)
    )
    split = split_sections(text, "10-Q")
    assert split.fallback and split.mode == "full" and split.missing_required == []
    assert split.coverage < 0.15
    assert split.summary().startswith("fallback=full (coverage ")


GE_STYLE_10Q = f"""<html><body>
<p>FORM 10-Q</p>
<table><tr><td>Management's Discussion and Analysis of Financial Condition and Results of Operations (MD&amp;A)</td><td>4</td></tr>
<tr><td>Financial Statements and Notes</td><td>14</td></tr><tr><td>Other Information</td><td>33</td></tr></table>
<table><tr><td>Management's Discussion and Analysis of Financial Condition and Results of Operations (MD&amp;A)</td><td>4</td></tr></table>
{_paras("MD&A", 10)}
<table><tr><td>Financial Statements and Notes</td><td>14</td></tr></table>
<table><tr><td>Total revenues</td><td>$</td><td>9,838</td><td>$</td><td>8,220</td></tr></table>{_paras("Notes", 10)}
<table><tr><td>Other Information</td><td>33</td></tr></table>{_paras("Other", 2)}
</body></html>"""

MS_STYLE_10Q = f"""<html><body>
<p>FORM 10-Q</p>
<p>Management's Discussion and Analysis of Financial Condition and Results of Operations</p>{_paras("MD&A", 10)}
<p>Quantitative and Qualitative Disclosures about Risk</p>{_paras("Risk management", 3)}
<p>Consolidated Income Statement (Unaudited)</p>
<table><tr><td>Net revenues</td><td>$</td><td>16,393</td><td>$</td><td>15,140</td></tr></table>
<p>Consolidated Balance Sheet</p>
<table><tr><td>Total assets</td><td>$</td><td>1,258,874</td></tr></table>{_paras("Notes to Consolidated Financial Statements (Unaudited)", 200)}
<p>Legal Proceedings</p>{_paras("Legal", 2)}
<p>Risk Factors</p>{_paras("Part II risk", 2)}
</body></html>"""

PEP_STYLE_10K = f"""<html><body>
<p>Item 1. Business.</p>{_paras("Business", 8)}
<p>Item 1A. Risk Factors.</p>{_paras("Risk", 8)}
<p>Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations.</p>{_paras("MD&A", 12)}
<p>CONSOLIDATED STATEMENT OF INCOME | 57</p>
{_paras("More MD&A", 6)}
<p>Consolidated Statement of Income</p>
<table><tr><td>Net Revenue</td><td>$</td><td>91,854</td><td>$</td><td>91,471</td></tr></table>{_paras("Notes to Consolidated Financial Statements", 200)}
<p>Item 7A. Quantitative and Qualitative Disclosures About Market Risk.</p><p>Included in Item 7.</p>
<p>Item 8. Financial Statements and Supplementary Data.</p><p>See Item 7. Our Financial Statements are presented in Item 7.</p>
<p>Item 9. Changes in and Disagreements with Accountants on Accounting and Financial Disclosure.</p><p>None.</p>
<p>Item 15. Exhibits and Financial Statement Schedules.</p>{_paras("Exhibits", 3)}
<p>Report of Independent Registered Public Accounting Firm (PCAOB ID: 185).</p>{_paras("Auditor opinion on internal control", 2)}
</body></html>"""


def test_page_cell_headings_are_recognised_in_title_mode():
    text, split = html_to_sections(GE_STYLE_10Q, "10-Q")
    assert split.mode == "title" and split.found == ["item_1", "item_2"]
    assert "Total revenues | $9,838 | $8,220" in split.sections["item_1"]
    assert "MD&A sentence 9" in split.sections["item_2"] and "Notes sentence" not in split.sections["item_2"]
    assert "Other sentence" not in split.sections["item_1"]


def test_statements_after_the_mdna_are_rescued_in_a_10q():
    text, split = html_to_sections(MS_STYLE_10Q, "10-Q")
    assert split.mode == "title" and split.found == ["item_1", "item_2"]
    item_1 = split.sections["item_1"]
    assert item_1.startswith("Consolidated Income Statement (Unaudited)")
    assert "Net revenues | $16,393 | $15,140" in item_1 and "Notes to Consolidated Financial Statements (Unaudited) sentence 199" in item_1
    assert "Legal sentence" not in item_1 and "Part II risk" not in item_1
    assert "Risk management sentence" not in split.sections["item_2"]


def test_statements_inside_the_mdna_span_split_item_7_and_item_8():
    text, split = html_to_sections(PEP_STYLE_10K, "10-K")
    assert split.mode == "item" and "item_8" in split.found
    item_7, item_8 = split.sections["item_7"], split.sections["item_8"]
    assert "MD&A sentence 11" in item_7 and "More MD&A sentence 5" in item_7  # the index row with a page cell is not a heading
    assert item_8.startswith("Consolidated Statement of Income")
    assert "Net Revenue | $91,854 | $91,471" in item_8 and "Notes to Consolidated Financial Statements sentence 199" in item_8
    assert "Included in Item 7." not in item_8 and "Auditor opinion" not in item_8


NFLX_STYLE_10Q = f"""<html><body>
<p>FORM 10-Q</p>
<table><tr><td>Item 1.</td><td>Consolidated Financial Statements</td><td>3</td></tr>
<tr><td></td><td>Consolidated Statements of Operations</td><td>3</td></tr>
<tr><td>Item 2.</td><td>Management's Discussion and Analysis of Financial Condition and Results of Operations</td><td>26</td></tr>
<tr><td>Item 1.</td><td>Legal Proceedings</td><td>38</td></tr></table>
<p>PART I. FINANCIAL INFORMATION</p>
<p>Consolidated Statements of Operations</p>
<p>(unaudited) (in thousands, except per share data)</p>
<table><tr><td>Revenues</td><td>$</td><td>11,510,045</td><td>$</td><td>9,824,703</td></tr></table>{_paras("Notes", 220)}
<p>Item 2.Management's Discussion and Analysis of Financial Condition and Results of Operations</p>{_paras("MD&A", 12)}
<p>Item 3.Quantitative and Qualitative Disclosures About Market Risk</p>{_paras("Market risk", 2)}
<p>PART II. OTHER INFORMATION</p>
<p>Item 1.Legal Proceedings</p>{_paras("Legal", 2)}
<p>Item 6.Exhibits</p><p>Exhibit 31.1</p>
</body></html>"""


def test_unlabelled_statements_before_the_mdna_are_rescued_in_a_10q():
    text, split = html_to_sections(NFLX_STYLE_10Q, "10-Q")
    assert split.mode == "item", split.summary()
    assert split.found == ["item_1", "item_2"]
    item_1 = split.sections["item_1"]
    assert item_1.startswith("Consolidated Statements of Operations")
    assert "Revenues | $11,510,045 | $9,824,703" in item_1 and "Notes sentence 219" in item_1
    assert "| 3" not in item_1  # the TOC rows are not part of the section
    assert "MD&A sentence" not in item_1 and "MD&A sentence 11" in split.sections["item_2"]
    assert "Legal sentence" not in split.sections["item_2"]


def test_wrapper_stubs_do_not_count_as_required_sections():
    stub = "<p>Information in response to this Item can be found in the 2025 Annual Report under the same heading, which is incorporated by reference.</p>"
    wrapper = f"""<html><body>
<p>Item 1. Business</p>{_paras("Business", 8)}
<p>Item 1A. Risk Factors</p>{stub}
<p>Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations</p>{stub}
<p>Item 7A. Quantitative and Qualitative Disclosures About Market Risk</p>{stub}
<p>Item 8. Financial Statements and Supplementary Data</p>{stub}
<p>Item 9. Changes in and Disagreements with Accountants</p><p>None.</p>
<p>Risk Factors</p>{_paras("Annual report risk", 10)}
<p>Financial Review</p>{_paras("Annual report MD&A", 10)}
<p>Financial Statements</p>{_paras("Annual report statements", 10)}
<p>Signatures</p><p>Signed.</p>
</body></html>"""
    text, split = html_to_sections(wrapper, "10-K")
    assert split.mode == "title", split.summary()
    assert split.found == ["item_1", "item_1a", "item_7", "item_8"]
    assert "Annual report risk sentence 9" in split.sections["item_1a"]
    assert "Annual report MD&A sentence 9" in split.sections["item_7"]  # "Financial Review" is an MD&A alias
    assert "Annual report statements sentence 9" in split.sections["item_8"]
    assert "incorporated by reference" not in split.sections["item_7"]


def test_section_titles():
    assert section_title("10-K", "item_7a").startswith("Item 7A.")
    assert section_title("10-Q", "item_2").startswith("Part I, Item 2.")
    assert section_title("10-K", "full") == "Full filing"
    assert section_title("10-K", "item_99") == "item_99"
