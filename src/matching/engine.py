"""Explainable CV-to-job matching.

The overall score is a weighted average of six components (weights from settings). A
component the job gives no information about is marked "not assessed" and its weight is
shared among the others, so missing job data never counts against the candidate. When
the job asks for something the CV does not show, the gap is worded as "not found in your
CV" — the score reflects what the CV evidences, not what the candidate can or cannot do.

The score estimates how well the CV evidences the job's stated requirements. It is not a
prediction of being shortlisted or hired.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from config.settings import ScoringWeights
from src.cv.ats import ATSReport, analyse_cv
from src.cv.extraction import ExtractionResult
from src.cv.parsing import ParsedCV, parse_cv
from src.jobs.models import JobPosting
from src.matching.education import LEVEL_LABELS, DegreeLevel, DegreeMention, highest_degree
from src.matching.requirements import JobRequirements, extract_requirements
from src.matching.text import content_stems, stem

Confidence = Literal["High", "Medium", "Low"]

MATCH_LIMITATIONS = (
    "The match score estimates how well your CV evidences the requirements stated in the job description, "
    "using transparent rules. It is not a prediction of being shortlisted or hired, and a missing item means "
    "it was not found in your CV text — not that you lack it."
)

COMPONENT_LABELS = {
    "ats": "CV readability (ATS)", "required_skills": "Required skills", "experience": "Experience",
    "responsibilities": "Responsibilities", "education": "Education", "keywords": "Job keywords",
}
_COVERED_RATIO = 0.5  # share of a responsibility's key words that must appear in the CV
_FULL_CREDIT_RATIO = 0.6
_REQUIRED_SHARE = 0.85  # required skills vs preferred skills within the skills component
_YEARS_SHARE = 0.6  # years vs relevance within the experience component
_TITLE_NOISE = frozenset(stem(w) for w in """
senior junior lead principal staff head chief remote hybrid onsite contract contractor freelance fulltime
parttime intern internship graduate entry level associate assistant trainee apprentice global regional
""".split())


@dataclass(frozen=True)
class MatchProfile:
    """Everything the engine needs from a CV, computed once and reused for every job."""

    text: str
    parsed: ParsedCV
    ats: ATSReport
    skills: frozenset[str]
    stems: frozenset[str]
    experience_stems: frozenset[str]
    years: float  # estimated from dated roles; 0 when no dates were found
    has_dates: bool
    degree: DegreeMention | None


def build_profile(extraction: ExtractionResult) -> MatchProfile:
    parsed = parse_cv(extraction.text)
    return profile_from(extraction.text, parsed, analyse_cv(extraction, parsed))


def profile_from(text: str, parsed: ParsedCV, ats: ATSReport) -> MatchProfile:
    experience = parsed.section("experience")
    education = parsed.section("education")
    return MatchProfile(
        text=text,
        parsed=parsed,
        ats=ats,
        skills=frozenset(s.name for s in parsed.skills),
        stems=frozenset(content_stems(text)),
        experience_stems=frozenset(content_stems(experience.text if experience else text)),
        years=parsed.experience_years_estimate,
        has_dates=bool(parsed.date_ranges),
        degree=highest_degree(education.text if education and education.text else text),
    )


@dataclass(frozen=True)
class ComponentScore:
    key: str
    label: str
    weight: float  # configured weight (percent)
    score: float | None  # 0–1; None = not assessed
    evidence: tuple[str, ...] = ()
    gaps: tuple[str, ...] = ()
    note: str = ""

    @property
    def assessed(self) -> bool:
        return self.score is not None

    @property
    def percent(self) -> int | None:
        return None if self.score is None else round(100 * self.score)


@dataclass(frozen=True)
class MandatoryGap:
    requirement: str
    detail: str
    evidence: str  # the job's sentence that states it


@dataclass(frozen=True)
class MatchResult:
    job: JobPosting
    score: int  # 0–100
    components: tuple[ComponentScore, ...]
    confidence: Confidence
    confidence_reasons: tuple[str, ...]
    matched_skills: tuple[str, ...]
    missing_required_skills: tuple[str, ...]
    missing_preferred_skills: tuple[str, ...]
    mandatory_gaps: tuple[MandatoryGap, ...]
    check_yourself: tuple[tuple[str, str], ...]  # requirements a CV cannot prove
    requirements: JobRequirements
    limitations: str = MATCH_LIMITATIONS
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def assessed_weight(self) -> float:
        return sum(c.weight for c in self.components if c.assessed)

    def effective_weight(self, component: ComponentScore) -> float:
        """The component's share of the overall score after redistributing unassessed weight."""
        total = self.assessed_weight
        return round(100 * component.weight / total, 1) if component.assessed and total else 0.0


