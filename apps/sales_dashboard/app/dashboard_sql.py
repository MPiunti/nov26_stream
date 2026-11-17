"""SQL of the sales dashboard: read-only queries on the silver tables and the dimensions.

Every query is a SELECT. Filter values are passed as named parameters (`:name`), never pasted into the SQL.
Plain functions, standard library only, so they can be tested without a connection.
See doc/sales_dashboard.md, "Queries".
"""
import os
import re
from dataclasses import dataclass

DEFAULT_TABLES = {
    # Views on the silver tables that keep only the current simulation (src/sql/15_...).
    "SALES_TABLE": "workspace.test02_streaming.current_sales_transactions",
    "PEOPLE_TABLE": "workspace.test02_streaming.current_people_counter_events",
    "STORE_TABLE": "workspace.test02_warehouse.dim_store",
    "PRODUCT_TABLE": "workspace.test02_warehouse.dim_product",
    # Metric views of the Clienteling tab (doc/kpi_metrics.md, doc/kpi_glossary.md).
    "CLIENT_METRICS": "workspace.test02_metric.client_metrics",
    "STORE_METRICS": "workspace.test02_metric.store_metrics",
}

# Drill-down levels: the column each level groups by. Labels come from the dimension cache in the app.
GEO_LEVELS = {"REGION": "d.macro_region", "COUNTRY": "d.country_code", "STORE": "d.store_id"}
PRODUCT_LEVELS = {"CATEGORY": "s.category", "PRODUCT": "s.product_id"}
# Sales channel of the store (dim_store.channel). RETAIL and FLAGSHIP are physical stores, with people
# counting; ECOM stores sell online only, so they have sales but no people events.
CHANNELS = ("RETAIL", "FLAGSHIP", "ECOM")
CHANNEL_LEVEL = "d.channel"  # the channel chart groups by it

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def table(var):
    name = os.environ.get(var, DEFAULT_TABLES[var]).strip()
    if not re.fullmatch(r"[A-Za-z0-9_]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+", name):
        raise ValueError(f"{var} must be catalog.schema.table, got {name!r}")
    return name


# GMT (UTC) time of each row, as a TIMESTAMP_NTZ wall clock. Sales carry it in silver; people events are
# converted here from the store's time zone, the same way 03_sales.py does it.
SALES_UTC = "s.transaction_timestamp_utc"
PEOPLE_UTC = "convert_timezone(d.timezone_id, 'UTC', s.event_timestamp)"


@dataclass(frozen=True)
class Filters:
    """What the viewer selected. Empty tuple = no filter on that field."""
    dates: tuple = ()       # GMT (UTC) calendar dates, YYYY-MM-DD
    regions: tuple = ()     # dim_store.macro_region
    countries: tuple = ()   # dim_store.country_code
    stores: tuple = ()      # dim_store.store_id
    categories: tuple = ()  # silver_sales_transactions.category
    products: tuple = ()    # silver_sales_transactions.product_id
    channels: tuple = ()    # dim_store.channel: RETAIL, FLAGSHIP, ECOM

    def __post_init__(self):
        for d in self.dates:
            if not _DATE.fullmatch(d):
                raise ValueError(f"bad date {d!r}")
        for c in self.channels:
            if c not in CHANNELS:
                raise ValueError(f"bad channel {c!r}")


def _in(column, name, values, params, cast=None):
    markers = []
    for i, value in enumerate(values):
        key = f"{name}_{i}"
        params[key] = str(value)
        markers.append(f"CAST(:{key} AS {cast})" if cast else f":{key}")
    return f"{column} IN ({', '.join(markers)})"


def where(f, utc_column, sales=True):
    """WHERE clause and parameters for the filters. People events have no category or product."""
    clauses, params = [], {}
    if f.dates:
        clauses.append(_in(f"CAST({utc_column} AS DATE)", "date", f.dates, params, cast="DATE"))
    for column, name, values in (("d.macro_region", "region", f.regions), ("d.country_code", "country", f.countries),
                                 ("d.store_id", "store", f.stores), ("d.channel", "channel", f.channels)):
        if values:
            clauses.append(_in(column, name, values, params))
    if sales:
        if f.categories:
            clauses.append(_in("s.category", "category", f.categories, params))
        if f.products:
            clauses.append(_in("s.product_id", "product", f.products, params))
    return ("WHERE " + "\n  AND ".join(clauses)) if clauses else "", params


