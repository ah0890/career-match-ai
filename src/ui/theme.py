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
  display: inline-block; font-size: 11px; font-weight: 700; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--cm-color-link); background: #E8F0FE;
  border: 1px solid #D3E1FC; border-radius: var(--cm-radius-pill); padding: 3px 10px;
  margin-bottom: var(--cm-space-sm);
}
.cm-page-header h1 {
  font-size: var(--cm-font-page-title); line-height: 1.2; font-weight: 750;
  letter-spacing: -0.022em; color: var(--cm-color-text-primary); margin: 0 0 var(--cm-space-xs) 0; padding: 0;
}
.cm-page-header p, .cm-section-header p {
  font-size: var(--cm-font-body); color: var(--cm-color-text-secondary);
  margin: 0; max-width: 70ch; line-height: 1.55;
}
.cm-section-header { margin: var(--cm-space-lg) 0 var(--cm-space-sm) 0; }
.cm-section-header h2 {
  font-size: var(--cm-font-section); line-height: 1.3; font-weight: 700; letter-spacing: -0.012em;
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

.cm-metric { padding: 18px var(--cm-space-lg); position: relative; overflow: hidden; }
.cm-metric::before { content: ""; position: absolute; inset: 0 auto 0 0; width: 3px; background: var(--cm-color-accent); }
.cm-metric-label { font-size: 12px; color: var(--cm-color-text-secondary); font-weight: 650;
  text-transform: uppercase; letter-spacing: 0.05em; }
.cm-metric-value {
  font-size: 30px; font-weight: 750; letter-spacing: -0.02em; color: var(--cm-color-text-primary);
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
  background: #E8F0FE; color: var(--cm-color-link);
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
.cm-badge-row { display: flex; flex-wrap: wrap; gap: var(--cm-space-sm); }
.cm-badge {
  display: inline-block; padding: 2px 10px; border-radius: var(--cm-radius-pill);
  font-size: 12px; font-weight: 600; line-height: 1.6; border: 1px solid transparent; white-space: nowrap;
}
.cm-notice {
  border-radius: var(--cm-radius-md); padding: 12px var(--cm-space-md);
  font-size: 14px; line-height: 1.55; border: 1px solid transparent;
}
.cm-tone-neutral { background: var(--cm-color-surface-subtle); color: var(--cm-color-text-secondary); border-color: var(--cm-color-border); }
.cm-tone-info { background: #E8F0FE; color: var(--cm-color-primary); border-color: #D3E1FC; }
.cm-tone-success { background: var(--cm-color-success-bg); color: var(--cm-color-success); border-color: #C7E9DA; }
.cm-tone-warning { background: var(--cm-color-warning-bg); color: var(--cm-color-warning); border-color: #F6DFB4; }
.cm-tone-danger { background: var(--cm-color-danger-bg); color: var(--cm-color-danger); border-color: #F8D0CC; }

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
  background: var(--cm-color-surface); border: 1px dashed #C9D3E1;
  border-radius: var(--cm-radius-lg); padding: var(--cm-space-xl) var(--cm-space-lg); text-align: center;
}
.cm-empty h3 {
  font-size: var(--cm-font-card-title); font-weight: 600; color: var(--cm-color-text-primary);
  margin: 0 0 var(--cm-space-sm) 0; padding: 0;
}
.cm-empty p { font-size: var(--cm-font-body); color: var(--cm-color-text-secondary); margin: 0 auto; max-width: 56ch; line-height: 1.55; }

/* ---------- Scores ---------- */
.cm-score-card { padding: var(--cm-space-lg); height: 100%; box-sizing: border-box; }
.cm-score-title { font-size: var(--cm-font-label); font-weight: 600; color: var(--cm-color-text-secondary); text-transform: uppercase; letter-spacing: 0.05em; }
.cm-score-value { display: flex; align-items: baseline; gap: 6px; margin: var(--cm-space-sm) 0; font-variant-numeric: tabular-nums; }
.cm-score-value span { font-size: var(--cm-font-score); font-weight: 750; line-height: 1; color: var(--cm-color-text-primary); }
.cm-score-value small { font-size: 16px; color: var(--cm-color-text-secondary); font-weight: 500; }
.cm-score-card p { font-size: 14px; line-height: 1.55; color: var(--cm-color-text-secondary); margin: var(--cm-space-md) 0 0 0; }

.cm-bars { padding: var(--cm-space-md) var(--cm-space-lg); }
.cm-bar-row { padding: 10px 0; }
.cm-bar-head { display: flex; justify-content: space-between; gap: var(--cm-space-md); font-size: 14px; color: var(--cm-color-text-primary); font-weight: 500; }
.cm-bar-num { color: var(--cm-color-text-secondary); font-variant-numeric: tabular-nums; white-space: nowrap; }
.cm-bar-track { height: 8px; background: var(--cm-color-surface-subtle); border-radius: var(--cm-radius-pill); margin-top: 6px; overflow: hidden; }
.cm-bar-fill { height: 100%; border-radius: var(--cm-radius-pill); }
.cm-fill-success { background: var(--cm-color-success); }
.cm-fill-info { background: var(--cm-color-accent); }
.cm-fill-warning { background: #D08A1A; }
.cm-fill-danger { background: var(--cm-color-danger); }
.cm-fill-neutral { background: #8A94A6; }
.cm-bar-caption { font-size: 13px; color: var(--cm-color-text-secondary); margin-top: 4px; }

/* ---------- Chips ---------- */
.cm-chip-list { display: flex; flex-wrap: wrap; gap: 6px; }
.cm-chip { display: inline-block; padding: 3px 10px; border-radius: var(--cm-radius-pill); font-size: 13px; line-height: 1.5; border: 1px solid transparent; }
.cm-chip-empty { font-size: 14px; color: var(--cm-color-text-secondary); margin: 0; }

/* ---------- Lists ---------- */
.cm-list { list-style: none; margin: 0; padding: var(--cm-space-xs) var(--cm-space-lg); }
.cm-list li { display: flex; gap: var(--cm-space-md); align-items: flex-start; padding: 12px 0; border-bottom: 1px solid var(--cm-color-border); }
.cm-list li:last-child { border-bottom: none; }
.cm-list .cm-badge { flex: 0 0 auto; min-width: 88px; text-align: center; box-sizing: border-box; margin-top: 1px; }
.cm-list-title { font-weight: 600; font-size: 14px; color: var(--cm-color-text-primary); }
.cm-list-detail { font-size: 14px; color: var(--cm-color-text-secondary); line-height: 1.5; margin-top: 2px; }
.cm-list-meta { font-size: 12px; color: var(--cm-color-text-secondary); margin-top: 4px; }

/* ---------- Job cards ---------- */
.cm-job { padding: var(--cm-space-lg); margin-bottom: var(--cm-space-md); }
.cm-job-head { display: flex; justify-content: space-between; align-items: baseline; gap: var(--cm-space-md); }
.cm-job-head h3 { font-size: var(--cm-font-card-title); font-weight: 650; color: var(--cm-color-text-primary); margin: 0; padding: 0; line-height: 1.35; }
.cm-job-posted { font-size: 13px; color: var(--cm-color-text-secondary); white-space: nowrap; }
.cm-job-meta { font-size: 14px; color: var(--cm-color-text-secondary); margin: 4px 0 var(--cm-space-sm) 0; }
.cm-job-snippet { font-size: 14px; color: var(--cm-color-text-primary); line-height: 1.55; margin: var(--cm-space-md) 0; }
.cm-job-foot { display: flex; justify-content: space-between; align-items: center; gap: var(--cm-space-md); flex-wrap: wrap;
  border-top: 1px solid var(--cm-color-border); padding-top: var(--cm-space-md); }
.cm-job-also { font-size: 13px; color: var(--cm-color-text-secondary); margin: calc(-1 * var(--cm-space-sm)) 0 var(--cm-space-md) 0; }
.cm-job-also a { color: var(--cm-color-link); }
.cm-job-source { font-size: 13px; color: var(--cm-color-text-secondary); font-weight: 500; }
.cm-job-links { display: flex; gap: var(--cm-space-sm); flex-wrap: wrap; }
.cm-link-btn {
  display: inline-flex; align-items: center; gap: 6px; padding: 7px 14px; border-radius: 8px; font-size: 14px; font-weight: 500;
  text-decoration: none !important; border: 1px solid var(--cm-color-border); color: var(--cm-color-primary) !important; background: var(--cm-color-surface);
}
.cm-link-btn:hover { background: var(--cm-color-surface-subtle); }
.cm-link-btn:focus-visible { outline: 2px solid var(--cm-color-accent); outline-offset: 2px; }
.cm-link-primary { background: var(--cm-color-primary); color: #FFFFFF !important; border-color: var(--cm-color-primary); }
.cm-link-primary:hover { background: var(--cm-color-primary-hover); }
.cm-source-link { color: var(--cm-color-primary) !important; font-weight: 600; }
/* Adzuna's terms require the "Adzuna" label to be at least 116 × 23 px. */
.cm-source-adzuna { display: inline-flex; align-items: center; justify-content: center; min-width: 116px; min-height: 23px;
  padding: 2px 10px; border: 1px solid var(--cm-color-border); border-radius: 6px; font-size: 14px; }
.cm-muted { font-size: 13px; color: var(--cm-color-text-secondary); }

/* ---------- Match summary (inside a job card) ---------- */
.cm-match { display: flex; gap: var(--cm-space-md); align-items: flex-start; margin-top: var(--cm-space-md);
  padding: var(--cm-space-md); border-radius: 10px; background: var(--cm-color-surface-subtle); border: 1px solid var(--cm-color-border); }
.cm-match-score { flex: 0 0 auto; min-width: 84px; padding: 8px 10px; border-radius: 10px; border: 1px solid transparent;
  text-align: center; box-sizing: border-box; font-variant-numeric: tabular-nums; }
.cm-match-score span { display: block; font-size: 28px; font-weight: 750; line-height: 1.1; }
.cm-match-score small { font-size: 12px; font-weight: 500; }
.cm-match-body { display: flex; flex-direction: column; gap: var(--cm-space-sm); min-width: 0; }
.cm-match-headline { font-size: 14px; font-weight: 600; color: var(--cm-color-text-primary); margin: 0; }
.cm-match-row { display: flex; flex-direction: column; gap: 4px; }
.cm-match-row > span { font-size: 12px; font-weight: 600; color: var(--cm-color-text-secondary); text-transform: uppercase; letter-spacing: 0.04em; }

/* ---------- Job description & comparison ---------- */
.cm-job-desc { white-space: pre-line; font-size: 14px; line-height: 1.6; color: var(--cm-color-text-primary);
  max-height: 480px; overflow-y: auto; }
.cm-compare-wrap { overflow-x: auto; padding: 0; }
.cm-compare { width: 100%; border-collapse: collapse; font-size: 14px; min-width: 560px; table-layout: fixed; }
.cm-compare col.cm-compare-label { width: 200px; }
.cm-compare th, .cm-compare td { text-align: left; vertical-align: top; padding: 10px 14px; border-bottom: 1px solid var(--cm-color-border); }
.cm-compare thead th { font-weight: 650; color: var(--cm-color-text-primary); background: var(--cm-color-surface-subtle); }
.cm-compare tbody th { font-weight: 600; color: var(--cm-color-text-secondary); }
.cm-compare td { overflow-wrap: anywhere; }
.cm-compare tbody tr:last-child th, .cm-compare tbody tr:last-child td { border-bottom: none; }

/* ---------- Company profile ---------- */
.cm-company-head { display: flex; justify-content: space-between; align-items: flex-start; gap: var(--cm-space-md); flex-wrap: wrap; margin: var(--cm-space-md) 0; }
.cm-company-head h2 { font-size: 22px; font-weight: 700; margin: 0; padding: 0; color: var(--cm-color-text-primary); }
.cm-company-head p { margin: 4px 0 0 0; color: var(--cm-color-text-secondary); font-size: 15px; }
.cm-company-summary { padding: var(--cm-space-lg); }
.cm-company-summary p { margin: 0 0 var(--cm-space-sm) 0; font-size: 15px; line-height: 1.6; color: var(--cm-color-text-primary); }
.cm-facts { width: 100%; border-collapse: collapse; font-size: 14px; }
.cm-facts th, .cm-facts td { text-align: left; vertical-align: top; padding: 10px 14px; border-bottom: 1px solid var(--cm-color-border); }
.cm-facts thead th { background: var(--cm-color-surface-subtle); font-weight: 650; color: var(--cm-color-text-primary); }
.cm-facts tbody th { font-weight: 600; color: var(--cm-color-text-secondary); width: 30%; }
.cm-facts tbody tr:last-child th, .cm-facts tbody tr:last-child td { border-bottom: none; }
.cm-fact-asof { font-size: 12px; color: var(--cm-color-text-secondary); margin-top: 2px; }
.cm-fact-source { white-space: nowrap; width: 1%; }
.cm-source-list { margin: 0; padding-left: 20px; font-size: 14px; }

/* ---------- Interview questions ---------- */
.cm-question { padding: var(--cm-space-lg); margin-bottom: var(--cm-space-md); }
.cm-question h3 { font-size: 17px; font-weight: 650; line-height: 1.4; margin: var(--cm-space-sm) 0; padding: 0; color: var(--cm-color-text-primary); }
.cm-question p { font-size: 14px; line-height: 1.55; margin: 2px 0 var(--cm-space-sm) 0; color: var(--cm-color-text-primary); }
.cm-q-label { font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; color: var(--cm-color-text-secondary); margin-top: var(--cm-space-sm); }
.cm-study h3 { font-size: 16px; font-weight: 650; margin: var(--cm-space-sm) 0 4px 0; padding: 0; color: var(--cm-color-text-primary); }
.cm-study p { font-size: 14px; line-height: 1.55; margin: 0 0 4px 0; color: var(--cm-color-text-secondary); }
.cm-q-material { margin: 4px 0 var(--cm-space-sm) 0; padding-left: 20px; font-size: 14px; line-height: 1.5; color: var(--cm-color-text-primary); }

/* ---------- Premium surfaces ----------
   Keyed Streamlit containers get an "st-key-KEY" class; only our own cm_* keys are styled. */
.st-key-cm_hero {
  background: radial-gradient(120% 140% at 100% 0%, #24478F 0%, rgba(36, 71, 143, 0) 55%),
              linear-gradient(135deg, var(--cm-color-sidebar) 0%, var(--cm-color-primary) 100%);
  border-radius: var(--cm-radius-xl); padding: 36px 36px 28px 36px; box-shadow: var(--cm-shadow-raised);
  margin-bottom: var(--cm-space-sm);
}
.st-key-cm_hero .cm-eyebrow { color: #CFE0FF; background: rgba(255, 255, 255, 0.08); border-color: rgba(255, 255, 255, 0.16); }
.st-key-cm_hero .cm-page-header h1 { color: #FFFFFF; font-size: 34px; }
.st-key-cm_hero .cm-page-header p { color: var(--cm-color-sidebar-text); font-size: 16px; }
.st-key-cm_hero label, .st-key-cm_hero label p { color: var(--cm-color-sidebar-text) !important; font-weight: 600; }
.st-key-cm_hero [data-testid="stFormSubmitButton"] button {
  background: var(--cm-color-accent); border-color: var(--cm-color-accent); color: #FFFFFF;
}
.st-key-cm_hero [data-testid="stFormSubmitButton"] button:hover { background: var(--cm-color-link); border-color: var(--cm-color-link); }
.cm-hero-points { display: flex; flex-wrap: wrap; gap: 8px 20px; margin: 4px 0 0 0 !important; padding: 0 !important; list-style: none; }
.cm-hero-points li { margin: 0 !important; padding: 0 !important; }
.cm-hero-points li { color: var(--cm-color-sidebar-text); font-size: 13px; display: flex; align-items: center; gap: 8px; }
.cm-hero-points li::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: #7FA6FF; }

/* One card per job: the summary, its details and its actions sit together. */
[class*="st-key-cm_job_"] {
  background: var(--cm-color-surface); border: 1px solid var(--cm-color-border) !important;
  border-radius: var(--cm-radius-lg); box-shadow: var(--cm-shadow-card);
  padding: 4px 20px 20px 20px; transition: box-shadow 160ms ease, border-color 160ms ease;
}
[class*="st-key-cm_job_"]:hover { box-shadow: var(--cm-shadow-raised); border-color: #CBD6E6 !important; }
[class*="st-key-cm_job_"] .cm-job { border: none; box-shadow: none; margin-bottom: 0; padding: 20px 0 8px 0; }
[class*="st-key-cm_chart_"] {
  background: var(--cm-color-surface); border: 1px solid var(--cm-color-border);
  border-radius: var(--cm-radius-lg); box-shadow: var(--cm-shadow-card); padding: 16px 16px 8px 16px;
}
.cm-card { transition: box-shadow 160ms ease; }

@media (prefers-reduced-motion: reduce) {
  .cm-card, [class*="st-key-cm_job_"] { transition: none; }
}

/* ---------- Narrow screens ---------- */
@media (max-width: 640px) {
  .cm-page-header h1 { font-size: 24px; }
  .st-key-cm_hero { padding: 24px 20px; }
  .st-key-cm_hero .cm-page-header h1 { font-size: 26px; }
  .cm-section-header h2 { font-size: 19px; }
  .cm-metric-value { font-size: 24px; }
  .cm-kv { grid-template-columns: 1fr; gap: 2px; }
  .cm-kv dd { margin-bottom: var(--cm-space-sm); }
  .cm-empty { padding: var(--cm-space-lg) var(--cm-space-md); }
  .cm-job { padding: var(--cm-space-md); }
  .cm-job-head { flex-direction: column; gap: 2px; }
  .cm-match { flex-direction: column; }
}
"""


def build_stylesheet() -> str:
    return f"<style>\n{css_variables()}\n{_BASE_CSS}\n</style>"


def apply_theme() -> None:
    """Inject the global stylesheet (call once per script run)."""
    st.html(build_stylesheet())
