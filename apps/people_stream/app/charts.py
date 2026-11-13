"""Cumulative ENTRY and EXIT people counts per region over the run's simulated time.

See doc/people_stream.md §3. Both charts share one form: x = simulated UTC time over the run's
max_run_sim_hours, y = running sum of people_count, one line per region with a fixed color.
"""
from datetime import datetime, timedelta

import plotly.graph_objects as go

# First three slots of the validated categorical palette (light mode), fixed per region.
REGION_COLOR = {"EUROPE": "#2a78d6", "AMERICAS": "#eb6834", "ASIA": "#1baf7a"}
REGION_LABEL = {"EUROPE": "Europe", "AMERICAS": "Americas", "ASIA": "Asia"}
TEXT, MUTED, GRID = "#1f1f1e", "#6b6a64", "#e6e5e0"


def _ts(iso):
    return datetime.fromisoformat(iso.replace(" ", "T")).replace(tzinfo=None)


KINDS = {"entries": ("ENTRY", "Cumulative people in (ENTRY)", "Press START to stream visitors"),
         "exits": ("EXIT", "Cumulative people out (EXIT)", "Press START to stream visitors")}


def cumulative_entries(snapshot, max_hours):
    return cumulative(snapshot, max_hours, "entries")


def cumulative_exits(snapshot, max_hours):
    return cumulative(snapshot, max_hours, "exits")


def cumulative(snapshot, max_hours, kind):
    """Empty figure before the first run; one line per region afterwards, x fixed to the run's length."""
    _, y_title, empty_text = KINDS[kind]
    fig = go.Figure()
    history = snapshot.get("history") or []
    start = _ts(snapshot["start_utc"]) if snapshot.get("start_utc") else None
    if start:
        x = [_ts(p["sim_utc"]) for p in history]
        for region, color in REGION_COLOR.items():
            y = [p[kind][region] for p in history]
            fig.add_trace(go.Scatter(
                x=x, y=y, name=REGION_LABEL[region], mode="lines",
                line={"color": color, "width": 2},
                hovertemplate=f"{REGION_LABEL[region]}: %{{y:,}}<extra></extra>",
            ))
            if len(x) > 1:  # direct label at the line's end, in text ink
                fig.add_annotation(x=x[-1], y=y[-1], text=f"{REGION_LABEL[region]} {y[-1]:,}",
                                   xanchor="left", xshift=6, showarrow=False,
                                   font={"size": 11, "color": TEXT})
        fig.update_xaxes(range=[start, start + timedelta(hours=max_hours)])
    else:
        fig.add_annotation(text=empty_text, x=0.5, y=0.5, xref="paper", yref="paper",
                           showarrow=False, font={"color": MUTED})
        fig.update_xaxes(visible=False)
        fig.update_yaxes(visible=False)
    fig.update_layout(
        height=340, margin={"l": 60, "r": 120, "t": 30, "b": 50},
        plot_bgcolor="white", paper_bgcolor="white", font={"color": TEXT, "size": 12},
        hovermode="x unified", showlegend=True,
        legend={"orientation": "h", "x": 0, "y": 1.12, "font": {"color": TEXT}},
        uirevision=snapshot.get("run_id") or "none",  # keep zoom while the same run updates
    )
    fig.update_xaxes(title={"text": "Simulated time (UTC)", "font": {"color": MUTED}},
                     tickformat="%d %b %H:%M", gridcolor=GRID, linecolor=GRID, tickfont={"color": MUTED})
    fig.update_yaxes(title={"text": y_title, "font": {"color": MUTED}},
                     rangemode="tozero", gridcolor=GRID, zeroline=False, tickformat=",",
                     tickfont={"color": MUTED})
    return fig
