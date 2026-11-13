"""People-stream generator: simulated people-counter events for every store. Standard library only.

Functional description: doc/people_stream.md. All parameters come from shop_config.yml;
with the shipped values:
- Time runs 360x faster than real time: 240 real seconds are one simulated day, 10 seconds one hour.
- On START the simulated clock starts at the current real UTC time; each store sees it in its own time zone.
- Each store is its own stream. It emits events only while open, 10:00-20:00 local time.
- Visitors per store per simulated day average N_AVG_PEOPLE of the store's macro region.
- Each person stays inside at most 1.5 hours: the stay is drawn evenly between 0 and max_stay_minutes,
  and everyone leaves by closing time.
- Each tick (5 real seconds = 30 simulated minutes) emits, per open store, at most one ENTRY
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

import sales
import shop_config

CONFIG = shop_config.load()
REAL_SECONDS_PER_SIM_DAY = CONFIG.real_seconds_per_sim_day
TIME_SCALE = CONFIG.time_scale  # simulated seconds per real second
MAX_RUN_SIM_HOURS = CONFIG.max_run_sim_hours  # a run ends by itself after this many simulated hours...
MAX_RUN_REAL_SECONDS = CONFIG.max_run_real_seconds  # ...that many real seconds
OPEN_HOUR, CLOSE_HOUR = CONFIG.opening_hour, CONFIG.closing_hour
OPEN_MINUTES = (CLOSE_HOUR - OPEN_HOUR) * 60
MAX_STAY_MINUTES = CONFIG.max_stay_minutes
MAX_STAY = timedelta(minutes=MAX_STAY_MINUTES)

REGIONS = shop_config.REGIONS
N_AVG_DEFAULTS = dict(CONFIG.n_avg_default)
N_AVG_MIN, N_AVG_MAX, N_AVG_STEP = CONFIG.n_avg_min, CONFIG.n_avg_max, CONFIG.n_avg_step
CATEGORIES = shop_config.CATEGORIES
PURCHASE_PROB_DEFAULTS = {r: dict(CONFIG.purchase_prob_default[r]) for r in REGIONS}
PROB_MIN, PROB_MAX, PROB_STEP = CONFIG.prob_min, CONFIG.prob_max, CONFIG.prob_step

SOURCE_TOPIC = "people-counter-app"
PARTITION = {"EUROPE": 0, "AMERICAS": 1, "ASIA": 2}  # one Event Hubs partition per macro region
DEFAULT_TICK_SECONDS = CONFIG.tick_seconds


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
    """One store's stream: it carries the people still inside between ticks.

    cohorts holds one Cohort per ENTRY event whose people haven't all left yet.
    """
    store: Store
    tz: ZoneInfo = field(init=False)
    cohorts: list = field(default_factory=list)

    def __post_init__(self):
        self.tz = ZoneInfo(self.store.timezone_id)

    @property
    def occupancy(self):
        return sum(c.inside for c in self.cohorts)


@dataclass
class Cohort:
    """The people of one ENTRY event. Each stays a time drawn evenly in [0, MAX_STAY], cut at closing."""
    entered: datetime  # store local time
    closing: datetime  # last moment before closing, same day
    inside: int
    left_share: float = 0.0  # share of the cohort's leave times already past

    def latest_leave(self):
        return min(self.entered + MAX_STAY, self.closing)

    def share_left_by(self, local_time):
        """Share of the cohort whose leave time is before local_time (uniform stay, everyone out by closing)."""
        if local_time > self.closing:
            return 1.0
        return min(1.0, max(0.0, (local_time - self.entered) / MAX_STAY))


def browser_title(snapshot, app_title):
    """Browser tab title: the app title, plus the simulated hour while RUNNING."""
    hour = headline_time(snapshot)
    return f"{app_title} · {hour}" if hour else app_title


def headline_time(snapshot):
    """Headline text: simulated UTC time rounded down to the hour while RUNNING, else empty."""
    if snapshot.get("state") != "RUNNING" or not snapshot.get("sim_utc"):
        return ""
    return f"{str(snapshot['sim_utc'])[:13].replace('T', ' ')}:00 UTC"


def clamp_prob(value):
    """Slider value -> valid PURCHASE_PROB percent: within [PROB_MIN, PROB_MAX], on the step grid."""
    value = PROB_MIN + int(round((float(value) - PROB_MIN) / PROB_STEP)) * PROB_STEP
    return max(PROB_MIN, min(PROB_MAX, value))


def clamp_n_avg(value):
    """Slider value -> valid N_AVG_PEOPLE: within [N_AVG_MIN, N_AVG_MAX], on the step grid."""
    value = N_AVG_MIN + int(round((float(value) - N_AVG_MIN) / N_AVG_STEP)) * N_AVG_STEP
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


def binomial(n, p, rng):
    """People out of n who do something, each with probability p; fast approximations for large n."""
    if n <= 0 or p <= 0:
        return 0
    if p >= 1:
        return n
    if p > 0.5:
        return n - binomial(n, 1 - p, rng)
    if n * p * (1 - p) >= 9:
        return max(0, min(n, int(round(rng.gauss(n * p, math.sqrt(n * p * (1 - p)))))))
    if n <= 50:
        return sum(1 for _ in range(n) if rng.random() < p)
    return min(n, poisson(n * p, rng))


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
    Each person who enters stays a time drawn evenly in [0, MAX_STAY] and leaves at entry + stay, or just
    before closing if that comes first. Per cohort (one ENTRY event), the people leaving in the window are
    drawn from the share of its leave times that fall in the window. The EXIT event counts everyone leaving
    in the window and carries the latest moment they can have left.
    """
    local_from = sim_from_utc.astimezone(stream.tz).replace(tzinfo=None)
    local_to = sim_to_utc.astimezone(stream.tz).replace(tzinfo=None)
    windows = open_windows(local_from, local_to)
    minutes = sum((e - s).total_seconds() for s, e in windows) / 60
    events = []
    if minutes > 0:
        entries = poisson(expected_entries(n_avg, minutes), rng)
        if entries:
            entered = _random_time(windows, minutes, rng)
            events.append(("ENTRY", entries, entered))
            closing = entered.replace(hour=CLOSE_HOUR, minute=0, second=0, microsecond=0) - timedelta(milliseconds=1)
            stream.cohorts.append(Cohort(entered, closing, entries))
    left, last = 0, None
    for cohort in stream.cohorts:
        share = cohort.share_left_by(local_to)
        if share >= 1:
            leaving = cohort.inside
        else:
            leaving = binomial(cohort.inside, (share - cohort.left_share) / (1 - cohort.left_share), rng)
        cohort.left_share = share
        if leaving:
            cohort.inside -= leaving
            left += leaving
            moment = min(local_to - timedelta(milliseconds=1), cohort.latest_leave())
            last = moment if last is None else max(last, moment)
    stream.cohorts = [c for c in stream.cohorts if c.inside > 0]
    if left:
        events.append(("EXIT", left, last))
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
    Sales (optional, doc/sales.md): load_catalog() -> sales.Catalog; load_sales_offsets() -> {partition:
    next offset}; write_sales(rows) inserts the transactions. Without load_catalog no sales are made.
    clear_sources() (optional) runs first at every START and empties both source tables.
    """

    def __init__(self, load_stores, load_offsets, write, tick_seconds=DEFAULT_TICK_SECONDS,
                 clock=time.monotonic, now=lambda: datetime.now(timezone.utc),
                 load_catalog=None, load_sales_offsets=None, write_sales=None, clear_sources=None):
        self._load_stores, self._load_offsets, self._write = load_stores, load_offsets, write
        self._load_catalog = load_catalog
        self._load_sales_offsets = load_sales_offsets or (lambda: {})
        self._write_sales = write_sales or (lambda rows: None)
        self._clear_sources = clear_sources
        self.tick_seconds = tick_seconds
        self._clock, self._now = clock, now
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self.n_avg = dict(N_AVG_DEFAULTS)
        self.purchase_prob = {r: dict(PURCHASE_PROB_DEFAULTS[r]) for r in REGIONS}
        self._reset_status()

    def _reset_status(self):
        self.status = {"state": "STOPPED", "start_utc": None, "sim_utc": None, "end_utc": None,
                       "run_id": None, "remaining_seconds": None,
                       "rows_written": 0, "batches": 0, "entries": {r: 0 for r in REGIONS},
                       "exits": {r: 0 for r in REGIONS},
                       # People per store-local calendar date: {date: {region: {"entries": n, "exits": n}}}.
                       "daily": {},
                       "open_stores": {r: 0 for r in REGIONS}, "stores": {r: 0 for r in REGIONS},
                       "last_batch_rows": 0, "error": None,
                       # Cumulative people_count of ENTRY and of EXIT events per region, one point per batch.
                       "history": [],
                       # Sales so far: per region, transactions, amount (EUR) and transactions per category.
                       "sales": {r: {"transactions": 0, "amount": 0.0, "by_category": {c: 0 for c in CATEGORIES}}
                                 for r in REGIONS},
                       "sales_rows_written": 0, "sources_cleared": False}

    def set_purchase_prob(self, region, category, value):
        with self._lock:
            self.purchase_prob[region][category] = clamp_prob(value)

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
            if self._clear_sources is not None:
                self._clear_sources()  # every run starts from empty source tables
                with self._lock:
                    self.status["sources_cleared"] = True
            stores = self._load_stores()
            generator = Generator(stores, self._load_offsets())
            seller = None
            if self._load_catalog is not None:
                seller = sales.SalesGenerator(self._load_catalog(), {s.store_id: s.store_id[:2] for s in stores},
                                              self._load_sales_offsets(), run_id=generator.run_id)
            start_real, start_utc = self._clock(), self._now()
            end_utc = start_utc + timedelta(hours=MAX_RUN_SIM_HOURS)
            with self._lock:
                self.status.update(state="RUNNING", start_utc=start_utc, sim_utc=start_utc, end_utc=end_utc,
                                   run_id=generator.run_id, remaining_seconds=MAX_RUN_REAL_SECONDS)
                for s in stores:
                    self.status["stores"][s.macro_region] += 1
                self.status["history"].append({"sim_utc": start_utc, "entries": {r: 0 for r in REGIONS},
                                               "exits": {r: 0 for r in REGIONS}})
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
                    prob = {r: dict(self.purchase_prob[r]) for r in REGIONS}
                rows = generator.tick(sim_from, sim_to, n_avg)
                sale_rows = seller.sales_for(rows, prob) if seller else []
                if rows:
                    self._write(rows)
                if sale_rows:
                    self._write_sales(sale_rows)
                with self._lock:
                    st = self.status
                    st["sim_utc"], st["batches"] = sim_to, st["batches"] + 1
                    st["rows_written"] += len(rows)
                    st["last_batch_rows"] = len(rows)
                    st["open_stores"] = generator.open_stores(sim_to)
                    for row in rows:
                        event = json.loads(row["raw_event"])
                        kind = "entries" if event["event_type"] == "ENTRY" else "exits"
                        region = REGIONS[row["source_partition"]]
                        st[kind][region] += event["people_count"]
                        day = st["daily"].setdefault(event["event_timestamp"][:10],
                                                     {r: {"entries": 0, "exits": 0} for r in REGIONS})
                        day[region][kind] += event["people_count"]
                    for row in sale_rows:
                        tx = json.loads(row["raw_event"])
                        region_sales = st["sales"][REGIONS[row["source_partition"]]]
                        region_sales["transactions"] += 1
                        region_sales["amount"] = round(region_sales["amount"] + tx["amount"], 2)
                        region_sales["by_category"][tx["category"]] += 1
                    st["sales_rows_written"] += len(sale_rows)
                    st["error"] = None
                    st["remaining_seconds"] = max(0.0, MAX_RUN_REAL_SECONDS - elapsed)
                    st["history"].append({"sim_utc": sim_to, "entries": dict(st["entries"]),
                                         "exits": dict(st["exits"])})
                sim_from = sim_to
            with self._lock:
                self.status["state"] = "FINISHED" if finished else "STOPPED"
                self.status["remaining_seconds"] = 0.0
        except Exception as exc:  # shown in the app; the simulation stops
            with self._lock:
                self.status.update(state="FAILED", error=f"{type(exc).__name__}: {exc}")

    def snapshot(self):
        with self._lock:
            return json.loads(json.dumps({**self.status, "n_avg": dict(self.n_avg),
                                          "purchase_prob": self.purchase_prob}, default=str))
