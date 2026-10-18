"""Reusable presentation helpers.

Each component has a pure ``*_html`` builder (unit-testable) and a thin renderer.
All dynamic text is HTML-escaped; callers never pass raw HTML.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Iterable, Literal

import streamlit as st

Tone = Literal["neutral", "info", "success", "warning", "danger"]
_TONES: frozenset[str] = frozenset({"neutral", "info", "success", "warning", "danger"})


def _tone(tone: str) -> str:
    if tone not in _TONES:
        raise ValueError(f"Unknown tone: {tone!r}")
    return tone


# --- Headers ---------------------------------------------------------------

def page_header_html(title: str, subtitle: str | None = None, eyebrow: str | None = None) -> str:
    eb = f'<div class="cm-eyebrow">{escape(eyebrow)}</div>' if eyebrow else ""
    sub = f"<p>{escape(subtitle)}</p>" if subtitle else ""
    return f'<header class="cm-page-header">{eb}<h1>{escape(title)}</h1>{sub}</header>'


def section_header_html(title: str, subtitle: str | None = None) -> str:
    sub = f"<p>{escape(subtitle)}</p>" if subtitle else ""
    return f'<div class="cm-section-header"><h2>{escape(title)}</h2>{sub}</div>'


# --- Status & feedback -----------------------------------------------------

def badge_html(label: str, tone: Tone = "neutral") -> str:
    """A status pill. The label text always carries the meaning (never colour alone)."""
    return f'<span class="cm-badge cm-tone-{_tone(tone)}">{escape(label)}</span>'


def notice_html(message: str, tone: Tone = "info", title: str | None = None) -> str:
    head = f"<strong>{escape(title)}</strong> " if title else ""
    role = "alert" if tone == "danger" else "status"
    return f'<div class="cm-notice cm-tone-{_tone(tone)}" role="{role}">{head}{escape(message)}</div>'


def empty_state_html(title: str, message: str) -> str:
    return (
        f'<section class="cm-empty" role="status">'
        f"<h3>{escape(title)}</h3><p>{escape(message)}</p></section>"
    )


# --- Cards -----------------------------------------------------------------

@dataclass(frozen=True)
class Metric:
    label: str
    value: str
    caption: str | None = None


def metric_grid_html(metrics: Iterable[Metric]) -> str:
    tiles = []
    for m in metrics:
        cap = f'<div class="cm-metric-caption">{escape(m.caption)}</div>' if m.caption else ""
        tiles.append(
            f'<div class="cm-card cm-metric"><div class="cm-metric-label">{escape(m.label)}</div>'
            f'<div class="cm-metric-value">{escape(m.value)}</div>{cap}</div>'
        )
    return f'<div class="cm-grid cm-grid-metrics">{"".join(tiles)}</div>'


@dataclass(frozen=True)
class Feature:
    title: str
    description: str


def feature_grid_html(features: Iterable[Feature]) -> str:
    cards = "".join(
        f'<div class="cm-card cm-feature"><h4>{escape(f.title)}</h4><p>{escape(f.description)}</p></div>'
        for f in features
    )
    return f'<div class="cm-grid cm-grid-features">{cards}</div>'


@dataclass(frozen=True)
class Step:
    title: str
    description: str
    done: bool = False


def steps_html(steps: Iterable[Step]) -> str:
    items = []
    for i, s in enumerate(steps, start=1):
        state = badge_html("Done", "success") if s.done else badge_html("To do", "neutral")
        items.append(
            f'<li class="cm-step{" cm-step-done" if s.done else ""}">'
            f'<span class="cm-step-num" aria-hidden="true">{i}</span>'
            f'<div class="cm-step-body"><div class="cm-step-title">{escape(s.title)} {state}</div>'
            f"<p>{escape(s.description)}</p></div></li>"
        )
    return f'<ol class="cm-card cm-steps">{"".join(items)}</ol>'


def key_value_html(rows: Iterable[tuple[str, str]]) -> str:
    body = "".join(f"<dt>{escape(k)}</dt><dd>{escape(v)}</dd>" for k, v in rows)
    return f'<dl class="cm-card cm-kv">{body}</dl>'


# --- Renderers -------------------------------------------------------------

def _render(html: str) -> None:
    st.html(html)


def page_header(title: str, subtitle: str | None = None, eyebrow: str | None = None) -> None:
    _render(page_header_html(title, subtitle, eyebrow))


def section_header(title: str, subtitle: str | None = None) -> None:
    _render(section_header_html(title, subtitle))


def notice(message: str, tone: Tone = "info", title: str | None = None) -> None:
    _render(notice_html(message, tone, title))


def empty_state(title: str, message: str) -> None:
    _render(empty_state_html(title, message))


def metric_grid(metrics: Iterable[Metric]) -> None:
    _render(metric_grid_html(metrics))


def feature_grid(features: Iterable[Feature]) -> None:
    _render(feature_grid_html(features))


def steps(items: Iterable[Step]) -> None:
    _render(steps_html(items))


def key_value(rows: Iterable[tuple[str, str]]) -> None:
    _render(key_value_html(rows))
