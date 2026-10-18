"""Score visualisation: headline score cards, component bars and chip lists."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Iterable

from src.ui.components import Tone, badge_html


def score_tone(percent: float) -> Tone:
    if percent >= 85:
        return "success"
    if percent >= 70:
        return "info"
    if percent >= 50:
        return "warning"
    return "danger"


def score_card_html(score: int, band: str, title: str, explanation: str, *, out_of: int = 100) -> str:
    tone = score_tone(100 * score / out_of if out_of else 0)
    return (
        f'<div class="cm-card cm-score-card">'
        f'<div class="cm-score-title">{escape(title)}</div>'
        f'<div class="cm-score-value"><span>{score}</span><small>/ {out_of}</small></div>'
        f"{badge_html(band, tone)}"
        f'<p>{escape(explanation)}</p></div>'
    )


@dataclass(frozen=True)
class Bar:
    label: str
    value: float
    max_value: float
    caption: str | None = None


def bars_html(bars: Iterable[Bar]) -> str:
    rows = []
    for b in bars:
        pct = 0 if b.max_value <= 0 else max(0, min(100, round(100 * b.value / b.max_value)))
        tone = score_tone(pct)
        cap = f'<div class="cm-bar-caption">{escape(b.caption)}</div>' if b.caption else ""
        rows.append(
            f'<div class="cm-bar-row">'
            f'<div class="cm-bar-head"><span>{escape(b.label)}</span>'
            f'<span class="cm-bar-num">{b.value:g} / {b.max_value:g}</span></div>'
            f'<div class="cm-bar-track" role="img" aria-label="{escape(b.label)}: {b.value:g} of {b.max_value:g}">'
            f'<div class="cm-bar-fill cm-fill-{tone}" style="width:{pct}%"></div></div>{cap}</div>'
        )
    return f'<div class="cm-card cm-bars">{"".join(rows)}</div>'


def chips_html(items: Iterable[str], tone: Tone = "neutral", empty: str = "None") -> str:
    items = list(items)
    if not items:
        return f'<p class="cm-chip-empty">{escape(empty)}</p>'
    chips = "".join(f'<span class="cm-chip cm-tone-{tone}">{escape(i)}</span>' for i in items)
    return f'<div class="cm-chip-list">{chips}</div>'
