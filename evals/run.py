"""
Eval harness for Stockify briefs.

Usage:
    # Fast: run agent on every case, apply deterministic checks only.
    uv run python -m evals.run

    # Full: also run the LLM-judge (costs ~1 Gemini-Pro call per case).
    uv run python -m evals.run --judge

    # Use cached briefs from a previous run (no agent calls, free).
    uv run python -m evals.run --cached

    # Subset.
    uv run python -m evals.run --only NVDA,KO

Briefs are cached to evals/results/briefs/<ticker>.json so prompt iterations
don't re-pay for data fetching. Delete the cache when upstream data changes.

Exit code: 0 if all cases pass all deterministic checks, 1 otherwise. The
LLM-judge scores do not affect exit code — they're for tracking, not gating.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from evals.cases import CASES, EvalCase
from evals.checks import run_all_checks


RESULTS_DIR = Path(__file__).parent / "results"
BRIEF_CACHE_DIR = RESULTS_DIR / "briefs"
BRIEF_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def load_cached_brief(ticker: str) -> dict | None:
    path = BRIEF_CACHE_DIR / f"{ticker}.json"
    if path.exists():
        return json.loads(path.read_text())
    return None


def save_cached_brief(ticker: str, brief: dict) -> None:
    (BRIEF_CACHE_DIR / f"{ticker}.json").write_text(json.dumps(brief, indent=2))


def get_brief(case: EvalCase, cached: bool) -> tuple[dict, float]:
    """Return (brief, seconds). Uses cache when requested and available."""
    if cached:
        b = load_cached_brief(case.ticker)
        if b:
            return b, 0.0

    from src.agent import run_agent
    t0 = time.time()
    brief = run_agent(case.ticker)
    elapsed = time.time() - t0
    save_cached_brief(case.ticker, brief)
    return brief, elapsed


def print_case_report(case: EvalCase, check_results: list, judge_score=None, elapsed: float = 0.0) -> bool:
    """Print a single case's results. Returns True if all deterministic checks passed."""
    all_passed = all(not issues for _, issues in check_results)
    status = "PASS" if all_passed else "FAIL"
    timing = f" ({elapsed:.1f}s)" if elapsed else " (cached)"
    print(f"\n[{status}] {case.ticker}{timing} — {case.description}")

    for check_name, issues in check_results:
        if not issues:
            continue
        for issue in issues:
            print(f"  - {check_name}: {issue}")

    if judge_score:
        print(
            f"  judge: faith={judge_score.citation_faithfulness}/5 "
            f"plain={judge_score.plain_english}/5 "
            f"tone={judge_score.tone}/5 "
            f"rubric={judge_score.rubric_match}/5 "
            f"(mean {judge_score.mean:.2f})"
        )
        for axis, reason in judge_score.reasons.items():
            print(f"    • {axis}: {reason}")

    return all_passed


def write_summary_json(run_record: dict) -> Path:
    """Persist a machine-readable run record for tracking scores over time."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = RESULTS_DIR / f"run_{ts}.json"
    path.write_text(json.dumps(run_record, indent=2))
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Stockify eval harness")
    parser.add_argument("--judge", action="store_true",
                        help="Run LLM-as-judge (costs ~1 Gemini-Pro call per case)")
    parser.add_argument("--cached", action="store_true",
                        help="Use cached briefs from previous run, skip agent calls")
    parser.add_argument("--only", type=str, default="",
                        help="Comma-separated tickers to run (e.g. NVDA,KO)")
    args = parser.parse_args()

    only = {t.strip().upper() for t in args.only.split(",") if t.strip()}
    cases = [c for c in CASES if not only or c.ticker in only]

    print(f"Stockify eval: {len(cases)} case(s), judge={'on' if args.judge else 'off'}, cached={'on' if args.cached else 'off'}")
    print("=" * 72)

    run_record = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "judge_enabled": args.judge,
        "cases": [],
    }
    passed = failed = 0

    for case in cases:
        try:
            brief, elapsed = get_brief(case, cached=args.cached)
        except Exception as e:
            print(f"\n[ERROR] {case.ticker}: could not generate brief: {e}")
            failed += 1
            run_record["cases"].append({
                "ticker": case.ticker, "status": "error", "error": str(e),
            })
            continue

        check_results = run_all_checks(brief, case)

        judge_score = None
        if args.judge:
            try:
                from evals.judge import judge_brief
                judge_score = judge_brief(brief, case)
            except Exception as e:
                print(f"  judge failed: {e}")

        ok = print_case_report(case, check_results, judge_score, elapsed)
        if ok:
            passed += 1
        else:
            failed += 1

        run_record["cases"].append({
            "ticker": case.ticker,
            "status": "pass" if ok else "fail",
            "elapsed_seconds": elapsed,
            "issues": [
                {"check": n, "issues": i} for n, i in check_results if i
            ],
            "judge": (
                {
                    "citation_faithfulness": judge_score.citation_faithfulness,
                    "plain_english": judge_score.plain_english,
                    "tone": judge_score.tone,
                    "rubric_match": judge_score.rubric_match,
                    "reasons": judge_score.reasons,
                }
                if judge_score else None
            ),
        })

    print("\n" + "=" * 72)
    print(f"Summary: {passed} passed, {failed} failed out of {len(cases)}")

    if args.judge:
        scored = [c for c in run_record["cases"] if c.get("judge")]
        if scored:
            mean_of_means = sum(
                (c["judge"]["citation_faithfulness"] + c["judge"]["plain_english"]
                 + c["judge"]["tone"] + c["judge"]["rubric_match"]) / 4
                for c in scored
            ) / len(scored)
            print(f"Judge mean-of-means: {mean_of_means:.2f} / 5")

    summary_path = write_summary_json(run_record)
    print(f"Run record: {summary_path.relative_to(Path.cwd())}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
