# The data pipeline: data flow, validation rules, running it

Reference for the streaming medallion pipeline (bronze → silver + quarantine): every object from the dimensions to the dashboard, the people-counter validation rules, and how the pipeline is kept running. Read it before changing the pipeline, and update it in the same change. Schemas and keys are in [`warehouse.md`](warehouse.md), stores and events in [`dataset.md`](dataset.md), the sales rules in [`sales.md`](sales.md) §10; why it is built this way, in [`decisions.md`](decisions.md).

## 1. Data flow

| Step | Object | Created by |
|---|---|---|
| Store dimension | `workspace.test02_warehouse.dim_store` (213 stores, primary key `store_id`, `macro_region` EUROPE / AMERICAS / ASIA, `channel` RETAIL 198 / FLAGSHIP 2 / ECOM 13, one e-commerce store per country); see [`dataset.md`](dataset.md) | `src/sql/01_…` and `02_…`, by hand (`16_…` once, on a `dim_store` without `channel`) |
| Simulated source | `workspace.test02_streaming.simulated_event_source` (append-only, raw JSON) | Created by `src/sql/04_…`; filled by `05_…` by hand, and by the people-stream app |
| Client dimension | `workspace.test02_warehouse.dim_client` (100,000 clients, primary key `client_id`); see [`client.md`](client.md) | `src/sql/08_…` and `09_…`, by hand |
| Product dimension | `workspace.test02_warehouse.dim_product` (120 products, primary key `product_id`); see [`product.md`](product.md) | `src/sql/10_…` and `11_…`, by hand |
| Sales source | `workspace.test02_streaming.simulated_sales_source` (append-only, raw JSON transactions); see [`sales.md`](sales.md) | Created by `src/sql/12_…`; filled by the people-stream app |
| Pre-flight check | Fails the update before anything is loaded if an input table is missing, or if `dim_store`, `dim_client` or `dim_product` is empty | Pipeline, `00_check_tables.py` |
| Bronze | `bronze_people_counter_events`: raw events plus `ingestion_timestamp` | Pipeline, `01_bronze.py` |
| Silver | `silver_people_counter_events`: parsed, typed and valid events, with the store's time zone | Pipeline, `02_silver.py` |
| Quarantine | `quarantine_people_counter_events`: invalid events with `rejection_reason`, `record_status` = `OPEN` | Pipeline, `02_silver.py` |
| Sales bronze, silver, quarantine | `bronze_sales_transactions`, `silver_sales_transactions` (one row per item; primary key `transaction_id`, `line_number`, foreign keys to `dim_store`, `dim_client`, `dim_product`; sale time local and GMT, `transaction_timestamp_utc`), `quarantine_sales_transactions`; rules in [`sales.md`](sales.md) §10 | Pipeline, `03_sales.py` |
| Metric views (KPIs) | `workspace.test02_metric.client_metrics` (client KPIs) and `store_metrics` (store KPIs, sales and traffic, with conversion), computed live from silver and the dimensions; definitions in [`kpi_glossary.md`](kpi_glossary.md), see [`kpi_metrics.md`](kpi_metrics.md) | The schema by `src/sql/17_…`, by hand; the metric views by the job `retail-metric-views`, from `src/metrics/` |
| Current-simulation views | `current_simulation`, `current_people_counter_events`, `current_sales_transactions`: the silver tables filtered to the latest `simulation_id`; see [`warehouse.md`](warehouse.md) §6 | `src/sql/15_…`, by hand, once |
| Sales dashboard | Reads `current_sales_transactions`, `current_people_counter_events`, the metric views `client_metrics` and `store_metrics` (Clienteling tab), `dim_store`, `dim_product`; never writes; see [`sales_dashboard.md`](sales_dashboard.md) | The sales dashboard app |
| Genie agent | Reads the two metric views, the three dimensions and the current-simulation views, with the permissions of the user who asks; see [`kpi_genie.md`](kpi_genie.md) | The Genie bundle's job `deploy-kpi-genie` |

**Three schemas** ([`warehouse.md`](warehouse.md)): the dimensions are in `workspace.test02_warehouse`; the sources and all pipeline tables, which are streaming tables, are in `workspace.test02_streaming`; the metric views (KPIs) are in `workspace.test02_metric` ([`kpi_metrics.md`](kpi_metrics.md)). The silver table has a primary key on `event_id` and a foreign key on `store_id` to `test02_warehouse.dim_store`.

