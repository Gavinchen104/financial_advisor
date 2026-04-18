import json
import concurrent.futures
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

load_dotenv()

LOGS_DIR = Path(__file__).parent.parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)
LOG_FILE = LOGS_DIR / "briefs.jsonl"

app = FastAPI(title="Financial Advisor", version="0.1.0")


class BriefRequest(BaseModel):
    ticker: str
    experience_level: str = "first_year"
    mode: Literal["baseline", "enhanced"] = "enhanced"


class BriefResponse(BaseModel):
    ticker: str
    what_happened: str
    why_moved: str
    what_it_means: str
    sources_text: str
    full_brief: str
    disclaimer: str
    mode: str


class CompareResponse(BaseModel):
    ticker: str
    baseline: BriefResponse
    enhanced: BriefResponse


def _validate_ticker(ticker: str) -> str:
    ticker = ticker.strip().upper()
    if not ticker or not ticker.replace(".", "").isalpha() or len(ticker) > 5:
        raise HTTPException(status_code=400, detail="Invalid ticker symbol. Use 1–5 letters (e.g. NVDA).")
    return ticker


def _log(ticker: str, experience_level: str, mode: str):
    entry = {"ts": datetime.now(timezone.utc).isoformat(), "ticker": ticker, "experience_level": experience_level, "mode": mode}
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


@app.get("/")
def serve_index():
    return FileResponse(Path(__file__).parent / "web" / "index.html")


@app.post("/brief", response_model=BriefResponse)
def generate_brief(req: BriefRequest):
    ticker = _validate_ticker(req.ticker)
    from .agent import run_agent
    result = run_agent(ticker, req.experience_level, req.mode)
    if "error" in result and not result.get("what_happened"):
        raise HTTPException(status_code=500, detail=result["error"])
    _log(ticker, req.experience_level, req.mode)
    return BriefResponse(**result)


@app.post("/brief/compare", response_model=CompareResponse)
def compare_briefs(req: BriefRequest):
    """Run baseline and enhanced in parallel and return both for side-by-side comparison."""
    ticker = _validate_ticker(req.ticker)
    from .agent import run_agent

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f_baseline = executor.submit(run_agent, ticker, req.experience_level, "baseline")
        f_enhanced = executor.submit(run_agent, ticker, req.experience_level, "enhanced")
        baseline = f_baseline.result()
        enhanced = f_enhanced.result()

    _log(ticker, req.experience_level, "compare")
    return CompareResponse(
        ticker=ticker,
        baseline=BriefResponse(**baseline),
        enhanced=BriefResponse(**enhanced),
    )
