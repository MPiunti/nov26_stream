"""Logic of the sales dashboard: KPIs, deltas, drill-down and chart series. Standard library only.

Works on the rows of the queries in dashboard_sql.py, as lists of dicts. See doc/sales_dashboard.md.
"""
from dataclasses import replace

from dashboard_sql import Filters

# KPI on charts: label, unit. AVG_PRICE = value / quantity; PEOPLE_IN = entries counted by the sensors.
KPIS = {
    "VALUE": ("Sales value", "EUR"),
    "QUANTITY": ("Items sold", "items"),
    "AVG_PRICE": ("Average price", "EUR"),
    "PEOPLE_IN": ("People in", "people"),
}
SALES_KPIS = ("VALUE", "QUANTITY", "AVG_PRICE")
OPEN_HOUR, CLOSE_HOUR = 10, 20  # store opening hours (doc/dataset.md); the closing EXIT is at 20:00
TOP_MEMBERS = 15  # bars per breakdown chart

GEO_PATH = ("REGION", "COUNTRY", "STORE")
PRODUCT_PATH = ("CATEGORY", "PRODUCT")


# ------------------------------------------------------------------ rows

def normalize(rows):
    """Query rows to plain values: dates as YYYY-MM-DD, numbers as float, NULL sums as 0."""
    out = []
    for r in rows:
        row = {}
        for k, v in r.items():
            if k == "local_date":
                row[k] = str(v)[:10] if v is not None else None
            elif k in ("value", "quantity", "transactions", "people_in", "people_out", "row_count"):
                row[k] = float(v or 0)
            elif k == "local_hour":
                row[k] = int(v)
            else:
                row[k] = v
        out.append(row)
    return out


def metric(row, kpi):
    """One KPI from a row with value, quantity (and/or people_in)."""
    if kpi == "VALUE":
        return row.get("value", 0.0)
    if kpi == "QUANTITY":
        return row.get("quantity", 0.0)
    if kpi == "AVG_PRICE":
        q = row.get("quantity", 0.0)
        return row.get("value", 0.0) / q if q else 0.0
    if kpi == "PEOPLE_IN":
        return row.get("people_in", 0.0)
    raise ValueError(f"unknown KPI {kpi!r}")


def _add(acc, row, fields=("value", "quantity", "transactions", "people_in", "people_out")):
    for f in fields:
        if f in row:
            acc[f] = acc.get(f, 0.0) + row[f]
    return acc


# ------------------------------------------------------------------ KPI cards

def totals(sales_rows, people_rows):
    """Headline numbers. ITEMS_PER_VISITOR = items sold / people in (the category filter applies only to items)."""
    t = {"value": 0.0, "quantity": 0.0, "transactions": 0.0, "people_in": 0.0, "people_out": 0.0}
    for r in list(sales_rows) + list(people_rows):
        _add(t, r)
    return {
        "VALUE": t["value"],
        "QUANTITY": t["quantity"],
        "AVG_PRICE": metric(t, "AVG_PRICE"),
        "PEOPLE_IN": t["people_in"],
        "TRANSACTIONS": t["transactions"],
        "PEOPLE_OUT": t["people_out"],
        "ITEMS_PER_VISITOR": t["quantity"] / t["people_in"] if t["people_in"] else 0.0,
    }


def like_for_like(sales_rows, people_rows, kpi):
    """Latest store-local date vs the date before, over the same hours (up to the latest hour of the latest date).

    Returns (current, previous, percent change) or None when there's no earlier date or nothing to compare.
    """
    rows = people_rows if kpi == "PEOPLE_IN" else sales_rows
    dates = sorted({r["local_date"] for r in rows if r.get("local_date")})
    if len(dates) < 2:
        return None
    latest, previous = dates[-1], dates[-2]
    last_hour = max(r["local_hour"] for r in rows if r["local_date"] == latest)
    cur, prev = {}, {}
    for r in rows:
        if r["local_hour"] <= last_hour:
            if r["local_date"] == latest:
                _add(cur, r)
            elif r["local_date"] == previous:
                _add(prev, r)
    c, p = metric(cur, kpi), metric(prev, kpi)
    if not p:
        return None
    return c, p, (c - p) / p * 100


def live_delta(current, snapshot, signature):
    """Change of each KPI since the previous refresh with the same filters; None after a filter change."""
    if not snapshot or snapshot.get("signature") != signature:
        return None
    before = snapshot.get("totals", {})
    return {k: current[k] - before.get(k, 0.0) for k in current}


def signature(filters):
    """A stable, JSON-friendly key of the filters, to tell whether two refreshes are comparable."""
    return [list(filters.dates), list(filters.regions), list(filters.countries), list(filters.stores),
            list(filters.categories), list(filters.products), filters.store_type]


# ------------------------------------------------------------------ trend

def trend_series(rows, kpi, cumulative=False):
    """{date: (hours, values)}, one series per store-local date, hours OPEN_HOUR..CLOSE_HOUR.

    Hours without data count as 0 for value, quantity and people. Cumulative sums the hours within each date,
    so each line grows through the day; for AVG_PRICE it's the running average (cumulative value / quantity).
    """
    by_date = {}
    for r in rows:
        if r.get("local_date") is None:
            continue
        hours = by_date.setdefault(r["local_date"], {})
        _add(hours.setdefault(r["local_hour"], {}), r)
    series = {}
    for date in sorted(by_date):
        hours = by_date[date]
        last = max(hours)
        xs, ys, acc = [], [], {}
        for h in range(min(OPEN_HOUR, min(hours)), max(CLOSE_HOUR, last) + 1):
            if h > last:
                break  # the day hasn't reached this hour yet: stop the line, don't draw zeros
            cell = hours.get(h, {})
            if cumulative:
                _add(acc, cell)
                y = metric(acc, kpi)
            else:
                y = metric(cell, kpi)
            xs.append(h)
            ys.append(y)
        series[date] = (xs, ys)
    return series


# ------------------------------------------------------------------ breakdown charts

def breakdown(rows, kpi, top=TOP_MEMBERS):
    """Horizontal bars, cumulative per date: members ordered by total, and each member's value per date.

    Returns (members, dates, {date: [value per member]}, hidden), members largest first, at most `top`;
    `hidden` is how many members were left out. For AVG_PRICE the segments don't add up, so it's one
    segment per member over all dates (dates == ["all dates"]).
    """
    per_member, per_cell = {}, {}
    for r in rows:
        _add(per_member.setdefault(r["member"], {}), r)
        _add(per_cell.setdefault((r["member"], r["local_date"]), {}), r)
    members = sorted(per_member, key=lambda m: (-metric(per_member[m], kpi), str(m)))
    hidden = max(0, len(members) - top)
    members = members[:top]
    if kpi == "AVG_PRICE":
        return members, ["all dates"], {"all dates": [metric(per_member[m], kpi) for m in members]}, hidden
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


def fmt_pct(x):
    return f"{'+' if x >= 0 else ''}{x:.2f}%"


__all__ = ["Filters", "KPIS", "totals", "like_for_like", "live_delta", "trend_series", "breakdown",
           "drill_down", "drill_up", "signature", "fmt_kpi", "fmt_delta", "fmt_pct", "normalize"]
