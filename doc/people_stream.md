# People stream: the simulator app

Functional reference for the people-stream simulator: a Databricks app that generates people-counter events for every store and inserts them into the pipeline's source table, as if they arrived from Event Hubs.

The stores, opening hours, payload and `N_AVG_PEOPLE_*` parameters are defined in [`dataset.md`](dataset.md); this page describes how the simulator uses them.

## 1. Purpose and boundaries

| | |
|---|---|
| **What it does** | Simulates the people flow of all 200 stores and inserts the events into `workspace.test02_streaming.simulated_event_source` |
| **What it doesn't do** | Run the pipeline. The pipeline is triggered: run it (or schedule it) to move new events to bronze, silver and quarantine |
| **Bundle** | `apps/people_stream/`, bundle `retail_people_stream_bundle`. Separate from the pipeline bundle at the repo root: deployed, started and destroyed on its own |
| **App** | `people-stream-<user>` (e.g. `people-stream-michele-piunti`), under **Compute → Apps** |
| **Code** | `apps/people_stream/app/`: `app.py` (screen), `simulator.py` (generator, standard library only), `warehouse.py` (SQL warehouse reads and writes) |

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
| `n_avg_people.default.EUROPE` / `.AMERICAS` / `.ASIA` | 3000 each | `N_AVG_PEOPLE_EUROPE`, `_AMERICA`, `_ASIA`: average visitors per store per simulated day; slider start values and **Reset to defaults** |
| `n_avg_people.min`, `.max`, `.step` | 2000, 6000, 100 | Slider range |
| `simulation.real_seconds_per_sim_day` | 240 | Day length: 24 simulated hours in 240 real seconds, so 1 hour = 10 s |
| `simulation.max_run_sim_hours` | 48 | Longest run (= 480 real seconds with a 240 s day) |
| `simulation.tick_seconds` | 5 | Real seconds between batches (= 30 simulated minutes with a 240 s day) |

**Format:** nested `key: value` lines with two-space indents, whole numbers only, `#` comments. The app refuses to start, with the reason in its log, if the file has an unknown or missing key, a value that isn't a whole number, closing before opening, a default outside the slider range or off its step grid, or a batch longer than a run.

The rest of this page quotes the shipped values. `dataset.md` §4 and §5 describe the same assumptions for the data as a whole.

## 3. Screen

The screen has a header, always visible, and two tabs: **Simulator** (controls) and **Counters** (the dashboard).

| Control | Behaviour |
|---|---|
| **START** | Starts a new run from scratch: reads the stores and sets the simulated clock to the current time. The run lasts at most 48 simulated hours (480 s). Disabled while running |
| **STOP** | Ends the run: the generator quits after the batch it is writing, if any. Disabled while stopped |
| **Three vertical sliders (equalizer)** | `N_AVG_PEOPLE_EUROPE`, `N_AVG_PEOPLE_AMERICA`, `N_AVG_PEOPLE_ASIA`: average visitors per store per simulated day. Range 2000–6000, step 100, default 3000 (from `shop_config.yml`). A change applies from the next batch, also while running |
| **Reset to defaults** | Puts the three sliders back to `n_avg_people.default` |
| **Parameters** | The values read from `shop_config.yml`, with what each means |
| **Headline time** | Next to the title, while a run is `RUNNING`: the simulated UTC time rounded down to the hour, e.g. `2026-11-14 07:00 UTC`. Hidden otherwise |
| **Tabs** | **Simulator**: sliders, parameters and stream status; no charts. **Counters**: the in/out table, people per calendar date, and the cumulative people-out and people-in charts. START, STOP and the headline sit above the tabs |
| **In, out and still inside** (Counters tab) | Per region: people in (sum of `ENTRY`), people out (sum of `EXIT`) and their difference, the people still inside open stores |
| **People per calendar date** (Counters tab) | Bar chart: for each calendar date, one bar per region (grouped side by side) with the sum of `people_count` on that date. The date is the store's local date (from `event_timestamp`), the same day the in/out balance uses. A switch picks **People out (EXIT)** (default) or **People in (ENTRY)**. Each bar is that date's total, not a running total. The first and last dates of a run are partial, because the run starts and ends mid-day |
| **Cumulative people-in chart** (Counters tab) | One line per region, the running sum of `people_count` of the region's `ENTRY` events since START (y), against simulated UTC time (x). The x axis always spans the run's 48 simulated hours from START, so the lines grow left to right; one point per batch (at most 97). Colors are fixed per region (Europe blue, Americas orange, Asia aqua), with a legend, a label at each line's end, and a shared hover tooltip. The chart keeps the last run until the next START |
| **Cumulative people-out chart** (Counters tab) | The same chart for `EXIT` events: the running sum of `people_count` of the region's `EXIT` events since START (y) against simulated UTC time (x), over the run's 48 hours, same colors, legend, end labels and hover. Exits follow entries during the day and catch up at each store's 20:00 closing, so the lines climb in steps when a region closes |
| **Status** | State (`STOPPED` by STOP, `FINISHED` after 48 simulated hours, `STARTING`, `RUNNING`, `FAILED` with the error), simulated UTC time, start and end time, seconds left, rows written, batches, run id; per region: stores open now and visitors so far |

