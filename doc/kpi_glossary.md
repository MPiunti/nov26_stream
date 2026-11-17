# KPI glossary

The functional definition of every KPI and every dimension the KPIs can be sliced by. Each description below is, word for word, the `comment` of the measure or dimension in its Unity Catalog metric view, so dashboard users, AI/BI and Genie see exactly these definitions. Why metric views, the design rules and the KPI choices are in [`kpi_metrics.md`](kpi_metrics.md).

**Keeping it true:** the definitions live in `src/metrics/*.sql`. Change a description there and here together: a test fails when a description differs, or when a KPI or dimension is missing on either side.

**Reading the calculations:** `source` is the metric view's source table; `dim_store`, `dim_client` and `dim_product` are the dimensions joined on their natural keys. A KPI named in a calculation (e.g. `Total Spent / Transactions`) is that KPI, recomputed for the same slice, so ratios stay correct for any client, store, channel, country, date or hour. `try_divide` leaves a ratio empty instead of failing when there is nothing to divide by.

## 1. Client KPIs: `workspace.test02_metric.client_metrics`

What each client buys, in every channel (retail, flagship, e-commerce). Over `silver_sales_transactions`: one row per item sold; a transaction is a basket of items ([`sales.md`](sales.md) §5).

### 1.1 KPIs

| KPI | Functional description | Calculation |
|---|---|---|
| Total Spent | What the client spent, in EUR, in every channel: the sum of the amounts of the items bought. Values are always registered in euro. | `COALESCE(SUM(amount), 0)` |
| Clients | Number of different clients who bought. By segment: how many clients are in each segment. Not additive: a client who bought in two stores counts once overall. | `COUNT(DISTINCT client_id)` |
| Transactions | Number of purchases the client made. A transaction is everything bought in one store visit or one online order: a basket of one or more items. | `COUNT(DISTINCT transaction_id)` |
| Items | Number of items the client bought, across all purchases. A purchase holds at most one item per category. | `COALESCE(SUM(quantity), 0)` |
| Average Basket | What the client spends per purchase, in EUR: Total Spent divided by Transactions. | `try_divide(Total Spent, Transactions)` |
| Stores Visited | Number of different points of sale where the client bought; a country's online store counts as one. | `COUNT(DISTINCT store_id)` |
| Online Spent | What the client spent online, in EUR, in the e-commerce stores (channel ECOM). | `COALESCE(SUM(amount) FILTER (WHERE channel = 'ECOM'), 0)` |
| Online Share | Part of the client's spend made online: Online Spent divided by Total Spent. | `try_divide(Online Spent, Total Spent)` |

### 1.2 Dimensions

| Dimension | Functional description | Calculation |
|---|---|---|
| Simulation | The simulation the purchase belongs to: one START of the people-stream app, identified by its UTC start time (YYYYMMDDTHHMMSSmmm). The latest simulation is the highest id; filter on it to see the current run. | `simulation_id` |
| Client | The buyer, by natural key (CL-<country>-<number>). Every client is registered in one country. | `client_id` |
| Client Country | Country where the client is registered (ISO 3166 code). | `client_country` |
| Client Region | Macro region of the client's registration country: EUROPE, AMERICAS or ASIA. | `client_region` |
| Client Type | Per purchase: Local when the client is registered in the country of the store where they bought, Visitor when registered in another country (a tourist). Online purchases are always local. | `CASE WHEN client_country = store_country THEN 'Local' ELSE 'Visitor' END` |
| Client Segment | The client's segment by what they spent in the whole simulation, in every channel: OCC (Occasional) under 600 EUR, EXP (Experiencer) 600 to under 2,000, ASP (Aspiring) 2,000 to under 5,000, POT (Potential VIC) 5,000 to under 10,000, VIC1 10,000 to under 15,000, VICSTAR 15,000 and more, ND (Not Defined) when there is no spend to classify. Fixed per client and simulation: filters on dates, stores or categories don't move a client to another segment. | `CASE WHEN client_simulation_spent IS NULL OR client_simulation_spent <= 0 THEN 'ND' WHEN client_simulation_spent < 600 THEN 'OCC' WHEN client_simulation_spent < 2000 THEN 'EXP' WHEN client_simulation_spent < 5000 THEN 'ASP' WHEN client_simulation_spent < 10000 THEN 'POT' WHEN client_simulation_spent < 15000 THEN 'VIC1' ELSE 'VICSTAR' END` |
| Client Segment Name | The client segment's name: Occasional, Experiencer, Aspiring, Potential VIC, VIC1, VICSTAR or Not Defined, for the code in Client Segment. | `CASE WHEN client_simulation_spent IS NULL OR client_simulation_spent <= 0 THEN 'Not Defined' WHEN client_simulation_spent < 600 THEN 'Occasional' WHEN client_simulation_spent < 2000 THEN 'Experiencer' WHEN client_simulation_spent < 5000 THEN 'Aspiring' WHEN client_simulation_spent < 10000 THEN 'Potential VIC' WHEN client_simulation_spent < 15000 THEN 'VIC1' ELSE 'VICSTAR' END` |
| Client Segment Rank | The client segment's position from the lowest to the highest spend, to sort segments: 0 Not Defined, 1 Occasional, 2 Experiencer, 3 Aspiring, 4 Potential VIC, 5 VIC1, 6 VICSTAR. | `CASE WHEN client_simulation_spent IS NULL OR client_simulation_spent <= 0 THEN 0 WHEN client_simulation_spent < 600 THEN 1 WHEN client_simulation_spent < 2000 THEN 2 WHEN client_simulation_spent < 5000 THEN 3 WHEN client_simulation_spent < 10000 THEN 4 WHEN client_simulation_spent < 15000 THEN 5 ELSE 6 END` |
| Store | Where the client bought, by natural key: a physical store (e.g. IT-MI-001) or a country's online store (e.g. IT-EC-001). | `store_id` |
| Store Name | Name of the point of sale where the client bought, e.g. Milan Galleria Vittorio Emanuele, or E-commerce Italy online. | `store_name` |
| Channel | Sales channel of the purchase: RETAIL (physical store), FLAGSHIP (the two flagships, Milan and New York) or ECOM (online). | `channel` |
| Store Country | Country of the point of sale where the client bought (ISO 3166 code). | `store_country` |
| Macro Region | Macro region of the point of sale where the client bought: EUROPE, AMERICAS or ASIA. | `macro_region` |
| Category | Merchandise category of the items bought: SHOES, BAGS, READY_TO_WEAR, ACCESSORIES, TRAVEL or SUNGLASSES. | `category` |
| Product Name | Name of the item bought, as in the product dimension, e.g. Shoes 007. | `product_name` |
| Date (GMT) | Calendar date of the purchase in GMT, the same timeline for every store and channel. | `CAST(transaction_timestamp_utc AS DATE)` |

