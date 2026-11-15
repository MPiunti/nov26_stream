
from pyspark import pipelines as dp
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType,
    StructField,
    StringType,
    IntegerType,
    DecimalType
)

# ============================================================
# SALES - Bronze, silver and quarantine of the sales transactions
# ============================================================
# Same layering as the people-counter events (01_bronze.py, 02_silver.py),
# for the transactions the people-stream app writes to the sales source.
# Rules and columns: doc/sales.md, "Silver sales".

SALES_SOURCE_TABLE = "workspace.test02_streaming.simulated_sales_source"
BRONZE_SALES_TABLE = "workspace.test02_streaming.bronze_sales_transactions"
STORE_TABLE = "workspace.test02_warehouse.dim_store"
CLIENT_TABLE = "workspace.test02_warehouse.dim_client"
PRODUCT_TABLE = "workspace.test02_warehouse.dim_product"


SALES_SCHEMA = StructType([
    StructField("transaction_id", StringType(), True),
    StructField("line_number", IntegerType(), True),
    StructField("line_count", IntegerType(), True),
    StructField("exit_event_id", StringType(), True),
    StructField("store_id", StringType(), True),
    StructField("client_id", StringType(), True),
    StructField("product_id", StringType(), True),
    StructField("category", StringType(), True),
    StructField("quantity", IntegerType(), True),
    StructField("unit_price", DecimalType(12, 2), True),
    StructField("amount", DecimalType(12, 2), True),
    StructField("currency", StringType(), True),
    StructField("transaction_timestamp", StringType(), True),
    StructField("simulation_id", StringType(), True)
])


# ============================================================
# BRONZE - Raw sales transactions
# ============================================================

@dp.table(
    name="bronze_sales_transactions",
    comment="Bronze raw ingestion of simulated sales transactions",
    table_properties={
        "quality": "bronze",
        "domain": "retail"
    }
)
def bronze_sales_transactions():

    # skipChangeCommits: every START of the people-stream app also empties the sales
    # source; the delete is skipped and the stream goes on with the new rows, as in 01_bronze.py.
    return (
        spark.readStream
            .option("skipChangeCommits", "true")
            .table(SALES_SOURCE_TABLE)
            .select(
                F.col("raw_event"),
                F.col("source_topic"),
                F.col("source_partition"),
                F.col("source_offset"),
                F.col("source_timestamp"),
                F.current_timestamp().alias("ingestion_timestamp")
            )
    )


# ============================================================
# SILVER AND QUARANTINE TABLE SCHEMAS
# ============================================================

SILVER_SALES_SCHEMA = """
    raw_event STRING
        COMMENT 'Original JSON transaction payload received from the source',

    source_topic STRING
        COMMENT 'Source topic or logical stream identifier',

    source_partition INT
        COMMENT 'Source partition identifier: one per macro region',

    source_offset BIGINT
        COMMENT 'Original source offset within the partition',

    source_timestamp TIMESTAMP
        COMMENT 'Timestamp assigned by the source system (UTC)',

    ingestion_timestamp TIMESTAMP
        COMMENT 'Timestamp when the transaction was ingested into Bronze',

    transaction_id STRING NOT NULL
        COMMENT 'The transaction (one buyer, one basket): TX-<simulation id>-<sequence>, sortable by purchase time',

    line_number INT NOT NULL
        COMMENT 'Line of the transaction, 1..line_count: one item per line; with transaction_id, the natural key',

    line_count INT
        COMMENT 'Lines (items) in the transaction',

    exit_event_id STRING
        COMMENT 'event_id of the EXIT people-counter event that triggered the purchase',

    store_id STRING NOT NULL
        COMMENT 'Natural key of the store',

    client_id STRING NOT NULL
        COMMENT 'Natural key of the client',

    product_id STRING NOT NULL
        COMMENT 'Natural key of the product',

    category STRING
        COMMENT 'Merchandise category of the product',

    quantity INT
        COMMENT 'Units sold',

    unit_price DECIMAL(12,2)
        COMMENT 'Unit price in currency',

    amount DECIMAL(12,2)
        COMMENT 'quantity x unit_price, in currency',

    currency STRING
        COMMENT 'ISO currency code: EUR',

    transaction_timestamp_raw STRING
        COMMENT 'Original transaction timestamp as provided in the JSON payload',

    store_timezone_id STRING
        COMMENT 'IANA timezone identifier associated with the store',

    transaction_timestamp TIMESTAMP_NTZ
        COMMENT 'Store local time of the transaction, without timezone conversion',

    transaction_timestamp_utc TIMESTAMP_NTZ
        COMMENT 'The same moment in UTC (GMT): transaction_timestamp converted from store_timezone_id',

    simulation_id STRING
        COMMENT 'Simulation (one START of the people-stream app) that produced the sale; sortable, latest = MAX',

    CONSTRAINT pk_silver_sales_transactions
        PRIMARY KEY (transaction_id, line_number),

    CONSTRAINT fk_silver_sales_store
        FOREIGN KEY (store_id)
        REFERENCES workspace.test02_warehouse.dim_store(store_id),

    CONSTRAINT fk_silver_sales_client
        FOREIGN KEY (client_id)
        REFERENCES workspace.test02_warehouse.dim_client(client_id),

    CONSTRAINT fk_silver_sales_product
        FOREIGN KEY (product_id)
        REFERENCES workspace.test02_warehouse.dim_product(product_id)
"""

