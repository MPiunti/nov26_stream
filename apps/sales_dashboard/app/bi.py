"""Logic of the sales dashboard: KPIs, live deltas, drill-down and chart series. Standard library only.

Works on the rows of the queries in dashboard_sql.py, as lists of dicts. Times are GMT (UTC).
See doc/sales_dashboard.md.
"""
from dataclasses import replace
from datetime import date, datetime, timedelta

from dashboard_sql import Filters

# KPI on charts: label, unit. AVG_PRICE = value / quantity; PEOPLE_IN = entries counted by the sensors.
KPIS = {
    "VALUE": ("Sales value", "EUR"),
    "QUANTITY": ("Items sold", "items"),
    "AVG_PRICE": ("Average price", "EUR"),
    "PEOPLE_IN": ("People in", "people"),
}
SALES_KPIS = ("VALUE", "QUANTITY", "AVG_PRICE")
REGIONS = ("EUROPE", "AMERICAS", "ASIA")  # one trend line each
TOP_MEMBERS = 15  # bars per breakdown chart

GEO_PATH = ("REGION", "COUNTRY", "STORE")
PRODUCT_PATH = ("CATEGORY", "PRODUCT")
MEASURES = ("value", "quantity", "transactions", "store_quantity", "people_in", "people_out", "row_count")


# ------------------------------------------------------------------ rows

def normalize(rows):
    """Query rows to plain values: dates as YYYY-MM-DD, numbers as float, NULL sums as 0."""
    out = []
    for r in rows:
        row = {}
        for k, v in r.items():
            if k == "utc_date":
                row[k] = str(v)[:10] if v is not None else None
            elif k in MEASURES:
                row[k] = float(v or 0)
            elif k == "utc_hour":
                row[k] = int(v)
            else:
                row[k] = v
        out.append(row)
    return out


def metric(row, kpi):
    """One KPI from a row with value, quantity (and/or people_in). AVG_PRICE is None without items."""
    if kpi == "VALUE":
        return row.get("value", 0.0)
    if kpi == "QUANTITY":
        return row.get("quantity", 0.0)
    if kpi == "AVG_PRICE":
        q = row.get("quantity", 0.0)
        return row.get("value", 0.0) / q if q else None
    if kpi == "PEOPLE_IN":
        return row.get("people_in", 0.0)
    raise ValueError(f"unknown KPI {kpi!r}")


def _add(acc, row):
    for f in MEASURES:
        if f in row:
            acc[f] = acc.get(f, 0.0) + row[f]
    return acc


# ------------------------------------------------------------------ KPI cards

def totals(sales_rows, people_rows):
    """Headline numbers. ITEMS_PER_VISITOR = items sold in physical stores / people in: e-commerce sales have
    no visitors, so they are left out of it (the category filter applies only to the items)."""
    t = {"value": 0.0, "quantity": 0.0, "transactions": 0.0, "store_quantity": 0.0, "people_in": 0.0,
         "people_out": 0.0}
    for r in list(sales_rows) + list(people_rows):
        _add(t, r)
    return {
        "VALUE": t["value"],
        "QUANTITY": t["quantity"],
        "AVG_PRICE": metric(t, "AVG_PRICE") or 0.0,
        "PEOPLE_IN": t["people_in"],
        "TRANSACTIONS": t["transactions"],
        "PEOPLE_OUT": t["people_out"],
        "ITEMS_PER_VISITOR": t["store_quantity"] / t["people_in"] if t["people_in"] else 0.0,
    }


def live_delta(current, snapshot, signature):
    """Change of each KPI since the previous refresh with the same filters; None after a filter change."""
    if not snapshot or snapshot.get("signature") != signature:
        return None
    before = snapshot.get("totals", {})
    return {k: current[k] - before.get(k, 0.0) for k in current}


def signature(filters):
    """A stable, JSON-friendly key of the filters, to tell whether two refreshes are comparable."""
    return [list(filters.dates), list(filters.regions), list(filters.countries), list(filters.stores),
            list(filters.categories), list(filters.products), list(filters.channels)]


# ------------------------------------------------------------------ trend

def _hour(row):
    return datetime.combine(date.fromisoformat(row["utc_date"]), datetime.min.time()) + timedelta(hours=row["utc_hour"])


