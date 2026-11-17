# Retail KPI Assistant: the Genie agent

Reference for the Genie agent that answers questions in natural language on the KPIs of the semantic layer: what it is for, what it reads, how it is built and deployed, and how it is checked. The KPIs themselves are defined in [`kpi_glossary.md`](kpi_glossary.md); why they are metric views, in [`kpi_metrics.md`](kpi_metrics.md).

## 1. Purpose and boundaries

| | |
|---|---|
| **What it does** | Answers executives' questions on the client and store sales KPIs of the retail simulation (revenue, total spent, transactions, average basket, items per basket, distinct clients, visitor and online share, people in and out, conversion), ranks and compares stores, clients, channels and regions, and explains what each KPI means and how it is calculated |
| **Audience** | Business executives: plain business language, SQL only when asked |
| **Default scope** | The **current simulation** (the latest `simulation_id`), unless the user names another one or asks for all simulations |
| **What it doesn't do** | Write anything: Genie only reads, with the permissions of the user who asks |
| **Where to use it** | In the workspace under **Genie**, or in the sales dashboard's **Ask Genie** tab ([`sales_dashboard.md`](sales_dashboard.md) §9), where the app asks it as its service principal |
| **Bundle** | `agents/kpi_genie/`, bundle `retail_kpi_genie_bundle`. Separate from the pipeline bundle and the two app bundles: deployed and run on its own |
| **Agent** | **Retail KPI Assistant**, a Genie space in `/Workspace/Users/<user>/genie`, under **Genie** in the workspace |
| **Code** | `agents/kpi_genie/src/kpi_genie.json` (the definition), `agents/kpi_genie/src/deploy_genie.py` (creates or updates the agent from it) |

## 2. What it reads

Seven sources, all read-only:

| Source | Why |
|---|---|
| `workspace.test02_metric.store_metrics` | The store KPIs, sales and traffic, with conversion: the governed answer to every store question |
| `workspace.test02_metric.client_metrics` | The client KPIs: the governed answer to every client question |
| `workspace.test02_warehouse.dim_store`, `dim_client`, `dim_product` | The dimensions: names, countries, channels, categories, prices |
| `workspace.test02_streaming.current_sales_transactions` | The sales lines of the current simulation, for details the metric views don't hold (e.g. the lines of one transaction) |
| `workspace.test02_streaming.current_people_counter_events` | The door events of the current simulation, for traffic details |

**KPIs come from the metric views.** Genie sees each KPI's description (the glossary, word for word), its synonyms and its formula there, so "What does Conversion mean?" and "Conversion by channel" are answered from the same governed definition. The raw facts and dimensions are attached for detail questions only; the agent's instructions tell it to use the metric views for KPIs.

## 3. How it is built

The definition `src/kpi_genie.json` holds the agent's title and description and its **serialized space** (version 2):

| Part | Content |
|---|---|
| **Description** | Purpose and scope, the first thing Genie and any supervising agent read |
| **Data sources** | The 7 sources of §2. On the categorical dimensions users name (channel, region, country, store name, category, client type) **entity matching** and **format assistance** are on; technical columns (`raw_event`, `source_…`, ingestion times) are hidden |
| **Join specs** | Sales lines and door events to the dimensions, on the natural keys (many to one) |
| **Filters** | **Current simulation**, one for each metric view: the simulation id in `current_simulation`. Synonyms: current simulation, current run, latest simulation |
| **Example SQL** | 7 checked query shapes: clients and spend by segment; top stores by revenue; conversion by channel; top clients by total spent; average basket of visitors vs locals; revenue by region and GMT hour; clients who bought in more than 3 stores (ranking on a measure, through a CTE) |
| **Text instructions** | Short, for what can't be said structurally: the audience, the current-simulation default, Revenue vs Total Spent, conversion and e-commerce, EUR and percentage formats, always naming the simulation |
| **Sample questions** | Shown in the Genie UI: what Conversion means; top 10 stores by revenue; conversion by channel; top clients by total spent; visitors' vs locals' basket |
| **Benchmarks** | 10 questions with checked SQL answers (§5) |

All IDs are fixed (derived from their content), so redeploying the same definition updates the agent rather than duplicating its parts.

## 4. Deployment

| Step | How |
|---|---|
| Before the first deploy | The metric views (`retail-metric-views`), the current-simulation views (`src/sql/15_…`) and the dimensions must exist |
| Check | From `agents/kpi_genie/`: `databricks bundle validate --strict -t dev --profile MPiunti` |
| Deploy | From `agents/kpi_genie/`: `databricks bundle deploy -t dev --profile MPiunti`; or, in the Git folder, open `agents/kpi_genie/` and use **Deployments** |
| Create or update the agent | `databricks bundle run deploy_kpi_genie -t dev --profile MPiunti`, or run the job `deploy-kpi-genie-dev` in Jobs & Pipelines. It finds the agent by title in its folder: updates it if it exists, creates it otherwise. Run it after every change to `kpi_genie.json` |
| Use it | Workspace → **Genie** → **Retail KPI Assistant**. The job prints its link |
| Who can ask | Whoever the space is shared with, with their own permissions on the 7 sources |
| Cost | It runs queries on the Serverless Starter Warehouse only when asked; no compute runs otherwise |

The job runs on serverless compute, with the Databricks SDK that every serverless environment provides.

## 5. Checked before deploy

Every example SQL and every benchmark answer was run read-only on the workspace on 16 November 2026, on the current simulation, and returned rows. For example:

| Benchmark question | Answer then |
|---|---|
| What is the conversion rate of each flagship store? | Milan Galleria Vittorio Emanuele 18.0%, New York Fifth Avenue 17.1% |
| What share of New York Fifth Avenue's revenue comes from visitors? | 70.3% |
| What share of client spending is made online? | 13.4% |

The benchmarks are questions a later **evaluation run** can score the agent on: Genie answers each question, and its result is compared with the checked SQL. Numbers move with every simulation, so the benchmarks keep the SQL, not the numbers.

The tests (`tests/test_kpi_genie.py`) check, before anything is deployed, that the definition follows the Genie rules (IDs, sort orders, limits), that every KPI and dimension its SQL names exists in the metric views, that every query defaults to the current simulation, and that the deploy script updates instead of duplicating.
