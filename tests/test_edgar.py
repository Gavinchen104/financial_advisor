"""EDGAR client with mocked HTTP (respx): CIK lookup, filing selection, caching,
throttling and retries (P2-C)."""

import json
import time
from datetime import date

import httpx
import pytest
import respx

from src.rag.edgar import ARCHIVE_URL, SUBMISSIONS_URL, TICKERS_URL, EdgarClient, EdgarError, Filing, period_label

TICKERS_JSON = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"},
}
SUBMISSIONS = {
    "name": "Apple Inc.",
    "filings": {
        "recent": {  # newest first, like the real API
            "form": ["8-K", "10-Q", "10-K/A", "10-K", "10-Q", "10-Q", "10-K"],
            "accessionNumber": [
                "0000320193-25-000090", "0000320193-25-000080", "0000320193-24-000130", "0000320193-24-000123",
                "0000320193-24-000081", "0000320193-24-000069", "0000320193-23-000106",
            ],
            "reportDate": ["2025-10-30", "2025-06-28", "2024-09-28", "2024-09-28", "2024-06-29", "2024-03-30", "2023-09-30"],
            "filingDate": ["2025-10-30", "2025-08-01", "2024-11-15", "2024-11-01", "2024-08-02", "2024-05-03", "2023-11-03"],
            "primaryDocument": [
                "aapl-20251030.htm", "aapl-20250628.htm", "aapl-20240928a.htm", "aapl-20240928.htm",
                "aapl-20240629.htm", "aapl-20240330.htm", "aapl-20230930.htm",
            ],
        }
    },
}


@pytest.fixture
def client(tmp_path) -> EdgarClient:
    return EdgarClient(user_agent="Stockify tests test@example.com", raw_dir=tmp_path, max_rps=10_000, retry_wait_max=0)


def _mock_tickers():
    return respx.get(TICKERS_URL).mock(return_value=httpx.Response(200, json=TICKERS_JSON))


@respx.mock
def test_cik_lookup_is_cached_and_mirrored(client, tmp_path):
    route = _mock_tickers()
    assert client.cik_for("aapl") == "0000320193"
    assert client.cik_for("NVDA") == "0001045810"
    assert client.company_name("AAPL") == "Apple Inc."
    assert route.call_count == 1  # one fetch per process
    assert json.loads((tmp_path / "company_tickers.json").read_text()) == TICKERS_JSON
    with pytest.raises(EdgarError):
        client.cik_for("ZZZZ")


@respx.mock
def test_cik_lookup_falls_back_to_the_mirror_when_sec_is_down(tmp_path):
    (tmp_path / "company_tickers.json").write_text(json.dumps(TICKERS_JSON))
    respx.get(TICKERS_URL).mock(return_value=httpx.Response(503))
    client = EdgarClient(user_agent="t t@example.com", raw_dir=tmp_path, max_rps=10_000, retry_wait_max=0, attempts=1)
    assert client.cik_for("AAPL") == "0000320193"


@respx.mock
def test_list_filings_takes_latest_per_form_with_exact_form_match(client):
    _mock_tickers()
    respx.get(SUBMISSIONS_URL.format(cik="0000320193")).mock(return_value=httpx.Response(200, json=SUBMISSIONS))

    filings = client.list_filings("AAPL")
    assert [(f.form, f.accession) for f in filings] == [
        ("10-Q", "0000320193-25-000080"),
        ("10-K", "0000320193-24-000123"),  # the 10-K/A amendment is skipped
        ("10-Q", "0000320193-24-000081"),
    ]
    k = filings[1]
    assert k.cik == "0000320193" and k.ticker == "AAPL" and k.company_name == "Apple Inc."
    assert k.period_end == date(2024, 9, 28) and k.filed_at == date(2024, 11, 1)
    assert k.url == "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm"
    assert k.node_id == "filing:0000320193-24-000123"
    assert k.title == "AAPL 10-K FY2024"
    assert filings[0].title == "AAPL 10-Q quarter ended 2025-06-28"


@respx.mock
def test_list_filings_honors_custom_counts(client):
    _mock_tickers()
    respx.get(SUBMISSIONS_URL.format(cik="0000320193")).mock(return_value=httpx.Response(200, json=SUBMISSIONS))
    filings = client.list_filings("AAPL", {"10-K": 2})
    assert [f.accession for f in filings] == ["0000320193-24-000123", "0000320193-23-000106"]


@respx.mock
def test_fetch_document_caches_on_disk(client, tmp_path):
    filing = Filing("AAPL", "0000320193", "10-K", "0000320193-24-000123", "aapl-20240928.htm", date(2024, 9, 28), date(2024, 11, 1))
    route = respx.get(filing.url).mock(return_value=httpx.Response(200, text="<html>10-K body</html>"))

    assert not client.is_cached(filing)
    assert client.fetch_document(filing) == "<html>10-K body</html>"
    assert route.call_count == 1
    cached = tmp_path / "0000320193" / "0000320193-24-000123.html"
    assert cached.read_text() == "<html>10-K body</html>"
    assert client.is_cached(filing)

    assert client.fetch_document(filing) == "<html>10-K body</html>"
    assert route.call_count == 1  # served from disk
    client.fetch_document(filing, refetch=True)
    assert route.call_count == 2


