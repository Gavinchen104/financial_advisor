"""
Eval test cases. Each case names a ticker and what must/must-not be true about
the generated brief. Add cases here as you find failure modes in production —
this file is the regression set.
"""

from dataclasses import dataclass, field


@dataclass
class EvalCase:
    ticker: str
    description: str
    # must_mention: at least one of these substrings (lowercase) should appear somewhere in the brief
    must_mention_any: list[str] = field(default_factory=list)
    # must_not_mention: none of these substrings (lowercase) should appear anywhere in the brief
    must_not_mention: list[str] = field(default_factory=list)
    # judge_rubric: freeform criterion the LLM judge will score (0-5) when --judge is set
    judge_rubric: str = ""
    # expect_invalid: if True, the brief should gracefully acknowledge missing data instead of fabricating
    expect_invalid: bool = False


CASES: list[EvalCase] = [
    EvalCase(
        ticker="NVDA",
        description="High-news tech stock — should reference knowledge-graph context (AI, semis, 10y yield)",
        must_mention_any=["ai", "data center", "gpu", "semiconductor", "chip"],
        judge_rubric=(
            "Does the brief explain the week's price move using at least one "
            "specific signal (earnings, analyst action, competitor move, macro factor, "
            "or named news event)? Generic statements like 'tech was volatile' score low."
        ),
    ),
    EvalCase(
        ticker="KO",
        description="Quiet consumer-staples stock — should gracefully say 'not much happened' when news is thin",
        must_mention_any=["quiet", "limited", "little news", "not much", "modest", "stable", "no major"],
        judge_rubric=(
            "When news is thin, does the brief honestly acknowledge that limitation "
            "instead of inventing drama? Honesty about uncertainty scores high."
        ),
    ),
    EvalCase(
        ticker="ZZZZ",
        description="Invalid ticker — must say data unavailable, must not fabricate",
        must_mention_any=["invalid", "not found", "unavailable", "unable", "no price", "no data", "delisted"],
        expect_invalid=True,
    ),
    EvalCase(
        ticker="XOM",
        description="Energy stock — should tie move to crude oil (macro factor from knowledge graph)",
        must_mention_any=["oil", "crude", "energy", "opec"],
        judge_rubric=(
            "Does the brief tie the price move to a named macro factor (oil price, "
            "rig count, OPEC, etc.)? A generic 'energy sector moved' without the driver scores low."
        ),
    ),
    EvalCase(
        ticker="JPM",
        description="Bank stock — should reference rates / yield curve / net interest margin",
        must_mention_any=["rate", "yield", "interest", "fed", "margin"],
        judge_rubric=(
            "Does the brief connect the move to a rate-sensitive driver specific to banks? "
            "Vague 'financials were up' scores low."
        ),
    ),
]
