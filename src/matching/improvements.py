"""Job-specific CV improvement plan: skill evidence, keyword gaps and bullet-level tips.

Every suggestion points at something the job asks for and the CV does not yet show
clearly. Suggestions never supply content: they ask the candidate to state what they
genuinely have, in their own words. Nothing here invents skills, numbers or achievements.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from src.cv.parsing import ACTION_VERBS, bullet_lines
from src.matching.engine import MatchProfile, MatchResult
from src.matching.skills import extract_skills
from src.matching.text import content_stems, split_sentences, stem

Evidence = Literal["shown in experience", "shown in education", "listed only", "not found"]
Priority = Literal["High", "Medium", "Low"]

IMPROVEMENT_NOTE = (
    "Only add what is true. These suggestions point at what this job asks for; they never replace your own "
    "experience, and recruiters may ask about anything on your CV."
)
_EXPERIENCE_SECTIONS = ("experience", "projects", "volunteering")
_EDUCATION_SECTIONS = ("education", "certifications")
_QUANTIFIED = re.compile(r"\d|%|percent", re.I)
_FIRST_PERSON = re.compile(r"\b(I|me|my)\b")
_PRIORITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}
_MAX_BULLETS = 5
_LONG_BULLET_WORDS = 35


@dataclass(frozen=True)
class SkillEvidence:
    name: str
    required: bool
    essential: bool
    evidence: Evidence
    job_says: str  # the job sentence that mentions it ("" when it came from the source's tags)


@dataclass(frozen=True)
class KeywordGap:
    keyword: str
    job_says: str


@dataclass(frozen=True)
class BulletTip:
    bullet: str
    related_to: tuple[str, ...]  # job skills/terms this bullet already touches
    tips: tuple[str, ...]


@dataclass(frozen=True)
class Suggestion:
    priority: Priority
    title: str
    detail: str
    where: str  # CV section the change belongs in


@dataclass(frozen=True)
class ImprovementPlan:
    skills: tuple[SkillEvidence, ...]
    keyword_gaps: tuple[KeywordGap, ...]
    bullet_tips: tuple[BulletTip, ...]
    suggestions: tuple[Suggestion, ...]
    note: str = IMPROVEMENT_NOTE

    def count(self, evidence: Evidence) -> int:
        return sum(s.evidence == evidence for s in self.skills)


def _section_skills(profile: MatchProfile, keys: tuple[str, ...]) -> set[str]:
    text = "\n".join(s.text for s in profile.parsed.sections if s.key in keys)
    return {m.name for m in extract_skills(text)} if text else set()


def _skills_by_place(profile: MatchProfile) -> tuple[set[str], set[str]]:
    """Skill names found in experience-type sections, and anywhere in the CV."""
    parsed = profile.parsed
    sections = [s for s in parsed.sections if s.key in _EXPERIENCE_SECTIONS]
    text = "\n".join(s.text for s in sections) if sections else ""
    in_experience = {m.name for m in extract_skills(text)} if text else set()
    if not sections:  # no recognised sections: anything in a bullet counts as shown in use
        in_experience = {m.name for m in extract_skills("\n".join(bullet_lines(profile.text)))}
    return in_experience, set(profile.skills)


def _skill_evidence(profile: MatchProfile, result: MatchResult) -> list[SkillEvidence]:
    in_experience, anywhere = _skills_by_place(profile)
    in_education = _section_skills(profile, _EDUCATION_SECTIONS)
    out = []
    for s in result.requirements.skills:
        evidence: Evidence = ("shown in experience" if s.name in in_experience
                              else "shown in education" if s.name in in_education
                              else "listed only" if s.name in anywhere else "not found")
        out.append(SkillEvidence(s.name, s.required, s.mandatory, evidence, s.evidence))
    order = {"not found": 0, "listed only": 1, "shown in education": 2, "shown in experience": 3}
    return sorted(out, key=lambda e: (order[e.evidence], not e.essential, not e.required))


def _keyword_gaps(profile: MatchProfile, result: MatchResult) -> list[KeywordGap]:
    sentences = split_sentences(result.job.description)
    lower = profile.text.lower()
    gaps = []
    for k in result.requirements.keywords:
        if stem(k) in profile.stems or k in lower:
            continue
        said = next((s for s in sentences if re.search(rf"\b{re.escape(k)}", s, re.I)), "")
        gaps.append(KeywordGap(k, said))
    return gaps


def _job_terms(result: MatchResult) -> dict[str, str]:
    """Stems of what the job cares about → a readable label."""
    req = result.requirements
    terms: dict[str, str] = {}
    for s in req.skills:
        for st in content_stems(s.name):
            terms.setdefault(st, s.name)
    for k in req.keywords:
        terms.setdefault(stem(k), k)
    for r in req.responsibilities:
        for st in content_stems(r):
            terms.setdefault(st, st)
    return terms


def _bullet_tips(profile: MatchProfile, result: MatchResult) -> list[BulletTip]:
    terms = _job_terms(result)
    skill_names = {s.name for s in result.requirements.skills}
    scored = []
    for bullet in bullet_lines(profile.text):
        stems_ = content_stems(bullet)
        hits = [terms[s] for s in stems_ if s in terms]
        named = [m.name for m in extract_skills(bullet) if m.name in skill_names]
        related = tuple(dict.fromkeys([*named, *(h for h in hits if h in skill_names or h in result.requirements.keywords)]))
        relevance = len(set(hits)) + 2 * len(named)
        if relevance:
            scored.append((relevance, bullet, related))
    scored.sort(key=lambda x: -x[0])
    tips_out = []
    for _, bullet, related in scored[:_MAX_BULLETS]:
        tips = []
        words = bullet.split()
        first = re.sub(r"[^a-z]", "", words[0].lower()) if words else ""
        if not _QUANTIFIED.search(bullet):
            tips.append("Add a measurable result if you have one — scale, frequency, time or cost saved, or a "
                        "percentage. Use only figures you can stand behind.")
        if first not in ACTION_VERBS:
            tips.append("Start with an action verb that says what you did (for example Led, Built, Reduced).")
        if _FIRST_PERSON.search(bullet):
            tips.append("Remove “I”/“my”; start with the action instead.")
        if len(words) > _LONG_BULLET_WORDS:
            tips.append(f"Shorten it ({len(words)} words); split it into two bullets if it covers two things.")
        if tips:
            tips_out.append(BulletTip(bullet, related, tuple(tips)))
    return tips_out


def _title_words(title: str) -> list[str]:
    noise = {"senior", "junior", "lead", "principal", "staff", "remote", "hybrid", "contract", "intern"}
    return [w for w in re.findall(r"[A-Za-z][A-Za-z+#]*", title) if w.lower() not in noise and len(w) > 2]


def _suggestions(profile: MatchProfile, result: MatchResult, skills: list[SkillEvidence],
                 keyword_gaps: list[KeywordGap]) -> list[Suggestion]:
    out: list[Suggestion] = []
    for s in skills:
        if s.evidence == "not found" and (s.essential or s.required):
            out.append(Suggestion(
                "High" if s.essential else "Medium", f"{s.name}: not found in your CV",
                ("The job states it as essential. " if s.essential else "The job lists it as required. ")
                + "If you have it, add it to your Skills section and name it in the role where you used it.",
                "Skills and Experience"))
    listed = [s.name for s in skills if s.evidence == "listed only" and s.required]
    if listed:
        out.append(Suggestion(
            "Medium", "Show where you used skills you only list",
            f"{', '.join(listed)} appear in your CV but not in any role. Recruiters look for evidence of use: name "
            "the skill in the bullet that describes the work.", "Experience"))
    preferred_missing = [s.name for s in skills if s.evidence == "not found" and not s.required]
    if preferred_missing:
        out.append(Suggestion("Low", "Preferred skills not found",
                              f"{', '.join(preferred_missing)}. Add any you genuinely have; they are not required.",
                              "Skills"))
    if keyword_gaps:
        out.append(Suggestion(
            "Low", "Use the job's own terms where they are accurate",
            "The job repeats terms your CV does not use: " + ", ".join(k.keyword for k in keyword_gaps[:8])
            + ". Where you have done the same thing under another name, consider the job's wording.",
            "Summary and Experience"))
    summary = profile.parsed.section("summary")
    title_words = _title_words(result.job.title)
    if summary is None or not summary.text.strip():
        out.append(Suggestion("Low", "Add a short summary for this kind of role",
                              "Two or three lines on your experience and the role you are targeting help a reader "
                              "see the fit quickly.", "Summary"))
    elif title_words and not any(stem(w.lower()) in content_stems(summary.text) for w in title_words):
        out.append(Suggestion("Low", "Mention the target role in your summary",
                              f"Your summary does not mention “{' '.join(title_words)}”. If it describes the role "
                              "you want, say so.", "Summary"))
    out.sort(key=lambda s: _PRIORITY_ORDER[s.priority])
    return out


def improvement_plan(profile: MatchProfile, result: MatchResult) -> ImprovementPlan:
    skills = _skill_evidence(profile, result)
    keyword_gaps = _keyword_gaps(profile, result)
    return ImprovementPlan(
        skills=tuple(skills),
        keyword_gaps=tuple(keyword_gaps),
        bullet_tips=tuple(_bullet_tips(profile, result)),
        suggestions=tuple(_suggestions(profile, result, skills, keyword_gaps)),
    )
