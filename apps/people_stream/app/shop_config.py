"""Read and check shop_config.yml: store and simulation parameters. Standard library only.

The file uses a small YAML subset (nested "key: value" lines, two-space indents, whole numbers,
# comments), parsed here so the generator and its tests need no extra package. Anything outside
the subset, an unknown or missing key, or an inconsistent value is rejected with a clear error.
"""
import os
import re
from dataclasses import dataclass

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shop_config.yml")
REGIONS = ("EUROPE", "AMERICAS", "ASIA")
CATEGORIES = ("SHOES", "BAGS", "READY_TO_WEAR", "ACCESSORIES", "TRAVEL", "SUNGLASSES")

_SCHEMA = {
    "stores": {"opening_hour": int, "closing_hour": int, "max_stay_minutes": int},
    "n_avg_people": {"default": {r: int for r in REGIONS}, "min": int, "max": int, "step": int},
    "purchase_prob": {"default": {r: {c: int for c in CATEGORIES} for r in REGIONS},
                      "min": int, "max": int, "step": int},
    "simulation": {"real_seconds_per_sim_day": int, "max_run_sim_hours": int, "tick_seconds": int},
}


@dataclass(frozen=True)
class ShopConfig:
    opening_hour: int
    closing_hour: int
    max_stay_minutes: int
    n_avg_default: dict
    n_avg_min: int
    n_avg_max: int
    n_avg_step: int
    purchase_prob_default: dict  # {region: {category: percent}}
    prob_min: int
    prob_max: int
    prob_step: int
    real_seconds_per_sim_day: int
    max_run_sim_hours: int
    tick_seconds: int

    @property
    def time_scale(self):
        """Simulated seconds per real second."""
        return 86400 / self.real_seconds_per_sim_day

    @property
    def real_seconds_per_sim_hour(self):
        return self.real_seconds_per_sim_day / 24

    @property
    def max_run_real_seconds(self):
        return self.max_run_sim_hours * 3600 / self.time_scale

    @property
    def tick_sim_minutes(self):
        return self.tick_seconds * self.time_scale / 60


def parse(text):
    """Nested dict from the YAML subset; raises ValueError on anything else."""
    root, stack = {}, [(-1, None)]
    stack[0] = (-1, root)
    for number, raw in enumerate(text.splitlines(), 1):
        line = re.sub(r"\s+#.*$|^\s*#.*$", "", raw).rstrip()
        if not line.strip():
            continue
        m = re.fullmatch(r"( *)([A-Za-z_][A-Za-z0-9_]*):(?: +(-?\d+))?", line)
        if not m or len(m.group(1)) % 2:
            raise ValueError(f"shop_config.yml line {number}: expected 'key: whole number' or 'key:' "
                             f"with two-space indents, got {raw.strip()!r}")
        indent, key, value = len(m.group(1)), m.group(2), m.group(3)
        while stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]
        if indent != stack[-1][0] + 2 and not (indent == 0 and stack[-1][0] == -1):
            raise ValueError(f"shop_config.yml line {number}: wrong indent")
        if key in parent:
            raise ValueError(f"shop_config.yml line {number}: duplicate key {key}")
        if value is None:
            parent[key] = {}
            stack.append((indent, parent[key]))
        else:
            parent[key] = int(value)
    return root


def _check_shape(data, schema, where="shop_config.yml"):
    if set(data) != set(schema):
        missing, extra = set(schema) - set(data), set(data) - set(schema)
        raise ValueError(f"{where}: missing {sorted(missing)}, unknown {sorted(extra)}")
    for key, kind in schema.items():
        if isinstance(kind, dict):
            if not isinstance(data[key], dict):
                raise ValueError(f"{where}.{key} must be a section")
            _check_shape(data[key], kind, f"{where}.{key}")
        elif not isinstance(data[key], kind):
            raise ValueError(f"{where}.{key} must be a whole number")


