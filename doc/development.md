# Development: project layout and working rules

The general rules for anyone working on the project, people and AI agents alike: where each file lives, and how to change, test and hand over a change. Read it before making changes, and update it in the same change as whatever it describes. Deploying and running are in [`operations.md`](operations.md); the tests in [`testing.md`](testing.md).

## 1. Project layout

```
nov26_stream/
├── readme.md                       Front door: what the solution is, who reads what, the four bundles, quick start
├── agents.md                       Entry point for AI agents: index of the docs by level, and mandatory rules
├── CLAUDE.md                       Entry point for Claude Code: loads the readme, agents.md and this page
├── doc/
│   ├── executive_brief.md          Level 0, for a CTO: the retail problem, why Databricks, value, roadmap, questions, demo script
│   ├── architecture.md             Level 1: the engines, how they are decoupled, the Databricks services used, speed, numbers
│   ├── decisions.md                Level 1: the decision log, each decision with its alternatives and consequences
│   ├── pipeline.md                 Level 2: data flow, people-counter validation rules, running the pipeline
│   ├── warehouse.md                Level 2: schemas (test02_warehouse dimensions, test02_streaming streams, test02_metric metric views), natural keys, loading order, current-simulation views
│   ├── kpi_metrics.md              Level 2: KPIs as Unity Catalog metric views in test02_metric: why metric views, design rules, KPI list
│   ├── kpi_glossary.md             Level 3: functional definition of every KPI and dimension: the metric views' comments, word for word
│   ├── kpi_genie.md                Level 2: the Genie agent on the KPIs: purpose, sources, definition, deployment, checks
│   ├── dataset.md                  Level 2: stores, macro regions, people-flow streaming, opening hours, volumes
│   ├── people_stream.md            Level 2: the people-stream simulator app: screen, time model, generator, writes, switch on and off
│   ├── sales.md                    Level 2: the sales simulator: purchase probabilities, transactions, natural keys; silver sales rules
│   ├── sales_dashboard.md          Level 2: the sales BI dashboard app: screen, KPIs, drill-down, refresh, queries
│   ├── client.md                   Level 2: the client dimension: natural client_id, 100,000 clients, local vs visitor buyers
│   ├── product.md                  Level 2: the product dimension: natural product_id, six categories, prices
│   ├── operations.md               Level 3: workspace, tools, deployment order and rules, everyday tasks
│   ├── development.md              Level 3: this page
│   └── testing.md                  Level 3: test strategy and what each test file checks
├── databricks.yml                  Pipeline bundle settings: name, variables, dev and prod targets; excludes apps/ and agents/
├── agents/
│   └── kpi_genie/                  Separate bundle: the Genie agent Retail KPI Assistant
│       ├── databricks.yml          Bundle settings: name, warehouse lookup, Genie folder, targets
│       ├── resources/
│       │   └── kpi_genie.job.yml   Job deploy_kpi_genie: creates or updates the agent from its definition (run on demand)
│       └── src/
│           ├── kpi_genie.json      The agent's definition: title, description, sources, instructions, example SQL, benchmarks
│           └── deploy_genie.py     Creates the agent from kpi_genie.json, or updates it in place
├── apps/
│   ├── people_stream/              Separate bundle: the people-stream simulator app
│   │   ├── databricks.yml          App bundle settings: name, variables, warehouse lookup, targets
│   │   ├── resources/
│   │   │   └── people_stream.app.yml  The app: source folder, warehouse and table permissions
│   │   └── app/                    App source (Python, Dash)
│   │       ├── app.py              Screen: headline panel, cockpit (sales and e-commerce switches) (analog clock of the simulated time, simulation id, start), START/STOP; Simulator tab (sliders, parameters, status); Counters tab (dashboard); Switch on / off tab; signature
│   │       ├── assets/
│   │       │   └── clock.css       Headline panel and analog clock styles, served by Dash
│   │       ├── operations.py       Switch on / off steps and the signature, shown on the app's third tab; standard library only
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
│           ├── app.py              Screen: filter area; Sales performance tab (KPI cards, trend, channel, geography and product bars with drill-down); Clienteling tab (client and store KPIs from the metric views); Ask Genie tab (chat with the Genie agent)
│           ├── bi.py               KPIs, live deltas, drill-down, chart series on GMT hours; standard library only
│           ├── dashboard_sql.py    Read-only, parameterized queries on silver, the metric views and the dimensions; standard library only
│           ├── genie_chat.py       Ask Genie tab: Genie Conversation API client and answer parsing; standard library only
│           ├── figures.py          Plotly charts: trend lines per macro region on GMT hours, horizontal bars stacked per date
│           ├── assets/
│           │   └── dashboard.css   Compact sizes and side margins (5–10% of the width), served by Dash
│           ├── sql_warehouse.py    Databricks SQL warehouse access: parallel queries, one connection per thread
│           ├── app.yaml            Start command and environment variables (warehouse, table names, refresh seconds)
│           └── requirements.txt    Pinned packages, installed by Databricks on deploy
├── resources/
│   ├── modeling.peoplecounter.pipeline.yml  The pipeline: catalog, schema, serverless, source files
│   ├── modeling.peoplecounter.job.yml       Continuous job that keeps the pipeline running (created paused)
│   └── modeling.metrics.job.yml             Job that creates or updates the metric views from src/metrics/ (run on demand)
├── src/
│   ├── pipelines/                  Pipeline source files only
│   │   ├── 00_check_tables.py      Pre-flight check that the input tables exist
│   │   ├── 01_bronze.py            Bronze streaming ingestion
│   │   ├── 02_silver.py            Parsing, validation, silver and quarantine tables
│   │   └── 03_sales.py             Sales: bronze, silver and quarantine transactions, foreign keys to the dimensions
│   ├── metrics/                    Unity Catalog metric view definitions, run by the job retail-metric-views
│   │   ├── client_metrics.sql      Client KPIs (test02_metric.client_metrics)
│   │   └── store_metrics.sql       Store KPIs, sales and traffic, with conversion (test02_metric.store_metrics)
│   └── sql/                        Scripts run by hand on the SQL warehouse, in number order
│       ├── 01_create_dim_store.sql                Setup: creates the test02_warehouse schema and the store dimension; idempotent
│       ├── 02_populate_dim_store.sql              Setup: loads 213 stores (200 physical, 13 e-commerce), macro regions, channels, the 2 flagships (idempotent MERGE)
│       ├── 03_validate_dim_store.sql              Check: store counts, channels, macro regions, keys, time zones
│       ├── 04_create_simulated_event_source.sql   Setup: creates the test02_streaming schema and the simulated source table
│       ├── 05_insert_simulated_events.sql         Load: merges 8 test events (5 valid, 3 invalid); idempotent
│       ├── 06_validate_simulated_event_source.sql Check: the source table's contents
│       ├── 07_validate_bronze.sql.dbquery.ipynb   Check: the bronze table's contents
│       ├── 08_create_dim_client.sql               Setup: creates the client dimension (natural key client_id)
│       ├── 09_populate_dim_client.sql             Setup: loads 100,000 clients, 500 per store per country (idempotent MERGE)
│       ├── 10_create_dim_product.sql              Setup: creates the product dimension (natural key product_id)
│       ├── 11_populate_dim_product.sql            Setup: loads 120 products, 20 per category, luxury price lists (idempotent MERGE; reprices existing products)
│       ├── 12_create_simulated_sales_source.sql   Setup: creates the simulated sales source table
│       ├── 13_validate_dim_client_product.sql     Check: client and product counts, keys, formats
│       ├── 14_drop_old_streaming_dimensions.sql   One-off: drops the old dimension copies from test02_streaming (doc/warehouse.md §5)
│       ├── 15_create_current_simulation_views.sql Setup: views on silver that keep only the latest simulation (doc/warehouse.md §6)
│       ├── 16_add_store_channel.sql               One-off: adds the channel column to an existing dim_store (doc/dataset.md §2.6)
│       └── 17_create_metric_schema.sql            Setup: creates the test02_metric schema for the metric views (doc/kpi_metrics.md)
├── tests/                          Tests of the bundles, code and docs; see doc/testing.md
│   ├── helpers.py                  Shared helpers for the tests
│   ├── test_project_consistency.py Tests of the bundle, pipeline code and docs
│   ├── test_dataset.py             Tests of the dataset rules in doc/dataset.md
│   ├── test_people_stream.py       Tests of the simulator app, its bundle and doc/people_stream.md
│   ├── test_sales.py               Tests of the sales simulator, clients, products and their docs
│   ├── test_sales_dashboard.py     Tests of the sales dashboard app, its bundle and doc/sales_dashboard.md
│   ├── test_kpi_metrics.py         Tests of the metric views, their deploy job and doc/kpi_glossary.md
│   ├── test_kpi_genie.py           Tests of the Genie agent bundle, its definition and doc/kpi_genie.md
│   └── run_tests.py                Notebook that runs all tests in Databricks
├── pyproject.toml, uv.lock         Local Python environment (Databricks Connect), managed by `databricks environments setup-local`
└── .gitignore
```

