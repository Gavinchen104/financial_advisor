import json
from datetime import datetime, timezone
from pathlib import Path

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


class BriefResponse(BaseModel):
    ticker: str
    what_happened: str
    why_moved: str
    what_it_means: str
    sources_text: str
    full_brief: str
    disclaimer: str


@app.get("/")
def serve_index():
    return FileResponse(Path(__file__).parent / "web" / "index.html")


@app.post("/brief", response_model=BriefResponse)
def generate_brief(req: BriefRequest):
    ticker = req.ticker.strip().upper()
    if not ticker or not ticker.replace(".", "").isalpha() or len(ticker) > 5:
        raise HTTPException(status_code=400, detail="Invalid ticker symbol. Use 1–5 letters (e.g. NVDA).")

    from .agent import run_agent

    result = run_agent(ticker, req.experience_level)

    if "error" in result and not result.get("what_happened"):
        raise HTTPException(status_code=500, detail=result["error"])

    log_entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "ticker": ticker,
        "experience_level": req.experience_level,
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(log_entry) + "\n")

    return BriefResponse(**result)
