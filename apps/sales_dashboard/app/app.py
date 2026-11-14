"""Sales BI dashboard: self-service sales and people performance, read live from the silver tables.

Read-only: it queries silver_sales_transactions, silver_people_counter_events and the dimensions through the
SQL warehouse, and refreshes every REFRESH_SECONDS. No coupling with the people-stream app or the pipeline.
Times are GMT (UTC). Layout and sizes: assets/dashboard.css. See doc/sales_dashboard.md.
"""
import os
import threading
from datetime import datetime, timezone

import dash_bootstrap_components as dbc
from dash import Dash, Input, Output, State, ctx, dcc, html, no_update

import bi
import dashboard_sql as q
import figures
import sql_warehouse

REFRESH_SECONDS = max(2, int(os.environ.get("REFRESH_SECONDS", "5")))
REGIONS = ("EUROPE", "AMERICAS", "ASIA")
CATEGORIES = ("SHOES", "BAGS", "READY_TO_WEAR", "ACCESSORIES", "TRAVEL", "SUNGLASSES")
CATEGORY_LABEL = {"SHOES": "Shoes", "BAGS": "Bags", "READY_TO_WEAR": "Ready-to-wear", "ACCESSORIES": "Accessories",
                  "TRAVEL": "Travel", "SUNGLASSES": "Sunglasses"}
REGION_LABEL = {"EUROPE": "Europe", "AMERICAS": "Americas", "ASIA": "Asia"}
GEO_LEVEL_LABEL = {"REGION": "Area", "COUNTRY": "Country", "STORE": "Store"}
PRODUCT_LEVEL_LABEL = {"CATEGORY": "Merch. category", "PRODUCT": "Product"}
CARDS = ("VALUE", "QUANTITY", "AVG_PRICE", "PEOPLE_IN", "ITEMS_PER_VISITOR")
CARD_LABEL = {"VALUE": "VALUE", "QUANTITY": "QUANTITY", "AVG_PRICE": "AVG PRICE", "PEOPLE_IN": "PEOPLE IN",
              "ITEMS_PER_VISITOR": "ITEMS PER VISITOR"}

SIDEBAR_BG, CARD_BG = "#cfe2f0", "#f2f2f2"
GOOD, BAD = "#4a9d4a", "#d9534f"
BUTTONS = dict(input_class_name="btn-check", label_class_name="btn btn-light btn-sm",
               label_checked_class_name="active btn-dark text-white")

wh = sql_warehouse.Warehouse()

# The browser tab title is fixed: update_title=None stops Dash from showing "Updating..." during the
# refresh callbacks, and nothing on the page changes the title afterwards.
APP_TITLE = "Sales BI dashboard"
app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP], title=APP_TITLE, update_title=None,
           meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}])
server = app.server


# ------------------------------------------------------------------ dimension cache

class Dimensions:
    """dim_store and dim_product, read once (and again after a failure): labels and filter options."""

    def __init__(self):
        self._lock = threading.Lock()
        self.stores, self.products = None, None

    def load(self):
        with self._lock:
            if self.stores is None:
                self.stores = {r["store_id"]: r for r in wh.query(*q.stores_sql())}
            if self.products is None:
                self.products = {r["product_id"]: r for r in wh.query(*q.products_sql())}
        return self

    def geo_labels(self, level):
        if level == "REGION":
            return REGION_LABEL
        if level == "COUNTRY":
            return {s["country_code"]: s["country_name"] for s in self.stores.values()}
        return {k: s["store_name"] + (" ★" if s["is_flagship"] else "") for k, s in self.stores.items()}

    def product_labels(self, level):
        if level == "CATEGORY":
            return CATEGORY_LABEL
        return {k: p["product_name"] for k, p in self.products.items()}


dims = Dimensions()


# ------------------------------------------------------------------ layout

def label(text):
    return html.Div(text, className="tiny fw-semibold mt-2 mb-1 text-uppercase")


