
-- ============================================================
-- 04 - Create generic simulated streaming source
-- Purpose: decouple pipeline development from Event Hubs
-- ============================================================

CREATE TABLE IF NOT EXISTS
    workspace.test02_streaming.simulated_event_source
(
    raw_event STRING NOT NULL
        COMMENT 'Original JSON event payload',

    source_topic STRING
        COMMENT 'Generic source identifier; later Event Hubs topic',

    source_partition INT
        COMMENT 'Source partition identifier; nullable for generic source',

    source_offset BIGINT
        COMMENT 'Source offset; nullable for generic source',

    source_timestamp TIMESTAMP
        COMMENT 'Timestamp provided by the source system'
)
USING DELTA
COMMENT 'Generic append-only source used to simulate incoming people counter events';
