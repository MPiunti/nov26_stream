"""People-stream generator: simulated people-counter events for every store. Standard library only.

Functional description: doc/people_stream.md. Summary:
- Time runs 360x faster than real time: 240 real seconds are one simulated day, 10 seconds one hour.
- On START the simulated clock starts at the current real UTC time; each store sees it in its own time zone.
- Each store is its own stream. It emits events only while open, 10:00-20:00 local time.
- Visitors per store per simulated day average N_AVG_PEOPLE of the store's macro region.
- Each tick (default 5 real seconds = 30 simulated minutes) emits, per open store, at most one ENTRY
  and one EXIT event whose people_count totals the people who came in and went out in that window.
- A run lasts at most 48 simulated hours (480 real seconds), then the generator stops (FINISHED).
  STOP ends it earlier; START always begins a new run from the current time.
"""
import json
import math
import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

REAL_SECONDS_PER_SIM_DAY = 240
TIME_SCALE = 86400 / REAL_SECONDS_PER_SIM_DAY  # simulated seconds per real second: 360
MAX_RUN_SIM_HOURS = 48  # a run ends by itself after 2 simulated days...
MAX_RUN_REAL_SECONDS = MAX_RUN_SIM_HOURS * 3600 / TIME_SCALE  # ...that is 480 real seconds
OPEN_HOUR, CLOSE_HOUR = 10, 20
OPEN_MINUTES = (CLOSE_HOUR - OPEN_HOUR) * 60

REGIONS = ("EUROPE", "AMERICAS", "ASIA")
N_AVG_DEFAULT, N_AVG_MIN, N_AVG_MAX, N_AVG_STEP = 3000, 2000, 6000, 100

SOURCE_TOPIC = "people-counter-app"
PARTITION = {"EUROPE": 0, "AMERICAS": 1, "ASIA": 2}  # one Event Hubs partition per macro region
DEFAULT_TICK_SECONDS = 5


@dataclass(frozen=True)
class Store:
    store_id: str
    macro_region: str
    timezone_id: str

    @property
    def sensor_id(self):
        return f"PC-{self.store_id.split('-')[1]}-01"


@dataclass
class StoreStream:
    """One store's stream: it carries the people still inside between ticks."""
    store: Store
    tz: ZoneInfo = field(init=False)
    occupancy: int = 0

    def __post_init__(self):
        self.tz = ZoneInfo(self.store.timezone_id)


def headline_time(snapshot):
    """Headline text: simulated UTC time rounded down to the hour while RUNNING, else empty."""
    if snapshot.get("state") != "RUNNING" or not snapshot.get("sim_utc"):
        return ""
    return f"{str(snapshot['sim_utc'])[:13].replace('T', ' ')}:00 UTC"


def clamp_n_avg(value):
    """Slider value -> valid N_AVG_PEOPLE: within [N_AVG_MIN, N_AVG_MAX], on the step grid."""
    value = int(round(float(value) / N_AVG_STEP)) * N_AVG_STEP
    return max(N_AVG_MIN, min(N_AVG_MAX, value))


def sim_time(start_utc, elapsed_real_seconds):
    """Simulated UTC time after elapsed_real_seconds of real time."""
    return start_utc + timedelta(seconds=elapsed_real_seconds * TIME_SCALE)


def is_open(local_dt):
    return OPEN_HOUR <= local_dt.hour < CLOSE_HOUR


def open_windows(local_from, local_to):
    """Parts of [local_from, local_to) that fall within opening hours, as (start, end) naive local times."""
    windows = []
    day = local_from.replace(hour=0, minute=0, second=0, microsecond=0)
    while day < local_to:
        start = max(local_from, day.replace(hour=OPEN_HOUR))
        end = min(local_to, day.replace(hour=CLOSE_HOUR))
        if start < end:
            windows.append((start, end))
        day += timedelta(days=1)
    return windows


