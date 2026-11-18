# nov26_stream: the real-time retailer on Databricks

A retail group with 200 stores in 13 countries, an e-commerce store in each country and 100,000 clients sees footfall and sales **while they happen**. Door events and sales stream through a medallion pipeline (bronze → silver + quarantine). The KPIs are defined once, as Unity Catalog metric views. They are served live in a BI app and to a Genie agent that answers questions in plain language. Everything runs on the Databricks Data Intelligence Platform, serverless, deployed as code from [github.com/MPiunti/nov26_stream](https://github.com/MPiunti/nov26_stream). All data is synthetic.

## Start here

| You are | Read | It tells you |
|---|---|---|
| **An executive or CTO** | [`doc/executive_brief.md`](doc/executive_brief.md) | The retail problem, why Databricks, the business value, the roadmap, the questions to expect, the ten-minute demo |
| **An architect** | [`doc/architecture.md`](doc/architecture.md), then [`doc/decisions.md`](doc/decisions.md) | The engines, how they are decoupled, the Databricks services used, speed and volumes; why each choice was made |
| **A KPI owner or analyst** | [`doc/kpi_glossary.md`](doc/kpi_glossary.md), [`doc/kpi_metrics.md`](doc/kpi_metrics.md) | What each KPI means and how it is calculated; why KPIs are metric views |
| **An engineer** | [`doc/development.md`](doc/development.md), [`doc/operations.md`](doc/operations.md), [`doc/testing.md`](doc/testing.md) | The layout and working rules; the workspace, deployment and everyday tasks; the tests |
| **An AI agent** | [`agents.md`](agents.md) | The index of every page, and the mandatory rules |

## The documentation, by level

| Level | For | Pages |
|---|---|---|
| **0. Executive** | Decision makers | [`executive_brief.md`](doc/executive_brief.md) |
| **1. Solution** | Architects | [`architecture.md`](doc/architecture.md), [`decisions.md`](doc/decisions.md) |
| **2. Topics** | Designers and builders | Data: [`pipeline.md`](doc/pipeline.md), [`warehouse.md`](doc/warehouse.md), [`dataset.md`](doc/dataset.md), [`sales.md`](doc/sales.md), [`client.md`](doc/client.md), [`product.md`](doc/product.md). KPIs and AI: [`kpi_metrics.md`](doc/kpi_metrics.md), [`kpi_genie.md`](doc/kpi_genie.md). Apps: [`people_stream.md`](doc/people_stream.md), [`sales_dashboard.md`](doc/sales_dashboard.md) |
| **3. Reference** | Everyone who runs or changes it | [`kpi_glossary.md`](doc/kpi_glossary.md), [`operations.md`](doc/operations.md), [`development.md`](doc/development.md), [`testing.md`](doc/testing.md) |

Each level summarizes the one below it and links to it; each rule is described on one page only.

## The solution in four bundles

| Bundle | Folder | Contents |
|---|---|---|
| `retail_people_counter_bundle` | repo root | The pipeline, its continuous job, and the job that deploys the metric views; see [`doc/pipeline.md`](doc/pipeline.md) |
| `retail_people_stream_bundle` | `apps/people_stream/` | The simulation engine: the people-stream simulator app and its sales simulator, which feed the two source tables; see [`doc/people_stream.md`](doc/people_stream.md) and [`doc/sales.md`](doc/sales.md) |
| `retail_sales_dashboard_bundle` | `apps/sales_dashboard/` | The BI engine: a read-only, live sales and footfall dashboard with drill-down, a Clienteling tab on the metric views and an Ask Genie tab; see [`doc/sales_dashboard.md`](doc/sales_dashboard.md) |
| `retail_kpi_genie_bundle` | `agents/kpi_genie/` | The Genie agent **Retail KPI Assistant**: natural-language questions on the KPIs; see [`doc/kpi_genie.md`](doc/kpi_genie.md) |

The move to one bundle per environment, deployed by CI, is proposed in [`doc/decisions.md`](doc/decisions.md) D12.

## Quick start

| # | Do | Where |
|---|---|---|
| 1 | Run the tests: `python -m unittest discover -s tests` | [`doc/testing.md`](doc/testing.md) |
| 2 | Deploy, on a new workspace in the given order | [`doc/operations.md`](doc/operations.md) §3 |
| 3 | Switch on: resume the continuous job, start both apps, press START | [`doc/people_stream.md`](doc/people_stream.md) §10 |
| 4 | Watch the dashboard, ask Genie | [`doc/sales_dashboard.md`](doc/sales_dashboard.md) |
| 5 | Switch off: STOP, pause the job, stop the apps | [`doc/people_stream.md`](doc/people_stream.md) §10 |

## Rules in one line each

- **Synthetic data only;** serverless only; validate every bundle change with `bundle validate --strict`.
- **Every change brings its test, and updates its page** in the same change.
- **Agents never commit or push,** and ask before deploying or running anything.

The full rules are in [`doc/development.md`](doc/development.md) §2.
