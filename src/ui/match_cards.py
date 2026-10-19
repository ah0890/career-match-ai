"""Match result presentation: the summary inside each job card and the score breakdown."""

from __future__ import annotations

from html import escape

import streamlit as st

from src.jobs.freshness import assess
from src.jobs.models import JobPosting
from src.matching.engine import MatchResult
from src.matching.improvements import ImprovementPlan
from src.matching.recommendations import RECOMMENDATION_DISCLAIMER, RankedMatch, Recommendation
from src.ui.components import ListItem, badge_html, item_list, notice
from src.ui.job_cards import _ARRANGEMENT_LABELS, _salary, job_card_html, posted_label
from src.ui.score_components import Bar, bars_html, chips_html, score_tone

_CONFIDENCE_TONE = {"High": "success", "Medium": "info", "Low": "warning"}
_CHIP_LIMIT = 8


def _chips(items: tuple[str, ...], tone: str) -> str:
    shown = list(items[:_CHIP_LIMIT])
    if len(items) > _CHIP_LIMIT:
        shown.append(f"+{len(items) - _CHIP_LIMIT} more")
    return chips_html(shown, tone)


def match_summary_html(result: MatchResult, rec: Recommendation | None = None) -> str:
    # A low-confidence score is shown neutrally so a high number on thin data is not read as a strong match.
    low = result.confidence == "Low"
    tone = "neutral" if low else score_tone(result.score)
    caption = "/ 100 · limited information" if low else "/ 100 match"
    badges = [badge_html(rec.label.value, rec.tone)] if rec else []
    badges.append(badge_html(f"{result.confidence} confidence", _CONFIDENCE_TONE[result.confidence]))
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
    headline = f'<p class="cm-match-headline">{escape(rec.headline)}</p>' if rec else ""
    return (
        f'<div class="cm-match">'
        f'<div class="cm-match-score cm-tone-{tone}" role="img" aria-label="Match score {result.score} out of 100">'
        f'<span>{result.score}</span><small>{caption}</small></div>'
        f'<div class="cm-match-body"><div class="cm-badge-row">{"".join(badges)}</div>{headline}{"".join(rows)}</div>'
        f"</div>"
    )


def match_card_html(result: MatchResult, rec: Recommendation | None = None) -> str:
    return job_card_html(result.job, extra_html=match_summary_html(result, rec))


def breakdown_bars_html(result: MatchResult) -> str:
    bars = []
    for c in result.components:
        if c.assessed:
            bars.append(Bar(c.label, c.percent, 100,
                            f"Counts for {result.effective_weight(c):g}% of the score. {c.note}".strip()))
    return bars_html(bars)


_ACTION_TONE = {"High": "danger", "Medium": "warning", "Low": "neutral"}


def render_recommendation(rec: Recommendation) -> None:
    st.markdown(f"**Recommendation: {rec.label.value}** — {rec.headline}")
    item_list(ListItem(r, badge="Why", tone="info") for r in rec.reasons)
    if rec.actions:
        st.markdown("**What you could do**")
        item_list(ListItem(a.title, a.detail, a.priority, _ACTION_TONE[a.priority]) for a in rec.actions)
    for c in rec.caveats:
        st.caption(c)
    st.caption(RECOMMENDATION_DISCLAIMER)


def render_breakdown(result: MatchResult, rec: Recommendation | None = None) -> None:
    if rec is not None:
        render_recommendation(rec)
        st.divider()
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


def description_html(job: JobPosting) -> str:
    """The full job description as plain text with its line breaks kept (escaped, never rendered as HTML)."""
    text = job.description.strip() or "The source did not provide a description."
    return f'<div class="cm-job-desc">{escape(text)}</div>'