def closes_within(local_from, local_to):
    """True if a closing time (CLOSE_HOUR:00 local) falls in (local_from, local_to]."""
    day = local_from.replace(hour=0, minute=0, second=0, microsecond=0)
    while day <= local_to:
        close = day.replace(hour=CLOSE_HOUR)
        if local_from < close <= local_to:
            return True
        day += timedelta(days=1)
    return False


def expected_entries(n_avg, open_minutes):
    """Average people entering a store during open_minutes, for N_AVG_PEOPLE visitors per day."""
    return n_avg * open_minutes / OPEN_MINUTES


def poisson(lam, rng):
    if lam <= 0:
        return 0
    if lam < 30:  # Knuth
        limit, k, p = math.exp(-lam), 0, 1.0
        while True:
            p *= rng.random()
            if p <= limit:
                return k
            k += 1
    return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))


def _random_time(windows, minutes, rng):
    pick = rng.random() * minutes
    for start, end in windows:
        span = (end - start).total_seconds() / 60
        if pick <= span:
            return start + timedelta(minutes=pick)
        pick -= span
    return windows[-1][1] - timedelta(milliseconds=1)


def store_tick(stream, sim_from_utc, sim_to_utc, n_avg, rng):
    """Events of one store for the simulated window [sim_from_utc, sim_to_utc).

    Returns [(event_type, people_count, local_timestamp)], at most one ENTRY and one EXIT.
    """
    local_from = sim_from_utc.astimezone(stream.tz).replace(tzinfo=None)
    local_to = sim_to_utc.astimezone(stream.tz).replace(tzinfo=None)
    windows = open_windows(local_from, local_to)
    minutes = sum((e - s).total_seconds() for s, e in windows) / 60
    events = []
    if minutes > 0:
        lam = expected_entries(n_avg, minutes)
        entries = poisson(lam, rng)
        exits = min(stream.occupancy, poisson(lam, rng))  # people who came in during earlier ticks
        if entries:
            events.append(("ENTRY", entries, _random_time(windows, minutes, rng)))
        stream.occupancy += entries
        if exits:
            events.append(("EXIT", exits, _random_time(windows, minutes, rng)))
        stream.occupancy -= exits
    if closes_within(local_from, local_to) and stream.occupancy:
        # Closing time: everyone still inside leaves.
        close = max((e for _, e in windows), default=local_to) - timedelta(milliseconds=1)
        events.append(("EXIT", stream.occupancy, close))
        stream.occupancy = 0
    return events


class Generator:
    """Turns simulated time windows into source-table rows for every store."""

    def __init__(self, stores, next_offsets=None, run_id=None, seed=None):
        self.streams = [StoreStream(s) for s in stores]
        self.next_offset = {p: (next_offsets or {}).get(p, 1) for p in PARTITION.values()}
        self.run_id = run_id or uuid.uuid4().hex[:8]
        self.rng = random.Random(seed)

    def tick(self, sim_from_utc, sim_to_utc, n_avg_by_region):
        rows = []
        for stream in self.streams:
            region = stream.store.macro_region
            for event_type, count, local_ts in store_tick(
                    stream, sim_from_utc, sim_to_utc, n_avg_by_region[region], self.rng):
                partition = PARTITION[region]
                offset = self.next_offset[partition]
                self.next_offset[partition] += 1
                payload = {
                    "event_id": f"sim-{self.run_id}-{partition}-{offset:010d}",
                    "store_id": stream.store.store_id,
                    "sensor_id": stream.store.sensor_id,
                    "event_timestamp": local_ts.isoformat(timespec="milliseconds"),
                    "event_type": event_type,
                    "people_count": count,
                }
                rows.append({
                    "raw_event": json.dumps(payload, separators=(",", ":")),
                    "source_topic": SOURCE_TOPIC,
                    "source_partition": partition,
                    "source_offset": offset,
                    "source_timestamp": sim_to_utc,
                })
        return rows

    def open_stores(self, sim_utc):
        counts = {r: 0 for r in REGIONS}
        for stream in self.streams:
            if is_open(sim_utc.astimezone(stream.tz)):
                counts[stream.store.macro_region] += 1
        return counts


