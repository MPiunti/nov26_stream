"""Databricks SQL warehouse access for the sales dashboard: read-only, parameterized queries.

Runs as the app's service principal through the warehouse in DATABRICKS_WAREHOUSE_ID. One connection per
worker thread, reused across refreshes and reopened after an error; a refresh runs its queries in parallel.
"""
import os
import threading
from concurrent.futures import ThreadPoolExecutor

PARALLEL_QUERIES = 6  # one per refresh query, so a refresh is one round of queries, not two


class Warehouse:

    def __init__(self):
        self._local = threading.local()
        self._pool = ThreadPoolExecutor(max_workers=PARALLEL_QUERIES, thread_name_prefix="sql")

    @staticmethod
    def _connect():
        from databricks import sql as dbsql
        from databricks.sdk.core import Config

        warehouse_id = os.environ.get("DATABRICKS_WAREHOUSE_ID")
        if not warehouse_id:
            raise RuntimeError("DATABRICKS_WAREHOUSE_ID is not set. Check the app's sql-warehouse resource.")
        cfg = Config()
        # Session time zone UTC: TIMESTAMP columns (ingestion_timestamp) come back in GMT, like the rest of
        # the screen. The GMT sale and event times are TIMESTAMP_NTZ and don't depend on it.
        return dbsql.connect(server_hostname=cfg.host, http_path=f"/sql/1.0/warehouses/{warehouse_id}",
                             credentials_provider=lambda: cfg.authenticate,
                             session_configuration={"TIMEZONE": "UTC"})

    def _close(self):
        conn = getattr(self._local, "conn", None)
        self._local.conn = None
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass

    def query(self, sql, params=None):
        """Rows as dicts. Retries once on a fresh connection."""
        for attempt in (1, 2):
            try:
                if getattr(self._local, "conn", None) is None:
                    self._local.conn = self._connect()
                with self._local.conn.cursor() as cursor:
                    cursor.execute(sql, params or None)
                    names = [c[0] for c in cursor.description]
                    return [dict(zip(names, row)) for row in cursor.fetchall()]
            except Exception as exc:
                self._close()
                if attempt == 2 or "TABLE_OR_VIEW_NOT_FOUND" in str(exc):
                    raise

    def query_many(self, statements):
        """{name: (sql, params)} -> {name: rows or the exception}, run in parallel."""
        futures = {name: self._pool.submit(self.query, sql, params) for name, (sql, params) in statements.items()}
        results = {}
        for name, future in futures.items():
            try:
                results[name] = future.result()
            except Exception as exc:  # reported on screen, per query
                results[name] = exc
        return results
