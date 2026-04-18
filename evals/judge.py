"""
LLM-as-judge. Costs one Gemini call per case, per axis. Opt-in via --judge flag
on the runner, because it's the expensive part of the eval.

We score on four axes (0-5 each):
  - citation_faithfulness : are the claims actually supported by the cited URLs?
  - plain_english         : is jargon defined inline? would Alex (22-28, <18mo investing) follow?
  - tone                  : calm / honest / non-hyped? no forbidden posture?
  - rubric_match          : how well does the brief satisfy this case's specific judge_rubric?

We use a stronger model (gemini-2.5-pro) as judge — cheaper than a human, and
the "judge harder than generator" pattern is the standard guidance.
"""

import json
import os
from dataclasses import dataclass

from google import genai
from google.genai import types

from .cases import EvalCase


JUDGE_MODEL = "gemini-2.5-pro"

JUDGE_SYSTEM_PROMPT = """You are a careful evaluator of stock briefs written for first-year investors.

You will score a brief on four axes, each 0-5:
  - citation_faithfulness: 5 = every factual claim is supported by the cited URLs. 0 = claims are fabricated or unsupported.
  - plain_english: 5 = jargon is always defined inline, no undefined terms. 0 = dense finance-speak with no translation.
  - tone: 5 = calm, honest, acknowledges uncertainty. 0 = hyped, FOMO-inducing, or condescending.
  - rubric_match: 5 = fully satisfies the specific rubric for this case. 0 = ignores it.

Be strict. Most real briefs score 2-4, not 5. A 5 means genuinely excellent.
Return a short justification (<= 2 sentences) per axis."""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "citation_faithfulness": {"type": "integer", "minimum": 0, "maximum": 5},
        "citation_faithfulness_reason": {"type": "string"},
        "plain_english": {"type": "integer", "minimum": 0, "maximum": 5},
        "plain_english_reason": {"type": "string"},
        "tone": {"type": "integer", "minimum": 0, "maximum": 5},
        "tone_reason": {"type": "string"},
        "rubric_match": {"type": "integer", "minimum": 0, "maximum": 5},
        "rubric_match_reason": {"type": "string"},
    },
    "required": [
        "citation_faithfulness", "citation_faithfulness_reason",
        "plain_english", "plain_english_reason",
        "tone", "tone_reason",
        "rubric_match", "rubric_match_reason",
    ],
}


@dataclass
class JudgeScore:
    citation_faithfulness: int
    plain_english: int
    tone: int
    rubric_match: int
    reasons: dict[str, str]

    @property
    def total(self) -> int:
        return self.citation_faithfulness + self.plain_english + self.tone + self.rubric_match

    @property
    def mean(self) -> float:
        return self.total / 4.0


_client = None


def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


def judge_brief(brief: dict, case: EvalCase) -> JudgeScore:
    rubric = case.judge_rubric or "Generic: brief is useful, honest, and appropriate for a first-year investor."

    prompt = f"""Evaluate this stock brief for {case.ticker}.

### Case-specific rubric
{rubric}

### Full brief (markdown)
{brief.get('full_brief', '')}

Score each axis 0-5 with a short justification. Be strict."""

    response = _get_client().models.generate_content(
        model=JUDGE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=JUDGE_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=JUDGE_SCHEMA,
        ),
    )

    data = json.loads(response.text)
    return JudgeScore(
        citation_faithfulness=data["citation_faithfulness"],
        plain_english=data["plain_english"],
        tone=data["tone"],
        rubric_match=data["rubric_match"],
        reasons={
            "citation_faithfulness": data["citation_faithfulness_reason"],
            "plain_english": data["plain_english_reason"],
            "tone": data["tone_reason"],
            "rubric_match": data["rubric_match_reason"],
        },
    )
