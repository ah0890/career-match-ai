"""Job-specific optimisation of a CV version.

Compares the CV with one job description and proposes changes the user approves one by one:
lead with the most relevant skills and achievements, a focused summary, a section order that
puts the relevant evidence first, the job's own name for a skill the CV already shows, and the
usual wording fixes on the bullets that matter for this job.

Missing skills are reported as genuine gaps. Adding one is only ever offered as a change the
user must confirm is true — the CV never claims a skill on its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.cv.extraction import ExtractionResult
from src.cv.parsing import extract_date_ranges, estimate_experience_years
from src.jobs.models import JobPosting
from src.matching.engine import MatchResult, build_profile, match_job
from src.matching.skills import extract_skills
from src.matching.text import content_stems
from src.workspace.document import CVDocument
from src.workspace.review import BULLET_KINDS, Suggestion, _text_suggestions

TAILORING_NOTE = ("Suggestions only reorder, emphasise or restate what your CV already says. Skills the job asks for "
                  "that your CV does not show are listed as gaps — add one only if you genuinely have it.")


def job_posting(title: str, description: str, company: str | None = None, *, key: str | None = None) -> JobPosting:
    """A job entered by hand (or taken from the tracker) in the shape the matching engine expects."""
    return JobPosting(provider_id="manual", source_name="Your job description", source_job_id=key,
                      title=" ".join(title.split())[:300] or "Target role", company=(company or None),
                      description=description.strip()[:60000])


def score(content: CVDocument, job: JobPosting, weights) -> MatchResult:
    profile = build_profile(ExtractionResult(content.to_text(), "docx", None))
    return match_job(profile, job, weights)


@dataclass
class TailoringReport:
    result: MatchResult
    suggestions: list[Suggestion]
    gaps: list[tuple[str, str]]  # (skill or requirement, why it matters)
    strengths: list[str]
    note: str = TAILORING_NOTE
    keywords_to_check: list[str] = field(default_factory=list)


def _terms(result: MatchResult) -> tuple[set[str], set[str]]:
    skills = {s.name for s in result.requirements.skills}
    stems = {st for r in result.requirements.responsibilities for st in content_stems(r)}
    stems |= {st for s in skills for st in content_stems(s)}
    stems |= {st for k in result.requirements.keywords for st in content_stems(k)}
    return skills, stems


def _relevance(text: str, skills: set[str], stems: set[str]) -> int:
    return 3 * sum(m.name in skills for m in extract_skills(text)) + len(stems & set(content_stems(text)))


def _reorder_suggestions(content: CVDocument, skills: set[str], stems: set[str]) -> list[Suggestion]:
    out = []
    for s in content.sections:
        if s.hidden or s.kind not in ("skills", *BULLET_KINDS):
            continue
        for e in s.entries:
            visible = [i for i in e.items if not i.hidden]
            if len(visible) < 2:
                continue
            ranked = sorted(e.items, key=lambda i: -_relevance(i.text, skills, stems))  # stable for ties
            if [i.id for i in ranked] == [i.id for i in e.items]:
                continue
            first = [i.text for i in ranked if not i.hidden][:3]
            where = s.title + (f" · {e.title}" if e.title else "")
            if s.kind == "skills":
                title, why = "Lead with this job's skills", "The skills this job asks for are listed first."
            else:
                title, why = ("Lead with your most relevant achievements",
                              "Within this role, the bullets that match the job's responsibilities move to the top.")
            out.append(Suggestion(
                f"order:{e.id}", "tailoring", "Medium", "reorder", where,
                "\n".join(i.text for i in visible), "\n".join(i.text for i in ranked if not i.hidden),
                f"{title}. {why} Nothing is added, removed or reworded; nothing moves to another role.",
                "Recruiters scan the top of each list first. Now it starts with: " + "; ".join(first)[:200],
                section_id=s.id, entry_id=e.id, payload={"scope": "items", "entry_id": e.id,
                                                          "order": [i.id for i in ranked]}))
    return out


def _section_order(content: CVDocument, result: MatchResult) -> Suggestion | None:
    visible = [s for s in content.sections if not s.hidden]
    priority = {"summary": 0, "skills": 1, "experience": 2, "projects": 3, "certifications": 4, "education": 5}
    skill_heavy = len(result.requirements.required_skills) >= 4
    if not skill_heavy:
        priority["skills"] = 2.5
    proposed = sorted(content.sections, key=lambda s: priority.get(s.kind, 10))  # stable for the rest
    if [s.id for s in proposed] == [s.id for s in content.sections]:
        return None
    before = " → ".join(s.title for s in visible)
    after = " → ".join(s.title for s in proposed if not s.hidden)
    if before == after:
        return None
    return Suggestion(
        "order:sections", "tailoring", "Low", "reorder", "Section order", before, after,
        "Puts the sections that best show your fit for this job near the top"
        + (" — this job lists many required skills, so Skills comes right after your summary." if skill_heavy else ".")
        + " No content changes.", "The evidence a recruiter looks for first is seen first.",
        payload={"scope": "sections", "order": [s.id for s in proposed]})


def _summary(content: CVDocument, result: MatchResult) -> Suggestion | None:
    required = {r.name for r in result.requirements.required_skills}
    matched = [s for s in result.matched_skills if s in required][:4] or list(result.matched_skills[:3])
    if not matched:
        return None
    strengths = ", ".join(matched[:-1]) + (" and " if len(matched) > 1 else "") + matched[-1]
    section = content.section("summary")
    current = next((i for e in (section.entries if section else []) for i in e.items if not i.hidden), None)
    if current is not None:
        line = f"Key strengths for this role: {strengths}."
        if strengths.lower() in current.text.lower() or "key strengths for this role" in current.text.lower():
            return None
        return Suggestion(
            "summary:job", "tailoring", "High", "replace", "Professional Summary", current.text,
            current.text.rstrip() + " " + line,
            "Adds one line naming the job's required skills that your CV already shows. Your own words stay.",
            "Shows the fit for this role in the first lines a recruiter reads.", section_id=section.id,
            entry_id=section.entries[0].id, item_id=current.id,
            verification="Check you are comfortable highlighting these skills for this role.")
    exp = content.section("experience")
    title = content.contact.headline or (exp.entries[0].title if exp and exp.entries else "Professional")
    years = estimate_experience_years(extract_date_ranges(content.to_text()))
    sentence = (f"{title} with {int(years)}+ years of experience, with strengths in {strengths}." if years >= 1
                else f"{title} with strengths in {strengths}.")
    return Suggestion(
        "summary:job", "tailoring", "High", "add", "Professional Summary", "", sentence,
        "A short summary aimed at this job, built only from your CV's own title, dates and skills.",
        "Shows the fit for this role in the first lines a recruiter reads.",
        verification="Check the title, years and skills are accurate before accepting.", payload={"kind": "summary"})


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9+#]", "", text.lower())


def _terminology(content: CVDocument, job: JobPosting, result: MatchResult) -> list[Suggestion]:
    """Where the CV names a skill differently from the job (e.g. 'statistical process control' vs 'SPC')."""
    job_terms: dict[str, str] = {}
    for m in extract_skills(f"{job.title}\n{job.description}"):
        job_terms.setdefault(m.name, m.matched_text)
    cv_squashed = _squash(content.to_text())
    out, done = [], set()
    for s, e, i in content.iter_items(include_hidden=False):
        if s.kind not in BULLET_KINDS:
            continue
        for m in extract_skills(i.text):
            job_word = job_terms.get(m.name)
            if job_word is None or m.name in done or _squash(job_word) == _squash(m.matched_text):
                continue
            if _squash(job_word) in cv_squashed:  # the CV already uses the job's word somewhere
                continue
            proposed = i.text.replace(m.matched_text, f"{m.matched_text} ({job_word})", 1)
            if proposed == i.text:
                continue
            done.add(m.name)
            out.append(Suggestion(
                f"term:{i.id}", "tailoring", "Medium", "replace", s.title + (f" · {e.title}" if e.title else ""),
                i.text, proposed, f"The job calls this “{job_word}”; your CV says “{m.matched_text}”. Adding the "
                "job's term helps keyword searches find it. The meaning is unchanged.",
                "ATS searches often look for the employer's exact wording.",
                section_id=s.id, entry_id=e.id, item_id=i.id))
    return out


def _add_skills(content: CVDocument, result: MatchResult) -> list[Suggestion]:
    essential = {g.requirement for g in result.mandatory_gaps}
    skills = content.section("skills")
    out = []
    for name in result.missing_required_skills[:8]:
        out.append(Suggestion(
            f"addskill:{name.lower()}", "tailoring", "Low", "add", "Skills", "", name,
            ("The job states it as essential" if name in essential else "The job lists it as required")
            + " and your CV does not mention it.", "Only worth adding if it is true — you may be asked about it.",
            section_id=skills.id if skills else None,
            verification=f"I genuinely have experience with {name} and can discuss it in an interview.",
            payload={"kind": "skills"}))
    return out


def tailor(content: CVDocument, job: JobPosting, weights) -> TailoringReport:
    result = score(content, job, weights)
    skills, stems = _terms(result)
    suggestions: list[Suggestion] = []
    if (s := _summary(content, result)) is not None:
        suggestions.append(s)
    suggestions += _reorder_suggestions(content, skills, stems)
    if (s := _section_order(content, result)) is not None:
        suggestions.append(s)
    suggestions += _terminology(content, job, result)
    relevant_items = {i.id for _, _, i in content.iter_items(include_hidden=False)
                      if _relevance(i.text, skills, stems) > 0}
    term_items = {s.item_id for s in suggestions if s.key.startswith("term:")}
    for fix in _text_suggestions(content):
        if fix.item_id in relevant_items and fix.item_id not in term_items:
            fix.key, fix.category = f"tailor-text:{fix.item_id}", "tailoring"
            fix.explanation += " This line matters for the job, so it is worth getting right."
            suggestions.append(fix)
    suggestions += _add_skills(content, result)
    gaps = [(g.requirement, g.detail) for g in result.mandatory_gaps]
    gaps += [(name, "Required by the job; your CV does not mention it.") for name in result.missing_required_skills
             if name not in {g for g, _ in gaps}]
    gaps += [(name, "Preferred by the job; nice to have.") for name in result.missing_preferred_skills]
    strengths = list(result.matched_skills)
    return TailoringReport(result, suggestions, gaps, strengths,
                           keywords_to_check=[k for k, _ in result.check_yourself][:8])
