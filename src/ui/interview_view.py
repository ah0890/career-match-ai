"""Interview question cards."""

from __future__ import annotations

from html import escape

from src.interview.prep import Question
from src.interview.study import StudyTopic
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


_PRIORITY_TONE = {"High": "danger", "Medium": "warning", "Low": "neutral"}


def study_topic_html(topic: StudyTopic) -> str:
    acts = "".join(f"<li>{escape(a)}</li>" for a in topic.activities)
    link = (f'<p><a class="cm-source-link" href="{escape(topic.link, quote=True)}" target="_blank" rel="noopener">'
            f"Official documentation</a></p>" if topic.link else "")
    return (
        f'<div class="cm-study">'
        f'<div class="cm-badge-row">{badge_html(f"{topic.priority} priority", _PRIORITY_TONE[topic.priority])}'
        f'{badge_html(f"Effort: {topic.effort}", "neutral")}</div>'
        f"<h3>{escape(topic.title)}</h3><p>{escape(topic.why)}</p>"
        f'<ul class="cm-q-material">{acts}</ul>{link}</div>'
    )
