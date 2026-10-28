import os
import warnings
from typing import Any

import httpx
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

EDGAR_BASE = "https://data.sec.gov"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
# SEC's fair-access policy requires a descriptive User-Agent with contact info.
# Set SEC_USER_AGENT in .env ("Your Name you@example.com"). The fallback keeps
# dev and tests working, but use a real one before fetching at any volume.
HEADERS = {"User-Agent": os.environ.get("SEC_USER_AGENT") or "Financial Advisor MVP contact@example.com"}

_cik_map: dict[str, str] = {}


def _load_cik_map() -> dict[str, str]:
    global _cik_map
    if _cik_map:
        return _cik_map
    resp = httpx.get(TICKERS_URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    _cik_map = {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in data.values()}
    return _cik_map


def _fetch_filing_text(url: str, max_chars: int = 3000) -> str:
    """Fetch and extract readable text from an SEC filing document."""
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
        if resp.status_code != 200:
            return ""
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["script", "style", "nav", "header", "footer", "table"]):
            tag.decompose()
        text = " ".join(soup.get_text(separator=" ").split())
        return text[:max_chars]
    except Exception:
        return ""


def get_latest_filing(ticker: str) -> dict[str, Any]:
    """Fetch the most recent 10-K, 10-Q, or 8-K from SEC EDGAR, with text for 8-Ks."""
    ticker = ticker.upper()
    try:
        cik_map = _load_cik_map()
    except Exception as e:
        return {"error": f"Could not load SEC ticker data: {e}"}

    cik = cik_map.get(ticker)
    if not cik:
        return {"error": f"No SEC EDGAR entry found for ticker {ticker}."}

    try:
        resp = httpx.get(f"{EDGAR_BASE}/submissions/CIK{cik}.json", headers=HEADERS, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return {"error": f"SEC EDGAR request failed: {e}"}

    filings = data.get("filings", {}).get("recent", {})
    forms = filings.get("form", [])
    dates = filings.get("filingDate", [])
    acc_nums = filings.get("accessionNumber", [])
    descriptions = filings.get("primaryDocument", [])

    # CIK without leading zeros for building document URLs
    cik_int = str(int(cik))

    target_forms = {"10-K", "10-Q", "8-K"}
    for i, form in enumerate(forms):
        if form in target_forms:
            acc_clean = acc_nums[i].replace("-", "")
            doc = descriptions[i] if i < len(descriptions) else ""
            filing_url = (
                f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_clean}/{doc}"
                if doc
                else f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}&dateb=&owner=include&count=1"
            )

            result: dict[str, Any] = {
                "company_name": data.get("name", ticker),
                "form_type": form,
                "filing_date": dates[i],
                "accession_number": acc_nums[i],
                "url": filing_url,
                "edgar_page": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=&dateb=&owner=include&count=10",
                "content": "",
            }

            # For 8-Ks, fetch the actual text to expose material events
            if form == "8-K" and doc and filing_url.startswith("https://www.sec.gov/Archives"):
                result["content"] = _fetch_filing_text(filing_url)

            return result

    return {"error": f"No recent 10-K, 10-Q, or 8-K found for {ticker}."}
