# Decision log: why the solution is built this way

The architecture decisions behind the solution, one entry each: the context, the decision, the alternatives we weighed, and what follows from it. Each entry is short and links the page with the detail; the overall picture is in [`architecture.md`](architecture.md), the executive view in [`executive_brief.md`](executive_brief.md). Add an entry with every new decision, and mark replaced ones instead of deleting them.

| # | Decision | Status | Detail |
|---|---|---|---|
| D1 | A streaming medallion pipeline on Lakeflow Declarative Pipelines, serverless | Adopted | [`pipeline.md`](pipeline.md) |
| D2 | A continuous job keeps a triggered pipeline running, with 2-second micro-batches | Adopted | [`pipeline.md`](pipeline.md) §3 |
| D3 | Three engines decoupled by data contracts, never by calls | Adopted | [`architecture.md`](architecture.md) §3 |
| D4 | A simulation id instead of a full refresh at every START | Adopted | [`warehouse.md`](warehouse.md) §6 |
| D5 | Quarantine, never drop: every rejected row kept with all its reasons | Adopted | [`pipeline.md`](pipeline.md) §2 |
| D6 | Natural business keys, declared keys, and one GMT timeline next to local time | Adopted | [`warehouse.md`](warehouse.md) |
| D7 | KPIs as Unity Catalog metric views, computed live | Adopted, 16 November 2026 | [`kpi_metrics.md`](kpi_metrics.md) §1–2 |
| D8 | Metric views created once, then altered, so permissions survive | Adopted, 16 November 2026 | [`kpi_metrics.md`](kpi_metrics.md) §8 |
| D9 | A Genie agent on the metric views, defined as code, with benchmarks | Adopted | [`kpi_genie.md`](kpi_genie.md) |
| D10 | Both apps on Databricks Apps, each with least-privilege permissions declared in its bundle | Adopted | [`sales_dashboard.md`](sales_dashboard.md), [`people_stream.md`](people_stream.md) |
| D11 | Contract tests that need no Databricks connection, and docs kept in step by tests | Adopted | [`testing.md`](testing.md) |
| D12 | From four bundles and hand-run scripts to one bundle per environment, deployed by CI | Proposed, 18 November 2026 | [`operations.md`](operations.md) §3 |
| D13 | Synthetic data only | Adopted | [`dataset.md`](dataset.md) |

## D1. A streaming medallion pipeline on Lakeflow Declarative Pipelines

- **Context:** footfall and sales must be usable seconds after they happen, validated, with nothing lost.
- **Decision:** one declarative pipeline, serverless: bronze keeps every message as received, silver the parsed and valid rows, quarantine the invalid ones. Streaming tables throughout; a pre-flight check fails an update before anything is loaded if an input table is missing or empty.
- **Alternatives:** hand-written Structured Streaming jobs (more code to own: checkpoints, retries, table management); nightly batch (the problem we are solving).
- **Consequences:** the pipeline declares *what* to compute and Databricks runs it: dependencies, checkpoints, retries, compute. Serverless means no cluster to size or keep warm.

## D2. A continuous job keeps a triggered pipeline running

- **Context:** the pipeline's own `continuous` setting is deprecated, and the pipeline must keep running between simulations without anyone starting it.
- **Decision:** the pipeline is triggered; a continuous job keeps one update running and starts a new one if it ends or fails. Micro-batches every 2 seconds per table (`pipelines.trigger.interval`). The job never full-refreshes and is created paused.
- **Alternatives:** a scheduled job every minute (a minute of latency); the deprecated continuous pipeline.
- **Consequences:** one switch for the whole data flow: resume for a session, pause to stop all compute. Today each micro-batch takes 4 to 6 seconds, which is the latency floor ([`architecture.md`](architecture.md) §5).

## D3. Three engines decoupled by data contracts

- **Context:** the simulator stands in for real store sensors and tills, and must be replaceable by an event broker; the BI must be replaceable by any tool.
- **Decision:** the simulation engine, the pipeline and the BI engine never call each other. They meet only at tables and views with an agreed shape: the source tables in an event-broker envelope (topic, partition, offset), the simulation id, the current-simulation views, the dimensions.
- **Alternatives:** the simulator triggering the pipeline and notifying the dashboard (coupled deploys and failures).
- **Consequences:** each part can be started, stopped, redeployed or replaced alone; a failure stays in its part; permissions follow the contracts (each app reaches only its tables).

## D4. A simulation id instead of a full refresh at every START

- **Context:** every START empties the source tables. A full refresh to follow it would stop the pipeline, and the dashboard would mix old and new simulations.
- **Decision:** every START gets a new, sortable `simulation_id` (its UTC start time) in every event and sale. Bronze reads its sources with `skipChangeCommits`, so the deletes don't stop the stream. Views keep only the latest simulation.
- **Alternatives:** a full refresh at every START (minutes of downtime and an operator); one table per simulation (schema sprawl).
- **Consequences:** a START needs nobody and nothing else; earlier simulations stay for analysis until an occasional housekeeping refresh.

## D5. Quarantine, never drop

- **Context:** invalid data is information: a broken sensor, an unknown store, a bad till.
- **Decision:** a row that fails any rule goes to a quarantine table with every failed rule in `rejection_reason` and `record_status` = `OPEN`: 8 rules for people events, 11 for sales.
- **Alternatives:** pipeline expectations that drop rows (the reason is lost); failing the update (one bad row stops everyone).
- **Consequences:** silver holds only valid rows, and nothing is lost; data stewards can work the quarantine like a queue.

