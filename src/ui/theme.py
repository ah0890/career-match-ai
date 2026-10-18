"""Global stylesheet built from design tokens.

Streamlit's own widgets are styled through `.streamlit/config.toml`. This CSS
targets only CareerMatch's ``cm-*`` classes, so it does not depend on
Streamlit's internal DOM structure.
"""

from __future__ import annotations

import streamlit as st

from src.ui.tokens import css_variables

_BASE_CSS = """
/* ---------- Headers ---------- */
.cm-page-header { margin: 0 0 var(--cm-space-sm) 0; }
.cm-eyebrow {
  font-size: var(--cm-font-label); font-weight: 600; letter-spacing: 0.06em;
  text-transform: uppercase; color: var(--cm-color-link); margin-bottom: var(--cm-space-xs);
}
.cm-page-header h1 {
  font-size: var(--cm-font-page-title); line-height: 1.2; font-weight: 700;
  letter-spacing: -0.015em; color: var(--cm-color-text-primary); margin: 0 0 var(--cm-space-xs) 0; padding: 0;
}
.cm-page-header p, .cm-section-header p {
  font-size: var(--cm-font-body); color: var(--cm-color-text-secondary);
  margin: 0; max-width: 70ch; line-height: 1.55;
}
.cm-section-header { margin: var(--cm-space-md) 0 var(--cm-space-sm) 0; }
.cm-section-header h2 {
  font-size: var(--cm-font-section); line-height: 1.3; font-weight: 650;
  color: var(--cm-color-text-primary); margin: 0 0 var(--cm-space-xs) 0; padding: 0;
}

/* ---------- Cards & grids ---------- */
.cm-card {
  background: var(--cm-color-surface); border: 1px solid var(--cm-color-border);
  border-radius: var(--cm-radius-lg); box-shadow: var(--cm-shadow-card);
}
.cm-grid { display: grid; gap: var(--cm-space-md); }
.cm-grid-metrics { grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); }
.cm-grid-features { grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }

.cm-metric { padding: var(--cm-space-md) var(--cm-space-lg); }
.cm-metric-label { font-size: var(--cm-font-label); color: var(--cm-color-text-secondary); font-weight: 500; }
.cm-metric-value {
  font-size: 28px; font-weight: 700; color: var(--cm-color-text-primary);
  line-height: 1.25; margin-top: var(--cm-space-xs); font-variant-numeric: tabular-nums;
}
.cm-metric-caption { font-size: var(--cm-font-caption); color: var(--cm-color-text-secondary); margin-top: 2px; }

.cm-feature { padding: var(--cm-space-lg); }
.cm-feature h4 {
  font-size: var(--cm-font-card-title); font-weight: 600; color: var(--cm-color-text-primary);
  margin: 0 0 var(--cm-space-sm) 0; padding: 0;
}
.cm-feature p { font-size: 14px; color: var(--cm-color-text-secondary); margin: 0; line-height: 1.55; }

/* ---------- Steps ---------- */
.cm-steps { list-style: none; margin: 0; padding: var(--cm-space-sm) var(--cm-space-lg); }
.cm-step { display: flex; gap: var(--cm-space-md); padding: var(--cm-space-md) 0; border-bottom: 1px solid var(--cm-color-border); }
.cm-step:last-child { border-bottom: none; }
.cm-step-num {
  flex: 0 0 28px; height: 28px; border-radius: var(--cm-radius-pill);
  background: var(--cm-color-surface-subtle); color: var(--cm-color-primary);
  font-weight: 700; font-size: 13px; display: flex; align-items: center; justify-content: center;
}
.cm-step-done .cm-step-num { background: var(--cm-color-success-bg); color: var(--cm-color-success); }
.cm-step-title { font-weight: 600; color: var(--cm-color-text-primary); font-size: var(--cm-font-body); }
.cm-step-title .cm-badge { margin-left: var(--cm-space-sm); vertical-align: 1px; }
.cm-step p { margin: 2px 0 0 0; font-size: 14px; color: var(--cm-color-text-secondary); line-height: 1.5; }

/* ---------- Key/value ---------- */
.cm-kv {
  display: grid; grid-template-columns: minmax(140px, max-content) 1fr;
  gap: var(--cm-space-sm) var(--cm-space-lg); padding: var(--cm-space-lg); margin: 0;
}
.cm-kv dt { color: var(--cm-color-text-secondary); font-size: 14px; }
.cm-kv dd { margin: 0; color: var(--cm-color-text-primary); font-size: 14px; font-weight: 500; overflow-wrap: anywhere; }

/* ---------- Badges & notices ---------- */
.cm-badge {
  display: inline-block; padding: 2px 10px; border-radius: var(--cm-radius-pill);
  font-size: 12px; font-weight: 600; line-height: 1.6; border: 1px solid transparent; white-space: nowrap;
}
.cm-notice {
  border-radius: var(--cm-radius-md); padding: 12px var(--cm-space-md);
  font-size: 14px; line-height: 1.55; border: 1px solid transparent;
}
.cm-tone-neutral { background: var(--cm-color-surface-subtle); color: var(--cm-color-text-secondary); border-color: var(--cm-color-border); }
.cm-tone-info { background: #EEF1FD; color: var(--cm-color-primary); border-color: #D9DFFB; }
.cm-tone-success { background: var(--cm-color-success-bg); color: var(--cm-color-success); border-color: #CDEBDD; }
.cm-tone-warning { background: var(--cm-color-warning-bg); color: var(--cm-color-warning); border-color: #F5E2B8; }
.cm-tone-danger { background: var(--cm-color-danger-bg); color: var(--cm-color-danger); border-color: #F7D3D7; }

/* ---------- Status legend ---------- */
.cm-status-legend { list-style: none; margin: 0; padding: var(--cm-space-sm) var(--cm-space-lg); }
.cm-status-legend li {
  display: grid; grid-template-columns: 110px 1fr; align-items: center; gap: var(--cm-space-md);
  padding: 10px 0; border-bottom: 1px solid var(--cm-color-border); font-size: 14px; color: var(--cm-color-text-secondary);
}
.cm-status-legend .cm-badge { justify-self: start; }
.cm-status-legend li:last-child { border-bottom: none; }

/* ---------- Empty state ---------- */
.cm-empty {
  background: var(--cm-color-surface); border: 1px dashed #CDD5E1;
  border-radius: var(--cm-radius-lg); padding: var(--cm-space-xl) var(--cm-space-lg); text-align: center;
}
.cm-empty h3 {
  font-size: var(--cm-font-card-title); font-weight: 600; color: var(--cm-color-text-primary);
  margin: 0 0 var(--cm-space-sm) 0; padding: 0;
}
.cm-empty p { font-size: var(--cm-font-body); color: var(--cm-color-text-secondary); margin: 0 auto; max-width: 56ch; line-height: 1.55; }

/* ---------- Narrow screens ---------- */
@media (max-width: 640px) {
  .cm-page-header h1 { font-size: 24px; }
  .cm-section-header h2 { font-size: 19px; }
  .cm-metric-value { font-size: 24px; }
  .cm-kv { grid-template-columns: 1fr; gap: 2px; }
  .cm-kv dd { margin-bottom: var(--cm-space-sm); }
  .cm-empty { padding: var(--cm-space-lg) var(--cm-space-md); }
}
"""


def build_stylesheet() -> str:
    return f"<style>\n{css_variables()}\n{_BASE_CSS}\n</style>"


def apply_theme() -> None:
    """Inject the global stylesheet (call once per script run)."""
    st.html(build_stylesheet())
