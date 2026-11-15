# Data warehouse: schemas, dimensions and keys

Reference for how the project's tables are organised: which schema holds what, the dimensions and their natural keys, and how the streaming data references them. It ties together the detailed pages:

| Page | Covers |
|---|---|
| [`architecture.md`](architecture.md) | The whole solution on one page: the three engines and the data contracts between them |
| [`dataset.md`](dataset.md) | The store dimension (`dim_store`), flagships, the people-counter events, opening hours, volumes |
| [`client.md`](client.md) | The client dimension (`dim_client`) and how buyers are chosen (local clients and visitors) |
| [`product.md`](product.md) | The product dimension (`dim_product`), categories and prices |
| [`people_stream.md`](people_stream.md) | The app that streams people events into `simulated_event_source` |
| [`sales.md`](sales.md) | The sales simulator that streams transactions into `simulated_sales_source`, and the silver sales rules |
| [`sales_dashboard.md`](sales_dashboard.md) | The read-only BI app that queries the silver tables and the dimensions |

"Warehouse" on this page means the **data warehouse** (the `test02_warehouse` schema). The app's `sql_warehouse.py` is unrelated: it talks to the Databricks **SQL warehouse**, the compute that runs the app's SQL.

## 1. Two schemas

Both are in the catalog `workspace` (the bundle variable `catalog`).

| Schema | Bundle variable | Holds | Written by |
|---|---|---|---|
| `test02_warehouse` | `warehouse_schema` | **Dimensions** only: `dim_store`, `dim_client`, `dim_product`. Small, slowly changing master data, loaded by idempotent scripts | `src/sql/01_…`, `02_…`, `08_…` to `11_…`, by hand |
| `test02_streaming` | `schema` | **Streaming** only: the append-only sources `simulated_event_source` and `simulated_sales_source`, and the pipeline's streaming tables (bronze, silver, quarantine, for people events and for sales) | The people-stream app (sources), `src/sql/04_…`, `05_…`, `12_…`, and the pipeline |

The pipeline and the apps read the dimensions from `test02_warehouse`; the pipeline and the people-stream app write only to `test02_streaming`, and the sales dashboard writes nothing. Nothing streams into `test02_warehouse`.

## 2. Tables

| Table | Schema | Grain | Primary key (natural) | Rows | Reference |
|---|---|---|---|---|---|
| `dim_store` | `test02_warehouse` | One store | `store_id`, e.g. `IT-MI-001`, `IT-EC-001` | 213: 198 `RETAIL`, 2 `FLAGSHIP`, 13 `ECOM` (`channel`) | `dataset.md` §2 |
| `dim_client` | `test02_warehouse` | One registered client | `client_id`, e.g. `CL-IT-0000001` | 100,000 | `client.md` |
| `dim_product` | `test02_warehouse` | One product (SKU) | `product_id`, e.g. `SH-0007` | 120 | `product.md` |
| `simulated_event_source` | `test02_streaming` | One people-counter message | `source_topic` + `source_partition` + `source_offset` | per run | `dataset.md` §3, `people_stream.md` |
| `simulated_sales_source` | `test02_streaming` | One sales transaction message | `source_topic` + `source_partition` + `source_offset` | per run | `sales.md` |
| `bronze_people_counter_events` | `test02_streaming` | One message | as the source | pipeline | `readme.md` |
| `silver_people_counter_events` | `test02_streaming` | One valid event | `event_id` | pipeline | `readme.md` |
| `quarantine_people_counter_events` | `test02_streaming` | One invalid event | none | pipeline | `readme.md` |
| `bronze_sales_transactions` | `test02_streaming` | One sales message | as the source | pipeline | `sales.md` §10 |
| `silver_sales_transactions` | `test02_streaming` | One valid transaction | `transaction_id` | pipeline | `sales.md` §10 |
| `quarantine_sales_transactions` | `test02_streaming` | One invalid transaction | none | pipeline | `sales.md` §10 |
| `current_simulation` (view) | `test02_streaming` | One row: the latest `simulation_id` | | view | §6 |
| `current_people_counter_events` (view) | `test02_streaming` | One valid event of the current simulation | `event_id` | view | §6 |
| `current_sales_transactions` (view) | `test02_streaming` | One valid transaction of the current simulation | `transaction_id` | view | §6 |

## 3. Natural keys only