def sidebar():
    return html.Div([
        html.Div("FILTER AREA", className="panel-title text-center"),
        label("KPI on charts"),
        dcc.Dropdown(id="kpi", options=[{"label": v[0], "value": k} for k, v in bi.KPIS.items()],
                     value="VALUE", clearable=False, searchable=False),
        label("GMT dates"),
        dcc.Dropdown(id="dates", multi=True, placeholder="All dates"),
        label("Macro region"),
        dbc.Checklist(id="regions", value=[], inline=True,
                      options=[{"label": REGION_LABEL[r], "value": r} for r in REGIONS], **BUTTONS),
        label("Country"),
        dcc.Dropdown(id="countries", multi=True, placeholder="All countries"),
        label("Store"),
        dcc.Dropdown(id="stores", multi=True, placeholder="All stores"),
        label("Store type"),
        dbc.RadioItems(id="store-type", value="ALL", inline=True,
                       options=[{"label": "All", "value": "ALL"}, {"label": "Flagships", "value": "FLAGSHIP"},
                                {"label": "Others", "value": "OTHER"}], **BUTTONS),
        label("Merch. category"),
        dbc.Checklist(id="categories", value=[], inline=True,
                      options=[{"label": CATEGORY_LABEL[c], "value": c} for c in CATEGORIES], **BUTTONS),
        dbc.Switch(id="live", value=True, label=f"Live, every {REFRESH_SECONDS} s", className="mt-2 tiny"),
        dbc.Button("Reset filters", id="reset", color="secondary", outline=True, size="sm", className="w-100 mt-1"),
    ], className="filters", style={"background": SIDEBAR_BG, "borderRadius": "6px", "padding": "8px 10px"})


def panel(children, **style):
    return html.Div(children, style={"background": CARD_BG, "borderRadius": "6px", "padding": "6px 8px", **style})


def breakdown_panel(prefix, levels, value):
    return panel([
        html.Div([
            html.Div(id=f"{prefix}-title", className="panel-title"),
            html.Div(id=f"{prefix}-path", className="tiny text-muted text-end"),
        ], className="d-flex justify-content-between flex-wrap gap-1"),
        html.Div([
            dbc.RadioItems(id=f"{prefix}-level", value=value, inline=True,
                           options=[{"label": v, "value": k} for k, v in levels.items()], **BUTTONS),
            dbc.Button("▲ Up", id=f"{prefix}-up", color="secondary", outline=True, size="sm", className="mb-1"),
        ], className="level d-flex flex-wrap align-items-center mt-1"),
        dcc.Graph(id=f"{prefix}-chart", config={"displayModeBar": False}),
    ], height="100%")


FRESH_CHIPS = (("refresh", "Refreshed"), ("sales", "Last sale"), ("people", "Last people event"))


def footer():
    """Freshness chips, all GMT: a status dot, the time, and how long ago (ticked every second in the browser)."""
    chips = [html.Span([
        html.Span(id=f"dot-{key}", className="dot dot-off"),
        html.Span(text, className="text-muted me-1"),
        html.Span("—", id=f"ts-{key}", className="fw-semibold"),
        html.Span(id=f"age-{key}", className="age ms-1"),
    ], className="chip") for key, text in FRESH_CHIPS]
    return html.Div(chips + [html.Span(id="foot-rows", className="chip text-muted")],
                    className="footer d-flex flex-wrap justify-content-end align-items-center gap-1 tiny")


app.layout = html.Div([
    dbc.Row([
        dbc.Col(sidebar(), xs=12, md=3, xl=2, className="mb-2"),
        dbc.Col([
            html.Div(id="alert"),
            dbc.Row([dbc.Col(html.Div(id=f"card-{k}"), xs=6, sm=4, lg=True, className="mb-2") for k in CARDS],
                    className="g-2"),
            panel([
                html.Div([
                    html.Div(id="trend-title", className="panel-title"),
                    dbc.Switch(id="cumulative", value=True, label="Cumulative", className="tiny mb-0"),
                ], className="d-flex justify-content-between align-items-center flex-wrap"),
                dcc.Graph(id="trend", config={"displayModeBar": False}),
            ], marginBottom="8px"),
            dbc.Row([
                dbc.Col(breakdown_panel("geo", GEO_LEVEL_LABEL, "REGION"), xs=12, lg=6, className="mb-2"),
                dbc.Col(breakdown_panel("product", PRODUCT_LEVEL_LABEL, "CATEGORY"), xs=12, lg=6, className="mb-2"),
            ], className="g-2"),
            footer(),
        ], xs=12, md=9, xl=10),
    ], className="g-2"),
    dcc.Interval(id="refresh", interval=REFRESH_SECONDS * 1000),
    dcc.Interval(id="clock", interval=1000),  # ticks the footer ages in the browser; no server call
    dcc.Store(id="fresh-ms"),            # epoch ms of the last refresh and of the last sales / people ingestion
    dcc.Store(id="tick"),                # time a refresh was requested (ms), see gate_refresh
    dcc.Store(id="done"),                # the tick of the last refresh that finished
    dcc.Store(id="products", data=[]),   # product filter, set by clicking a product bar
    dcc.Store(id="snapshot"),            # previous refresh's totals, for the live deltas
], className="page", style={"fontFamily": "Segoe UI, Helvetica, Arial, sans-serif"})


