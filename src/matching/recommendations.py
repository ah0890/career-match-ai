"""Turn a match result into prioritisation guidance.

Labels are guidance for deciding where to spend effort — never a prediction of being
shortlisted or hired. Suggested actions only ask the candidate to make explicit what
they genuinely have; nothing here invents skills, experience or achievements.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Literal

from config.settings import RecommendationThresholds
from src.jobs.freshness import Freshness, assess
from src.matching.engine import MatchResult

Priority = Literal["High", "Medium", "Low"]

RECOMMENDATION_DISCLAIMER = (
    "Recommendations help you decide where to spend your effort. They are based only on your CV and the job "
    "description, and are not a prediction of being shortlisted or hired."
)


class Label(str, Enum):
    APPLY = "APPLY"
    APPLY_AFTER_IMPROVEMENT = "APPLY AFTER IMPROVEMENT"
    DONT_PRIORITIZE = "DON'T PRIORITIZE"


LABEL_TONES = {Label.APPLY: "success", Label.APPLY_AFTER_IMPROVEMENT: "info", Label.DONT_PRIORITIZE: "neutral"}
LABEL_ORDER = {Label.APPLY: 0, Label.APPLY_AFTER_IMPROVEMENT: 1, Label.DONT_PRIORITIZE: 2}
_PRIORITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}
_ATS_ACTION_BELOW = 70
_SKILLS_PER_ACTION = 5
_RESPONSIBILITY_ACTIONS = 2


@dataclass(frozen=True)
class Action:
    priority: Priority
    title: str
    detail: str


@dataclass(frozen=True)
class Recommendation:
    label: Label
    headline: str
    reasons: tuple[str, ...]
    actions: tuple[Action, ...]
    caveats: tuple[str, ...]

    @property
    def tone(self) -> str:
        return LABEL_TONES[self.label]


def _component_percent(result: MatchResult, key: str) -> int | None:
    return next((c.percent for c in result.components if c.key == key), None)


def _actions(result: MatchResult) -> list[Action]:
    actions = [
        Action("High", f"Show “{g.requirement}” clearly, if you have it",
               f"The job states it as essential (“{g.evidence}”), and it was not found in your CV. If you have it, "
               "name it explicitly in your skills and in the role where you used it.")
        for g in result.mandatory_gaps
    ]
    essential = {g.requirement for g in result.mandatory_gaps}
    missing = [s for s in result.missing_required_skills if s not in essential]
    if missing:
        shown = missing[:_SKILLS_PER_ACTION]
        more = f" and {len(missing) - len(shown)} more" if len(missing) > len(shown) else ""
        actions.append(Action(
            "Medium", "Name the required skills you genuinely have",
            f"Not found in your CV: {', '.join(shown)}{more}. If you have used any of them, list them and describe "
            "where. Leave out anything you have not done."))
    resp = next((c for c in result.components if c.key == "responsibilities"), None)
    if resp and resp.assessed:
        for gap in resp.gaps[:_RESPONSIBILITY_ACTIONS]:
            text = gap.removeprefix("Not clearly reflected: ")
            actions.append(Action(
                "Medium", "Describe relevant experience in the job's terms",
                f"The job lists “{text}”. If you have done similar work, describe it in your experience using "
                "comparable wording."))
    exp = next((c for c in result.components if c.key == "experience"), None)
    if exp and exp.assessed:
        for gap in exp.gaps:
            if "no employment dates" in gap:
                actions.append(Action("Medium", "Add dates to each role",
                                      "Your experience could not be measured because no employment dates were found."))
            else:
                actions.append(Action("Low", "Lead with your most relevant experience",
                                      f"{gap} Editing your CV cannot change this; put your most relevant work first."))
    edu = next((c for c in result.components if c.key == "education"), None)
    if edu and edu.assessed and edu.gaps and "No " in edu.gaps[0]:
        actions.append(Action("Medium", "List your qualifications", edu.gaps[0]))
    ats = _component_percent(result, "ats")
    if ats is not None and ats < _ATS_ACTION_BELOW:
        actions.append(Action("Medium", "Make your CV easier to read",
                              f"Your CV readability score is {ats}/100. See CV Analysis for specific fixes."))
    actions.sort(key=lambda a: _PRIORITY_ORDER[a.priority])
    return actions


def recommend(result: MatchResult, thresholds: RecommendationThresholds, now: datetime | None = None) -> Recommendation:
    freshness = assess(result.job, now)
    reasons: list[str] = []
    caveats: list[str] = []

    if result.score >= thresholds.apply:
        label = Label.APPLY
        reasons.append(f"Your match score of {result.score} meets the APPLY threshold ({thresholds.apply:g}).")
    elif result.score >= thresholds.improve:
        label = Label.APPLY_AFTER_IMPROVEMENT
        reasons.append(f"Your match score of {result.score} is between the improvement ({thresholds.improve:g}) and "
                       f"APPLY ({thresholds.apply:g}) thresholds.")
    else:
        label = Label.DONT_PRIORITIZE
        reasons.append(f"Your match score of {result.score} is below the improvement threshold ({thresholds.improve:g}).")

    if result.mandatory_gaps:
        names = ", ".join(g.requirement for g in result.mandatory_gaps)
        reasons.append(f"Essential requirement(s) not found in your CV: {names}.")
        if label is Label.APPLY:
            label = Label.APPLY_AFTER_IMPROVEMENT
            reasons.append("A job with an essential requirement your CV does not show is never marked APPLY, "
                           "whatever the score.")

    if freshness.status is Freshness.EXPIRED:
        label = Label.DONT_PRIORITIZE
        reasons.append(freshness.explanation)
    elif freshness.status is Freshness.POSSIBLY_STALE:
        caveats.append(f"{freshness.explanation}")

    if result.confidence == "Low":
        caveats.append("This is based on limited information from the source. Read the full listing before deciding.")
    if result.check_yourself:
        caveats.append("Confirm these yourself: " + ", ".join(label_ for label_, _ in result.check_yourself) + ".")

    headline = {
        Label.APPLY: "Strong evidence for this role — worth applying.",
        Label.APPLY_AFTER_IMPROVEMENT: "Promising — strengthen your CV for this role before applying.",
        Label.DONT_PRIORITIZE: "Lower priority — other roles match your CV better.",
    }[label]
    if freshness.status is Freshness.EXPIRED:
        headline = "This listing has expired."
    return Recommendation(label, headline, tuple(reasons), tuple(_actions(result)), tuple(caveats))


@dataclass(frozen=True)
class RankedMatch:
    result: MatchResult
    recommendation: Recommendation


def prioritise(results: list[MatchResult], thresholds: RecommendationThresholds,
               now: datetime | None = None) -> list[RankedMatch]:
    """Order by recommendation, then score. Low-confidence matches stay after the others."""
    ranked = [RankedMatch(r, recommend(r, thresholds, now)) for r in results]
    return sorted(ranked, key=lambda m: (m.result.confidence == "Low", LABEL_ORDER[m.recommendation.label],
                                         -m.result.score))