There is one simulation per app, shared by everyone who opens it: a second viewer sees the same run and the same slider values.

## 4. Time model

| Rule | Value |
|---|---|
| Speed | **24 simulated hours = 240 real seconds**: 1 simulated hour = 10 s, 1 simulated minute ≈ 0.17 s (factor 360) |
| Start | On **START**, simulated time = the current real UTC time |
| Store clock | Each store sees the simulated UTC time in its own `timezone_id`, with daylight-saving time |
| Batch (tick) | Every `simulation.tick_seconds` real seconds (shipped: **5 s = 30 simulated minutes**), the simulator emits the events of the simulated time since the previous batch |
| Run length | **At most 48 simulated hours = 480 real seconds.** The last batch ends exactly at start + 48 h; then the generator quits and the state becomes `FINISHED`. The app itself keeps running, ready for the next START |
| Restart | START always begins a new run from scratch, from the current real time, with a new run id and a new 480-second limit; the previous run's simulated time and store occupancy are not resumed |

The batch window follows the real clock, not a counter: if a write takes longer than a tick, the next batch covers the longer window, and simulated time never drifts.

## 5. One stream per store

Each store runs its own stream, 24 simulated hours a day:

1. **Opening hours:** events only between **10:00 and 20:00 local time**. Across the three macro regions some store is open at every UTC hour (see `dataset.md` §4), so the app writes around the clock.
2. **Entries:** for the open minutes of a batch, the number of people entering is drawn from a Poisson distribution with mean `N_AVG_PEOPLE_<region> × open minutes / 600`. With the default that's 150 per store per 30-minute batch.
3. **Exits:** drawn the same way, but never more than the people already inside from earlier batches.
4. **Closing:** in the batch that contains 20:00 local, everyone still inside leaves in a final `EXIT` at closing time. Entries and exits balance every day.
5. **Events:** per store and batch, at most one `ENTRY` and one `EXIT` event (plus the closing `EXIT`), whose `people_count` is the number of people; batches with zero people emit nothing. The event time is a random moment within the open part of the batch, in local time.

## 6. Event shape

The payload follows `dataset.md` §3.3; the values the simulator sets:

| Field | Value |
|---|---|
| `event_id` | `sim-<run id>-<partition>-<offset, 10 digits>`, unique across runs |
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

- **Statement:** one insert-only `MERGE` per batch into `simulated_event_source`, keyed on `source_topic`, `source_partition`, `source_offset`. A retried batch can't insert a row twice, and no row is ever updated or deleted, so bronze keeps streaming from the table.
- **Connection:** through the SQL warehouse (Serverless Starter Warehouse), as the app's service principal; one connection reused across batches and reopened after an error.
- **Failure:** if a write fails twice in a row, the run stops with state `FAILED` and the error on screen. Press START to begin a new run.

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
| Before the first deploy | In the pipeline bundle, run `src/sql/01_…`, `02_…` (stores with `macro_region`) and `04_…` (source table). The app's permissions are granted on these tables, so they must exist |
| Check | `databricks bundle validate --strict -t dev --profile MPiunti`, from `apps/people_stream/` |
| Deploy | From `apps/people_stream/`: `databricks bundle deploy -t dev --profile MPiunti`, then `databricks bundle run people_stream -t dev --profile MPiunti` to start the app; or, in the workspace Git folder, open `apps/people_stream/` and use **Deployments** |
| Granted to the app | `CAN_USE` on the warehouse; `SELECT` on `dim_store`; `SELECT` and `MODIFY` on `simulated_event_source` |
| Stop paying for it | Stop the app under **Compute → Apps**; STOP alone only stops the simulation |

The pipeline bundle doesn't upload `apps/` (`sync.exclude` in the root `databricks.yml`), and the app bundle has its own state, so deploying one never changes the other.
