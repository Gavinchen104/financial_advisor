import concurrent.futures
import json
import os
from pathlib import Path
from typing import Literal

from google import genai
from google.genai import types
from dotenv import load_dotenv

from .tools.news import get_recent_news
from .tools.filings import get_latest_filing
from .tools.price import (
    get_price_action,
    get_earnings_data,
    get_market_context,
    get_analyst_data,
    get_insider_transactions,
)
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

    if mode == "enhanced":
        # Fetch all data sources in parallel for lower latency
        with concurrent.futures.ThreadPoolExecutor(max_workers=7) as executor:
            f_news = executor.submit(get_recent_news, ticker, 7, True)
            f_filing = executor.submit(get_latest_filing, ticker)
            f_price = executor.submit(get_price_action, ticker)
            f_earnings = executor.submit(get_earnings_data, ticker)
            f_market = executor.submit(get_market_context, ticker)
            f_analyst = executor.submit(get_analyst_data, ticker)
            f_insider = executor.submit(get_insider_transactions, ticker)
            news = f_news.result()
            filing = f_filing.result()
            price = f_price.result()
            earnings = f_earnings.result()
            market_ctx = f_market.result()
            analyst = f_analyst.result()
            insider = f_insider.result()

        enhanced_sections = f"""
## Earnings & Fundamentals
{json.dumps(earnings, indent=2)}

## Market Context (vs S&P 500 and Sector ETF)
{json.dumps(market_ctx, indent=2)}

## Analyst Consensus
{json.dumps(analyst, indent=2)}

## Insider Transactions
{json.dumps(insider, indent=2)}
"""
        search_note = "\nUse the Google Search tool if you need to verify or expand on any of the above."
        gemini_tools = [types.Tool(google_search=types.GoogleSearch())]
    else:
        news = get_recent_news(ticker, fetch_content=False)
        filing = get_latest_filing(ticker)
        price = get_price_action(ticker)
        enhanced_sections = ""
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
{enhanced_sections}{search_note}
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
