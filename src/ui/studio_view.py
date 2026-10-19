"""Presentational helpers for CV Studio (HTML snippets are escaped; no CV text is ever trusted as HTML)."""

from __future__ import annotations

from html import escape

from src.ui.components import Tone, badge_html
from src.workspace.review import CATEGORIES

CATEGORY_LABELS = {k: v[0] for k, v in CATEGORIES.items()} | {"tailoring": "Job-specific"}
SOURCE_LABELS = {"rules": "Built-in rules", "claude": "Claude", "tailoring": "Job tailoring"}
STATUS_TONES: dict[str, Tone] = {"pending": "info", "accepted": "success", "edited": "success", "rejected": "neutral",
                                 "kept": "neutral"}
PRIORITY_TONES: dict[str, Tone] = {"High": "danger", "Medium": "warning", "Low": "neutral"}
PROVENANCE_LABELS = {"extracted": "From your upload", "verified": "Confirmed by you", "edited": "Written by you",
                     "suggested": "Accepted suggestion", "unverified": "Needs your confirmation"}

WORKFLOW = ("Upload", "Review", "Approve changes", "Missing information", "Preview & download")


def workflow_html(done: dict[str, bool], current: str) -> str:
    """A compact progress indicator. State is written out in text, not shown by colour alone."""
    parts = []
    for n, name in enumerate(WORKFLOW, start=1):
        state = "done" if done.get(name) else ("current" if name == current else "todo")
        label = {"done": "done", "current": "in progress", "todo": "to do"}[state]
        parts.append(f'<li class="cm-flow-step cm-flow-{state}"><span class="cm-flow-num">{n}</span>'
                     f'<span class="cm-flow-name">{escape(name)}</span>'
                     f'<span class="cm-sr">({label})</span></li>')
    return f'<ol class="cm-flow" aria-label="CV workflow">{"".join(parts)}</ol>'


def rec_badges_html(*, status: str, status_label: str, priority: str, category: str, source: str) -> str:
    return ('<div class="cm-badge-row">'
            + badge_html(status_label, STATUS_TONES.get(status, "neutral"))
            + badge_html(f"{priority} priority", PRIORITY_TONES.get(priority, "neutral"))
            + badge_html(CATEGORY_LABELS.get(category, category.title()), "neutral")
            + badge_html(SOURCE_LABELS.get(source, source.title()), "info" if source == "claude" else "neutral")
            + "</div>")


def before_after_html(before: str, after: str, *, before_label: str = "Current", after_label: str = "Suggested") -> str:
    def block(label: str, text: str, cls: str) -> str:
        body = escape(text).replace("\n", "<br>") if text else "<em>(nothing)</em>"
        return f'<div class="cm-diff-col {cls}"><div class="cm-diff-label">{escape(label)}</div><p>{body}</p></div>'

    return f'<div class="cm-diff">{block(before_label, before, "cm-diff-before")}' \
           f'{block(after_label, after, "cm-diff-after")}</div>'


def changes_html(changes) -> str:
    if not changes:
        return '<p class="cm-chip-empty">No differences.</p>'
    rows = []
    for c in changes:
        tone = {"added": "success", "removed": "danger", "changed": "warning"}[c.kind]
        rows.append(
            f"<tr><td>{badge_html(c.kind.title(), tone)}</td><td>{escape(c.where)}</td>"
            f"<td>{escape(c.before) or '—'}</td><td>{escape(c.after) or '—'}</td></tr>")
    return ('<div class="cm-table-wrap"><table class="cm-table"><thead><tr><th>Change</th><th>Where</th>'
            "<th>Before</th><th>After</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")


def checks_html(checks: list[dict]) -> str:
    items = []
    for c in checks:
        mark, tone = ("Passed", "success") if c["passed"] else ("Failed", "danger")
        items.append(f'<li>{badge_html(mark, tone)} <strong>{escape(c["label"])}</strong> — '
                     f'{escape(c["detail"])}</li>')
    return f'<ul class="cm-checks">{"".join(items)}</ul>'
