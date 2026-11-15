# Sales dashboard: the self-service BI app

Functional reference for the sales BI dashboard: a read-only Databricks app that shows sales and people performance live, from the pipeline's silver tables, with drill-down by geography and merchandise.

The data it reads is described in [`sales.md`](sales.md) (transactions and the silver sales rules), [`dataset.md`](dataset.md) (stores, people events) and [`warehouse.md`](warehouse.md) (schemas and keys).

The dashboard is the **BI engine** of the solution; how it stays decoupled from the simulation engine and from the pipeline is explained in [`architecture.md`](architecture.md).

## 1. Purpose and boundaries

| | |
|---|---|
| **What it does** | Shows sales value (EUR), items sold, average price and people in, on one **GMT** timeline, with filters and drill-down; refreshes **every 5 seconds**, so the numbers grow while the people-stream app and the continuous pipeline run |
| **What it reads** | The current-simulation views `current_sales_transactions` and `current_people_counter_events` (`test02_streaming`): the silver tables `silver_sales_transactions` and `silver_people_counter_events`, filtered to the latest simulation ([`warehouse.md`](warehouse.md) §6); and `dim_store` and `dim_product` (`test02_warehouse`). `SELECT` only |
| **What it doesn't do** | Write anything, read the source tables, or talk to the people-stream app or the pipeline. It works whenever the silver tables exist, also with the simulator stopped |
| **Bundle** | `apps/sales_dashboard/`, bundle `retail_sales_dashboard_bundle`. Separate from the pipeline bundle and from the people-stream app bundle: deployed, started and destroyed on its own |
| **App** | `sales-bi-<user>` (e.g. `sales-bi-michele-piunti`), under **Compute → Apps** |
| **Code** | `apps/sales_dashboard/app/`: `app.py` (screen and callbacks), `assets/dashboard.css` (compact sizes, side margins), `bi.py` (KPIs, deltas, drill-down, chart series; standard library only), `dashboard_sql.py` (the queries; standard library only), `figures.py` (Plotly charts), `sql_warehouse.py` (SQL warehouse access) |

```
 people-stream app ──▶ sources ──(continuous job)──▶ pipeline ──▶ silver_sales_transactions
                                                                  silver_people_counter_events
                                                                          │ SELECT, every 5 s
                                       dim_store, dim_product ──────────▶ │
                                                                          ▼
                                                                  sales dashboard app
```

## 2. Screen

One compact page, laid out like a classic sales BI report. **All dates and hours are GMT (UTC)**, so stores in Milan, New York and Tokyo share one timeline:

| Area | Content |
|---|---|
| **Filter area** (left) | **KPI on charts** (Sales value, Items sold, Average price, People in); **GMT dates** (the dates found in the silver tables; none = all); **macro region** buttons; **country** and **store** lists (narrowed by the region and country chosen; flagships marked ★); **channel** buttons (Retail, Flagship, E-commerce); **merch. category** buttons; the **Live** switch; **Reset filters** |
| **KPI cards** (top) | VALUE, QUANTITY, AVG PRICE, PEOPLE IN, ITEMS PER VISITOR, each with its **Δ live** (§4). There's no comparison with a previous period |
| **Trend** | The chosen KPI on the **GMT calendar date and hour** axis, **one line per macro region** in distinct colours (Europe blue, Americas orange, Asia green). Every line covers the same hours; an hour when a region's stores are closed counts as 0. **Cumulative** (on by default) adds up from the first hour, so the lines grow through the run; off, each point is that hour alone. For the average price, an hour without sales is a gap |
| **Channel** | Next to the trend: horizontal bars of the chosen KPI by **sales channel**, Retail, Flagship and E-commerce (`dataset.md` §2.6), one segment per GMT date. With KPI *People in*, E-commerce has no bar: it has no people counting |
| **Geography** | Horizontal bars of the chosen KPI by **Area → Country → Store**, largest first (top 15, with a note of how many more). Each bar is **cumulative over the dates**: one segment per GMT date (latest blue, earlier grey), with the total at the end of the bar |
| **Product** | The same by **Merch. category → Product**. With KPI *People in*, it shows sales value instead: people aren't counted per product |
| **Footer** | All in GMT (§5): a live clock (**Now**); freshness chips **Refreshed** (with a bar filling up to the next refresh), **Last sale** and **Last people event** (the latest simulated time in silver, and when it was ingested), each with a status dot and an age; then the running **Simulation** id and its counts in silver: sales transactions, items and people events |

