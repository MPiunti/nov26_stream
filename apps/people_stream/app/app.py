"""People-stream simulator app: START/STOP the simulated people flow and set N_AVG_PEOPLE per region.

See doc/people_stream.md. One simulation runs per app process and is shared by every viewer.
"""
import os

import dash_bootstrap_components as dbc
from dash import Dash, Input, Output, ctx, dcc, html

import simulator as sim
import warehouse

wh = warehouse.Warehouse()
simulation = sim.Simulation(
    load_stores=wh.load_stores,
    load_offsets=wh.load_offsets,
    write=wh.write,
    tick_seconds=float(os.environ.get("SIM_TICK_SECONDS", sim.DEFAULT_TICK_SECONDS)),
)

REGION_LABEL = {"EUROPE": "Europe", "AMERICAS": "Americas", "ASIA": "Asia"}
STATE_COLOR = {"RUNNING": "success", "STARTING": "info", "STOPPED": "secondary", "FINISHED": "primary",
               "FAILED": "danger"}

app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP], title="People stream simulator")
server = app.server


def equalizer(region, value):
    return dbc.Col([
        html.Div(REGION_LABEL[region], className="fw-semibold text-center"),
        html.Div(f"N_AVG_PEOPLE_{'AMERICA' if region == 'AMERICAS' else region}",
                 className="small text-muted text-center mb-2"),
        html.Div(dcc.Slider(
            id={"type": "n-avg", "region": region},
            min=sim.N_AVG_MIN, max=sim.N_AVG_MAX, step=sim.N_AVG_STEP, value=value,
            vertical=True, verticalHeight=260,
            marks={v: str(v) for v in range(sim.N_AVG_MIN, sim.N_AVG_MAX + 1, 1000)},
            tooltip={"placement": "right", "always_visible": True},
        ), className="d-flex justify-content-center"),
        html.Div(id={"type": "region-stats", "region": region}, className="small text-center mt-2"),
    ], xs=4)


def serve_layout():
    # Built per page load, so the sliders show the running simulation's values.
    n_avg = simulation.snapshot()["n_avg"]
    return dbc.Container([
        html.H3("People stream simulator", className="mt-3"),
        html.P("Streams simulated people-counter events into the pipeline's source table. "
               "24 simulated hours take 240 seconds; stores are open 10:00-20:00 local time. "
               "Each run lasts at most 48 simulated hours (480 seconds); START always begins a new run.",
               className="text-muted"),
        dbc.Card(dbc.CardBody(dbc.Row([
            dbc.Col([
                dbc.Button("START", id="start", color="success", className="me-2 px-4"),
                dbc.Button("STOP", id="stop", color="danger", className="px-4"),
            ], md="auto"),
            dbc.Col(html.Div(id="state"), className="d-flex align-items-center"),
        ], className="g-3")), className="mb-3 shadow-sm"),
        dbc.Card([
            dbc.CardHeader("Average visitors per store per day, by region"),
            dbc.CardBody([
                dbc.Row([equalizer(r, n_avg[r]) for r in sim.REGIONS]),
                dbc.Button("Reset to 3000", id="reset", color="link", size="sm", className="mt-2"),
            ]),
        ], className="mb-3 shadow-sm"),
        dbc.Card([dbc.CardHeader("Stream"), dbc.CardBody(id="stream-stats")], className="mb-3 shadow-sm"),
        dcc.Interval(id="tick", interval=1000),
        dcc.Store(id="sink-buttons"),
        dcc.Store(id="sink-sliders"),
    ], fluid=False)


app.layout = serve_layout


@app.callback(Output("sink-buttons", "data"), Input("start", "n_clicks"), Input("stop", "n_clicks"),
              prevent_initial_call=True)
def start_stop(_start, _stop):
    if ctx.triggered_id == "start":
        simulation.start()
    else:
        simulation.stop()
    return ctx.triggered_id


@app.callback(Output({"type": "n-avg", "region": sim.REGIONS[0]}, "value"),
              Output({"type": "n-avg", "region": sim.REGIONS[1]}, "value"),
              Output({"type": "n-avg", "region": sim.REGIONS[2]}, "value"),
              Input("reset", "n_clicks"), prevent_initial_call=True)
def reset(_):
    return [sim.N_AVG_DEFAULT] * 3


@app.callback(Output("sink-sliders", "data"),
              Input({"type": "n-avg", "region": sim.REGIONS[0]}, "value"),
              Input({"type": "n-avg", "region": sim.REGIONS[1]}, "value"),
              Input({"type": "n-avg", "region": sim.REGIONS[2]}, "value"))
def set_n_avg(*values):
    for region, value in zip(sim.REGIONS, values):
        if value is not None:
            simulation.set_n_avg(region, value)
    return simulation.snapshot()["n_avg"]


def _fmt_time(iso):
    return iso[:19].replace("T", " ") + " UTC" if iso else "-"


@app.callback(Output("state", "children"), Output("stream-stats", "children"),
              Output({"type": "region-stats", "region": sim.REGIONS[0]}, "children"),
              Output({"type": "region-stats", "region": sim.REGIONS[1]}, "children"),
              Output({"type": "region-stats", "region": sim.REGIONS[2]}, "children"),
              Output("start", "disabled"),
              Output("stop", "disabled"),
              Input("tick", "n_intervals"))
def refresh(_):
    s = simulation.snapshot()
    state = [dbc.Badge(s["state"], color=STATE_COLOR.get(s["state"], "secondary"), className="me-2 fs-6")]
    if s["error"]:
        state.append(html.Span(s["error"], className="text-danger small"))
    stats = dbc.Row([
        dbc.Col([html.Div("Simulated time", className="small text-muted"), html.Div(_fmt_time(s["sim_utc"]))]),
        dbc.Col([html.Div("Started at", className="small text-muted"), html.Div(_fmt_time(s["start_utc"]))]),
        dbc.Col([html.Div("Ends at", className="small text-muted"), html.Div(_fmt_time(s["end_utc"]))]),
        dbc.Col([html.Div("Seconds left", className="small text-muted"),
                 html.Div("-" if s["remaining_seconds"] is None else f"{s['remaining_seconds']:.0f}")]),
        dbc.Col([html.Div("Rows written", className="small text-muted"), html.Div(f"{s['rows_written']:,}")]),
        dbc.Col([html.Div("Batches", className="small text-muted"),
                 html.Div(f"{s['batches']:,} (last {s['last_batch_rows']} rows)")]),
        dbc.Col([html.Div("Run id", className="small text-muted"), html.Div(s["run_id"] or "-")]),
    ])
    regions = [html.Div([html.Div(f"{s['open_stores'][r]} / {s['stores'][r]} stores open"),
                         html.Div(f"{s['entries'][r]:,} visitors so far")]) for r in sim.REGIONS]
    active = s["state"] in ("RUNNING", "STARTING")
    return state, stats, *regions, active, not active


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("DATABRICKS_APP_PORT", 8000)), debug=False)