def trend_series(rows, kpi, cumulative=False):
    """{region: (GMT hours, values)}: one line per macro region on one GMT timeline.

    Every line covers every hour from the first to the last hour with data in any region, so the lines can be
    compared hour by hour; an hour without data counts as 0 (the region's stores were closed). Cumulative adds up
    from the first hour, so each line only grows; for AVG_PRICE it's the running average, and an hour without
    items has no average (None, a gap in the line).
    """
    cells = {}
    for r in rows:
        if r.get("utc_date") is None or r.get("region") not in REGIONS:
            continue
        _add(cells.setdefault((r["region"], _hour(r)), {}), r)
    if not cells:
        return {}
    hours = [h for _, h in cells]
    first, last = min(hours), max(hours)
    timeline = [first + timedelta(hours=i) for i in range(int((last - first).total_seconds() // 3600) + 1)]
    series = {}
    for region in REGIONS:
        if not any(reg == region for reg, _ in cells):
            continue
        acc, ys = {}, []
        for h in timeline:
            cell = cells.get((region, h), {})
            if cumulative:
                _add(acc, cell)
                ys.append(metric(acc, kpi))
            else:
                ys.append(metric(cell, kpi))
        series[region] = (timeline, ys)
    return series


# ------------------------------------------------------------------ breakdown charts

def breakdown(rows, kpi, top=TOP_MEMBERS):
    """Horizontal bars, cumulative per GMT date: members ordered by total, and each member's value per date.

    Returns (members, dates, {date: [value per member]}, hidden), members largest first, at most `top`;
    `hidden` is how many members were left out. For AVG_PRICE the segments don't add up, so it's one
    segment per member over all dates (dates == ["all dates"]).
    """
    per_member, per_cell = {}, {}
    for r in rows:
        _add(per_member.setdefault(r["member"], {}), r)
        _add(per_cell.setdefault((r["member"], r["utc_date"]), {}), r)
    members = sorted(per_member, key=lambda m: (-(metric(per_member[m], kpi) or 0.0), str(m)))
    hidden = max(0, len(members) - top)
    members = members[:top]
    if kpi == "AVG_PRICE":
        return members, ["all dates"], {"all dates": [metric(per_member[m], kpi) or 0.0 for m in members]}, hidden
    dates = sorted({d for (_, d) in per_cell if d is not None})
    values = {d: [metric(per_cell.get((m, d), {}), kpi) for m in members] for d in dates}
    return members, dates, values, hidden


# ------------------------------------------------------------------ drill-down

def drill_down(filters, levels, dimension, member):
    """Click on a bar: filter on that member and go one level down (at the last level, toggle the member).

    `levels` is {"GEO": level, "PRODUCT": level}. Returns the new (filters, levels).
    """
    levels = dict(levels)
    if dimension == "GEO":
        level = levels["GEO"]
        if level == "REGION":
            filters = replace(filters, regions=(member,), countries=(), stores=())
            levels["GEO"] = "COUNTRY"
        elif level == "COUNTRY":
            filters = replace(filters, countries=(member,), stores=())
            levels["GEO"] = "STORE"
        else:
            filters = replace(filters, stores=_toggle(filters.stores, member))
    elif dimension == "PRODUCT":
        if levels["PRODUCT"] == "CATEGORY":
            filters = replace(filters, categories=(member,), products=())
            levels["PRODUCT"] = "PRODUCT"
        else:
            filters = replace(filters, products=_toggle(filters.products, member))
    elif dimension == "CHANNEL":  # one level: a click adds or removes the channel in the filter
        filters = replace(filters, channels=_toggle(filters.channels, member))
    else:
        raise ValueError(f"unknown dimension {dimension!r}")
    return filters, levels


def drill_up(filters, levels, dimension):
    """The Up button: drop the filter of the current level and the one above it, and go one level up."""
    levels = dict(levels)
    if dimension == "GEO":
        level = levels["GEO"]
        if level == "STORE":
            filters = replace(filters, stores=(), countries=())
            levels["GEO"] = "COUNTRY"
        elif level == "COUNTRY":
            filters = replace(filters, countries=(), regions=())
            levels["GEO"] = "REGION"
    elif dimension == "PRODUCT":
        if levels["PRODUCT"] == "PRODUCT":
            filters = replace(filters, products=(), categories=())
            levels["PRODUCT"] = "CATEGORY"
    elif dimension == "CHANNEL":
        filters = replace(filters, channels=())
    else:
        raise ValueError(f"unknown dimension {dimension!r}")
    return filters, levels


def _toggle(values, member):
    return tuple(v for v in values if v != member) if member in values else tuple(values) + (member,)


# ------------------------------------------------------------------ formatting

def fmt_number(x, unit=""):
    """4,750,000 -> '4.75 M'; with unit EUR -> '€ 4.75 M'."""
    sign = "-" if x < 0 else ""
    a = abs(x)
    for limit, suffix in ((1e9, " B"), (1e6, " M"), (1e3, " K")):
        if a >= limit:
            text = f"{a / limit:,.2f}{suffix}"
            break
    else:
        text = f"{a:,.0f}" if unit != "EUR" or a >= 100 else f"{a:,.2f}"
    return f"{sign}€ {text}" if unit == "EUR" else f"{sign}{text}"


def fmt_kpi(kpi, x):
    return fmt_number(x, KPIS[kpi][1] if kpi in KPIS else "")


def fmt_delta(kpi, x):
    return ("+" if x >= 0 else "") + fmt_kpi(kpi, x)