# ------------------------------------------------------------------ callbacks

def make_filters(dates, regions, countries, stores, store_type, categories, products):
    return q.Filters(dates=tuple(dates or ()), regions=tuple(regions or ()), countries=tuple(countries or ()),
                     stores=tuple(stores or ()), categories=tuple(categories or ()), products=tuple(products or ()),
                     store_type=store_type or "ALL")


@app.callback(Output("refresh", "disabled"), Input("live", "value"))
def toggle_live(live):
    return not live


# Footer ages: recomputed in the browser every second from the epoch times of the last refresh, so they keep
# counting between refreshes (and show when data stops arriving). Green < FRESH_OK_S, amber < FRESH_WARN_S, red after.
FRESH_OK_S, FRESH_WARN_S = 30, 120
app.clientside_callback(
    f"""function(n, f) {{
        const out = [];
        for (const key of ["refresh", "sales", "people"]) {{
            const ms = f && f[key];
            if (!ms) {{ out.push("", "dot dot-off"); continue; }}
            const s = Math.max(0, Math.round((Date.now() - ms) / 1000));
            const age = s < 60 ? s + " s ago" : s < 3600 ? Math.floor(s / 60) + " min ago"
                                              : Math.floor(s / 3600) + " h ago";
            out.push(age, s < {FRESH_OK_S} ? "dot dot-ok" : s < {FRESH_WARN_S} ? "dot dot-warn" : "dot dot-stale");
        }}
        return out;
    }}""",
    [o for key, _ in FRESH_CHIPS for o in (Output(f"age-{key}", "children"), Output(f"dot-{key}", "className"))],
    Input("clock", "n_intervals"), Input("fresh-ms", "data"),
)


# One refresh at a time. If the interval fired the refresh directly, a refresh slower than REFRESH_SECONDS would
# be overtaken by the next one, and Dash drops the result of an overtaken callback: the screen would freeze.
# So the interval only asks for a refresh when the previous one is done (or after STUCK_MS, in case one failed).
STUCK_MS = 30000
app.clientside_callback(
    f"""function(n, tick, done) {{
        if (tick && done !== tick && Date.now() - tick < {STUCK_MS}) {{
            return window.dash_clientside.no_update;
        }}
        return Date.now();
    }}""",
    Output("tick", "data"),
    Input("refresh", "n_intervals"),
    State("tick", "data"), State("done", "data"),
)


@app.callback(
    Output("dates", "value"), Output("regions", "value"), Output("countries", "value"), Output("stores", "value"),
    Output("store-type", "value"), Output("categories", "value"), Output("products", "data"),
    Output("geo-level", "value"), Output("product-level", "value"),
    Output("geo-chart", "clickData"), Output("product-chart", "clickData"),
    Input("geo-chart", "clickData"), Input("product-chart", "clickData"),
    Input("geo-up", "n_clicks"), Input("product-up", "n_clicks"), Input("reset", "n_clicks"),
    State("dates", "value"), State("regions", "value"), State("countries", "value"), State("stores", "value"),
    State("store-type", "value"), State("categories", "value"), State("products", "data"),
    State("geo-level", "value"), State("product-level", "value"),
    prevent_initial_call=True,
)
def drill(geo_click, product_click, _geo_up, _product_up, _reset,
          dates, regions, countries, stores, store_type, categories, products, geo_level, product_level):
    """Click a bar to drill down, Up to drill up, Reset to clear every filter."""
    trigger = ctx.triggered_id
    if trigger == "reset":
        return [], [], [], [], "ALL", [], [], "REGION", "CATEGORY", None, None
    f = make_filters(dates, regions, countries, stores, store_type, categories, products)
    levels = {"GEO": geo_level, "PRODUCT": product_level}
    if trigger in ("geo-chart", "product-chart"):
        click = geo_click if trigger == "geo-chart" else product_click
        point = (click or {}).get("points", [{}])[0]
        member = point.get("customdata")
        if member is None:
            return (no_update,) * 9 + (None, None)
        f, levels = bi.drill_down(f, levels, "GEO" if trigger == "geo-chart" else "PRODUCT", member)
    elif trigger in ("geo-up", "product-up"):
        f, levels = bi.drill_up(f, levels, "GEO" if trigger == "geo-up" else "PRODUCT")
    return (list(f.dates), list(f.regions), list(f.countries), list(f.stores), f.store_type, list(f.categories),
            list(f.products), levels["GEO"], levels["PRODUCT"], None, None)


