"""Plotly chart builders. Single-series charts: one hue, no legend (the title names the series),
thin rounded bars, recessive grid, hover on every mark. Text uses text tokens, never the series colour."""

from __future__ import annotations

import plotly.graph_objects as go

from src.analytics.dashboard import WeekCount
from src.ui.tokens import COLORS, FONT_FAMILY

SERIES = COLORS["accent"]  # validated against the light surface (dataviz palette checks)
_GRID = COLORS["border"]
_MUTED = COLORS["text_secondary"]


def _layout(fig: go.Figure, title: str, height: int = 260) -> go.Figure:
    fig.update_layout(
        title={"text": title, "font": {"size": 15, "color": COLORS["text_primary"]}, "x": 0, "xanchor": "left"},
        height=height, margin={"l": 8, "r": 8, "t": 44, "b": 8}, showlegend=False,
        paper_bgcolor=COLORS["surface"], plot_bgcolor=COLORS["surface"],
        font={"family": FONT_FAMILY, "size": 12, "color": _MUTED}, barcornerradius=4,
        hoverlabel={"bgcolor": COLORS["surface"], "bordercolor": _GRID, "font": {"color": COLORS["text_primary"]}},
    )
    fig.update_xaxes(showgrid=False, linecolor=_GRID, ticks="", zeroline=False)
    fig.update_yaxes(gridcolor=_GRID, griddash="dot", zeroline=False, linecolor=_GRID)
    return fig


def pipeline_figure(rows: list[tuple[str, int]]) -> go.Figure:
    labels = [r[0] for r in rows][::-1]  # first stage at the top
    values = [r[1] for r in rows][::-1]
    fig = go.Figure(go.Bar(
        x=values, y=labels, orientation="h", marker={"color": SERIES}, width=0.55,
        text=values, textposition="outside", textfont={"color": COLORS["text_primary"]},
        hovertemplate="%{y}: %{x} application(s)<extra></extra>", cliponaxis=False,
    ))
    _layout(fig, "Applications by status", height=max(180, 46 * len(rows) + 70))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(showgrid=False)
    return fig


def weekly_figure(weeks: tuple[WeekCount, ...]) -> go.Figure:
    fig = go.Figure(go.Bar(
        x=[w.week_start for w in weeks], y=[w.count for w in weeks], marker={"color": SERIES}, width=4.2 * 86400000,
        customdata=[f"{w.week_start:%d %b}" for w in weeks],
        hovertemplate="Week of %{customdata}: %{y} application(s)<extra></extra>",
    ))
    _layout(fig, "Applications submitted per week")
    fig.update_xaxes(tickformat="%d %b", dtick=14 * 86400000)
    fig.update_yaxes(rangemode="tozero", dtick=1 if max((w.count for w in weeks), default=0) <= 5 else None)
    return fig


def score_figure(scores: tuple[int, ...], improve: float, apply: float) -> go.Figure:
    fig = go.Figure(go.Histogram(
        x=list(scores), xbins={"start": 0, "end": 100.001, "size": 10}, marker={"color": SERIES,
                                                                               "line": {"color": COLORS["surface"], "width": 2}},
        hovertemplate="Score %{x}: %{y} job(s)<extra></extra>",
    ))
    _layout(fig, "Match scores in your latest results")
    # Labels sit on opposite sides of their lines so they never collide when thresholds are close.
    for value, label, anchor, shift in ((improve, "Improve", "right", -4), (apply, "Apply", "left", 4)):
        fig.add_vline(x=value, line={"color": _MUTED, "width": 1, "dash": "dash"})
        fig.add_annotation(x=value, y=1.06, yref="paper", text=f"{label} {value:g}", showarrow=False,
                           xanchor=anchor, xshift=shift, font={"size": 11, "color": _MUTED})
    fig.update_xaxes(range=[0, 100], dtick=10, title={"text": "Match score", "font": {"size": 12}})
    fig.update_yaxes(title={"text": "Jobs", "font": {"size": 12}}, rangemode="tozero")
    return fig
