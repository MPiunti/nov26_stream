# Solution overview: how it works

The whole solution on one page: what it does, its three independent parts, how they are decoupled, the Databricks services it runs on, and how fast data moves through it. It is level 1 of the documentation: the executive view is in [`executive_brief.md`](executive_brief.md), the reasons behind each choice in [`decisions.md`](decisions.md), and the detailed pages are linked from each section and listed in [`agents.md`](../agents.md).

## 1. In short

A retail group with **200 stores** in Europe, the Americas and Asia, and an **e-commerce store in each of its 13 countries**, wants to see footfall and sales **while they happen**. This solution shows how, end to end, on Databricks:

- A **simulation engine** plays the stores' day: people entering and leaving, and what they buy.
- A **streaming data pipeline** checks every event and sale and stores the valid ones, seconds after they happen.
- A **BI engine**, the sales dashboard, shows value, quantity, average price and people in, live, with drill-down by geography and product.

On top of the data, a **semantic layer** of Unity Catalog metric views defines every KPI once; the dashboard's Clienteling tab and the **Genie agent**, which answers questions in plain language, both read it.

The three parts are **decoupled**: each can be started, stopped, redeployed or replaced without touching the others. All data is synthetic.

## 2. The picture

```
 SIMULATION ENGINE              DATA PIPELINE                    SEMANTIC LAYER           BI ENGINE AND AI
 people-stream app              continuous job + pipeline        views in Unity Catalog   dashboard app, Genie

 START ─▶ people events ─▶ source ─▶ bronze ─▶ silver ──┬─▶ current-simulation ───▶ KPI cards, trend lines,
          sales        ─▶ tables    (raw)     (valid)   │   views                    drill-down bars
                           append-             quarantine├─▶ metric views ─────────▶ Clienteling tab
                           only                (invalid) │   client_metrics   └────▶ Genie: questions in
                                                         │   store_metrics           plain language
 stores, clients, products (dimensions) ─────────────────┴─────────────────────────▶ names, filters

 writes: source tables only     reads sources, writes             defines, stores nothing  reads only
                                bronze, silver, quarantine
```

| Part | What it is | Its job | Detail |
|---|---|---|---|
| **Simulation engine** | The people-stream app | Generates people-counter events for the 200 physical stores, the sales they lead to, and the online sales of the 13 e-commerce stores, and writes them to two source tables, as an event broker would deliver them | [`people_stream.md`](people_stream.md), [`sales.md`](sales.md) |
| **Data pipeline** | A streaming pipeline kept running by a continuous job | Bronze keeps every message as received; silver keeps the parsed, typed, valid ones; quarantine keeps the invalid ones with the reason | [`pipeline.md`](pipeline.md), [`warehouse.md`](warehouse.md) |
| **Semantic layer** | Two Unity Catalog metric views, `client_metrics` and `store_metrics` | Defines every KPI once, with its business description, computed live from silver for any slice | [`kpi_metrics.md`](kpi_metrics.md), [`kpi_glossary.md`](kpi_glossary.md) |
| **Genie agent** | Retail KPI Assistant | Answers executives' questions in natural language on the KPIs of the metric views, and explains each KPI's definition; available under Genie and in the dashboard's Ask Genie tab | [`kpi_genie.md`](kpi_genie.md) |
| **BI engine** | The sales dashboard app | Self-service sales and footfall analysis, refreshed every 5 seconds, with filters and drill-down | [`sales_dashboard.md`](sales_dashboard.md) |

**The Databricks services it runs on:**

