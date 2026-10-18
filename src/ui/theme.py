"""Global stylesheet built from design tokens.

CSS targets only CareerMatch's own ``cm-*`` classes plus the documented top-level
``.stApp`` container, so it does not depend on Streamlit's internal DOM details.
"""

from __future__ import annotations

import streamlit as st

from src.ui.tokens import css_variables

_BASE_CSS = """
.stApp { font-family: var(--cm-font-family); }

.cm-page-header { margin: 0 0 var(--cm-space-lg) 0; }
.cm-page-header h1 {
  font-size: var(--cm-font-page-title);
  line-height: 1.2;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: var(--cm-color-text-primary);
  margin: 0 0 var(--cm-space-xs) 0;
  padding: 0;
}
.cm-page-header p {
  font-size: var(--cm-font-body);
  color: var(--cm-color-text-secondary);
  margin: 0;
  max-width: 68ch;
  line-height: 1.55;
}

.cm-empty {
  background: var(--cm-color-surface);
  border: 1px dashed var(--cm-color-border);
  border-radius: var(--cm-radius-lg);
  padding: var(--cm-space-xl) var(--cm-space-lg);
  text-align: center;
}
.cm-empty h3 {
  font-size: var(--cm-font-card-title);
  font-weight: 600;
  color: var(--cm-color-text-primary);
  margin: 0 0 var(--cm-space-sm) 0;
  padding: 0;
}
.cm-empty p {
  font-size: var(--cm-font-body);
  color: var(--cm-color-text-secondary);
  margin: 0 auto;
  max-width: 56ch;
  line-height: 1.55;
}
"""


def build_stylesheet() -> str:
    return f"<style>\n{css_variables()}\n{_BASE_CSS}\n</style>"


def apply_theme() -> None:
    """Inject the global stylesheet (call once per script run)."""
    st.html(build_stylesheet())
