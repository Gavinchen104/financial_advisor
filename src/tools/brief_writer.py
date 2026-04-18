DISCLAIMER = (
    "This is educational information, not investment advice. Financial Advisor does not "
    "recommend buying or selling any security. Do your own research and consider "
    "consulting a licensed financial advisor."
)

SECTION_HEADERS = {
    "what happened": "what_happened",
    "why the price moved": "why_moved",
    "what it means for a first-year investor": "what_it_means",
    "what it means": "what_it_means",
    "sources": "sources_text",
}


def parse_brief(text: str, ticker: str) -> dict:
    """Parse the 3-layer brief from agent markdown output into structured fields."""
    sections: dict[str, list[str]] = {}
    current: str | None = None

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            heading = stripped[3:].lower().strip()
            matched = next((v for k, v in SECTION_HEADERS.items() if heading.startswith(k)), None)
            if matched:
                current = matched
                sections.setdefault(current, [])
                continue

        if current is not None:
            sections[current].append(line)

    def join(key: str) -> str:
        return "\n".join(sections.get(key, [])).strip()

    full_brief = text.strip() + "\n\n---\n*" + DISCLAIMER + "*"

    return {
        "ticker": ticker.upper(),
        "what_happened": join("what_happened"),
        "why_moved": join("why_moved"),
        "what_it_means": join("what_it_means"),
        "sources_text": join("sources_text"),
        "full_brief": full_brief,
        "disclaimer": DISCLAIMER,
    }
