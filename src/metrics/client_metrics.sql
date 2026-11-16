-- ============================================================
-- Metric view: client KPIs
-- Target: workspace.test02_metric.client_metrics
-- Source: workspace.test02_streaming.silver_sales_transactions (one row
--         per item sold, every channel), joined to dim_client,
--         dim_store and dim_product on their natural keys.
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

CREATE VIEW IF NOT EXISTS workspace.test02_metric.client_metrics
WITH METRICS
LANGUAGE YAML
AS $$
version: 1.1
source: workspace.test02_streaming.silver_sales_transactions
dimensions:
  - name: Client
    expr: client_id
measures:
  - name: Total Spent
    expr: SUM(amount)
$$;

ALTER VIEW workspace.test02_metric.client_metrics
AS $$
version: 1.1
source: workspace.test02_streaming.silver_sales_transactions
comment: "Client KPIs: what each client buys, in every channel, computed live from silver at query time. One source row per item sold; a transaction is a basket of items. Glossary: doc/kpi_glossary.md"
joins:
  - name: dim_client
    source: workspace.test02_warehouse.dim_client
    'on': source.client_id = dim_client.client_id
  - name: dim_store
    source: workspace.test02_warehouse.dim_store
    'on': source.store_id = dim_store.store_id
  - name: dim_product
    source: workspace.test02_warehouse.dim_product
    'on': source.product_id = dim_product.product_id
dimensions:
  - name: Simulation
    expr: source.simulation_id
    comment: "The simulation the purchase belongs to: one START of the people-stream app, identified by its UTC start time (YYYYMMDDTHHMMSSmmm). The latest simulation is the highest id; filter on it to see the current run."
  - name: Client
    expr: source.client_id
    comment: "The buyer, by natural key (CL-<country>-<number>). Every client is registered in one country."
  - name: Client Country
    expr: dim_client.country_code
    comment: "Country where the client is registered (ISO 3166 code)."
  - name: Client Region
    expr: dim_client.macro_region
    comment: "Macro region of the client's registration country: EUROPE, AMERICAS or ASIA."
  - name: Client Type
    expr: "CASE WHEN dim_client.country_code = dim_store.country_code THEN 'Local' ELSE 'Visitor' END"
    comment: "Per purchase: Local when the client is registered in the country of the store where they bought, Visitor when registered in another country (a tourist). Online purchases are always local."
  - name: Store
    expr: source.store_id
    comment: "Where the client bought, by natural key: a physical store (e.g. IT-MI-001) or a country's online store (e.g. IT-EC-001)."
  - name: Store Name
    expr: dim_store.store_name
    comment: "Name of the point of sale where the client bought, e.g. Milan Galleria Vittorio Emanuele, or E-commerce Italy online."
  - name: Channel
    expr: dim_store.channel
    comment: "Sales channel of the purchase: RETAIL (physical store), FLAGSHIP (the two flagships, Milan and New York) or ECOM (online)."
  - name: Store Country
    expr: dim_store.country_code
    comment: "Country of the point of sale where the client bought (ISO 3166 code)."
  - name: Macro Region
    expr: dim_store.macro_region
    comment: "Macro region of the point of sale where the client bought: EUROPE, AMERICAS or ASIA."
  - name: Category
    expr: source.category
    comment: "Merchandise category of the items bought: SHOES, BAGS, READY_TO_WEAR, ACCESSORIES, TRAVEL or SUNGLASSES."
  - name: Product Name
    expr: dim_product.product_name
    comment: "Name of the item bought, as in the product dimension, e.g. Shoes 007."
  - name: Date (GMT)
    expr: "CAST(source.transaction_timestamp_utc AS DATE)"
    comment: "Calendar date of the purchase in GMT, the same timeline for every store and channel."
measures:
  - name: Total Spent
    expr: "COALESCE(SUM(source.amount), 0)"
    comment: "What the client spent, in EUR, in every channel: the sum of the amounts of the items bought. Values are always registered in euro."
    synonyms: ["Client spend", "Client value", "Total spend"]
    format:
      type: currency
      currency_code: EUR
      decimal_places:
        type: exact
        places: 0
  - name: Transactions
    expr: COUNT(DISTINCT source.transaction_id)
    comment: "Number of purchases the client made. A transaction is everything bought in one store visit or one online order: a basket of one or more items."
    synonyms: ["Purchases", "Baskets", "Orders"]
    format:
      type: number
  - name: Items
    expr: "COALESCE(SUM(source.quantity), 0)"
    comment: "Number of items the client bought, across all purchases. A purchase holds at most one item per category."
    synonyms: ["Items bought", "Quantity"]
    format:
      type: number
  - name: Average Basket
    expr: "try_divide(MEASURE(`Total Spent`), MEASURE(`Transactions`))"
    comment: "What the client spends per purchase, in EUR: Total Spent divided by Transactions."
    synonyms: ["Average transaction", "Average ticket"]
    format:
      type: currency
      currency_code: EUR
      decimal_places:
        type: exact
        places: 0
  - name: Stores Visited
    expr: COUNT(DISTINCT source.store_id)
    comment: "Number of different points of sale where the client bought; a country's online store counts as one."
    format:
      type: number
  - name: Online Spent
    expr: "COALESCE(SUM(source.amount) FILTER (WHERE dim_store.channel = 'ECOM'), 0)"
    comment: "What the client spent online, in EUR, in the e-commerce stores (channel ECOM)."
    format:
      type: currency
      currency_code: EUR
      decimal_places:
        type: exact
        places: 0
  - name: Online Share
    expr: "try_divide(MEASURE(`Online Spent`), MEASURE(`Total Spent`))"
    comment: "Part of the client's spend made online: Online Spent divided by Total Spent."
    format:
      type: percentage
      decimal_places:
        type: exact
        places: 1
$$;