# --- Components --------------------------------------------------------------

def _ats(p: MatchProfile, weight: float) -> ComponentScore:
    return ComponentScore("ats", COMPONENT_LABELS["ats"], weight, p.ats.score / 100,
                          (f"General CV readability score: {p.ats.score}/100 ({p.ats.band}).",),
                          note="The same for every job; see CV Analysis for how to improve it.")


def _skills(p: MatchProfile, req: JobRequirements, weight: float) -> ComponentScore:
    required, preferred = req.required_skills, req.preferred_skills
    label = COMPONENT_LABELS["required_skills"]
    if not required and not preferred:
        return ComponentScore("required_skills", label, weight, None,
                              note="No recognisable skills were found in the job description.")
    req_hit = [s.name for s in required if s.name in p.skills]
    pref_hit = [s.name for s in preferred if s.name in p.skills]
    req_cov = len(req_hit) / len(required) if required else None
    pref_cov = len(pref_hit) / len(preferred) if preferred else None
    if req_cov is not None and pref_cov is not None:
        score = _REQUIRED_SHARE * req_cov + (1 - _REQUIRED_SHARE) * pref_cov
    else:
        score = req_cov if req_cov is not None else pref_cov
    evidence = []
    if required:
        evidence.append(f"{len(req_hit)} of {len(required)} required skill(s) found in your CV"
                        + (f": {', '.join(req_hit)}." if req_hit else "."))
    if preferred:
        evidence.append(f"{len(pref_hit)} of {len(preferred)} preferred skill(s) found"
                        + (f": {', '.join(pref_hit)}." if pref_hit else "."))
    gaps = [f"{s.name} ({'required' if s.required else 'preferred'}) — not found in your CV."
            for s in (*required, *preferred) if s.name not in p.skills]
    return ComponentScore("required_skills", label, weight, score, tuple(evidence), tuple(gaps),
                          "Required skills count for 85% of this component and preferred skills for 15%."
                          if required and preferred else "")


def _title_relevance(p: MatchProfile, job: JobPosting) -> tuple[float, list[str]] | None:
    title_stems = [s for s in content_stems(job.title) if s not in _TITLE_NOISE]
    if not title_stems:
        return None
    hits = [s for s in title_stems if s in p.experience_stems]
    return len(hits) / len(title_stems), hits


def _experience(p: MatchProfile, job: JobPosting, req: JobRequirements, weight: float) -> ComponentScore:
    label = COMPONENT_LABELS["experience"]
    relevance = _title_relevance(p, job)
    evidence: list[str] = []
    gaps: list[str] = []
    rel_score = None
    if relevance is not None:
        rel_score, hits = relevance
        words = re.findall(r"[A-Za-z][A-Za-z+#-]*", job.title)
        matched_words = [w for w in words if stem(w.lower()) in hits]
        evidence.append(f"Job title words found in your experience: {', '.join(matched_words)}."
                        if matched_words else f"No words from the job title “{job.title}” appear in your experience.")
    exp = req.experience
    if exp is None:
        if rel_score is None:
            return ComponentScore("experience", label, weight, None,
                                  note="The job states no years of experience and its title has no specific words.")
        return ComponentScore("experience", label, weight, rel_score, tuple(evidence), tuple(gaps),
                              "The job states no years of experience, so this is based on how closely your "
                              "experience relates to the job title.")
    wanted = f"{exp.min_years}–{exp.max_years}" if exp.max_years else f"{exp.min_years}+"
    if p.has_dates:
        years_score = min(1.0, p.years / exp.min_years)
        evidence.append(f"The job asks for {wanted} years; your dated roles cover about {p.years:g} years.")
        if p.years < exp.min_years:
            gaps.append(f"About {exp.min_years - p.years:g} year(s) short of the stated {exp.min_years} years "
                        "(based on the dates in your CV).")
    else:
        years_score = 0.0
        gaps.append(f"The job asks for {wanted} years, but no employment dates were found in your CV, so your "
                    "experience could not be measured. Add dates to each role.")
    score = years_score if rel_score is None else _YEARS_SHARE * years_score + (1 - _YEARS_SHARE) * rel_score
    note = ("Years of experience count for 60% and relevance to the job title for 40%."
            if rel_score is not None else "")
    if not exp.required:
        note = (note + " The years requirement is listed as preferred.").strip()
    return ComponentScore("experience", label, weight, score, tuple(evidence), tuple(gaps), note)


