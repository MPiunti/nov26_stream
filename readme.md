# nov26_stream

A Databricks learning project that ingests anonymous retail people-counter events and sales transactions through a streaming medallion pipeline (bronze → silver + quarantine). It is packaged as three separate Declarative Automation Bundles, and runs on a Databricks Free Edition workspace:

| Bundle | Folder | Contents |
|---|---|---|
| `retail_people_counter_bundle` | repo root | The pipeline |
| `retail_people_stream_bundle` | `apps/people_stream/` | The people-stream simulator app, which feeds the pipeline's source table, and its sales simulator, which feeds the sales source table; see [`doc/people_stream.md`](doc/people_stream.md) and [`doc/sales.md`](doc/sales.md) |
| `retail_sales_dashboard_bundle` | `apps/sales_dashboard/` | The sales BI dashboard app: read-only, live sales and people performance from the silver tables, with drill-down; see [`doc/sales_dashboard.md`](doc/sales_dashboard.md) |

The events come from a simulated source table for now, so pipeline development doesn't depend on Event Hubs. All data is synthetic.

This page gives the general rules for anyone working on the project, people and AI agents alike. Read it before making changes, and update it in the same change as whatever it describes.

## Project layout

```
nov26_stream/
├── readme.md                       General rules (this page)
├── agents.md                       Entry point for AI agents: index of the docs and mandatory rules
├── CLAUDE.md                       Entry point for Claude Code: loads this page and agents.md
├── doc/
│   ├── warehouse.md                Schemas (test02_warehouse dimensions, test02_streaming streams), natural keys, loading order
│   ├── dataset.md                  Stores, macro regions, people-flow streaming, opening hours, volumes
│   ├── people_stream.md            The people-stream simulator app: screen, time model, generator, writes
│   ├── sales.md                    The sales simulator: purchase probabilities, transactions, natural keys; silver sales rules
│   ├── sales_dashboard.md          The sales BI dashboard app: screen, KPIs, drill-down, refresh, queries
│   ├── client.md                   The client dimension: natural client_id, 100,000 clients, local vs visitor buyers
│   └── product.md                  The product dimension: natural product_id, six categories, prices
├── databricks.yml                  Pipeline bundle settings: name, variables, dev and prod targets; excludes apps/
├── apps/
│   ├── people_stream/              Separate bundle: the people-stream simulator app
│   │   ├── databricks.yml          App bundle settings: name, variables, warehouse lookup, targets
│   │   ├── resources/
│   │   │   └── people_stream.app.yml  The app: source folder, warehouse and table permissions
│   │   └── app/                    App source (Python, Dash)
│   │       ├── app.py              Screen: START/STOP and simulated hour; Simulator tab (sliders, parameters, status); Counters tab (dashboard)
│   │       ├── charts.py           Counters charts: people per calendar date (bars) and cumulative people in and out (lines)
│   │       ├── shop_config.yml     Store and simulation parameters: opening hours, stays, client mix, flagships, N_AVG_PEOPLE, PURCHASE_PROB, timing
│   │       ├── shop_config.py      Reads and checks shop_config.yml; standard library only
│   │       ├── simulator.py        Event generator and run loop; standard library only
│   │       ├── sales.py            Sales simulator: purchases from EXIT events; standard library only
│   │       ├── sql_warehouse.py    Databricks SQL warehouse access: reads dimensions and offsets, empties and fills the sources
│   │       ├── app.yaml            Start command and environment variables (warehouse, table names)
│   │       └── requirements.txt    Pinned packages, installed by Databricks on deploy
│   └── sales_dashboard/            Separate bundle: the sales BI dashboard app (read-only)
│       ├── databricks.yml          App bundle settings: name, variables, warehouse lookup, targets
│       ├── resources/
│       │   └── sales_dashboard.app.yml  The app: source folder, warehouse and SELECT-only table permissions
│       └── app/                    App source (Python, Dash)
│           ├── app.py              Screen: filter area, KPI cards, trend by hour, geography and product bars with drill-down
│           ├── bi.py               KPIs, live and like-for-like deltas, drill-down, chart series; standard library only
│           ├── dashboard_sql.py    Read-only, parameterized queries on silver and the dimensions; standard library only
│           ├── figures.py          Plotly charts: trend lines per date, horizontal bars stacked per date
│           ├── sql_warehouse.py    Databricks SQL warehouse access: parallel queries, one connection per thread
│           ├── app.yaml            Start command and environment variables (warehouse, table names, refresh seconds)
│           └── requirements.txt    Pinned packages, installed by Databricks on deploy
├── resources/
│   ├── modeling.peoplecounter.pipeline.yml  The pipeline: catalog, schema, serverless, source files
│   └── modeling.peoplecounter.job.yml       Continuous job that keeps the pipeline running (created paused)
├── src/
│   ├── pipelines/                  Pipeline source files only
│   │   ├── 00_check_tables.py      Pre-flight check that the input tables exist
│   │   ├── 01_bronze.py            Bronze streaming ingestion
│   │   ├── 02_silver.py            Parsing, validation, silver and quarantine tables
│   │   └── 03_sales.py             Sales: bronze, silver and quarantine transactions, foreign keys to the dimensions
│   └── sql/                        Scripts run by hand on the SQL warehouse, in number order
│       ├── 01_create_dim_store.sql                Setup: creates the test02_warehouse schema and the store dimension; idempotent
│       ├── 02_populate_dim_store.sql              Setup: loads 200 stores, macro regions and the 2 flagships (idempotent MERGE)
│       ├── 03_validate_dim_store.sql              Check: store counts, macro regions, keys, time zones
│       ├── 04_create_simulated_event_source.sql   Setup: creates the test02_streaming schema and the simulated source table
│       ├── 05_insert_simulated_events.sql         Load: merges 8 test events (5 valid, 3 invalid); idempotent
│       ├── 06_validate_simulated_event_source.sql Check: the source table's contents
│       ├── 07_validate_bronze.sql.dbquery.ipynb   Check: the bronze table's contents
│       ├── 08_create_dim_client.sql               Setup: creates the client dimension (natural key client_id)
│       ├── 09_populate_dim_client.sql             Setup: loads 100,000 clients, 500 per store per country (idempotent MERGE)
│       ├── 10_create_dim_product.sql              Setup: creates the product dimension (natural key product_id)
│       ├── 11_populate_dim_product.sql            Setup: loads 120 products, 20 per category (idempotent MERGE)
│       ├── 12_create_simulated_sales_source.sql   Setup: creates the simulated sales source table
│       ├── 13_validate_dim_client_product.sql     Check: client and product counts, keys, formats
│       └── 14_drop_old_streaming_dimensions.sql   One-off: drops the old dimension copies from test02_streaming (doc/warehouse.md §5)
├── tests/                          Tests of the bundle, pipeline code and docs
│   ├── helpers.py                  Shared helpers for the tests
│   ├── test_project_consistency.py Tests of the bundle, pipeline code and docs
│   ├── test_dataset.py             Tests of the dataset rules in doc/dataset.md
│   ├── test_people_stream.py       Tests of the simulator app, its bundle and doc/people_stream.md
│   ├── test_sales.py               Tests of the sales simulator, clients, products and their docs
│   ├── test_sales_dashboard.py     Tests of the sales dashboard app, its bundle and doc/sales_dashboard.md
│   └── run_tests.py                Notebook that runs all tests in Databricks
├── pyproject.toml, uv.lock         Local Python environment (Databricks Connect), managed by `databricks environments setup-local`
└── .gitignore
```

