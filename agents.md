# agents.md

Entry point for AI agents working on this project. Start here, then read the pages that match your task.

## Documentation, by level

| Level | Topic | Page | Read it before |
|---|---|---|---|
| — | **Front door** | [`readme.md`](readme.md) | Anything: what the solution is, who reads what, the four bundles, quick start |
| 0 | **Executive brief** | [`doc/executive_brief.md`](doc/executive_brief.md) | Preparing a pitch or presentation: the retail problem, why Databricks, business value, proof points, roadmap, CTO questions, demo script. Keep its figures in step with `architecture.md` |
| 1 | **Solution overview** | [`doc/architecture.md`](doc/architecture.md) | Explaining or presenting the solution: the three engines (simulation, pipeline, BI), the data contracts that decouple them, the Databricks services used, what happens at START, measured speed, the business numbers, limits and next steps. Keep its figures in step with the detailed pages |
| 1 | **Decision log** | [`doc/decisions.md`](doc/decisions.md) | Making or questioning an architecture choice: each decision with its context, alternatives and consequences. Add an entry with every new decision |
| 2 | **Pipeline** | [`doc/pipeline.md`](doc/pipeline.md) | Changing the pipeline: the data flow, the people-counter validation rules, running the pipeline and its continuous job |
| 2 | **Data warehouse** | [`doc/warehouse.md`](doc/warehouse.md) | Touching schemas, tables or keys: `test02_warehouse` (dimensions) vs `test02_streaming` (streaming tables), natural keys, loading order. Start here for any data change |
| 2 | **Dataset** | [`doc/dataset.md`](doc/dataset.md) | Touching stores, events or volumes: the store dimension and its distribution, sales channels (RETAIL, FLAGSHIP, ECOM), macro regions, how people-counter events are streamed in, opening hours, the `N_AVG_PEOPLE_*` parameters |
| 2 | **Sales** | [`doc/sales.md`](doc/sales.md) | Touching the sales simulator, PURCHASE_PROB, transactions, the sales source table, or the pipeline's sales tables and their validation rules (`03_sales.py`) |
| 2 | **Clients** | [`doc/client.md`](doc/client.md) | Touching `dim_client` or how buyers are chosen |
| 2 | **Products** | [`doc/product.md`](doc/product.md) | Touching `dim_product`, categories or prices |
| 2 | **KPIs and metric views** | [`doc/kpi_metrics.md`](doc/kpi_metrics.md) | Defining or changing a KPI, the metric views in `test02_metric`, or the Clienteling tab: the decision for metric views and the comparison behind it, design rules, the KPI list with functional descriptions |
| 2 | **Genie agent** | [`doc/kpi_genie.md`](doc/kpi_genie.md) | Touching the Genie agent Retail KPI Assistant or its bundle (`agents/kpi_genie/`): its sources, definition (`kpi_genie.json`), example SQL, benchmarks, deployment |
| 2 | **People stream app** | [`doc/people_stream.md`](doc/people_stream.md) | Touching the simulator app or its bundle (`apps/people_stream/`): screen, time model (240 s = 24 h), per-store streams, event shape, writes to the source table, volumes, deployment, switching on and off |
| 2 | **Sales dashboard app** | [`doc/sales_dashboard.md`](doc/sales_dashboard.md) | Touching the BI app or its bundle (`apps/sales_dashboard/`): screen, KPIs, drill-down, refresh, queries, permissions |
| 3 | **KPI glossary** | [`doc/kpi_glossary.md`](doc/kpi_glossary.md) | Reading or changing a KPI's definition: every KPI and dimension of the metric views, with its functional description (word for word the metric view comment) and its calculation. Change it together with `src/metrics/*.sql` |
| 3 | **Operations** | [`doc/operations.md`](doc/operations.md) | Deploying or running anything: the workspace, the CLI, the deployment order and the rules learned, everyday tasks |
| 3 | **Development** | [`doc/development.md`](doc/development.md) | Any change: the project layout (every file) and the working rules |
| 3 | **Testing** | [`doc/testing.md`](doc/testing.md) | Adding or changing a test: the four-layer strategy and what each test file checks |

Every page in `doc/` is listed in this table. Update a page in the same change as whatever it describes; describe each rule on one page only and link to it elsewhere.

## Mandatory rules

- **Tests:** run `python -m unittest discover -s tests` before handing over a change, and add a test for every new feature or data rule.
- **Never commit or push.** Leave all changes uncommitted for the owner to review. End every task with a list of the files you added, changed or deleted, as links.
- **Ask first** before deploying, running or full-refreshing the pipeline, or running SQL that writes data.

Details: "Working rules" in [`doc/development.md`](doc/development.md) and [`doc/testing.md`](doc/testing.md).
