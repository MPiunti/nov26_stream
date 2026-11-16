# KPI glossary

The functional definition of every KPI and every dimension the KPIs can be sliced by. Each description below is, word for word, the `comment` of the measure or dimension in its Unity Catalog metric view, so dashboard users, AI/BI and Genie see exactly these definitions. Why metric views, the design rules and the KPI choices are in [`kpi_metrics.md`](kpi_metrics.md).

**Keeping it true:** the definitions live in `src/metrics/*.sql`. Change a description there and here together: a test fails when a description differs, or when a KPI or dimension is missing on either side.

**Reading the calculations:** `source` is the silver table of the metric view; `dim_store`, `dim_client` and `dim_product` are the dimensions joined on their natural keys. A KPI named in a calculation (e.g. `Revenue / Transactions`) is that KPI, recomputed for the same slice, so ratios stay correct for any client, store, channel, country or date.

## 1. Sales KPIs: `workspace.test02_metric.sales_metrics`

Over `silver_sales_transactions`: one row per item sold, in every channel (retail, flagship, e-commerce). A transaction is a basket of items ([`sales.md`](sales.md) §5).

### 1.1 KPIs

| KPI | Functional description | Calculation |
|---|---|---|
| Revenue | What was sold, in EUR: the sum of the items' amounts, in every channel. By client it is the client's total spent; by store, the store's revenue. Values are always registered in euro. | `SUM(source.amount)` |
| Transactions | Number of purchases. A transaction is everything one buyer bought in one store visit or one online order: a basket of one or more items. | `COUNT(DISTINCT source.transaction_id)` |
| Items | Number of items sold. A transaction holds at most one item per category. | `SUM(source.quantity)` |
| Average Basket | Average spend per purchase, in EUR: Revenue divided by Transactions. | `Revenue / Transactions` |
| Items per Basket | Average number of items per purchase: Items divided by Transactions. | `Items / Transactions` |
| Stores Visited | Number of different points of sale where purchases were made; a country's online store counts as one. By client: the stores the client bought in. | `COUNT(DISTINCT source.store_id)` |
| Distinct Clients | Number of different clients who bought. Not additive across stores: a client who bought in two stores counts once in each, and once overall. | `COUNT(DISTINCT source.client_id)` |
| Online Revenue | Revenue in EUR made online, in the e-commerce stores (channel ECOM). | `COALESCE(SUM(source.amount) FILTER (WHERE dim_store.channel = 'ECOM'), 0)` |
| Online Share | Part of the revenue made online: Online Revenue divided by Revenue. By client: the share of the client's total spent made online. | `Online Revenue / Revenue` |
| Visitor Revenue | Revenue in EUR from visitors: clients registered in a country other than the store's. | `COALESCE(SUM(source.amount) FILTER (WHERE dim_client.country_code <> dim_store.country_code), 0)` |
| Visitor Share | Part of the revenue from visitors: Visitor Revenue divided by Revenue. About 70% at the flagships, about 30% in the other physical stores, 0% online. | `Visitor Revenue / Revenue` |
| Store Transactions | Transactions in physical stores only (RETAIL and FLAGSHIP): the purchases the people counters can be compared with. The numerator of Conversion. | `COUNT(DISTINCT source.transaction_id) FILTER (WHERE dim_store.channel <> 'ECOM')` |

**Client KPIs** are these KPIs by `Client`: **Revenue** is the client's *total spent*, plus Transactions, Items, Average Basket, Stores Visited and Online Share. **Store KPIs** are the same by `Store`: **Revenue**, Transactions, Average Basket, Items per Basket, Distinct Clients, Visitor Share, and Conversion (§3).

### 1.2 Dimensions

