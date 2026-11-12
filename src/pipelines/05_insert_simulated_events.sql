
-- ============================================================
-- 05 - Insert simulated people counter events
-- ============================================================

INSERT INTO workspace.test02_streaming.simulated_event_source
(
    raw_event,
    source_topic,
    source_partition,
    source_offset,
    source_timestamp
)

SELECT
    raw_event,
    'people-counter-simulation',
    0,
    event_offset,
    CURRENT_TIMESTAMP()
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
AS events(event_offset, raw_event);
