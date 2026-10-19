"""Interview question cards."""

from __future__ import annotations

from html import escape

from src.interview.prep import Question
from src.ui.components import badge_html

_LIKELIHOOD_TONE = {"Very likely": "danger", "Likely": "warning", "Possible": "neutral"}


def question_card_html(q: Question) -> str:
    material = (
        '<div class="cm-q-label">From your CV</div><ul class="cm-q-material">'
        + "".join(f"<li>{escape(m)}</li>" for m in q.cv_material) + "</ul>"
        if q.cv_material else
        "" if q.kind in ("Motivation", "Company") else
        '<div class="cm-q-label">From your CV</div><p class="cm-muted">No closely related line was found in your CV.</p>'
    )
    return (
        f'<article class="cm-card cm-question">'
        f'<div class="cm-badge-row">{badge_html(q.likelihood, _LIKELIHOOD_TONE[q.likelihood])}'
        f'{badge_html(q.kind, "info")}</div>'
        f"<h3>{escape(q.text)}</h3>"
        f'<div class="cm-q-label">Why it may come up</div><p>{escape(q.why)}</p>'
        f"{material}"
        f'<div class="cm-q-label">How to prepare</div><p>{escape(q.guidance)}</p>'
        f"</article>"
    )
