"""Connect a researched company to the user's search results and CV.

This is analysis, not sourced fact, and is always labelled as such in the UI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.company.models import CompanyProfile
from src.jobs.models import JobPosting
from src.jobs.normalization import normalize_company
from src.matching.recommendations import RankedMatch


@dataclass(frozen=True)
class Relevance:
    roles: tuple[JobPosting, ...]  # roles at this company in the current search
    matches: tuple[RankedMatch, ...]  # the same roles, scored against the CV (when available)
    cv_mentions: tuple[str, ...]  # industries/products from the profile that the CV also mentions


def same_company(a: str | None, b: str | None) -> bool:
    """Compare employer names after removing legal suffixes ("Siemens AG" = "Siemens").

    Names must otherwise be identical: "Siemens Energy" is a different employer from "Siemens".
    """
    na, nb = normalize_company(a), normalize_company(b)
    return bool(na) and na == nb


def companies_in(jobs: list[JobPosting]) -> list[str]:
    """Distinct employer names from search results, as the sources wrote them."""
    seen: dict[str, str] = {}
    for job in jobs:
        if job.company and (key := normalize_company(job.company)):
            seen.setdefault(key, job.company)
    return sorted(seen.values(), key=str.lower)


def relevance(profile: CompanyProfile, jobs: list[JobPosting], matches: list[RankedMatch],
              cv_text: str | None) -> Relevance:
    roles = tuple(j for j in jobs if same_company(j.company, profile.name))
    keys = {j.key for j in roles}
    scored = tuple(m for m in matches if m.result.job.key in keys)
    mentions: list[str] = []
    if cv_text:
        lower = cv_text.lower()
        for fact in profile.facts:
            if fact.label not in ("Industry", "Products"):
                continue
            for term in (t.strip() for t in fact.value.split(",")):
                if len(term) >= 4 and re.search(rf"(?<![a-z]){re.escape(term.lower())}(?![a-z])", lower):
                    mentions.append(term)
    return Relevance(roles, scored, tuple(dict.fromkeys(mentions)))