def _responsibilities(p: MatchProfile, req: JobRequirements, weight: float) -> ComponentScore:
    label = COMPONENT_LABELS["responsibilities"]
    items = [(r, content_stems(r)) for r in req.responsibilities]
    items = [(r, st) for r, st in items if len(st) >= 2]
    if not items:
        return ComponentScore("responsibilities", label, weight, None,
                              note="No responsibilities could be identified in the job description.")
    covered, uncovered, credit = [], [], 0.0
    for text, stems_ in items:
        ratio = sum(s in p.stems for s in stems_) / len(stems_)
        credit += min(1.0, ratio / _FULL_CREDIT_RATIO)
        (covered if ratio >= _COVERED_RATIO else uncovered).append(text)
    evidence = [f"{len(covered)} of {len(items)} responsibilities are reflected in your CV wording."]
    evidence += [f"Reflected: {t}" for t in covered[:5]]
    gaps = [f"Not clearly reflected: {t}" for t in uncovered]
    return ComponentScore("responsibilities", label, weight, credit / len(items), tuple(evidence), tuple(gaps),
                          "Based on how many key words of each responsibility appear in your CV.")


def _education(p: MatchProfile, req: JobRequirements, weight: float) -> ComponentScore:
    label = COMPONENT_LABELS["education"]
    edu = req.education
    if edu is None:
        return ComponentScore("education", label, weight, None, note="The job states no education requirement.")
    wanted = LEVEL_LABELS[edu.level]
    evidence = [f"The job asks for a {wanted}" + (" (preferred)." if not edu.required else ".")]
    gaps: list[str] = []
    have = p.degree.level if p.degree else DegreeLevel.NONE
    if have >= edu.level:
        score = 1.0
        evidence.append(f"Your CV shows a {LEVEL_LABELS[have]}: “{p.degree.text[:120]}”.")
    elif have is not DegreeLevel.NONE:
        score = 0.5 if have == edu.level - 1 else 0.25
        evidence.append(f"Your CV shows a {LEVEL_LABELS[have]}.")
        gaps.append(f"The job asks for a {wanted}; the highest level found in your CV is a {LEVEL_LABELS[have]}.")
    else:
        score = 0.0
        gaps.append(f"No {wanted} was found in your CV. If you have one, list it in an Education section.")
    if score < 1 and edu.allows_equivalent:
        score = max(score, 0.5)
        evidence.append("The job accepts equivalent experience instead of the degree.")
    return ComponentScore("education", label, weight, score, tuple(evidence), tuple(gaps),
                          "Only the degree level is compared; check the subject yourself.")


def _keywords(p: MatchProfile, req: JobRequirements, weight: float) -> ComponentScore:
    label = COMPONENT_LABELS["keywords"]
    if not req.keywords:
        return ComponentScore("keywords", label, weight, None,
                              note="The job description has too few repeated terms to compare.")
    hit = [k for k in req.keywords if stem(k) in p.stems or k in p.text.lower()]
    missing = [k for k in req.keywords if k not in hit]
    return ComponentScore("keywords", label, weight, len(hit) / len(req.keywords),
                          (f"{len(hit)} of {len(req.keywords)} repeated job terms appear in your CV"
                           + (f": {', '.join(hit)}." if hit else "."),),
                          tuple(f"“{k}” — not found in your CV." for k in missing),
                          "Terms the job description repeats, other than recognised skills.")


