# People stream: the simulator app

Functional reference for the people-stream simulator: a Databricks app that generates people-counter events for every store and inserts them into the pipeline's source table, as if they arrived from Event Hubs.

The stores, opening hours, payload and `N_AVG_PEOPLE_*` parameters are defined in [`dataset.md`](dataset.md); this page describes how the simulator uses them.

The simulator is the **simulation engine** of the solution; how it stays decoupled from the pipeline and from the BI engine (the sales dashboard) is explained in [`architecture.md`](architecture.md).

## 1. Purpose and boundaries

**Which stores:** the people stream covers the 200 physical stores, channels `RETAIL` and `FLAGSHIP` (`dataset.md` §2.6). The 13 e-commerce stores (`ECOM`) have no people counter: the app loads them with the others but only generates their online sales (`sales.md` §12).

| | |
|---|---|
| **What it does** | Simulates the people flow of all 200 stores and inserts the events into `workspace.test02_streaming.simulated_event_source`. Its sales simulator turns people leaving into sales transactions in `simulated_sales_source`; see [`sales.md`](sales.md) |
| **What it doesn't do** | Run the pipeline. The pipeline moves new events to bronze, silver and quarantine when it runs; its continuous job keeps it running (`readme.md`, "Running the pipeline"). The sales dashboard ([`sales_dashboard.md`](sales_dashboard.md)) then shows them |
| **Bundle** | `apps/people_stream/`, bundle `retail_people_stream_bundle`. Separate from the pipeline bundle at the repo root: deployed, started and destroyed on its own |
| **App** | `people-stream-<user>` (e.g. `people-stream-michele-piunti`), under **Compute → Apps** |
| **Code** | `apps/people_stream/app/`: `app.py` (screen), `assets/clock.css` (headline panel and clock), `simulator.py` (generator, standard library only), `sql_warehouse.py` (SQL warehouse reads and writes) |

```
 app screen ──START/STOP, sliders──▶ simulator (one thread)
                                        │ every 5 s: 30 simulated minutes of events
                                        ▼
                     simulated_event_source  ◀── also 05_insert_simulated_events.sql
                                        │ (pipeline run, triggered)
                                        ▼
                          bronze ─▶ silver / quarantine
```

## 2. Configuration: `shop_config.yml`

Every store and simulation parameter is in `apps/people_stream/app/shop_config.yml`, deployed with the app. The app reads it once when it starts, checks it, and shows the values in its **Parameters** panel. After changing it, redeploy the app bundle (or restart the app).

| Key | Shipped value | Meaning |
|---|---|---|
| `stores.opening_hour`, `stores.closing_hour` | 10, 20 | Opening hours, each store's local time |
| `stores.max_stay_minutes` | 90 | Longest a person stays inside (1.5 h); every stay also ends by closing. Shown on the Simulator tab (intro line and Parameters panel). See §5 |
| `avg_stay_minutes.default`, `.min`, `.max`, `.step` | 45, 5, 85, 5 | Average stay inside a store (exit time − entry time, as the sensors register it): start value and range of the stay slider. `max` must be below `stores.max_stay_minutes`. See §5 |
| `clients.local_share` | 70 | Percent of buyers registered in the store's country; the other 30% are visitors from other countries. See `client.md` §4 |
| `flagships.store_ids` | `IT-MI-001, US-NY-001` | The flagship stores (Milan Galleria Vittorio Emanuele, New York Fifth Avenue), `dataset.md` §2.5 |
| `flagships.traffic_pct` | 145 | Entering people at flagships, percent of the region's N_AVG_PEOPLE (+45%) |
| `flagships.local_share` | 30 | Percent of local buyers at flagships (70% visitors, the inverse of the other stores) |
| `cockpit.sales`, `cockpit.ecommerce` | 1, 1 | Start values of the cockpit switches (§3): 1 = on, 0 = off |
| `ecommerce.share_pct`, `.high_share_pct` | 10, 15 | E-commerce stores (channel `ECOM`): online sales as a percent of a country's total sales value; 15% in `high_share_countries`. See `sales.md` §12 |
| `ecommerce.high_share_countries` | `US, CN` | Countries with the higher e-commerce share |
| `ecommerce.price_pct` | 90 | Online price, percent of list price: e-commerce transactions are 10% lower on average |
| `n_avg_people.default.EUROPE` / `.AMERICAS` / `.ASIA` | 3000 each | `N_AVG_PEOPLE_EUROPE`, `_AMERICA`, `_ASIA`: average visitors per store per simulated day; slider start values and **Reset to defaults** |
| `n_avg_people.min`, `.max`, `.step` | 2000, 6000, 100 | Slider range |
| `purchase_prob.default.<REGION>.<CATEGORY>` | SHOES 5, BAGS 2, READY_TO_WEAR 6, ACCESSORIES 3, TRAVEL 2, SUNGLASSES 2 (every region) | PURCHASE_PROB, percent: chance that a person leaving buys one item of the category; horizontal slider start values. See `sales.md` §3 |
| `purchase_prob.min`, `.max`, `.step` | 0, 100, 1 | Probability slider range |
| `simulation.real_seconds_per_sim_day` | 240 | Day length: 24 simulated hours in 240 real seconds, so 1 hour = 10 s |
| `simulation.max_run_sim_hours` | 48 | Longest run (= 480 real seconds with a 240 s day) |
| `simulation.tick_seconds` | 5 | Real seconds between batches (= 30 simulated minutes with a 240 s day) |

