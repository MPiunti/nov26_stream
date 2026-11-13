"""People-stream simulator app: START/STOP the simulated people flow and the sales it generates.

Sliders set N_AVG_PEOPLE per region (vertical) and PURCHASE_PROB per region and category (horizontal).
See doc/people_stream.md and doc/sales.md. One simulation runs per app process, shared by every viewer.
"""
import os

import dash_bootstrap_components as dbc
from dash import ALL, Dash, Input, Output, State, ctx, dcc, html, no_update

import charts
import shop_config
import simulator as sim
import warehouse

wh = warehouse.Warehouse()
simulation = sim.Simulation(
    load_stores=wh.load_stores,
    load_offsets=wh.load_offsets,
    write=wh.write,
    tick_seconds=sim.DEFAULT_TICK_SECONDS,
    load_catalog=wh.load_catalog,
    load_sales_offsets=wh.load_sales_offsets,
    write_sales=wh.write_sales,
    clear_sources=wh.clear_sources,
)
CATEGORY_LABEL = {"SHOES": "Shoes", "BAGS": "Bags", "READY_TO_WEAR": "Ready-to-wear", "ACCESSORIES": "Accessories",
                  "TRAVEL": "Travel", "SUNGLASSES": "Sunglasses"}
CFG = sim.CONFIG  # from shop_config.yml, read once at start

REGION_LABEL = {"EUROPE": "Europe", "AMERICAS": "Americas", "ASIA": "Asia"}
STATE_COLOR = {"RUNNING": "success", "STARTING": "info", "STOPPED": "secondary", "FINISHED": "primary",
               "FAILED": "danger"}

# update_title=None: keep the browser tab title fixed; by default Dash shows "Updating..." during every
# callback, which flickers with the 1-second refresh.
APP_TITLE = "People stream simulator"
app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP], title=APP_TITLE, update_title=None)
# The browser tab title follows the simulated hour while running (set in the browser, no server round trip).
app.clientside_callback(
    "function(title) { if (title) { document.title = title; } return window.dash_clientside.no_update; }",
    Output("browser-title", "id"),
    Input("browser-title", "data"),
)
server = app.server


def slider_marks(count=5):
    """About `count` evenly spaced labels on the slider grid, always including min and max."""
    span = (sim.N_AVG_MAX - sim.N_AVG_MIN) // sim.N_AVG_STEP
    every = max(1, round(span / (count - 1))) * sim.N_AVG_STEP
    values = list(range(sim.N_AVG_MIN, sim.N_AVG_MAX, every)) + [sim.N_AVG_MAX]
    return {v: f"{v:,}" for v in values}


def parameters_card():
    rows = [html.Tr([html.Td(html.Code(name), className="small"), html.Td(value, className="fw-semibold"),
                     html.Td(meaning, className="small text-muted")])
            for name, value, meaning in shop_config.describe(CFG)]
    return dbc.Card([
        dbc.CardHeader("Parameters (shop_config.yml)"),
        dbc.CardBody(dbc.Table(html.Tbody(rows), size="sm", borderless=True, className="mb-0")),
    ], className="mb-3 shadow-sm")


def probability_slider(region, category, value):
    return dbc.Row([
        dbc.Col(html.Span(CATEGORY_LABEL[category], className="small"), xs=4, className="text-end pe-0"),
        dbc.Col(dcc.Slider(
            id={"type": "prob", "region": region, "category": category},
            min=sim.PROB_MIN, max=sim.PROB_MAX, step=sim.PROB_STEP, value=value, marks=None,
            tooltip={"placement": "right", "always_visible": True, "template": "{value}%"},
        ), xs=8, className="ps-1"),
    ], className="g-0 align-items-center mb-1")


def equalizer(region, value, probs):
    return dbc.Col([
        html.Div(REGION_LABEL[region], className="fw-semibold text-center"),
        html.Div(f"N_AVG_PEOPLE_{'AMERICA' if region == 'AMERICAS' else region}",
                 className="small text-muted text-center mb-2"),
        html.Div(dcc.Slider(
            id={"type": "n-avg", "region": region},
            min=sim.N_AVG_MIN, max=sim.N_AVG_MAX, step=sim.N_AVG_STEP, value=value,
            vertical=True, verticalHeight=260,
            marks=slider_marks(),
            tooltip={"placement": "right", "always_visible": True},
        ), className="d-flex justify-content-center"),
        html.Div(id={"type": "region-stats", "region": region}, className="small text-center mt-2"),
        html.Div("PURCHASE_PROB per person leaving (%)", className="small text-muted text-center mt-3 mb-1"),
        html.Div([probability_slider(region, c, probs[c]) for c in sim.CATEGORIES]),
    ], md=4)


def chart_card(title, graph_id, figure):
    return dbc.Card([
        dbc.CardHeader(title),
        dbc.CardBody(dcc.Graph(id=graph_id, config={"displayModeBar": False}, figure=figure)),
    ], className="mb-3 shadow-sm")