| Service | Used for | How it is set up |
|---|---|---|
| **Lakeflow Declarative Pipelines** | The streaming pipeline: bronze, silver, quarantine for people events and sales | Serverless, triggered, kept running by a continuous Lakeflow job; micro-batches every 2 seconds |
| **Delta Lake** | Every table: sources, streaming tables, dimensions | Open format; liquid clustering by `simulation_id` on silver |
| **Unity Catalog** | Governance: three schemas, declared primary and foreign keys, grants per app, lineage, the metric views | Catalog `workspace`; schemas `test02_warehouse`, `test02_streaming`, `test02_metric` ([`warehouse.md`](warehouse.md)) |
| **Unity Catalog metric views** | The semantic layer: every KPI defined once | YAML definitions in Git, deployed by a SQL job ([`kpi_metrics.md`](kpi_metrics.md)) |
| **Databricks SQL** | Every query and write of the apps, and the metric view deployment | The Serverless Starter Warehouse: starts on the first query, stops when idle |
| **Databricks Apps** | The simulator and the dashboard | Python (Dash), each running as its own service principal with only its permissions |
| **Genie** | Natural-language questions on the KPIs | The Retail KPI Assistant, defined as code with 10 benchmark questions ([`kpi_genie.md`](kpi_genie.md)) |
| **Declarative Automation Bundles** | Deploying everything from Git | Four bundles today, one proposed ([`decisions.md`](decisions.md) D12) |

## 3. How the engines are decoupled

The simulation engine and the BI engine never talk to each other, and neither talks to the pipeline. They meet only at **data contracts**: tables and views with an agreed shape.

| Contract | Between | What is agreed |
|---|---|---|
| **Source tables** (`simulated_event_source`, `simulated_sales_source`) | Simulation engine → pipeline | Append-only messages in an event-broker envelope (topic, partition, offset, timestamp) with a JSON payload. The pipeline doesn't know or care who writes them |
| **Simulation id** (`simulation_id`) | Simulation engine → everything downstream | Every START gets a new id, its UTC start time, written into every event and sale. A later START always has a higher id |
| **Current-simulation views** (`current_people_counter_events`, `current_sales_transactions`) | Pipeline → BI engine | The valid events and sales of the latest simulation only. The dashboard reads nothing else, apart from the dimensions |
| **Dimensions** (`dim_store`, `dim_client`, `dim_product`) | Master data → all three | Stores, clients and products with their natural business keys |

What this decoupling means in practice:

| Property | How it shows |
|---|---|
| **No calls between parts** | The simulator never starts the pipeline or notifies the dashboard. Pressing START only writes data; everything downstream reacts to the data |
| **Least privilege, by construction** | The simulator may write only the two source tables. The dashboard has `SELECT` on the two views and two dimensions, and nothing else: not even the silver tables. Neither app has any permission on the other's objects |
| **Independent deployment** | Four separate bundles: pipeline, simulator, dashboard, Genie agent. Deploying or stopping one never changes the others |
| **Replaceable ends** | The simulator can be replaced by a real event broker (Azure Event Hubs is the intended one) delivering the same messages; the dashboard by any BI tool that can read the views. The pipeline in the middle doesn't change |
| **Independent failure** | If the dashboard is down, data keeps flowing. If the simulator stops, the dashboard keeps showing the last simulation. If the pipeline is paused, events wait in the source tables and nothing is lost |

## 4. What happens when START is pressed

1. The simulator creates a new simulation id, for example `20261114T201229280`, and empties its two source tables.
2. Every 5 seconds it writes a batch: 30 simulated minutes of people events for the stores open at that simulated time, and the sales made by the people leaving.
3. The pipeline, already running, picks the new rows up in its next micro-batch. It skips the deletes, validates each row and appends the valid ones to silver, with their simulation id.
4. The views now see a higher simulation id and show only the new simulation.
5. The dashboard's next refresh shows the new simulation: the numbers restart from zero and grow every few seconds.

Nothing is paused, refreshed or restarted. Earlier simulations stay in silver for analysis and are removed by an occasional housekeeping refresh ([`pipeline.md`](pipeline.md) §3).

## 5. How fast

Measured on 14 November 2026, on the Databricks Free Edition workspace:

| Stage | Measured |
|---|---|
| Simulator writes a batch | Every 5 seconds (one batch = 30 simulated minutes; a simulated day = 240 seconds) |
| Source → bronze | Bronze 3 to 7 seconds behind the clock |
| Silver commits | Every 4 to 6 seconds |
| Dashboard queries | 1.6 to 2.0 seconds each; about 3 seconds for a whole refresh of five queries in parallel |
| Dashboard refresh | Every 5 seconds, one refresh at a time |
| New simulation visible in the views | Within a minute of START right after a deployment, most of it the pipeline starting up; with the pipeline already running, a few seconds |