Every table is identified by its business key; there are **no surrogate keys** (no generated or identity columns). References use the referenced table's natural primary key:

```
 dim_store (store_id) ◀──────────────┬──────────── silver_people_counter_events.store_id   (FOREIGN KEY)
      ▲                              │
      │ country_code                 └──────────── silver_sales_transactions.store_id      (FOREIGN KEY)
 dim_client (client_id) ◀───────────────────────── silver_sales_transactions.client_id     (FOREIGN KEY)
 dim_product (product_id) ◀──────────────────────── silver_sales_transactions.product_id    (FOREIGN KEY)
 silver event_id ◀───────────────────────────────── silver_sales_transactions.exit_event_id (plain column)
```

- `silver_people_counter_events` declares `FOREIGN KEY (store_id) REFERENCES workspace.test02_warehouse.dim_store(store_id)` (informational, as all Unity Catalog constraints).
- `silver_sales_transactions` declares its `store_id`, `client_id` and `product_id` foreign keys the same way (`sales.md` §10). The sales source holds raw JSON, so it has no constraints.
- `dim_client.country_code` is a store country: every client is registered in a country that has stores.

## 4. Loading order

All scripts are in `src/sql/`, run by hand on the SQL warehouse, in number order. Every script is idempotent.

| Step | Scripts | Result |
|---|---|---|
| Stores | `01` (creates the `test02_warehouse` schema and `dim_store`), `02`, check `03`. An older `dim_store` without `channel`: `16` once, before `02` | 213 stores: 200 physical (2 flagships), 13 e-commerce |
| People source | `04` (creates the `test02_streaming` schema and the source), optionally `05`, check `06` | Empty source, or the 8 hand-written events |
| Clients and products | `08`, `09`, `10`, `11`, check `13` | 100,000 clients, 120 products |
| Sales source | `12` | Empty sales source |
| Current-simulation views | `15`, after the pipeline has created the silver tables | Three views (§6) |

## 5. Moving the dimensions out of `test02_streaming`

The dimensions used to live in `test02_streaming`. To move to the layout above in an existing workspace:

1. Run `01`, `02`, `03` and `08` to `11`, `13`: the dimensions are created and loaded in `test02_warehouse` (100,000 clients).
2. Redeploy the pipeline bundle and the app bundle; both now read `test02_warehouse`.
3. Run the pipeline with **Full refresh all**: silver's foreign key now points to `test02_warehouse.dim_store`.
4. Run `14_drop_old_streaming_dimensions.sql` once: it drops the old `dim_store`, `dim_client` and `dim_product` from `test02_streaming`.

## 6. Simulations and the current-simulation views

Every START of the people-stream app begins a new **simulation**. Its `simulation_id` is the real UTC start time to the millisecond, e.g. `20261114T193627123`: sortable, so the latest simulation is `MAX(simulation_id)`. The app writes it into every event and transaction (`people_stream.md` §6, `sales.md` §5), and the pipeline carries it into the silver and quarantine tables as the column `simulation_id`. Rows that don't come from the app (the 8 hand-written events of `05_…`) have no simulation id.

The pipeline is never stopped or refreshed at a START (`readme.md`, "Running the pipeline"), so silver holds **every** simulation. Three plain views, created once by `src/sql/15_create_current_simulation_views.sql`, keep only the latest:

| View | Definition |
|---|---|
| `current_simulation` | `SELECT MAX(simulation_id) FROM silver_people_counter_events`: the one definition of "current". People events always arrive before the first sale, so everything below switches to a new simulation at the same moment |
| `current_people_counter_events` | `silver_people_counter_events` where `simulation_id` is the current one |
| `current_sales_transactions` | `silver_sales_transactions` where `simulation_id` is the current one |

- **Plain views, not materialized:** they are evaluated at query time, so they add no delay to silver. A new simulation is visible as soon as its first people events reach silver.
- **Fast filter:** both silver tables are clustered by `simulation_id` (`cluster_by` in the pipeline), so the filter and the `MAX` don't scan earlier simulations.
- **Readers:** the sales dashboard reads only the two `current_…` views and the dimensions ([`sales_dashboard.md`](sales_dashboard.md)). Anything that should follow the running simulation reads the views; the silver tables remain for looking at earlier simulations.
- **Housekeeping:** earlier simulations stay in the tables until a full refresh (`readme.md`, "Running the pipeline").
