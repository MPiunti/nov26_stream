# Operations: workspace, tools, deployment, everyday tasks

Reference for running the solution in its Databricks workspace: where everything is, the tools on the PC, how to deploy each part and in which order, and the everyday tasks. How the pipeline runs is in [`pipeline.md`](pipeline.md) §3; switching the whole solution on and off, step by step, in [`people_stream.md`](people_stream.md) §10. The values below are those of the demo environment; the planned move to one bundle per environment is in [`decisions.md`](decisions.md) D12.

## 1. The Databricks workspace

| | |
|---|---|
| **Workspace** | `https://dbc-06fb0002-68c5.cloud.databricks.com` (Free Edition) |
| **CLI profile** | `MPiunti` |
| **Catalog and schemas** | Catalog `workspace` (**not** `main`). `test02_warehouse` for the dimensions (bundle variable `warehouse_schema`), `test02_streaming` for the sources and pipeline tables (bundle variable `schema`), `test02_metric` for the metric views. See [`warehouse.md`](warehouse.md). |
| **Git folder** | `/Workspace/Users/michele.piunti@gmail.com/retail_people_counter_bundle`, linked to `github.com/MPiunti/nov26_stream`, branch `main` |
| **Bundle target** | `dev` (development mode, the default). `prod` deploys to `/Users/michele.piunti@gmail.com/.bundle/retail_people_counter_bundle/prod` and runs as the owner. |
| **Pipeline** | `retail_people_counter_bronze`, shown as `[dev michele_piunti] retail-people-counter-bronze-dev`. Serverless, triggered: on its own, each run processes what's new and stops. Don't set `continuous` on the pipeline (deprecated); it runs continuously through the job below. |
| **Continuous job** | `retail_people_counter_continuous`, shown as `[dev michele_piunti] retail-simulator`, under **Jobs & Pipelines**. The clock of the pipeline: while resumed, it keeps one pipeline update running, which processes new source rows in micro-batches every 2 seconds per table (`pipelines.trigger.interval`); if that update ends or fails, the job starts a new one. It never full-refreshes. Created **paused**; development mode pauses it again on every deploy. |
| **App** | `people-stream-michele-piunti`, under **Compute → Apps**, from the `retail_people_stream_bundle` bundle in `apps/people_stream/`. Writes through the Serverless Starter Warehouse. |
| **Dashboard app** | `sales-bi-michele-piunti`, under **Compute → Apps**, from the `retail_sales_dashboard_bundle` bundle in `apps/sales_dashboard/`. Reads through the Serverless Starter Warehouse, every 5 seconds while a page is open. |
| **Genie agent** | **Retail KPI Assistant**, under **Genie**, in `/Workspace/Users/michele.piunti@gmail.com/genie`, from the `retail_kpi_genie_bundle` bundle in `agents/kpi_genie/`, created or updated by the job `deploy-kpi-genie-dev`. Queries the Serverless Starter Warehouse only when asked. |

## 2. Tools

- **Databricks CLI:** `databricks` isn't on the `PATH`. Use the copy installed with the Databricks VS Code extension:
  ```powershell
  $db = "$env:USERPROFILE\.vscode\extensions\databricks.databricks-2.23.1-win32-x64\bin\databricks.exe"
  & $db bundle validate --strict -t dev --profile MPiunti
  ```
  The folder name changes when the extension updates; look for `databricks.exe` under `%USERPROFILE%\.vscode\extensions\databricks.databricks-*`. In Git Bash, set `MSYS_NO_PATHCONV=1` before passing workspace paths such as `/Users/...`.
- **Python:** Python 3.13, without PyYAML, pandas or pyspark. The tests use only the standard library.

## 3. Deploying

Today the solution is four bundles, deployed one by one, plus SQL scripts run by hand ([`decisions.md`](decisions.md) D12 records why, and the move to one bundle).

**On a new workspace, in this order:**

| # | What | How |
|---|---|---|
| 1 | Schemas, dimensions and source tables | `src/sql/01_…`, `02_…`, `04_…`, `08_…` to `12_…` and `17_…`, by hand on the SQL warehouse, in number order |
| 2 | The pipeline and its jobs | From the repo root: `& $db bundle deploy -t dev --profile MPiunti` |
| 3 | Silver tables | Run the pipeline once ([`pipeline.md`](pipeline.md) §3), so the silver tables exist |
| 4 | Current-simulation views | `src/sql/15_create_current_simulation_views.sql`, once |
| 5 | Metric views | `& $db bundle run retail_metric_views -t dev --profile MPiunti` |
| 6 | Genie agent | From `agents/kpi_genie/`: `bundle deploy`, then `bundle run deploy_kpi_genie`; set the dashboard bundle's `genie_space_id` to the agent's id if it is new |
| 7 | The two apps | From `apps/people_stream/` and `apps/sales_dashboard/`: `bundle deploy`, then `bundle run people_stream` / `bundle run sales_dashboard` |

