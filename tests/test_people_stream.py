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
    import warehouse
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
            "10:00 - 20:00", "Europe 3,000 / Americas 3,000 / Asia 3,000", "2,000 - 6,000, step 100",
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
        grants = re.findall(r"securable_full_name: \$\{var\.catalog\}\.\$\{var\.schema\}\.(\w+)\s*\n\s*"
                            r"securable_type: TABLE\s*\n\s*permission: (\w+)", res)
        self.assertEqual(sorted(grants), [("dim_store", "SELECT"), ("simulated_event_source", "MODIFY"),
                                          ("simulated_event_source", "SELECT")])
        self.assertIn("permission: CAN_USE", res)

    def test_app_yaml_tables_match_bundle_variables(self):
        app_yml = read_text(*APP, "databricks.yml")
        catalog = re.search(r"catalog:\n(?:\s+.*\n)*?\s+default: (\S+)", app_yml).group(1)
        schema = re.search(r"schema:\n(?:\s+.*\n)*?\s+default: (\S+)", app_yml).group(1)
        app_yaml = read_text(*APP, "app", "app.yaml")
        self.assertIn(f"value: {catalog}.{schema}.dim_store", app_yaml)
        self.assertIn(f"value: {catalog}.{schema}.simulated_event_source", app_yaml)
        self.assertIn("valueFrom: sql-warehouse", app_yaml)

    def test_app_name_fits_30_characters(self):
        self.assertLessEqual(len("people-stream-michele-piunti"), 30)

    def test_requirements_are_pinned(self):
        for line in read_text(*APP, "app", "requirements.txt").split():
            self.assertRegex(line, r"^[A-Za-z0-9_.-]+==[\w.]+$")


class PeopleStreamDocTests(unittest.TestCase):

    def test_doc_matches_simulator_constants(self):
        doc = read_text("doc", "people_stream.md")
        for text in ("24 simulated hours = 240 real seconds", "1 simulated hour = 10 s",
                     "Range 2000–6000, step 100, default 3000", "**5 s = 30 simulated minutes**",
                     "**10:00 and 20:00 local time**", "`people-counter-app`",
                     "`0` EUROPE, `1` AMERICAS, `2` ASIA",
                     "At most 48 simulated hours = 480 real seconds"):
            self.assertIn(text, doc)

    def test_readme_lists_app_files(self):
        readme = read_text("readme.md")
        for root, dirs, files in os.walk(path(*APP)):
            dirs[:] = [d for d in dirs if d != "__pycache__"]  # local bytecode, gitignored
            for f in files:
                self.assertIn(f, readme, f"{os.path.join(root, f)} isn't in readme.md")


if __name__ == "__main__":
    unittest.main()
