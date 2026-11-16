"""Tests of the people-stream simulator app (apps/people_stream) and doc/people_stream.md. Standard library only."""
import json
import os
import re
import sys
import threading
import time
import unittest
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from helpers import path, read_text

sys.path.insert(0, path("apps", "people_stream", "app"))
try:
    import simulator as sim
    import sql_warehouse as warehouse
    from zoneinfo import ZoneInfo
    ZoneInfo("Europe/Rome")
except Exception as exc:  # no time-zone database on this machine
    sim = None
    SKIP_REASON = f"simulator can't load: {exc} (pip install tzdata)"
else:
    SKIP_REASON = ""

from test_project_consistency import _rejections, _store_ids

APP = ("apps", "people_stream")
MACRO = {"IT": "EUROPE", "FR": "EUROPE", "DE": "EUROPE", "ES": "EUROPE", "NL": "EUROPE", "BE": "EUROPE",
         "AT": "EUROPE", "PT": "EUROPE", "SE": "EUROPE", "US": "AMERICAS", "CN": "ASIA", "JP": "ASIA", "KR": "ASIA"}
HALF_HOUR = timedelta(minutes=30)


def _stores():
    """The 200 stores of 02_populate_dim_store.sql, as the app reads them."""
    sql = read_text("src", "sql", "02_populate_dim_store.sql")
    rows = re.findall(r"\('(\w\w)', '[^']*', '(\w\w)', '[^']*', '[^']*', '([^']*)', (\d+)\)", sql)
    return [sim.Store(f"{c}-{code}-{n:03d}", MACRO[c], tz) for c, code, tz, k in rows for n in range(1, int(k) + 1)]


def _run(generator, days, n_avg, start=datetime(2026, 11, 13, 0, 0, tzinfo=timezone.utc), step=HALF_HOUR):
    rows, windows, t = [], [], start
    for _ in range(int(days * 86400 / step.total_seconds())):
        batch = generator.tick(t, t + step, n_avg)
        rows += batch
        windows += [(t, t + step)] * len(batch)
        t += step
    return rows, windows


def _events(rows):
    return [json.loads(r["raw_event"]) for r in rows]


