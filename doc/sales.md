# Sales: the sales simulator

Functional reference for the sales transactions: how the people-stream app turns people leaving a store into purchases, what a transaction contains, the natural keys it references, and where it is written.

The people flow it builds on is in [`people_stream.md`](people_stream.md); stores in [`dataset.md`](dataset.md); clients in [`client.md`](client.md); products in [`product.md`](product.md); schemas and keys in [`warehouse.md`](warehouse.md).

## 1. Purpose and boundaries

| | |
|---|---|
| **What it does** | A second simulator on the people stream's timeline: for each `EXIT` event, it decides who of the people leaving bought something, and inserts one sales transaction per purchase into `workspace.test02_streaming.simulated_sales_source` |
| **E-commerce** | The 13 e-commerce stores (channel `ECOM`) have no people stream: their online sales are generated per batch, on top of the stores' sales, sized as a share of each country's sales value; see §12 |
| **Where it runs** | Inside the people-stream app (`apps/people_stream/app/sales.py`), in the same batches as the people events: START, STOP and the 48-hour limit apply to both |
| **Loaded by** | The pipeline (`src/pipelines/03_sales.py`): bronze, silver and quarantine sales tables, with the foreign keys of §2; see §10. The sales dashboard reads silver ([`sales_dashboard.md`](sales_dashboard.md)) |

```
 people stream (one batch)                        sales simulator
 ENTRY / EXIT events ──EXIT, people_count N──▶  per person, per category:
        │                                         buys with PURCHASE_PROB[region][category]
        ▼                                                │ one transaction per purchase
 simulated_event_source                                  ▼
                                               simulated_sales_source
                                               (store_id, client_id, product_id, …)
```

## 2. Data model

All keys are **natural keys**; there are no surrogate keys. Every reference uses the referenced table's natural primary key. The dimensions are in `test02_warehouse`, the sales source in `test02_streaming` ([`warehouse.md`](warehouse.md)).

| Table | Grain | Primary key | References |
|---|---|---|---|
| `dim_store` | One row per store | `store_id` | |
| `dim_client` | One registered client | `client_id` | (registered in a `dim_store` country) |
| `dim_product` | One product (SKU) | `product_id` | |
| `simulated_sales_source` | One message = one transaction | `source_topic` + `source_partition` + `source_offset` (message identity) | Payload: `store_id` → `dim_store`, `client_id` → `dim_client`, `product_id` → `dim_product`, `exit_event_id` → the people event's `event_id` |
| `silver_sales_transactions` | One valid transaction | `transaction_id` | `FOREIGN KEY` `store_id` → `dim_store`, `client_id` → `dim_client`, `product_id` → `dim_product` (§10) |

The source table holds raw JSON, like `simulated_event_source`, so the references inside the payload are not constraints there. `silver_sales_transactions` declares them as Unity Catalog `FOREIGN KEY` constraints on the natural keys (informational, like the `store_id` foreign key of `silver_people_counter_events`); `exit_event_id` is kept as a plain column. See §10.

## 3. Purchase probabilities (PURCHASE_PROB)

Each person leaving a store may buy in each of the six merchandise categories, independently. The probability is a percent per **macro region** and **category**:

| Category | Default, every region |
|---|---|
| `SHOES` | 5% |
| `BAGS` | 2% |
| `READY_TO_WEAR` | 6% |
| `ACCESSORIES` | 3% |
| `TRAVEL` | 2% |
| `SUNGLASSES` | 2% |

- **Defaults:** `purchase_prob.default.<REGION>.<CATEGORY>` in `apps/people_stream/app/shop_config.yml`, with range `purchase_prob.min`–`max` (0–100%) and `step` (1%). See `people_stream.md` §2.
- **Sliders:** on the **Simulator** tab, under each region's vertical N_AVG_PEOPLE slider, six horizontal sliders, one per category, 0–100%. A change applies from the next batch, also while running; **Reset to defaults** restores them with the N_AVG_PEOPLE sliders.
- **Per person, per category:** a person can buy in several categories during one visit; at most one item per category. Everything one person buys in a visit is **one transaction** (a basket), with one line per item (§4).