The pipeline's micro-batch interval is set to 2 seconds; in practice each micro-batch takes 4 to 6 seconds. That processing time, not the setting, is today's limit to going faster.

## 6. The business model in numbers

| | |
|---|---|
| Stores | 200 physical stores in 13 countries and 3 macro regions (Europe 100, Americas 60, Asia 40); 2 flagships, Milan and New York ([`dataset.md`](dataset.md)) |
| Sales channels | **Retail** (198 stores) and **Flagship** (2): sales come from the people counted leaving. **E-commerce** (13, one per country): online sales all day, no people counting, 10% of a country's sales value (15% in the US and China), at prices 10% below the stores ([`sales.md`](sales.md) §12) |
| Opening hours | 10:00 to 20:00 local time, so some store is open at every hour of the day worldwide |
| Clients | 100,000; 70% of buyers are local, 30% visitors from another country, inverted at the flagships ([`client.md`](client.md)) |
| Products | 120 in six merchandise categories, at luxury price points ([`product.md`](product.md)) |
| Average transaction | About 1,097 EUR in the stores, 984 EUR online: a transaction is one buyer's basket, 1.08 items on average at about 1,012 EUR each, always in euro ([`sales.md`](sales.md) §11) |
| Transaction ids | One per transaction in every channel, `TX-<simulation>-<sequence>`, numbered in purchase-time order, so they sort by time; one row per item, glued by the id |
| Cockpit | Under START/STOP in the simulator: switch the sales on or off, and the e-commerce sales with them |
| Volumes | About 600,000 visitors and 126,000 transactions per simulated day (110,000 in the stores, 16,800 online) with 137,000 items, about 137 million EUR, of which e-commerce about 12% |
| Time | Sales and events keep the store's local time and, for one worldwide timeline, GMT |

## 7. Quality and control

| Topic | How it is handled |
|---|---|
| **Data quality** | Every event and sale is validated (8 rules for events, 11 for sales). Invalid rows are not lost: they go to a quarantine table with the reasons |
| **Keys** | Natural business keys everywhere; silver declares its primary and foreign keys to the dimensions |
| **Access** | Each app runs as its own service principal with only the permissions listed in §3 |
| **One definition of every KPI** | The metric views; the dashboard's Clienteling tab and Genie read the same definitions, and the glossary repeats each description word for word |
| **Reproducible deployment** | Everything is code in one Git repository: pipeline, apps, KPIs, Genie agent, tables, views and documentation. Four bundles deploy it today ([`operations.md`](operations.md) §3) |
| **Tests** | Automated tests check that the code, the bundles, the SQL scripts and these documents agree, before anything is deployed |
| **Synthetic data** | No real customer, store or company data is used |

## 8. Operating it

| When | What |
|---|---|
| Start of a session | Resume the continuous job, once |
| During the session | Press START in the simulator as often as needed; watch the dashboard |
| End of a session | Pause the job and stop the apps, so no compute is running or billed |
| Occasionally | A full refresh of the pipeline, with the job paused, to drop earlier simulations |

## 9. Limits today and natural next steps

| Limit today | Next step |
|---|---|
| The source is a simulator writing to tables | Connect Azure Event Hubs; the source tables already have its message envelope |
| Micro-batches take 4 to 6 seconds | Tune the pipeline's processing per batch, or accept this latency: the simulator itself writes every 5 seconds |
| E-commerce is sized on the stores' expected sales, with a fixed online curve | Model online traffic too (sessions, conversion), as the stores have people counting |
| The Sales performance tab still computes its KPIs in its own queries; only Clienteling and Genie read the metric views | Move the Sales performance tab onto the metric views too, and add AI/BI dashboards on them ([`kpi_metrics.md`](kpi_metrics.md) §7) |
| Four bundles deployed one by one, SQL scripts run by hand, schema names written into the code | One bundle per environment, deployed by CI after the tests, with schema names as settings ([`decisions.md`](decisions.md) D12) |
| The dashboard shows only the current simulation | Add a simulation selector, to compare runs: silver already keeps them |
| Free Edition workspace, one SQL warehouse shared by both apps | A paid workspace separates the simulator's writes from the dashboard's queries |
