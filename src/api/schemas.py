"""Request bodies and response shapes for the API.

Responses are built from the engines' own dataclasses by small converter functions, so the
API never exposes a field the app would not show (for example, CV text is never returned
except in the user's own tailored CV).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.api.models import UserCV, UserJob
from src.interview.prep import PrepPlan
from src.matching.engine import MatchProfile, MatchResult
from src.matching.improvements import ImprovementPlan
from src.matching.recommendations import Recommendation
from src.tailoring.edits import Edit

MAX_DESCRIPTION = 60_000
MAX_CV_TEXT = 100_000


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Credentials(_In):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)
    client: Literal["web", "extension"] = "web"


class JobIn(_In):
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=30, max_length=MAX_DESCRIPTION)
    company: str | None = Field(None, max_length=300)
    location: str | None = Field(None, max_length=300)
    url: str | None = Field(None, max_length=2048)
    apply_url: str | None = Field(None, max_length=2048)
    source_name: str | None = Field(None, max_length=100)


class TailoredCVIn(_In):
    accepted: list[str] = Field(default_factory=list, max_length=100)
    text: str | None = Field(None, max_length=MAX_CV_TEXT)  # the user's own edits of the tailored text
    format: Literal["docx", "pdf", "text"] = "docx"


# --- converters -----------------------------------------------------------

def token_out(token: str, email: str, expires_days: int) -> dict:
    return {"token": token, "token_type": "bearer", "email": email, "expires_in_days": expires_days}


def account_out(email: str, created_at: datetime, cv: UserCV | None, job_count: int) -> dict:
    return {"email": email, "created_at": created_at.isoformat(), "has_cv": cv is not None, "saved_jobs": job_count}


def cv_out(row: UserCV, profile: MatchProfile) -> dict:
    return {
        "filename": row.filename, "kind": row.kind, "uploaded_at": row.uploaded_at.isoformat(),
        "word_count": profile.parsed.word_count,
        "ats": {"score": profile.ats.score, "band": profile.ats.band,
                "top_improvements": [{"priority": r.priority, "title": r.title, "detail": r.detail}
                                     for r in profile.ats.recommendations[:5]]},
        "skills": sorted(profile.skills),
        "experience_years_estimate": round(profile.years, 1) if profile.has_dates else None,
    }


def job_out(row: UserJob) -> dict:
    return {
        "id": row.id, "title": row.title, "company": row.company, "location": row.location,
        "source_name": row.source_name, "listing_url": row.listing_url, "apply_url": row.apply_url,
        "match_score": row.match_score, "recommendation": row.recommendation,
        "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat(),
    }


def analysis_out(row: UserJob, result: MatchResult, rec: Recommendation, plan: ImprovementPlan) -> dict:
    return {
        "job": job_out(row),
        "score": result.score,
        "confidence": result.confidence,
        "confidence_reasons": list(result.confidence_reasons),
        "recommendation": {
            "label": rec.label.value, "headline": rec.headline, "reasons": list(rec.reasons),
            "actions": [{"priority": a.priority, "title": a.title, "detail": a.detail} for a in rec.actions],
            "caveats": list(rec.caveats),
        },
        "components": [{"key": c.key, "label": c.label, "weight": c.weight, "percent": c.percent,
                        "evidence": list(c.evidence), "gaps": list(c.gaps), "note": c.note}
                       for c in result.components],
        "matched_skills": list(result.matched_skills),
        "missing_required_skills": list(result.missing_required_skills),
        "missing_preferred_skills": list(result.missing_preferred_skills),
        "mandatory_gaps": [{"requirement": g.requirement, "detail": g.detail, "evidence": g.evidence}
                           for g in result.mandatory_gaps],
        "check_yourself": [{"requirement": r, "note": n} for r, n in result.check_yourself],
        "improvements": [{"priority": s.priority, "title": s.title, "detail": s.detail, "where": s.where}
                         for s in plan.suggestions],
        "limitations": result.limitations,
    }


def prep_out(plan: PrepPlan) -> dict:
    return {
        "job_title": plan.job_title, "company": plan.company,
        "questions": [{"kind": q.kind, "likelihood": q.likelihood, "text": q.text, "why": q.why,
                       "cv_material": list(q.cv_material), "guidance": q.guidance} for q in plan.questions],
        "questions_to_ask": list(plan.questions_to_ask), "checklist": list(plan.checklist),
        "disclaimer": plan.disclaimer, "notes": list(plan.notes),
    }


def edits_out(edits: list[Edit]) -> list[dict]:
    return [{"id": e.id, "kind": e.kind, "title": e.title, "why": e.why, "before": e.before, "after": e.after,
             "needs_confirmation": e.needs_confirmation, "default_on": e.default_on} for e in edits]
