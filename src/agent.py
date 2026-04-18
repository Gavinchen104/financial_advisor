import json
import os
from pathlib import Path

from google import genai
from google.genai import types
from dotenv import load_dotenv

from .tools.news import get_recent_news
from .tools.filings import get_latest_filing
from .tools.price import get_price_action
from .tools.brief_writer import parse_brief

load_dotenv()

_PROMPTS_DIR = Path(__file__).parent / "prompts"
SYSTEM_PROMPT = (_PROMPTS_DIR / "system.md").read_text()

_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def run_agent(ticker: str, experience_level: str = "first_year") -> dict:
    ticker = ticker.strip().upper()

    # Gather all data upfront
    news = get_recent_news(ticker)
    filing = get_latest_filing(ticker)
    price = get_price_action(ticker)

    user_message = f"""Generate a Financial Advisor brief for {ticker}. Experience level: {experience_level}.

Here is all the data you need:

## Recent News
{json.dumps(news, indent=2)}

## Latest SEC Filing
{json.dumps(filing, indent=2)}

## Price Action (last 7 days)
{json.dumps(price, indent=2)}

Now write the brief using the required format."""

    response = _client.models.generate_content(
        model="gemini-2.5-flash",
        contents=user_message,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
        ),
    )

    return parse_brief(response.text, ticker)
