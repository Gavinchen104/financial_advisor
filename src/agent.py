import json
import os
from pathlib import Path
from typing import Literal

from google import genai
from google.genai import types
from dotenv import load_dotenv

from .tools.news import get_recent_news
from .tools.filings import get_latest_filing
from .tools.price import get_price_action, get_earnings_data
from .tools.brief_writer import parse_brief

load_dotenv()

_PROMPTS_DIR = Path(__file__).parent / "prompts"
SYSTEM_PROMPT = (_PROMPTS_DIR / "system.md").read_text()

_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def run_agent(
    ticker: str,
    experience_level: str = "first_year",
    mode: Literal["baseline", "enhanced"] = "enhanced",
) -> dict:
    ticker = ticker.strip().upper()

    # Both modes use the same core data sources
    news = get_recent_news(ticker, fetch_content=(mode == "enhanced"))
    filing = get_latest_filing(ticker)
    price = get_price_action(ticker)

    if mode == "enhanced":
        earnings = get_earnings_data(ticker)
        earnings_section = f"\n## Earnings & Fundamentals\n{json.dumps(earnings, indent=2)}\n"
        search_note = "\nUse the Google Search tool if you need to verify or expand on any of the above."
        gemini_tools = [types.Tool(google_search=types.GoogleSearch())]
    else:
        earnings_section = ""
        search_note = ""
        gemini_tools = []

    user_message = f"""Generate a Financial Advisor brief for {ticker}. Experience level: {experience_level}.

Here is all the data you need:

## Recent News
{json.dumps(news, indent=2)}

## Latest SEC Filing
{json.dumps(filing, indent=2)}

## Price Action (last 7 days)
{json.dumps(price, indent=2)}
{earnings_section}{search_note}
Now write the brief using the required format."""

    response = _client.models.generate_content(
        model="gemini-2.5-flash",
        contents=user_message,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=gemini_tools if gemini_tools else None,
        ),
    )

    result = parse_brief(response.text, ticker)
    result["mode"] = mode
    return result