With the defaults, a person leaving buys on average 0.20 items (the sum of the six probabilities); 18.5% of them buy something (1 − 0.95 × 0.98 × 0.94 × 0.97 × 0.98 × 0.98), so a transaction holds **≈ 1.08 items** on average.

## 4. From an EXIT to transactions

For every `EXIT` event of a batch, with `people_count = N`, in a store of region R:

1. **A basket per person:** for each of the N people leaving, each category C is bought with probability `PURCHASE_PROB[R][C] / 100`, independently: for example shoes and sunglasses, or nothing.
2. **One transaction per buyer:** a person with a non-empty basket makes **one transaction**, with **one line per item**, in category order (shoes, bags, ready-to-wear, accessories, travel, sunglasses):
   - **Client:** a local client (registered in the store's country) with probability `clients.local_share` = **70%**, otherwise a visitor registered in another country; at the two flagships the shares are inverted, **30% local, 70% visitors** (`client.md` §4). One client for the whole transaction.
   - **Products:** per line, one product of the line's category, drawn uniformly from `dim_product` (`product.md` §4).
   - **Quantity and amount:** per line, 1 unit at the product's `list_price`, always in EUR (§11).
   - **Time:** the exit's local `event_timestamp`, the same for every line.
3. **Transaction ids in time order:** the batch's transactions, store and e-commerce together (§12), are sorted by their GMT time and numbered on from the previous batch (§5).

Entries never trigger sales; only people leaving buy. Stores closed or not yet reached by the timeline produce no exits and therefore no sales. The closing `EXIT` at 20:00 (everyone still inside) produces sales like any other exit.

**Cockpit:** the switches under START/STOP turn the sales off, or only the e-commerce sales, from the next batch (`people_stream.md` §3). With sales off the people stream goes on, without any transaction.

## 5. Transaction shape

Payload (`raw_event`): one JSON object per **line**, that is per item. A transaction of two items is two messages with the same `transaction_id`, for example shoes and sunglasses:

```json
{"transaction_id":"TX-20261114T193627123-0000004711","line_number":1,"line_count":2,
 "simulation_id":"20261114T193627123","exit_event_id":"sim-20261114T193627123-0-0000001234",
 "store_id":"IT-MI-001","client_id":"CL-IT-0004711","product_id":"SH-0007","category":"SHOES",
 "quantity":1,"unit_price":725.0,"amount":725.0,"currency":"EUR",
 "transaction_timestamp":"2026-11-14T15:31:12.408"}
{"transaction_id":"TX-20261114T193627123-0000004711","line_number":2,"line_count":2,
 "simulation_id":"20261114T193627123","exit_event_id":"sim-20261114T193627123-0-0000001234",
 "store_id":"IT-MI-001","client_id":"CL-IT-0004711","product_id":"SG-0003","category":"SUNGLASSES",
 "quantity":1,"unit_price":286.0,"amount":286.0,"currency":"EUR",
 "transaction_timestamp":"2026-11-14T15:31:12.408"}
```

| Field | Rule |
|---|---|
| `transaction_id` | `TX-<simulation id>-<sequence, 10 digits>`: one per transaction (one buyer, one basket), in every channel. **Rankable:** within a simulation the sequence is given in GMT purchase-time order, stores and e-commerce together, so a higher id is never an earlier purchase; across simulations the simulation id (the START time) orders them. Unique across simulations |
| `line_number` | 1 to `line_count`, one item per line. With `transaction_id`, the natural key of a line |
| `line_count` | The lines (items) of the transaction, the same on every line |
| `simulation_id` | The simulation's id, the same as in its people events (`people_stream.md` §6): sortable, the latest simulation is the highest |
| `exit_event_id` | `event_id` of the `EXIT` that triggered it; several transactions can share one exit, and every line of a transaction has the same one. `null` for an e-commerce sale: online there's no visit (§12) |
| `store_id` | The exit's store → `dim_store.store_id` |
| `client_id` | → `dim_client.client_id`, the same on every line; from the store's country for 70% of transactions (30% at flagships), from another country otherwise |
| `product_id` | → `dim_product.product_id`; of `category` |
| `category` | The product's category; at most one line per category in a transaction |
| `quantity` | 1 |
| `unit_price`, `amount` | The product's `list_price`; `amount = quantity × unit_price` |
| `currency` | `EUR`, always: transaction values are registered in euro in every country (§11) |
| `transaction_timestamp` | Store local time, no time zone (as the people events' `event_timestamp`); the same on every line |

Envelope columns:

| Column | Value |
|---|---|
| `source_topic` | `retail-sales-app` |
| `source_partition` | One per macro region, as the people stream: `0` EUROPE, `1` AMERICAS, `2` ASIA |
| `source_offset` | Consecutive per partition, one per line; on START it continues after the highest offset already in the table for this topic and partition |
| `source_timestamp` | The batch's simulated UTC time, as for the people events |

## 6. Writing

- **Empty at START:** every START empties `simulated_sales_source` (and the people source) before the run, so the table holds the current run only. See `people_stream.md` §7.
- **Order:** in every batch the app writes the people events first, then the sales transactions they generated.
- **Statement:** insert-only `MERGE` on the message identity (`source_topic`, `source_partition`, `source_offset`), in chunks of at most 10,000 rows, by the app's background writer (`people_stream.md` §7). A retried batch can't insert a row twice; no row is ever updated or deleted, so the table can be read as a stream.
- **Failure:** a failed write stops the run with state `FAILED`, as for the people events.

## 7. Volumes

With N_AVG_PEOPLE 3000 and the default probabilities, about 600,000 people leave per simulated day, so:

| | Per simulated day (240 s) | Per run (48 h, 480 s) |
|---|---|---|
| Store transactions (`RETAIL`, `FLAGSHIP`) | ≈ 110,000, with ≈ 119,000 items (1.08 per transaction) | ≈ 220,000 |
| Store amount | ≈ 120 million EUR (≈ 1,097 EUR per transaction, ≈ 1,012 EUR per item, §11.3) | ≈ 240 million EUR |
| E-commerce transactions (`ECOM`, §12) | ≈ 16,800, with ≈ 18,100 items | ≈ 33,600 |
| E-commerce amount | ≈ 16.5 million EUR (≈ 984 EUR per transaction, ≈ 910 EUR per item: 10% below the stores) | ≈ 33 million EUR |
| **All channels** | ≈ 126,000 transactions, ≈ 137,000 items, ≈ 137 million EUR, of which e-commerce ≈ 12% | ≈ 253,000 transactions, ≈ 273 million EUR |

Measured over two simulated days with the shipped parameters. Lines (items) follow the exits, so they peak when a region's stores close at 20:00: a batch can then hold up to about 9,000 lines (measured peak 8,722 before baskets), still one statement. Batches are generated every 5 seconds whatever the warehouse is doing; if writing falls behind, batches wait in the writer's queue (`people_stream.md` §7).

## 8. On screen

- **Simulator tab:** the 18 horizontal PURCHASE_PROB sliders (§3); the **Parameters** panel shows their defaults and range.
- **Cockpit** (under START/STOP): the **Sales transactions** and **E-commerce sales** switches (§4, `people_stream.md` §3).
- **Counters tab:** **Sales transactions by region and category**: items per category, transactions, items per transaction, amount in EUR, conversion (transactions per person out), local clients' share; then the e-commerce transactions, amount and share.

## 9. Setup and permissions

| Step | How |
|---|---|
| Tables | In the pipeline bundle, run `src/sql/08_…` to `11_…` (clients and products), `12_…` (sales source), then check with `13_…`. See `client.md` §5 and `product.md` §5 |
| Granted to the app | `SELECT` on `test02_warehouse.dim_client` and `dim_product`; `SELECT` and `MODIFY` on `simulated_sales_source` (`apps/people_stream/resources/people_stream.app.yml`). The tables must exist before the app bundle is deployed |
| App settings | `CLIENT_TABLE`, `PRODUCT_TABLE`, `SALES_TABLE` in `apps/people_stream/app/app.yaml` |

## 10. Silver sales

The pipeline's `src/pipelines/03_sales.py` loads the sales source the same way `01_bronze.py` and `02_silver.py` load the people events:

| Table | Content |
|---|---|
| `bronze_sales_transactions` | The source rows as they are, plus `ingestion_timestamp`. Reads the source with `skipChangeCommits`, so the deletes of an app START don't stop the stream |
| `silver_sales_transactions` | Parsed, typed and valid transactions: the §5 fields, `unit_price` and `amount` as `DECIMAL(12,2)`, `transaction_timestamp` as `TIMESTAMP_NTZ` (store local time) plus the raw string, the store's time zone, and `transaction_timestamp_utc`, the same moment in GMT (§11.4). Primary key (`transaction_id`, `line_number`): one row per line, so a transaction is all the rows with its id; foreign keys `store_id` → `dim_store`, `client_id` → `dim_client`, `product_id` → `dim_product` (informational, on the natural keys in `test02_warehouse`). Read by the sales dashboard ([`sales_dashboard.md`](sales_dashboard.md)) |
| `quarantine_sales_transactions` | Invalid transactions, with `rejection_reason`, `record_status` = `OPEN` and `quarantine_timestamp` |

A transaction goes to silver if it passes every rule, and to quarantine otherwise; `rejection_reason` lists every failed rule, separated by `|`. The simulator's transactions pass them all.

| Code | Rule |
|---|---|
| `INVALID_JSON` | The payload isn't valid JSON for the transaction schema |
| `MISSING_TRANSACTION_ID` | `transaction_id` is missing or empty |
| `INVALID_LINE_NUMBER` | `line_number` or `line_count` is missing, or `line_number` is below 1 or above `line_count` |
| `INVALID_TRANSACTION_TIMESTAMP` | `transaction_timestamp` is missing or not a valid timestamp |
| `INVALID_QUANTITY` | `quantity` is missing, zero or negative |
| `INVALID_AMOUNT` | `unit_price` is missing, zero or negative, or `amount` isn't `quantity × unit_price` (to the cent) |
| `INVALID_CURRENCY` | `currency` isn't `EUR` (after trimming and upper-casing) |
| `UNKNOWN_STORE` | `store_id` is missing or isn't in `dim_store` |
| `UNKNOWN_CLIENT` | `client_id` is missing or isn't in `dim_client` |
| `UNKNOWN_PRODUCT` | `product_id` is missing or isn't in `dim_product` |
| `CATEGORY_MISMATCH` | `category` (after trimming and upper-casing) isn't the product's category in `dim_product` |

The pre-flight check (`00_check_tables.py`) also requires `simulated_sales_source`, and a non-empty `dim_client` and `dim_product`: run `src/sql/08_…` to `12_…` before the pipeline. Silver and quarantine carry the transaction's `simulation_id`, and silver is clustered by it. The pipeline keeps running through an app START, so silver holds every simulation; the view `current_sales_transactions` keeps only the latest (`warehouse.md` §6). A new silver column, such as `transaction_timestamp_utc` or `simulation_id`, needs one full refresh before it appears.

## 11. Purchase model: products, categories and price points

The brand is a **luxury house selling outdoor and leather garments, leather goods and accessories**. Its price points put the **average transaction at about 1,000 EUR**. This section ties together how a purchase is modelled; the steps are in §3 and §4, and the products in [`product.md`](product.md).

### 11.1 From a visitor to a transaction

| Question | Model |
|---|---|
| **Who buys?** | In the physical stores (`RETAIL`, `FLAGSHIP`), only people **leaving** a store (`EXIT` events); online, the e-commerce stores' orders (§12). Each one buys in each of the six merchandise categories independently, with probability `PURCHASE_PROB[region][category]` (§3). With the defaults, a person leaving buys 0.20 items on average |
| **What do they buy?** | In a category, **one product**, drawn uniformly from the 20 active products of that category in `dim_product` |
| **How many?** | **1 unit per category**, at most. Everything one buyer buys in a visit is **one transaction** (a basket) with one line per item: shoes, a garment and sunglasses are one transaction of three lines. On average a transaction holds ≈ 1.08 items |
| **At what price?** | In the stores, the product's **list price** (`dim_product.list_price`): no discounts, no promotions, the **same price in every country and region**. Online, **90% of list price** (`ecommerce.price_pct`), so the average e-commerce transaction is 10% lower (§12) |
| **In what currency?** | **Always EUR.** Transaction values are registered in euro whatever the store's country: there's no local currency and no exchange rate. `dim_product.currency` is `EUR`, every transaction has `currency` = `EUR`, and silver rejects any other currency (`INVALID_CURRENCY`, §10) |
| **When?** | At the exit's store-local time (`transaction_timestamp`); silver adds the same moment in GMT (`transaction_timestamp_utc`, §11.4) |
| **Who is the client?** | A local client 70% of the time, a visitor from another country 30%; inverted at the two flagships (§4, [`client.md`](client.md)) |

### 11.2 Price lists

`list_price = base + n × step` for product number `n` = 1 to 20 (`src/sql/11_populate_dim_product.sql`):

| Category | What it stands for | Base | Step | Price range (EUR) | Average price | Share of transactions | Share of value |
|---|---|---|---|---|---|---|---|
| `SHOES` | Leather shoes and outdoor boots | 550 | 25 | 575 – 1,050 | 812.50 | 25% | 20.1% |
| `BAGS` | Leather bags | 1,300 | 80 | 1,380 – 2,900 | 2,140 | 10% | 21.1% |
| `READY_TO_WEAR` | Outdoor and leather garments: jackets, coats, knitwear | 550 | 50 | 600 – 1,550 | 1,075 | 30% | 31.9% |
| `ACCESSORIES` | Small leather goods, belts, scarves | 200 | 20 | 220 – 600 | 410 | 15% | 6.1% |
| `TRAVEL` | Leather luggage and travel goods | 1,000 | 70 | 1,070 – 2,400 | 1,735 | 10% | 17.1% |
| `SUNGLASSES` | Eyewear | 250 | 12 | 262 – 490 | 376 | 10% | 3.7% |

The share of transactions is each category's default probability over their sum (5, 2, 6, 3, 2, 2 out of 20); the share of value weights it by the average price.

### 11.3 Average item and average transaction

The **average item** is the average list price, weighted by how often each category is bought:

```
average item = Σ PURCHASE_PROB[c] × average price[c] / Σ PURCHASE_PROB[c]
             = (5×812.50 + 2×2,140 + 6×1,075 + 3×410 + 2×1,735 + 2×376) / 20
             ≈ 1,012 EUR
```

A **transaction** is a basket of ≈ 1.08 items (§3), so the **average transaction** is ≈ 1.08 × 1,012 ≈ **1,097 EUR** in the stores (measured 1,097), and ≈ 984 EUR online, where every item costs 10% less (§12).

- **Per visitor:** a person leaving spends 0.20 × 1,012 ≈ 202 EUR on average.
- **Sliders move it:** raising the probability of bags or travel raises the averages; raising accessories or sunglasses lowers them. Raising every probability also makes baskets bigger. Prices themselves don't change at run time.
- **Previous models:** before the price-list change an item averaged about 720 EUR; before baskets, a transaction was one item, so the average transaction was the average item, ≈ 1,012 EUR. To bring the average transaction back to about 1,000 EUR, lower the price lists by about 9% in `11_…`. `11_…` **reprices existing products** (`WHEN MATCHED … UPDATE SET list_price`), so running it again is enough; the people-stream app reads the prices at START.

### 11.4 Local time and GMT

A sale has two times, for the same moment:

| Column | Type | Meaning |
|---|---|---|
| `transaction_timestamp` | `TIMESTAMP_NTZ` | The store's **local** time, as the sensor and the till see it (e.g. 15:31 in Milan) |
| `transaction_timestamp_utc` | `TIMESTAMP_NTZ` | The same moment in **GMT (UTC)** (e.g. 14:31 in winter), added in silver by `03_sales.py` with `convert_timezone(store_timezone_id, 'UTC', transaction_timestamp)`. Daylight saving time is applied per store time zone |

Both are wall clocks without a time zone (`TIMESTAMP_NTZ`), so they read the same in any session time zone. Local time answers "at what hour of the shop's day?"; GMT puts every store on **one timeline**, as the sales dashboard does ([`sales_dashboard.md`](sales_dashboard.md)).

## 12. E-commerce sales

Every country has one e-commerce store, channel `ECOM` (`dataset.md` §2.6). It sells online, all day, with no people counting: its sales don't come from people leaving, they come **on top of** the stores' sales.

### 12.1 Parameters

In the app's `shop_config.yml`, section `ecommerce` (`people_stream.md` §2):

| Key | Shipped value | Meaning |
|---|---|---|
| `share_pct` | 10 | E-commerce sales as a percent of a country's **total** sales value (stores + e-commerce) |
| `high_share_pct` | 15 | The same, in the countries below |
| `high_share_countries` | `US, CN` | United States and China |
| `price_pct` | 90 | Online price, percent of list price: the average e-commerce transaction is **10% lower** than in the stores |

### 12.2 How the online orders are generated

For each batch (30 simulated minutes) and each e-commerce store:

1. **The country's store sales:** the expected store items in a day are the country's daily visitors (physical stores × N_AVG_PEOPLE of the region, flagships weighted by their traffic) × `PURCHASE_PROB[region][category]`.
2. **Sized to the share:** e-commerce must be `share` percent of the total value, so its value is `share / (100 − share)` of the stores' value (10/90 = 11.1%, or 15/85 = 17.6%). At 90% of the price, that takes `share / (100 − share) / 0.90` online transactions per store transaction: 12.3%, or 19.6% in the US and China.
3. **Through the online day:** the day's online orders are spread over the store's 24 local hours along a fixed curve: quiet at night (about a tenth of the average at 03:00–04:00), rising through the day, peaking after dinner (twice the average at 20:00–21:00). The batch gets the share of its local hour.
4. **In baskets:** online orders are baskets like the stores' (each category with its PURCHASE_PROB, at least one item), ≈ 1.08 items each, so the expected orders are the expected items / items per basket. The number of orders in the batch is drawn around that (a Poisson count), each at a random moment of the batch.

Each order is one transaction with one line per item, like a store sale (§5), and gets its transaction id in time order with the stores' transactions of the batch, except:

| Field | E-commerce value |
|---|---|
| `store_id` | The country's e-commerce store, e.g. `IT-EC-001` |
| `exit_event_id` | `null`: no visit, no `EXIT` event |
| `client_id` | A client registered in the country, drawn uniformly (online buyers are local) |
| `unit_price`, `amount` | `price_pct` of the product's list price, rounded to the cent |
| `transaction_timestamp` | The order's local time in the e-commerce store's time zone (the country's main one) |
| `source_partition` | The country's macro region, like the stores; offsets continue the same sequence |

The PURCHASE_PROB sliders and the N_AVG_PEOPLE sliders move the e-commerce sales too, so the share stays at its target whatever the sliders say. E-commerce sales pass the same silver rules (§10) and reach the same silver table; the dashboard tells them apart by the store's channel (`sales_dashboard.md`).

### 12.3 What the share means in practice

The share is of the sales **value**, measured over whole days. Within a day it varies: the online curve and the stores' opening hours don't match, so in the evening, when the stores have closed, e-commerce is most of the sales; at night it's all of them. Over a simulated day the tests measure 10% ± 1 point in the 10% countries together, and 15% ± 1 point in the US and China together.