@unittest.skipIf(sim is None, SKIP_REASON)
class TimeModelTests(unittest.TestCase):

    def test_240_seconds_are_one_day_and_10_seconds_one_hour(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.assertEqual(sim.REAL_SECONDS_PER_SIM_DAY, 240)
        self.assertEqual(sim.sim_time(start, 240) - start, timedelta(days=1))
        self.assertEqual(sim.sim_time(start, 10) - start, timedelta(hours=1))

    def test_default_tick_is_30_simulated_minutes(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.assertEqual(sim.sim_time(start, sim.DEFAULT_TICK_SECONDS) - start, HALF_HOUR)
        self.assertIn("tick_seconds: 5 ", read_text(*APP, "app", "shop_config.yml"))

    def test_opening_hours(self):
        self.assertEqual((sim.OPEN_HOUR, sim.CLOSE_HOUR), (10, 20))
        day = datetime(2026, 1, 1)
        self.assertEqual(sim.open_windows(day.replace(hour=9), day.replace(hour=11)),
                         [(day.replace(hour=10), day.replace(hour=11))])
        self.assertEqual(sim.open_windows(day.replace(hour=20), day.replace(hour=23)), [])
        self.assertTrue(sim.closes_within(day.replace(hour=19, minute=45), day.replace(hour=20, minute=15)))
        self.assertFalse(sim.closes_within(day.replace(hour=20), day.replace(hour=21)))

    def test_start_uses_current_time(self):
        now = datetime(2026, 11, 13, 21, 0, tzinfo=timezone.utc)
        s = sim.Simulation(lambda: _stores()[:3], lambda: {}, lambda rows: None, tick_seconds=0.01,
                           now=lambda: now)
        s.start()
        time.sleep(0.2)
        s.stop()
        snap = s.snapshot()
        self.assertTrue(snap["start_utc"].startswith("2026-11-13 21:00:00"))
        self.assertEqual(snap["state"], "STOPPED")


class _FastClock:
    """Fake monotonic clock: every call advances by `step` real seconds."""

    def __init__(self, step):
        self.t, self.step = 0.0, step

    def __call__(self):
        self.t += self.step
        return self.t


@unittest.skipIf(sim is None, SKIP_REASON)
class RunLengthTests(unittest.TestCase):
    START = datetime(2026, 11, 13, 21, 0, tzinfo=timezone.utc)

    def _simulation(self, written):
        return sim.Simulation(lambda: _stores(), lambda: {}, written.extend, tick_seconds=0.001,
                              clock=_FastClock(7), now=lambda: self.START)

    def test_limit_is_48_simulated_hours_or_480_seconds(self):
        self.assertEqual(sim.MAX_RUN_SIM_HOURS, 48)
        self.assertEqual(sim.MAX_RUN_REAL_SECONDS, 480)

    def test_run_finishes_by_itself_at_48_hours(self):
        written = []
        s = self._simulation(written)
        s.start()
        s._thread.join(timeout=10)
        snap = s.snapshot()
        self.assertEqual(snap["state"], "FINISHED")
        end = self.START + timedelta(hours=48)
        self.assertTrue(snap["sim_utc"].startswith(str(end)[:19]), snap["sim_utc"])
        self.assertEqual(snap["remaining_seconds"], 0)
        self.assertTrue(written)
        self.assertLessEqual(max(r["source_timestamp"] for r in written), end)
        self.assertFalse(s.running)

    def test_start_again_begins_from_scratch(self):
        written = []
        s = self._simulation(written)
        s.start()
        s._thread.join(timeout=10)
        first = s.snapshot()
        s.start()
        s._thread.join(timeout=10)
        second = s.snapshot()
        self.assertNotEqual(first["run_id"], second["run_id"])
        self.assertEqual(second["state"], "FINISHED")
        self.assertEqual(first["rows_written"] + second["rows_written"], len(written))
        self.assertLess(second["rows_written"], len(written))  # counters restart with each run

    def test_history_feeds_the_cumulative_chart(self):
        written = []
        s = self._simulation(written)
        s.start()
        s._thread.join(timeout=10)
        snap = s.snapshot()
        history = snap["history"]
        zero = {r: 0 for r in sim.REGIONS}
        self.assertEqual(history[0], {"sim_utc": str(self.START), "entries": zero, "exits": zero})
        self.assertTrue(history[-1]["sim_utc"].startswith(str(self.START + timedelta(hours=48))[:19]))
        self.assertLessEqual(len(history), 97)
        for kind, event_type in (("entries", "ENTRY"), ("exits", "EXIT")):
            for region in sim.REGIONS:
                values = [p[kind][region] for p in history]
                self.assertEqual(values, sorted(values), f"{kind} {region} isn't cumulative")
                self.assertEqual(values[-1], snap[kind][region])
            people = sum(json.loads(r["raw_event"])["people_count"] for r in written
                         if json.loads(r["raw_event"])["event_type"] == event_type)
            self.assertEqual(sum(history[-1][kind].values()), people, kind)
        for point in history:  # nobody leaves before entering
            for region in sim.REGIONS:
                self.assertLessEqual(point["exits"][region], point["entries"][region])

    def test_headline_shows_the_simulated_hour_only_while_running(self):
        self.assertEqual(sim.headline_time({"state": "RUNNING", "sim_utc": "2026-11-14 07:42:10+00:00"}),
                         "2026-11-14 07:00 UTC")
        self.assertEqual(sim.headline_time({"state": "FINISHED", "sim_utc": "2026-11-15 21:00:00+00:00"}), "")
        self.assertEqual(sim.headline_time({"state": "STOPPED", "sim_utc": None}), "")

    def test_chart_spans_48_hours_with_fixed_region_colors(self):
        chart = read_text(*APP, "app", "charts.py")
        self.assertIn('REGION_COLOR = {"EUROPE": "#2a78d6", "AMERICAS": "#eb6834", "ASIA": "#1baf7a"}', chart)
        self.assertIn("range=[start, start + timedelta(hours=max_hours)]", chart)
        self.assertIn('"width": 2', chart)
        app = read_text(*APP, "app", "app.py")
        self.assertIn('"entries-chart", charts.cumulative_entries(', app)
        self.assertIn('"exits-chart", charts.cumulative_exits(', app)
        self.assertIn('y = [p[kind][region] for p in history]', chart)

    def test_charts_only_on_the_counters_tab(self):
        app = read_text(*APP, "app", "app.py")
        self.assertIn('dbc.Tab(label="Simulator", tab_id="tab-simulator", children=simulator_tab(n_avg))', app)
        self.assertIn('dbc.Tab(label="Counters", tab_id="tab-counters", children=counters_tab())', app)
        simulator_tab = app.split("def simulator_tab(", 1)[1].split("\ndef ", 1)[0]
        counters_tab = app.split("def counters_tab(", 1)[1].split("\ndef ", 1)[0]
        self.assertNotIn("dcc.Graph", simulator_tab)
        self.assertNotIn("chart_card", simulator_tab)
        for graph in ('id="daily-chart"', '"exits-chart"', '"entries-chart"', 'id="exit-stats"'):
            self.assertIn(graph, counters_tab)

    def test_daily_bar_chart_groups_regions_per_date(self):
        chart = read_text(*APP, "app", "charts.py")
        self.assertIn('barmode="group"', chart)
        self.assertIn('y=[daily[d][region][kind] for d in dates]', chart)
        self.assertIn('Input("daily-kind", "value")', read_text(*APP, "app", "app.py"))

    def test_daily_totals_per_local_date(self):
        written = []
        s = self._simulation(written)
        s.start()
        s._thread.join(timeout=10)
        snap = s.snapshot()
        daily = snap["daily"]
        expected = defaultdict(int)
        for row in written:
            e = json.loads(row["raw_event"])
            kind = "entries" if e["event_type"] == "ENTRY" else "exits"
            expected[(e["event_timestamp"][:10], sim.REGIONS[row["source_partition"]], kind)] += e["people_count"]
        got = {(d, r, k): daily[d][r][k] for d in daily for r in sim.REGIONS for k in ("entries", "exits")}
        self.assertEqual({key: v for key, v in got.items() if v}, dict(expected))
        for kind in ("entries", "exits"):
            for region in sim.REGIONS:
                self.assertEqual(sum(daily[d][region][kind] for d in daily), snap[kind][region])
        # 48 hours from 21:00 UTC touch 3 store-local dates in every region
        self.assertEqual(sorted(daily), ["2026-11-13", "2026-11-14", "2026-11-15", "2026-11-16"][:len(daily)])

    def test_ticks_keep_their_schedule_when_writing_is_slow(self):
        """Batches (and chart points) come every tick even if each write takes 4 ticks; nothing is lost."""
        written = []

        def slow_write(rows):
            time.sleep(0.2)
            written.extend(rows)

        s = sim.Simulation(lambda: _stores(), lambda: {}, slow_write, tick_seconds=0.05,
                           now=lambda: self.START)
        s.start()
        time.sleep(0.8)
        running = s.snapshot()
        self.assertGreaterEqual(running["batches"], 10, "about 16 ticks in 0.8 s, not 4")
        self.assertEqual(len(running["history"]), running["batches"] + 1)
        self.assertGreater(running["pending_batches"], 0, "slow writes queue up instead of slowing ticks")
        s.stop(wait=False)
        self.assertIn(s.snapshot()["state"], ("STOPPING", "WRITING"))
        s._thread.join(timeout=30)
        done = s.snapshot()
        self.assertEqual(done["state"], "STOPPED")
        self.assertEqual(done["pending_batches"], 0)
        generated = sum(1 for p in done["history"][1:])  # every generated batch was written
        self.assertEqual(done["rows_written"], len(written))
        self.assertGreaterEqual(generated, running["batches"])

    def test_stop_quits_the_generator(self):
        s = sim.Simulation(lambda: _stores()[:3], lambda: {}, lambda rows: None, tick_seconds=0.01,
                           now=lambda: self.START)
        s.start()
        time.sleep(0.1)
        s.stop()
        self.assertFalse(s.running)
        self.assertEqual(s.snapshot()["state"], "STOPPED")


@unittest.skipIf(sim is None, SKIP_REASON)
class SlidersTests(unittest.TestCase):

    def test_range_and_default(self):
        self.assertEqual((sim.N_AVG_MIN, sim.N_AVG_MAX, sim.N_AVG_STEP), (2000, 6000, 100))
        self.assertEqual(sim.N_AVG_DEFAULTS, {"EUROPE": 3000, "AMERICAS": 3000, "ASIA": 3000})
        self.assertEqual(sim.clamp_n_avg(1500), 2000)
        self.assertEqual(sim.clamp_n_avg(9000), 6000)
        self.assertEqual(sim.clamp_n_avg(3049), 3000)
        self.assertEqual(sim.clamp_n_avg("4500"), 4500)

    def test_slider_change_applies_to_its_region(self):
        s = sim.Simulation(lambda: [], lambda: {}, lambda rows: None)
        s.set_n_avg("ASIA", 5555)
        self.assertEqual(s.snapshot()["n_avg"], {"EUROPE": 3000, "AMERICAS": 3000, "ASIA": 5600})

    def test_browser_tab_title_is_stable(self):
        app = read_text(*APP, "app", "app.py")
        self.assertIn('APP_TITLE = "People stream simulator"', app)
        self.assertIn("title=APP_TITLE, update_title=None", app)  # no "Updating..." flicker on every refresh
        self.assertIn("document.title = title", app)

    def test_browser_title_shows_the_simulated_hour_while_running(self):
        running = {"state": "RUNNING", "sim_utc": "2026-11-14 07:42:10+00:00"}
        self.assertEqual(sim.browser_title(running, "People stream simulator"),
                         "People stream simulator · 2026-11-14 07:00 UTC")
        self.assertEqual(sim.browser_title({"state": "FINISHED", "sim_utc": "2026-11-14 07:42:10+00:00"},
                                           "People stream simulator"), "People stream simulator")

    def test_app_has_three_vertical_sliders(self):
        app = read_text(*APP, "app", "app.py")
        self.assertIn("vertical=True", app)
        self.assertIn("min=sim.N_AVG_MIN, max=sim.N_AVG_MAX, step=sim.N_AVG_STEP", app)
        self.assertEqual(len(sim.REGIONS), 3)
        for button in ('"START", id="start"', '"STOP", id="stop"'):
            self.assertIn(button, app)


@unittest.skipIf(sim is None, SKIP_REASON)
class StreamTests(unittest.TestCase):

    def test_daily_visitors_match_n_avg_per_region(self):
        n_avg = {"EUROPE": 3000, "AMERICAS": 6000, "ASIA": 2000}
        rows, _ = _run(sim.Generator(_stores(), seed=7), days=3, n_avg=n_avg)
        stores = defaultdict(int)
        for s in _stores():
            stores[s.macro_region] += 1
        entries = defaultdict(int)
        for row, e in zip(rows, _events(rows)):
            if e["event_type"] == "ENTRY":
                entries[sim.REGIONS[row["source_partition"]]] += e["people_count"]
        for region, n in n_avg.items():
            per_store_day = entries[region] / 3 / stores[region]
            self.assertAlmostEqual(per_store_day / n, 1, delta=0.03, msg=f"{region}: {per_store_day:.0f}/day")

    def test_events_only_during_local_opening_hours(self):
        tz = {s.store_id: s.timezone_id for s in _stores()}
        rows, windows = _run(sim.Generator(_stores(), seed=3), days=1, n_avg={r: 3000 for r in sim.REGIONS})
        self.assertTrue(rows)
        for e, (w_from, w_to) in zip(_events(rows), windows):
            local = datetime.fromisoformat(e["event_timestamp"])
            self.assertTrue(10 <= local.hour < 20, e)
            zone = ZoneInfo(tz[e["store_id"]])
            self.assertLessEqual(w_from.astimezone(zone).replace(tzinfo=None), local, e)
            self.assertLess(local, w_to.astimezone(zone).replace(tzinfo=None), e)

    def test_nobody_stays_longer_than_max_stay(self):
        """Every person leaves at most max_stay_minutes after entering, and by closing time."""
        self.assertEqual(sim.MAX_STAY_MINUTES, 90)
        for store in _stores()[::20]:  # 10 stores across the regions
            stream = sim.StoreStream(store)
            rng = sim.random.Random(store.store_id)
            t = datetime(2026, 11, 13, 0, 0, tzinfo=timezone.utc)
            for _ in range(96):
                local_to = (t + HALF_HOUR).astimezone(stream.tz).replace(tzinfo=None)
                for _, count, ts in sim.store_tick(stream, t, t + HALF_HOUR, 3000, rng):
                    self.assertLess(ts, local_to)
                    self.assertTrue(sim.is_open(ts), ts)
                for cohort in stream.cohorts:  # whoever is still inside entered less than 90 min ago
                    self.assertGreater(cohort.entered + sim.MAX_STAY, local_to, store.store_id)
                    self.assertGreater(cohort.closing, local_to)
                    self.assertGreater(cohort.inside, 0)
                t += HALF_HOUR

    def test_stay_window_has_the_slider_average_and_respects_max_stay(self):
        self.assertEqual((sim.AVG_STAY_DEFAULT, sim.AVG_STAY_MIN, sim.AVG_STAY_MAX, sim.AVG_STAY_STEP), (45, 5, 85, 5))
        for avg in range(5, 90, 5):
            lo, hi = sim.stay_window(avg)
            self.assertAlmostEqual((lo + hi) / 2, avg)
            self.assertGreaterEqual(lo, 0)
            self.assertLessEqual(hi, sim.MAX_STAY_MINUTES)
        self.assertEqual(sim.stay_window(45), (0, 90))
        self.assertEqual(sim.stay_window(60), (30, 90))
        self.assertEqual((sim.clamp_avg_stay(2), sim.clamp_avg_stay(62), sim.clamp_avg_stay(99)), (5, 60, 85))

    def test_measured_average_stay_follows_the_slider(self):
        for avg in (20, 45, 70):
            g = sim.Generator(_stores()[:40], seed=avg)  # 40 Italian stores
            t = datetime(2026, 11, 13, 8, 0, tzinfo=timezone.utc)  # 09:00 in Rome, before opening
            for _ in range(24):  # 12 hours: the whole opening day
                g.tick(t, t + HALF_HOUR, {r: 3000 for r in sim.REGIONS}, avg)
                t += HALF_HOUR
            measured = g.measured_stay()["EUROPE"]
            self.assertAlmostEqual(measured, avg, delta=max(3, avg * 0.08), msg=f"slider {avg}, measured {measured}")

    def test_flagships_get_45_percent_more_traffic(self):
        self.assertEqual(sim.FLAGSHIP_IDS, {"IT-MI-001", "US-NY-001"})
        milan = [s for s in _stores() if s.store_id.startswith("IT-MI-")]
        rows, _ = _run(sim.Generator(milan, seed=9), days=6, n_avg={r: 3000 for r in sim.REGIONS})
        entries = defaultdict(int)
        for e in _events(rows):
            if e["event_type"] == "ENTRY":
                entries[e["store_id"]] += e["people_count"]
        others = sum(v for k, v in entries.items() if k != "IT-MI-001") / (len(milan) - 1)
        self.assertAlmostEqual(entries["IT-MI-001"] / others, 1.45, delta=0.05)

    def test_app_has_the_average_stay_slider(self):
        app = read_text(*APP, "app", "app.py")
        self.assertIn('id="avg-stay", min=sim.AVG_STAY_MIN, max=sim.AVG_STAY_MAX, step=sim.AVG_STAY_STEP', app)
        self.assertIn('Output("avg-stay", "value")', app)  # Reset to defaults
        self.assertIn("stay_card(snapshot[\"avg_stay\"])", app)
        s = sim.Simulation(lambda: [], lambda: {}, lambda rows: None)
        s.set_avg_stay(33)
        self.assertEqual(s.snapshot()["avg_stay"], 35)

    def test_stays_are_spread_evenly_up_to_max_stay(self):
        """A cohort leaves evenly over the 90 minutes after entering: one sixth per 15 minutes."""
        stream = sim.StoreStream(_stores()[0])  # Milan
        entered = datetime(2026, 11, 13, 11, 0)
        stream.cohorts.append(sim.Cohort(entered, entered.replace(hour=19, minute=59, second=59), 60000))
        rng, quarter = sim.random.Random(1), timedelta(minutes=15)
        t = datetime(2026, 11, 13, 10, 0, tzinfo=timezone.utc)  # 11:00 in Rome
        out = []
        for _ in range(7):
            events = sim.store_tick(stream, t, t + quarter, 0, rng)
            out.append(sum(c for kind, c, _ in events if kind == "EXIT"))
            t += quarter
        self.assertEqual(sum(out), 60000)
        self.assertEqual(out[-1], 0, "everyone has left after 90 minutes")
        for n in out[:6]:
            self.assertAlmostEqual(n / 10000, 1, delta=0.05)

    def test_closing_cuts_the_stay(self):
        stream = sim.StoreStream(_stores()[0])
        entered = datetime(2026, 11, 13, 19, 45)  # 15 minutes before closing
        stream.cohorts.append(sim.Cohort(entered, entered.replace(hour=19, minute=59, second=59), 100))
        t = datetime(2026, 11, 13, 18, 45, tzinfo=timezone.utc)  # 19:45 in Rome
        events = sim.store_tick(stream, t, t + timedelta(minutes=30), 0, sim.random.Random(2))
        self.assertEqual([(k, c) for k, c, _ in events], [("EXIT", 100)])
        self.assertLess(events[0][2], entered.replace(hour=20, minute=0))

    def test_exits_balance_entries_every_store_day_that_closes(self):
        """For every store and local day whose 20:00 closing falls within the run: people in = people out.

        Days still open when the run ends (48 h limit or STOP) are left unbalanced, as documented.
        """
        stores = _stores()
        zones = {s.store_id: ZoneInfo(s.timezone_id) for s in stores}
        for start in (datetime(2026, 11, 13, 15, 42, tzinfo=timezone.utc),   # winter, starts mid-day
                      datetime(2026, 7, 15, 9, 5, tzinfo=timezone.utc)):      # summer time
            g = sim.Generator(stores, seed=start.hour)
            rows, _ = _run(g, days=2, n_avg={r: 3000 for r in sim.REGIONS}, start=start)
            end = start + timedelta(hours=48)
            balance = defaultdict(lambda: [0, 0])
            for e in _events(rows):
                self.assertGreaterEqual(e["people_count"], 1)
                balance[(e["store_id"], e["event_timestamp"][:10])][e["event_type"] == "EXIT"] += e["people_count"]
            closed = 0
            for (store_id, day), (people_in, people_out) in balance.items():
                self.assertLessEqual(people_out, people_in, (store_id, day))
                if datetime.fromisoformat(f"{day}T20:00") <= end.astimezone(zones[store_id]).replace(tzinfo=None):
                    self.assertEqual(people_in, people_out, f"{store_id} {day}: {people_in} in, {people_out} out")
                    closed += 1
            self.assertEqual(closed, 400, "every store closes twice in 48 hours")
            inside = {s.store.store_id: s.occupancy for s in g.streams}
            for store_id, people in inside.items():  # only stores still open at the end keep people inside
                if people:
                    self.assertTrue(sim.is_open(end.astimezone(zones[store_id])), store_id)

    def test_every_event_passes_the_silver_rules(self):
        rows, _ = _run(sim.Generator(_stores(), seed=11), days=1, n_avg={r: 3000 for r in sim.REGIONS})
        store_ids = _store_ids()
        for row in rows:
            self.assertEqual(_rejections(row["raw_event"], store_ids), [], row["raw_event"])

    def test_envelope_offsets_and_ids(self):
        g = sim.Generator(_stores(), next_offsets={0: 101, 1: 1, 2: 7}, run_id="abc12345", seed=1)
        rows, _ = _run(g, days=1, n_avg={r: 3000 for r in sim.REGIONS})
        by_partition = defaultdict(list)
        for row, e in zip(rows, _events(rows)):
            self.assertEqual(row["source_topic"], "people-counter-app")
            self.assertEqual(row["source_partition"], sim.PARTITION[MACRO[e["store_id"][:2]]])
            self.assertEqual(e["event_id"], f"sim-abc12345-{row['source_partition']}-{row['source_offset']:010d}")
            by_partition[row["source_partition"]].append(row["source_offset"])
        for partition, first in {0: 101, 1: 1, 2: 7}.items():
            offsets = by_partition[partition]
            self.assertEqual(offsets, list(range(first, first + len(offsets))))

    def test_failed_write_stops_the_run(self):
        def fail(rows):
            raise RuntimeError("warehouse down")
        s = sim.Simulation(lambda: _stores(), lambda: {}, fail, tick_seconds=0.01,
                           now=lambda: datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc))
        s.start()
        s._thread.join(timeout=5)
        snap = s.snapshot()
        self.assertEqual(snap["state"], "FAILED")
        self.assertIn("warehouse down", snap["error"])


@unittest.skipIf(sim is None, SKIP_REASON)
class WarehouseSqlTests(unittest.TestCase):

    def test_insert_is_an_insert_only_merge_on_message_identity(self):
        rows, _ = _run(sim.Generator(_stores()[:3], seed=1), days=1, n_avg={r: 3000 for r in sim.REGIONS})
        sql = warehouse.insert_sql("workspace.test02_streaming.simulated_event_source", rows)
        self.assertTrue(sql.startswith("MERGE INTO workspace.test02_streaming.simulated_event_source"))
        for col in ("source_topic", "source_partition", "source_offset"):
            self.assertIn(f"target.{col} <=> source.{col}", sql)
        self.assertIn("WHEN NOT MATCHED THEN INSERT", sql)
        self.assertNotIn("WHEN MATCHED", sql.replace("WHEN NOT MATCHED", ""))
        self.assertEqual(sql.count("TIMESTAMP'"), len(rows))

    def test_literals_are_escaped(self):
        self.assertEqual(warehouse._literal("a'b\\c"), "'a\\'b\\\\c'")
        self.assertEqual(warehouse._literal(5), "5")
        with self.assertRaises(TypeError):
            warehouse._literal(None)

    def test_table_names_are_validated(self):
        os.environ["SOURCE_TABLE"] = "x; DROP TABLE y"
        try:
            with self.assertRaises(ValueError):
                warehouse.table("SOURCE_TABLE")
        finally:
            del os.environ["SOURCE_TABLE"]


@unittest.skipIf(sim is None, SKIP_REASON)
class ShopConfigTests(unittest.TestCase):
    """shop_config.yml holds every store and simulation parameter; the app reads and shows them."""

    def _load(self, text):
        import shop_config
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False, encoding="utf-8") as f:
            f.write(text)
        try:
            return shop_config.load(f.name)
        finally:
            os.remove(f.name)

    def test_shipped_values(self):
        import shop_config
        cfg = shop_config.load()
        self.assertEqual((cfg.opening_hour, cfg.closing_hour), (10, 20))
        self.assertEqual(cfg.n_avg_default, {"EUROPE": 3000, "AMERICAS": 3000, "ASIA": 3000})
        self.assertEqual((cfg.n_avg_min, cfg.n_avg_max, cfg.n_avg_step), (2000, 6000, 100))
        self.assertEqual((cfg.real_seconds_per_sim_day, cfg.max_run_sim_hours, cfg.tick_seconds), (240, 48, 5))
        self.assertEqual((cfg.time_scale, cfg.max_run_real_seconds, cfg.tick_sim_minutes), (360, 480, 30))

    def test_simulator_takes_every_parameter_from_the_config(self):
        cfg = sim.CONFIG
        self.assertEqual((sim.OPEN_HOUR, sim.CLOSE_HOUR), (cfg.opening_hour, cfg.closing_hour))
        self.assertEqual(sim.N_AVG_DEFAULTS, cfg.n_avg_default)
        self.assertEqual((sim.N_AVG_MIN, sim.N_AVG_MAX, sim.N_AVG_STEP),
                         (cfg.n_avg_min, cfg.n_avg_max, cfg.n_avg_step))
        self.assertEqual((sim.REAL_SECONDS_PER_SIM_DAY, sim.MAX_RUN_SIM_HOURS, sim.DEFAULT_TICK_SECONDS),
                         (cfg.real_seconds_per_sim_day, cfg.max_run_sim_hours, cfg.tick_seconds))
        code = re.sub(r'"""[\s\S]*?"""|#[^\n]*', "",
                      read_text(*APP, "app", "simulator.py") + read_text(*APP, "app", "app.py"))
        for literal in ("240", "480", "3000", "2000", "6000", "= 10", "= 20", "= 48"):
            self.assertNotIn(literal, code, f"{literal} is hard-coded; take it from shop_config.yml")

    def test_app_shows_the_parameters(self):
        import shop_config
        rows = shop_config.describe(shop_config.load())
        self.assertEqual([r[1] for r in rows], [
            "10:00 - 20:00", "90 min = 1.5 h", "45 min (slider 5 - 85, step 5)", "70% local, 30% visitors",
            "IT-MI-001, US-NY-001: traffic 145%, 30% local", "sales on, e-commerce on",
            "10% of a country's sales value; 15% in US, CN", "90% of list price",
            "Europe 3,000 / Americas 3,000 / Asia 3,000", "2,000 - 6,000, step 100",
            "All regions: SHOES 5%, BAGS 2%, READY_TO_WEAR 6%, ACCESSORIES 3%, TRAVEL 2%, SUNGLASSES 2%",
            "0% - 100%, step 1",
            "240 s = 24 h", "48 h = 480 s", "5 s = 30 min"])
        self.assertIn("parameters_card()", read_text(*APP, "app", "app.py"))
        self.assertNotIn("SIM_TICK_SECONDS", read_text(*APP, "app", "app.yaml"))

    def test_other_values_take_effect(self):
        cfg = self._load(read_text(*APP, "app", "shop_config.yml")
                         .replace("opening_hour: 10", "opening_hour: 9")
                         .replace("real_seconds_per_sim_day: 240", "real_seconds_per_sim_day: 480"))
        self.assertEqual((cfg.opening_hour, cfg.time_scale, cfg.max_run_real_seconds), (9, 180, 960))

    def test_bad_files_are_rejected(self):
        good = read_text(*APP, "app", "shop_config.yml")
        for bad, why in ((good.replace("closing_hour: 20", "closing_hour: 8"), "closing before opening"),
                         (good.replace("    ASIA: 3000", "    ASIA: 3050"), "default off the step grid"),
                         (good.replace("    ASIA: 3000", "    ASIA: 9000"), "default out of range"),
                         (good.replace("  tick_seconds: 5", "  tick_seconds: 0"), "zero tick"),
                         (good.replace("  step: 100", "  step: 100\n  extra: 1"), "unknown key"),
                         (good.replace("  max_run_sim_hours: 48", ""), "missing key"),
                         (good.replace("opening_hour: 10", "opening_hour: ten"), "not a number"),
                         (good.replace("opening_hour: 10", "opening_hour: 10.5"), "not whole")):
            with self.assertRaises(ValueError, msg=why):
                self._load(bad)


