# Sales dashboard: the self-service BI app

Functional reference for the sales BI dashboard: a read-only Databricks app that shows sales and people performance live, from the pipeline's silver tables, with drill-down by geography and merchandise.

The data it reads is described in [`sales.md`](sales.md) (transactions and the silver sales rules), [`dataset.md`](dataset.md) (stores, people events) and [`warehouse.md`](warehouse.md) (schemas and keys).

## 1. Purpose and boundaries

| | |
|---|---|
| **What it does** | Shows sales value (EUR), items sold, average price and people in, per store-local date and hour, with filters and drill-down; refreshes **every 5 seconds**, so the numbers grow while the people-stream app and the continuous pipeline run |
| **What it reads** | `silver_sales_transactions` and `silver_people_counter_events` (`test02_streaming`), `dim_store` and `dim_product` (`test02_warehouse`). `SELECT` only |
| **What it doesn't do** | Write anything, read the source tables, or talk to the people-stream app or the pipeline. It works whenever the silver tables exist, also with the simulator stopped |
| **Bundle** | `apps/sales_dashboard/`, bundle `retail_sales_dashboard_bundle`. Separate from the pipeline bundle and from the people-stream app bundle: deployed, started and destroyed on its own |
| **App** | `sales-bi-<user>` (e.g. `sales-bi-michele-piunti`), under **Compute → Apps** |
| **Code** | `apps/sales_dashboard/app/`: `app.py` (screen and callbacks), `bi.py` (KPIs, deltas, drill-down, chart series; standard library only), `dashboard_sql.py` (the queries; standard library only), `figures.py` (Plotly charts), `sql_warehouse.py` (SQL warehouse access) |

```
 people-stream app ──▶ sources ──(continuous job)──▶ pipeline ──▶ silver_sales_transactions
                                                                  silver_people_counter_events
                                                                          │ SELECT, every 5 s
                                       dim_store, dim_product ──────────▶ │
                                                                          ▼
                                                                  sales dashboard app
```

## 2. Screen

One page, laid out like a classic sales BI report:

| Area | Content |
|---|---|
| **Filter area** (left) | **KPI on charts** (Sales value, Items sold, Average price, People in); **store-local dates** (the dates found in the silver tables; none = all); **macro region** buttons; **country** and **store** lists (narrowed by the region and country chosen; flagships marked ★); **store type** (All, Flagships, Others); **merch. category** buttons; the **Live** switch; **Reset filters** |
| **KPI cards** (top) | VALUE, QUANTITY, AVG PRICE, PEOPLE IN, ITEMS PER VISITOR, each with **DELTA LIVE** and **VS PREV. DAY** (§4) |
| **Trend** | The chosen KPI by store-local hour (10 to 20), **one line per store-local date**: the latest date in blue, earlier ones in grey, so today's line can be compared with yesterday's as it grows. **Cumulative through the day** (on by default) adds up the hours within each date; off, each point is that hour alone |
| **Geography** | Horizontal bars of the chosen KPI by **Area → Country → Store**, largest first (top 15, with a note of how many more). Each bar is **cumulative over the dates**: one segment per store-local date, with the total at the end of the bar |
| **Product** | The same by **Merch. category → Product**. With KPI *People in*, it shows sales value instead: people aren't counted per product |
| **Footer** | Last refresh (UTC), last sale and last people event (store-local time), last sales ingestion into bronze (UTC), and silver row counts |

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

**▲ Up** removes the filter of the current level and the one above it, and goes one level up: Store → Country (clears stores and countries), Country → Area (clears countries and regions), Product → Merch. category (clears products and categories).

## 4. KPIs

| KPI | Definition | Filters that apply |
|---|---|---|
| VALUE | `SUM(amount)` of the silver transactions, EUR | All |
| QUANTITY | `SUM(quantity)`: items sold | All |
| AVG PRICE | VALUE / QUANTITY | All |
| PEOPLE IN | `SUM(people_count)` of the silver `ENTRY` events | Dates, geography, store type; **not** category or product |
| ITEMS PER VISITOR | QUANTITY / PEOPLE IN | As its two parts |

- **Store-local time:** dates and hours are the stores' local time (`transaction_timestamp`, `event_timestamp`; `TIMESTAMP_NTZ`), as in silver. A date therefore covers different UTC hours in Milan, New York and Tokyo.
- **DELTA LIVE:** the change since the previous refresh with the same filters, so it shows how much arrived in the last 5 seconds. It's blank (—) right after a filter change.
- **VS PREV. DAY:** a **like-for-like** comparison: the latest store-local date against the date before, over the same hours (up to the latest hour of the latest date). Blank with a single date.

## 5. Freshness

| Step | Delay |
|---|---|
| People-stream app → source tables | A batch every 5 s (30 simulated minutes); see [`people_stream.md`](people_stream.md) §4 |
| Source → silver | The continuous job runs one pipeline update after another; each picks up what's new (`readme.md`, "Running the pipeline") |
| Silver → screen | The dashboard queries silver **every 5 seconds** (`REFRESH_SECONDS` in `app/app.yaml`, at least 2). The **Live** switch stops and restarts the refresh |

Each refresh runs five read-only queries in parallel (sales by date and hour, people by date and hour, the geography breakdown, the product breakdown, freshness), on one reused connection per worker thread. The dimensions are read once and cached.

If a silver table doesn't exist yet (pipeline not deployed or not run since `03_sales.py` was added), the page shows a warning and keeps retrying at every refresh.

## 6. Queries

All in `app/dashboard_sql.py`:

- **Read-only:** every statement is a `SELECT`.
- **Parameterized:** filter values are passed as named parameters (`:region_0`, `:date_0`, …), never pasted into the SQL. Dates must be `YYYY-MM-DD`, levels and store types come from fixed lists, and table names are checked to be `catalog.schema.table`.
- **Joins:** silver is joined to `dim_store` on the natural key `store_id`, for the region, country and flagship filters. Store, country and product names come from the cached dimensions.

## 7. Deployment and permissions

| Step | How |
|---|---|
| Before the first deploy | Deploy the pipeline bundle and run the pipeline at least once, so `silver_sales_transactions` and `silver_people_counter_events` exist (the app's permissions are granted on them). The dimensions come from `src/sql/01_…`, `02_…`, `10_…`, `11_…` |
| Check | `databricks bundle validate --strict -t dev --profile MPiunti`, from `apps/sales_dashboard/` |
| Deploy | From `apps/sales_dashboard/`: `databricks bundle deploy -t dev --profile MPiunti`, then `databricks bundle run sales_dashboard -t dev --profile MPiunti` to start the app; or, in the workspace Git folder, open `apps/sales_dashboard/` and use **Deployments** |
| Granted to the app | `CAN_USE` on the SQL warehouse; `SELECT` on `test02_streaming.silver_sales_transactions` and `silver_people_counter_events`, and on `test02_warehouse.dim_store` and `dim_product`. Nothing else |
| Stop paying for it | Stop the app under **Compute → Apps**. While open, the page queries the SQL warehouse every 5 seconds, which keeps the warehouse running; switch **Live** off or close the page when you're done |

The pipeline bundle doesn't upload `apps/` (`sync.exclude` in the root `databricks.yml`), and each app bundle has its own state, so deploying one never changes the others.