def comparison_html(matches: list[RankedMatch]) -> str:
    """Side-by-side comparison of a few ranked matches."""
    def pct(m, key):
        c = next(c for c in m.result.components if c.key == key)
        return f"{c.percent}%" if c.assessed else "Not assessed"

    def listing(items, empty):
        return ", ".join(items) if items else empty

    rows: list[tuple[str, list[str]]] = [
        ("Company", [m.result.job.company or "Not provided" for m in matches]),
        ("Recommendation", [m.recommendation.label.value for m in matches]),
        ("Match score", [f"{m.result.score} / 100" + (" (limited information)" if m.result.confidence == "Low" else "")
                         for m in matches]),
        ("Confidence", [m.result.confidence for m in matches]),
        *[(c.label, [pct(m, c.key) for m in matches]) for c in matches[0].result.components],
        ("Essential requirements not found", [listing([g.requirement for g in m.result.mandatory_gaps], "None")
                                              for m in matches]),
        ("Required skills not found", [listing(m.result.missing_required_skills, "None") for m in matches]),
        ("Skills found in your CV", [listing(m.result.matched_skills, "None recognised") for m in matches]),
        ("Location", [m.result.job.location or "Not provided" for m in matches]),
        ("Work arrangement", [_ARRANGEMENT_LABELS.get(m.result.job.work_arrangement, "Not provided")
                              for m in matches]),
        ("Salary", [_salary(m.result.job) or "Not provided" for m in matches]),
        ("Posted", [posted_label(m.result.job.posted_at) for m in matches]),
        ("Freshness", [assess(m.result.job).label for m in matches]),
        ("Source", [m.result.job.source_name for m in matches]),
    ]
    head = "".join(f'<th scope="col">{escape(m.result.job.title)}</th>' for m in matches)
    body = "".join(
        f'<tr><th scope="row">{escape(label)}</th>{"".join(f"<td>{escape(v)}</td>" for v in values)}</tr>'
        for label, values in rows
    )
    cols = '<colgroup><col class="cm-compare-label">' + "<col>" * len(matches) + "</colgroup>"
    return (f'<div class="cm-card cm-compare-wrap"><table class="cm-compare">{cols}'
            f'<thead><tr><td></td>{head}</tr></thead><tbody>{body}</tbody></table></div>')


_EVIDENCE_BADGE = {"shown in experience": "In experience", "shown in education": "In education",
                   "listed only": "Listed only", "not found": "Not found"}
_EVIDENCE_TONE = {"shown in experience": "success", "shown in education": "success", "listed only": "info",
                  "not found": "warning"}


def render_improvement_plan(plan: ImprovementPlan) -> None:
    notice(plan.note, tone="info")
    if plan.suggestions:
        st.markdown("**Suggested changes**")
        item_list(ListItem(s.title, s.detail, s.priority, _ACTION_TONE[s.priority], f"Where: {s.where}")
                  for s in plan.suggestions)
    if plan.skills:
        st.markdown("**How your CV evidences the job's skills**")
        st.caption(f"{plan.count('shown in experience')} shown in your experience, "
                   f"{plan.count('shown in education')} shown in education, {plan.count('listed only')} listed "
                   f"without context, {plan.count('not found')} not found.")
        item_list(
            ListItem(s.name, f"Job says: “{s.job_says}”" if s.job_says else "From the source's tags for this job.",
                     _EVIDENCE_BADGE[s.evidence], _EVIDENCE_TONE[s.evidence],
                     "Essential" if s.essential else ("Required" if s.required else "Preferred"))
            for s in plan.skills
        )
    if plan.keyword_gaps:
        st.markdown("**Job terms your CV does not use**")
        item_list(ListItem(f"“{k.keyword}”", f"Job says: “{k.job_says}”" if k.job_says else None,
                           "Not found", "neutral") for k in plan.keyword_gaps)
    if plan.bullet_tips:
        st.markdown("**Your most relevant bullets, and how to strengthen them**")
        for tip in plan.bullet_tips:
            item_list([ListItem(tip.bullet, " ".join(tip.tips), "Bullet", "info",
                                f"Relates to: {', '.join(tip.related_to)}" if tip.related_to else None)])
