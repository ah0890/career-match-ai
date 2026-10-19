"""Tailoring suggestions for one job, each previewed and accepted or rejected by the user.

Edits only reorder, emphasise or restate what the CV already says. The one edit that adds
content — a required skill the CV does not show — is off by default and needs the user to
confirm they genuinely have it. Nothing is invented.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.cv.parsing import parse_cv
from src.matching.engine import MatchResult
from src.matching.skills import extract_skills
from src.matching.text import content_stems
from src.tailoring.document import (
    SkillList, find_section, insert_section_after_preamble, join_roles, parse_skill_list, render_skill_list,
    replace_section_body, section_body, split_roles,
)

Kind = Literal["skills_order", "bullet_order", "summary", "add_skill"]
_ORDER: dict[str, int] = {"skills_order": 0, "add_skill": 1, "bullet_order": 2, "summary": 3}


@dataclass(frozen=True)
class Edit:
    id: str
    kind: Kind
    title: str
    why: str
    before: str
    after: str
    needs_confirmation: bool = False  # adds content: the user must confirm it is true
    default_on: bool = True


def _job_terms(result: MatchResult) -> tuple[set[str], set[str]]:
    skills = {s.name for s in result.requirements.skills}
    stems = {st for r in result.requirements.responsibilities for st in content_stems(r)}
    stems |= {st for s in skills for st in content_stems(s)} | {st for k in result.requirements.keywords
                                                                 for st in content_stems(k)}
    return skills, stems


def _relevance(line: str, skills: set[str], stems: set[str]) -> int:
    named = sum(m.name in skills for m in extract_skills(line))
    return 3 * named + len(stems & set(content_stems(line)))


def _skills_order(text: str, skills: set[str]) -> Edit | None:
    body = section_body(text, "skills")
    if not body:
        return None
    current = parse_skill_list(body)
    relevant = [i for i in current.items if any(m.name in skills for m in extract_skills(i))]
    if not relevant:
        return None
    reordered = SkillList(tuple(relevant + [i for i in current.items if i not in relevant]), current.style)
    if reordered.items == current.items:
        return None
    return Edit("skills_order", "skills_order", "Put this job's skills first",
                f"{', '.join(relevant[:6])} are listed first, so a reader sees them immediately. Nothing is "
                "added or removed.", render_skill_list(current), render_skill_list(reordered))


def _bullet_order(text: str, skills: set[str], stems: set[str]) -> Edit | None:
    body = section_body(text, "experience")
    if not body:
        return None
    roles = split_roles(body)
    changed = False
    new_roles = []
    for header, bullets in roles:
        ranked = sorted(bullets, key=lambda b: -_relevance(b, skills, stems))  # stable: ties keep their order
        changed = changed or ranked != bullets
        new_roles.append((header, ranked))
    if not changed:
        return None
    return Edit("bullet_order", "bullet_order", "Lead each role with its most relevant achievements",
                "Within each role, bullets that mention this job's skills and responsibilities move to the top. "
                "Wording is unchanged and no bullet moves to another role.", body, join_roles(new_roles))


def _summary(text: str, result: MatchResult) -> Edit | None:
    parsed = parse_cv(text)
    matched = [s for s in result.matched_skills
               if s in {r.name for r in result.requirements.required_skills}][:4]
    if not matched:
        return None
    strengths = ", ".join(matched[:-1]) + (" and " if len(matched) > 1 else "") + matched[-1]
    years = (f"about {int(parsed.experience_years_estimate)} years of experience"
             if parsed.date_ranges and parsed.experience_years_estimate >= 1 else None)
    existing = section_body(text, "summary")
    if existing and existing.strip():
        line = f"Key strengths for this role: {strengths}."
        if line in existing:
            return None
        after = existing.rstrip() + ("\n" if "\n" in existing.strip() else " ") + line
        return Edit("summary", "summary", "Add a focused line to your summary",
                    "Names the job's required skills that your CV already shows. It states nothing your CV does "
                    "not already contain.", existing, after)
    sentence = (f"Professional with {years}, with strengths in {strengths}." if years
                else f"Professional with strengths in {strengths}.")
    return Edit("summary", "summary", "Add a short summary",
                "A two-line summary helps a reader see the fit. It is built only from your CV's dates and the "
                "skills it already shows — edit it to describe yourself in your own words.", "", sentence)


def _add_skills(text: str, result: MatchResult) -> list[Edit]:
    if find_section(text, "skills") is None:
        return []
    essential = {g.requirement for g in result.mandatory_gaps}
    out = []
    for name in result.missing_required_skills:
        out.append(Edit(
            f"add_skill:{name}", "add_skill", f"Add “{name}” to your skills",
            ("The job states it as essential" if name in essential else "The job lists it as required")
            + " and your CV does not mention it. Only add it if you genuinely have it — you may be asked about it.",
            "", name, needs_confirmation=True, default_on=False))
    return out


def suggest_edits(text: str, result: MatchResult) -> list[Edit]:
    skills, stems = _job_terms(result)
    edits = [e for e in (_skills_order(text, skills), _bullet_order(text, skills, stems), _summary(text, result)) if e]
    edits += _add_skills(text, result)
    return sorted(edits, key=lambda e: _ORDER[e.kind])


def apply_edits(text: str, edits: list[Edit], accepted: set[str]) -> str:
    """Apply the accepted edits in a fixed order. Rejected edits leave the text untouched."""
    chosen = sorted((e for e in edits if e.id in accepted), key=lambda e: _ORDER[e.kind])
    for e in chosen:
        if e.kind == "skills_order":
            text = replace_section_body(text, "skills", e.after)
        elif e.kind == "add_skill":
            body = section_body(text, "skills") or ""
            current = parse_skill_list(body)
            if e.after not in current.items:
                text = replace_section_body(text, "skills", render_skill_list(
                    SkillList(current.items + (e.after,), current.style)))
        elif e.kind == "bullet_order":
            text = replace_section_body(text, "experience", e.after)
        elif e.kind == "summary":
            text = (replace_section_body(text, "summary", e.after) if find_section(text, "summary")
                    else insert_section_after_preamble(text, "PROFESSIONAL SUMMARY", e.after))
    return text