def _sales_from():
    return f"FROM {table('SALES_TABLE')} s\nJOIN {table('STORE_TABLE')} d ON s.store_id = d.store_id"


def _people_from():
    return f"FROM {table('PEOPLE_TABLE')} s\nJOIN {table('STORE_TABLE')} d ON s.store_id = d.store_id"


# store_quantity: the items sold in physical stores, the ones the people counters can be compared with.
# transactions: baskets, so distinct transaction ids (a transaction has one row per item). Every line of a
# basket has the same store, time and channel, so the counts add up across hours, regions and channels.
SALES_MEASURES = ("SUM(s.amount) AS value, SUM(s.quantity) AS quantity, COUNT(DISTINCT s.transaction_id) AS transactions, "
                  "SUM(CASE WHEN d.channel <> 'ECOM' THEN s.quantity ELSE 0 END) AS store_quantity")
PEOPLE_MEASURES = ("SUM(CASE WHEN s.event_type = 'ENTRY' THEN s.people_count ELSE 0 END) AS people_in, "
                   "SUM(CASE WHEN s.event_type = 'EXIT' THEN s.people_count ELSE 0 END) AS people_out")


def _trend(utc, measures, frm, clause):
    return f"""SELECT d.macro_region AS region, CAST({utc} AS DATE) AS utc_date, HOUR({utc}) AS utc_hour,
  {measures}
{frm}
{clause}
GROUP BY 1, 2, 3
ORDER BY 2, 3, 1"""


def sales_trend_sql(f):
    """Sales per macro region and GMT date and hour: feeds the KPI cards and the trend lines."""
    clause, params = where(f, SALES_UTC)
    return _trend(SALES_UTC, SALES_MEASURES, _sales_from(), clause), params


def people_trend_sql(f):
    """People in and out per macro region and GMT date and hour. The category and product filters don't apply."""
    clause, params = where(f, PEOPLE_UTC, sales=False)
    return _trend(PEOPLE_UTC, PEOPLE_MEASURES, _people_from(), clause), params


def sales_breakdown_sql(f, column):
    """Sales per member of a drill level (GEO_LEVELS, PRODUCT_LEVELS or the channel) and GMT date."""
    if column not in (*GEO_LEVELS.values(), *PRODUCT_LEVELS.values(), CHANNEL_LEVEL):
        raise ValueError(f"bad level column {column!r}")
    clause, params = where(f, SALES_UTC)
    sql = f"""SELECT {column} AS member, CAST({SALES_UTC} AS DATE) AS utc_date,
  {SALES_MEASURES}
{_sales_from()}
{clause}
GROUP BY 1, 2"""
    return sql, params


def people_breakdown_sql(f, column):
    """People per geography member or channel and GMT date. E-commerce stores have no people events."""
    if column not in (*GEO_LEVELS.values(), CHANNEL_LEVEL):
        raise ValueError(f"bad level column {column!r}")
    clause, params = where(f, PEOPLE_UTC, sales=False)
    sql = f"""SELECT {column} AS member, CAST({PEOPLE_UTC} AS DATE) AS utc_date,
  {PEOPLE_MEASURES}
{_people_from()}
{clause}
GROUP BY 1, 2"""
    return sql, params


def freshness_sql():
    """The current simulation in silver, unfiltered: its id, row counts and latest rows, for the footer, and
    the GMT dates on offer. Sales rows are lines (items); transactions are distinct transaction ids."""
    sales, people, store = table("SALES_TABLE"), table("PEOPLE_TABLE"), table("STORE_TABLE")
    sql = f"""SELECT 'SALES' AS stream, CAST({SALES_UTC} AS DATE) AS utc_date,
  COUNT(*) AS row_count, COUNT(DISTINCT s.transaction_id) AS transactions,
  MAX(s.ingestion_timestamp) AS last_ingested, MAX({SALES_UTC}) AS last_utc, MAX(s.simulation_id) AS simulation_id
FROM {sales} s
GROUP BY 1, 2
UNION ALL
SELECT 'PEOPLE', CAST({PEOPLE_UTC} AS DATE),
  COUNT(*), CAST(NULL AS BIGINT), MAX(s.ingestion_timestamp), MAX({PEOPLE_UTC}), MAX(s.simulation_id)
FROM {people} s
JOIN {store} d ON s.store_id = d.store_id
GROUP BY 1, 2"""
    return sql, {}