Only the files in `src/pipelines/` are pipeline source files, and the pipeline lists each one by name. The scripts in `src/sql/` are run by hand, in number order, on the SQL warehouse; never put them in `src/pipelines/`.

## Data flow

| Step | Object | Created by |
|---|---|---|
| Store dimension | `workspace.test02_warehouse.dim_store` (200 stores, 2 flagships, primary key `store_id`, `macro_region` EUROPE / AMERICAS / ASIA); see [`doc/dataset.md`](doc/dataset.md) | `src/sql/01_…` and `02_…`, by hand |
| Simulated source | `workspace.test02_streaming.simulated_event_source` (append-only, raw JSON) | Created by `src/sql/04_…`; filled by `05_…` by hand, and by the people-stream app |
| Client dimension | `workspace.test02_warehouse.dim_client` (100,000 clients, primary key `client_id`); see [`doc/client.md`](doc/client.md) | `src/sql/08_…` and `09_…`, by hand |
| Product dimension | `workspace.test02_warehouse.dim_product` (120 products, primary key `product_id`); see [`doc/product.md`](doc/product.md) | `src/sql/10_…` and `11_…`, by hand |
| Sales source | `workspace.test02_streaming.simulated_sales_source` (append-only, raw JSON transactions); see [`doc/sales.md`](doc/sales.md) | Created by `src/sql/12_…`; filled by the people-stream app |
| Pre-flight check | Fails the update before anything is loaded if an input table is missing, or if `dim_store`, `dim_client` or `dim_product` is empty | Pipeline, `00_check_tables.py` |
| Bronze | `bronze_people_counter_events`: raw events plus `ingestion_timestamp` | Pipeline, `01_bronze.py` |
| Silver | `silver_people_counter_events`: parsed, typed and valid events, with the store's time zone | Pipeline, `02_silver.py` |
| Quarantine | `quarantine_people_counter_events`: invalid events with `rejection_reason`, `record_status` = `OPEN` | Pipeline, `02_silver.py` |
| Sales bronze, silver, quarantine | `bronze_sales_transactions`, `silver_sales_transactions` (primary key `transaction_id`, foreign keys to `dim_store`, `dim_client`, `dim_product`), `quarantine_sales_transactions`; rules in [`doc/sales.md`](doc/sales.md) §10 | Pipeline, `03_sales.py` |
| Sales dashboard | Reads `silver_sales_transactions`, `silver_people_counter_events`, `dim_store`, `dim_product`; never writes; see [`doc/sales_dashboard.md`](doc/sales_dashboard.md) | The sales dashboard app |

