"""Transparent, rule-based ATS compatibility analysis.

The general score (0–100) measures how reliably a CV's content can be read and
understood by software and recruiters. It is NOT the output of any real applicant
tracking system: ATS products and employer configurations differ widely.

Job-specific keyword alignment is reported separately so formatting quality and
fit for a particular role are never mixed together.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Literal

from src.cv.extraction import ExtractionResult
from src.cv.parsing import ParsedCV
from src.matching.skills import extract_skills

Priority = Literal["High", "Medium", "Low"]
_PRIORITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}

ATS_LIMITATIONS = (
    "This score estimates how reliably software can read your CV using transparent rules. Applicant "
    "tracking systems differ between products and employers, so no score can predict how a specific "
    "employer's system will rank you."
)


@dataclass(frozen=True)
class Check:
    label: str
    points: float
    max_points: float
    detail: str
    priority: Priority = "Medium"  # used when the check is not fully met
    advice: str | None = None  # recommendation when not fully met

    @property
    def passed(self) -> bool:
        return self.points >= self.max_points - 1e-9


@dataclass(frozen=True)
class Component:
    key: str
    label: str
    description: str
    checks: tuple[Check, ...]

    @property
    def score(self) -> float:
        return round(sum(c.points for c in self.checks), 1)

    @property
    def max_score(self) -> float:
        return sum(c.max_points for c in self.checks)

    @property
    def percent(self) -> int:
        return round(100 * self.score / self.max_score) if self.max_score else 0


@dataclass(frozen=True)
class Recommendation:
    priority: Priority
    title: str
    detail: str
    component: str
    points_available: float


@dataclass(frozen=True)
class ATSReport:
    score: int
    band: str
    components: tuple[Component, ...]
    recommendations: tuple[Recommendation, ...]
    limitations: str = ATS_LIMITATIONS


def score_band(score: float) -> str:
    if score >= 85:
        return "Strong"
    if score >= 70:
        return "Good"
    if score >= 50:
        return "Needs improvement"
    return "Significant issues"


def _ratio_points(ratio: float, target: float, max_points: float) -> float:
    return round(max_points * min(1.0, ratio / target), 1) if target > 0 else max_points


# --- Components ------------------------------------------------------------

def _readability(ex: ExtractionResult) -> Component:
    text = ex.text
    lines = [line for line in text.split("\n") if line.strip()]
    odd = sum(ch in "�□" or (ord(ch) < 32 and ch not in "\n\t") for ch in text)
    odd_ratio = odd / max(1, len(text))
    long_lines = sum(len(line) > 220 for line in lines)
    long_ratio = long_lines / max(1, len(lines))
    checks = [
        Check("Text can be extracted", 0 if ex.needs_ocr else 10, 10,
              "The document is a scanned image; no text could be read." if ex.needs_ocr
              else f"{ex.word_count:,} words were read from the file.",
              "High", "Export your CV as a text-based PDF or DOCX from the original editor, not as a scan."),
        Check("No scanned pages", 0 if ex.scanned_pages else 4, 4,
              f"Page(s) {', '.join(map(str, ex.scanned_pages))} contain images instead of text."
              if ex.scanned_pages else "Every page contains readable text.",
              "High", "Replace scanned pages with text so their content can be read."),
        Check("Clean characters", 3 if odd_ratio < 0.005 else 0, 3,
              "No unreadable symbols were found." if odd_ratio < 0.005
              else "Some characters could not be decoded (often from icons or unusual fonts).",
              "Medium", "Replace icon fonts and decorative symbols with plain text labels."),
        Check("Readable line structure", 3 if long_ratio < 0.1 else 0, 3,
              "Lines break naturally." if long_ratio < 0.1
              else "Many very long lines were found, which can indicate merged columns or text boxes.",
              "Medium", "Use a single-column layout without text boxes so content is read in order."),
    ]
    if ex.needs_ocr:
        checks[2] = Check("Clean characters", 0, 3, "Not assessed — no text could be read.")
        checks[3] = Check("Readable line structure", 0, 3, "Not assessed — no text could be read.")
    return Component("readability", "Text readability",
                     "Whether software can read the text in your file at all.", tuple(checks))


def _sections(p: ParsedCV) -> Component:
    def present(key: str, label: str, pts: float, priority: Priority, advice: str) -> Check:
        found = p.has(key)
        return Check(f"{label} section", pts if found else 0, pts,
                     f"Found under “{p.section(key).heading}”." if found
                     else f"No {label.lower()} heading was recognised.", priority, advice)

    unrec = len(p.unrecognised_headings)
    checks = [
        present("experience", "Experience", 6, "High",
                "Add a clearly labelled “Experience” or “Work Experience” section."),
        present("education", "Education", 4, "Medium", "Add an “Education” section, even if brief."),
        present("skills", "Skills", 4, "High", "Add a “Skills” section listing your key tools and competencies."),
        present("summary", "Summary", 3, "Low", "Consider a short professional summary at the top."),
        Check("Standard headings", 3 if unrec <= 1 else (1.5 if unrec <= 3 else 0), 3,
              "Headings use common names that software recognises." if unrec <= 1
              else f"Non-standard headings found: {', '.join(p.unrecognised_headings[:5])}.",
              "Low", "Use conventional heading names such as Experience, Education and Skills."),
    ]
    return Component("sections", "Section organisation",
                     "Whether the main CV sections can be identified.", tuple(checks))


def _contact(p: ParsedCV) -> Component:
    c = p.contact
    has_profile = bool(c.links)
    checks = [
        Check("Email address", 5 if c.emails else 0, 5,
              "An email address was found near the top." if c.emails else "No email address was found near the top.",
              "High", "Put your email address in the main body near the top (not only in a header or image)."),
        Check("Phone number", 3 if c.phones else 0, 3,
              "A phone number was found." if c.phones else "No phone number was detected.",
              "Medium", "Add a phone number with country code near the top."),
        Check("Professional profile link (optional)", 2 if has_profile else 0, 2,
              "A profile or portfolio link was found." if has_profile else "No LinkedIn or portfolio link was found.",
              "Low", "If relevant, add a LinkedIn or portfolio URL."),
    ]
    return Component("contact", "Contact information", "Whether recruiters can contact you.", tuple(checks))


def _experience_detail(p: ParsedCV) -> Component:
    ranges = list(p.date_ranges)
    styles = {r.style for r in ranges if r.style != "mixed"}
    mixed = any(r.style == "mixed" for r in ranges)
    consistent = bool(ranges) and len(styles) <= 1 and not mixed
    starts = [r.start for r in ranges]
    reverse_chrono = len(starts) >= 2 and all(a >= b for a, b in zip(starts, starts[1:]))
    checks = [
        Check("Employment dates", 7 if ranges else 0, 7,
              f"{len(ranges)} date range(s) found." if ranges else "No date ranges (e.g. “Jan 2020 – Present”) were found.",
              "High", "Give each role a start and end date, e.g. “Mar 2021 – Present”."),
        Check("Consistent date format", 4 if consistent else 0, 4,
              "Dates use one consistent format." if consistent
              else ("Dates use different formats." if ranges else "Not assessed — no dates were found."),
              "Low", "Use one date format throughout, e.g. “Jan 2020 – Mar 2023”."),
        Check("Most recent role first", 4 if reverse_chrono or len(starts) == 1 else 0, 4,
              "Roles appear in reverse chronological order." if reverse_chrono
              else ("Only one role was dated." if len(starts) == 1
                    else ("Roles do not appear newest first." if starts else "Not assessed — no dates were found.")),
              "Medium", "List roles in reverse chronological order (most recent first)."),
    ]
    return Component("experience", "Experience detail",
                     "Whether roles are dated and ordered so your history can be followed.", tuple(checks))


def _content(p: ParsedCV) -> Component:
    b = p.bullets
    if b.total == 0:
        none = "Not assessed — no bullet points were detected."
        checks = [
            Check("Bullet points", 0, 5, "No bullet points were detected.", "Medium",
                  "Describe each role with 3–6 concise bullet points."),
            Check("Action verbs", 0, 5, none), Check("Quantified results", 0, 5, none),
            Check("No first-person pronouns", 0, 3, none), Check("Concise bullets", 0, 2, none),
        ]
    else:
        av = b.action_verb / b.total
        qn = b.quantified / b.total
        long_ratio = b.too_long / b.total
        checks = [
            Check("Bullet points", 5 if b.total >= 3 else 2.5, 5, f"{b.total} bullet point(s) found.", "Medium",
                  "Describe each role with 3–6 concise bullet points."),
            Check("Action verbs", _ratio_points(av, 0.5, 5), 5,
                  f"{b.action_verb} of {b.total} bullets start with an action verb ({av:.0%}).", "Medium",
                  "Start bullets with strong action verbs such as Led, Built, Reduced or Improved."),
            Check("Quantified results", _ratio_points(qn, 0.3, 5), 5,
                  f"{b.quantified} of {b.total} bullets include numbers ({qn:.0%}).", "Medium",
                  "Where you genuinely can, add measurable results (numbers, percentages, scale)."),
            Check("No first-person pronouns", 3 if b.first_person == 0 else 0, 3,
                  "Bullets avoid “I”/“my”." if b.first_person == 0
                  else f"{b.first_person} bullet(s) use first-person pronouns.", "Low",
                  "Remove “I” and “my” from bullets, e.g. “Led a team…” instead of “I led a team…”."),
            Check("Concise bullets", 2 if long_ratio <= 0.1 else 0, 2,
                  f"Average bullet length is {b.average_words:g} words.", "Low",
                  "Keep bullets under about 30 words; split long ones."),
        ]
    return Component("content", "Content quality",
                     "Whether achievements are clear, specific and easy to scan.", tuple(checks))


def _length_and_format(ex: ExtractionResult, p: ParsedCV) -> Component:
    words = p.word_count
    if 350 <= words <= 1100:
        length_pts, length_detail = 6, f"{words:,} words — a comfortable length."
    elif 200 <= words < 350 or 1100 < words <= 1600:
        length_pts, length_detail = 3, f"{words:,} words — {'short' if words < 350 else 'long'} for most roles."
    else:
        length_pts, length_detail = 0, f"{words:,} words — {'very short' if words < 200 else 'very long'}."
    pages_ok = ex.page_count is None or ex.page_count <= 3
    table_lines = sum(" | " in line for line in ex.text.split("\n"))
    skills = len(p.skills)
    checks = [
        Check("Appropriate length", length_pts, 6, length_detail, "Medium",
              "Aim for roughly 350–1,100 words (typically 1–2 pages)."),
        Check("Page count", 3 if pages_ok else 0, 3,
              ("Not applicable to DOCX files." if ex.page_count is None else f"{ex.page_count} page(s).")
              if pages_ok else f"{ex.page_count} pages — longer than most recruiters expect.", "Low",
              "Condense to 2–3 pages by focusing on recent, relevant experience."),
        Check("Few tables", 3 if table_lines < 3 else 0, 3,
              "No significant table layout detected." if table_lines < 3
              else f"{table_lines} lines appear to come from tables, which some systems read out of order.",
              "Medium", "Move key information out of tables into plain text sections."),
        Check("Identifiable skills", 3 if skills >= 5 else round(3 * skills / 5, 1), 3,
              f"{skills} recognised skill(s) found.", "Medium",
              "List your relevant tools, technologies and methods explicitly by name."),
    ]
    return Component("format", "Length and formatting",
                     "Length and layout patterns that commonly cause parsing problems.", tuple(checks))


def analyse_cv(ex: ExtractionResult, parsed: ParsedCV) -> ATSReport:
    components = (
        _readability(ex), _sections(parsed), _contact(parsed),
        _experience_detail(parsed), _content(parsed), _length_and_format(ex, parsed),
    )
    total = round(sum(c.score for c in components))
    recs = [
        Recommendation(check.priority, check.label, check.advice, comp.label,
                       round(check.max_points - check.points, 1))
        for comp in components for check in comp.checks
        if not check.passed and check.advice
    ]
    recs.sort(key=lambda r: (_PRIORITY_ORDER[r.priority], -r.points_available))
    return ATSReport(total, score_band(total), components, tuple(recs))


# --- Job-specific keyword alignment ---------------------------------------

_STOPWORDS = frozenset("""
a about above across after again against all also am an and any are as at be because been before being
below between both but by can could did do does doing down during each either etc every few for from
further had has have having he her here hers him his how i if in into is it its itself just least
less like made make many may me might more most must my no nor not now of off on once only or other our
ours out over own per please same shall she should so some such than that the their theirs them then
there these they this those through to too under until up upon us very via was we well were what when
where which while who whom why will with within without would you your yours
ability able across apply applicant applicants application benefits candidate candidates company
competitive day days description duties environment equal excellent experience full great good include
includes including job join knowledge level looking new opportunity opportunities plus position
preferred required requirement requirements responsibilities responsibility role salary skills strong
team teams time work working year years using use used based within key ensure provide support related
""".split())

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z+#./-]{2,}")


@dataclass(frozen=True)
class JobAlignment:
    score: int
    matched_skills: tuple[str, ...]
    missing_skills: tuple[str, ...]
    matched_keywords: tuple[str, ...]
    missing_keywords: tuple[str, ...]
    job_word_count: int
    reliable: bool
    note: str


def job_keywords(job_text: str, limit: int = 15) -> list[str]:
    tokens = [t.lower().strip(".-/") for t in _TOKEN_RE.findall(job_text)]
    counts = Counter(t for t in tokens if len(t) >= 4 and t not in _STOPWORDS)
    return [w for w, n in counts.most_common(limit * 2) if n >= 2][:limit]


def job_alignment(cv_text: str, job_text: str) -> JobAlignment:
    """Compare CV wording with a job description. Missing terms mean 'not found in the CV text'."""
    job_words = len(job_text.split())
    cv_lower = cv_text.lower()
    job_skills = [s.name for s in extract_skills(job_text)]
    cv_skills = {s.name for s in extract_skills(cv_text)}
    matched_s = [s for s in job_skills if s in cv_skills]
    missing_s = [s for s in job_skills if s not in cv_skills]
    skill_names_lower = {s.lower() for s in job_skills}
    keywords = [k for k in job_keywords(job_text) if k not in skill_names_lower]
    matched_k = [k for k in keywords if re.search(rf"\b{re.escape(k)}", cv_lower)]
    missing_k = [k for k in keywords if k not in matched_k]

    skill_cov = len(matched_s) / len(job_skills) if job_skills else None
    kw_cov = len(matched_k) / len(keywords) if keywords else None
    if skill_cov is not None and kw_cov is not None:
        score = 0.7 * skill_cov + 0.3 * kw_cov
    else:
        score = skill_cov if skill_cov is not None else (kw_cov or 0.0)

    reliable = job_words >= 80 and (bool(job_skills) or len(keywords) >= 5)
    note = (
        "Based on skills and repeated terms in the job description. A missing term means it was not found "
        "in your CV text — not that you lack it."
        if reliable else
        "The job description is short or contains few recognisable skills, so this comparison is unreliable. "
        "Paste the full description for a better result."
    )
    return JobAlignment(round(100 * score), tuple(matched_s), tuple(missing_s), tuple(matched_k),
                        tuple(missing_k), job_words, reliable, note)
