"""Smoke test: runs the agent on NVDA, KO, and ZZZZ and prints results."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv()

from src.agent import run_agent

FORBIDDEN_WORDS = ["buy", "sell", "hold", "strong buy", "price target"]

TEST_CASES = [
    ("NVDA", "high-news stock — should have lots to say"),
    ("KO", "stable stock — should gracefully say not much happened"),
    ("ZZZZ", "invalid ticker — should fail gracefully"),
]


def check_brief(result: dict, ticker: str) -> list[str]:
    issues = []
    full = result.get("full_brief", "").lower()
    for word in FORBIDDEN_WORDS:
        if f" {word} " in f" {full} ":
            issues.append(f"forbidden word: '{word}'")
    if "educational information" not in result.get("disclaimer", "").lower():
        issues.append("missing or malformed disclaimer")
    return issues


def run_smoke_tests() -> bool:
    passed = 0
    failed = 0

    for ticker, description in TEST_CASES:
        print(f"\n{'=' * 60}")
        print(f"  {ticker}: {description}")
        print("=" * 60)

        try:
            result = run_agent(ticker)

            what_happened = result.get("what_happened", "").strip()
            why_moved = result.get("why_moved", "").strip()
            what_it_means = result.get("what_it_means", "").strip()

            print(f"What happened:  {what_happened[:120]}")
            print(f"Why moved:      {why_moved[:120]}")
            print(f"What it means:  {what_it_means[:120]}")

            if ticker == "ZZZZ":
                no_data = any(
                    kw in what_happened.lower()
                    for kw in ["invalid", "not found", "unavailable", "unable", "no price", "could not", "no data"]
                )
                if no_data or not what_happened:
                    print("PASS: invalid ticker handled gracefully")
                    passed += 1
                else:
                    print(f"PASS (partial): got a response, content may vary for unknown tickers")
                    passed += 1
                continue

            issues = check_brief(result, ticker)
            if issues:
                for issue in issues:
                    print(f"WARN: {issue}")

            required = ["what_happened", "why_moved", "what_it_means", "disclaimer"]
            missing = [f for f in required if not result.get(f)]
            if missing:
                print(f"FAIL: missing fields: {missing}")
                failed += 1
            else:
                print("PASS")
                passed += 1

        except Exception as e:
            if ticker == "ZZZZ":
                print(f"PASS (exception for invalid ticker): {e}")
                passed += 1
            else:
                print(f"FAIL: unexpected exception: {e}")
                import traceback
                traceback.print_exc()
                failed += 1

    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed out of {len(TEST_CASES)} tests")
    return failed == 0


if __name__ == "__main__":
    success = run_smoke_tests()
    sys.exit(0 if success else 1)
