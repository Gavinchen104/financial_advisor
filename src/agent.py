import json
import os
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from .tools.news import get_recent_news
from .tools.filings import get_latest_filing
from .tools.price import get_price_action
from .tools.brief_writer import parse_brief

load_dotenv()

_PROMPTS_DIR = Path(__file__).parent / "prompts"
SYSTEM_PROMPT = (_PROMPTS_DIR / "system.md").read_text()

TOOL_DEFS = [
    {
        "name": "get_recent_news",
        "description": "Fetch recent news headlines and URLs for a stock ticker from the past N days.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol, e.g. NVDA"},
                "days": {"type": "integer", "description": "Days of news to fetch", "default": 7},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_latest_filing",
        "description": "Fetch the most recent SEC filing (10-K, 10-Q, or 8-K) for a stock ticker.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_price_action",
        "description": "Fetch recent price action for a stock ticker: % change, volume, weekly high/low.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol"},
                "days": {"type": "integer", "description": "Number of trading days to look back", "default": 7},
            },
            "required": ["ticker"],
        },
    },
]

_TOOL_FNS = {
    "get_recent_news": get_recent_news,
    "get_latest_filing": get_latest_filing,
    "get_price_action": get_price_action,
}


def run_agent(ticker: str, experience_level: str = "first_year") -> dict:
    """Run the Financial Advisor agent for a ticker and return a structured brief."""
    client = anthropic.Anthropic()
    ticker = ticker.strip().upper()

    messages: list[dict] = [
        {
            "role": "user",
            "content": f"Generate a Financial Advisor brief for {ticker}. Experience level: {experience_level}.",
        }
    ]

    for _ in range(10):
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            # Cache the system prompt — it's large and constant across requests
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            tools=TOOL_DEFS,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            text = next(
                (b.text for b in response.content if hasattr(b, "text")),
                "",
            )
            return parse_brief(text, ticker)

        if response.stop_reason != "tool_use":
            break

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            fn = _TOOL_FNS.get(block.name)
            if fn is None:
                result = {"error": f"Unknown tool: {block.name}"}
            else:
                try:
                    result = fn(**block.input)
                except Exception as e:
                    result = {"error": str(e)}
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(result)}
            )

        messages.append({"role": "user", "content": tool_results})

    return parse_brief("## What happened\nThe agent did not produce a complete brief.\n\n## Why the price moved\nUnable to determine.\n\n## What it means for a first-year investor\nNo information available.\n\n## Sources\nN/A", ticker)