## D6. Natural keys, declared keys, one GMT timeline

- **Context:** sales, door events, clients, products and stores come from different systems and must join the same way everywhere, across 13 countries and their time zones.
- **Decision:** the business keys (`store_id`, `client_id`, `product_id`, `transaction_id`) are the keys; silver declares its primary and foreign keys to the dimensions in Unity Catalog. Every event keeps the store's local time, and sales add GMT for one worldwide timeline.
- **Alternatives:** surrogate keys (a lookup on every load, and IDs nobody recognizes in a question to Genie).
- **Consequences:** the keys are documented in the catalog, and Genie and the metric views join on them; "sales at 18:00" means local time, "the last hour worldwide" means GMT.

## D7. KPIs as Unity Catalog metric views

- **Context:** the same KPIs are needed by the dashboard, by Genie and later by AI/BI dashboards, and silver changes every few seconds.
- **Decision:** KPIs are defined once, as metric views in `test02_metric`, computed live from silver; each measure carries its functional description, which the glossary repeats word for word.
- **Alternatives:** a KPI table refreshed after every silver update; the comparison and the feasibility check are in [`kpi_metrics.md`](kpi_metrics.md) §2–3.
- **Consequences:** one version of the truth, as fresh as silver, with no extra pipeline; metric views can be materialized later without changing their consumers.

## D8. Metric views created once, then altered

- **Context:** re-creating a view drops its grants; the dashboard lost its access that way once.
- **Decision:** each definition file runs `CREATE VIEW IF NOT EXISTS`, then `ALTER VIEW … AS` with the full definition, from a bundle job.
- **Alternatives:** `CREATE OR REPLACE` with grants re-applied by hand (one forgotten step breaks the dashboard).
- **Consequences:** redeploying a KPI never breaks a consumer. The current-simulation views (`15_…`) don't follow this rule yet; D12 brings them in line.

## D9. A Genie agent on the metric views, defined as code

- **Context:** executives ask questions no dashboard anticipated, and the answer must use the governed KPIs, not a new formula.
- **Decision:** the agent Retail KPI Assistant reads the two metric views first, with the dimensions and current-simulation facts for detail. Its definition (sources, instructions, example SQL, 10 benchmark questions with checked answers) is versioned in Git and deployed by a job that updates it in place.
- **Alternatives:** Genie on the raw silver tables (each answer reinvents the KPI); an agent configured only in the UI (not reviewable, not reproducible).
- **Consequences:** "What does Conversion mean?" and "Conversion by channel" use the same definition as the dashboard. Genie answers with the asking user's own permissions.

## D10. Apps on Databricks Apps, least privilege by construction

- **Context:** the simulator and the dashboard need a UI, compute and data access, and must not reach each other's data.
- **Decision:** both are Python (Dash) apps on Databricks Apps, each running as its own service principal, with its permissions declared in its bundle: the simulator may write only the two source tables, the dashboard may only read the views, the metric views and the dimensions, and run the Genie agent. Both go through the SQL warehouse.
- **Alternatives:** apps hosted outside Databricks (separate identity, network and secrets to manage).
- **Consequences:** no credentials in the code; access is reviewed in the bundle, granted on deploy, and visible in Unity Catalog.

## D11. Contract tests, and docs kept in step by tests

- **Context:** a change to one part (a rule, a KPI, a table name) must not silently break another, or the docs.
- **Decision:** tests that read only the project's files and need no Databricks connection check that the bundles, pipeline code, SQL scripts, apps, the Genie definition and the docs agree.
- **Alternatives:** testing only on the workspace (slow, and only after deploying).
- **Consequences:** fast feedback before any deploy; the docs can be trusted in a presentation. They don't test Spark itself; layers 2 and 3 of [`testing.md`](testing.md) §1 are planned.

## D12. From four bundles to one bundle per environment, deployed by CI (proposed)

- **Context:** today four bundles are deployed one by one, and in an order, plus SQL scripts run by hand. Deploys from the workspace Git folder upload no app files, and deploying an out-of-date folder rolled back permissions once ([`operations.md`](operations.md) §3). `bundle destroy` can't remove the Genie agent, the schemas or the script-made tables, and schema names are written into the code, so a prod target would share dev's tables.
- **Proposed decision:**
  - One bundle holds everything: the schemas with their grants, a setup job (tables, seed data, views, metric views, data checks), the pipeline, both apps, and the Genie agent as a bundle resource. The Databricks CLI now supports `genie_spaces` and `schemas` resources.
  - Schema names become settings per environment.
  - A CI workflow runs the tests, validates, deploys to a test environment, checks it, and promotes to prod as a service principal.
- **Alternatives:** keep four bundles with a deploy script (the order is still not guaranteed).
- **Consequences:** one deploy installs or refreshes the whole solution, and one destroy removes it, protected data aside. It is planned after the presentation, so the demo runs on the version already proven.

## D13. Synthetic data only

- **Context:** a demonstration that is shown and shared widely.
- **Decision:** stores, clients, products, footfall and sales are all generated; no real customer, store or company data is ever added.
- **Consequences:** the solution can be shown anywhere; with real data, Unity Catalog row filters and column masks would protect client details ([`executive_brief.md`](executive_brief.md) §7).
