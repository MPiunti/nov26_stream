"""Plotly figures of the sales dashboard: trend by store-local hour and horizontal breakdown bars.

Colours follow the reference layout: the latest store-local date in blue, earlier dates in greys.
See doc/sales_dashboard.md, "Screen".
"""
import plotly.graph_objects as go

import bi

LATEST = "#7fb3d5"
EARLIER = ["#8c8c8c", "#b3b3b3", "#d0d0d0", "#e3e3e3"]
FONT = dict(family="Segoe UI, Helvetica, Arial, sans-serif", size=12, color="#333")


def date_colors(dates):
    """Latest date blue, then greys going back."""
    ordered = sorted(dates, reverse=True)
    return {d: (LATEST if i == 0 else EARLIER[min(i - 1, len(EARLIER) - 1)]) for i, d in enumerate(ordered)}


def _layout(fig, height):
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=10, b=10), font=FONT,
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1),
                      uirevision="keep")  # keep zoom and legend clicks across refreshes
    return fig


def empty(message, height=320):
    fig = go.Figure()
    fig.add_annotation(text=message, showarrow=False, font=dict(size=14, color="#888"))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return _layout(fig, height)


def trend(series, kpi, cumulative):
    """One line per store-local date, x = local hour."""
    if not series:
        return empty("No data yet")
    colors = date_colors(series)
    fig = go.Figure()
    for date, (xs, ys) in series.items():
        fig.add_trace(go.Scatter(
            x=xs, y=ys, name=date, mode="lines+markers+text", line=dict(color=colors[date], width=3, shape="spline"),
            marker=dict(size=7), text=[bi.fmt_kpi(kpi, y) for y in ys], textposition="top center",
            textfont=dict(size=10, color="#555"),
            hovertemplate=f"{date} %{{x}}:00<br>%{{text}}<extra></extra>"))
    fig.update_xaxes(dtick=1, tickformat="d", title_text="Store-local hour", showgrid=False)
    fig.update_yaxes(visible=False, rangemode="tozero")
    return _layout(fig, 300)


def bars(members, labels, dates, values, kpi, hidden):
    """Horizontal bars, largest on top; one segment per store-local date (cumulative over dates)."""
    if not members:
        return empty("No data for these filters", height=340)
    colors = date_colors([d for d in dates if d != "all dates"]) if dates != ["all dates"] else {"all dates": LATEST}
    names = [labels.get(m, m) for m in members]
    fig = go.Figure()
    for date in dates:
        fig.add_trace(go.Bar(
            y=names, x=values[date], name=date, orientation="h", marker_color=colors[date],
            customdata=members, hovertemplate=f"%{{y}}<br>{date}: %{{x:,.2f}}<extra></extra>"))
    totals = [sum(values[d][i] for d in dates) for i in range(len(members))] if kpi != "AVG_PRICE" else values[dates[0]]
    fig.add_trace(go.Scatter(  # total label at the end of each bar
        y=names, x=totals, mode="text", text=[bi.fmt_kpi(kpi, t) for t in totals], textposition="middle right",
        textfont=dict(size=11), showlegend=False, hoverinfo="skip", customdata=members))
    fig.update_layout(barmode="stack")
    fig.update_yaxes(autorange="reversed", showgrid=False)
    fig.update_xaxes(visible=False, range=[0, max(totals) * 1.25 if max(totals) > 0 else 1])
    if hidden:
        fig.add_annotation(text=f"+{hidden} more not shown", xref="paper", yref="paper", x=1, y=0,
                           showarrow=False, font=dict(size=10, color="#888"))
    return _layout(fig, max(260, 28 * len(members) + 60))
