"""Application cards for the tracker."""

from __future__ import annotations

from datetime import date
from html import escape

from src.db.models import Application, ApplicationEvent
from src.jobs.models import safe_url
from src.tracker.repository import STATUS_TONES
from src.ui.components import badge_html


def follow_up_label(app: Application, today: date | None = None) -> tuple[str, str] | None:
    if not app.next_action_on:
        return None
    days = (app.next_action_on - (today or date.today())).days
    if days < 0:
        return f"Follow-up overdue by {-days} day(s)", "danger"
    if days == 0:
        return "Follow-up due today", "warning"
    return f"Follow-up in {days} day(s)", "info" if days > 3 else "warning"


def application_card_html(app: Application, today: date | None = None) -> str:
    meta = " · ".join(escape(x) for x in (app.company or "Company not provided", app.location) if x)
    badges = [badge_html(app.status, STATUS_TONES.get(app.status, "neutral"))]
    if app.recommendation:
        badges.append(badge_html(f"{app.recommendation} ({app.match_score:.0f}) when saved"
                                 if app.match_score is not None else app.recommendation, "neutral"))
    if fu := follow_up_label(app, today):
        badges.append(badge_html(*fu))
    details = []
    if app.applied_on:
        details.append(f"Applied {app.applied_on:%d %b %Y}")
    if app.next_action:
        details.append(f"Next: {escape(app.next_action)}"
                       + (f" ({app.next_action_on:%d %b %Y})" if app.next_action_on else ""))
    detail_html = f'<div class="cm-job-meta">{" · ".join(details)}</div>' if details else ""
    url = safe_url(app.listing_url)  # re-checked on display: the database file could be edited outside the app
    link = (f'<a class="cm-link-btn" href="{escape(url, quote=True)}" target="_blank" rel="noopener">'
            f'View listing <span aria-hidden="true">↗</span></a>' if url else "")
    source = f'<span class="cm-job-source">Source: {escape(app.source_name)}</span>' if app.source_name else ""
    return (
        f'<article class="cm-card cm-job cm-app">'
        f'<div class="cm-job-head"><h3>{escape(app.title)}</h3>'
        f'<span class="cm-job-posted">Updated {app.updated_at:%d %b %Y}</span></div>'
        f'<div class="cm-job-meta">{meta}</div><div class="cm-badge-row">{"".join(badges)}</div>{detail_html}'
        f'<div class="cm-job-foot">{source}<div class="cm-job-links">{link}</div></div></article>'
    )


_SOURCE_LABELS = {"manual": "by you", "email": "from email", "app": "in CareerMatch"}


def timeline_html(events: list[ApplicationEvent]) -> str:
    """The application's history, oldest first. Email events link to the original message when possible."""
    if not events:
        return '<p class="cm-chip-empty">No events yet.</p>'
    items = []
    for e in sorted(events, key=lambda e: (e.occurred_at.replace(tzinfo=None), e.id or 0)):
        meta = [_SOURCE_LABELS.get(e.source, e.source)]
        if e.confidence is not None:
            meta.append(f"{round(100 * e.confidence)}% confidence")
        link = ""
        if e.message is not None and (url := safe_url(e.message.web_link)):
            link = (f' · <a href="{escape(url, quote=True)}" target="_blank" rel="noopener">open email '
                    f'<span aria-hidden="true">↗</span></a>')
        items.append(
            f'<li><span class="cm-tl-date">{e.occurred_at:%d %b %Y}</span>'
            f'<div class="cm-tl-body">{badge_html(e.kind, STATUS_TONES.get(e.kind, "neutral"))}'
            f'<div class="cm-tl-summary">{escape(e.summary)}</div>'
            f'<div class="cm-list-meta">{escape(" · ".join(meta))}{link}</div></div></li>')
    return f'<ol class="cm-card cm-timeline">{"".join(items)}</ol>'
