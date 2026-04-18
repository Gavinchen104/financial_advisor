"""
Deterministic checks against a generated brief. Each check returns a list of
issue strings (empty list = pass). These are free to run — no model calls, no
subjective scoring. Use them to catch regressions on every prompt change.
"""

import re

from .cases import EvalCase

# Word-boundary regex for the forbidden-words rule. Compiled once.
# Includes the core list from system.md + the FOMO/hype list.
_FORBIDDEN_WORDS = [
    r"\bbuy\b", r"\bsell\b", r"\bhold\b", r"\bholds\b",
    r"\bstrong buy\b", r"\bprice target\b",
    r"\bshould\b", r"\brecommend\b", r"\brecommends\b",
    r"\bmust\b", r"\bneed to\b", r"\bneeds to\b",
    r"\bdon't miss\b", r"\bdo not miss\b", r"\bact now\b",
    r"\bsurging\b", r"\bskyrocket\w*\b", r"\bmoon\w*\b",
]
_FORBIDDEN_RE = re.compile("|".join(_FORBIDDEN_WORDS), re.IGNORECASE)

_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"  # pictographs & emoji
    "\U00002600-\U000027BF"  # misc symbols
    "\U0001F000-\U0001F1FF"
    "]+",
    flags=re.UNICODE,
)

_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\)]+)\)")
_CITATION_RE = re.compile(r"\[(\d+)\]")


def check_sections_present(brief: dict) -> list[str]:
    issues = []
    for field in ("what_happened", "why_moved", "what_it_means"):
        if not brief.get(field) or not brief[field].strip():
            issues.append(f"missing or empty section: {field}")
    return issues


def check_no_forbidden_words(brief: dict) -> list[str]:
    full = brief.get("full_brief", "")
    # Strip the disclaimer block (it legitimately contains "recommend" and "buying or selling")
    body = full.split("---")[0] if "---" in full else full
    matches = _FORBIDDEN_RE.findall(body)
    if matches:
        uniq = sorted(set(m.lower() for m in matches))
        return [f"forbidden word(s): {', '.join(uniq)}"]
    return []


def check_no_emojis_or_exclamations(brief: dict) -> list[str]:
    issues = []
    body = brief.get("full_brief", "").split("---")[0]
    if _EMOJI_RE.search(body):
        issues.append("brief contains emoji")
    # Allow exclamations only inside URLs/quoted-title sources
    body_without_links = _MD_LINK_RE.sub("", body)
    if "!" in body_without_links:
        issues.append("brief contains '!' outside of source links")
    return issues


def check_sources_are_markdown_links(brief: dict) -> list[str]:
    sources = brief.get("sources_text", "")
    if not sources.strip():
        return ["sources section is empty"]
    # Every non-blank line that looks like a source entry must contain a markdown link
    issues = []
    for line in sources.splitlines():
        line = line.strip().lstrip("-").lstrip("*").strip()
        if not line:
            continue
        if not _MD_LINK_RE.search(line):
            issues.append(f"source not in [Title](URL) form: {line[:80]}")
    return issues


def check_citations_resolve(brief: dict) -> list[str]:
    """If the body uses [1], [2]-style citations, each number must exist in sources."""
    body = (
        brief.get("what_happened", "") + "\n" +
        brief.get("why_moved", "") + "\n" +
        brief.get("what_it_means", "")
    )
    sources = brief.get("sources_text", "")
    cited = set(_CITATION_RE.findall(body))
    if not cited:
        return []  # citations are optional if sources are inline-linked
    source_nums = set(_CITATION_RE.findall(sources))
    unresolved = cited - source_nums
    if unresolved:
        return [f"citations [{','.join(sorted(unresolved))}] have no matching source entry"]
    return []


def check_disclaimer_present(brief: dict) -> list[str]:
    disc = brief.get("disclaimer", "").lower()
    if "educational information" not in disc or "not investment advice" not in disc:
        return ["disclaimer missing or malformed"]
    return []


def check_section_lengths(brief: dict) -> list[str]:
    """Per system prompt: what_happened 1-2 sentences, why_moved 2-3, what_it_means 1-2.
    We count sentences loosely (split on ./?/!) and allow +1 tolerance."""
    issues = []
    for field, (lo, hi) in [
        ("what_happened", (1, 3)),
        ("why_moved", (1, 4)),
        ("what_it_means", (1, 3)),
    ]:
        text = brief.get(field, "").strip()
        if not text:
            continue
        # Rough sentence count — split on terminators, drop empties
        sentences = [s for s in re.split(r"[.!?]+\s+", text) if s.strip()]
        n = len(sentences)
        if n < lo or n > hi:
            issues.append(f"{field}: ~{n} sentences (expected {lo}-{hi})")
    return issues


def check_expectations(brief: dict, case: EvalCase) -> list[str]:
    """Case-specific deterministic assertions (must_mention_any, must_not_mention)."""
    issues = []
    body = brief.get("full_brief", "").lower()

    if case.must_mention_any:
        if not any(term.lower() in body for term in case.must_mention_any):
            issues.append(
                f"expected at least one of: {case.must_mention_any} — none found"
            )

    if case.must_not_mention:
        hit = [term for term in case.must_not_mention if term.lower() in body]
        if hit:
            issues.append(f"unexpected mention of: {hit}")

    return issues


def check_invalid_handling(brief: dict, case: EvalCase) -> list[str]:
    """For cases marked expect_invalid, the brief must acknowledge missing data
    rather than fabricate (e.g., invent a price move)."""
    if not case.expect_invalid:
        return []
    wh = brief.get("what_happened", "").lower()
    graceful = any(
        kw in wh for kw in
        ["invalid", "not found", "unavailable", "unable", "no price", "could not", "no data", "delisted"]
    )
    if not graceful:
        return ["invalid ticker: brief did not acknowledge missing/invalid data in 'what happened'"]
    return []


ALL_CHECKS = [
    check_sections_present,
    check_no_forbidden_words,
    check_no_emojis_or_exclamations,
    check_sources_are_markdown_links,
    check_citations_resolve,
    check_disclaimer_present,
    check_section_lengths,
]


def run_all_checks(brief: dict, case: EvalCase) -> list[tuple[str, list[str]]]:
    """Run every check against a brief. Returns [(check_name, [issues]), ...]."""
    # Invalid-ticker briefs skip most format checks (they may have empty sources etc.)
    if case.expect_invalid:
        return [
            ("check_invalid_handling", check_invalid_handling(brief, case)),
            ("check_disclaimer_present", check_disclaimer_present(brief)),
        ]

    results = [(c.__name__, c(brief)) for c in ALL_CHECKS]
    results.append(("check_expectations", check_expectations(brief, case)))
    return results
