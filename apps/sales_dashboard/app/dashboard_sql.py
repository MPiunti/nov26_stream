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
}

# Drill-down levels: the column each level groups by. Labels come from the dimension cache in the app.
GEO_LEVELS = {"REGION": "d.macro_region", "COUNTRY": "d.country_code", "STORE": "d.store_id"}
PRODUCT_LEVELS = {"CATEGORY": "s.category", "PRODUCT": "s.product_id"}
STORE_TYPES = ("ALL", "FLAGSHIP", "OTHER")

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
    store_type: str = "ALL"  # ALL, FLAGSHIP (the two flagships) or OTHER

    def __post_init__(self):
        for d in self.dates:
            if not _DATE.fullmatch(d):
                raise ValueError(f"bad date {d!r}")
        if self.store_type not in STORE_TYPES:
            raise ValueError(f"bad store type {self.store_type!r}")


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
                                 ("d.store_id", "store", f.stores)):
        if values:
            clauses.append(_in(column, name, values, params))
    if f.store_type == "FLAGSHIP":
        clauses.append("d.is_flagship")
    elif f.store_type == "OTHER":
        clauses.append("NOT d.is_flagship")
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


SALES_MEASURES = "SUM(s.amount) AS value, SUM(s.quantity) AS quantity, COUNT(*) AS transactions"
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
    """Sales per member of a drill level (GEO_LEVELS or PRODUCT_LEVELS column) and GMT date."""
    if column not in GEO_LEVELS.values() and column not in PRODUCT_LEVELS.values():
        raise ValueError(f"bad level column {column!r}")
    clause, params = where(f, SALES_UTC)
    sql = f"""SELECT {column} AS member, CAST({SALES_UTC} AS DATE) AS utc_date,
  {SALES_MEASURES}
{_sales_from()}
{clause}
GROUP BY 1, 2"""
    return sql, params


def people_breakdown_sql(f, column):
    """People per geography member and GMT date."""
    if column not in GEO_LEVELS.values():
        raise ValueError(f"bad level column {column!r}")
    clause, params = where(f, PEOPLE_UTC, sales=False)
    sql = f"""SELECT {column} AS member, CAST({PEOPLE_UTC} AS DATE) AS utc_date,
  {PEOPLE_MEASURES}
{_people_from()}
{clause}
GROUP BY 1, 2"""
    return sql, params


def freshness_sql():
    """Latest rows of both silver tables, unfiltered: the footer and the GMT dates on offer."""
    sales, people, store = table("SALES_TABLE"), table("PEOPLE_TABLE"), table("STORE_TABLE")
    sql = f"""SELECT 'SALES' AS stream, CAST({SALES_UTC} AS DATE) AS utc_date,
  COUNT(*) AS row_count, MAX(s.ingestion_timestamp) AS last_ingested, MAX({SALES_UTC}) AS last_utc
FROM {sales} s
GROUP BY 1, 2
UNION ALL
SELECT 'PEOPLE', CAST({PEOPLE_UTC} AS DATE),
  COUNT(*), MAX(s.ingestion_timestamp), MAX({PEOPLE_UTC})
FROM {people} s
JOIN {store} d ON s.store_id = d.store_id
GROUP BY 1, 2"""
    return sql, {}


def stores_sql():
    return (f"SELECT store_id, store_name, country_code, country_name, macro_region, is_flagship "
            f"FROM {table('STORE_TABLE')} WHERE is_active ORDER BY store_id"), {}


def products_sql():
    return (f"SELECT product_id, product_name, category FROM {table('PRODUCT_TABLE')} "
            f"WHERE is_active ORDER BY product_id"), {}