@app.callback(Output("countries", "options"), Output("stores", "options"),
              Input("regions", "value"), Input("countries", "value"), Input("refresh", "n_intervals"))
def filter_options(regions, countries, _n):
    """Countries of the selected regions; stores of the selected regions and countries."""
    try:
        d = dims.load()
    except Exception:
        return no_update, no_update
    stores = [s for s in d.stores.values() if (not regions or s["macro_region"] in regions)]
    country_opts = sorted({(s["country_name"], s["country_code"]) for s in stores})
    stores = [s for s in stores if not countries or s["country_code"] in countries]
    return ([{"label": n, "value": c} for n, c in country_opts],
            [{"label": s["store_name"] + (" ★" if s["is_flagship"] else ""), "value": s["store_id"]}
             for s in sorted(stores, key=lambda s: s["store_name"])])


def kpi_card(key, value, live):
    """Label, value and the change since the previous refresh (DELTA LIVE)."""
    unit_kpi = key if key in bi.KPIS else None
    big = bi.fmt_kpi(unit_kpi, value) if unit_kpi else f"{value:.3f}"
    if live is None:
        delta = html.Span("—", className="text-muted")
    else:
        d = live.get(key, 0.0)
        text = bi.fmt_delta(unit_kpi, d) if unit_kpi else f"{d:+.3f}"
        delta = html.Span(text, style={"color": GOOD if d >= 0 else BAD})
    return panel([
        html.Div(CARD_LABEL[key], className="kpi-label text-muted"),
        html.Div(big, className="kpi-value"),
        html.Div(["Δ live ", delta], className="tiny"),
    ], height="100%")


def _fmt_ts(value, fmt="%d/%m/%Y %H:%M"):
    return value.strftime(fmt) if hasattr(value, "strftime") else "—"


def _epoch_ms(value):
    """A TIMESTAMP from the warehouse (session time zone UTC) as epoch milliseconds, for the browser's ages."""
    if not hasattr(value, "timestamp"):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp() * 1000)