**Two schemas** ([`doc/warehouse.md`](doc/warehouse.md)): the dimensions are in `workspace.test02_warehouse`; the sources and all pipeline tables, which are streaming tables, are in `workspace.test02_streaming`. The silver table has a primary key on `event_id` and a foreign key on `store_id` to `test02_warehouse.dim_store`.

**A load iteration:** run `05_insert_simulated_events.sql` (or, later, receive events from Event Hubs), then run the pipeline. With the people-stream app: every START **empties both source tables** (people events and sales, including the events of `05_…`), so after a START run the pipeline once with a **full refresh**, then keep it running with the continuous job; see [Running the pipeline](#running-the-pipeline). The pipeline first runs the pre-flight check, then picks up only the source rows it hasn't processed yet.

**Deletes in the source:** both bronze tables (people and sales) read their source with `skipChangeCommits`, so the deletes of an app START don't stop the stream: it skips them and goes on with the new rows. Until the next full refresh, bronze, silver and quarantine still hold the previous run's rows as well.

**No duplicate source rows:** a source row is identified by `source_topic`, `source_partition` and `source_offset`, the message's identity in Event Hubs. `05_…` inserts with a `MERGE` on those three columns, so running it again inserts nothing. The `MERGE` must stay insert-only (no `WHEN MATCHED`): bronze reads the source table as a stream, and an update or delete there breaks the stream.

**Input tables:** every table the pipeline reads but doesn't create must be listed in `REQUIRED_TABLES` in `00_check_tables.py`.

`event_timestamp` is `TIMESTAMP_NTZ`: the sensor's local time, without time-zone conversion. Every table with a `TIMESTAMP_NTZ` column must set `"delta.feature.timestampNtz": "supported"` in its `table_properties`.

## Validation rules

Each event goes to silver if it passes every rule, and to quarantine otherwise. `rejection_reason` lists every failed rule, separated by `|`. These are the people-counter rules (`02_silver.py`); the sales transactions have their own, in [`doc/sales.md`](doc/sales.md) §10 (`03_sales.py`).

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

## Databricks workspace

| | |
|---|---|
| **Workspace** | `https://dbc-06fb0002-68c5.cloud.databricks.com` (Free Edition) |
| **CLI profile** | `MPiunti` |
| **Catalog and schemas** | Catalog `workspace` (**not** `main`). `test02_warehouse` for the dimensions (bundle variable `warehouse_schema`), `test02_streaming` for the sources and pipeline tables (bundle variable `schema`). See [`doc/warehouse.md`](doc/warehouse.md). |
| **Git folder** | `/Workspace/Users/michele.piunti@gmail.com/retail_people_counter_bundle`, linked to `github.com/MPiunti/nov26_stream`, branch `main` |
| **Bundle target** | `dev` (development mode, the default). `prod` deploys to `/Users/michele.piunti@gmail.com/.bundle/retail_people_counter_bundle/prod` and runs as the owner. |
| **Pipeline** | `retail_people_counter_bronze`, shown as `[dev michele_piunti] retail-people-counter-bronze-dev`. Serverless, triggered: on its own, each run processes what's new and stops. Don't set `continuous` on the pipeline (deprecated); it runs continuously through the job below. |
| **Continuous job** | `retail_people_counter_continuous`, shown as `[dev michele_piunti] retail-people-counter-continuous-dev`, under **Jobs & Pipelines**. Runs the pipeline over and over, so it picks up every event the app writes within seconds. Created **paused**; development mode pauses it again on every deploy. |
| **App** | `people-stream-michele-piunti`, under **Compute → Apps**, from the `retail_people_stream_bundle` bundle in `apps/people_stream/`. Writes through the Serverless Starter Warehouse. |
| **Dashboard app** | `sales-bi-michele-piunti`, under **Compute → Apps**, from the `retail_sales_dashboard_bundle` bundle in `apps/sales_dashboard/`. Reads through the Serverless Starter Warehouse, every 5 seconds while a page is open. |

## Tools

- **Databricks CLI:** `databricks` isn't on the `PATH`. Use the copy installed with the Databricks VS Code extension:
  ```powershell
  $db = "$env:USERPROFILE\.vscode\extensions\databricks.databricks-2.23.1-win32-x64\bin\databricks.exe"
  & $db bundle validate --strict -t dev --profile MPiunti
  ```
  The folder name changes when the extension updates; look for `databricks.exe` under `%USERPROFILE%\.vscode\extensions\databricks.databricks-*`. In Git Bash, set `MSYS_NO_PATHCONV=1` before passing workspace paths such as `/Users/...`.
- **Python:** Python 3.13, without PyYAML, pandas or pyspark. The tests use only the standard library.

## Common tasks

| Task | How (with `$db` as above) |
|---|---|
| Check the bundle | `& $db bundle validate --strict -t dev --profile MPiunti` |
| Get the latest code into Databricks | Owner pushes to `main`, then in the Git folder: **Pull** (or `& $db repos update <repo-id> --branch main --profile MPiunti`) |
| Deploy the pipeline | In the Git folder: **Deployments** (rocket) → `dev` → **Deploy**. Or `& $db bundle deploy -t dev --profile MPiunti`, from the repo root. |
| Deploy and start the app | From `apps/people_stream/`: `& $db bundle deploy -t dev --profile MPiunti`, then `& $db bundle run people_stream -t dev --profile MPiunti`. Or open `apps/people_stream/` in the Git folder and use **Deployments**. Run `src/sql/01_…`, `02_…`, `04_…` and, for sales, `08_…` to `12_…` first. See [`doc/people_stream.md`](doc/people_stream.md) §9. |
| Deploy and start the dashboard | From `apps/sales_dashboard/`: `& $db bundle deploy -t dev --profile MPiunti`, then `& $db bundle run sales_dashboard -t dev --profile MPiunti`. The pipeline must have run once with `03_sales.py`, so the silver tables exist. See [`doc/sales_dashboard.md`](doc/sales_dashboard.md) §7. |
| Run the pipeline | Pipeline UI → **Start**, or `& $db bundle run retail_people_counter_bronze -t dev --profile MPiunti`. After an app START: **Full refresh all**, or add `--full-refresh-all` |
| Follow the app continuously | See [Running the pipeline](#running-the-pipeline): Pause the job, START the app, full refresh, Resume the job |
| Rebuild silver and quarantine | Pipeline UI → **Full refresh selection** on the two tables. Needed after a change to a table's schema or table features, because a normal update doesn't change an existing table's features. |
| Run the tests on a PC | `python -m unittest discover -s tests`. See [Tests](#tests). |
| Run the tests in Databricks | Open `tests/run_tests` in the Git folder and click **Run all** |

## Running the pipeline

The app and the pipeline are decoupled: the app writes to the source tables, the pipeline reads them. For each app run:

| Step | Where | What happens |
|---|---|---|
| 1. **Pause** the continuous job (if it's running) | Jobs & Pipelines → `[dev michele_piunti] retail-people-counter-continuous-dev` → **Pause** | No pipeline update runs. Only one update can run at a time, so this frees the pipeline for the full refresh |
| 2. **START** the app | People-stream app | The app empties both source tables and starts writing people events and sales |
| 3. **Full refresh** the pipeline, once | Jobs & Pipelines → `[dev michele_piunti] retail-people-counter-bronze-dev` → arrow next to **Run pipeline** → **Run pipeline with full table refresh** (older UI: **Start** ▾ → **Full refresh all**). Or `& $db bundle run retail_people_counter_bronze --full-refresh-all -t dev --profile MPiunti` | Bronze, silver and quarantine are emptied and rebuilt from the current source: the current run only. Silver is recreated with its foreign key to `test02_warehouse.dim_store` |
| 4. **Resume** the continuous job | The job's page → **Resume** | From now on the job keeps the pipeline running: every new event and sale the app writes reaches bronze and silver within seconds, for the rest of the run, and the sales dashboard shows it at its next refresh |

Pause the job again when the run is over: while it's resumed, it keeps serverless compute running and billed. If you forget step 1, nothing breaks: bronze skips the START's deletes and keeps streaming, but the tables hold the previous run too until you do steps 1, 3 and 4. A normal **Run pipeline** (no full refresh) also works at any time; it adds what's new and stops.

## Working rules

**Databricks:**
- **Validate first:** run `bundle validate --strict` after every change to `databricks.yml`, `resources/` or `src/`.
- **Serverless only:** Free Edition has no classic clusters. Don't add cluster settings.
- **Never upload `.git/`:** the workspace copy is the Git folder; don't copy the local repo into the workspace with `import-dir`.
- **Table features:** a new column type that needs a Delta table feature (such as `TIMESTAMP_NTZ`) needs the feature in `table_properties`, then a full refresh of the tables that already exist.

**Tests:**
- **Run them before deploying:** after pulling a change into the Git folder, run `tests/run_tests` there, and deploy only if it passes. Agents run them on the PC before handing over a change.
- **Add a test with every change:** a new feature or data rule gets a test in `tests/`.

**Data:**
- **Synthetic only:** never add real customer, store or company data.

**Git:**
- **Branch:** work happens on `main`.
- **Flow:** the owner commits and pushes to GitHub first; then Databricks pulls the changes into the Git folder; then the bundle is deployed from there.
- **Pull first:** the repo can also be edited from the Databricks Git folder, so pull before committing.
- **Don't commit:** `.databricks/` (already in `.gitignore`), `.vscode/`, credentials, tokens or local environment files.

**Agents:**
- **Never commit or push — mandatory:** leave every change uncommitted in the working tree, so the owner can review it in VS Code's Source Control view. At the end of each task, list every file you added, changed or deleted, as links, so the owner can open them. The owner commits and pushes after reviewing. This applies even when a task seems to need a commit, such as pulling into the Databricks Git folder; say that the owner needs to commit and push first.
- **Ask first:** get the owner's confirmation before deploying, running or full-refreshing the pipeline.
- **Report honestly:** say what was run and checked, and what wasn't. Code that hasn't run in Databricks is untested.

## Tests

The `tests/` folder checks that the project's parts agree with each other, before anything is deployed. The tests read only the project's files: they don't touch any table or pipeline, and need no Databricks connection or extra packages.

| File | Checks |
|---|---|
| `test_project_consistency.py` | Bundle: name, targets, includes, the files the pipeline points to, serverless only, no deprecated pipeline fields. Pipeline code: the pre-flight check runs first and covers every input table; bronze skips the source deletes of an app START (`skipChangeCommits`); the continuous job runs the pipeline, is created paused and never full-refreshes; dimensions are read from `warehouse_schema` and streaming tables use `schema`; every table with a `TIMESTAMP_NTZ` column enables `timestampNtz`; table names use the bundle's catalog and schema; every rejection code is in [Validation rules](#validation-rules) and vice versa. Sales pipeline (`03_sales.py`): bronze skips the source deletes, silver and quarantine select their schema columns, the foreign keys point to the three dimensions, and every sales rejection code is in [`doc/sales.md`](doc/sales.md) §10 and vice versa. Simulated events: the load is an insert-only `MERGE` on topic, partition and offset; offsets are unique; the 8 events and their expected outcome. Docs: every test file is listed on this page, and `CLAUDE.md` loads this page and keeps the mandatory rules. |
| `test_dataset.py` | The rules in [`doc/dataset.md`](doc/dataset.md): the store distribution and totals match `02_populate_dim_store.sql`; `macro_region` is defined in the create, populate and validate scripts, and every country maps to one macro region the same way in each; the two flagships (`IT-MI-001`, `US-NY-001`) and their names; the dimensions live only in `test02_warehouse` and the sources in `test02_streaming`; the validation script's expected counts match; at least one store is open at every UTC hour, in winter and summer; the `N_AVG_PEOPLE_*` defaults. `agents.md` lists every page in `doc/`, and its links work. |
| `test_sales.py` | The sales simulator, clients and products, against [`doc/sales.md`](doc/sales.md), [`doc/client.md`](doc/client.md) and [`doc/product.md`](doc/product.md): buyers per category match PURCHASE_PROB; only EXITs trigger sales; each transaction names the exit's store, a client of the store's country and a product of the category at list price, at the exit's time; transaction IDs and offsets; the client and product scripts generate what the docs say (100,000 distinct clients, 120 products, ID formats, prices); 70% local buyers and 30% visitors, inverted at the flagships, with visitors from every country; the six categories agree everywhere; the sales source has the same envelope as the people source; the app has 18 probability sliders and writes sales after people; every simulated transaction passes the silver sales rules. |
| `test_sales_dashboard.py` | The sales dashboard app, against [`doc/sales_dashboard.md`](doc/sales_dashboard.md): every query is a read-only `SELECT` on the silver tables and dimensions only, with filter values as parameters (no SQL injection) and checked dates, levels and table names; every filter reaches the sales queries, people ignore category and product; KPI totals, average price, items per visitor; the like-for-like delta compares the same hours, the live delta only with the same filters; trend lines per date, cumulative through the day, stopping at the latest hour; horizontal bars largest first, one segment per date, top 15; drill-down Area → Country → Store and Merch. category → Product, and Up; the tab title is fixed; the 5-second refresh; the bundle is separate, grants `SELECT` only, and its settings match the queries; no coupling with the people-stream app. |
| `test_people_stream.py` | The simulator app, against [`doc/people_stream.md`](doc/people_stream.md): 240 s per simulated day and 10 s per hour; START uses the current time and begins from scratch; a run finishes by itself after 48 simulated hours (480 s), and STOP quits the generator; slider range, step and default; daily visitors per store match each region's `N_AVG_PEOPLE`; events only during local opening hours; nobody stays longer than `max_stay_minutes` (90); the stay window has the average stay slider's mean and the measured average follows the slider; flagships get 45% more entries; people in = people out for every store and local day that reaches closing within the run; every event passes the silver rules; topic, partition per region and consecutive offsets; a failed write stops the run; the chart history is cumulative per region for entries and exits, never has more out than in, and ends at 48 hours; the charts are only on the Counters tab; the per-date bars sum people per store-local date and region; the headline and the browser tab title show the simulated hour only while running; every START first empties both source tables, before reading or writing anything. `shop_config.yml` holds every parameter, the simulator and app take them from it (no hard-coded values), the app shows them, and bad files are rejected. The insert is an insert-only `MERGE` on topic, partition and offset. The app bundle is separate from the pipeline bundle, grants exactly the table permissions the app uses, and pins its packages. The time-zone tests need `tzdata` on Windows and are skipped without it. |

**Running them:**
- **On a PC:** from the repo root, run `python -m unittest discover -s tests`.
- **In Databricks:** open `tests/run_tests` in the Git folder, attach serverless compute and click **Run all**. It fails if any test fails.

**What the tests don't cover:** Spark itself, the parsing results on real data, and the deployed pipeline. Those are checked by running the pipeline and the validation scripts in `src/`.