# --- Overall -----------------------------------------------------------------

def _mandatory_gaps(p: MatchProfile, req: JobRequirements) -> list[MandatoryGap]:
    gaps = [MandatoryGap(s.name, "Stated as essential, but not found in your CV.", s.evidence)
            for s in req.skills if s.mandatory and s.name not in p.skills]
    exp = req.experience
    if exp and exp.mandatory and exp.required and (not p.has_dates or p.years < exp.min_years):
        detail = (f"At least {exp.min_years} years stated as essential; your CV's dates cover about {p.years:g}."
                  if p.has_dates else f"At least {exp.min_years} years stated as essential; no dates found in your CV.")
        gaps.append(MandatoryGap(f"{exp.min_years}+ years of experience", detail, exp.evidence))
    edu = req.education
    have = p.degree.level if p.degree else DegreeLevel.NONE
    if edu and edu.mandatory and edu.required and have < edu.level and not edu.allows_equivalent:
        gaps.append(MandatoryGap(LEVEL_LABELS[edu.level].capitalize(),
                                 "Stated as essential, but not found in your CV.", edu.evidence))
    return gaps


def _confidence(req: JobRequirements, assessed_weight: float) -> tuple[Confidence, list[str]]:
    reasons = []
    if req.word_count < 80:
        reasons.append(f"The job description is short ({req.word_count} words).")
    elif req.word_count < 200:
        reasons.append(f"The job description is moderately detailed ({req.word_count} words).")
    if not req.structured:
        reasons.append("The description has no clear requirements section.")
    if assessed_weight < 100:
        reasons.append(f"Only {assessed_weight:g}% of the scoring weight could be assessed from this job's information.")
    if req.word_count < 80 or assessed_weight < 50:
        return "Low", reasons
    if req.word_count >= 200 and req.structured and assessed_weight >= 80:
        return "High", reasons or ["The job description is detailed and every component could be assessed."]
    return "Medium", reasons


def match_job(profile: MatchProfile, job: JobPosting, weights: ScoringWeights) -> MatchResult:
    req = extract_requirements(job)
    w = weights.as_dict()
    components = (
        _ats(profile, w["ats"]),
        _skills(profile, req, w["required_skills"]),
        _experience(profile, job, req, w["experience"]),
        _responsibilities(profile, req, w["responsibilities"]),
        _education(profile, req, w["education"]),
        _keywords(profile, req, w["keywords"]),
    )
    assessed = sum(c.weight for c in components if c.assessed)
    total = sum(c.weight * c.score for c in components if c.score is not None)
    score = round(100 * total / assessed) if assessed else 0
    confidence, reasons = _confidence(req, assessed)
    return MatchResult(
        job=job,
        score=max(0, min(100, score)),
        components=components,
        confidence=confidence,
        confidence_reasons=tuple(reasons),
        matched_skills=tuple(s.name for s in req.skills if s.name in profile.skills),
        missing_required_skills=tuple(s.name for s in req.required_skills if s.name not in profile.skills),
        missing_preferred_skills=tuple(s.name for s in req.preferred_skills if s.name not in profile.skills),
        mandatory_gaps=tuple(_mandatory_gaps(profile, req)),
        check_yourself=req.unverifiable,
        requirements=req,
        notes=req.notes,
    )


_CONFIDENCE_ORDER = {"High": 0, "Medium": 0, "Low": 1}


def rank_jobs(profile: MatchProfile, jobs: list[JobPosting], weights: ScoringWeights) -> list[MatchResult]:
    """Match every job and rank by score. Jobs with too little information are listed after the others."""
    results = [match_job(profile, job, weights) for job in jobs]
    return sorted(results, key=lambda r: (_CONFIDENCE_ORDER[r.confidence], -r.score))
