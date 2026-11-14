# Data warehouse: schemas, dimensions and keys

Reference for how the project's tables are organised: which schema holds what, the dimensions and their natural keys, and how the streaming data references them. It ties together the detailed pages:

| Page | Covers |
|---|---|
| [`dataset.md`](dataset.md) | The store dimension (`dim_store`), flagships, the people-counter events, opening hours, volumes |
| [`client.md`](client.md) | The client dimension (`dim_client`) and how buyers are chosen (local clients and visitors) |
| [`product.md`](product.md) | The product dimension (`dim_product`), categories and prices |
| [`people_stream.md`](people_stream.md) | The app that streams people events into `simulated_event_source` |
| [`sales.md`](sales.md) | The sales simulator that streams transactions into `simulated_sales_source` |

"Warehouse" on this page means the **data warehouse** (the `test02_warehouse` schema). The app's `sql_warehouse.py` is unrelated: it talks to the Databricks **SQL warehouse**, the compute that runs the app's SQL.

## 1. Two schemas

Both are in the catalog `workspace` (the bundle variable `catalog`).

| Schema | Bundle variable | Holds | Written by |
|---|---|---|---|
| `test02_warehouse` | `warehouse_schema` | **Dimensions** only: `dim_store`, `dim_client`, `dim_product`. Small, slowly changing master data, loaded by idempotent scripts | `src/sql/01_…`, `02_…`, `08_…` to `11_…`, by hand |
| `test02_streaming` | `schema` | **Streaming** only: the append-only sources `simulated_event_source` and `simulated_sales_source`, and the pipeline's streaming tables (bronze, silver, quarantine) | The people-stream app (sources), `src/sql/04_…`, `05_…`, `12_…`, and the pipeline |

The pipeline and the app read the dimensions from `test02_warehouse` and write only to `test02_streaming`. Nothing streams into `test02_warehouse`.

## 2. Tables

| Table | Schema | Grain | Primary key (natural) | Rows | Reference |
|---|---|---|---|---|---|
| `dim_store` | `test02_warehouse` | One store | `store_id`, e.g. `IT-MI-001` | 200 (2 flagships) | `dataset.md` §2 |
| `dim_client` | `test02_warehouse` | One registered client | `client_id`, e.g. `CL-IT-0000001` | 100,000 | `client.md` |
| `dim_product` | `test02_warehouse` | One product (SKU) | `product_id`, e.g. `SH-0007` | 120 | `product.md` |
| `simulated_event_source` | `test02_streaming` | One people-counter message | `source_topic` + `source_partition` + `source_offset` | per run | `dataset.md` §3, `people_stream.md` |
| `simulated_sales_source` | `test02_streaming` | One sales transaction message | `source_topic` + `source_partition` + `source_offset` | per run | `sales.md` |
| `bronze_people_counter_events` | `test02_streaming` | One message | as the source | pipeline | `readme.md` |
| `silver_people_counter_events` | `test02_streaming` | One valid event | `event_id` | pipeline | `readme.md` |
| `quarantine_people_counter_events` | `test02_streaming` | One invalid event | none | pipeline | `readme.md` |

## 3. Natural keys only

Every table is identified by its business key; there are **no surrogate keys** (no generated or identity columns). References use the referenced table's natural primary key:

```
 dim_store (store_id) ◀──────────────┬──────────── silver_people_counter_events.store_id   (FOREIGN KEY)
      ▲                              │
      │ country_code                 └──────────── sales payload store_id
 dim_client (client_id) ◀───────────────────────── sales payload client_id
 dim_product (product_id) ◀──────────────────────── sales payload product_id
 silver event_id ◀───────────────────────────────── sales payload exit_event_id
```

- `silver_people_counter_events` declares `FOREIGN KEY (store_id) REFERENCES workspace.test02_warehouse.dim_store(store_id)` (informational, as all Unity Catalog constraints).
- The sales source holds raw JSON, so its references are not constraints yet; the silver sales table of the next step will declare them the same way (`sales.md` §2).
- `dim_client.country_code` is a store country: every client is registered in a country that has stores.

## 4. Loading order

All scripts are in `src/sql/`, run by hand on the SQL warehouse, in number order. Every script is idempotent.

| Step | Scripts | Result |
|---|---|---|
| Stores | `01` (creates the `test02_warehouse` schema and `dim_store`), `02`, check `03` | 200 stores, 2 flagships |
| People source | `04` (creates the `test02_streaming` schema and the source), optionally `05`, check `06` | Empty source, or the 8 hand-written events |
| Clients and products | `08`, `09`, `10`, `11`, check `13` | 100,000 clients, 120 products |
| Sales source | `12` | Empty sales source |

## 5. Moving the dimensions out of `test02_streaming`

The dimensions used to live in `test02_streaming`. To move to the layout above in an existing workspace:

1. Run `01`, `02`, `03` and `08` to `11`, `13`: the dimensions are created and loaded in `test02_warehouse` (100,000 clients).
2. Redeploy the pipeline bundle and the app bundle; both now read `test02_warehouse`.
3. Run the pipeline with **Full refresh all**: silver's foreign key now points to `test02_warehouse.dim_store`.
4. Run `14_drop_old_streaming_dimensions.sql` once: it drops the old `dim_store`, `dim_client` and `dim_product` from `test02_streaming`.
