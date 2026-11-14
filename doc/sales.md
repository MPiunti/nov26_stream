# Sales: the sales simulator

Functional reference for the sales transactions: how the people-stream app turns people leaving a store into purchases, what a transaction contains, the natural keys it references, and where it is written.

The people flow it builds on is in [`people_stream.md`](people_stream.md); stores in [`dataset.md`](dataset.md); clients in [`client.md`](client.md); products in [`product.md`](product.md); schemas and keys in [`warehouse.md`](warehouse.md).

## 1. Purpose and boundaries

| | |
|---|---|
| **What it does** | A second simulator on the people stream's timeline: for each `EXIT` event, it decides who of the people leaving bought something, and inserts one sales transaction per purchase into `workspace.test02_streaming.simulated_sales_source` |
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
- **Per person, per category:** a person can buy in several categories during one visit; at most one item per category.

With the defaults, a person leaving buys on average 0.20 items (the sum of the six probabilities).

## 4. From an EXIT to transactions

For every `EXIT` event of a batch, with `people_count = N`, in a store of region R:

1. **Buyers per category:** for each category C, the number of buyers is drawn from a binomial distribution: N people, each buying with probability `PURCHASE_PROB[R][C] / 100`.
2. **One transaction per buyer:** for each buyer:
   - **Client:** a local client (registered in the store's country) with probability `clients.local_share` = **70%**, otherwise a visitor registered in another country; at the two flagships the shares are inverted, **30% local, 70% visitors** (`client.md` §4).
   - **Product:** one product of category C, drawn uniformly from `dim_product` (`product.md` §4).
   - **Quantity and amount:** 1 unit at the product's `list_price`, always in EUR (§11).
   - **Time:** the exit's local `event_timestamp`.

Entries never trigger sales; only people leaving buy. Stores closed or not yet reached by the timeline produce no exits and therefore no sales. The closing `EXIT` at 20:00 (everyone still inside) produces sales like any other exit.

## 5. Transaction shape

Payload (`raw_event`), one JSON object per transaction:

```json
{"transaction_id":"tx-20261114T193627123-0-0000000042","simulation_id":"20261114T193627123",
 "exit_event_id":"sim-20261114T193627123-0-0000001234",
 "store_id":"IT-MI-001","client_id":"CL-IT-0004711","product_id":"SH-0007","category":"SHOES",
 "quantity":1,"unit_price":725.0,"amount":725.0,"currency":"EUR",
 "transaction_timestamp":"2026-11-14T15:31:12.408"}
```

| Field | Rule |
|---|---|
| `transaction_id` | `tx-<simulation id>-<partition>-<offset, 10 digits>`; unique across simulations. The natural key of a transaction |
| `simulation_id` | The simulation's id, the same as in its people events (`people_stream.md` §6): sortable, the latest simulation is the highest |
| `exit_event_id` | `event_id` of the `EXIT` that triggered it; several transactions can share one exit |
| `store_id` | The exit's store → `dim_store.store_id` |
| `client_id` | → `dim_client.client_id`; from the store's country for 70% of transactions (30% at flagships), from another country otherwise |
| `product_id` | → `dim_product.product_id`; of `category` |
| `category` | The product's category |
| `quantity` | 1 |
| `unit_price`, `amount` | The product's `list_price`; `amount = quantity × unit_price` |
| `currency` | `EUR`, always: transaction values are registered in euro in every country (§11) |
| `transaction_timestamp` | Store local time, no time zone (as the people events' `event_timestamp`) |

Envelope columns:

| Column | Value |
|---|---|
| `source_topic` | `retail-sales-app` |
| `source_partition` | One per macro region, as the people stream: `0` EUROPE, `1` AMERICAS, `2` ASIA |
| `source_offset` | Consecutive per partition; on START it continues after the highest offset already in the table for this topic and partition |
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
| Transactions | ≈ 120,000 | ≈ 240,000 |
| Amount | ≈ 121 million EUR (≈ 1,012 EUR average per transaction, §11.3) | ≈ 243 million EUR |

Transactions follow the exits, so they peak when a region's stores close at 20:00: a batch can then hold up to about 9,000 transactions (measured peak 8,722), still one statement. Batches are generated every 5 seconds whatever the warehouse is doing; if writing falls behind, batches wait in the writer's queue (`people_stream.md` §7).

## 8. On screen

- **Simulator tab:** the 18 horizontal PURCHASE_PROB sliders (§3); the **Parameters** panel shows their defaults and range.
- **Counters tab:** **Sales transactions by region and category**: transactions per category, total transactions, amount in EUR, local clients' share, and transactions per person out.

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
| `silver_sales_transactions` | Parsed, typed and valid transactions: the §5 fields, `unit_price` and `amount` as `DECIMAL(12,2)`, `transaction_timestamp` as `TIMESTAMP_NTZ` (store local time) plus the raw string, the store's time zone, and `transaction_timestamp_utc`, the same moment in GMT (§11.4). Primary key `transaction_id`; foreign keys `store_id` → `dim_store`, `client_id` → `dim_client`, `product_id` → `dim_product` (informational, on the natural keys in `test02_warehouse`). Read by the sales dashboard ([`sales_dashboard.md`](sales_dashboard.md)) |
| `quarantine_sales_transactions` | Invalid transactions, with `rejection_reason`, `record_status` = `OPEN` and `quarantine_timestamp` |

A transaction goes to silver if it passes every rule, and to quarantine otherwise; `rejection_reason` lists every failed rule, separated by `|`. The simulator's transactions pass them all.

| Code | Rule |
|---|---|
| `INVALID_JSON` | The payload isn't valid JSON for the transaction schema |
| `MISSING_TRANSACTION_ID` | `transaction_id` is missing or empty |
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
| **Who buys?** | Only people **leaving** a store (`EXIT` events). Each one buys in each of the six merchandise categories independently, with probability `PURCHASE_PROB[region][category]` (§3). With the defaults, a person leaving buys 0.20 items on average |
| **What do they buy?** | In a category, **one product**, drawn uniformly from the 20 active products of that category in `dim_product` |
| **How many?** | **1 unit**: one transaction = one item. A person buying in two categories makes two transactions |
| **At what price?** | The product's **list price** (`dim_product.list_price`): no discounts, no promotions, the **same price in every country and region** |
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

### 11.3 Average transaction

Every transaction is one item, so the average transaction is the average item price, weighted by how often each category is bought:

```
average transaction = Σ PURCHASE_PROB[c] × average price[c] / Σ PURCHASE_PROB[c]
                    = (5×812.50 + 2×2,140 + 6×1,075 + 3×410 + 2×1,735 + 2×376) / 20
                    ≈ 1,012 EUR
```

- **Per visitor:** a person leaving spends 0.20 × 1,012 ≈ 202 EUR on average.
- **Sliders move it:** raising the probability of bags or travel raises the average transaction; raising accessories or sunglasses lowers it. Prices themselves don't change at run time.
- **Previous price lists:** until this change the average transaction was about 720 EUR. `11_…` now **reprices existing products** (`WHEN MATCHED … UPDATE SET list_price`), so running it again is enough. The people-stream app reads the prices at START, so the next START sells at the new prices; transactions already in silver keep the price they were sold at.

### 11.4 Local time and GMT

A sale has two times, for the same moment:

| Column | Type | Meaning |
|---|---|---|
| `transaction_timestamp` | `TIMESTAMP_NTZ` | The store's **local** time, as the sensor and the till see it (e.g. 15:31 in Milan) |
| `transaction_timestamp_utc` | `TIMESTAMP_NTZ` | The same moment in **GMT (UTC)** (e.g. 14:31 in winter), added in silver by `03_sales.py` with `convert_timezone(store_timezone_id, 'UTC', transaction_timestamp)`. Daylight saving time is applied per store time zone |

Both are wall clocks without a time zone (`TIMESTAMP_NTZ`), so they read the same in any session time zone. Local time answers "at what hour of the shop's day?"; GMT puts every store on **one timeline**, as the sales dashboard does ([`sales_dashboard.md`](sales_dashboard.md)).
