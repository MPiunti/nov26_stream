-- ============================================================
-- Metric view: store KPIs, sales and traffic
-- Target: workspace.test02_metric.store_metrics
-- Source: a query on two silver facts, one row each:
--   - silver_sales_transactions: one row per item sold (every channel);
--   - silver_people_counter_events: one row per door-sensor event
--     (physical stores only).
-- Both carry the store, the simulation and the GMT time, so sales and
-- traffic aggregate over the same slices and Conversion (transactions
-- per person out) is a measure of its own. A query source can't use
-- joins: the store and client attributes are joined in the query.
--
-- Every dimension and measure has a functional description (comment);
-- together they are the glossary, doc/kpi_glossary.md, which repeats
-- them word for word (a test checks it). Change both together.
--
-- Deployed by the job retail-metric-views (resources/modeling.metrics.job.yml).
-- Created if missing, then ALTERed to this definition: ALTER keeps the
-- grants (the sales dashboard's SELECT); replacing the view would drop them.
-- Rules: doc/kpi_metrics.md.
-- ============================================================

CREATE VIEW IF NOT EXISTS workspace.test02_metric.store_metrics
WITH METRICS
LANGUAGE YAML
AS $$
version: 1.1
source: workspace.test02_streaming.silver_sales_transactions
dimensions:
  - name: Store
    expr: store_id
measures:
  - name: Revenue
    expr: SUM(amount)
$$;

ALTER VIEW workspace.test02_metric.store_metrics
AS $$
version: 1.1
source: |
  SELECT s.simulation_id, s.store_id, d.store_name, d.channel, d.city, d.country_code AS store_country,
         d.country_name AS store_country_name, d.macro_region,
         s.transaction_id, s.client_id, c.country_code AS client_country, s.amount, s.quantity,
         s.transaction_timestamp_utc AS time_utc,
         CAST(NULL AS STRING) AS event_type, CAST(NULL AS INT) AS people_count
  FROM workspace.test02_streaming.silver_sales_transactions s
  JOIN workspace.test02_warehouse.dim_store d ON s.store_id = d.store_id
  LEFT JOIN workspace.test02_warehouse.dim_client c ON s.client_id = c.client_id
  UNION ALL
  SELECT e.simulation_id, e.store_id, d.store_name, d.channel, d.city, d.country_code,
         d.country_name, d.macro_region,
         CAST(NULL AS STRING), CAST(NULL AS STRING), CAST(NULL AS STRING), CAST(NULL AS DECIMAL(12,2)),
         CAST(NULL AS INT),
         convert_timezone(e.store_timezone_id, 'UTC', e.event_timestamp),
         e.event_type, e.people_count
  FROM workspace.test02_streaming.silver_people_counter_events e
  JOIN workspace.test02_warehouse.dim_store d ON e.store_id = d.store_id
comment: "Store KPIs: what each point of sale sells, and for the physical stores the traffic at the door and the conversion, computed live from silver at query time. Sales are one row per item sold; traffic one row per door-sensor event. Glossary: doc/kpi_glossary.md"
dimensions:
  - name: Simulation
    expr: simulation_id
    comment: "The simulation the sales and events belong to: one START of the people-stream app, identified by its UTC start time (YYYYMMDDTHHMMSSmmm). The latest simulation is the highest id; filter on it to see the current run."
  - name: Store
    expr: store_id
    comment: "The point of sale, by natural key: a physical store (e.g. IT-MI-001) or a country's online store (e.g. IT-EC-001)."
  - name: Store Name
    expr: store_name
    comment: "Name of the point of sale, e.g. Milan Galleria Vittorio Emanuele, or E-commerce Italy for an online store."
  - name: Channel
    expr: channel
    comment: "Sales channel of the point of sale: RETAIL (physical store), FLAGSHIP (the two flagships, Milan and New York) or ECOM (the country's online store, which has no people counting)."
  - name: City
    expr: city
    comment: "City of the point of sale; Online for the e-commerce stores."
  - name: Store Country
    expr: store_country
    comment: "Country of the point of sale (ISO 3166 code)."
  - name: Store Country Name
    expr: store_country_name
    comment: "Country of the point of sale, by name."
  - name: Macro Region
    expr: macro_region
    comment: "Macro region of the point of sale: EUROPE, AMERICAS or ASIA."
  - name: Date (GMT)
    expr: "CAST(time_utc AS DATE)"
    comment: "Calendar date in GMT of the sale or the door event, the same timeline for every store."
  - name: Hour (GMT)
    expr: "HOUR(time_utc)"
    comment: "Hour of the day in GMT of the sale or the door event, 0 to 23."
measures:
  - name: Revenue
    expr: "COALESCE(SUM(amount), 0)"
    comment: "What the point of sale sold, in EUR: the sum of the amounts of the items sold. Values are always registered in euro."
    synonyms: ["Sales value", "Turnover", "Store revenue"]
    format:
      type: currency
      currency_code: EUR
      decimal_places:
        type: exact
        places: 0
  - name: Transactions
    expr: COUNT(DISTINCT transaction_id)
    comment: "Number of purchases at the point of sale. A transaction is everything one buyer bought in one store visit or one online order: a basket of one or more items."
    synonyms: ["Purchases", "Baskets", "Orders"]
    format:
      type: number
  - name: Items
    expr: "COALESCE(SUM(quantity), 0)"
    comment: "Number of items sold at the point of sale. A transaction holds at most one item per category."
    synonyms: ["Items sold", "Quantity", "Units"]
    format:
      type: number
  - name: Average Basket
    expr: "try_divide(MEASURE(`Revenue`), MEASURE(`Transactions`))"
    comment: "Average spend per purchase at the point of sale, in EUR: Revenue divided by Transactions."
    synonyms: ["Average transaction", "Average ticket"]
    format:
      type: currency
      currency_code: EUR
      decimal_places:
        type: exact
        places: 0
  - name: Items per Basket
    expr: "try_divide(MEASURE(`Items`), MEASURE(`Transactions`))"
    comment: "Average number of items per purchase at the point of sale: Items divided by Transactions."
    format:
      type: number
      decimal_places:
        type: exact
        places: 2
  - name: Distinct Clients
    expr: COUNT(DISTINCT client_id)
    comment: "Number of different clients who bought at the point of sale. Not additive across stores: a client who bought in two stores counts once in each, and once overall."
    synonyms: ["Buyers", "Unique clients"]
    format:
      type: number
  - name: Visitor Revenue
    expr: "COALESCE(SUM(amount) FILTER (WHERE client_country <> store_country), 0)"
    comment: "Revenue in EUR from visitors: clients registered in a country other than the store's."
    format:
      type: currency
      currency_code: EUR
      decimal_places:
        type: exact
        places: 0
  - name: Visitor Share
    expr: "try_divide(MEASURE(`Visitor Revenue`), MEASURE(`Revenue`))"
    comment: "Part of the revenue from visitors: Visitor Revenue divided by Revenue. About 70% at the flagships, about 30% in the other physical stores, 0% online."
    format:
      type: percentage
      decimal_places:
        type: exact
        places: 1
  - name: Store Transactions
    expr: "COUNT(DISTINCT transaction_id) FILTER (WHERE channel <> 'ECOM')"
    comment: "Transactions in physical stores only (RETAIL and FLAGSHIP): the purchases the people counters can be compared with. The numerator of Conversion."
    format:
      type: number
  - name: People In
    expr: "COALESCE(SUM(people_count) FILTER (WHERE event_type = 'ENTRY'), 0)"
    comment: "People who entered the store, as counted by the sensor at the door. Physical stores only: e-commerce stores have no people counting."
    synonyms: ["Footfall", "Entries", "Visitors"]
    format:
      type: number
  - name: People Out
    expr: "COALESCE(SUM(people_count) FILTER (WHERE event_type = 'EXIT'), 0)"
    comment: "People who left the store, as counted by the sensor at the door. Only people leaving can buy, so this is the denominator of Conversion."
    synonyms: ["Exits"]
    format:
      type: number
  - name: Conversion
    expr: "try_divide(MEASURE(`Store Transactions`), MEASURE(`People Out`))"
    comment: "Share of the people leaving a physical store who bought something: Store Transactions divided by People Out. Physical stores only (RETAIL and FLAGSHIP); empty for e-commerce, which has no people counting."
    synonyms: ["Conversion rate", "Buyers per visitor"]
    format:
      type: percentage
      decimal_places:
        type: exact
        places: 1
$$;
