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
        self.assertIn('value: "5"', read_text(*APP, "app", "app.yaml"))

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
        self.assertEqual((sim.N_AVG_MIN, sim.N_AVG_DEFAULT, sim.N_AVG_MAX), (2000, 3000, 6000))
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

    def test_exits_balance_entries_by_closing(self):
        g = sim.Generator(_stores()[:20], seed=5)
        rows, _ = _run(g, days=2, n_avg={r: 3000 for r in sim.REGIONS},
                       start=datetime(2026, 11, 13, 0, 0, tzinfo=timezone.utc))
        net = defaultdict(int)
        for e in _events(rows):
            net[e["store_id"]] += e["people_count"] if e["event_type"] == "ENTRY" else -e["people_count"]
            self.assertGreaterEqual(e["people_count"], 1)
        for stream in g.streams:  # 2026-11-15 00:00 UTC: all 20 Italian stores are closed
            self.assertEqual(stream.occupancy, 0)
            self.assertEqual(net[stream.store.store_id], 0)

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
        for root, _, files in os.walk(path(*APP)):
            for f in files:
                self.assertIn(f, readme, f"{os.path.join(root, f)} isn't in readme.md")


if __name__ == "__main__":
    unittest.main()