class Simulation:
    """START/STOP lifecycle: a background thread that ticks the generator and writes each batch.

    load_stores() -> [Store]; load_offsets() -> {partition: next offset}; write(rows) inserts them.
    """

    def __init__(self, load_stores, load_offsets, write, tick_seconds=DEFAULT_TICK_SECONDS,
                 clock=time.monotonic, now=lambda: datetime.now(timezone.utc)):
        self._load_stores, self._load_offsets, self._write = load_stores, load_offsets, write
        self.tick_seconds = tick_seconds
        self._clock, self._now = clock, now
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self.n_avg = {r: N_AVG_DEFAULT for r in REGIONS}
        self._reset_status()

    def _reset_status(self):
        self.status = {"state": "STOPPED", "start_utc": None, "sim_utc": None, "end_utc": None,
                       "run_id": None, "remaining_seconds": None,
                       "rows_written": 0, "batches": 0, "entries": {r: 0 for r in REGIONS},
                       "open_stores": {r: 0 for r in REGIONS}, "stores": {r: 0 for r in REGIONS},
                       "last_batch_rows": 0, "error": None,
                       # Cumulative visitors (ENTRY people_count) per region, one point per batch.
                       "history": []}

    def set_n_avg(self, region, value):
        with self._lock:
            self.n_avg[region] = clamp_n_avg(value)

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.running:
            return
        self._stop.clear()
        with self._lock:
            self._reset_status()
            self.status["state"] = "STARTING"
        self._thread = threading.Thread(target=self._run, name="people-stream", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=60)

    def _run(self):
        try:
            stores = self._load_stores()
            generator = Generator(stores, self._load_offsets())
            start_real, start_utc = self._clock(), self._now()
            end_utc = start_utc + timedelta(hours=MAX_RUN_SIM_HOURS)
            with self._lock:
                self.status.update(state="RUNNING", start_utc=start_utc, sim_utc=start_utc, end_utc=end_utc,
                                   run_id=generator.run_id, remaining_seconds=MAX_RUN_REAL_SECONDS)
                for s in stores:
                    self.status["stores"][s.macro_region] += 1
                self.status["history"].append({"sim_utc": start_utc, **{r: 0 for r in REGIONS}})
            sim_from = start_utc
            finished = False
            while not finished:
                elapsed = self._clock() - start_real
                wait = min(self.tick_seconds, max(0.0, MAX_RUN_REAL_SECONDS - elapsed))
                if self._stop.wait(wait):
                    break
                elapsed = self._clock() - start_real
                finished = elapsed >= MAX_RUN_REAL_SECONDS
                sim_to = min(sim_time(start_utc, elapsed), end_utc)
                with self._lock:
                    n_avg = dict(self.n_avg)
                rows = generator.tick(sim_from, sim_to, n_avg)
                if rows:
                    self._write(rows)
                with self._lock:
                    st = self.status
                    st["sim_utc"], st["batches"] = sim_to, st["batches"] + 1
                    st["rows_written"] += len(rows)
                    st["last_batch_rows"] = len(rows)
                    st["open_stores"] = generator.open_stores(sim_to)
                    for row in rows:
                        event = json.loads(row["raw_event"])
                        if event["event_type"] == "ENTRY":
                            st["entries"][REGIONS[row["source_partition"]]] += event["people_count"]
                    st["error"] = None
                    st["remaining_seconds"] = max(0.0, MAX_RUN_REAL_SECONDS - elapsed)
                    st["history"].append({"sim_utc": sim_to, **st["entries"]})
                sim_from = sim_to
            with self._lock:
                self.status["state"] = "FINISHED" if finished else "STOPPED"
                self.status["remaining_seconds"] = 0.0
        except Exception as exc:  # shown in the app; the simulation stops
            with self._lock:
                self.status.update(state="FAILED", error=f"{type(exc).__name__}: {exc}")

    def snapshot(self):
        with self._lock:
            return json.loads(json.dumps({**self.status, "n_avg": dict(self.n_avg)}, default=str))
