# nov26_stream

A Databricks learning project that ingests anonymous retail people-counter events through a streaming medallion pipeline (bronze → silver + quarantine). It is packaged as a Declarative Automation Bundle, `retail_people_counter_bundle`, and runs on a Databricks Free Edition workspace.

The events come from a simulated source table for now, so pipeline development doesn't depend on Event Hubs. All data is synthetic.

This page gives the general rules for anyone working on the project, people and AI agents alike. Read it before making changes, and update it in the same change as whatever it describes.

## Project layout

```
nov26_stream/
├── readme.md                       General rules (this page)
├── CLAUDE.md                       Entry point for Claude Code: loads this page
├── databricks.yml                  Bundle settings: name, variables, dev and prod targets
├── resources/
│   └── bronze.pipeline.yml         The pipeline: catalog, schema, serverless, source files
├── src/
│   ├── pipelines/
│   │   ├── 01_bronze.py            Pipeline source: bronze streaming ingestion
│   │   ├── 02_silver.py            Pipeline source: parsing, validation, silver and quarantine tables
│   │   ├── 04_create_simulated_event_source.sql   Setup: creates the simulated source table
│   │   ├── 05_insert_simulated_events.sql         Setup: inserts 8 test events (5 valid, 3 invalid)
│   │   └── 06_validate_simulated_event_source.sql Check: the source table's contents
│   └── sql/
│       ├── 01_create_dim_store.sql         Setup: creates the store dimension
│       ├── 02_populate_dim_store.sql       Setup: loads 200 stores (idempotent MERGE)
│       ├── 03_validate_dim_store.sql       Check: store counts, keys, time zones
│       └── 07_validate_bronze.sql.dbquery.ipynb  Check: the bronze table's contents
├── tests/                          Tests of the bundle, pipeline code and docs
│   ├── helpers.py                  Shared helpers for the tests
│   ├── test_project_consistency.py The tests
│   └── run_tests.py                Notebook that runs all tests in Databricks
├── pyproject.toml, uv.lock         Local Python environment (Databricks Connect), managed by `databricks environments setup-local`
└── .gitignore
```

Only `01_bronze.py` and `02_silver.py` are pipeline source files. The numbered `.sql` files are run by hand, in number order, on the SQL warehouse.

## Data flow

| Step | Object | Created by |
|---|---|---|
| Store dimension | `workspace.test02_streaming.dim_store` (200 stores, primary key `store_id`) | `src/sql/01_…` and `02_…`, by hand |
| Simulated source | `workspace.test02_streaming.simulated_event_source` (append-only, raw JSON) | `src/pipelines/04_…` and `05_…`, by hand |
| Bronze | `bronze_people_counter_events`: raw events plus `ingestion_timestamp` | Pipeline, `01_bronze.py` |
| Silver | `silver_people_counter_events`: parsed, typed and valid events, with the store's time zone | Pipeline, `02_silver.py` |
| Quarantine | `quarantine_people_counter_events`: invalid events with `rejection_reason`, `record_status` = `OPEN` | Pipeline, `02_silver.py` |

All pipeline tables are streaming tables in `workspace.test02_streaming`. The silver table has a primary key on `event_id` and a foreign key on `store_id` to `dim_store`.

`event_timestamp` is `TIMESTAMP_NTZ`: the sensor's local time, without time-zone conversion. Every table with a `TIMESTAMP_NTZ` column must set `"delta.feature.timestampNtz": "supported"` in its `table_properties`.

## Validation rules

Each event goes to silver if it passes every rule, and to quarantine otherwise. `rejection_reason` lists every failed rule, separated by `|`.

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
| **Catalog and schema** | `workspace.test02_streaming`, set by the bundle variables `catalog` and `schema`. The catalog is `workspace`, **not** `main`. |
| **Git folder** | `/Workspace/Users/michele.piunti@gmail.com/retail_people_counter_bundle`, linked to `github.com/MPiunti/nov26_stream`, branch `main` |
| **Bundle target** | `dev` (development mode, the default). `prod` deploys to `/Users/michele.piunti@gmail.com/.bundle/retail_people_counter_bundle/prod` and runs as the owner. |
| **Pipeline** | `retail_people_counter_bronze`, shown as `[dev michele_piunti] retail-people-counter-bronze-dev`. Serverless, triggered (not continuous). |

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
| Deploy | In the Git folder: **Deployments** (rocket) → `dev` → **Deploy**. Or `& $db bundle deploy -t dev --profile MPiunti`. |
| Run the pipeline | Pipeline UI → **Start**, or `& $db bundle run retail_people_counter_bronze -t dev --profile MPiunti` |
| Rebuild silver and quarantine | Pipeline UI → **Full refresh selection** on the two tables. Needed after a change to a table's schema or table features, because a normal update doesn't change an existing table's features. |
| Run the tests on a PC | `python -m unittest discover -s tests`. See [Tests](#tests). |
| Run the tests in Databricks | Open `tests/run_tests` in the Git folder and click **Run all** |

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
| `test_project_consistency.py` | Bundle: name, targets, includes, the files the pipeline points to, serverless only. Pipeline code: every table with a `TIMESTAMP_NTZ` column enables `timestampNtz`; table names use the bundle's catalog and schema; every rejection code is in [Validation rules](#validation-rules) and vice versa. Simulated events: the 8 events and their expected outcome. Docs: every test file is listed on this page, and `CLAUDE.md` loads this page and keeps the mandatory rules. |

**Running them:**
- **On a PC:** from the repo root, run `python -m unittest discover -s tests`.
- **In Databricks:** open `tests/run_tests` in the Git folder, attach serverless compute and click **Run all**. It fails if any test fails.

**What the tests don't cover:** Spark itself, the parsing results on real data, and the deployed pipeline. Those are checked by running the pipeline and the validation scripts in `src/`.
