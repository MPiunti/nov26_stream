# Executive brief: the real-time retailer on Databricks

For the CTO of a retail group: what this solution shows, why the Databricks Data Intelligence Platform changes how a retailer runs on data, what it is worth, and how to take it from demonstration to enterprise. It is the basis for the pitch; the technical picture is in [`architecture.md`](architecture.md), and the reasons behind each choice in [`decisions.md`](decisions.md). All data is synthetic.

## 1. The retailer's problem

| Today, in most retail groups | What it costs |
|---|---|
| Store traffic, tills, e-commerce and CRM live in separate systems | Nobody sees footfall and sales together; conversion is guessed |
| Reports arrive the next morning, from overnight batches | Staffing, stock and clienteling react a day late |
| Each team computes its KPIs its own way | Three numbers for "conversion" in one meeting; trust in data erodes |
| AI pilots run on extracted copies, outside governance | Risky, hard to scale, and not trusted by the business |
| A different tool for ingestion, warehouse, BI, AI and app hosting | Integration projects, copies of data, a security review for each |

## 2. What the solution shows

A luxury retail group with **200 stores in 13 countries** across Europe, the Americas and Asia, 2 flagships (Milan and New York), an e-commerce store in every country and **100,000 clients**:

- **Live:** every door event and every sale is validated and available for analysis **seconds after it happens**: about 600,000 visitors and 126,000 transactions per simulated day, worth about 137 million EUR.
- **One definition of every KPI:** revenue, conversion, average basket, client segments from Occasional to VICSTAR, the same in the dashboard and in natural-language answers.
- **Self-service:** a live sales dashboard with drill-down from region to store and from category to product; a Clienteling view; and **Ask Genie**, where an executive types a question in plain language and gets the governed answer.
- **Built on one platform, by one engineer, in six days** (12–18 November 2026), on a Databricks Free Edition workspace, everything as code in one Git repository.

## 3. Why Databricks is a game changer: five shifts

| From | To | With Databricks | In this solution |
|---|---|---|---|
| **Overnight batch** | **Seconds** | **Lakeflow Declarative Pipelines** on serverless compute: both streams declared in about 900 lines of Python, comments included; Databricks runs the checkpoints, retries and scaling | Source to silver in a few seconds, with 8 validation rules for door events and 11 for sales; invalid rows kept in quarantine with their reasons, never lost |
| **Copies of data in every tool** | **One governed copy** | **Delta Lake** tables governed by **Unity Catalog**: permissions, declared keys, lineage, in one place | Every app runs as its own identity with least privilege: the simulator may write only its two source tables, the dashboard may only read |
| **Every team its own KPIs** | **One definition, everywhere** | **Unity Catalog metric views**: a governed semantic layer, computed live | `client_metrics` and `store_metrics`: identical to the cent with hand-written SQL, as fresh as the data, with each KPI's business definition attached ([`kpi_glossary.md`](kpi_glossary.md)) |
| **AI on the side** | **AI on governed data** | **Genie**: natural-language questions answered through the semantic layer, with the asking user's permissions | The Retail KPI Assistant answers "What is the conversion rate of each flagship store?" from the same metric views as the dashboard, checked against 10 benchmark questions |
| **A tool per job** | **One platform, as code** | **Databricks SQL** serverless warehouse, **Databricks Apps**, **Declarative Automation Bundles** | The simulator and the dashboard run on the platform itself; pipeline, apps, KPIs and agent are deployed from Git, tested before every deploy |

**And cost follows use:** everything is serverless. Compute runs while the data flows or someone looks, and stops when the session is switched off: no idle clusters, no capacity to size.

## 4. Business value for a retailer

| Area | Decision it enables | From the solution |
|---|---|---|
| **Store operations** | Staff to the traffic of the next hour, not last month's average | People in and out per store and hour, live, on one worldwide timeline |
| **Conversion** | Find the stores where visitors leave without buying, while it is happening | Conversion per store, channel, region and hour: about 15% on a typical run, 17–18% at the flagships |
| **Clienteling** | Recognize VIC and potential-VIC clients, assign each to the store they keep coming back to, and give its client advisors a reason to call | Client segments OCC, EXP, ASP, POT, VIC1, VICSTAR, fixed per client, live; each client's preferred store, by visits; top clients with their spend, stores visited and online share |
| **Tourism and flagships** | Plan flagship assortments and staff for international visitors | Visitor share of revenue: about 70% at New York Fifth Avenue on a typical run |
| **Omnichannel** | Balance online and in-store: share, basket, price | E-commerce share per country (10%, 15% in the US and China), online vs store basket |
| **Merchandising** | React to a category or product taking off today | Drill-down from category to product, live |
| **Leadership** | Ask the next question without waiting for a report | Ask Genie, on governed numbers |