**Format:** nested `key: value` lines with two-space indents, whole numbers (or, for `store_ids` and `high_share_countries`, a comma-separated list of ids), `#` comments. The app refuses to start, with the reason in its log, if the file has an unknown or missing key, a value that isn't a whole number, closing before opening, a default outside the slider range or off its step grid, or a batch longer than a run.

The rest of this page quotes the shipped values. `dataset.md` §4 and §5 describe the same assumptions for the data as a whole.

## 3. Screen

The screen has a header, always visible, and two tabs: **Simulator** (controls) and **Counters** (the dashboard).

| Control | Behaviour |
|---|---|
| **START** | Starts a new run from scratch: first **empties both source tables** (`simulated_event_source` and `simulated_sales_source`, see §7), then reads the stores and sets the simulated clock to the current time. The run lasts at most 48 simulated hours (480 s). Disabled while running |
| **STOP** | Ends the run: the generator stops at once (state `STOPPING`); batches already generated are still written (state `WRITING`), then the state becomes `STOPPED`. The screen never waits for the writes. Disabled while stopped |
| **Cockpit** | Under START/STOP, always visible. **Sales transactions** (default on): each person leaving a store buys with PURCHASE_PROB, and everything one buyer buys is one transaction (`sales.md` §4); off, no sales at all, while the people stream goes on. **E-commerce sales** (default on): the e-commerce stores' online orders on top of the stores' sales (`sales.md` §12); it can be on only while sales are on, so it's greyed while sales are off. Both apply from the next batch, also while running, and are shared by every viewer. Start values: `cockpit.*` in `shop_config.yml` (§2) |
| **Three vertical sliders (equalizer)** | `N_AVG_PEOPLE_EUROPE`, `N_AVG_PEOPLE_AMERICA`, `N_AVG_PEOPLE_ASIA`: average visitors per store per simulated day. Range 2000–6000, step 100, default 3000 (from `shop_config.yml`). A change applies from the next batch, also while running |
| **Average stay slider** | At the top of the Simulator tab: the average stay inside a store, 5–85 minutes, step 5, default 45. Next to it, the window stays are drawn from and the **measured** average stay per region (estimated from the people who left). A change applies to people entering from the next batch |
| **PURCHASE_PROB sliders** | Under each region's vertical slider, six horizontal sliders, one per merchandise category, 0–100%. See `sales.md` §3 |
| **Reset to defaults** | Puts all sliders back to `n_avg_people.default`, `purchase_prob.default` and `avg_stay_minutes.default` |
| **Parameters** | The values read from `shop_config.yml`, with what each means |
| **Headline panel** | Under the title, always visible, kept current by the screen's 1-second refresh (so it changes with every batch, every 5 seconds). Three blocks: **Simulated time**, an analog clock showing the simulated GMT time, with the timestamp below, e.g. `14 Nov 2026 20:42:29 GMT`; **Simulation id**, e.g. `20261114T201229280` (§6); **Started at**, the START time in GMT. Before the first START the clock is greyed, with both hands up, and the values show `—`; after a run ends they keep its last values |
| **Analog clock** | Hour and minute hands on a 12-hour dial; morning or afternoon is read from the timestamp below. The hands only turn forwards, also past 12, and glide to the new time between the batches of a running simulation. They jump, without animation, on the first batch of a simulation and when the page is opened |
| **Browser tab title** | `People stream simulator`; while a run is `RUNNING`, followed by the simulated hour, e.g. `People stream simulator · 2026-11-14 07:00 UTC`. It changes once per simulated hour and never shows "Updating..." |
| **Signature** | At the bottom of the page: "This app is made by Michele Piunti in November 2026.", with a link to the Git project, [github.com/MPiunti/nov26_stream](https://github.com/MPiunti/nov26_stream) |
| **Tabs** | **Switch on / off**: how to switch the whole solution on and off by hand in Databricks, the steps of §10. **Simulator**: sliders, parameters and stream status; no charts. **Counters**: the in/out table, people per calendar date, and the cumulative people-out and people-in charts. The headline panel, START and STOP and the cockpit sit above the tabs |
| **Sales transactions by region and category** (Counters tab) | Per region, for the physical stores: items per category, transactions (baskets), items per transaction, amount in EUR, conversion (transactions per person out), share of local clients. Then the e-commerce stores: transactions, amount, and their share of the region's sales value. See `sales.md` §8 and §12 |
| **In, out and still inside** (Counters tab) | Per region: people in (sum of `ENTRY`), people out (sum of `EXIT`), their difference (the people still inside open stores), and the measured average stay |
| **People per calendar date** (Counters tab) | Bar chart: for each calendar date, one bar per region (grouped side by side) with the sum of `people_count` on that date. The date is the store's local date (from `event_timestamp`), the same day the in/out balance uses. A switch picks **People out (EXIT)** (default) or **People in (ENTRY)**. Each bar is that date's total, not a running total. The first and last dates of a run are partial, because the run starts and ends mid-day |
| **Cumulative people-in chart** (Counters tab) | One line per region, the running sum of `people_count` of the region's `ENTRY` events since START (y), against simulated UTC time (x). The x axis always spans the run's 48 simulated hours from START, so the lines grow left to right; one point per batch (at most 97). Colors are fixed per region (Europe blue, Americas orange, Asia aqua), with a legend, a label at each line's end, and a shared hover tooltip. The chart keeps the last run until the next START |
| **Cumulative people-out chart** (Counters tab) | The same chart for `EXIT` events: the running sum of `people_count` of the region's `EXIT` events since START (y) against simulated UTC time (x), over the run's 48 hours, same colors, legend, end labels and hover. Exits follow entries during the day and catch up at each store's 20:00 closing, so the lines climb in steps when a region closes |
| **Status** | State (`STARTING`, `RUNNING`, `STOPPING` after STOP, `WRITING` while queued batches are still being written, `STOPPED` by STOP, `FINISHED` after 48 simulated hours, `FAILED` with the error), simulated UTC time, start and end time, seconds left, rows written, batches waiting to be written, batches generated, simulation id; per region: stores open now and visitors so far |

There is one simulation per app, shared by everyone who opens it: a second viewer sees the same run and the same slider values.

## 4. Time model

| Rule | Value |
|---|---|
| Speed | **24 simulated hours = 240 real seconds**: 1 simulated hour = 10 s, 1 simulated minute ≈ 0.17 s (factor 360) |
| Start | On **START**, simulated time = the current real UTC time |
| Store clock | Each store sees the simulated UTC time in its own `timezone_id`, with daylight-saving time |
| Batch (tick) | Every `simulation.tick_seconds` real seconds (shipped: **5 s = 30 simulated minutes**), the simulator emits the events of the simulated time since the previous batch |
| Run length | **At most 48 simulated hours = 480 real seconds.** The last batch ends exactly at start + 48 h; then the generator quits and the state becomes `FINISHED`. The app itself keeps running, ready for the next START |
| Restart | START always begins a new simulation from scratch, from the current real time, with a new simulation id (§6) and a new 480-second limit, on empty source tables; the previous simulation's simulated time, store occupancy and events are not kept |

**Fixed schedule:** batches are generated at START + 5 s, + 10 s, + 15 s, … (every `simulation.tick_seconds`), whatever the warehouse is doing, and the status and the Counters charts update with each batch: one new chart point per tick. Writing runs in the background (§7), so a slow write never delays the next tick or the charts. Each batch covers the simulated time since the previous one, so simulated time never drifts.

## 5. One stream per store

Each store runs its own stream, 24 simulated hours a day:

1. **Opening hours:** events only between **10:00 and 20:00 local time**. Across the three macro regions some store is open at every UTC hour (see `dataset.md` §4), so the app writes around the clock.
2. **Entries:** for the open minutes of a batch, the number of people entering is drawn from a Poisson distribution with mean `N_AVG_PEOPLE_<region> × open minutes / 600`. With the default that's 150 per store per 30-minute batch. The two flagships use 145% of their region's N_AVG_PEOPLE (`flagships.traffic_pct`).
3. **Stay:** each person stays inside a time drawn evenly from a window whose mean is the **average stay slider** value A and which never goes beyond `stores.max_stay_minutes` (90): `0` to `2A` when A ≤ 45 (default 45: 0–90 minutes), `2A − 90` to `90` when A > 45 (e.g. 60: 30–90). They leave at entry time + stay, or just before 20:00 if that comes first. Nobody stays longer than 1.5 hours; closing shortens the stays of late entrants a little, so the measured average can be slightly below A.
4. **Exits:** in each batch, the people whose leave time falls in the batch leave. The simulator handles the people of one `ENTRY` event together: per batch it draws how many of them leave, from the share of their stay window (cut at closing) that the batch covers. The window is fixed when they enter, so a slider change applies to people entering afterwards.
5. **Closing:** everyone's leave time is before 20:00 local, so a store is empty at closing and entries and exits balance every day.
6. **Events:** per store and batch, at most one `ENTRY` and one `EXIT` event, whose `people_count` is the number of people; batches with zero people emit nothing. The `ENTRY` time is a random moment within the open part of the batch; the `EXIT` time is the latest moment within the batch at which its people can have left. Both are in local time.

## 6. Event shape

The payload follows `dataset.md` §3.3; the values the simulator sets:

| Field | Value |
|---|---|
| `event_id` | `sim-<simulation id>-<partition>-<offset, 10 digits>`, unique across simulations |
| `simulation_id` | The simulation's id: the real UTC time of the START, `YYYYMMDDTHHMMSSmmm`, e.g. `20261114T193627123`. Sortable, so the latest simulation is the highest id; the same in every event and sales transaction of the simulation. The pipeline's current-simulation views and the dashboard follow it (`warehouse.md` §6) |
| `store_id` | From `dim_store` (active stores only) |
| `sensor_id` | `PC-<city code>-01`, one sensor per store |
| `event_timestamp` | Local time of the store, `YYYY-MM-DDTHH:MM:SS.mmm`, no time zone |
| `event_type` | `ENTRY` or `EXIT` |
| `people_count` | ≥ 1 |

Envelope columns:

| Column | Value |
|---|---|
| `source_topic` | `people-counter-app` (the hand-written events of `05_…` use `people-counter-simulation`) |
| `source_partition` | One partition per macro region: `0` EUROPE, `1` AMERICAS, `2` ASIA |
| `source_offset` | Consecutive per partition. On START the simulator continues after the highest offset already in the table for this topic and partition |
| `source_timestamp` | The simulated UTC time at the end of the batch: when the simulated broker received it |

All simulated events pass the pipeline's validation rules, so they reach silver; none go to quarantine.

## 7. Writing the events

- **Empty at START:** every START first runs `DELETE FROM` on `simulated_event_source` and `simulated_sales_source`, so each run starts from empty sources and offsets restart at 1. The tables, their permissions and their Delta history stay (no drop: dropping needs table ownership and would remove the app's permissions). The 8 hand-written events of `src/sql/05_…` are removed too; rerun `05_…` to add them back.
- **No full refresh:** the pipeline keeps running through a START. Bronze skips the START's deletes (`skipChangeCommits`) and goes on with the new simulation's rows; silver keeps the earlier simulations, and the current-simulation views (`warehouse.md` §6) show only the new one, so the sales dashboard switches to it within seconds. The app and the pipeline stay decoupled: the app never starts the pipeline; keep the continuous job resumed (`readme.md`, "Running the pipeline"). The app says so next to the run state.
- **Statement:** one insert-only `MERGE` per batch into `simulated_event_source`, keyed on `source_topic`, `source_partition`, `source_offset`. A retried batch can't insert a row twice, and no row is ever updated or deleted, so bronze keeps streaming from the table.
- **Connection:** through the SQL warehouse (Serverless Starter Warehouse), as the app's service principal; one connection reused across batches and reopened after an error.
- **Background writer:** each batch goes into a queue; a separate writer thread writes the batches in order, each batch's people events before its sales transactions. If the warehouse is slower than the ticks, batches wait in the queue (**Waiting to be written** on screen) instead of slowing the simulation; the writer catches up when the load drops. At STOP or after 48 hours the generator stops and the writer finishes the queue (`WRITING`) before the run ends.
- **Chunks:** at most 10,000 rows per `MERGE` statement. Each `MERGE` costs about 1 second however small (measured: 1.1 s on average), so few large statements keep up with the ticks; a typical batch needs one statement per table.
- **Failure:** if a write fails twice in a row, the run stops with state `FAILED` and the error on screen; batches not yet written are dropped. Press START to begin a new run.

## 8. Volumes

With all three sliders at 3000 (measured with the generator over two simulated days):

| | Per simulated day (240 s) | Per real second |
|---|---|---|
| Visitors, EUROPE (100 stores) | ≈ 300,000 | ≈ 1,250 |
| Visitors, AMERICAS (60 stores) | ≈ 180,000 | ≈ 750 |
| Visitors, ASIA (40 stores) | ≈ 120,000 | ≈ 500 |
| Rows inserted | ≈ 8,000 | ≈ 33 (≈ 166 per 5 s batch, at most ≈ 420) |

Visitors scale linearly with the sliders; rows depend only on how many stores are open. A full run (48 simulated hours, 480 s) inserts ≈ 16,000 rows and ≈ 1.2 million visitors.

A run can end while some stores are open: their last `ENTRY` events have no matching closing `EXIT`, so `ENTRY` and `EXIT` totals balance per store and day only for days that reached closing time within the run.

## 9. Deployment and permissions

| Step | How |
|---|---|
| Before the first deploy | In the pipeline bundle, run `src/sql/01_…`, `02_…` (stores, in `test02_warehouse`), `04_…` (source table, in `test02_streaming`) and `08_…` to `12_…` (clients, products, sales source). See [`warehouse.md`](warehouse.md) §4. The app's permissions are granted on these tables, so they must exist |
| Check | `databricks bundle validate --strict -t dev --profile MPiunti`, from `apps/people_stream/` |
| Deploy | From `apps/people_stream/`: `databricks bundle deploy -t dev --profile MPiunti`, then `databricks bundle run people_stream -t dev --profile MPiunti` to start the app; or, in the workspace Git folder, open `apps/people_stream/` and use **Deployments** |
| Granted to the app | `CAN_USE` on the SQL warehouse; `SELECT` on `test02_warehouse.dim_store`, `dim_client` and `dim_product`; `SELECT` and `MODIFY` on `simulated_event_source` and `simulated_sales_source` (`MODIFY` also covers emptying them at START) |
| Stop paying for it | Stop the app under **Compute → Apps**; STOP alone only stops the simulation |

The pipeline bundle doesn't upload `apps/` (`sync.exclude` in the root `databricks.yml`), and the app bundle has its own state, so deploying one never changes the other.

## 10. Switch on and off

How to switch the whole solution on and off by hand in the Databricks UI: the two apps, the continuous job and, through it, the pipeline. The app's **Switch on / off** tab shows the same steps, from `apps/people_stream/app/operations.py`; change them there and here together (a test checks that they agree). Background: `readme.md`, "Running the pipeline".

**Switch on, in this order:**

| # | Where | Action | Why |
|---|---|---|---|
| 0 | Workspace → Git folder retail_people_counter_bundle | Pull | Only after new commits on main: brings the Git folder up to date. Deployed apps keep running their deployed version |
| 1 | Jobs & Pipelines → [dev michele_piunti] retail-simulator | Resume | First, because the pipeline needs about a minute to start: it's ready when the first events arrive |
| 2 | Compute → Apps → people-stream-michele-piunti | Start, and wait for Running | This app: the simulation engine |
| 3 | Compute → Apps → sales-bi-michele-piunti | Start | The BI engine; it can start at the same time as step 2 |
| 4 | This app, above the tabs | Check the cockpit switches, then press START | Begins a new simulation: 8 minutes (48 simulated hours), or until STOP |
| 5 | The sales dashboard app | Nothing to do | It switches to the new simulation within seconds; its footer shows the simulation id |

**Switch off:**

| # | Where | Action | Why |
|---|---|---|---|
| 1 | This app | Press STOP, or let the run finish | No more events or sales are written |
| 2 | Jobs & Pipelines → [dev michele_piunti] retail-simulator | Pause | The pipeline stops: no serverless compute running or billed |
| 3 | Compute → Apps → people-stream-michele-piunti and sales-bi-michele-piunti | Stop | The apps' compute stops |
| 4 | SQL warehouse (Serverless Starter Warehouse) | Nothing to do | It stops by itself after a while without queries |

- The SQL warehouse needs no step: it starts when an app first queries it.
- Don't re-run src/sql/15_create_current_simulation_views.sql: re-creating the views drops the sales dashboard's permission to read them.

**Credits:** this app is made by Michele Piunti in November 2026. Code: [github.com/MPiunti/nov26_stream](https://github.com/MPiunti/nov26_stream).
