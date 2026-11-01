"""SEC EDGAR access for filings ingestion (docs/PROJECT2-PLAN.md P2-C).

ticker → CIK (company_tickers.json) → recent filings (submissions API) → the
primary 10-K / 10-Q document, cached on disk under data/raw/edgar/{cik}/.

Fair-access rules baked in: a descriptive User-Agent (SEC_USER_AGENT), at most
SEC_MAX_RPS requests per second across threads, exponential backoff on 429 / 5xx,
and never re-downloading a document that is already cached.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx
from loguru import logger
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential

from . import config

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc}/{doc}"
INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc}/index.json"
INGEST_FORMS = ("10-K", "10-Q")  # exact form names; amendments (10-K/A) are not ingested

# Files in a filing folder that never hold the report body: XBRL viewer pages (R1.htm…),
# index pages, and boilerplate exhibits (charters, contracts, consents, certifications).
# Exhibit 13 (annual report to shareholders) and Exhibit 99 may hold it, so they stay.
_VIEWER_FILE = re.compile(r"^R\d+\.htm$", re.I)
_BOILERPLATE_EXHIBIT = re.compile(r"ex[-_]?(?:3|4|10|19|21|22|23|24|31|32|95|97)(?![0-9])[a-z0-9._-]*\.html?$", re.I)
SUPPLEMENT_MIN_BYTES = 200_000
SUPPLEMENT_MAX_DOCS = 2


class EdgarError(RuntimeError):
    pass


def period_label(form: str, period_end: date | None) -> str:
    """'FY2025' for a 10-K (the fiscal year ends in that calendar year, which matches
    how filers name it), 'quarter ended 2025-06-28' for a 10-Q."""
    if period_end is None:
        return "period unknown"
    if form.startswith("10-K"):
        return f"FY{period_end.year}"
    return f"quarter ended {period_end.isoformat()}"


@dataclass(frozen=True)
class Filing:
    ticker: str
    cik: str  # 10 digits, zero padded
    form: str
    accession: str  # 0000320193-25-000079
    primary_document: str
    period_end: date | None
    filed_at: date | None
    company_name: str = ""

    @property
    def accession_nodash(self) -> str:
        return self.accession.replace("-", "")

    @property
    def url(self) -> str:
        return ARCHIVE_URL.format(cik_int=int(self.cik), acc=self.accession_nodash, doc=self.primary_document)

    @property
    def fiscal_label(self) -> str:
        return period_label(self.form, self.period_end)

    @property
    def node_id(self) -> str:
        return f"filing:{self.accession}"

    @property
    def title(self) -> str:
        return f"{self.ticker} {self.form} {self.fiscal_label}"


def _parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code == 429 or code >= 500
    return False


class EdgarClient:
    """One client per process. Thread-safe throttle; share it across workers."""

    def __init__(
        self,
        *,
        user_agent: str | None = None,
        raw_dir: Path | str | None = None,
        max_rps: float = config.SEC_MAX_RPS,
        client: httpx.Client | None = None,
        retry_wait_max: float = 20.0,
        attempts: int = 5,
    ):
        self.user_agent = user_agent or config.sec_user_agent()
        self.raw_dir = Path(raw_dir or config.EDGAR_RAW_DIR)
        self._min_interval = 1.0 / max_rps if max_rps else 0.0
        self._last_request = 0.0
        self._lock = threading.Lock()
        self._client = client or httpx.Client(
            headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"},
            timeout=30.0,
            follow_redirects=True,
        )
        self._retry_wait_max = retry_wait_max
        self._attempts = attempts
        self._cik_map: dict[str, dict] | None = None
        self.requests = 0  # network requests actually made (cache hits don't count)

    # ---------- HTTP ----------
    def _throttle(self) -> None:
        with self._lock:
            wait = self._last_request + self._min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()

    def _get(self, url: str) -> httpx.Response:
        for attempt in Retrying(
            retry=retry_if_exception(_retryable),
            stop=stop_after_attempt(self._attempts),
            wait=wait_exponential(multiplier=0.5, max=self._retry_wait_max),
            reraise=True,
        ):
            with attempt:
                self._throttle()
                self.requests += 1
                response = self._client.get(url, headers={"User-Agent": self.user_agent})
                response.raise_for_status()
                return response
        raise EdgarError(f"unreachable: {url}")  # pragma: no cover — Retrying re-raises

    # ---------- tickers → CIK ----------
    def cik_map(self) -> dict[str, dict]:
        """{TICKER: {'cik': '0000320193', 'name': 'Apple Inc.'}}. Fetched once per
        process and mirrored to raw_dir/company_tickers.json; the mirror is used
        when SEC is unreachable."""
        if self._cik_map is not None:
            return self._cik_map
        mirror = self.raw_dir / "company_tickers.json"
        try:
            data = self._get(TICKERS_URL).json()
            mirror.parent.mkdir(parents=True, exist_ok=True)
            mirror.write_text(json.dumps(data))
        except (httpx.HTTPError, EdgarError) as e:
            if not mirror.exists():
                raise EdgarError(f"could not load {TICKERS_URL}: {e}") from e
            logger.warning(f"edgar: using cached company_tickers.json after error: {e}")
            data = json.loads(mirror.read_text())
        self._cik_map = {
            str(v["ticker"]).upper(): {"cik": str(v["cik_str"]).zfill(10), "name": str(v.get("title", "")).strip()}
            for v in data.values()
        }
        return self._cik_map

    def cik_for(self, ticker: str) -> str:
        entry = self.cik_map().get(ticker.upper())
        if not entry:
            raise EdgarError(f"no SEC CIK for ticker {ticker.upper()}")
        return entry["cik"]

    def company_name(self, ticker: str) -> str:
        entry = self.cik_map().get(ticker.upper())
        return entry["name"] if entry else ticker.upper()

    # ---------- filings ----------
    def list_filings(self, ticker: str, form_counts: dict[str, int] | None = None) -> list[Filing]:
        """The latest N filings per form (default 1 10-K + 2 10-Qs), newest first.
        `form` must match exactly, so 10-K/A, 10-KT and NT 10-K are excluded."""
        ticker = ticker.upper()
        wanted = dict(form_counts or config.DEFAULT_FORM_COUNTS)
        cik = self.cik_for(ticker)
        data = self._get(SUBMISSIONS_URL.format(cik=cik)).json()
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accessions = recent.get("accessionNumber", [])
        report_dates = recent.get("reportDate", [])
        filing_dates = recent.get("filingDate", [])
        documents = recent.get("primaryDocument", [])
        name = (data.get("name") or self.company_name(ticker)).strip()

        out: list[Filing] = []
        for i, form in enumerate(forms):  # recent[] is newest first
            if wanted.get(form, 0) <= 0:
                continue
            doc = documents[i] if i < len(documents) else ""
            if not doc:
                continue
            wanted[form] -= 1
            out.append(Filing(
                ticker=ticker,
                cik=cik,
                form=form,
                accession=accessions[i],
                primary_document=doc,
                period_end=_parse_date(report_dates[i] if i < len(report_dates) else None),
                filed_at=_parse_date(filing_dates[i] if i < len(filing_dates) else None),
                company_name=name,
            ))
            if all(n <= 0 for n in wanted.values()):
                break
        return out

    def cache_path(self, filing: Filing) -> Path:
        return self.raw_dir / filing.cik / f"{filing.accession}.html"

    def fetch_document(self, filing: Filing, *, refetch: bool = False) -> str:
        """The primary document's HTML, from the on-disk cache when present."""
        path = self.cache_path(filing)
        if path.exists() and not refetch:
            return path.read_text(encoding="utf-8", errors="replace")
        html = self._get(filing.url).text
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
        logger.info(f"edgar: fetched {filing.title} ({len(html) / 1e6:.1f} MB) → {path}")
        return html

    def is_cached(self, filing: Filing) -> bool:
        return self.cache_path(filing).exists()

    # ---------- sibling documents (thin primary documents) ----------
    def filing_index(self, filing: Filing) -> list[dict]:
        """[{name, size}] for the filing folder, cached next to the document."""
        path = self.raw_dir / filing.cik / f"{filing.accession}.index.json"
        if path.exists():
            return json.loads(path.read_text())
        data = self._get(INDEX_URL.format(cik_int=int(filing.cik), acc=filing.accession_nodash)).json()
        items = [
            {"name": it.get("name", ""), "size": int(it.get("size") or 0)}
            for it in data.get("directory", {}).get("item", [])
        ]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(items))
        return items

    def supplemental_documents(self, filing: Filing) -> list[tuple[str, str]]:
        """Large sibling .htm documents that may hold the report body when the primary
        document is a wrapper: Wells Fargo's 10-K body is a second .htm, IBM's is
        Exhibit 13. Returns [(file name, html)], largest first, at most
        SUPPLEMENT_MAX_DOCS, each at least twice the primary document's size."""
        items = self.filing_index(filing)
        primary_size = next((it["size"] for it in items if it["name"] == filing.primary_document), 0)
        floor = max(2 * primary_size, SUPPLEMENT_MIN_BYTES)
        picks = [
            it for it in items
            if it["name"].lower().endswith((".htm", ".html"))
            and it["name"] != filing.primary_document
            and "index" not in it["name"].lower()
            and not _VIEWER_FILE.match(it["name"])
            and not _BOILERPLATE_EXHIBIT.search(it["name"])
            and it["size"] >= floor
        ]
        picks.sort(key=lambda it: -it["size"])
        out: list[tuple[str, str]] = []
        for it in picks[:SUPPLEMENT_MAX_DOCS]:
            path = self.raw_dir / filing.cik / f"{filing.accession}__{it['name']}"
            if path.exists():
                html = path.read_text(encoding="utf-8", errors="replace")
            else:
                html = self._get(ARCHIVE_URL.format(cik_int=int(filing.cik), acc=filing.accession_nodash, doc=it["name"])).text
                path.write_text(html, encoding="utf-8")
                logger.info(f"edgar: fetched sibling document {it['name']} for {filing.title} ({len(html) / 1e6:.1f} MB)")
            out.append((it["name"], html))
        return out
