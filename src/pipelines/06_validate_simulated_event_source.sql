
-- ============================================================
-- 06 - Validate simulated streaming source
-- ============================================================

SELECT
    COUNT(*) AS total_records,
    COUNT(DISTINCT source_offset) AS distinct_offsets,
    COUNT_IF(raw_event IS NULL) AS null_payloads,
    COUNT_IF(source_topic <> 'people-counter-simulation') AS unexpected_topics,
    COUNT_IF(source_partition <> 0) AS unexpected_partitions
FROM workspace.test02_streaming.simulated_event_source;

-- Expected: 8 records, 8 distinct offsets, zero null payloads,
-- zero unexpected topics and zero unexpected partitions.

-- Inspect all raw records before Bronze ingestion.
SELECT
    source_offset,
    source_timestamp,
    raw_event
FROM workspace.test02_streaming.simulated_event_source
ORDER BY source_offset;