QUARANTINE_SALES_SCHEMA = """
    raw_event STRING
        COMMENT 'Original JSON transaction payload received from the source',

    source_topic STRING
        COMMENT 'Source topic or logical stream identifier',

    source_partition INT
        COMMENT 'Source partition identifier',

    source_offset BIGINT
        COMMENT 'Original source offset within the partition',

    source_timestamp TIMESTAMP
        COMMENT 'Timestamp assigned by the source system (UTC)',

    ingestion_timestamp TIMESTAMP
        COMMENT 'Timestamp when the transaction was ingested into Bronze',

    transaction_id STRING
        COMMENT 'Transaction identifier extracted from the payload, when available',

    line_number INT
        COMMENT 'Line of the transaction, as provided',

    line_count INT
        COMMENT 'Lines in the transaction, as provided',

    exit_event_id STRING
        COMMENT 'Triggering EXIT event identifier, when available',

    store_id STRING
        COMMENT 'Store identifier extracted from the payload, when available',

    client_id STRING
        COMMENT 'Client identifier extracted from the payload, when available',

    product_id STRING
        COMMENT 'Product identifier extracted from the payload, when available',

    category STRING
        COMMENT 'Category as provided in the payload',

    quantity INT
        COMMENT 'Units sold, as provided',

    unit_price DECIMAL(12,2)
        COMMENT 'Unit price, as provided',

    amount DECIMAL(12,2)
        COMMENT 'Amount, as provided',

    currency STRING
        COMMENT 'Currency, as provided',

    transaction_timestamp_raw STRING
        COMMENT 'Original transaction timestamp as provided in the JSON payload',

    store_timezone_id STRING
        COMMENT 'IANA timezone identifier, when the store is recognized',

    transaction_timestamp TIMESTAMP_NTZ
        COMMENT 'Parsed transaction timestamp, when valid',

    transaction_timestamp_utc TIMESTAMP_NTZ
        COMMENT 'The same moment in UTC (GMT), when the timestamp and the store are valid',

    simulation_id STRING
        COMMENT 'Simulation that produced the sale, when available',

    rejection_reason STRING
        COMMENT 'One or more validation errors separated by a pipe character',

    record_status STRING
        COMMENT 'Quarantine lifecycle status: OPEN, RESOLVED or REPROCESSED',

    quarantine_timestamp TIMESTAMP
        COMMENT 'Timestamp when the record entered quarantine'
"""


# ============================================================
# PARSING AND VALIDATION
# ============================================================