class AppBundleTests(unittest.TestCase):

    def test_every_app_file_is_valid_python(self):
        """app.py can't be imported here (no Dash), so at least parse it: catches syntax and indent errors."""
        import ast
        folder = path(*APP, "app")
        for f in sorted(os.listdir(folder)):
            if f.endswith(".py"):
                ast.parse(read_text(*APP, "app", f), filename=f)

    def test_separate_bundle(self):
        app_yml = read_text(*APP, "databricks.yml")
        root_yml = read_text("databricks.yml")
        self.assertIn('name: "retail_people_stream_bundle"', app_yml)
        self.assertNotIn("retail_people_stream_bundle", root_yml)
        self.assertRegex(root_yml, r"sync:\s*\n\s*exclude:\s*\n\s*- apps/\*\*", "root bundle must not upload apps/")
        self.assertEqual(app_yml.count("host: https://dbc-06fb0002-68c5.cloud.databricks.com"), 2)

    def test_app_resources_grant_what_the_app_uses(self):
        res = read_text(*APP, "resources", "people_stream.app.yml")
        self.assertIn("source_code_path: ../app", res)
        grants = re.findall(r"securable_full_name: \$\{var\.catalog\}\.\$\{var\.(\w+)\}\.(\w+)\s*\n\s*"
                            r"securable_type: TABLE\s*\n\s*permission: (\w+)", res)
        self.assertEqual(sorted(grants), [
            ("schema", "simulated_event_source", "MODIFY"), ("schema", "simulated_event_source", "SELECT"),
            ("schema", "simulated_sales_source", "MODIFY"), ("schema", "simulated_sales_source", "SELECT"),
            ("warehouse_schema", "dim_client", "SELECT"), ("warehouse_schema", "dim_product", "SELECT"),
            ("warehouse_schema", "dim_store", "SELECT")])
        self.assertIn("permission: CAN_USE", res)

    def test_app_yaml_tables_match_bundle_variables(self):
        app_yml = read_text(*APP, "databricks.yml")
        catalog = re.search(r"catalog:\n(?:\s+.*\n)*?\s+default: (\S+)", app_yml).group(1)
        schema = re.search(r"^  schema:\n(?:\s+.*\n)*?\s+default: (\S+)", app_yml, re.M).group(1)
        warehouse = re.search(r"^  warehouse_schema:\n(?:\s+.*\n)*?\s+default: (\S+)", app_yml, re.M).group(1)
        app_yaml = read_text(*APP, "app", "app.yaml")
        for table in ("dim_store", "dim_client", "dim_product"):
            self.assertIn(f"value: {catalog}.{warehouse}.{table}", app_yaml)
        for table in ("simulated_event_source", "simulated_sales_source"):
            self.assertIn(f"value: {catalog}.{schema}.{table}", app_yaml)
        self.assertIn("valueFrom: sql-warehouse", app_yaml)

    def test_app_name_fits_30_characters(self):
        self.assertLessEqual(len("people-stream-michele-piunti"), 30)

    def test_requirements_are_pinned(self):
        for line in read_text(*APP, "app", "requirements.txt").split():
            self.assertRegex(line, r"^[A-Za-z0-9_.-]+==[\w.]+$")


