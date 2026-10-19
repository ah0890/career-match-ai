"""Extract structured requirements from a job description.

Everything here is read from the text the source provided. When a description has no
recognisable structure, requirements are still extracted but marked as less certain
(``structured=False``) so the match confidence can reflect it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from src.cv.ats import job_keywords
from src.jobs.models import JobPosting
from src.matching.education import DegreeLevel, DegreeMention, lowest_degree
from src.matching.skills import extract_skills
from src.matching.text import split_sentences

Context = Literal["required", "preferred", "responsibilities", "other"]

_HEADINGS: dict[Context, tuple[str, ...]] = {
    "required": (
        "requirements", "minimum requirements", "job requirements", "qualifications", "minimum qualifications",
        "required qualifications", "basic qualifications", "required skills", "must have", "must haves",
        "must-have", "must-haves", "what you'll need", "what you will need", "what you need", "what we need",
        "you have", "you should have", "who you are", "about you", "what we're looking for",
        "what we are looking for", "we're looking for", "skills and experience", "experience and skills",
        "skills & experience", "essential", "essential criteria", "essential skills", "key requirements",
        "your profile", "profile", "the ideal candidate", "candidate profile", "skills", "competencies",
    ),
    "preferred": (
        "nice to have", "nice to haves", "nice-to-have", "nice-to-haves", "preferred", "preferred qualifications",
        "preferred skills", "bonus", "bonus points", "bonus if you have", "desirable", "desirable criteria",
        "good to have", "it would be great if", "pluses", "additional qualifications", "extra credit",
    ),
    "responsibilities": (
        "responsibilities", "key responsibilities", "main responsibilities", "job responsibilities",
        "duties", "key duties", "main duties", "what you'll do", "what you will do", "what you'll be doing",
        "your role", "the role", "role overview", "in this role", "in this role you will", "day to day",
        "day-to-day", "your responsibilities", "your mission", "what the job involves", "job description",
        "your tasks", "tasks",
    ),
    "other": (
        "benefits", "perks", "what we offer", "we offer", "about us", "about the company", "who we are",
        "compensation", "salary", "how to apply", "our values", "why join us", "why us", "equal opportunity",
        "location", "about the team",
    ),
}
_HEADING_TO_CONTEXT = {h: ctx for ctx, hs in _HEADINGS.items() for h in hs}

_PREFERRED_CUE = re.compile(
    r"(?i)\b(?:preferred|preferably|nice[- ]to[- ]have|a plus|is a plus|an advantage|advantageous|bonus|desirable|"
    r"ideally|beneficial|good to have|would be great|not required|optional)\b")
_MANDATORY_CUE = re.compile(
    r"(?i)\b(?:must|required|requires|requirement|essential|mandatory|minimum|at least|need to have|"
    r"you will need|is needed|are needed|necessary)\b")
_YEARS_RE = re.compile(
    r"(?i)(?P<min>\d{1,2})\s*\+?\s*(?:(?:-|–|to)\s*(?P<max>\d{1,2})\s*\+?\s*)?(?:years?|yrs?)\b"
    r"(?P<tail>[^.;\n]{0,80})")
_YEARS_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                "nine": 9, "ten": 10}
_YEARS_WORD_RE = re.compile(rf"(?i)\b(?P<min>{'|'.join(_YEARS_WORDS)})\s*\+?\s*(?:years?)\b(?P<tail>[^.;\n]{{0,80}})")
_EQUIVALENT = re.compile(r"(?i)\bor\s+(?:an?\s+)?equivalent\b|\bequivalent\s+(?:practical\s+|work\s+)?experience\b")

# Requirements that a CV can rarely prove; surfaced for the user to check themselves.
_UNVERIFIABLE: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Right to work / work authorisation", re.compile(
        r"(?i)\b(?:right to work|work(?:ing)? (?:authori[sz]ation|permit)|authori[sz]ed to work|eligible to work|"
        r"visa sponsorship|sponsorship|citizenship|citizen)\b")),
    ("Security clearance", re.compile(r"(?i)\b(?:security clearance|clearance|background check|vetting)\b")),
    ("Driving licence", re.compile(r"(?i)\bdriv(?:er'?s|ing) licen[cs]e\b|\bvalid licen[cs]e\b")),
    ("Travel or relocation", re.compile(r"(?i)\b(?:willing(?:ness)? to (?:travel|relocate)|relocation|"
                                        r"travel (?:up to|required)|\d{1,2}\s?% travel)\b")),
    ("Working hours or shifts", re.compile(r"(?i)\b(?:shift work|night shifts?|weekend work|on-call|on call|"
                                           r"rotating shifts?)\b")),
)

_RESPONSIBILITY_START = re.compile(
    r"(?i)^(?:you will |you'll |will )?(?:lead|manage|develop|design|build|create|own|drive|deliver|support|"
    r"maintain|implement|coordinate|conduct|perform|analy[sz]e|monitor|ensure|prepare|review|collaborate|work|"
    r"partner|define|improve|oversee|plan|report|write|test|deploy|operate|run|handle|identify|investigate|"
    r"establish|execute|mentor|train|communicate|present|negotiate|evaluate|assess|optimi[sz]e|automate|"
    r"track|liaise|organi[sz]e|supervise|participate|contribute|provide|act|serve|resolve|research)\b")


@dataclass(frozen=True)
class SkillRequirement:
    name: str
    category: str
    required: bool  # False = preferred / nice to have
    mandatory: bool  # stated with "must", "essential", "required" …
    evidence: str  # the sentence it was found in ("" when it came only from the source's tags)


@dataclass(frozen=True)
class ExperienceRequirement:
    min_years: int
    max_years: int | None
    required: bool
    mandatory: bool
    evidence: str


@dataclass(frozen=True)
class EducationRequirement:
    level: DegreeLevel
    required: bool
    mandatory: bool
    allows_equivalent: bool  # "or equivalent experience"
    evidence: str


@dataclass(frozen=True)
class JobRequirements:
    skills: tuple[SkillRequirement, ...]
    experience: ExperienceRequirement | None
    education: EducationRequirement | None
    responsibilities: tuple[str, ...]
    keywords: tuple[str, ...]
    unverifiable: tuple[tuple[str, str], ...]  # (requirement, evidence sentence)
    structured: bool  # recognisable requirement/responsibility headings were found
    word_count: int
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def required_skills(self) -> tuple[SkillRequirement, ...]:
        return tuple(s for s in self.skills if s.required)

    @property
    def preferred_skills(self) -> tuple[SkillRequirement, ...]:
        return tuple(s for s in self.skills if not s.required)


def _heading_context(line: str) -> Context | None:
    raw = line.strip().strip("#*:-–—|•").strip()
    if not raw or len(raw) > 60 or len(raw.split()) > 8:
        return None
    norm = re.sub(r"\s+", " ", raw.lower().replace("’", "'")).rstrip(":?!. ")
    norm = re.sub(r"\s*\((?:optional|required)\)$", "", norm)
    return _HEADING_TO_CONTEXT.get(norm)


@dataclass(frozen=True)
class _Sentence:
    text: str
    context: Context


def _classified_sentences(description: str) -> tuple[list[_Sentence], bool]:
    sentences: list[_Sentence] = []
    context: Context = "other"
    structured = False
    for line in description.split("\n"):
        heading = _heading_context(line)
        if heading is not None:
            context = heading
            structured = structured or heading != "other"
            continue
        for s in split_sentences(line):
            sentences.append(_Sentence(s, context))
    return sentences, structured


def _is_preferred(s: _Sentence) -> bool:
    return s.context == "preferred" or bool(_PREFERRED_CUE.search(s.text))


def _is_mandatory(s: _Sentence) -> bool:
    return not _is_preferred(s) and bool(_MANDATORY_CUE.search(s.text))


def _extract_skills(sentences: list[_Sentence], job: JobPosting) -> list[SkillRequirement]:
    mentions: dict[str, list[_Sentence]] = {}
    categories: dict[str, str] = {}
    for s in sentences:
        if s.context == "other" and any(x.context != "other" for x in sentences):
            continue  # benefits / "about us" text describes the employer, not the role
        for m in extract_skills(s.text):
            mentions.setdefault(m.name, []).append(s)
            categories[m.name] = m.category
    out = [
        SkillRequirement(
            name=name, category=categories[name],
            required=not all(_is_preferred(s) for s in ss),
            mandatory=any(_is_mandatory(s) for s in ss),
            evidence=next((s.text for s in ss if not _is_preferred(s)), ss[0].text),
        )
        for name, ss in mentions.items()
    ]
    # Source tags (e.g. "python", "sql") count as required skills when the text does not mention them.
    seen = set(mentions)
    for m in extract_skills(", ".join(job.tags)):
        if m.name not in seen:
            seen.add(m.name)
            out.append(SkillRequirement(m.name, m.category, True, False, ""))
    return out


def _years_from(text: str) -> tuple[int, int | None] | None:
    for regex in (_YEARS_RE, _YEARS_WORD_RE):
        for m in regex.finditer(text):
            tail = m.group("tail").lower()
            head = text[max(0, m.start() - 40):m.start()].lower()
            if "experience" not in tail and "experience" not in head:
                continue
            raw_min = m.group("min").lower()
            lo = _YEARS_WORDS.get(raw_min) or int(raw_min)
            hi = int(m.group("max")) if regex is _YEARS_RE and m.group("max") else None
            if 0 < lo <= 30 and (hi is None or hi >= lo):
                return lo, hi
    return None


def _extract_experience(sentences: list[_Sentence]) -> ExperienceRequirement | None:
    candidates: list[ExperienceRequirement] = []
    for s in sentences:
        found = _years_from(s.text)
        if found:
            candidates.append(ExperienceRequirement(found[0], found[1], not _is_preferred(s), _is_mandatory(s), s.text))
    if not candidates:
        return None
    required = [c for c in candidates if c.required]
    # The headline requirement is the smallest required minimum (later lines are often about one tool).
    pool = required or candidates
    return min(pool, key=lambda c: c.min_years)


def _extract_education(sentences: list[_Sentence]) -> EducationRequirement | None:
    candidates: list[tuple[DegreeMention, _Sentence]] = []
    for s in sentences:
        if s.context == "other" and any(x.context != "other" for x in sentences):
            continue
        mention = lowest_degree(s.text)
        if mention is not None and mention.level is not DegreeLevel.NONE:
            candidates.append((mention, s))
    if not candidates:
        return None
    required = [(m, s) for m, s in candidates if not _is_preferred(s)]
    pool = required or candidates
    mention, s = min(pool, key=lambda ms: ms[0].level)
    return EducationRequirement(mention.level, not _is_preferred(s), _is_mandatory(s),
                                bool(_EQUIVALENT.search(s.text)), s.text)


def _extract_responsibilities(sentences: list[_Sentence], structured: bool) -> list[str]:
    if structured and any(s.context == "responsibilities" for s in sentences):
        items = [s.text for s in sentences if s.context == "responsibilities"]
    else:
        items = [s.text for s in sentences if s.context in ("other", "responsibilities")
                 and _RESPONSIBILITY_START.match(s.text)]
    return [i for i in dict.fromkeys(items) if 3 <= len(i.split()) <= 60][:20]


def extract_requirements(job: JobPosting) -> JobRequirements:
    description = job.description or ""
    sentences, structured = _classified_sentences(description)
    skills = _extract_skills(sentences, job)
    skill_lower = {s.name.lower() for s in skills}
    # In a structured ad, benefits and "about us" text says nothing about the role itself.
    role_text = "\n".join(s.text for s in sentences if s.context != "other") if structured else description
    keywords = tuple(k for k in job_keywords(f"{job.title}\n{role_text}") if k not in skill_lower)
    unverifiable: list[tuple[str, str]] = []
    for label, pattern in _UNVERIFIABLE:
        hit = next((s.text for s in sentences if pattern.search(s.text)), None)
        if hit:
            unverifiable.append((label, hit))
    words = len(description.split())
    notes = []
    if words < 80:
        notes.append("The source provided only a short description, so some requirements may be missing.")
    elif not structured:
        notes.append("The description has no recognisable requirement sections, so required and preferred items "
                     "could not always be told apart.")
    return JobRequirements(
        skills=tuple(skills),
        experience=_extract_experience(sentences),
        education=_extract_education(sentences),
        responsibilities=tuple(_extract_responsibilities(sentences, structured)),
        keywords=keywords,
        unverifiable=tuple(unverifiable),
        structured=structured,
        word_count=words,
        notes=tuple(notes),
    )
