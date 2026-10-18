"""Job result cards and provider status rows."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape

from src.jobs.models import EmploymentType, JobPosting, WorkArrangement
from src.providers.base import ProviderResult
from src.ui.components import badge_html

_ARRANGEMENT_LABELS = {
    WorkArrangement.REMOTE: "Remote", WorkArrangement.HYBRID: "Hybrid", WorkArrangement.ONSITE: "On-site",
}
_EMPLOYMENT_LABELS = {
    EmploymentType.FULL_TIME: "Full-time", EmploymentType.PART_TIME: "Part-time",
    EmploymentType.CONTRACT: "Contract", EmploymentType.TEMPORARY: "Temporary",
    EmploymentType.INTERNSHIP: "Internship",
}


def posted_label(posted_at: datetime | None, now: datetime | None = None) -> str:
    if posted_at is None:
        return "Posting date not provided"
    now = now or datetime.now(timezone.utc)
    days = (now - posted_at).days
    if days <= 0:
        return "Posted today"
    if days == 1:
        return "Posted yesterday"
    if days < 30:
        return f"Posted {days} days ago"
    return f"Posted {posted_at:%d %b %Y}"


def _salary(job: JobPosting) -> str | None:
    if job.salary_min or job.salary_max:
        cur = f"{job.salary_currency} " if job.salary_currency else ""
        lo = f"{job.salary_min:,.0f}" if job.salary_min else ""
        hi = f"{job.salary_max:,.0f}" if job.salary_max else ""
        rng = f"{lo} – {hi}" if lo and hi and lo != hi else (lo or hi)
        return f"{cur}{rng}" + (" (estimated by source)" if job.salary_is_estimate else "")
    return job.salary_text


def _link(url: str, label: str, primary: bool = False) -> str:
    cls = "cm-link-btn cm-link-primary" if primary else "cm-link-btn"
    return (f'<a class="{cls}" href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">'
            f"{escape(label)} <span aria-hidden=\"true\">↗</span></a>")


def job_card_html(job: JobPosting, snippet_chars: int = 260) -> str:
    meta = " · ".join(escape(x) for x in (job.company or "Company not provided", job.location) if x)
    badges = [badge_html(_ARRANGEMENT_LABELS[job.work_arrangement], "info")] \
        if job.work_arrangement in _ARRANGEMENT_LABELS else []
    if job.employment_type in _EMPLOYMENT_LABELS:
        badges.append(badge_html(_EMPLOYMENT_LABELS[job.employment_type], "neutral"))
    salary = _salary(job)
    if salary:
        badges.append(badge_html(salary, "neutral"))
    snippet = job.description[:snippet_chars].rsplit(" ", 1)[0] + "…" if len(job.description) > snippet_chars \
        else job.description
    links = []
    if job.apply_url:
        links.append(_link(job.apply_url, "Apply on employer site", primary=True))
    if job.listing_url:
        links.append(_link(job.listing_url, f"View original listing on {job.source_name}", primary=not job.apply_url))
    if not links:
        links.append('<span class="cm-muted">No valid listing link was provided by the source.</span>')
    return (
        f'<article class="cm-card cm-job">'
        f'<div class="cm-job-head"><h3>{escape(job.title)}</h3>'
        f'<span class="cm-job-posted">{escape(posted_label(job.posted_at))}</span></div>'
        f'<div class="cm-job-meta">{meta}</div>'
        f'<div class="cm-badge-row">{"".join(badges)}</div>'
        f'<p class="cm-job-snippet">{escape(snippet)}</p>'
        f'<div class="cm-job-foot"><span class="cm-job-source">Source: {escape(job.source_name)}</span>'
        f'<div class="cm-job-links">{"".join(links)}</div></div>'
        f"</article>"
    )


def provider_result_badge(result: ProviderResult) -> tuple[str, str]:
    if result.status == "ok":
        return ("Cached results" if result.from_cache else "Live results"), "success"
    if result.status == "skipped":
        return "Not searched", "neutral"
    return "Failed", "danger"
