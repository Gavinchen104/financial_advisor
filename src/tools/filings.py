from typing import Any

import httpx

EDGAR_BASE = "https://data.sec.gov"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
HEADERS = {"User-Agent": "Financial Advisor MVP contact@example.com"}

# Cache the ticker→CIK map for the process lifetime (avoids re-fetching on each call)
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


def get_latest_filing(ticker: str) -> dict[str, Any]:
    """Fetch the most recent 10-K, 10-Q, or 8-K summary from SEC EDGAR."""
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

    target_forms = {"10-K", "10-Q", "8-K"}
    for i, form in enumerate(forms):
        if form in target_forms:
            acc_clean = acc_nums[i].replace("-", "")
            doc = descriptions[i] if i < len(descriptions) else ""
            filing_url = (
                f"https://www.sec.gov/Archives/edgar/full-index/"
                f"{dates[i][:4]}/{dates[i][5:7]}/{acc_clean}/{doc}"
                if doc
                else f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}&dateb=&owner=include&count=1"
            )
            return {
                "company_name": data.get("name", ticker),
                "form_type": form,
                "filing_date": dates[i],
                "accession_number": acc_nums[i],
                "url": filing_url,
                "edgar_page": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=&dateb=&owner=include&count=10",
            }

    return {"error": f"No recent 10-K, 10-Q, or 8-K found for {ticker}."}