The figures are those of the simulation, so they show the mechanism, not a forecast of returns.

## 5. Proof points, measured

| | Measured on the demo ([`architecture.md`](architecture.md) §5–6) |
|---|---|
| Event to silver | Bronze 3 to 7 seconds behind the clock; silver commits every 4 to 6 seconds |
| Dashboard | Refreshed every 5 seconds; each query 1.6 to 2.0 seconds on the live data |
| Volume | About 600,000 visitors and 126,000 transactions per simulated day |
| KPI accuracy | Metric views identical to hand-written SQL on silver, for every channel and the top clients |
| Data quality | Every row validated; invalid rows in quarantine with every failed rule |
| Change safety | Automated tests check that code, bundles, SQL and these documents agree before every deploy |
| Time to build | Six days, one engineer, from empty workspace to live dashboard, KPIs and Genie |

## 6. From demonstration to enterprise

| Phase | What | Databricks capabilities |
|---|---|---|
| **1. Pilot, one region (about 3 months)** | Real door counters and tills instead of the simulator; the pipeline doesn't change, because the source tables already have an event broker's envelope | Event Hubs or Kafka into Lakeflow Declarative Pipelines; Lakeflow Connect for CRM, ERP and e-commerce |
| **2. Industrialize** | One bundle per environment (dev, test, prod), deployed by CI as a service principal; data checks as gates; quality monitoring ([`decisions.md`](decisions.md) D12) | Declarative Automation Bundles, Unity Catalog per environment, data quality monitoring and SQL alerts |
| **3. Scale to the group** | All regions and brands; KPIs pre-computed only where volume requires it | Serverless autoscaling; materialized metric views, without changing their consumers |
| **4. Intelligence** | Traffic and demand forecasting per store and hour; next best action for client advisors; an operational clienteling app | AI Functions such as `ai_forecast`, Mosaic AI model training and serving, Lakebase for low-latency app data |
| **5. Ecosystem** | Share sell-out and traffic with brands, landlords and partners without copying data | Delta Sharing, Databricks Clean Rooms |

## 7. What a CTO will ask

| Question | Answer |
|---|---|
| **What does it cost to run?** | Serverless, pay per use: nothing runs when the session is switched off. KPIs cost only when queried; pre-compute them only when volume makes it worth it |
| **Does it scale?** | The same declarative pipeline scales on serverless compute; the levers are the micro-batch interval, materialized metric views and separate SQL warehouses for writes and queries |
| **Is it lock-in?** | Data in Delta Lake, an open format, readable by other engines and as Iceberg; the pipelines in Spark declarative syntax, open source as Apache Spark Declarative Pipelines; SQL and Python everywhere |
| **How is client data protected?** | Unity Catalog: least-privilege grants per app and per person, lineage, audit; row filters and column masks for client details. Genie answers with the asking user's own permissions |
| **How fast is "real time"?** | Seconds today, limited by the 4–6 seconds of each micro-batch; Structured Streaming's real-time mode for use cases that need less than a second |
| **How do we trust an AI answer?** | Genie answers from the governed metric views, shows its SQL, and is scored against benchmark questions with checked answers |
| **What does a new KPI take?** | A few lines in a metric view, deployed from Git; the dashboard, Genie and AI/BI see it at once, with its definition |
| **What if bad data arrives?** | It is kept in quarantine with the reason, and silver stays clean; nothing is lost, nothing stops |

## 8. The demonstration, in ten minutes

Before the session, switch everything on ([`people_stream.md`](people_stream.md) §10).

| # | Show | Say |
|---|---|---|
| 1 | The picture ([`architecture.md`](architecture.md) §2) | Three engines that never call each other, joined only by governed tables |
| 2 | The simulator: press **START** | 200 stores open around the world; every 5 seconds is half an hour of trading |
| 3 | The dashboard, **Sales performance** | Sales and traffic arrive in seconds; drill Europe → Italy → the Milan flagship |
| 4 | The **Clienteling** tab | One definition of every KPI: conversion, average basket, client segments up to VICSTAR |
| 5 | **Ask Genie:** "What is the conversion rate of each flagship store?", then "Show the SQL" | Plain language, governed answer, nothing invented |
| 6 | Unity Catalog: a metric view's lineage and the apps' permissions | One copy, governed end to end |
| 7 | The Git repository: bundles, tests, docs | Everything is code, tested before it is deployed |
| 8 | Switch off | Serverless: nothing running, nothing billed |
