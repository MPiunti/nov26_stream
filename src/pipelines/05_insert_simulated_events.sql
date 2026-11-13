
-- ============================================================
-- 05 - Insert simulated people counter events (idempotent)
--
-- MERGE on the message identity (source_topic, source_partition,
-- source_offset): rows already in the table are skipped, so running
-- this script again inserts nothing.
--
-- Keep the MERGE insert-only (no WHEN MATCHED clause): Bronze reads
-- this table as a stream, and an update or delete would break it.
-- ============================================================

MERGE INTO workspace.test02_streaming.simulated_event_source AS target

USING (
    SELECT
        raw_event,
        'people-counter-simulation' AS source_topic,
        0 AS source_partition,
        CAST(event_offset AS BIGINT) AS source_offset,
        CURRENT_TIMESTAMP() AS source_timestamp
    FROM VALUES

    -- Valid events
    (
        1,
        '{"event_id":"evt-000001","store_id":"IT-MI-001","sensor_id":"PC-MI-01","event_timestamp":"2026-07-15T15:30:20.123","event_type":"ENTRY","people_count":1}'
    ),
    (
        2,
        '{"event_id":"evt-000002","store_id":"IT-MI-002","sensor_id":"PC-MI-02","event_timestamp":"2026-07-15T15:31:20.123","event_type":"ENTRY","people_count":1}'
    ),
    (
        3,
        '{"event_id":"evt-000003","store_id":"US-NY-001","sensor_id":"PC-NY-01","event_timestamp":"2026-07-15T09:32:20.123","event_type":"EXIT","people_count":1}'
    ),
    (
        4,
        '{"event_id":"evt-000004","store_id":"JP-TK-001","sensor_id":"PC-TK-01","event_timestamp":"2026-07-15T22:33:20.123","event_type":"ENTRY","people_count":2}'
    ),
    (
        5,
        '{"event_id":"evt-000005","store_id":"CN-SH-001","sensor_id":"PC-SH-01","event_timestamp":"2026-07-15T21:34:20.123","event_type":"ENTRY","people_count":1}'
    ),

    -- Invalid JSON
    (
        6,
        '{"event_id":"evt-000006","store_id":"IT-MI-001","event_timestamp":'
    ),

    -- Unknown store
    (
        7,
        '{"event_id":"evt-000007","store_id":"XX-UNKNOWN-001","sensor_id":"PC-XX-01","event_timestamp":"2026-07-15T15:35:20.123","event_type":"ENTRY","people_count":1}'
    ),

    -- Invalid event type
    (
        8,
        '{"event_id":"evt-000008","store_id":"IT-MI-001","sensor_id":"PC-MI-01","event_timestamp":"2026-07-15T15:36:20.123","event_type":"UNKNOWN","people_count":1}'
    )
    AS events(event_offset, raw_event)

    -- One row per message, even if the list above repeats an offset.
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY event_offset
        ORDER BY raw_event
    ) = 1
) AS source

ON  target.source_topic <=> source.source_topic
AND target.source_partition <=> source.source_partition
AND target.source_offset <=> source.source_offset

WHEN NOT MATCHED THEN INSERT (
    raw_event,
    source_topic,
    source_partition,
    source_offset,
    source_timestamp
)
VALUES (
    source.raw_event,
    source.source_topic,
    source.source_partition,
    source.source_offset,
    source.source_timestamp
);
