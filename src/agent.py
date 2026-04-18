import concurrent.futures
import json
import os
from pathlib import Path

import yfinance as yf
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
    get_balance_sheet,
    get_valuation_context,
    get_technical_levels,
)
from .tools.context import get_knowledge_context
from .tools.brief_writer import parse_brief

load_dotenv()

_PROMPTS_DIR = Path(__file__).parent / "prompts"
SYSTEM_PROMPT = (_PROMPTS_DIR / "system.md").read_text()

_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def _ticker_has_price_data(ticker: str) -> bool:
    try:
        return yf.Ticker(ticker).fast_info.last_price is not None
    except Exception:
        return False


def run_agent(ticker: str, experience_level: str = "first_year") -> dict:
    ticker = ticker.strip().upper()

    if not _ticker_has_price_data(ticker):
        news = get_recent_news(ticker, fetch_content=False)
        filing = get_latest_filing(ticker)
        price = {"error": f"No price data found for {ticker}. It may be an invalid or delisted ticker."}
        enhanced_sections = ""
        gemini_tools = []
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            f_news = executor.submit(get_recent_news, ticker, 7, True)
            f_filing = executor.submit(get_latest_filing, ticker)
            f_price = executor.submit(get_price_action, ticker)
            f_earnings = executor.submit(get_earnings_data, ticker)
            f_market = executor.submit(get_market_context, ticker)
            f_analyst = executor.submit(get_analyst_data, ticker)
            f_insider = executor.submit(get_insider_transactions, ticker)
            f_balance = executor.submit(get_balance_sheet, ticker)
            f_valuation = executor.submit(get_valuation_context, ticker)
            f_technical = executor.submit(get_technical_levels, ticker)
            f_knowledge = executor.submit(get_knowledge_context, ticker)
            news = f_news.result()
            filing = f_filing.result()
            price = f_price.result()
            earnings = f_earnings.result()
            market_ctx = f_market.result()
            analyst = f_analyst.result()
            insider = f_insider.result()
            balance = f_balance.result()
            valuation = f_valuation.result()
            technical = f_technical.result()
            knowledge = f_knowledge.result()

        enhanced_sections = f"""
## Earnings & Fundamentals
{json.dumps(earnings, indent=2)}

## Market Context (vs S&P 500 and Sector ETF)
{json.dumps(market_ctx, indent=2)}

## Analyst Consensus
{json.dumps(analyst, indent=2)}

## Insider Transactions
{json.dumps(insider, indent=2)}

## Balance Sheet Health
{json.dumps(balance, indent=2)}

## Valuation vs Sector
{json.dumps(valuation, indent=2)}

## Technical Levels
{json.dumps(technical, indent=2)}

## Knowledge Graph Context (Related Companies & Macro Factors)
{json.dumps(knowledge, indent=2)}
"""
        gemini_tools = [types.Tool(google_search=types.GoogleSearch())]

    user_message = f"""Generate a Financial Advisor brief for {ticker}. Experience level: {experience_level}.

Here is all the data you need:

## Recent News
{json.dumps(news, indent=2)}

## Latest SEC Filing
{json.dumps(filing, indent=2)}

## Price Action (last 7 days)
{json.dumps(price, indent=2)}
{enhanced_sections}
Use the Google Search tool if you need to verify or expand on any of the above.
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
    return result
