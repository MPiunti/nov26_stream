"""SQL warehouse access for the people-stream app: read stores and offsets, insert events.

Runs as the app's service principal through the warehouse in DATABRICKS_WAREHOUSE_ID.
The SQL builders are plain functions, so they can be tested without a connection.
See doc/people_stream.md, "Writing the events".
"""
import os
import re
import threading

import sales
from simulator import PARTITION, SOURCE_TOPIC, Store

DEFAULT_TABLES = {
    "STORE_TABLE": "workspace.test02_streaming.dim_store",
    "SOURCE_TABLE": "workspace.test02_streaming.simulated_event_source",
    "CLIENT_TABLE": "workspace.test02_streaming.dim_client",
    "PRODUCT_TABLE": "workspace.test02_streaming.dim_product",
    "SALES_TABLE": "workspace.test02_streaming.simulated_sales_source",
}
CHUNK_ROWS = 1000  # rows per MERGE statement


def table(var):
    name = os.environ.get(var, DEFAULT_TABLES[var]).strip()
    if not re.fullmatch(r"[A-Za-z0-9_]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+", name):
        raise ValueError(f"{var} must be catalog.schema.table, got {name!r}")
    return name


def stores_sql(store_table):
    return (f"SELECT store_id, macro_region, timezone_id FROM {store_table} "
            f"WHERE is_active ORDER BY store_id")


def offsets_sql(source_table, topic=SOURCE_TOPIC):
    if not re.fullmatch(r"[a-z0-9-]+", topic):
        raise ValueError(f"bad topic {topic!r}")
    return (f"SELECT source_partition, MAX(source_offset) AS max_offset FROM {source_table} "
            f"WHERE source_topic = '{topic}' GROUP BY source_partition")


def clear_sql(source_table):
    """Empty a source table at START; keeps the table, its permissions and its history."""
    return f"DELETE FROM {source_table}"


def products_sql(product_table):
    return f"SELECT product_id, category, list_price FROM {product_table} WHERE is_active ORDER BY product_id"


def clients_sql(client_table):
    return f"SELECT client_id, country_code FROM {client_table} WHERE is_active"


def _literal(value):
    """SQL literal for the generator's own values (no user input reaches here)."""
    if isinstance(value, bool) or value is None:
        raise TypeError(f"unexpected value {value!r}")
    if isinstance(value, int):
        return str(value)
    if hasattr(value, "isoformat"):  # aware UTC datetime
        return f"TIMESTAMP'{value.isoformat(sep=' ', timespec='milliseconds')}'"
    text = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{text}'"


INSERT_COLUMNS = ("raw_event", "source_topic", "source_partition", "source_offset", "source_timestamp")


def insert_sql(source_table, rows):
    """Insert-only MERGE on the message identity: a retried batch inserts nothing twice."""
    values = ",\n    ".join("(" + ", ".join(_literal(r[c]) for c in INSERT_COLUMNS) + ")" for r in rows)
    cols = ", ".join(INSERT_COLUMNS)
    return f"""MERGE INTO {source_table} AS target
USING (
  SELECT * FROM VALUES
    {values}
  AS source({cols})
) AS source
ON  target.source_topic <=> source.source_topic
AND target.source_partition <=> source.source_partition
AND target.source_offset <=> source.source_offset
WHEN NOT MATCHED THEN INSERT ({cols})
VALUES ({", ".join("source." + c for c in INSERT_COLUMNS)})"""


class Warehouse:
    """One connection, reused across batches and reopened after an error."""

    def __init__(self):
        self._conn = None
        self._lock = threading.Lock()

    def _connect(self):
        from databricks import sql as dbsql
        from databricks.sdk.core import Config

        warehouse_id = os.environ.get("DATABRICKS_WAREHOUSE_ID")
        if not warehouse_id:
            raise RuntimeError("DATABRICKS_WAREHOUSE_ID is not set. Check the app's sql-warehouse resource.")
        cfg = Config()
        return dbsql.connect(server_hostname=cfg.host, http_path=f"/sql/1.0/warehouses/{warehouse_id}",
                             credentials_provider=lambda: cfg.authenticate)

    def _execute(self, statement, fetch=False):
        with self._lock:
            for attempt in (1, 2):
                try:
                    if self._conn is None:
                        self._conn = self._connect()
                    with self._conn.cursor() as cursor:
                        cursor.execute(statement)
                        return cursor.fetchall() if fetch else None
                except Exception:
                    self.close_unlocked()
                    if attempt == 2:
                        raise

    def close_unlocked(self):
        try:
            if self._conn is not None:
                self._conn.close()
        except Exception:
            pass
        self._conn = None

    def load_stores(self):
        try:
            rows = self._execute(stores_sql(table("STORE_TABLE")), fetch=True)
        except Exception as exc:
            if "macro_region" in str(exc):
                raise RuntimeError("dim_store has no macro_region column: run src/sql/01_create_dim_store.sql "
                                   "and 02_populate_dim_store.sql first.") from exc
            raise
        stores = [Store(r[0], r[1], r[2]) for r in rows]
        bad = [s.store_id for s in stores if s.macro_region not in PARTITION]
        if not stores:
            raise RuntimeError("dim_store is empty: run src/sql/02_populate_dim_store.sql first.")
        if bad:
            raise RuntimeError(f"{len(bad)} stores have no valid macro_region (e.g. {bad[0]}): "
                               "run src/sql/02_populate_dim_store.sql.")
        return stores

    def _next_offsets(self, table_var, topic):
        """Next offset per partition: continue after what earlier runs wrote."""
        rows = self._execute(offsets_sql(table(table_var), topic), fetch=True)
        found = {int(r[0]): int(r[1]) for r in rows}
        return {p: found.get(p, 0) + 1 for p in PARTITION.values()}

    def load_offsets(self):
        return self._next_offsets("SOURCE_TABLE", SOURCE_TOPIC)

    def clear_sources(self):
        """At START: empty the people and the sales source tables, so each run starts from empty sources."""
        for table_var in ("SOURCE_TABLE", "SALES_TABLE"):
            self._execute(clear_sql(table(table_var)))

    def load_sales_offsets(self):
        return self._next_offsets("SALES_TABLE", sales.SALES_TOPIC)

    def load_catalog(self):
        try:
            products = [sales.Product(r[0], r[1], float(r[2]))
                        for r in self._execute(products_sql(table("PRODUCT_TABLE")), fetch=True)]
            clients = [(r[0], r[1]) for r in self._execute(clients_sql(table("CLIENT_TABLE")), fetch=True)]
        except Exception as exc:
            if "TABLE_OR_VIEW_NOT_FOUND" in str(exc):
                raise RuntimeError("dim_product or dim_client is missing: run src/sql/08 to 11 first.") from exc
            raise
        return sales.Catalog(products, clients)

    def _write_chunks(self, table_var, rows):
        for i in range(0, len(rows), CHUNK_ROWS):
            self._execute(insert_sql(table(table_var), rows[i:i + CHUNK_ROWS]))

    def write(self, rows):
        self._write_chunks("SOURCE_TABLE", rows)

    def write_sales(self, rows):
        self._write_chunks("SALES_TABLE", rows)