@unittest.skipIf(sim is None, SKIP_REASON)
class SimulationIdTests(unittest.TestCase):

    def test_simulation_id_is_the_utc_start_time_and_sortable(self):
        early = sim.new_simulation_id(datetime(2026, 11, 14, 19, 36, 27, 123456, tzinfo=timezone.utc))
        late = sim.new_simulation_id(datetime(2026, 11, 14, 19, 36, 27, 124000, tzinfo=timezone.utc))
        self.assertEqual(early, "20261114T193627123")
        self.assertLess(early, late, "a later START has a higher id, so MAX(simulation_id) is the latest")
        self.assertLess(late, sim.new_simulation_id(datetime(2027, 1, 1, tzinfo=timezone.utc)))
        self.assertRegex(sim.new_simulation_id(), r"^\d{8}T\d{9}$")
        self.assertNotIn("-", early, "ids are split on hyphens")

    def test_every_event_and_transaction_carries_the_simulation_id(self):
        import sales as sales_mod
        from test_sales import _catalog, _probs, _store_country
        g = sim.Generator(_stores(), seed=3)
        self.assertRegex(g.run_id, r"^\d{8}T\d{9}$")
        rows, _ = _run(g, days=0.5, n_avg={r: 3000 for r in sim.REGIONS})
        events = _events(rows)
        self.assertTrue(events)
        self.assertEqual({e["simulation_id"] for e in events}, {g.run_id})
        self.assertTrue(all(e["event_id"].startswith(f"sim-{g.run_id}-") for e in events))
        seller = sales_mod.SalesGenerator(_catalog(), _store_country(), run_id=g.run_id, seed=1)
        txs = _events(seller.sales_for(rows, _probs()))
        self.assertTrue(txs)
        self.assertEqual({t["simulation_id"] for t in txs}, {g.run_id}, "sales share the people events' id")

    def test_app_explains_that_the_pipeline_follows(self):
        app = read_text(*APP, "app", "app.py")
        self.assertIn("New simulation: the running pipeline and the sales dashboard follow it.", app)
        self.assertNotIn("ull refresh", app, "a START no longer needs a full refresh")
        self.assertIn('"Simulation id"', app)


