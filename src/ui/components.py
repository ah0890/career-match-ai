"""Reusable presentation helpers.

All dynamic text is HTML-escaped before rendering; callers never pass raw HTML.
"""

from __future__ import annotations

from html import escape

import streamlit as st


def page_header_html(title: str, subtitle: str | None = None) -> str:
    sub = f"<p>{escape(subtitle)}</p>" if subtitle else ""
    return f'<header class="cm-page-header"><h1>{escape(title)}</h1>{sub}</header>'


def empty_state_html(title: str, message: str) -> str:
    return (
        f'<section class="cm-empty" role="status">'
        f"<h3>{escape(title)}</h3><p>{escape(message)}</p></section>"
    )


def page_header(title: str, subtitle: str | None = None) -> None:
    st.html(page_header_html(title, subtitle))


def empty_state(title: str, message: str) -> None:
    st.html(empty_state_html(title, message))
