"""Heuristic CV parsing: sections, contact details, dates, skills and bullet statistics.

The parser tolerates missing headings and unusual layouts. It separates facts that
were found in the text from inferences (marked ``uncertain``). A field that is not
found means only that it was not detected in the CV text — never that the candidate
lacks it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from src.matching.skills import SkillMatch, extract_skills

# --- Section headings ------------------------------------------------------

SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "summary": ("summary", "professional summary", "profile", "professional profile", "career summary",
                "objective", "career objective", "about me", "personal statement", "executive summary",
                "career profile", "overview"),
    "experience": ("experience", "work experience", "professional experience", "employment history",
                   "employment", "work history", "career history", "relevant experience",
                   "professional background", "career experience", "experience summary"),
    "education": ("education", "education and training", "academic background", "academic qualifications",
                  "qualifications", "educational background", "education & training", "academic history"),
    "skills": ("skills", "technical skills", "key skills", "core skills", "core competencies", "competencies",
               "areas of expertise", "expertise", "skills and abilities", "skills & competencies",
               "technical competencies", "tools and technologies", "technologies", "skills summary",
               "it skills", "computer skills"),
    "certifications": ("certifications", "certificates", "licenses", "licences", "certifications and licenses",
                       "professional certifications", "accreditations", "licenses and certifications",
                       "training and certifications", "courses", "training"),
    "projects": ("projects", "key projects", "selected projects", "project experience", "personal projects",
                 "academic projects"),
    "publications": ("publications", "research", "research and publications", "papers"),
    "languages": ("languages", "language skills", "language proficiency"),
    "awards": ("awards", "honors", "honours", "achievements", "awards and honors", "key achievements",
               "accomplishments"),
    "volunteering": ("volunteering", "volunteer experience", "volunteer work", "community involvement"),
    "memberships": ("memberships", "professional memberships", "affiliations", "professional affiliations"),
    "interests": ("interests", "hobbies", "hobbies and interests"),
    "references": ("references", "referees"),
    "personal": ("personal details", "personal information", "contact", "contact information",
                 "contact details"),
}
_ALIAS_TO_SECTION = {alias: name for name, aliases in SECTION_ALIASES.items() for alias in aliases}

SECTION_LABELS = {
    "summary": "Summary", "experience": "Experience", "education": "Education", "skills": "Skills",
    "certifications": "Certifications", "projects": "Projects", "publications": "Publications",
    "languages": "Languages", "awards": "Awards", "volunteering": "Volunteering",
    "memberships": "Memberships", "interests": "Interests", "references": "References",
    "personal": "Personal details",
}


def _normalise_heading(line: str) -> str:
    line = line.strip().strip(":-–—|•*#").strip()
    return re.sub(r"\s+", " ", line).lower()


def _lookup_heading(norm: str) -> str | None:
    for variant in (norm, norm.replace("&", "and"), norm.replace(" and ", " & ")):
        if variant in _ALIAS_TO_SECTION:
            return _ALIAS_TO_SECTION[variant]
    return None


def match_heading(line: str) -> str | None:
    """Return the canonical section for a heading line, or None."""
    raw = line.strip()
    if not raw or len(raw) > 45 or len(raw.split()) > 5:
        return None
    if raw.endswith((".", ",")) or re.search(r"\d{3,}|@", raw):
        return None
    return _lookup_heading(_normalise_heading(raw))


def looks_like_heading(line: str) -> bool:
    """A short all-caps line that is probably a heading even if it is not a standard one."""
    raw = line.strip()
    letters = [c for c in raw if c.isalpha()]
    return (
        3 <= len(raw) <= 40 and len(raw.split()) <= 5 and len(letters) >= 3
        and all(c.isupper() for c in letters) and not re.search(r"[@\d]", raw)
    )


# --- Contact details -------------------------------------------------------

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)")
URL_RE = re.compile(r"(?:https?://|www\.)[^\s|,;]+|(?:linkedin\.com|github\.com)/[^\s|,;]+", re.I)


def _valid_phone(candidate: str) -> bool:
    digits = re.sub(r"\D", "", candidate)
    if not 8 <= len(digits) <= 15:
        return False
    # Exclude date ranges such as "2015 - 2019" or "01.2015 - 12.2019".
    return not re.fullmatch(r"\s*(?:\d{1,2}[./])?\d{4}\s*[-–]\s*(?:\d{1,2}[./])?\d{4}\s*", candidate)


@dataclass(frozen=True)
class ContactInfo:
    emails: tuple[str, ...] = ()
    phones: tuple[str, ...] = ()
    links: tuple[str, ...] = ()


def extract_contact(text: str) -> ContactInfo:
    head = text[:1500]  # contact details are expected near the top; avoids picking up referees
    emails = tuple(dict.fromkeys(EMAIL_RE.findall(head)))
    phones = tuple(dict.fromkeys(p.strip() for p in PHONE_RE.findall(head) if _valid_phone(p)))
    links = tuple(dict.fromkeys(u.rstrip(".") for u in URL_RE.findall(text) if "@" not in u))
    return ContactInfo(emails, phones, links)


# --- Dates -----------------------------------------------------------------

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_NAME = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_DATE = rf"(?:{_MONTH_NAME}\.?\s+\d{{4}}|\d{{1,2}}[/.-]\d{{4}}|\d{{4}}[/.-]\d{{1,2}}|\d{{4}})"
_PRESENT = r"(?:present|current|now|today|date|ongoing)"
DATE_RANGE_RE = re.compile(rf"(?P<start>{_DATE})\s*(?:-|–|—|to|until|till)\s*(?P<end>{_DATE}|{_PRESENT})", re.I)


@dataclass(frozen=True)
class DateRange:
    raw: str
    start: date
    end: date
    is_current: bool
    style: str  # "month-name", "numeric", "year-only"


def _parse_date(token: str, *, end: bool) -> tuple[date, str] | None:
    t = token.strip().lower().rstrip(".")
    m = re.fullmatch(rf"({_MONTH_NAME})\.?\s+(\d{{4}})", t)
    if m:
        month = _MONTHS[m.group(1)[:4] if m.group(1).startswith("sept") else m.group(1)[:3]]
        return date(int(m.group(2)), month, 1), "month-name"
    m = re.fullmatch(r"(\d{1,2})[/.-](\d{4})", t)
    if m and 1 <= int(m.group(1)) <= 12:
        return date(int(m.group(2)), int(m.group(1)), 1), "numeric"
    m = re.fullmatch(r"(\d{4})[/.-](\d{1,2})", t)
    if m and 1 <= int(m.group(2)) <= 12:
        return date(int(m.group(1)), int(m.group(2)), 1), "numeric"
    if re.fullmatch(r"\d{4}", t):
        return date(int(t), 12 if end else 1, 1), "year-only"
    return None


def extract_date_ranges(text: str, today: date | None = None) -> list[DateRange]:
    today = today or date.today()
    ranges = []
    for m in DATE_RANGE_RE.finditer(text):
        start = _parse_date(m.group("start"), end=False)
        if start is None:
            continue
        end_raw = m.group("end")
        if re.fullmatch(_PRESENT, end_raw.strip(), re.I):
            end_date, current, end_style = today.replace(day=1), True, start[1]
        else:
            parsed = _parse_date(end_raw, end=True)
            if parsed is None:
                continue
            end_date, end_style = parsed
            current = False
        if not (1950 <= start[0].year <= today.year + 1) or end_date < start[0]:
            continue
        style = start[1] if start[1] == end_style or current else "mixed"
        ranges.append(DateRange(m.group(0), start[0], end_date, current, style))
    return ranges


def estimate_experience_years(ranges: list[DateRange]) -> float:
    """Total months covered by the union of date ranges, in years (overlaps counted once)."""
    if not ranges:
        return 0.0
    spans = sorted((r.start.year * 12 + r.start.month, r.end.year * 12 + r.end.month) for r in ranges)
    total, cur_s, cur_e = 0, spans[0][0], spans[0][1]
    for s, e in spans[1:]:
        if s <= cur_e:
            cur_e = max(cur_e, e)
        else:
            total += cur_e - cur_s + 1
            cur_s, cur_e = s, e
    total += cur_e - cur_s + 1
    return round(total / 12, 1)


# --- Bullets ---------------------------------------------------------------

ACTION_VERBS = frozenset("""
achieved accelerated administered advised analysed analyzed architected assessed audited automated
built calibrated championed coached collaborated commissioned completed conducted consolidated
coordinated created cut decreased defined delivered deployed designed developed devised directed
drove eliminated enabled engineered enhanced established evaluated executed expanded facilitated
forecasted formulated generated grew guided headed identified implemented improved increased initiated
inspected installed instituted integrated introduced investigated launched led maintained managed
mentored migrated modernised modernized monitored negotiated optimised optimized orchestrated organised
organized overhauled oversaw partnered performed pioneered planned prepared presented prioritised
prioritized produced programmed promoted proposed published raised reduced redesigned refactored
reorganised reorganized replaced resolved restructured revamped reviewed saved scaled secured
simplified spearheaded standardised standardized streamlined strengthened supervised supported
surpassed tested trained transformed troubleshot upgraded validated won wrote
""".split())

_FIRST_PERSON_RE = re.compile(r"\b(I|me|my|mine|myself)\b")
_QUANTIFIED_RE = re.compile(r"\d+(?:[.,]\d+)?\s*(?:%|percent|k\b|m\b|million|billion|x\b)|[$€£¥]\s?\d|\b\d{2,}\b", re.I)


@dataclass(frozen=True)
class BulletStats:
    total: int
    action_verb: int
    quantified: int
    first_person: int
    too_long: int  # more than 40 words
    average_words: float


def bullet_lines(text: str) -> list[str]:
    return [line[2:].strip() for line in text.split("\n") if line.startswith("- ") and len(line) > 3]


def analyse_bullets(bullets: list[str]) -> BulletStats:
    if not bullets:
        return BulletStats(0, 0, 0, 0, 0, 0.0)
    words = [len(b.split()) for b in bullets]
    first_words = [re.sub(r"[^a-z]", "", b.split()[0].lower()) if b.split() else "" for b in bullets]
    return BulletStats(
        total=len(bullets),
        action_verb=sum(w in ACTION_VERBS for w in first_words),
        quantified=sum(bool(_QUANTIFIED_RE.search(b)) for b in bullets),
        first_person=sum(bool(_FIRST_PERSON_RE.search(b)) for b in bullets),
        too_long=sum(w > 40 for w in words),
        average_words=round(sum(words) / len(words), 1),
    )


# --- Parsed CV -------------------------------------------------------------

@dataclass(frozen=True)
class Section:
    key: str
    heading: str
    text: str


@dataclass(frozen=True)
class ParsedCV:
    sections: tuple[Section, ...]
    unrecognised_headings: tuple[str, ...]
    contact: ContactInfo
    name_guess: str | None  # inference — shown as uncertain
    date_ranges: tuple[DateRange, ...]
    experience_years_estimate: float  # inference from date ranges
    skills: tuple[SkillMatch, ...]
    bullets: BulletStats
    word_count: int
    preamble: str = ""  # text before the first recognised heading
    notes: tuple[str, ...] = field(default_factory=tuple)

    def section(self, key: str) -> Section | None:
        return next((s for s in self.sections if s.key == key), None)

    def has(self, key: str) -> bool:
        s = self.section(key)
        return s is not None and bool(s.text.strip())

    @property
    def section_keys(self) -> tuple[str, ...]:
        return tuple(s.key for s in self.sections)


def _guess_name(preamble_lines: list[str]) -> str | None:
    for line in preamble_lines[:3]:
        candidate = line.strip()
        words = candidate.split()
        if (
            2 <= len(words) <= 4 and len(candidate) <= 40 and not re.search(r"[\d@|/:]", candidate)
            and all(w[0].isupper() for w in words if w[0].isalpha())
            and match_heading(candidate) is None
        ):
            return candidate.title() if candidate.isupper() else candidate
    return None


def split_sections(text: str) -> tuple[str, list[Section], list[str]]:
    lines = text.split("\n")
    preamble: list[str] = []
    sections: list[Section] = []
    unrecognised: list[str] = []
    current_key: str | None = None
    current_heading = ""
    buffer: list[str] = []

    def flush() -> None:
        if current_key is not None:
            sections.append(Section(current_key, current_heading, "\n".join(buffer).strip()))

    for line in lines:
        key = match_heading(line)
        if key is not None:
            flush()
            current_key, current_heading, buffer = key, line.strip(), []
            continue
        if looks_like_heading(line):
            unrecognised.append(line.strip())
        (buffer if current_key is not None else preamble).append(line)
    flush()

    # Merge repeated sections (e.g. "Experience" split across pages).
    merged: dict[str, Section] = {}
    for s in sections:
        if s.key in merged:
            prev = merged[s.key]
            merged[s.key] = Section(s.key, prev.heading, f"{prev.text}\n\n{s.text}".strip())
        else:
            merged[s.key] = s
    return "\n".join(preamble).strip(), list(merged.values()), unrecognised


def parse_cv(text: str, today: date | None = None) -> ParsedCV:
    preamble, sections, unrecognised = split_sections(text)
    notes: list[str] = []
    if not sections:
        notes.append("No standard section headings were recognised, so sections could not be separated.")

    experience = next((s for s in sections if s.key == "experience"), None)
    range_source = experience.text if experience else text
    ranges = extract_date_ranges(range_source, today)
    if not experience and ranges:
        notes.append("Experience dates were estimated from the whole CV because no Experience section was found.")

    return ParsedCV(
        sections=tuple(sections),
        unrecognised_headings=tuple(dict.fromkeys(unrecognised)),
        contact=extract_contact(text),
        name_guess=_guess_name(preamble.split("\n") if preamble else text.split("\n")),
        date_ranges=tuple(ranges),
        experience_years_estimate=estimate_experience_years(ranges),
        skills=tuple(extract_skills(text)),
        bullets=analyse_bullets(bullet_lines(text)),
        word_count=len(text.split()),
        preamble=preamble,
        notes=tuple(notes),
    )