**A load iteration:** run `05_insert_simulated_events.sql` (or, later, receive events from Event Hubs), then run the pipeline. With the people-stream app: keep the continuous job resumed; every START **empties both source tables** (people events and sales, including the events of `05_…`) and begins a new simulation with a new `simulation_id`, which the running pipeline picks up by itself, with no full refresh; see [§3](#3-running-the-pipeline). The pipeline first runs the pre-flight check, then picks up only the source rows it hasn't processed yet.

**Deletes in the source:** both bronze tables (people and sales) read their source with `skipChangeCommits`, so the deletes of an app START don't stop the stream: it skips them and goes on with the new rows. Bronze, silver and quarantine therefore keep the earlier simulations' rows; every row carries its `simulation_id`, and the `current_…` views show only the latest simulation ([`warehouse.md`](warehouse.md) §6).

**No duplicate source rows:** a source row is identified by `source_topic`, `source_partition` and `source_offset`, the message's identity in Event Hubs. `05_…` inserts with a `MERGE` on those three columns, so running it again inserts nothing. The `MERGE` must stay insert-only (no `WHEN MATCHED`): bronze reads the source table as a stream, and an update or delete there breaks the stream.

**Input tables:** every table the pipeline reads but doesn't create must be listed in `REQUIRED_TABLES` in `00_check_tables.py`.

`event_timestamp` is `TIMESTAMP_NTZ`: the sensor's local time, without time-zone conversion. Every table with a `TIMESTAMP_NTZ` column must set `"delta.feature.timestampNtz": "supported"` in its `table_properties`.

## 2. Validation rules

Each event goes to silver if it passes every rule, and to quarantine otherwise. `rejection_reason` lists every failed rule, separated by `|`. These are the people-counter rules (`02_silver.py`); the sales transactions have their own, in [`sales.md`](sales.md) §10 (`03_sales.py`).

| Code | Rule |
|---|---|
| `INVALID_JSON` | The payload isn't valid JSON for the event schema |
| `MISSING_EVENT_ID` | `event_id` is missing or empty |
| `MISSING_STORE_ID` | `store_id` is missing or empty |
| `MISSING_SENSOR_ID` | `sensor_id` is missing or empty |
| `INVALID_EVENT_TIMESTAMP` | `event_timestamp` is missing, empty or not a valid timestamp |
| `INVALID_EVENT_TYPE` | `event_type` isn't `ENTRY` or `EXIT` (after trimming and upper-casing) |
| `INVALID_PEOPLE_COUNT` | `people_count` is missing, zero or negative |
| `UNKNOWN_STORE` | `store_id` isn't in `dim_store` |

The 8 simulated events give 5 silver rows and 3 quarantine rows: invalid JSON (offset 6), unknown store (7) and invalid event type (8).

## 3. Running the pipeline

The apps and the pipeline are decoupled: the simulator writes to the source tables, the pipeline reads them, and the dashboard reads silver through the current-simulation views.

**Pipeline and job:** the pipeline defines *what* is computed (bronze, silver, quarantine); the continuous job decides *when*. While the job is resumed it keeps one pipeline update running, which picks up new source rows in micro-batches every 2 seconds per table (`pipelines.trigger.interval` in the pipeline's settings), so an event reaches silver a few seconds after the app writes it. You never start the pipeline yourself while the job is resumed: only one update can run at a time.

**Simulations:** every START of the people-stream app begins a new simulation with a new `simulation_id` (its UTC start time, so the latest is the highest). The pipeline keeps running through a START: nothing is paused, stopped or refreshed. Silver holds every simulation; the views `current_people_counter_events` and `current_sales_transactions` keep only the latest one, and the dashboard reads those views. So within seconds of a START the dashboard shows the new simulation only.

For a session:

| Step | Where | What happens |
|---|---|---|
| 1. **Resume** the continuous job, once | Jobs & Pipelines → `[dev michele_piunti] retail-simulator` → **Resume** | The job starts a pipeline update (about a minute to start) and keeps it running |
| 2. **START** the app, as often as you like | People-stream app | The app empties both source tables and writes a new simulation; bronze skips the deletes, silver receives the new rows within seconds, and the dashboard switches to the new simulation |
| 3. **Pause** the job when you're done | The job's page → **Pause** | The pipeline stops; no serverless compute is running or billed |

If the job is paused when you press START, nothing is lost: the events wait in the source tables, and the pipeline catches up once the job is resumed. The full switch-on and switch-off steps, apps included, are in [`people_stream.md`](people_stream.md) §10.

**Housekeeping, not at every START:** the earlier simulations stay in bronze, silver and quarantine. To drop them, with the job **paused** and no simulation running, run the pipeline once with a full refresh (Pipeline UI → arrow next to **Run pipeline** → **Run pipeline with full table refresh**, or `& $db bundle run retail_people_counter_bronze --full-refresh-all -t dev --profile MPiunti`). It empties the tables and rebuilds them from the current sources; the views stay valid. A full refresh is also needed after a change to a table's schema or table features.