| Dimension | Functional description | Calculation |
|---|---|---|
| Simulation | The simulation the sale belongs to: one START of the people-stream app, identified by its UTC start time (YYYYMMDDTHHMMSSmmm). The latest simulation is the highest id; filter on it to see the current run. | `source.simulation_id` |
| Client | The buyer, by natural key (CL-<country>-<number>). Every client is registered in one country. | `source.client_id` |
| Client Country | Country where the buyer is registered (ISO 3166 code). | `dim_client.country_code` |
| Client Type | Local when the buyer is registered in the store's country, Visitor when registered in another country (a tourist). Online buyers are always local. | `CASE WHEN dim_client.country_code = dim_store.country_code THEN 'Local' ELSE 'Visitor' END` |
| Store | The point of sale, by natural key: a physical store (e.g. IT-MI-001) or a country's online store (e.g. IT-EC-001). | `source.store_id` |
| Store Name | Name of the point of sale, e.g. Milan Galleria Vittorio Emanuele, or E-commerce Italy for an online store. | `dim_store.store_name` |
| Channel | Sales channel of the point of sale: RETAIL (physical store), FLAGSHIP (the two flagships, Milan and New York) or ECOM (the country's online store). | `dim_store.channel` |
| Store Country | Country of the point of sale (ISO 3166 code). | `dim_store.country_code` |
| Store Country Name | Country of the point of sale, by name. | `dim_store.country_name` |
| City | City of the point of sale; Online for the e-commerce stores. | `dim_store.city` |
| Macro Region | Macro region of the point of sale: EUROPE, AMERICAS or ASIA. | `dim_store.macro_region` |
| Category | Merchandise category of the item: SHOES, BAGS, READY_TO_WEAR, ACCESSORIES, TRAVEL or SUNGLASSES. | `source.category` |
| Product | The item sold, by natural key (e.g. SH-0007). | `source.product_id` |
| Product Name | Name of the item sold, as in the product dimension, e.g. Shoes 007. | `dim_product.product_name` |
| Date (GMT) | Calendar date of the sale in GMT, the same timeline for every store and channel. | `CAST(source.transaction_timestamp_utc AS DATE)` |
| Hour (GMT) | Hour of the day of the sale in GMT, 0 to 23. | `HOUR(source.transaction_timestamp_utc)` |
| Local Date | Calendar date of the sale in the store's local time. | `CAST(source.transaction_timestamp AS DATE)` |

## 2. Store traffic: `workspace.test02_metric.people_metrics`

Over `silver_people_counter_events`: the people counters at the doors of the physical stores (RETAIL and FLAGSHIP). E-commerce stores have no people counting.

### 2.1 KPIs

| KPI | Functional description | Calculation |
|---|---|---|
| People In | People who entered the store, as counted by the sensor at the door. | `COALESCE(SUM(source.people_count) FILTER (WHERE source.event_type = 'ENTRY'), 0)` |
| People Out | People who left the store. Only people leaving can buy, so this is the denominator of Conversion. | `COALESCE(SUM(source.people_count) FILTER (WHERE source.event_type = 'EXIT'), 0)` |

### 2.2 Dimensions

| Dimension | Functional description | Calculation |
|---|---|---|
| Simulation | The simulation the event belongs to: one START of the people-stream app, identified by its UTC start time (YYYYMMDDTHHMMSSmmm). The latest simulation is the highest id; filter on it to see the current run. | `source.simulation_id` |
| Store | The physical store whose people counter registered the event, by natural key (e.g. IT-MI-001). | `source.store_id` |
| Store Name | Name of the store, e.g. Milan Galleria Vittorio Emanuele. | `dim_store.store_name` |
| Channel | Sales channel of the store: RETAIL or FLAGSHIP. E-commerce stores (ECOM) have no people counting, so they never appear here. | `dim_store.channel` |
| Store Country | Country of the store (ISO 3166 code). | `dim_store.country_code` |
| Macro Region | Macro region of the store: EUROPE, AMERICAS or ASIA. | `dim_store.macro_region` |
| Date (GMT) | Calendar date of the event in GMT, the same timeline as the sales. | `CAST(convert_timezone(source.store_timezone_id, 'UTC', source.event_timestamp) AS DATE)` |
| Hour (GMT) | Hour of the day of the event in GMT, 0 to 23. | `HOUR(convert_timezone(source.store_timezone_id, 'UTC', source.event_timestamp))` |

## 3. KPIs combining the two metric views

| KPI | Functional description | Calculation |
|---|---|---|
| Conversion | Share of the people leaving a physical store who bought something: buyers per person out. Physical stores only (RETAIL and FLAGSHIP); e-commerce has no people counting. | `Store Transactions` (sales_metrics) / `People Out` (people_metrics), for the same stores, dates and hours |

Sales and people counts are two facts at different grains, so each lives in its own metric view and the consumer (the sales dashboard) divides the two for the same slice ([`kpi_metrics.md`](kpi_metrics.md) §6).
