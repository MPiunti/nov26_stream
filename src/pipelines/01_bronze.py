
from pyspark import pipelines as dp
from pyspark.sql import functions as F

# ============================================================
# BRONZE - Generic streaming ingestion
# ============================================================

SOURCE_TABLE = "workspace.test02_streaming.simulated_event_source"


@dp.table(
    name="bronze_people_counter_events",
    comment="Bronze raw ingestion of anonymous retail people counter events",
    table_properties={
        "quality": "bronze",
        "domain": "retail"
    }
)
def bronze_people_counter_events():

    # skipChangeCommits: every START of the people-stream app deletes the source rows. Without this
    # option the stream would fail on that delete; with it, the delete is skipped and the stream goes on
    # reading the new rows (so the continuous job keeps running). Bronze keeps the earlier rows until a
    # full refresh rebuilds it from the current source. See doc/pipeline.md, "Running the pipeline".
    return (
        spark.readStream
            .option("skipChangeCommits", "true")
            .table(SOURCE_TABLE)
            .select(
                F.col("raw_event"),
                F.col("source_topic"),
                F.col("source_partition"),
                F.col("source_offset"),
                F.col("source_timestamp"),
                F.current_timestamp().alias("ingestion_timestamp")
            )
    )
