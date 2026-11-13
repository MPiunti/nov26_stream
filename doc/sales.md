# Sales: the sales simulator

Functional reference for the sales transactions: how the people-stream app turns people leaving a store into purchases, what a transaction contains, the natural keys it references, and where it is written.

The people flow it builds on is in [`people_stream.md`](people_stream.md); stores in [`dataset.md`](dataset.md); clients in [`client.md`](client.md); products in [`product.md`](product.md).

## 1. Purpose and boundaries

| | |
|---|---|
| **What it does** | A second simulator on the people stream's timeline: for each `EXIT` event, it decides who of the people leaving bought something, and inserts one sales transaction per purchase into `workspace.test02_streaming.simulated_sales_source` |
| **Where it runs** | Inside the people-stream app (`apps/people_stream/app/sales.py`), in the same batches as the people events: START, STOP and the 48-hour limit apply to both |
| **What it doesn't do (yet)** | Load the sales into bronze/silver. The pipeline doesn't read `simulated_sales_source` yet; a sales pipeline step with the foreign keys of §5 is the next step |

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

All keys are **natural keys**; there are no surrogate keys. Every reference uses the referenced table's natural primary key.

| Table | Grain | Primary key | References |
|---|---|---|---|
| `dim_store` | One row per store | `store_id` | |
| `dim_client` | One registered client | `client_id` | (registered in a `dim_store` country) |
| `dim_product` | One product (SKU) | `product_id` | |
| `simulated_sales_source` | One message = one transaction | `source_topic` + `source_partition` + `source_offset` (message identity) | Payload: `store_id` → `dim_store`, `client_id` → `dim_client`, `product_id` → `dim_product`, `exit_event_id` → the people event's `event_id` |

The source table holds raw JSON, like `simulated_event_source`, so the references inside the payload are not constraints yet. The silver sales table of the next step will declare them as Unity Catalog `FOREIGN KEY` constraints on the natural keys (informational, like the existing `store_id` foreign key of `silver_people_counter_events`).

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
   - **Client:** one registered client of the store's country, drawn uniformly from `dim_client` (`client.md` §4).
   - **Product:** one product of category C, drawn uniformly from `dim_product` (`product.md` §4).
   - **Quantity and amount:** 1 unit at the product's `list_price`, in EUR.
   - **Time:** the exit's local `event_timestamp`.

Entries never trigger sales; only people leaving buy. Stores closed or not yet reached by the timeline produce no exits and therefore no sales. The closing `EXIT` at 20:00 (everyone still inside) produces sales like any other exit.

## 5. Transaction shape

Payload (`raw_event`), one JSON object per transaction:

```json
{"transaction_id":"tx-3f9a1c2b-0-0000000042","exit_event_id":"sim-3f9a1c2b-0-0000001234",
 "store_id":"IT-MI-001","client_id":"CL-IT-0004711","product_id":"SH-0007","category":"SHOES",
 "quantity":1,"unit_price":540.0,"amount":540.0,"currency":"EUR",
 "transaction_timestamp":"2026-11-14T15:31:12.408"}
```

| Field | Rule |
|---|---|
| `transaction_id` | `tx-<run id>-<partition>-<offset, 10 digits>`; unique across runs. The natural key of a transaction |
| `exit_event_id` | `event_id` of the `EXIT` that triggered it; several transactions can share one exit |
| `store_id` | The exit's store → `dim_store.store_id` |
| `client_id` | → `dim_client.client_id`; same country as the store |
| `product_id` | → `dim_product.product_id`; of `category` |
| `category` | The product's category |
| `quantity` | 1 |
| `unit_price`, `amount` | The product's `list_price`; `amount = quantity × unit_price` |
| `currency` | `EUR` |
| `transaction_timestamp` | Store local time, no time zone (as the people events' `event_timestamp`) |

Envelope columns:

| Column | Value |
|---|---|
| `source_topic` | `retail-sales-app` |
| `source_partition` | One per macro region, as the people stream: `0` EUROPE, `1` AMERICAS, `2` ASIA |
| `source_offset` | Consecutive per partition; on START it continues after the highest offset already in the table for this topic and partition |
| `source_timestamp` | The batch's simulated UTC time, as for the people events |

## 6. Writing

- **Order:** in every batch the app writes the people events first, then the sales transactions they generated.
- **Statement:** insert-only `MERGE` on the message identity (`source_topic`, `source_partition`, `source_offset`), in chunks of at most 1,000 rows. A retried batch can't insert a row twice; no row is ever updated or deleted, so the table can be read as a stream.
- **Failure:** a failed write stops the run with state `FAILED`, as for the people events.

## 7. Volumes

With N_AVG_PEOPLE 3000 and the default probabilities, about 600,000 people leave per simulated day, so:

| | Per simulated day (240 s) | Per run (48 h, 480 s) |
|---|---|---|
| Transactions | ≈ 120,000 | ≈ 240,000 |
| Amount | ≈ 86 million EUR (≈ 720 EUR average per transaction) | ≈ 170 million EUR |

Transactions follow the exits, so they peak when a region's stores close at 20:00: a batch can then hold up to about 9,000 transactions (measured peak 8,722), written as up to 9 statements of 1,000 rows. If writing takes longer than a batch interval, the next batch covers the longer window (`people_stream.md` §4), so simulated time doesn't drift.

## 8. On screen

- **Simulator tab:** the 18 horizontal PURCHASE_PROB sliders (§3); the **Parameters** panel shows their defaults and range.
- **Counters tab:** **Sales transactions by region and category**: transactions per category, total transactions, amount in EUR, and transactions per person out.

## 9. Setup and permissions

| Step | How |
|---|---|
| Tables | In the pipeline bundle, run `src/sql/08_…` to `11_…` (clients and products), `12_…` (sales source), then check with `13_…`. See `client.md` §5 and `product.md` §5 |
| Granted to the app | `SELECT` on `dim_client` and `dim_product`; `SELECT` and `MODIFY` on `simulated_sales_source` (`apps/people_stream/resources/people_stream.app.yml`). The tables must exist before the app bundle is deployed |
| App settings | `CLIENT_TABLE`, `PRODUCT_TABLE`, `SALES_TABLE` in `apps/people_stream/app/app.yaml` |