def validated_sales():

    bronze = (
        spark.readStream
            .table(BRONZE_SALES_TABLE)
            .withColumn("_tx", F.from_json(F.col("raw_event"), SALES_SCHEMA))
            .select(
                "raw_event",
                "source_topic",
                "source_partition",
                "source_offset",
                "source_timestamp",
                "ingestion_timestamp",
                F.trim(F.col("_tx.transaction_id")).alias("transaction_id"),
                F.col("_tx.line_number").alias("line_number"),
                F.col("_tx.line_count").alias("line_count"),
                F.trim(F.col("_tx.exit_event_id")).alias("exit_event_id"),
                F.trim(F.col("_tx.store_id")).alias("store_id"),
                F.trim(F.col("_tx.client_id")).alias("client_id"),
                F.trim(F.col("_tx.product_id")).alias("product_id"),
                F.upper(F.trim(F.col("_tx.category"))).alias("category"),
                F.col("_tx.quantity").alias("quantity"),
                F.col("_tx.unit_price").alias("unit_price"),
                F.col("_tx.amount").alias("amount"),
                F.upper(F.trim(F.col("_tx.currency"))).alias("currency"),
                F.col("_tx.transaction_timestamp").alias("transaction_timestamp_raw"),
                F.trim(F.col("_tx.simulation_id")).alias("simulation_id"),
                F.col("_tx").isNull().alias("_invalid_json")
            )
            .withColumn(
                "transaction_timestamp",
                F.expr("try_cast(transaction_timestamp_raw AS TIMESTAMP_NTZ)")
            )
    )

    # Static dimension lookups, on the natural keys.
    stores = spark.read.table(STORE_TABLE).select(
        F.col("store_id").alias("_dim_store_id"),
        F.col("timezone_id").alias("store_timezone_id")
    )
    clients = spark.read.table(CLIENT_TABLE).select(
        F.col("client_id").alias("_dim_client_id")
    )
    products = spark.read.table(PRODUCT_TABLE).select(
        F.col("product_id").alias("_dim_product_id"),
        F.col("category").alias("_dim_category")
    )

    sales = (
        bronze
            .join(stores, F.col("store_id") == F.col("_dim_store_id"), "left")
            .join(clients, F.col("client_id") == F.col("_dim_client_id"), "left")
            .join(products, F.col("product_id") == F.col("_dim_product_id"), "left")
            # GMT translation of the local sale time, from the store's time zone. convert_timezone
            # works on TIMESTAMP_NTZ wall clocks, so the result doesn't depend on the session time zone.
            .withColumn(
                "transaction_timestamp_utc",
                F.expr("convert_timezone(store_timezone_id, 'UTC', transaction_timestamp)")
            )
    )

    sales_rejection_reasons = [
        F.when(F.col("_invalid_json"), "INVALID_JSON"),

        F.when(
            F.col("transaction_id").isNull() |
            (F.length("transaction_id") == 0),
            "MISSING_TRANSACTION_ID"
        ),

        F.when(
            F.col("line_number").isNull() |
            (F.col("line_number") < 1) |
            F.col("line_count").isNull() |
            (F.col("line_number") > F.col("line_count")),
            "INVALID_LINE_NUMBER"
        ),

        F.when(
            F.col("transaction_timestamp_raw").isNull() |
            F.col("transaction_timestamp").isNull(),
            "INVALID_TRANSACTION_TIMESTAMP"
        ),

        F.when(
            F.col("quantity").isNull() |
            (F.col("quantity") <= 0),
            "INVALID_QUANTITY"
        ),

        F.when(
            F.col("unit_price").isNull() |
            (F.col("unit_price") <= 0) |
            F.col("amount").isNull() |
            (F.abs(F.col("amount") - F.col("quantity") * F.col("unit_price")) > 0.005),
            "INVALID_AMOUNT"
        ),

        F.when(
            F.col("currency").isNull() |
            (F.col("currency") != "EUR"),
            "INVALID_CURRENCY"
        ),

        F.when(F.col("_dim_store_id").isNull(), "UNKNOWN_STORE"),

        F.when(F.col("_dim_client_id").isNull(), "UNKNOWN_CLIENT"),

        F.when(F.col("_dim_product_id").isNull(), "UNKNOWN_PRODUCT"),

        F.when(
            F.col("_dim_product_id").isNotNull() &
            ~F.col("category").eqNullSafe(F.col("_dim_category")),
            "CATEGORY_MISMATCH"
        )
    ]

    return (
        sales
            .withColumn("rejection_reason", F.concat_ws("|", *sales_rejection_reasons))
            .drop("_invalid_json", "_dim_store_id", "_dim_client_id", "_dim_product_id", "_dim_category")
    )


# ============================================================
# SILVER - Valid sales transactions
# ============================================================

@dp.table(
    name="silver_sales_transactions",
    comment="Validated and typed sales transactions; read by the sales dashboard app",
    schema=SILVER_SALES_SCHEMA,
    # The current-simulation views filter on simulation_id: clustering keeps that filter fast.
    cluster_by=["simulation_id"],
    table_properties={
        "quality": "silver",
        "domain": "retail",
        # Required for the TIMESTAMP_NTZ column transaction_timestamp
        "delta.feature.timestampNtz": "supported"
    }
)
def silver_sales_transactions():

    return (
        validated_sales()
            .filter(F.col("rejection_reason") == "")
            .drop("rejection_reason")
            .select(
                "raw_event",
                "source_topic",
                "source_partition",
                "source_offset",
                "source_timestamp",
                "ingestion_timestamp",
                "transaction_id",
                "line_number",
                "line_count",
                "exit_event_id",
                "store_id",
                "client_id",
                "product_id",
                "category",
                "quantity",
                "unit_price",
                "amount",
                "currency",
                "transaction_timestamp_raw",
                "store_timezone_id",
                "transaction_timestamp",
                "transaction_timestamp_utc",
                "simulation_id"
            )
    )


# ============================================================
# QUARANTINE - Invalid sales transactions
# ============================================================

@dp.table(
    name="quarantine_sales_transactions",
    comment="Invalid sales transactions requiring remediation",
    schema=QUARANTINE_SALES_SCHEMA,
    table_properties={
        "quality": "quarantine",
        "domain": "retail",
        # Required for the TIMESTAMP_NTZ column transaction_timestamp
        "delta.feature.timestampNtz": "supported"
    }
)
def quarantine_sales_transactions():

    return (
        validated_sales()
            .filter(F.col("rejection_reason") != "")
            .withColumn("record_status", F.lit("OPEN"))
            .withColumn("quarantine_timestamp", F.current_timestamp())
            .select(
                "raw_event",
                "source_topic",
                "source_partition",
                "source_offset",
                "source_timestamp",
                "ingestion_timestamp",
                "transaction_id",
                "line_number",
                "line_count",
                "exit_event_id",
                "store_id",
                "client_id",
                "product_id",
                "category",
                "quantity",
                "unit_price",
                "amount",
                "currency",
                "transaction_timestamp_raw",
                "store_timezone_id",
                "transaction_timestamp",
                "transaction_timestamp_utc",
                "simulation_id",
                "rejection_reason",
                "record_status",
                "quarantine_timestamp"
            )
    )