Only the files in `src/pipelines/` are pipeline source files, and the pipeline lists each one by name. The scripts in `src/sql/` are run by hand, in number order, on the SQL warehouse; never put them in `src/pipelines/`.

## 2. Working rules

**Databricks:**
- **Validate first:** run `bundle validate --strict` after every change to `databricks.yml`, `resources/` or `src/`.
- **Serverless only:** Free Edition has no classic clusters. Don't add cluster settings.
- **Never upload `.git/`:** the workspace copy is the Git folder; don't copy the local repo into the workspace with `import-dir`.
- **Table features:** a new column type that needs a Delta table feature (such as `TIMESTAMP_NTZ`) needs the feature in `table_properties`, then a full refresh of the tables that already exist.

**Tests:**
- **Run them before deploying:** after pulling a change into the Git folder, run `tests/run_tests` there, and deploy only if it passes. Agents run them on the PC before handing over a change.
- **Add a test with every change:** a new feature or data rule gets a test in `tests/` ([`testing.md`](testing.md)).

**Data:**
- **Synthetic only:** never add real customer, store or company data.

**Documentation:**
- **Levels:** level 0 is the executive brief, level 1 the architecture and the decisions, level 2 one page per topic, level 3 the reference pages (glossary, operations, development, testing). A higher level summarizes and links; the detail lives on one page only.
- **Same change:** update a page in the same change as whatever it describes. A new decision gets an entry in [`decisions.md`](decisions.md); a new page is listed in [`agents.md`](../agents.md) and in §1.

**Git:**
- **Branch:** work happens on `main`.
- **Flow:** the owner commits and pushes to GitHub first; then Databricks pulls the changes into the Git folder; then the bundle is deployed from there.
- **Pull first:** the repo can also be edited from the Databricks Git folder, so pull before committing.
- **Don't commit:** `.databricks/` (already in `.gitignore`), `.vscode/`, credentials, tokens or local environment files.

**Agents:**
- **Never commit or push — mandatory:** leave every change uncommitted in the working tree, so the owner can review it in VS Code's Source Control view. At the end of each task, list every file you added, changed or deleted, as links, so the owner can open them. The owner commits and pushes after reviewing. This applies even when a task seems to need a commit, such as pulling into the Databricks Git folder; say that the owner needs to commit and push first.
- **Ask first:** get the owner's confirmation before deploying, running or full-refreshing the pipeline.
- **Report honestly:** say what was run and checked, and what wasn't. Code that hasn't run in Databricks is untested.