@app.callback(
    [Output(f"card-{k}", "children") for k in CARDS],
    Output("trend-title", "children"), Output("trend", "figure"),
    Output("geo-title", "children"), Output("geo-path", "children"), Output("geo-chart", "figure"),
    Output("product-title", "children"), Output("product-path", "children"), Output("product-chart", "figure"),
    Output("dates", "options"), Output("ts-refresh", "children"), Output("ts-sales", "children"),
    Output("ts-people", "children"), Output("foot-rows", "children"), Output("fresh-ms", "data"),
    Output("alert", "children"), Output("snapshot", "data"),
    Output("done", "data"),
    Input("tick", "data"), Input("kpi", "value"), Input("cumulative", "value"),
    Input("dates", "value"), Input("regions", "value"), Input("countries", "value"), Input("stores", "value"),
    Input("store-type", "value"), Input("categories", "value"), Input("products", "data"),
    Input("geo-level", "value"), Input("product-level", "value"),
    State("snapshot", "data"),
)
def refresh(tick, kpi, cumulative, dates, regions, countries, stores, store_type, categories, products,
            geo_level, product_level, snapshot):
    f = make_filters(dates, regions, countries, stores, store_type, categories, products)
    product_kpi = kpi if kpi in bi.SALES_KPIS else "VALUE"  # people aren't counted per product
    geo_sql = (q.people_breakdown_sql if kpi == "PEOPLE_IN" else q.sales_breakdown_sql)(f, q.GEO_LEVELS[geo_level])
    res = wh.query_many({
        "sales": q.sales_trend_sql(f),
        "people": q.people_trend_sql(f),
        "geo": geo_sql,
        "product": q.sales_breakdown_sql(f, q.PRODUCT_LEVELS[product_level]),
        "fresh": q.freshness_sql(),
    })
    try:
        dims.load()
    except Exception as exc:
        res["dims"] = exc
    errors = {k: v for k, v in res.items() if isinstance(v, Exception)}
    alert = None
    if errors:
        missing = any("TABLE_OR_VIEW_NOT_FOUND" in str(e) or "UNRESOLVED_COLUMN" in str(e) for e in errors.values())
        text = ("A silver table, column or dimension doesn't exist yet: deploy the pipeline (with 03_sales.py), "
                "run it with a full refresh, then reload. " if missing
                else "Some queries failed; retrying at the next refresh. ")
        alert = dbc.Alert(text + "; ".join(f"{k}: {str(e).splitlines()[0][:160]}" for k, e in errors.items()),
                          color="warning", className="mb-2 py-1 tiny")
        if "sales" in errors or "people" in errors or "dims" in errors:
            nothing = figures.empty("Waiting for the silver tables")
            return ([no_update] * len(CARDS) + ["", nothing, "", "", nothing, "", "", nothing,
                                                no_update] + [no_update] * 5 + [alert, snapshot, tick])

    sales_rows, people_rows = bi.normalize(res["sales"]), bi.normalize(res["people"])
    current = bi.totals(sales_rows, people_rows)
    sig = bi.signature(f)
    live = bi.live_delta(current, snapshot, sig)
    cards = [kpi_card(key, current[key], live) for key in CARDS]

    kpi_label = bi.KPIS[kpi][0]
    trend_rows = people_rows if kpi == "PEOPLE_IN" else sales_rows
    trend_fig = figures.trend(bi.trend_series(trend_rows, kpi, cumulative), kpi)
    trend_title = f"{kpi_label.upper()}{' (CUMULATIVE)' if cumulative else ''} BY GMT HOUR, PER MACRO REGION"

    def chart(name, chart_kpi, labels):
        if name in errors:
            return figures.empty("Query failed")
        members, ds, values, hidden = bi.breakdown(bi.normalize(res[name]), chart_kpi)
        return figures.bars(members, labels, ds, values, chart_kpi, hidden)

    geo_fig = chart("geo", kpi, dims.geo_labels(geo_level))
    product_fig = chart("product", product_kpi, dims.product_labels(product_level))
    geo_path = " › ".join(["All areas"] + [REGION_LABEL.get(r, r) for r in f.regions]
                          + [dims.geo_labels("COUNTRY").get(c, c) for c in f.countries]
                          + ([f"{len(f.stores)} store(s)"] if f.stores else []))
    product_path = " › ".join(["All categories"] + [CATEGORY_LABEL.get(c, c) for c in f.categories]
                              + ([f"{len(f.products)} product(s)"] if f.products else []))

    fresh = [] if "fresh" in errors else bi.normalize(res["fresh"])
    date_options = [{"label": d, "value": d} for d in sorted({r["utc_date"] for r in fresh if r["utc_date"]})]

    def latest(stream, field):
        values = [r[field] for r in fresh if r["stream"] == stream and r[field] is not None]
        return max(values) if values else None

    rows = {s: int(sum(r["row_count"] for r in fresh if r["stream"] == s)) for s in ("SALES", "PEOPLE")}
    now = datetime.now(timezone.utc)
    foot = [f"{now:%H:%M:%S} GMT"]
    for stream in ("SALES", "PEOPLE"):
        sim, ingested = latest(stream, "last_utc"), latest(stream, "last_ingested")
        foot.append(f"{_fmt_ts(sim, '%d %b %H:%M')} GMT · ingested {_fmt_ts(ingested, '%H:%M:%S')}" if sim else "—")
    foot.append(f"Silver: {rows['SALES']:,} sales · {rows['PEOPLE']:,} people events")
    fresh_ms = {"refresh": _epoch_ms(now), "sales": _epoch_ms(latest("SALES", "last_ingested")),
                "people": _epoch_ms(latest("PEOPLE", "last_ingested"))}

    return (cards + [trend_title, trend_fig,
                     f"GEOGRAPHY · {kpi_label.upper()} BY {GEO_LEVEL_LABEL[geo_level].upper()}, PER GMT DATE",
                     geo_path, geo_fig,
                     f"PRODUCT · {bi.KPIS[product_kpi][0].upper()} BY "
                     f"{PRODUCT_LEVEL_LABEL[product_level].upper()}, PER GMT DATE", product_path, product_fig,
                     date_options] + foot + [fresh_ms, alert, {"signature": sig, "totals": current}, tick])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("DATABRICKS_APP_PORT", 8000)), debug=False)