@unittest.skipIf(sim is None, SKIP_REASON)
class HeadlineTests(unittest.TestCase):

    RUNNING = {"state": "RUNNING", "run_id": "20261114T201229280", "batches": 3,
               "start_utc": "2026-11-14 20:12:29+00:00", "sim_utc": "2026-11-14 21:42:29+00:00"}

    def test_headline_shows_simulation_id_start_and_simulated_time_in_gmt(self):
        h = sim.headline(self.RUNNING)
        self.assertEqual((h["simulation_id"], h["started"], h["simulated"]),
                         ("20261114T201229280", "14 Nov 2026 20:12:29 GMT", "14 Nov 2026 21:42:29 GMT"))
        idle = sim.headline({"state": "STOPPED", "run_id": None, "start_utc": None, "sim_utc": None})
        self.assertEqual((idle["simulation_id"], idle["started"], idle["simulated"]), ("—", "—", "—"))
        self.assertEqual(sim.clock_class(idle), "sim-clock idle")
        self.assertEqual(sim.gmt_text("2026-11-14T22:12:29+02:00"), "14 Nov 2026 20:12:29 GMT", "converted to GMT")

    def test_clock_hands_point_at_the_simulated_time(self):
        for text, hour, minute in (("2026-11-14 21:42:00+00:00", 9 * 30 + 42 * 0.5, 42 * 6),
                                   ("2026-11-14 12:00:00+00:00", 0, 0), ("2026-11-14 06:30:00+00:00", 195, 180)):
            h, m = sim.clock_angles(text)
            self.assertAlmostEqual(h % 360, hour, msg=text)
            self.assertAlmostEqual(m % 360, minute, msg=text)
        self.assertEqual(sim.clock_angles(None), (0.0, 0.0))

    def test_clock_hands_only_turn_forwards(self):
        """Angles grow with time, also across 12 o'clock and midnight, so the animation never runs backwards."""
        start = datetime(2026, 11, 14, 11, 30, tzinfo=timezone.utc)
        angles = [sim.clock_angles(start + i * HALF_HOUR) for i in range(60)]  # 30 hours, one batch each
        for (h0, m0), (h1, m1) in zip(angles, angles[1:]):
            self.assertAlmostEqual(h1 - h0, 15)   # 30 minutes on the hour hand
            self.assertAlmostEqual(m1 - m0, 180)  # and on the minute hand

    def test_hands_are_animated_only_between_batches(self):
        self.assertEqual(sim.clock_class(sim.headline(self.RUNNING)), "sim-clock moving")
        first = sim.headline({**self.RUNNING, "batches": 1})
        self.assertEqual(sim.clock_class(first), "sim-clock", "the first batch jumps: no spin through 1970-today")
        self.assertEqual(sim.clock_class(sim.headline({**self.RUNNING, "state": "FINISHED"})), "sim-clock")

    def test_app_has_the_headline_panel(self):
        app = read_text(*APP, "app", "app.py")
        for component_id in ("headline-simulation-id", "headline-started", "headline-simulated", "hand-hour",
                             "hand-minute", "sim-clock"):
            self.assertIn(f'id="{component_id}"', app)
            self.assertRegex(app, rf'Output\("{component_id}", "(children|style|className)"\)')
        self.assertIn("headline_panel(sim.headline(snapshot))", app, "a page opened mid-run shows the hands in place")
        self.assertIn("for i in range(12)", app, "twelve hour marks")
        css = read_text(*APP, "app", "assets", "clock.css")
        self.assertIn(".sim-clock.moving .hand { transition: transform", css)
        self.assertNotRegex(css, r"\.sim-clock \.hand \{[^}]*transition", "no animation outside a running simulation")


