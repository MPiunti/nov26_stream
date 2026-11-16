-- ============================================================
-- Metric view: store traffic from the people counters
-- Target: workspace.test02_metric.people_metrics
-- Source: workspace.test02_streaming.silver_people_counter_events,
--         joined to dim_store. Physical stores only (RETAIL, FLAGSHIP):
--         the e-commerce stores have no people counting.
--
-- Every dimension and measure has a functional description (comment);
-- together they are the glossary, doc/kpi_glossary.md, which repeats
-- them word for word (a test checks it). Change both together.
--
-- Deployed by the job retail-metric-views (resources/modeling.metrics.job.yml).
-- Created if missing, then ALTERed to this definition: ALTER keeps the
-- grants (the sales dashboard's SELECT), CREATE OR REPLACE would drop them.
-- Rules: doc/kpi_metrics.md.
-- ============================================================

CREATE VIEW IF NOT EXISTS workspace.test02_metric.people_metrics
WITH METRICS
LANGUAGE YAML
AS $$
version: 1.1
source: workspace.test02_streaming.silver_people_counter_events
dimensions:
  - name: Store
    expr: store_id
measures:
  - name: People Out
    expr: SUM(people_count)
$$;

ALTER VIEW workspace.test02_metric.people_metrics
AS $$
version: 1.1
source: workspace.test02_streaming.silver_people_counter_events
comment: "Store traffic counted by the people counters at the doors of the physical stores, computed live from silver at query time. Combined with sales_metrics for Conversion. Glossary: doc/kpi_glossary.md"
joins:
  - name: dim_store
    source: workspace.test02_warehouse.dim_store
    'on': source.store_id = dim_store.store_id
dimensions:
  - name: Simulation
    expr: source.simulation_id
    comment: "The simulation the event belongs to: one START of the people-stream app, identified by its UTC start time (YYYYMMDDTHHMMSSmmm). The latest simulation is the highest id; filter on it to see the current run."
  - name: Store
    expr: source.store_id
    comment: "The physical store whose people counter registered the event, by natural key (e.g. IT-MI-001)."
  - name: Store Name
    expr: dim_store.store_name
    comment: "Name of the store, e.g. Milan Galleria Vittorio Emanuele."
  - name: Channel
    expr: dim_store.channel
    comment: "Sales channel of the store: RETAIL or FLAGSHIP. E-commerce stores (ECOM) have no people counting, so they never appear here."
  - name: Store Country
    expr: dim_store.country_code
    comment: "Country of the store (ISO 3166 code)."
  - name: Macro Region
    expr: dim_store.macro_region
    comment: "Macro region of the store: EUROPE, AMERICAS or ASIA."
  - name: Date (GMT)
    expr: "CAST(convert_timezone(source.store_timezone_id, 'UTC', source.event_timestamp) AS DATE)"
    comment: "Calendar date of the event in GMT, the same timeline as the sales."
  - name: Hour (GMT)
    expr: "HOUR(convert_timezone(source.store_timezone_id, 'UTC', source.event_timestamp))"
    comment: "Hour of the day of the event in GMT, 0 to 23."
measures:
  - name: People In
    expr: "COALESCE(SUM(source.people_count) FILTER (WHERE source.event_type = 'ENTRY'), 0)"
    comment: "People who entered the store, as counted by the sensor at the door."
    synonyms: ["Footfall", "Entries", "Visitors"]
    format:
      type: number
  - name: People Out
    expr: "COALESCE(SUM(source.people_count) FILTER (WHERE source.event_type = 'EXIT'), 0)"
    comment: "People who left the store. Only people leaving can buy, so this is the denominator of Conversion."
    synonyms: ["Exits"]
    format:
      type: number
$$;
