
-- ============================================================
-- 12 - Create simulated sales source
-- Target: workspace.test02_streaming.simulated_sales_source
--
-- Append-only, Event Hubs-like envelope, same columns as
-- simulated_event_source. Filled by the people-stream app's sales
-- simulator with an insert-only MERGE. Rules: doc/sales.md.
-- ============================================================

CREATE TABLE IF NOT EXISTS
    workspace.test02_streaming.simulated_sales_source
(
    raw_event STRING NOT NULL
        COMMENT 'Original JSON sales transaction payload',

    source_topic STRING
        COMMENT 'Source identifier; retail-sales-app for the simulator',

    source_partition INT
        COMMENT 'Source partition: one per macro region (0 EUROPE, 1 AMERICAS, 2 ASIA)',

    source_offset BIGINT
        COMMENT 'Offset within the partition; unique per topic and partition',

    source_timestamp TIMESTAMP
        COMMENT 'Timestamp provided by the source system (simulated UTC)'
)
USING DELTA
COMMENT 'Generic append-only source of simulated sales transactions';