class OperationsTests(unittest.TestCase):
    """The Switch on / off tab and the signature (operations.py), against doc/people_stream.md section 10."""

    @classmethod
    def setUpClass(cls):
        import operations
        cls.ops = operations
        cls.doc = read_text("doc", "people_stream.md").split("## 10. Switch on and off", 1)[1]

    def _doc_steps(self, title):
        table = self.doc.split(title, 1)[1].split("\n\n", 2)[1]
        return [tuple(c.strip() for c in line.strip("|").split("|"))
                for line in table.splitlines() if re.match(r"^\| \d", line)]

    def test_tab_and_doc_show_the_same_steps(self):
        self.assertEqual(self._doc_steps("**Switch on, in this order:**"), list(self.ops.SWITCH_ON))
        self.assertEqual(self._doc_steps("**Switch off:**"), list(self.ops.SWITCH_OFF))
        for note in self.ops.NOTES:
            self.assertIn(f"- {note}", self.doc)

    def test_steps_name_the_real_resources(self):
        """The job, apps and Git folder the steps name are the bundles' ones."""
        self.assertIn("name: retail-simulator", read_text("resources", "modeling.peoplecounter.job.yml"))
        self.assertEqual(self.ops.JOB, "[dev michele_piunti] retail-simulator")
        self.assertIn("default: people-stream-${workspace.current_user.domain_friendly_name}",
                      read_text(*APP, "databricks.yml"))
        self.assertIn("default: sales-bi-${workspace.current_user.domain_friendly_name}",
                      read_text("apps", "sales_dashboard", "databricks.yml"))
        self.assertEqual((self.ops.SIMULATOR_APP, self.ops.DASHBOARD_APP),
                         ("people-stream-michele-piunti", "sales-bi-michele-piunti"))
        self.assertEqual([s[0] for s in self.ops.SWITCH_ON], [str(i) for i in range(6)], "numbered in order")
        resume = [s for s in self.ops.SWITCH_ON if s[2] == "Resume"][0]
        start = [s for s in self.ops.SWITCH_ON if "press START" in s[2]][0]
        self.assertLess(int(resume[0]), int(start[0]), "the job is resumed before the simulation starts")

    def test_signature_and_git_link(self):
        self.assertEqual(self.ops.SIGNATURE, "This app is made by Michele Piunti in November 2026.")
        self.assertEqual(self.ops.REPO_URL, "https://github.com/MPiunti/nov26_stream")
        self.assertIn("github.com/MPiunti/nov26_stream", read_text("readme.md"), "the readme's Git project")
        self.assertIn(f"[github.com/MPiunti/nov26_stream]({self.ops.REPO_URL})", self.doc)
        app = read_text(*APP, "app", "app.py")
        for text in ('dbc.Tab(label="Switch on / off", tab_id="tab-operations", children=operations_tab())',
                     "html.A(\"GitHub: MPiunti/nov26_stream\", href=operations.REPO_URL", "signature(),"):
            self.assertIn(text, app)
        layout = app.split("def serve_layout():", 1)[1]
        self.assertLess(layout.index("dbc.Tabs("), layout.index("signature(),"), "at the bottom of the page")


class PeopleStreamDocTests(unittest.TestCase):

    def test_doc_matches_simulator_constants(self):
        doc = read_text("doc", "people_stream.md")
        for text in ("24 simulated hours = 240 real seconds", "1 simulated hour = 10 s",
                     "Range 2000–6000, step 100, default 3000", "**5 s = 30 simulated minutes**",
                     "**10:00 and 20:00 local time**", "`people-counter-app`",
                     "`0` EUROPE, `1` AMERICAS, `2` ASIA",
                     "At most 48 simulated hours = 480 real seconds"):
            self.assertIn(text, doc)

    def test_doc_describes_the_headline_panel(self):
        doc = read_text("doc", "people_stream.md")
        for text in ("**Headline panel**", "**Analog clock**", "`14 Nov 2026 20:42:29 GMT`", "`20261114T201229280`",
                     "The hands only turn forwards"):
            self.assertIn(text, doc)

    def test_readme_lists_app_files(self):
        readme = read_text("readme.md")
        for root, dirs, files in os.walk(path(*APP)):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", ".databricks")]  # local, gitignored
            for f in files:
                self.assertIn(f, readme, f"{os.path.join(root, f)} isn't in readme.md")


if __name__ == "__main__":
    unittest.main()
