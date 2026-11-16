-- ============================================================
-- Metric view: sales KPIs of clients and stores
-- Target: workspace.test02_metric.sales_metrics
-- Source: workspace.test02_streaming.silver_sales_transactions (one row
--         per item sold), joined to dim_store, dim_client, dim_product.
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

CREATE VIEW IF NOT EXISTS workspace.test02_metric.sales_metrics
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

ALTER VIEW workspace.test02_metric.sales_metrics
AS $$
version: 1.1
source: workspace.test02_streaming.silver_sales_transactions
comment: "Sales KPIs of clients and stores, in every channel, computed live from silver at query time. One source row per item sold; a transaction is a basket of items. Glossary: doc/kpi_glossary.md"
joins:
  - name: dim_store
    source: workspace.test02_warehouse.dim_store
    'on': source.store_id = dim_store.store_id
  - name: dim_client
    source: workspace.test02_warehouse.dim_client
    'on': source.client_id = dim_client.client_id
  - name: dim_product
    source: workspace.test02_warehouse.dim_product
    'on': source.product_id = dim_product.product_id
dimensions:
  - name: Simulation
    expr: source.simulation_id
    comment: "The simulation the sale belongs to: one START of the people-stream app, identified by its UTC start time (YYYYMMDDTHHMMSSmmm). The latest simulation is the highest id; filter on it to see the current run."
  - name: Client
    expr: source.client_id
    comment: "The buyer, by natural key (CL-<country>-<number>). Every client is registered in one country."
  - name: Client Country
    expr: dim_client.country_code
    comment: "Country where the buyer is registered (ISO 3166 code)."
  - name: Client Type
    expr: "CASE WHEN dim_client.country_code = dim_store.country_code THEN 'Local' ELSE 'Visitor' END"
    comment: "Local when the buyer is registered in the store's country, Visitor when registered in another country (a tourist). Online buyers are always local."
  - name: Store
    expr: source.store_id
    comment: "The point of sale, by natural key: a physical store (e.g. IT-MI-001) or a country's online store (e.g. IT-EC-001)."
  - name: Store Name
    expr: dim_store.store_name
    comment: "Name of the point of sale, e.g. Milan Galleria Vittorio Emanuele, or E-commerce Italy for an online store."
  - name: Channel
    expr: dim_store.channel
    comment: "Sales channel of the point of sale: RETAIL (physical store), FLAGSHIP (the two flagships, Milan and New York) or ECOM (the country's online store)."
  - name: Store Country
    expr: dim_store.country_code
    comment: "Country of the point of sale (ISO 3166 code)."
  - name: Store Country Name
    expr: dim_store.country_name
    comment: "Country of the point of sale, by name."
  - name: City
    expr: dim_store.city
    comment: "City of the point of sale; Online for the e-commerce stores."
  - name: Macro Region
    expr: dim_store.macro_region
    comment: "Macro region of the point of sale: EUROPE, AMERICAS or ASIA."
  - name: Category
    expr: source.category
    comment: "Merchandise category of the item: SHOES, BAGS, READY_TO_WEAR, ACCESSORIES, TRAVEL or SUNGLASSES."
  - name: Product
    expr: source.product_id
    comment: "The item sold, by natural key (e.g. SH-0007)."
  - name: Product Name
    expr: dim_product.product_name
    comment: "Name of the item sold, as in the product dimension, e.g. Shoes 007."
  - name: Date (GMT)
    expr: "CAST(source.transaction_timestamp_utc AS DATE)"
    comment: "Calendar date of the sale in GMT, the same timeline for every store and channel."
  - name: Hour (GMT)
    expr: "HOUR(source.transaction_timestamp_utc)"
    comment: "Hour of the day of the sale in GMT, 0 to 23."
  - name: Local Date
    expr: "CAST(source.transaction_timestamp AS DATE)"
    comment: "Calendar date of the sale in the store's local time."
measures:
  - name: Revenue
    expr: SUM(source.amount)
    comment: "What was sold, in EUR: the sum of the items' amounts, in every channel. By client it is the client's total spent; by store, the store's revenue. Values are always registered in euro."
    synonyms: ["Total spent", "Sales value", "Turnover"]
    format:
      type: currency
      currency_code: EUR
      decimal_places:
        type: exact
        places: 0
  - name: Transactions
    expr: COUNT(DISTINCT source.transaction_id)
    comment: "Number of purchases. A transaction is everything one buyer bought in one store visit or one online order: a basket of one or more items."
    synonyms: ["Purchases", "Baskets", "Orders"]
    format:
      type: number
  - name: Items
    expr: SUM(source.quantity)
    comment: "Number of items sold. A transaction holds at most one item per category."
    synonyms: ["Items bought", "Quantity", "Units"]
    format:
      type: number
  - name: Average Basket
    expr: "MEASURE(`Revenue`) / MEASURE(`Transactions`)"
    comment: "Average spend per purchase, in EUR: Revenue divided by Transactions."
    synonyms: ["Average transaction", "Average ticket"]
    format:
      type: currency
      currency_code: EUR
      decimal_places:
        type: exact
        places: 0
  - name: Items per Basket
    expr: "MEASURE(`Items`) / MEASURE(`Transactions`)"
    comment: "Average number of items per purchase: Items divided by Transactions."
    format:
      type: number
      decimal_places:
        type: exact
        places: 2
  - name: Stores Visited
    expr: COUNT(DISTINCT source.store_id)
    comment: "Number of different points of sale where purchases were made; a country's online store counts as one. By client: the stores the client bought in."
    format:
      type: number
  - name: Distinct Clients
    expr: COUNT(DISTINCT source.client_id)
    comment: "Number of different clients who bought. Not additive across stores: a client who bought in two stores counts once in each, and once overall."
    synonyms: ["Buyers", "Unique clients"]
    format:
      type: number
  - name: Online Revenue
    expr: "COALESCE(SUM(source.amount) FILTER (WHERE dim_store.channel = 'ECOM'), 0)"
    comment: "Revenue in EUR made online, in the e-commerce stores (channel ECOM)."
    format:
      type: currency
      currency_code: EUR
      decimal_places:
        type: exact
        places: 0
  - name: Online Share
    expr: "MEASURE(`Online Revenue`) / MEASURE(`Revenue`)"
    comment: "Part of the revenue made online: Online Revenue divided by Revenue. By client: the share of the client's total spent made online."
    format:
      type: percentage
      decimal_places:
        type: exact
        places: 1
  - name: Visitor Revenue
    expr: "COALESCE(SUM(source.amount) FILTER (WHERE dim_client.country_code <> dim_store.country_code), 0)"
    comment: "Revenue in EUR from visitors: clients registered in a country other than the store's."
    format:
      type: currency
      currency_code: EUR
      decimal_places:
        type: exact
        places: 0
  - name: Visitor Share
    expr: "MEASURE(`Visitor Revenue`) / MEASURE(`Revenue`)"
    comment: "Part of the revenue from visitors: Visitor Revenue divided by Revenue. About 70% at the flagships, about 30% in the other physical stores, 0% online."
    format:
      type: percentage
      decimal_places:
        type: exact
        places: 1
  - name: Store Transactions
    expr: "COUNT(DISTINCT source.transaction_id) FILTER (WHERE dim_store.channel <> 'ECOM')"
    comment: "Transactions in physical stores only (RETAIL and FLAGSHIP): the purchases the people counters can be compared with. The numerator of Conversion."
    format:
      type: number
$$;
