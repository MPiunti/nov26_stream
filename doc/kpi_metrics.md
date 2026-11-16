# KPIs and metric views: the semantic layer

Reference for the project's business KPIs: how they are defined, where they live, and why they are built as Unity Catalog **metric views**. The first consumer is the sales dashboard's planned **Clienteling** tab: sales KPIs on the two main entities, **clients** and **stores**.

The data underneath is described in [`sales.md`](sales.md) (transactions, baskets, channels), [`dataset.md`](dataset.md) (stores), [`client.md`](client.md) and [`product.md`](product.md); schemas and keys in [`warehouse.md`](warehouse.md); the whole solution in [`architecture.md`](architecture.md).

**Status (16 November 2026):** the KPI list is approved (§6), and the two metric views are live in `workspace.test02_metric` (§8), checked against plain SQL on silver. Their functional definitions are in [`kpi_glossary.md`](kpi_glossary.md). Next: the dashboard's Clienteling tab.

## 1. The decision: metric views

**KPIs are defined once, as Unity Catalog metric views, computed live from the silver tables and the dimensions. We stay with this approach for every KPI that allows it.**

A metric view is a governed, named definition of measures (revenue, transactions, average basket...) and of the dimensions they can be sliced by (client, store, channel, country, date...). It stores no data: every query computes the measures from silver at that moment, for whatever slice it asks.

## 2. Why: the options we compared

Two ways to serve KPIs in a near-real-time solution, where silver receives new sales every 4 to 6 seconds:

| | **Metric views** (chosen) | **KPI table refreshed after every silver update** |
|---|---|---|
| **Freshness** | Same as silver: a sale is in the KPIs a few seconds after it happens | Always one refresh behind. No refresh keeps pace with a silver update every 4–6 s, so in practice a refresh every minute or so |
| **Cost** | Only what is queried, when it is queried | A recompute at every refresh, even when nobody is looking |
| **Moving parts** | One SQL definition | A table plus a trigger: a scheduled job, or a step inside the running pipeline that slows its micro-batches |
| **One version of the truth** | Defined once, reused by the BI app, AI/BI dashboards and Genie (natural-language questions) with the same numbers | The numbers live in a table; the logic lives in a job, apart from the consumers |
| **Flexibility** | Any slice: client, store, channel, country, region, category, date, simulation. The measure recomputes correctly for each | Only the grain the table was built at; a new slice means a new table or a new job |
| **Volume today** | About 250,000 sales lines per simulation: aggregating at query time takes about 2 seconds | Pre-aggregation solves a problem we don't have |
| **Scaling later** | Metric views can be **materialized** (pre-computed by Databricks, kept fresh automatically) without changing their definition or their consumers | Already pre-computed, but by our own code |

**In one line, for the executive summary:** metric views give live KPIs with one governed definition and no extra pipeline, and keep a path to pre-computation when volumes grow.

**What a metric view can't express:** KPIs computed per client first and only then grouped, such as client segments (top spenders, recency or frequency bands), first purchase, new vs returning, or a client's favourite store. Within the metric-view approach these are handled by a source query in the metric view's definition, or, if needed, by a governed SQL function. A separate KPI table stays the last resort.

## 3. Feasibility: checked on the workspace

Checked on 16 November 2026, with a throwaway metric view (`zz_probe_sales_metrics`), dropped right after the check:

| Check | Result |
|---|---|
| SQL warehouse | Serverless Starter Warehouse: Pro, serverless, channel *current*, Databricks SQL `2026.44` |
| Create a metric view (YAML version 1.1) over `silver_sales_transactions`, with joins to `dim_store` and `dim_client`, a currency format, and measures `SUM`, `COUNT(DISTINCT)` and a ratio | Created |
| Query it with `MEASURE()`, filtered on the current simulation and grouped by channel | Revenue, transactions, items and average basket **identical to the cent** to the same query written directly on silver, for all three channels |
| Per-client query (total spent by client, top 3) | Works |

**One tooling note:** the Databricks CLI's query helper (`experimental aitools tools query`) strips leading spaces, which breaks the YAML of a metric view. Definitions are deployed through the SQL Statement Execution API (or a bundle-managed SQL job, §5), which sends the text unchanged.

## 4. Where: the `test02_metric` schema

A third schema, next to the other two ([`warehouse.md`](warehouse.md) §1):

| Schema | Holds |
|---|---|
| `test02_warehouse` | Dimensions |
| `test02_streaming` | Sources and pipeline tables (bronze, silver, quarantine) |
| **`test02_metric`** | **Metric views and KPIs only.** They read silver and the dimensions; nothing else writes here |

Created by `src/sql/17_create_metric_schema.sql` (idempotent). Created in the workspace on 16 November 2026; empty for now.

## 5. Design rules