## 2. Store KPIs: `workspace.test02_metric.store_metrics`

What each point of sale sells and, for the physical stores, the traffic at the door and the conversion. The source puts two silver facts on one timeline: `silver_sales_transactions` (one row per item sold, every channel) and `silver_people_counter_events` (one row per door-sensor event, physical stores only), each with its store, simulation and GMT time. So sales and traffic aggregate over the same stores, channels, regions, dates and hours, and Conversion is a KPI of its own. In the calculations below the columns are those of that source; `client_country` and `store_country` come from the client and store dimensions.

### 2.1 KPIs

| KPI | Functional description | Calculation |
|---|---|---|
| Revenue | What the point of sale sold, in EUR: the sum of the amounts of the items sold. Values are always registered in euro. | `COALESCE(SUM(amount), 0)` |
| Transactions | Number of purchases at the point of sale. A transaction is everything one buyer bought in one store visit or one online order: a basket of one or more items. | `COUNT(DISTINCT transaction_id)` |
| Items | Number of items sold at the point of sale. A transaction holds at most one item per category. | `COALESCE(SUM(quantity), 0)` |
| Average Basket | Average spend per purchase at the point of sale, in EUR: Revenue divided by Transactions. | `try_divide(Revenue, Transactions)` |
| Items per Basket | Average number of items per purchase at the point of sale: Items divided by Transactions. | `try_divide(Items, Transactions)` |
| Distinct Clients | Number of different clients who bought at the point of sale. Not additive across stores: a client who bought in two stores counts once in each, and once overall. | `COUNT(DISTINCT client_id)` |
| Visitor Revenue | Revenue in EUR from visitors: clients registered in a country other than the store's. | `COALESCE(SUM(amount) FILTER (WHERE client_country <> store_country), 0)` |
| Visitor Share | Part of the revenue from visitors: Visitor Revenue divided by Revenue. About 70% at the flagships, about 30% in the other physical stores, 0% online. | `try_divide(Visitor Revenue, Revenue)` |
| Store Transactions | Transactions in physical stores only (RETAIL and FLAGSHIP): the purchases the people counters can be compared with. The numerator of Conversion. | `COUNT(DISTINCT transaction_id) FILTER (WHERE channel <> 'ECOM')` |
| People In | People who entered the store, as counted by the sensor at the door. Physical stores only: e-commerce stores have no people counting. | `COALESCE(SUM(people_count) FILTER (WHERE event_type = 'ENTRY'), 0)` |
| People Out | People who left the store, as counted by the sensor at the door. Only people leaving can buy, so this is the denominator of Conversion. | `COALESCE(SUM(people_count) FILTER (WHERE event_type = 'EXIT'), 0)` |
| Conversion | Share of the people leaving a physical store who bought something: Store Transactions divided by People Out. Physical stores only (RETAIL and FLAGSHIP); empty for e-commerce, which has no people counting. | `try_divide(Store Transactions, People Out)` |

### 2.2 Dimensions

| Dimension | Functional description | Calculation |
|---|---|---|
| Simulation | The simulation the sales and events belong to: one START of the people-stream app, identified by its UTC start time (YYYYMMDDTHHMMSSmmm). The latest simulation is the highest id; filter on it to see the current run. | `simulation_id` |
| Store | The point of sale, by natural key: a physical store (e.g. IT-MI-001) or a country's online store (e.g. IT-EC-001). | `store_id` |
| Store Name | Name of the point of sale, e.g. Milan Galleria Vittorio Emanuele, or E-commerce Italy for an online store. | `store_name` |
| Channel | Sales channel of the point of sale: RETAIL (physical store), FLAGSHIP (the two flagships, Milan and New York) or ECOM (the country's online store, which has no people counting). | `channel` |
| City | City of the point of sale; Online for the e-commerce stores. | `city` |
| Store Country | Country of the point of sale (ISO 3166 code). | `store_country` |
| Store Country Name | Country of the point of sale, by name. | `store_country_name` |
| Macro Region | Macro region of the point of sale: EUROPE, AMERICAS or ASIA. | `macro_region` |
| Date (GMT) | Calendar date in GMT of the sale or the door event, the same timeline for every store. | `CAST(time_utc AS DATE)` |
| Hour (GMT) | Hour of the day in GMT of the sale or the door event, 0 to 23. | `HOUR(time_utc)` |