**Compact and responsive** (`app/assets/dashboard.css`, served by Dash automatically): small fonts and controls, short charts (trend 230 px, 20 px per bar), and white space at the sides of the page: **5% of the width on phones**, 7.5% from 768 px (tablets, laptops), 10% from 1,400 px (large screens). On a phone the filter area, the cards (two per row) and the charts stack in one column; the page sets the `viewport` meta tag so it renders at device width.

**Browser tab title:** fixed to "Sales BI dashboard". The app is created with `update_title=None`, so Dash doesn't show "Updating..." during the refresh callbacks, and nothing changes the title afterwards.

## 3. Drill-down

The level buttons on the left of each chart ("Select the chart fields") choose what the bars show. Clicking a bar drills down; **▲ Up** drills up; every drill also moves the matching filters in the filter area, so the whole page (cards, trend, other chart) follows.

| Chart | Click on a bar at level | Effect |
|---|---|---|
| Geography | Area | Filter on that macro region, show its countries |
| Geography | Country | Filter on that country, show its stores |
| Geography | Store | Add or remove that store in the store filter |
| Product | Merch. category | Filter on that category, show its products |
| Product | Product | Add or remove that product in the product filter |
| Channel | Channel (one level) | Add or remove that channel in the channel filter; **✕ All channels** clears it |

**▲ Up** removes the filter of the current level and the one above it, and goes one level up: Store → Country (clears stores and countries), Country → Area (clears countries and regions), Product → Merch. category (clears products and categories).

## 4. KPIs

| KPI | Definition | Filters that apply |
|---|---|---|
| VALUE | `SUM(amount)` of the silver transactions, EUR (transaction values are always in euro, [`sales.md`](sales.md) §11) | All |
| QUANTITY | `SUM(quantity)`: items sold. A transaction can hold several items, one row each (`sales.md` §5) | All |
| AVG PRICE | VALUE / QUANTITY | All |
| PEOPLE IN | `SUM(people_count)` of the silver `ENTRY` events | Dates, geography, store type; **not** category or product |
| ITEMS PER VISITOR | Items sold **in physical stores** (`RETAIL`, `FLAGSHIP`) / PEOPLE IN. E-commerce items are left out: online buyers never pass a people counter | As its two parts |

- **GMT time:** sales use silver's `transaction_timestamp_utc` ([`sales.md`](sales.md) §11.4). People events have only their local `event_timestamp` in silver, so the queries convert it the same way: `convert_timezone(d.timezone_id, 'UTC', s.event_timestamp)`, with the store's time zone from `dim_store`. The date filter and the bar segments are GMT dates.
- **Δ live:** the change since the previous refresh with the same filters, so it shows how much arrived in the last 5 seconds. It's blank (—) right after a filter change.

## 5. Freshness

| Step | Delay |
|---|---|
| People-stream app → source tables | A batch every 5 s (30 simulated minutes); see [`people_stream.md`](people_stream.md) §4 |
| Source → silver | The continuous job keeps a pipeline update running, with a micro-batch every 2 seconds per table (`pipelines.trigger.interval`); see `readme.md`, "Running the pipeline" |
| Silver → screen | The dashboard queries silver **every 5 seconds** (`REFRESH_SECONDS` in `app/app.yaml`, at least 2). The **Live** switch stops and restarts the refresh |

Each refresh runs six read-only queries in parallel, all six at once (sales by region, GMT date and hour; people likewise; the geography, product and channel breakdowns; freshness), on one reused connection per worker thread. Measured on the Serverless Starter Warehouse: about 1.6–1.9 s per query, 3–4 s per refresh. The dimensions are read once and cached.

**Footer freshness:** a **Now** clock shows the current GMT time, and each chip shows a time in GMT and how long ago it was. All of it is recomputed in the browser four times a second, with no server call, so time visibly passes between refreshes and the ages show at once when data stops arriving. Under **Refreshed**, a thin bar fills from the last refresh to the next one (5 seconds) and starts again at every refresh; a bar that stays full means a refresh is late:

| Chip | Time shown | Age counts from | Dot |
|---|---|---|---|
| Refreshed | When the page last got data, e.g. `19:32:05 GMT` | That moment | Green under 30 s, amber under 2 min, red after |
| Last sale | The latest `transaction_timestamp_utc` in silver (simulated, up to two days ahead), and when it was ingested into bronze | The ingestion (real time) | Same |
| Last people event | The latest people event in GMT, and when it was ingested | The ingestion | Same |

At the end of the footer, **Simulation** names the simulation the page shows (the latest `simulation_id`, the one the views select, `warehouse.md` §6), followed by its counts in silver: sales transactions (distinct `transaction_id`), their items (one row each) and people events. They restart from zero when a new simulation starts.

While the simulator and the continuous job run, all three dots stay green: a new batch reaches silver every few seconds. An amber or red sales or people dot with a green refresh dot means the page is fine but no new data is arriving (simulator stopped, or job paused).

**One refresh at a time:** the 5-second interval doesn't run the refresh directly; it only asks for one when the previous refresh has finished (or after 30 s, in case one failed). Otherwise a refresh slower than 5 s, which happens when the warehouse is also busy with the simulator's writes, would be overtaken by the next one, and Dash drops the result of an overtaken callback: the screen would never update. So the screen updates every 5 s, or as soon as the previous refresh ends if that takes longer.

**Always the current simulation:** the queries read the `current_…` views, so the page shows only the latest simulation. When START is pressed in the people-stream app, the page switches to the new simulation by itself as soon as its first events reach silver, a few seconds later: the numbers restart from zero and the trend starts a new timeline. Nothing has to be paused or refreshed. Earlier simulations stay in the silver tables but never mix into the page.

If a silver table or column doesn't exist yet (pipeline not deployed, or not full-refreshed since `03_sales.py` or `transaction_timestamp_utc` was added), the page shows a warning and keeps retrying at every refresh.

## 6. Queries

All in `app/dashboard_sql.py`:

- **Read-only:** every statement is a `SELECT`.
- **Parameterized:** filter values are passed as named parameters (`:region_0`, `:date_0`, …), never pasted into the SQL. Dates must be `YYYY-MM-DD`, levels and store types come from fixed lists, and table names are checked to be `catalog.schema.table`.
- **Joins:** silver is joined to `dim_store` on the natural key `store_id`, for the region, country and channel filters, the channel chart, the macro region of each trend line, and the people events' time zone. Store, country and product names come from the cached dimensions.
- **Transactions:** `COUNT(DISTINCT transaction_id)`, since a transaction has one row per item. All the rows of a transaction share its store, time and channel, so the counts add up across hours, regions and channels.
- **Session time zone UTC:** the connection sets `TIMEZONE` = `UTC`, so `TIMESTAMP` columns (`ingestion_timestamp`) come back in GMT too.

## 7. Deployment and permissions

| Step | How |
|---|---|
| Before the first deploy | Deploy the pipeline bundle and run the pipeline at least once, then run `src/sql/15_create_current_simulation_views.sql`, so the views `current_sales_transactions` and `current_people_counter_events` exist (the app's permissions are granted on them). The dimensions come from `src/sql/01_…`, `02_…`, `10_…`, `11_…` |
| Check | `databricks bundle validate --strict -t dev --profile MPiunti`, from `apps/sales_dashboard/` |
| Deploy | From `apps/sales_dashboard/`: `databricks bundle deploy -t dev --profile MPiunti`, then `databricks bundle run sales_dashboard -t dev --profile MPiunti` to start the app; or, in the workspace Git folder, open `apps/sales_dashboard/` and use **Deployments** |
| Granted to the app | `CAN_USE` on the SQL warehouse; `SELECT` on the views `test02_streaming.current_sales_transactions` and `current_people_counter_events`, and on `test02_warehouse.dim_store` and `dim_product`. Nothing else: no access to the silver tables themselves |
| Stop paying for it | Stop the app under **Compute → Apps**. While open, the page queries the SQL warehouse every 5 seconds, which keeps the warehouse running; switch **Live** off or close the page when you're done |

The pipeline bundle doesn't upload `apps/` (`sync.exclude` in the root `databricks.yml`), and each app bundle has its own state, so deploying one never changes the others.
