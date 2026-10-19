"""Match result presentation: the summary inside each job card and the score breakdown."""

from __future__ import annotations

import streamlit as st

from src.matching.engine import MatchResult
from src.ui.components import ListItem, badge_html, item_list, notice
from src.ui.job_cards import job_card_html
from src.ui.score_components import Bar, bars_html, chips_html, score_tone

_CONFIDENCE_TONE = {"High": "success", "Medium": "info", "Low": "warning"}
_CHIP_LIMIT = 8


def _chips(items: tuple[str, ...], tone: str) -> str:
    shown = list(items[:_CHIP_LIMIT])
    if len(items) > _CHIP_LIMIT:
        shown.append(f"+{len(items) - _CHIP_LIMIT} more")
    return chips_html(shown, tone)


def match_summary_html(result: MatchResult) -> str:
    # A low-confidence score is shown neutrally so a high number on thin data is not read as a strong match.
    low = result.confidence == "Low"
    tone = "neutral" if low else score_tone(result.score)
    caption = "/ 100 · limited information" if low else "/ 100 match"
    badges = [badge_html(f"{result.confidence} confidence", _CONFIDENCE_TONE[result.confidence])]
    if result.mandatory_gaps:
        n = len(result.mandatory_gaps)
        badges.append(badge_html(f"{n} essential requirement{'s' if n != 1 else ''} not found", "danger"))
    rows = []
    if result.matched_skills:
        rows.append(f'<div class="cm-match-row"><span>Found in your CV</span>'
                    f'{_chips(result.matched_skills, "success")}</div>')
    if result.missing_required_skills:
        rows.append(f'<div class="cm-match-row"><span>Required, not found</span>'
                    f'{_chips(result.missing_required_skills, "warning")}</div>')
    if not rows:
        rows.append('<p class="cm-muted">No recognisable skills were listed in this job description.</p>')
    return (
        f'<div class="cm-match">'
        f'<div class="cm-match-score cm-tone-{tone}" role="img" aria-label="Match score {result.score} out of 100">'
        f'<span>{result.score}</span><small>{caption}</small></div>'
        f'<div class="cm-match-body"><div class="cm-badge-row">{"".join(badges)}</div>{"".join(rows)}</div>'
        f"</div>"
    )


def match_card_html(result: MatchResult) -> str:
    return job_card_html(result.job, extra_html=match_summary_html(result))


def breakdown_bars_html(result: MatchResult) -> str:
    bars = []
    for c in result.components:
        if c.assessed:
            bars.append(Bar(c.label, c.percent, 100,
                            f"Counts for {result.effective_weight(c):g}% of the score. {c.note}".strip()))
    return bars_html(bars)


def render_breakdown(result: MatchResult) -> None:
    st.caption(result.limitations)
    if result.mandatory_gaps:
        notice("The job states these as essential, and they were not found in your CV. If you have them, make "
               "them explicit in your CV before applying.", tone="danger", title="Essential requirements not found.")
        item_list(ListItem(g.requirement, g.detail, "Essential", "danger", f"Job says: “{g.evidence}”")
                  for g in result.mandatory_gaps)
    st.html(breakdown_bars_html(result))
    unassessed = [c for c in result.components if not c.assessed]
    if unassessed:
        st.caption("Not assessed (its weight was shared among the other components): "
                   + "; ".join(f"{c.label} — {c.note}" for c in unassessed))
    for c in result.components:
        if not c.assessed or not (c.evidence or c.gaps):
            continue
        st.markdown(f"**{c.label}** — {c.percent}%")
        item_list([*(ListItem(e, badge="Evidence", tone="success") for e in c.evidence),
                   *(ListItem(g, badge="Gap", tone="warning") for g in c.gaps)])
    if result.check_yourself:
        st.markdown("**Check these yourself**")
        st.caption("A CV cannot show these requirements, so they do not affect the score.")
        item_list(ListItem(label, f"Job says: “{evidence}”", "Check", "info") for label, evidence in result.check_yourself)
    st.markdown("**Confidence in this score**")
    st.caption(" ".join(result.confidence_reasons))
    for n in result.notes:
        st.caption(n)