def stores_sql():
    return (f"SELECT store_id, store_name, country_code, country_name, macro_region, is_flagship, channel "
            f"FROM {table('STORE_TABLE')} WHERE is_active ORDER BY store_id"), {}


def products_sql():
    return (f"SELECT product_id, product_name, category FROM {table('PRODUCT_TABLE')} "
            f"WHERE is_active ORDER BY product_id"), {}


# ------------------------------------------------------------------ Clienteling: the metric views

_SIMULATION = re.compile(r"\d{8}T\d{9}")
CLIENTELING_ROWS = 20  # rows of the stores and clients tables

# (measure in the metric view, column alias)
CLIENT_KPIS = (("Total Spent", "total_spent"), ("Transactions", "transactions"), ("Items", "items"),
               ("Average Basket", "average_basket"), ("Stores Visited", "stores_visited"),
               ("Online Share", "online_share"))
STORE_KPIS = (("Revenue", "revenue"), ("Transactions", "transactions"), ("Average Basket", "average_basket"),
              ("Items per Basket", "items_per_basket"), ("Distinct Clients", "distinct_clients"),
              ("Visitor Share", "visitor_share"), ("People In", "people_in"), ("Conversion", "conversion"))


def metric_where(f, simulation, categories=False):
    """WHERE on the metric views' dimensions: the simulation, then the page's filters.

    Both views have the store and time dimensions; only client_metrics has Category. The product filter
    doesn't apply here (the tab is about clients and stores).
    """
    if not _SIMULATION.fullmatch(simulation or ""):
        raise ValueError(f"bad simulation id {simulation!r}")
    clauses, params = ["`Simulation` = :simulation"], {"simulation": simulation}
    if f.dates:
        clauses.append(_in("`Date (GMT)`", "date", f.dates, params, cast="DATE"))
    for column, name, values in (("`Macro Region`", "region", f.regions), ("`Store Country`", "country", f.countries),
                                 ("`Store`", "store", f.stores), ("`Channel`", "channel", f.channels)):
        if values:
            clauses.append(_in(column, name, values, params))
    if categories and f.categories:
        clauses.append(_in("`Category`", "category", f.categories, params))
    return "WHERE " + "\n  AND ".join(clauses), params


def _measures(kpis):
    return ",\n  ".join(f"MEASURE(`{measure}`) AS {alias}" for measure, alias in kpis)


def client_kpis_sql(f, simulation, limit=CLIENTELING_ROWS):
    """The top clients by total spent, with their KPIs."""
    clause, params = metric_where(f, simulation, categories=True)
    sql = f"""SELECT `Client` AS client, `Client Country` AS client_country, `Client Segment` AS client_segment,
  {_measures(CLIENT_KPIS)}
FROM {table('CLIENT_METRICS')}
{clause}
GROUP BY ALL
ORDER BY total_spent DESC
LIMIT {int(limit)}"""
    return sql, params


def store_kpis_sql(f, simulation, limit=CLIENTELING_ROWS):
    """The top stores by revenue, with their KPIs."""
    clause, params = metric_where(f, simulation)
    sql = f"""SELECT `Store` AS store, `Store Name` AS store_name, `Channel` AS channel, `Store Country` AS store_country,
  {_measures(STORE_KPIS)}
FROM {table('STORE_METRICS')}
{clause}
GROUP BY ALL
ORDER BY revenue DESC
LIMIT {int(limit)}"""
    return sql, params


# Clients by segment (client_metrics' Client Segment dimensions): (measure, alias)
SEGMENT_KPIS = (("Clients", "clients"), ("Total Spent", "total_spent"), ("Average Basket", "average_basket"),
                ("Transactions", "transactions"))


def segments_sql(f, simulation):
    """Clients by segment, lowest spend first: a client's segment is set by its spend in the whole simulation."""
    clause, params = metric_where(f, simulation, categories=True)
    sql = f"""SELECT `Client Segment Rank` AS segment_rank, `Client Segment` AS segment, `Client Segment Name` AS segment_name,
  {_measures(SEGMENT_KPIS)}
FROM {table('CLIENT_METRICS')}
{clause}
GROUP BY ALL
ORDER BY segment_rank"""
    return sql, params


def store_totals_sql(f, simulation):
    """The store KPIs over every store in the filters: the Clienteling cards."""
    clause, params = metric_where(f, simulation)
    return f"""SELECT {_measures(STORE_KPIS)}
FROM {table('STORE_METRICS')}
{clause}""", params
