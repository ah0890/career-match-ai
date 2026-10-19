"""Company profile presentation. Every fact is shown with a link to its source."""

from __future__ import annotations

from html import escape

from src.company.models import CompanyProfile, Fact, Source, Summary


def _source_link(source: Source) -> str:
    return (f'<a class="cm-source-link" href="{escape(source.url, quote=True)}" target="_blank" rel="noopener">'
            f"{escape(source.name)}</a>")


def facts_html(facts: tuple[Fact, ...], empty: str) -> str:
    if not facts:
        return f'<p class="cm-chip-empty">{escape(empty)}</p>'
    rows = "".join(
        f"<tr><th scope=\"row\">{escape(f.label)}</th><td>{escape(f.value)}"
        + (f'<div class="cm-fact-asof">{escape(f.as_of if f.as_of.startswith("since") else "As of " + f.as_of)}</div>'
           if f.as_of else "")
        + f"</td><td class=\"cm-fact-source\">{_source_link(f.source)}</td></tr>"
        for f in facts
    )
    return (f'<div class="cm-card cm-compare-wrap"><table class="cm-facts"><thead><tr><th scope="col">Fact</th>'
            f'<th scope="col">Value</th><th scope="col">Source</th></tr></thead><tbody>{rows}</tbody></table></div>')


def summary_html(summary: Summary | None) -> str:
    if summary is None:
        return '<p class="cm-chip-empty">No encyclopaedia summary is available for this company.</p>'
    s = summary.source
    return (f'<div class="cm-card cm-company-summary"><p>{escape(summary.text)}</p>'
            f'<div class="cm-muted">From {_source_link(s)}, available under {escape(s.licence)}. '
            f"Text may have been shortened.</div></div>")


def profile_header_html(profile: CompanyProfile) -> str:
    desc = f"<p>{escape(profile.description)}</p>" if profile.description else ""
    site = (f'<a class="cm-link-btn" href="{escape(profile.official_website, quote=True)}" target="_blank" '
            f'rel="noopener">Official website <span aria-hidden="true">↗</span></a>'
            if profile.official_website else '<span class="cm-muted">Official website not available</span>')
    return (f'<div class="cm-company-head"><div><h2>{escape(profile.name)}</h2>{desc}</div>'
            f'<div class="cm-job-links">{site}</div></div>')


def sources_html(profile: CompanyProfile) -> str:
    items = "".join(f"<li>{_source_link(s)} — {escape(s.licence)}</li>" for s in profile.sources)
    return (f'<ul class="cm-source-list">{items}</ul>'
            f'<p class="cm-muted">Retrieved {profile.retrieved_at.astimezone():%d %b %Y, %H:%M}.</p>')
