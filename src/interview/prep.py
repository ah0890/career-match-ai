"""Interview preparation for a specific job, built from the job description and the CV.

Questions are predictions of what an interviewer is likely to explore, derived from the
job's stated requirements. Each one shows why it is likely and which parts of the CV the
candidate can draw on. Answers are never written for the candidate: the plan gives a
structure (STAR) and points at their own material.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from src.company.models import CompanyProfile
from src.company.relevance import same_company
from src.cv.parsing import bullet_lines
from src.matching.engine import MatchProfile, MatchResult
from src.matching.skills import extract_skills
from src.matching.text import content_stems

Kind = Literal["Technical", "Behavioural", "Role", "Gap", "Company", "Motivation"]
Likelihood = Literal["Very likely", "Likely", "Possible"]

PREP_DISCLAIMER = (
    "These questions are predictions based on the job description, not the employer's actual questions. "
    "Prepare answers from your own experience; never claim experience you do not have."
)
STAR_PROMPT = ("Situation — where and when? Task — what was your responsibility? Action — what did you do "
               "yourself? Result — what changed, ideally with a number you can stand behind?")
_LIKELIHOOD_ORDER = {"Very likely": 0, "Likely": 1, "Possible": 2}
_MAX_EVIDENCE = 2
_MAX_SKILL_QUESTIONS = 8
_MAX_RESPONSIBILITY_QUESTIONS = 4


@dataclass(frozen=True)
class Question:
    kind: Kind
    likelihood: Likelihood
    text: str
    why: str  # why this is likely to come up, quoting the job where possible
    cv_material: tuple[str, ...]  # CV lines the candidate can draw on
    guidance: str


@dataclass(frozen=True)
class PrepPlan:
    job_title: str
    company: str | None
    questions: tuple[Question, ...]
    questions_to_ask: tuple[str, ...]
    checklist: tuple[str, ...]
    disclaimer: str = PREP_DISCLAIMER
    notes: tuple[str, ...] = field(default_factory=tuple)

    def by_kind(self, kind: Kind) -> tuple[Question, ...]:
        return tuple(q for q in self.questions if q.kind == kind)


def _cv_lines(profile: MatchProfile) -> list[str]:
    lines = bullet_lines(profile.text)
    if lines:
        return lines
    exp = profile.parsed.section("experience")  # CVs written without bullets: use experience lines
    return [ln.strip() for ln in (exp.text if exp else "").split("\n") if len(ln.split()) >= 5]


def _material(lines: list[str], topic: str, skill: str | None = None) -> tuple[str, ...]:
    """The CV lines that share the most meaningful words with a topic (or mention the skill by any alias)."""
    wanted = set(content_stems(topic))
    if not wanted and not skill:
        return ()
    scored = []
    for line in lines:
        overlap = len(wanted & set(content_stems(line))) + (3 if topic.lower() in line.lower() else 0)
        if skill and any(m.name == skill for m in extract_skills(line)):
            overlap += 5
        if overlap:
            scored.append((overlap, line))
    scored.sort(key=lambda x: -x[0])
    return tuple(line for _, line in scored[:_MAX_EVIDENCE])


_SKILL_TEMPLATES = {
    "technical": "Walk me through a piece of work where you used {s}. What was your part, and what was the result?",
    "tool": "How have you used {s} in your work? Give a specific example and what it achieved.",
    "methodology": "Take us through how you applied {s} on a real problem, step by step.",
    "domain": "What experience do you have with {s}, and how has it shaped the way you work?",
    "soft": "Tell me about a time you demonstrated {s}. What happened?",
}


def _skill_questions(result: MatchResult, lines: list[str]) -> list[Question]:
    out = []
    # Skills the CV shows, plus soft skills (a behavioural question works whether or not the CV names them).
    skills = [s for s in result.requirements.skills if s.category != "language"
              and (s.name in result.matched_skills or s.category == "soft")]
    skills.sort(key=lambda s: (not s.mandatory, not s.required))
    for s in skills[:_MAX_SKILL_QUESTIONS]:
        kind: Kind = "Behavioural" if s.category == "soft" else "Technical"
        likelihood: Likelihood = "Very likely" if s.mandatory or s.required else "Possible"
        why = (f"The job {'states it as essential' if s.mandatory else 'asks for it' if s.required else 'lists it as preferred'}"
               + (f": “{s.evidence}”" if s.evidence else " (from the source's tags)."))
        out.append(Question(kind, likelihood, _SKILL_TEMPLATES.get(s.category, _SKILL_TEMPLATES["technical"]).format(s=s.name),
                            why, _material(lines, s.name, s.name),
                            STAR_PROMPT if kind == "Behavioural" else
                            f"Pick one concrete example. Explain the problem, how you used {s.name}, the decisions you "
                            "made and the measurable outcome. Be ready for follow-up detail."))
    return out


def _responsibility_questions(result: MatchResult, lines: list[str]) -> list[Question]:
    out = []
    for r in result.requirements.responsibilities[:_MAX_RESPONSIBILITY_QUESTIONS]:
        material = _material(lines, r)
        out.append(Question(
            "Role", "Likely", f"This role involves: “{r.rstrip('.')}”. Tell me about a time you did something similar.",
            "It is listed among the job's responsibilities.", material,
            STAR_PROMPT if material else
            "Your CV has no clearly related line. If you have related experience, prepare an example; if not, explain "
            "how you would approach it and what you would learn first."))
    return out


def _gap_questions(result: MatchResult) -> list[Question]:
    out = []
    essential = {g.requirement for g in result.mandatory_gaps}
    for g in result.mandatory_gaps:
        out.append(Question(
            "Gap", "Very likely", f"The role requires {g.requirement}. What is your experience with it?",
            f"The job states it as essential (“{g.evidence}”) and your CV does not show it.", (),
            "If you have it, prepare a specific example and add it to your CV. If you do not, say so honestly, "
            "describe the closest related experience and how you would close the gap."))
    soft = {s.name for s in result.requirements.skills if s.category == "soft"}
    for name in result.missing_required_skills:
        if name in essential or name in soft:
            continue
        out.append(Question(
            "Gap", "Likely", f"How familiar are you with {name}?",
            "The job lists it as required and your CV does not mention it.", (),
            "Answer honestly. Mention related tools or methods you have used and how quickly you have learned "
            "similar things before."))
    exp = next((c for c in result.components if c.key == "experience"), None)
    if exp and exp.assessed and any("short of the stated" in g for g in exp.gaps):
        out.append(Question(
            "Gap", "Likely", "This role asks for more years of experience than your CV shows. Why are you ready for it?",
            next(g for g in exp.gaps if "short of the stated" in g), (),
            "Focus on the depth and relevance of what you have done, with concrete results, rather than the years."))
    return out


def _company_questions(result: MatchResult, company: CompanyProfile | None) -> tuple[list[Question], list[str]]:
    name = result.job.company or "this company"
    if company is None or not same_company(company.name, result.job.company):
        return [Question("Motivation", "Very likely", f"Why do you want to work at {name}?",
                         "Almost every interview asks it.", (),
                         "Research the company first (Company Intelligence) and connect what it does to your "
                         "experience and goals.")], ["Research the company on the Company Intelligence page."]
    facts = {f.label: f.value for f in company.facts}
    hooks = [f"{k.lower()}: {v}" for k, v in facts.items() if k in ("Industry", "Products", "Headquarters")]
    return [Question("Company", "Very likely", f"Why do you want to work at {company.name}?",
                     "Almost every interview asks it.", (),
                     "Connect the company's work to your own experience. Facts you can refer to (from Wikidata): "
                     + ("; ".join(hooks) if hooks else "none recorded — use the company's website") + ".")], []


def _questions_to_ask(result: MatchResult) -> tuple[str, ...]:
    qs = ["What would success look like in this role after the first six months?",
          "What are the biggest challenges the team is facing right now?",
          "How is the team organised, and who would I work with most closely?"]
    if result.requirements.responsibilities:
        qs.append(f"How much of the role is focused on “{result.requirements.responsibilities[0].rstrip('.')}”?")
    if result.check_yourself:
        qs.append("Can you confirm the requirements for "
                  + ", ".join(label.lower() for label, _ in result.check_yourself) + "?")
    qs.append("What are the next steps in the process?")
    return tuple(qs)


def build_prep_plan(profile: MatchProfile, result: MatchResult, company: CompanyProfile | None = None) -> PrepPlan:
    lines = _cv_lines(profile)
    company_qs, company_notes = _company_questions(result, company)
    summary = profile.parsed.section("summary")
    opening_material = ((" ".join(summary.text.split()),) if summary and summary.text.strip()
                        else _material(lines, result.job.title))
    opening = Question("Motivation", "Very likely", "Tell me about yourself.", "Most interviews start with it.",
                       opening_material,
                       "Two minutes: your current role, the experience most relevant to this job, and why you are "
                       "applying now.")
    questions = [opening, *company_qs, *_skill_questions(result, lines),
                 *_responsibility_questions(result, lines), *_gap_questions(result)]
    questions.sort(key=lambda q: _LIKELIHOOD_ORDER[q.likelihood])
    checklist = [
        "Re-read the full job description and the original listing.",
        "Prepare two or three STAR stories you can adapt to several questions.",
        "Check every number and date on your CV — you may be asked about any of them.",
        *company_notes,
    ]
    if result.mandatory_gaps or result.missing_required_skills:
        checklist.append("Decide how you will answer honestly about requirements your CV does not show.")
    notes = () if lines else ("No bullet points were found in your CV, so CV material could not be linked to "
                              "questions.",)
    return PrepPlan(result.job.title, result.job.company, tuple(questions), _questions_to_ask(result),
                    tuple(checklist), notes=notes)


def plan_markdown(plan: PrepPlan) -> str:
    """A plain Markdown export of the plan for offline use."""
    lines = [f"# Interview preparation: {plan.job_title}" + (f" at {plan.company}" if plan.company else ""), "",
             f"_{plan.disclaimer}_", ""]
    for q in plan.questions:
        lines += [f"## {q.text}", f"- **Type:** {q.kind} · **{q.likelihood}**", f"- **Why:** {q.why}"]
        lines += [f"- **From your CV:** {m}" for m in q.cv_material]
        lines += [f"- **How to prepare:** {q.guidance}", ""]
    lines += ["## Questions to ask", *[f"- {q}" for q in plan.questions_to_ask], "",
              "## Checklist", *[f"- [ ] {c}" for c in plan.checklist], ""]
    return "\n".join(lines)