| Rule | Why |
|---|---|
| **Source: the silver tables**, joined to the dimensions on their natural keys (`store_id`, `client_id`, `product_id`) | The governed, validated data; one join path |
| **The simulation is a dimension** (`simulation_id`), not a filter in the definition | The dashboard filters on the current simulation; the same metrics also answer questions about earlier simulations |
| **Measures re-aggregate at query time:** sums, distinct counts, ratios of sums (divided last) | Correct for any slice. A measure that would double-count when summed across a dimension doesn't belong in a metric view (§2) |
| **Transactions = `COUNT(DISTINCT transaction_id)`** | A transaction is a basket with one silver row per item ([`sales.md`](sales.md) §5) |
| **Amounts in EUR**, formatted as currency | Transaction values are always registered in euro ([`sales.md`](sales.md) §11) |
| **Every measure and dimension has a functional description** (`comment`) | It is shown to dashboard users and to Genie; it is the KPI's definition |
| **Deployed from the repository**, by a bundle-managed SQL job, together with its `GRANT SELECT` to the apps that read it | Re-creating a view drops its grants: we lost the dashboard's access that way once. Deployment and grant must travel together |

## 6. KPIs

Agreed with the owner on 16 November 2026, one by one. The functional description of each KPI is in [`kpi_glossary.md`](kpi_glossary.md), word for word the comment of the measure in its metric view.

### 6.1 Clients

| KPI | Functional description | Calculation | Status |
|---|---|---|---|
| **Total spent** | What a client spent, in EUR, across all channels | `SUM(amount)` by client | Approved |
| Transactions | Purchases made (baskets) | `COUNT(DISTINCT transaction_id)` by client | Approved |
| Items bought | Items across those purchases | `SUM(quantity)` by client | Approved |
| Average basket | Spend per purchase | Total spent / transactions | Approved |
| Stores visited | Different stores where the client bought | `COUNT(DISTINCT store_id)` by client | Approved |
| Online share | Part of the client's spend made online | Spend in `ECOM` stores / total spent | Approved |

### 6.2 Stores

| KPI | Functional description | Calculation | Status |
|---|---|---|---|
| **Revenue** | What the store sold, in EUR | `SUM(amount)` by store | Approved |
| Transactions | Purchases made (baskets) | `COUNT(DISTINCT transaction_id)` by store | Approved |
| Average basket | Spend per purchase | Revenue / transactions | Approved |
| Items per basket | Items per purchase | `SUM(quantity)` / transactions | Approved |
| Distinct clients | Different clients who bought | `COUNT(DISTINCT client_id)` by store | Approved |
| Visitor share | Part of the revenue from clients registered in another country | Revenue from non-local clients / revenue | Approved |
| Conversion | Buyers per person leaving the store; physical stores only | Store transactions / people out, from two metric views | Approved: second metric view on the people events |

**Conversion** combines sales with people counts, a different fact table at a different grain. Decided: each fact keeps its own metric view (`sales_metrics`, `people_metrics`), with the same store and time dimensions, and the dashboard divides the two for the same slice.

## 7. Next steps

1. Grant `SELECT` on the two metric views to the sales dashboard (in its bundle's resources) and build the **Clienteling** tab on them ([`sales_dashboard.md`](sales_dashboard.md)).

## 8. The metric views

| Metric view | Over | Holds | Definition |
|---|---|---|---|
| `workspace.test02_metric.sales_metrics` | `silver_sales_transactions`, joined to `dim_store`, `dim_client`, `dim_product` | The client and store KPIs: 12 measures, 17 dimensions | `src/metrics/sales_metrics.sql` |
| `workspace.test02_metric.people_metrics` | `silver_people_counter_events`, joined to `dim_store` | People in and out: 2 measures, 8 dimensions | `src/metrics/people_metrics.sql` |

**Deployment:** the job `retail-metric-views` of the pipeline bundle (`resources/modeling.metrics.job.yml`) runs both files on the SQL warehouse; run it after every change to a definition. Each file creates its metric view if missing (`CREATE VIEW IF NOT EXISTS`), then sets the definition with `ALTER VIEW … AS`. Checked on the workspace: `ALTER` keeps the grants, where `CREATE OR REPLACE` would drop them.

**Checked on 16 November 2026**, for the latest simulation, against the same calculations written directly on silver: revenue, transactions, items, average basket, items per basket, distinct clients, online and visitor share, store transactions by channel, and people in and out by channel, all identical. Per client (top spenders) the total spent, transactions, items, average basket, stores visited and online share work as expected. Filtered measures return 0, not empty, when nothing matches (e.g. the online share of a flagship).

**Querying:** measures through `MEASURE()`, dimensions by name in backticks, `GROUP BY ALL`. For example, the store KPIs of the current simulation:

```sql
SELECT `Store`, `Store Name`, MEASURE(`Revenue`) AS revenue, MEASURE(`Average Basket`) AS average_basket
FROM workspace.test02_metric.sales_metrics
WHERE `Simulation` = (SELECT MAX(simulation_id) FROM workspace.test02_streaming.silver_sales_transactions)
GROUP BY ALL
ORDER BY revenue DESC
```