def simulator_tab(n_avg):
    """Controls only: sliders, parameters and stream status. The charts are on the Counters tab."""
    probs = simulation.snapshot()["purchase_prob"]
    return [
        dbc.Card([
            dbc.CardHeader("Average visitors per store per day (vertical) and purchase probability "
                           "per category (horizontal), by region"),
            dbc.CardBody([
                dbc.Row([equalizer(r, n_avg[r], probs[r]) for r in sim.REGIONS]),
                dbc.Button("Reset to defaults", id="reset", color="link", size="sm", className="mt-2"),
            ]),
        ], className="mb-3 shadow-sm"),
        parameters_card(),
        dbc.Card([dbc.CardHeader("Stream"), dbc.CardBody(id="stream-stats")], className="mb-3 shadow-sm"),
    ]


def counters_tab():
    """The dashboard: in/out counters, people per calendar date, and the cumulative lines."""
    snapshot = simulation.snapshot()
    return [
        dbc.Card([dbc.CardHeader("In, out and still inside, by region"), dbc.CardBody(id="exit-stats")],
                 className="mb-3 shadow-sm"),
        dbc.Card([dbc.CardHeader("Sales transactions by region and category"), dbc.CardBody(id="sales-stats")],
                 className="mb-3 shadow-sm"),
        dbc.Card([
            dbc.CardHeader(dbc.Row([
                dbc.Col("People per calendar date (store local time), by region"),
                dbc.Col(dbc.RadioItems(id="daily-kind", value="exits", inline=True, options=[
                    {"label": "People out (EXIT)", "value": "exits"},
                    {"label": "People in (ENTRY)", "value": "entries"},
                ]), width="auto"),
            ], className="g-2 align-items-center")),
            dbc.CardBody(dcc.Graph(id="daily-chart", config={"displayModeBar": False},
                                   figure=charts.daily_bars(snapshot, "exits"))),
        ], className="mb-3 shadow-sm"),
        chart_card("Cumulative people out per region (sum of EXIT people_count), simulated UTC time",
                   "exits-chart", charts.cumulative_exits(snapshot, sim.MAX_RUN_SIM_HOURS)),
        chart_card("Cumulative people in per region (sum of ENTRY people_count), simulated UTC time",
                   "entries-chart", charts.cumulative_entries(snapshot, sim.MAX_RUN_SIM_HOURS)),
        html.P(f"Everyone still inside a store leaves in a final EXIT at its {CFG.closing_hour:02d}:00 closing, "
               "so each store's day ends with as many people out as in. Stores still open when the run "
               "ends keep their people inside.", className="small text-muted"),
    ]


