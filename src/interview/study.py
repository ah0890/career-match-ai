"""Study plan for a chosen job, built from the gaps between the job and the CV.

Effort is a relative suggestion (Short / Medium / Long), not a time estimate. Links point
only to official documentation for well-known tools; anything else is described without
a link rather than guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from src.matching.engine import MatchResult
from src.matching.improvements import ImprovementPlan

Priority = Literal["High", "Medium", "Low"]
Effort = Literal["Short", "Medium", "Long"]
Status = Literal["Not started", "Preparing", "Prepared"]
STATUSES: tuple[Status, ...] = ("Not started", "Preparing", "Prepared")
_PRIORITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}

# Official documentation only. A skill missing here simply gets no link.
OFFICIAL_DOCS: dict[str, str] = {
    "Python": "https://docs.python.org/3/",
    "JavaScript": "https://developer.mozilla.org/en-US/docs/Web/JavaScript",
    "TypeScript": "https://www.typescriptlang.org/docs/",
    "HTML": "https://developer.mozilla.org/en-US/docs/Web/HTML",
    "CSS": "https://developer.mozilla.org/en-US/docs/Web/CSS",
    "React": "https://react.dev/learn",
    "Docker": "https://docs.docker.com/",
    "Kubernetes": "https://kubernetes.io/docs/home/",
    "Terraform": "https://developer.hashicorp.com/terraform/docs",
    "Git": "https://git-scm.com/doc",
    "PostgreSQL": "https://www.postgresql.org/docs/",
    "Pandas": "https://pandas.pydata.org/docs/",
    "NumPy": "https://numpy.org/doc/",
    "scikit-learn": "https://scikit-learn.org/stable/user_guide.html",
    "PyTorch": "https://pytorch.org/docs/stable/",
    "TensorFlow": "https://www.tensorflow.org/learn",
    "Power BI": "https://learn.microsoft.com/power-bi/",
    "Azure": "https://learn.microsoft.com/azure/",
    "AWS": "https://docs.aws.amazon.com/",
    "Google Cloud": "https://cloud.google.com/docs",
    "Django": "https://docs.djangoproject.com/",
    "Flask": "https://flask.palletsprojects.com/",
    "FastAPI": "https://fastapi.tiangolo.com/",
    "Node.js": "https://nodejs.org/docs/latest/api/",
    "Rust": "https://doc.rust-lang.org/book/",
    "Go": "https://go.dev/doc/",
    "Scrum": "https://scrumguides.org/",
    "GitHub Actions": "https://docs.github.com/actions",
}


@dataclass(frozen=True)
class StudyTopic:
    id: str  # stable within a job, used to store progress
    title: str
    why: str
    priority: Priority
    effort: Effort
    activities: tuple[str, ...]
    link: str | None = None


@dataclass(frozen=True)
class StudyPlan:
    topics: tuple[StudyTopic, ...]
    days_left: int | None = None
    schedule_note: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)


def _learn(name: str, essential: bool) -> StudyTopic:
    return StudyTopic(
        f"learn:{name}", f"Learn the essentials of {name}",
        ("The job states it as essential" if essential else "The job lists it as required")
        + " and your CV does not show it.",
        "High" if essential else "Medium", "Long",
        (f"Work through the core concepts of {name}, starting from the official documentation.",
         f"Do a small hands-on exercise with {name} so you can talk about it from experience.",
         "Prepare an honest answer: what you know now, related experience and how you are learning it."),
        OFFICIAL_DOCS.get(name),
    )


def build_study_plan(result: MatchResult, improvements: ImprovementPlan, interview_on: date | None = None,
                     today: date | None = None) -> StudyPlan:
    topics: list[StudyTopic] = []
    for s in improvements.skills:
        if s.evidence == "not found" and (s.essential or s.required):
            topics.append(_learn(s.name, s.essential))
    for s in improvements.skills:
        if s.evidence == "listed only" and s.required:
            topics.append(StudyTopic(
                f"example:{s.name}", f"Prepare a worked example using {s.name}",
                "Your CV lists it but does not show where you used it, so expect detailed questions.", "Medium",
                "Short", (f"Pick one real piece of work where you used {s.name}.",
                          "Note the problem, what you did, and the result you can evidence.",
                          f"Refresh the parts of {s.name} that work relied on."),
                OFFICIAL_DOCS.get(s.name)))
    resp = next((c for c in result.components if c.key == "responsibilities"), None)
    if resp and resp.assessed:
        for i, gap in enumerate(resp.gaps[:3]):
            text = gap.removeprefix("Not clearly reflected: ").rstrip(".")
            topics.append(StudyTopic(
                f"resp:{i}", f"Prepare for: {text}",
                "This responsibility is not clearly reflected in your CV.", "Medium", "Medium",
                ("Find related work you have done and prepare a STAR story about it.",
                 "If you have not done it, think through how you would approach it in your first months.")))
    for s in improvements.skills:
        if s.evidence == "not found" and not s.required:
            topics.append(StudyTopic(
                f"preferred:{s.name}", f"Optional: get familiar with {s.name}",
                "Preferred by the job, not required.", "Low", "Medium",
                (f"Learn what {s.name} is used for and how it relates to your experience.",), OFFICIAL_DOCS.get(s.name)))
    topics.append(StudyTopic(
        "practice", "Practise your answers out loud",
        "Practised answers are clearer and shorter under pressure.", "Medium", "Short",
        ("Answer the Very likely questions out loud, ideally recorded or with a friend.",
         "Keep each answer to about two minutes.")))
    topics.sort(key=lambda t: _PRIORITY_ORDER[t.priority])

    days_left = note = None
    if interview_on:
        days_left = (interview_on - (today or date.today())).days
        high = sum(t.priority == "High" for t in topics)
        if days_left < 0:
            note = "The interview date is in the past."
        elif days_left <= 2:
            note = ("Little time left: focus on preparing honest answers and examples rather than learning new "
                    "skills in depth.")
        else:
            note = (f"{days_left} days left. Start with the {high} high-priority topic(s), then work down the list."
                    if high else f"{days_left} days left. Work down the list in order.")
    return StudyPlan(tuple(topics), days_left, note)


def progress(statuses: dict[str, Status], plan: StudyPlan) -> tuple[int, int]:
    """(prepared, total) for the topics in this plan."""
    return sum(statuses.get(t.id) == "Prepared" for t in plan.topics), len(plan.topics)