@respx.mock
def test_retries_on_503_and_429_but_not_on_404(client):
    url = ARCHIVE_URL.format(cik_int=1, acc="x", doc="a.htm")
    respx.get(url).mock(side_effect=[httpx.Response(503), httpx.Response(429), httpx.Response(200, text="ok")])
    assert client._get(url).text == "ok"
    assert client.requests == 3

    missing = ARCHIVE_URL.format(cik_int=1, acc="y", doc="b.htm")
    respx.get(missing).mock(return_value=httpx.Response(404))
    before = client.requests
    with pytest.raises(httpx.HTTPStatusError):
        client._get(missing)
    assert client.requests == before + 1


@respx.mock
def test_user_agent_header_is_sent(client):
    route = _mock_tickers()
    client.cik_for("AAPL")
    assert route.calls.last.request.headers["User-Agent"] == "Stockify tests test@example.com"


@respx.mock
def test_requests_are_throttled(tmp_path):
    client = EdgarClient(user_agent="t t@example.com", raw_dir=tmp_path, max_rps=50, retry_wait_max=0)
    url = ARCHIVE_URL.format(cik_int=1, acc="z", doc="c.htm")
    respx.get(url).mock(return_value=httpx.Response(200, text="ok"))
    t0 = time.perf_counter()
    for _ in range(5):
        client._get(url)
    elapsed = time.perf_counter() - t0
    assert elapsed >= 4 / 50 * 0.8  # four gaps of 20 ms, minus scheduler slack


@respx.mock
def test_supplemental_documents_pick_large_siblings_but_not_viewer_or_boilerplate_files(client, tmp_path):
    filing = Filing("WFC", "0000072971", "10-K", "0000072971-26-000133", "wfc-20251231_d2.htm", date(2025, 12, 31), date(2026, 2, 20))
    folder = "https://www.sec.gov/Archives/edgar/data/72971/000007297126000133"
    index = respx.get(f"{folder}/index.json").mock(return_value=httpx.Response(200, json={"directory": {"item": [
        {"name": "0000072971-26-000133-index.html", "size": "5000"},
        {"name": "R1.htm", "size": "92615"},
        {"name": "R41.htm", "size": "1151222"},
        {"name": "wfc-1231x2025xex10a.htm", "size": "392548"},
        {"name": "wfc-1231x2025xex4c.htm", "size": "301463"},
        {"name": "wfc-1231x2025xex13.htm", "size": "900000"},
        {"name": "wfc-20251231.htm", "size": "11595621"},
        {"name": "wfc-20251231_d2.htm", "size": "359609"},
        {"name": "small-ex99.htm", "size": "1000"},
        {"name": "logo.jpg", "size": "5000000"},
    ]}}))
    main = respx.get(f"{folder}/wfc-20251231.htm").mock(return_value=httpx.Response(200, text="<html>main body</html>"))
    ex13 = respx.get(f"{folder}/wfc-1231x2025xex13.htm").mock(return_value=httpx.Response(200, text="<html>annual report</html>"))

    docs = client.supplemental_documents(filing)
    assert [name for name, _ in docs] == ["wfc-20251231.htm", "wfc-1231x2025xex13.htm"]  # largest first, max two
    assert docs[0][1] == "<html>main body</html>" and docs[1][1] == "<html>annual report</html>"
    assert index.call_count == 1 and main.call_count == 1 and ex13.call_count == 1
    assert (tmp_path / "0000072971" / "0000072971-26-000133.index.json").exists()
    assert (tmp_path / "0000072971" / "0000072971-26-000133__wfc-20251231.htm").read_text() == "<html>main body</html>"

    # second call: everything comes from the cache
    assert [name for name, _ in client.supplemental_documents(filing)] == ["wfc-20251231.htm", "wfc-1231x2025xex13.htm"]
    assert index.call_count == 1 and main.call_count == 1


@respx.mock
def test_supplemental_documents_empty_when_nothing_is_large_enough(client):
    filing = Filing("ACME", "0000123456", "10-Q", "0000123456-25-000002", "acme.htm", date(2025, 6, 28), date(2025, 8, 1))
    respx.get("https://www.sec.gov/Archives/edgar/data/123456/000012345625000002/index.json").mock(
        return_value=httpx.Response(200, json={"directory": {"item": [
            {"name": "acme.htm", "size": "800000"}, {"name": "acme-ex99.htm", "size": "900000"}, {"name": "R2.htm", "size": "9000000"},
        ]}})
    )
    assert client.supplemental_documents(filing) == []  # ex99 is not 2× the primary; R2 is a viewer page


def test_period_label():
    assert period_label("10-K", date(2025, 9, 27)) == "FY2025"
    assert period_label("10-Q", date(2025, 6, 28)) == "quarter ended 2025-06-28"
    assert period_label("10-K", None) == "period unknown"