def load(path=CONFIG_PATH):
    with open(path, encoding="utf-8") as f:
        data = parse(f.read())
    _check_shape(data, _SCHEMA)
    s, n, p, sim = data["stores"], data["n_avg_people"], data["purchase_prob"], data["simulation"]
    cfg = ShopConfig(
        opening_hour=s["opening_hour"], closing_hour=s["closing_hour"], max_stay_minutes=s["max_stay_minutes"],
        n_avg_default=dict(n["default"]), n_avg_min=n["min"], n_avg_max=n["max"], n_avg_step=n["step"],
        purchase_prob_default={r: dict(p["default"][r]) for r in REGIONS},
        prob_min=p["min"], prob_max=p["max"], prob_step=p["step"],
        real_seconds_per_sim_day=sim["real_seconds_per_sim_day"], max_run_sim_hours=sim["max_run_sim_hours"],
        tick_seconds=sim["tick_seconds"],
    )
    problems = []
    if not 0 <= cfg.opening_hour < cfg.closing_hour <= 24:
        problems.append("stores: need 0 <= opening_hour < closing_hour <= 24")
    elif not 0 < cfg.max_stay_minutes <= (cfg.closing_hour - cfg.opening_hour) * 60:
        problems.append("stores: max_stay_minutes must be > 0 and no longer than the opening hours")
    if not 0 < cfg.n_avg_min <= cfg.n_avg_max or cfg.n_avg_step <= 0:
        problems.append("n_avg_people: need 0 < min <= max and step > 0")
    elif (cfg.n_avg_max - cfg.n_avg_min) % cfg.n_avg_step:
        problems.append("n_avg_people: max - min must be a multiple of step")
    for region, value in cfg.n_avg_default.items():
        if not cfg.n_avg_min <= value <= cfg.n_avg_max or (value - cfg.n_avg_min) % cfg.n_avg_step:
            problems.append(f"n_avg_people.default.{region}: {value} must be in min..max, on the step grid")
    if not 0 <= cfg.prob_min < cfg.prob_max <= 100 or cfg.prob_step <= 0:
        problems.append("purchase_prob: need 0 <= min < max <= 100 and step > 0")
    elif (cfg.prob_max - cfg.prob_min) % cfg.prob_step:
        problems.append("purchase_prob: max - min must be a multiple of step")
    else:
        for region, by_category in cfg.purchase_prob_default.items():
            for category, value in by_category.items():
                if not cfg.prob_min <= value <= cfg.prob_max or (value - cfg.prob_min) % cfg.prob_step:
                    problems.append(f"purchase_prob.default.{region}.{category}: {value} must be in "
                                    "min..max, on the step grid")
    if cfg.real_seconds_per_sim_day <= 0 or cfg.max_run_sim_hours <= 0:
        problems.append("simulation: real_seconds_per_sim_day and max_run_sim_hours must be > 0")
    elif not 0 < cfg.tick_seconds <= cfg.max_run_real_seconds:
        problems.append("simulation: tick_seconds must be > 0 and no longer than a run")
    if problems:
        raise ValueError("shop_config.yml: " + "; ".join(problems))
    return cfg


def _num(x):
    return f"{x:g}" if isinstance(x, float) else f"{x:,}"


def _probabilities(by_region):
    def one(d):
        return ", ".join(f"{c} {d[c]}%" for c in CATEGORIES)
    if all(by_region[r] == by_region[REGIONS[0]] for r in REGIONS):
        return "All regions: " + one(by_region[REGIONS[0]])
    return " / ".join(f"{r.title()}: {one(by_region[r])}" for r in REGIONS)


def describe(cfg):
    """(parameter, value, meaning) rows for the app's Parameters panel."""
    d = cfg.n_avg_default
    return [
        ("stores.opening_hour / closing_hour", f"{cfg.opening_hour:02d}:00 - {cfg.closing_hour:02d}:00",
         "Opening hours, each store's local time"),
        ("stores.max_stay_minutes", f"{cfg.max_stay_minutes} min = {_num(cfg.max_stay_minutes / 60)} h",
         "Longest a person stays inside; each stay is drawn evenly between 0 and this, and ends by closing"),
        ("n_avg_people.default", " / ".join(f"{r.title()} {_num(d[r])}" for r in REGIONS),
         "Average visitors per store per simulated day; slider start values"),
        ("n_avg_people.min / max / step", f"{_num(cfg.n_avg_min)} - {_num(cfg.n_avg_max)}, step {cfg.n_avg_step}",
         "Slider range"),
        ("purchase_prob.default", _probabilities(cfg.purchase_prob_default),
         "Percent chance that a person leaving a store buys one item of the category; slider start values"),
        ("purchase_prob.min / max / step", f"{cfg.prob_min}% - {cfg.prob_max}%, step {cfg.prob_step}",
         "Probability slider range"),
        ("simulation.real_seconds_per_sim_day", f"{cfg.real_seconds_per_sim_day} s = 24 h",
         f"Day length: 1 simulated hour = {_num(cfg.real_seconds_per_sim_hour)} s"),
        ("simulation.max_run_sim_hours", f"{cfg.max_run_sim_hours} h = {_num(cfg.max_run_real_seconds)} s",
         "Longest run; then the generator stops (FINISHED)"),
        ("simulation.tick_seconds", f"{cfg.tick_seconds} s = {_num(cfg.tick_sim_minutes)} min",
         "Time between batches written to the source table"),
    ]
