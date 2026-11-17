-- ============================================================
-- Metric view: client KPIs
-- Target: workspace.test02_metric.client_metrics
-- Source: a query on workspace.test02_streaming.silver_sales_transactions
--         (one row per item sold, every channel), joined to dim_client,
--         dim_store and dim_product on their natural keys, with each
--         client's total spent in the simulation (a window over the
--         client and the simulation): the base of the client segments.
--         A query source can't use joins: the dimensions are joined in it.
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
source: |
  SELECT s.simulation_id, s.client_id, c.country_code AS client_country, c.macro_region AS client_region,
         s.store_id, d.store_name, d.channel, d.country_code AS store_country, d.macro_region,
         s.category, p.product_name, s.transaction_id, s.amount, s.quantity, s.transaction_timestamp_utc,
         SUM(s.amount) OVER (PARTITION BY s.simulation_id, s.client_id) AS client_simulation_spent
  FROM workspace.test02_streaming.silver_sales_transactions s
  JOIN workspace.test02_warehouse.dim_store d ON s.store_id = d.store_id
  LEFT JOIN workspace.test02_warehouse.dim_client c ON s.client_id = c.client_id
  LEFT JOIN workspace.test02_warehouse.dim_product p ON s.product_id = p.product_id
comment: "Client KPIs: what each client buys, in every channel, and the client segments by spend, computed live from silver at query time. One source row per item sold; a transaction is a basket of items. Glossary: doc/kpi_glossary.md"
dimensions:
  - name: Simulation
    expr: simulation_id
    comment: "The simulation the purchase belongs to: one START of the people-stream app, identified by its UTC start time (YYYYMMDDTHHMMSSmmm). The latest simulation is the highest id; filter on it to see the current run."
  - name: Client
    expr: client_id
    comment: "The buyer, by natural key (CL-<country>-<number>). Every client is registered in one country."
  - name: Client Country
    expr: client_country
    comment: "Country where the client is registered (ISO 3166 code)."
  - name: Client Region
    expr: client_region
    comment: "Macro region of the client's registration country: EUROPE, AMERICAS or ASIA."
  - name: Client Type
    expr: "CASE WHEN client_country = store_country THEN 'Local' ELSE 'Visitor' END"
    comment: "Per purchase: Local when the client is registered in the country of the store where they bought, Visitor when registered in another country (a tourist). Online purchases are always local."
  - name: Client Segment
    expr: "CASE WHEN client_simulation_spent IS NULL OR client_simulation_spent <= 0 THEN 'ND' WHEN client_simulation_spent < 600 THEN 'OCC' WHEN client_simulation_spent < 2000 THEN 'EXP' WHEN client_simulation_spent < 5000 THEN 'ASP' WHEN client_simulation_spent < 10000 THEN 'POT' WHEN client_simulation_spent < 15000 THEN 'VIC1' ELSE 'VICSTAR' END"
    comment: "The client's segment by what they spent in the whole simulation, in every channel: OCC (Occasional) under 600 EUR, EXP (Experiencer) 600 to under 2,000, ASP (Aspiring) 2,000 to under 5,000, POT (Potential VIC) 5,000 to under 10,000, VIC1 10,000 to under 15,000, VICSTAR 15,000 and more, ND (Not Defined) when there is no spend to classify. Fixed per client and simulation: filters on dates, stores or categories don't move a client to another segment."
    synonyms: ["Segment", "Client tier", "Spend segment", "VIC segment"]
  - name: Client Segment Name
    expr: "CASE WHEN client_simulation_spent IS NULL OR client_simulation_spent <= 0 THEN 'Not Defined' WHEN client_simulation_spent < 600 THEN 'Occasional' WHEN client_simulation_spent < 2000 THEN 'Experiencer' WHEN client_simulation_spent < 5000 THEN 'Aspiring' WHEN client_simulation_spent < 10000 THEN 'Potential VIC' WHEN client_simulation_spent < 15000 THEN 'VIC1' ELSE 'VICSTAR' END"
    comment: "The client segment's name: Occasional, Experiencer, Aspiring, Potential VIC, VIC1, VICSTAR or Not Defined, for the code in Client Segment."
  - name: Client Segment Rank
    expr: "CASE WHEN client_simulation_spent IS NULL OR client_simulation_spent <= 0 THEN 0 WHEN client_simulation_spent < 600 THEN 1 WHEN client_simulation_spent < 2000 THEN 2 WHEN client_simulation_spent < 5000 THEN 3 WHEN client_simulation_spent < 10000 THEN 4 WHEN client_simulation_spent < 15000 THEN 5 ELSE 6 END"
    comment: "The client segment's position from the lowest to the highest spend, to sort segments: 0 Not Defined, 1 Occasional, 2 Experiencer, 3 Aspiring, 4 Potential VIC, 5 VIC1, 6 VICSTAR."
  - name: Store
    expr: store_id
    comment: "Where the client bought, by natural key: a physical store (e.g. IT-MI-001) or a country's online store (e.g. IT-EC-001)."
  - name: Store Name
    expr: store_name
    comment: "Name of the point of sale where the client bought, e.g. Milan Galleria Vittorio Emanuele, or E-commerce Italy online."
  - name: Channel
    expr: channel
    comment: "Sales channel of the purchase: RETAIL (physical store), FLAGSHIP (the two flagships, Milan and New York) or ECOM (online)."
  - name: Store Country
    expr: store_country
    comment: "Country of the point of sale where the client bought (ISO 3166 code)."
  - name: Macro Region
    expr: macro_region
    comment: "Macro region of the point of sale where the client bought: EUROPE, AMERICAS or ASIA."
  - name: Category
    expr: category
    comment: "Merchandise category of the items bought: SHOES, BAGS, READY_TO_WEAR, ACCESSORIES, TRAVEL or SUNGLASSES."
  - name: Product Name
    expr: product_name
    comment: "Name of the item bought, as in the product dimension, e.g. Shoes 007."
  - name: Date (GMT)
    expr: "CAST(transaction_timestamp_utc AS DATE)"
    comment: "Calendar date of the purchase in GMT, the same timeline for every store and channel."
measures:
  - name: Total Spent
    expr: "COALESCE(SUM(amount), 0)"
    comment: "What the client spent, in EUR, in every channel: the sum of the amounts of the items bought. Values are always registered in euro."
    synonyms: ["Client spend", "Client value", "Total spend"]
    format:
      type: currency
      currency_code: EUR
      decimal_places:
        type: exact
        places: 0
  - name: Clients
    expr: COUNT(DISTINCT client_id)
    comment: "Number of different clients who bought. By segment: how many clients are in each segment. Not additive: a client who bought in two stores counts once overall."
    synonyms: ["Buyers", "Number of clients", "Client count"]
    format:
      type: number
  - name: Transactions
    expr: COUNT(DISTINCT transaction_id)
    comment: "Number of purchases the client made. A transaction is everything bought in one store visit or one online order: a basket of one or more items."
    synonyms: ["Purchases", "Baskets", "Orders"]
    format:
      type: number
  - name: Items
    expr: "COALESCE(SUM(quantity), 0)"
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
    expr: COUNT(DISTINCT store_id)
    comment: "Number of different points of sale where the client bought; a country's online store counts as one."
    format:
      type: number
  - name: Online Spent
    expr: "COALESCE(SUM(amount) FILTER (WHERE channel = 'ECOM'), 0)"
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
