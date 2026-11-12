
from pyspark import pipelines as dp
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType,
    StructField,
    StringType,
    IntegerType
)

# ============================================================
# SILVER - Event parsing and business validation
# ============================================================

BRONZE_TABLE = "workspace.test02_streaming.bronze_people_counter_events"
STORE_TABLE = "workspace.test02_streaming.dim_store"

EVENT_SCHEMA = StructType([
    StructField("event_id", StringType(), True),
    StructField("store_id", StringType(), True),
    StructField("sensor_id", StringType(), True),
    StructField("event_timestamp", StringType(), True),
    StructField("event_type", StringType(), True),
    StructField("people_count", IntegerType(), True)
])


def validated_events():

    # Read Bronze as a streaming source.
    bronze = (
        spark.readStream
            .table(BRONZE_TABLE)
            .withColumn(
                "_event",
                F.from_json(F.col("raw_event"), EVENT_SCHEMA)
            )
            .select(
                "raw_event",
                "source_topic",
                "source_partition",
                "source_offset",
                "source_timestamp",
                "ingestion_timestamp",
                F.trim(F.col("_event.event_id")).alias("event_id"),
                F.trim(F.col("_event.store_id")).alias("store_id"),
                F.trim(F.col("_event.sensor_id")).alias("sensor_id"),
                F.col("_event.event_timestamp").alias(
                    "event_timestamp_raw"
                ),
                F.upper(
                    F.trim(F.col("_event.event_type"))
                ).alias("event_type"),
                F.col("_event.people_count").alias("people_count"),
                F.col("_event").isNull().alias("_invalid_json")
            )
            .withColumn(
                "event_timestamp",
                F.expr(
                    "try_cast(event_timestamp_raw AS TIMESTAMP_NTZ)"
                )
            )
    )

    # Static dimension lookup.
    stores = (
        spark.read
            .table(STORE_TABLE)
            .select(
                F.col("store_id").alias("_dim_store_id"),
                F.col("timezone_id").alias("store_timezone_id")
            )
    )

    events = (
        bronze.alias("e")
            .join(
                stores.alias("s"),
                F.col("e.store_id") == F.col("s._dim_store_id"),
                "left"
            )
            .drop("_dim_store_id")
    )

    # Business and structural validation.
    rejection_reasons = [
        F.when(F.col("_invalid_json"), "INVALID_JSON"),

        F.when(
            F.col("event_id").isNull() |
            (F.length("event_id") == 0),
            "MISSING_EVENT_ID"
        ),

        F.when(
            F.col("store_id").isNull() |
            (F.length("store_id") == 0),
            "MISSING_STORE_ID"
        ),

        F.when(
            F.col("sensor_id").isNull() |
            (F.length("sensor_id") == 0),
            "MISSING_SENSOR_ID"
        ),

        F.when(
            F.col("event_timestamp_raw").isNull() |
            (F.length(F.trim("event_timestamp_raw")) == 0) |
            F.col("event_timestamp").isNull(),
            "INVALID_EVENT_TIMESTAMP"
        ),

        F.when(
            F.col("event_type").isNull() |
            (~F.col("event_type").isin("ENTRY", "EXIT")),
            "INVALID_EVENT_TYPE"
        ),

        F.when(
            F.col("people_count").isNull() |
            (F.col("people_count") <= 0),
            "INVALID_PEOPLE_COUNT"
        ),

        F.when(
            F.col("store_id").isNotNull() &
            (F.length("store_id") > 0) &
            F.col("store_timezone_id").isNull(),
            "UNKNOWN_STORE"
        )
    ]

    return (
        events
            .withColumn(
                "rejection_reason",
                F.concat_ws("|", *rejection_reasons)
            )
            .drop("_invalid_json")
    )


# ------------------------------------------------------------
# SILVER - Valid events
# ------------------------------------------------------------

@dp.table(
    name="silver_people_counter_events",
    comment="Validated and typed retail people counter events",
    table_properties={
        "quality": "silver",
        "domain": "retail"
    }
)
def silver_people_counter_events():

    return (
        validated_events()
            .filter(F.col("rejection_reason") == "")
            .drop("rejection_reason")
    )


# ------------------------------------------------------------
# QUARANTINE - Invalid events
# ------------------------------------------------------------

@dp.table(
    name="quarantine_people_counter_events",
    comment="Invalid retail people counter events requiring remediation",
    table_properties={
        "quality": "quarantine",
        "domain": "retail"
    }
)
def quarantine_people_counter_events():

    return (
        validated_events()
            .filter(F.col("rejection_reason") != "")
            .withColumn("record_status", F.lit("OPEN"))
            .withColumn("quarantine_timestamp", F.current_timestamp())
    )