**After a pull,** redeploy every bundle whose files changed, in the same order (steps 2, 5, 6, 7).

**Rules learned the hard way:**

| Rule | Why |
|---|---|
| **Deploy the apps from the PC** | A deploy from the Git folder's Deployments panel is source-linked and uploads no files: the app, restarted from Compute → Apps, keeps the files of the last PC deploy, an older version |
| **Pull the Git folder before deploying from it** | Deploying an older commit rolls the resources back to that commit, permissions included: the sales dashboard once lost its access to the Genie agent that way |
| **Don't re-run `15_…`** | Re-creating the views drops the dashboard's permission to read them; the metric views avoid this with `CREATE … IF NOT EXISTS` and `ALTER` ([`kpi_metrics.md`](kpi_metrics.md) §8) |
| **Validate first** | `bundle validate --strict` after every change to a `databricks.yml`, `resources/` or `src/` |
| **Ask the owner first** | Before deploying, running or full-refreshing the pipeline ([`development.md`](development.md) §2) |

## 4. Everyday tasks

| Task | How (with `$db` as above) |
|---|---|
| Check the bundle | `& $db bundle validate --strict -t dev --profile MPiunti` |
| Get the latest code into Databricks | Owner pushes to `main`, then in the Git folder: **Pull** (or `& $db repos update <repo-id> --branch main --profile MPiunti`) |
| Deploy the pipeline | In the Git folder: **Deployments** (rocket) → `dev` → **Deploy**. Or `& $db bundle deploy -t dev --profile MPiunti`, from the repo root. |
| Deploy and start the app | From `apps/people_stream/`: `& $db bundle deploy -t dev --profile MPiunti`, then `& $db bundle run people_stream -t dev --profile MPiunti`. Run `src/sql/01_…`, `02_…`, `04_…` and, for sales, `08_…` to `12_…` first. See [`people_stream.md`](people_stream.md) §9. |
| Create or update the Genie agent | From `agents/kpi_genie/`: `& $db bundle deploy -t dev --profile MPiunti`, then `& $db bundle run deploy_kpi_genie -t dev --profile MPiunti`. See [`kpi_genie.md`](kpi_genie.md) §4 |
| Deploy and start the dashboard | From `apps/sales_dashboard/`, on the PC: `& $db bundle deploy -t dev --profile MPiunti`, then `& $db bundle run sales_dashboard -t dev --profile MPiunti`. The pipeline must have run once with `03_sales.py`, so the silver tables exist. See [`sales_dashboard.md`](sales_dashboard.md) §7. |
| Run the pipeline | Normally the continuous job runs it: **Resume** the job. By hand, with the job paused: Pipeline UI → **Run pipeline**, or `& $db bundle run retail_people_counter_bronze -t dev --profile MPiunti`; it processes what's new and stops |
| Switch everything on or off by hand | The people-stream app's **Switch on / off** tab, or [`people_stream.md`](people_stream.md) §10 |
| Follow the app continuously | **Resume** the continuous job, then START the app as often as you like; see [`pipeline.md`](pipeline.md) §3 |
| Create or update the metric views | After a change to `src/metrics/`: deploy the pipeline bundle, then `& $db bundle run retail_metric_views -t dev --profile MPiunti` (or run the job `retail-metric-views` in Jobs & Pipelines) |
| Create the current-simulation views | Run `src/sql/15_create_current_simulation_views.sql` once, after the pipeline has created the silver tables |
| Drop old simulations | With the job paused and no simulation running: **Run pipeline with full table refresh**, or add `--full-refresh-all`. See [`pipeline.md`](pipeline.md) §3 |
| Rebuild silver and quarantine | Pipeline UI → **Full refresh selection** on the two tables. Needed after a change to a table's schema or table features, because a normal update doesn't change an existing table's features. |
| Run the tests | On a PC: `python -m unittest discover -s tests`; in Databricks: open `tests/run_tests` in the Git folder and click **Run all**. See [`testing.md`](testing.md) |
