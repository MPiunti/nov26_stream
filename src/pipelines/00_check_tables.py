from pyspark.sql import SparkSession

# ============================================================
# PRE-FLIGHT CHECK - required input tables
# ============================================================
# Runs when the pipeline graph is built, before any data is read or
# written. If an input table is missing or empty, the update fails here
# with a clear message, instead of failing halfway through the load.
#
# Every table the pipeline reads but doesn't create belongs in this list.

REQUIRED_TABLES = {
    # table: (how to create it, must have rows)
    "workspace.test02_streaming.simulated_event_source": (
        "src/sql/04_create_simulated_event_source.sql", False
    ),
    "workspace.test02_warehouse.dim_store": (
        "src/sql/01_create_dim_store.sql and 02_populate_dim_store.sql", True
    ),
    # Sales (03_sales.py): see doc/sales.md.
    "workspace.test02_streaming.simulated_sales_source": (
        "src/sql/12_create_simulated_sales_source.sql", False
    ),
    "workspace.test02_warehouse.dim_client": (
        "src/sql/08_create_dim_client.sql and 09_populate_dim_client.sql", True
    ),
    "workspace.test02_warehouse.dim_product": (
        "src/sql/10_create_dim_product.sql and 11_populate_dim_product.sql", True
    ),
}


def _table_exists(spark, table):
    # spark.catalog.tableExists isn't allowed in pipelines, so resolve the
    # table's columns instead: a missing table fails with TABLE_OR_VIEW_NOT_FOUND.
    try:
        spark.read.table(table).columns
        return True
    except Exception as e:
        if "TABLE_OR_VIEW_NOT_FOUND" in str(e):
            return False
        raise


def check_required_tables():
    spark = SparkSession.getActiveSession()
    problems = []

    for table, (setup_script, needs_rows) in REQUIRED_TABLES.items():
        if not _table_exists(spark, table):
            problems.append(f"{table} is missing; create it with {setup_script}")
        elif needs_rows and spark.read.table(table).limit(1).count() == 0:
            problems.append(f"{table} is empty; load it with {setup_script}")

    if problems:
        raise RuntimeError(
            "Pre-flight check failed, nothing was loaded:\n  - "
            + "\n  - ".join(problems)
        )


check_required_tables()