def serve_layout():
    # Built per page load, so the sliders show the running simulation's values.
    n_avg = simulation.snapshot()["n_avg"]
    return dbc.Container([
        html.Div([
            html.H3("People stream simulator", className="mb-0 me-3"),
            html.H4(id="headline-time", className="mb-0 text-primary"),
        ], className="d-flex align-items-baseline flex-wrap mt-3 mb-2"),
        html.P("Streams simulated people-counter events into the pipeline's source table. "
               f"24 simulated hours take {CFG.real_seconds_per_sim_day} seconds; stores are open "
               f"{CFG.opening_hour:02d}:00-{CFG.closing_hour:02d}:00 local time, and each person stays inside "
               f"at most {CFG.max_stay_minutes} minutes ({CFG.max_stay_minutes / 60:g} h). Each run lasts at most "
               f"{CFG.max_run_sim_hours} simulated hours ({CFG.max_run_real_seconds:g} seconds); "
               "START always begins a new run and first empties both source tables (people events and sales); "
               "afterwards run the pipeline with a full refresh of all tables.",
               className="text-muted"),
        dbc.Card(dbc.CardBody(dbc.Row([
            dbc.Col([
                dbc.Button("START", id="start", color="success", className="me-2 px-4"),
                dbc.Button("STOP", id="stop", color="danger", className="px-4"),
            ], md="auto"),
            dbc.Col(html.Div(id="state"), className="d-flex align-items-center"),
        ], className="g-3")), className="mb-3 shadow-sm"),
        dbc.Tabs(id="tabs", active_tab="tab-simulator", className="mb-3", children=[
            dbc.Tab(label="Simulator", tab_id="tab-simulator", children=simulator_tab(n_avg)),
            dbc.Tab(label="Counters", tab_id="tab-counters", children=counters_tab()),
        ]),
        dcc.Interval(id="tick", interval=1000),
        dcc.Store(id="sink-buttons"),
        dcc.Store(id="sink-sliders"),
        dcc.Store(id="sink-probs"),
        dcc.Store(id="browser-title"),
        dcc.Store(id="chart-version"),
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
              Output({"type": "prob", "region": ALL, "category": ALL}, "value"),
              Input("reset", "n_clicks"), prevent_initial_call=True)
def reset(_):
    probs = [sim.PURCHASE_PROB_DEFAULTS[o["id"]["region"]][o["id"]["category"]] for o in ctx.outputs_list[3]]
    return [sim.N_AVG_DEFAULTS[r] for r in sim.REGIONS] + [probs]


@app.callback(Output("sink-probs", "data"), Input({"type": "prob", "region": ALL, "category": ALL}, "value"))
def set_purchase_prob(_values):
    for item in ctx.inputs_list[0]:
        if item.get("value") is not None:
            simulation.set_purchase_prob(item["id"]["region"], item["id"]["category"], item["value"])
    return simulation.snapshot()["purchase_prob"]


@app.callback(Output("sink-sliders", "data"),
              Input({"type": "n-avg", "region": sim.REGIONS[0]}, "value"),
              Input({"type": "n-avg", "region": sim.REGIONS[1]}, "value"),
              Input({"type": "n-avg", "region": sim.REGIONS[2]}, "value"))
def set_n_avg(*values):
    for region, value in zip(sim.REGIONS, values):
        if value is not None:
            simulation.set_n_avg(region, value)
    return simulation.snapshot()["n_avg"]


@app.callback(Output("entries-chart", "figure"), Output("exits-chart", "figure"), Output("exit-stats", "children"),
              Output("sales-stats", "children"),
              Output("chart-version", "data"),
              Input("tick", "n_intervals"), State("chart-version", "data"))
def refresh_chart(_, version):
    s = simulation.snapshot()
    current = f"{s['run_id']}:{len(s['history'])}"
    if current == version:  # redraw only when a new batch arrived
        return no_update, no_update, no_update, no_update, no_update
    return (charts.cumulative_entries(s, sim.MAX_RUN_SIM_HOURS), charts.cumulative_exits(s, sim.MAX_RUN_SIM_HOURS),
            exit_stats(s), sales_stats(s), current)


@app.callback(Output("daily-chart", "figure"), Input("daily-kind", "value"), Input("chart-version", "data"))
def refresh_daily(kind, _version):
    """Redraw on a new batch (chart-version changes) or when people in / out is switched."""
    return charts.daily_bars(simulation.snapshot(), kind or "exits")


def sales_stats(s):
    """Per region: transactions per category, total transactions, amount and transactions per person out."""
    header = html.Thead(html.Tr([html.Th("Region")] + [html.Th(CATEGORY_LABEL[c], className="text-end")
                                                       for c in sim.CATEGORIES]
                                + [html.Th("Transactions", className="text-end"),
                                   html.Th("Amount (EUR)", className="text-end"),
                                   html.Th("Per person out", className="text-end")]))
    rows = []
    for r in sim.REGIONS:
        x = s["sales"][r]
        per_person = x["transactions"] / s["exits"][r] if s["exits"][r] else 0
        rows.append(html.Tr([html.Td(REGION_LABEL[r])]
                            + [html.Td(f"{x['by_category'][c]:,}", className="text-end") for c in sim.CATEGORIES]
                            + [html.Td(f"{x['transactions']:,}", className="text-end fw-semibold"),
                               html.Td(f"{x['amount']:,.0f}", className="text-end"),
                               html.Td(f"{per_person:.1%}", className="text-end")]))
    return dbc.Table([header, html.Tbody(rows)], size="sm", responsive=True, className="mb-0")


def exit_stats(s):
    header = html.Thead(html.Tr([html.Th("Region"), html.Th("People in", className="text-end"),
                                 html.Th("People out", className="text-end"),
                                 html.Th("Still inside", className="text-end")]))
    rows = [html.Tr([html.Td(REGION_LABEL[r]), html.Td(f"{s['entries'][r]:,}", className="text-end"),
                     html.Td(f"{s['exits'][r]:,}", className="text-end"),
                     html.Td(f"{s['entries'][r] - s['exits'][r]:,}", className="text-end")])
            for r in sim.REGIONS]
    return dbc.Table([header, html.Tbody(rows)], size="sm", className="mb-0")


def _fmt_time(iso):
    return iso[:19].replace("T", " ") + " UTC" if iso else "-"


@app.callback(Output("state", "children"), Output("stream-stats", "children"),
              Output({"type": "region-stats", "region": sim.REGIONS[0]}, "children"),
              Output({"type": "region-stats", "region": sim.REGIONS[1]}, "children"),
              Output({"type": "region-stats", "region": sim.REGIONS[2]}, "children"),
              Output("start", "disabled"),
              Output("stop", "disabled"),
              Output("headline-time", "children"),
              Output("browser-title", "data"),
              Input("tick", "n_intervals"))
def refresh(_):
    s = simulation.snapshot()
    state = [dbc.Badge(s["state"], color=STATE_COLOR.get(s["state"], "secondary"), className="me-2 fs-6")]
    if s["error"]:
        state.append(html.Span(s["error"], className="text-danger small"))
    elif s.get("sources_cleared"):
        state.append(html.Span("Source tables emptied at START: run the pipeline with Full refresh all.",
                               className="text-muted small"))
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
    return (state, stats, *regions, active, not active, sim.headline_time(s),
            sim.browser_title(s, APP_TITLE))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("DATABRICKS_APP_PORT", 8000)), debug=False)
