"""Plotly figures of the sales dashboard: trend per macro region on GMT hours, and horizontal breakdown bars.

Compact sizes. Trend: one distinct colour per macro region. Bars: the latest GMT date in blue, earlier dates
in greys. See doc/sales_dashboard.md, "Screen".
"""
import plotly.graph_objects as go

import bi

REGION_COLORS = {"EUROPE": "#2f6fb0", "AMERICAS": "#e07b24", "ASIA": "#3a9a5b"}  # blue, orange, green
REGION_LABEL = {"EUROPE": "Europe", "AMERICAS": "Americas", "ASIA": "Asia"}
LATEST = "#7fb3d5"
EARLIER = ["#8c8c8c", "#b3b3b3", "#d0d0d0", "#e3e3e3"]
FONT = dict(family="Segoe UI, Helvetica, Arial, sans-serif", size=11, color="#333")
TREND_HEIGHT = 230
BAR_ROW_HEIGHT = 20


def date_colors(dates):
    """Latest date blue, then greys going back."""
    ordered = sorted(dates, reverse=True)
    return {d: (LATEST if i == 0 else EARLIER[min(i - 1, len(EARLIER) - 1)]) for i, d in enumerate(ordered)}


def _layout(fig, height):
    fig.update_layout(height=height, margin=dict(l=4, r=4, t=4, b=4), font=FONT,
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1, font=dict(size=10)),
                      uirevision="keep")  # keep zoom and legend clicks across refreshes
    return fig


def empty(message, height=200):
    fig = go.Figure()
    fig.add_annotation(text=message, showarrow=False, font=dict(size=12, color="#888"))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return _layout(fig, height)


def trend(series, kpi):
    """One line per macro region, x = GMT calendar date and hour."""
    if not series:
        return empty("No data yet", TREND_HEIGHT)
    fig = go.Figure()
    for region, (xs, ys) in series.items():
        fig.add_trace(go.Scatter(
            x=xs, y=ys, name=REGION_LABEL.get(region, region), mode="lines",
            line=dict(color=REGION_COLORS.get(region, "#666"), width=2), connectgaps=False,
            text=[bi.fmt_kpi(kpi, y) if y is not None else "—" for y in ys],
            hovertemplate=f"{REGION_LABEL.get(region, region)}: %{{text}}<extra></extra>"))
    fig.update_xaxes(title_text="GMT", title_font=dict(size=10), tickformat="%d %b\n%H:%M", showgrid=False)
    fig.update_yaxes(rangemode="tozero", gridcolor="#e6e6e6", tickfont=dict(size=10))
    fig.update_layout(hovermode="x unified")
    return _layout(fig, TREND_HEIGHT)


def bars(members, labels, dates, values, kpi, hidden):
    """Horizontal bars, largest on top; one segment per GMT date (cumulative over dates)."""
    if not members:
        return empty("No data for these filters")
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
        textfont=dict(size=10), showlegend=False, hoverinfo="skip", customdata=members))
    fig.update_layout(barmode="stack", bargap=0.25)
    fig.update_yaxes(autorange="reversed", showgrid=False, tickfont=dict(size=10))
    fig.update_xaxes(visible=False, range=[0, max(totals) * 1.3 if max(totals) > 0 else 1])
    if hidden:
        fig.add_annotation(text=f"+{hidden} more not shown", xref="paper", yref="paper", x=1, y=0,
                           showarrow=False, font=dict(size=9, color="#888"))
    return _layout(fig, max(160, BAR_ROW_HEIGHT * len(members) + 40))
