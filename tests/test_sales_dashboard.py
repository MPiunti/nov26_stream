"""Tests of the sales BI dashboard app (apps/sales_dashboard) and doc/sales_dashboard.md. Standard library only.

app.py, figures.py and sql_warehouse.py need Dash, plotly and the Databricks connector, so they're only parsed;
the logic (bi.py) and the SQL (dashboard_sql.py) are imported and run.
"""
import ast
import os
import re
import sys
import unittest

from helpers import constants, parse, path, read_text

APP = ("apps", "sales_dashboard")
sys.path.insert(0, path(*APP, "app"))
import bi  # noqa: E402
import dashboard_sql as q  # noqa: E402

WRITE_WORDS = re.compile(r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|CREATE|ALTER|TRUNCATE|GRANT)\b", re.I)


def _all_queries(f):
    yield q.sales_trend_sql(f)
    yield q.people_trend_sql(f)
    for column in list(q.GEO_LEVELS.values()) + list(q.PRODUCT_LEVELS.values()):
        yield q.sales_breakdown_sql(f, column)
    for column in q.GEO_LEVELS.values():
        yield q.people_breakdown_sql(f, column)
    yield q.freshness_sql()
    yield q.stores_sql()
    yield q.products_sql()


def _sales(date, hour, value, quantity=1, region="EUROPE"):
    return {"region": region, "utc_date": date, "utc_hour": hour, "value": float(value), "quantity": float(quantity),
            "transactions": float(quantity)}


def _people(date, hour, people_in, people_out=0, region="EUROPE"):
    return {"region": region, "utc_date": date, "utc_hour": hour, "people_in": float(people_in),
            "people_out": float(people_out)}


class QueryTests(unittest.TestCase):

    FULL = q.Filters(dates=("2026-11-13", "2026-11-14"), regions=("EUROPE",), countries=("IT",),
                     stores=("IT-MI-001",), categories=("SHOES",), products=("SH-0001",), store_type="FLAGSHIP")

    def test_read_only(self):
        for f in (q.Filters(), self.FULL):
            for sql, _ in _all_queries(f):
                self.assertTrue(sql.lstrip().upper().startswith("SELECT"), sql)
                self.assertNotRegex(sql, WRITE_WORDS)

    def test_reads_only_the_current_simulation_views_and_the_dimensions(self):
        tables = set()
        for sql, _ in _all_queries(self.FULL):
            tables.update(re.findall(r"\b(?:FROM|JOIN)\s+(\S+)", sql))
        self.assertEqual(tables, set(q.DEFAULT_TABLES.values()))
        self.assertEqual(q.DEFAULT_TABLES, {
            "SALES_TABLE": "workspace.test02_streaming.current_sales_transactions",
            "PEOPLE_TABLE": "workspace.test02_streaming.current_people_counter_events",
            "STORE_TABLE": "workspace.test02_warehouse.dim_store",
            "PRODUCT_TABLE": "workspace.test02_warehouse.dim_product"})

    def test_filter_values_are_parameters_not_sql(self):
        evil = "x' OR '1'='1"
        f = q.Filters(regions=(evil,), countries=(evil,), stores=(evil,), categories=(evil,), products=(evil,))
        for sql, params in _all_queries(f):
            self.assertNotIn(evil, sql)
        sql, params = q.sales_trend_sql(f)
        self.assertEqual(sorted(params), ["category_0", "country_0", "product_0", "region_0", "store_0"])
        self.assertTrue(all(v == evil for v in params.values()))
        for bad in ("2026-13", "x' OR 1=1"):
            with self.assertRaises(ValueError):
                q.Filters(dates=(bad,))
        with self.assertRaises(ValueError):
            q.Filters(store_type="ANY")
        with self.assertRaises(ValueError):
            q.sales_breakdown_sql(q.Filters(), "d.store_name; DROP TABLE x")

    def test_every_filter_reaches_the_sales_queries(self):
        sql, params = q.sales_trend_sql(self.FULL)
        for clause in ("CAST(s.transaction_timestamp_utc AS DATE) IN (CAST(:date_0 AS DATE), CAST(:date_1 AS DATE))",
                       "d.macro_region IN (:region_0)", "d.country_code IN (:country_0)", "d.store_id IN (:store_0)",
                       "s.category IN (:category_0)", "s.product_id IN (:product_0)", "d.is_flagship"):
            self.assertIn(clause, sql)
        self.assertEqual(params["date_1"], "2026-11-14")
        self.assertIn("NOT d.is_flagship", q.sales_trend_sql(q.Filters(store_type="OTHER"))[0])
        self.assertNotIn("WHERE", q.sales_trend_sql(q.Filters())[0])

    def test_people_ignore_category_and_product(self):
        sql, params = q.people_trend_sql(self.FULL)
        self.assertNotIn("category", sql)
        self.assertNotIn("product", sql)
        self.assertIn("d.store_id IN (:store_0)", sql)
        self.assertIn("CAST(convert_timezone(d.timezone_id, 'UTC', s.event_timestamp) AS DATE) IN", sql)

    def test_grouped_by_region_and_gmt_date_and_hour(self):
        """One GMT timeline: sales use silver's transaction_timestamp_utc, people are converted the same way."""
        sql, _ = q.sales_trend_sql(q.Filters())
        self.assertIn("SELECT d.macro_region AS region, CAST(s.transaction_timestamp_utc AS DATE) AS utc_date, "
                      "HOUR(s.transaction_timestamp_utc) AS utc_hour", sql)
        self.assertIn("GROUP BY 1, 2, 3", sql)
        self.assertIn("SUM(s.amount) AS value, SUM(s.quantity) AS quantity", sql)
        people, _ = q.people_trend_sql(q.Filters())
        self.assertIn("HOUR(convert_timezone(d.timezone_id, 'UTC', s.event_timestamp)) AS utc_hour", people)
        self.assertIn("event_type = 'ENTRY'", people)
        for other, _ in _all_queries(q.Filters()):
            self.assertNotRegex(other, r"CAST\(s\.(transaction|event)_timestamp AS DATE\)", "local dates are gone")

    def test_table_names_are_checked(self):
        os.environ["SALES_TABLE"] = "a.b; DROP"
        try:
            with self.assertRaises(ValueError):
                q.table("SALES_TABLE")
        finally:
            del os.environ["SALES_TABLE"]


class KpiTests(unittest.TestCase):

    def test_totals(self):
        t = bi.totals([_sales("2026-11-13", 10, 1000, 2), _sales("2026-11-13", 11, 500, 1)],
                      [_people("2026-11-13", 10, 30, 20)])
        self.assertEqual((t["VALUE"], t["QUANTITY"], t["AVG_PRICE"], t["PEOPLE_IN"]), (1500, 3, 500, 30))
        self.assertAlmostEqual(t["ITEMS_PER_VISITOR"], 0.1)
        self.assertEqual(bi.totals([], [])["AVG_PRICE"], 0)

    def test_live_delta_only_with_the_same_filters(self):
        f = q.Filters(regions=("ASIA",))
        sig = bi.signature(f)
        snap = {"signature": sig, "totals": {"VALUE": 100.0, "QUANTITY": 1.0}}
        self.assertEqual(bi.live_delta({"VALUE": 250.0, "QUANTITY": 3.0}, snap, sig), {"VALUE": 150, "QUANTITY": 2})
        self.assertIsNone(bi.live_delta({"VALUE": 1.0}, snap, bi.signature(q.Filters())))
        self.assertIsNone(bi.live_delta({"VALUE": 1.0}, None, sig))
        import json
        self.assertEqual(json.loads(json.dumps(sig)), sig, "the signature is stored in the browser as JSON")

    def test_formatting(self):
        self.assertEqual(bi.fmt_kpi("VALUE", 4_750_000_000), "€ 4.75 B")
        self.assertEqual(bi.fmt_kpi("VALUE", 23_070_000), "€ 23.07 M")
        self.assertEqual(bi.fmt_kpi("QUANTITY", 179_300), "179.30 K")
        self.assertEqual(bi.fmt_kpi("AVG_PRICE", 41), "€ 41.00")
        self.assertEqual(bi.fmt_delta("QUANTITY", -179_300), "-179.30 K")

    def test_normalize(self):
        from datetime import date
        from decimal import Decimal
        row = bi.normalize([{"utc_date": date(2026, 11, 14), "utc_hour": 15, "value": Decimal("12.50"),
                             "quantity": None}])[0]
        self.assertEqual(row, {"utc_date": "2026-11-14", "utc_hour": 15, "value": 12.5, "quantity": 0.0})


class ChartTests(unittest.TestCase):

    def test_trend_one_line_per_macro_region_on_one_gmt_timeline(self):
        from datetime import datetime
        rows = [_sales("2026-11-13", 22, 10, region="AMERICAS"), _sales("2026-11-13", 23, 5, region="AMERICAS"),
                _sales("2026-11-14", 1, 7, region="ASIA"), _sales("2026-11-14", 1, 3, region="ASIA")]
        series = bi.trend_series(rows, "VALUE")
        self.assertEqual(list(series), ["AMERICAS", "ASIA"], "regions in fixed order, only those with data")
        hours = [datetime(2026, 11, 13, 22), datetime(2026, 11, 13, 23), datetime(2026, 11, 14, 0),
                 datetime(2026, 11, 14, 1)]
        self.assertEqual(series["AMERICAS"], (hours, [10, 5, 0, 0]), "across midnight GMT; closed hours are 0")
        self.assertEqual(series["ASIA"], (hours, [0, 0, 0, 10]), "same timeline for every region")
        self.assertEqual(bi.trend_series([], "VALUE"), {})

    def test_trend_cumulative_grows_through_the_run(self):
        rows = [_sales("2026-11-13", 23, 100, 1), _sales("2026-11-14", 1, 300, 1)]
        self.assertEqual(bi.trend_series(rows, "VALUE", cumulative=True)["EUROPE"][1], [100, 100, 400])
        self.assertEqual(bi.trend_series(rows, "AVG_PRICE", cumulative=True)["EUROPE"][1], [100, 100, 200])
        self.assertEqual(bi.trend_series(rows, "AVG_PRICE")["EUROPE"][1], [100, None, 300],
                         "no items, no average: a gap, not a drop to 0")

    def test_region_lines_have_distinct_colours(self):
        consts = constants(parse(*APP, "app", "figures.py"))
        colours = consts["REGION_COLORS"]
        self.assertEqual(set(colours), set(bi.REGIONS))
        self.assertEqual(len(set(colours.values())), 3)

    def test_breakdown_cumulative_per_date(self):
        rows = [{"member": m, "utc_date": d, "value": float(v), "quantity": 1.0}
                for m, d, v in (("SHOES", "2026-11-13", 10), ("SHOES", "2026-11-14", 50), ("BAGS", "2026-11-13", 40))]
        members, dates, values, hidden = bi.breakdown(rows, "VALUE")
        self.assertEqual(members, ["SHOES", "BAGS"], "largest total first")
        self.assertEqual(dates, ["2026-11-13", "2026-11-14"])
        self.assertEqual(values, {"2026-11-13": [10, 40], "2026-11-14": [50, 0]})
        self.assertEqual(hidden, 0)
        members, dates, values, _ = bi.breakdown(rows, "AVG_PRICE")
        self.assertEqual((members, dates, values["all dates"]), (["BAGS", "SHOES"], ["all dates"], [40, 30]),
                         "average price over all dates: shoes (10 + 50) / 2, bags 40 / 1")

    def test_breakdown_keeps_the_top_members(self):
        rows = [{"member": f"S{i:02d}", "utc_date": "2026-11-14", "value": float(i), "quantity": 1.0}
                for i in range(40)]
        members, _, _, hidden = bi.breakdown(rows, "VALUE")
        self.assertEqual((len(members), hidden, members[0]), (bi.TOP_MEMBERS, 40 - bi.TOP_MEMBERS, "S39"))


class DrillTests(unittest.TestCase):

    START = {"GEO": "REGION", "PRODUCT": "CATEGORY"}

    def test_geography_region_country_store(self):
        f, levels = bi.drill_down(q.Filters(), self.START, "GEO", "EUROPE")
        self.assertEqual((f.regions, levels["GEO"]), (("EUROPE",), "COUNTRY"))
        f, levels = bi.drill_down(f, levels, "GEO", "IT")
        self.assertEqual((f.countries, levels["GEO"]), (("IT",), "STORE"))
        f, levels = bi.drill_down(f, levels, "GEO", "IT-MI-001")
        f, levels = bi.drill_down(f, levels, "GEO", "IT-MI-002")
        self.assertEqual(f.stores, ("IT-MI-001", "IT-MI-002"), "at the store level a click toggles the store")
        f, _ = bi.drill_down(f, levels, "GEO", "IT-MI-001")
        self.assertEqual(f.stores, ("IT-MI-002",))
        f, levels = bi.drill_up(f, levels, "GEO")
        self.assertEqual((f.regions, f.countries, f.stores, levels["GEO"]), (("EUROPE",), (), (), "COUNTRY"))
        f, levels = bi.drill_up(f, levels, "GEO")
        self.assertEqual((f.regions, levels["GEO"]), ((), "REGION"))

    def test_product_category_product(self):
        f, levels = bi.drill_down(q.Filters(regions=("ASIA",)), self.START, "PRODUCT", "BAGS")
        self.assertEqual((f.categories, levels), (("BAGS",), {"GEO": "REGION", "PRODUCT": "PRODUCT"}))
        self.assertEqual(f.regions, ("ASIA",), "drilling a product keeps the geography")
        f, levels = bi.drill_down(f, levels, "PRODUCT", "BG-0001")
        self.assertEqual(f.products, ("BG-0001",))
        f, levels = bi.drill_up(f, levels, "PRODUCT")
        self.assertEqual((f.categories, f.products, levels["PRODUCT"]), ((), (), "CATEGORY"))

    def test_drill_levels_match_the_queries(self):
        self.assertEqual(bi.GEO_PATH, tuple(q.GEO_LEVELS))
        self.assertEqual(bi.PRODUCT_PATH, tuple(q.PRODUCT_LEVELS))


class AppTests(unittest.TestCase):

    def test_every_app_file_is_valid_python(self):
        for f in sorted(os.listdir(path(*APP, "app"))):
            if f.endswith(".py"):
                ast.parse(read_text(*APP, "app", f), filename=f)

    def test_logic_modules_use_the_standard_library_only(self):
        allowed = {"os", "re", "dataclasses", "datetime", "dashboard_sql"}
        for f in ("bi.py", "dashboard_sql.py"):
            for node in ast.walk(parse(*APP, "app", f)):
                if isinstance(node, ast.Import):
                    names = {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom):
                    names = {node.module.split(".")[0]}
                else:
                    continue
                self.assertLessEqual(names, allowed, f)

    def test_tab_title_is_fixed(self):
        """No "Updating..." during callbacks, and nothing changes document.title."""
        code = read_text(*APP, "app", "app.py")
        self.assertIn('APP_TITLE = "Sales BI dashboard"', code)
        self.assertIn("title=APP_TITLE, update_title=None", code)
        self.assertNotIn("document.title", code)

    def test_no_previous_day_comparison(self):
        code = read_text(*APP, "app", "app.py") + read_text(*APP, "app", "bi.py")
        for gone in ("like_for_like", "VS PREV", "fmt_pct"):
            self.assertNotIn(gone, code)

    def test_compact_layout_with_side_margins(self):
        """5% white space at each side on phones, 7.5% on tablets and laptops, 10% on large screens."""
        css = read_text(*APP, "app", "assets", "dashboard.css")
        self.assertIn(".page { padding: 8px 5vw 12px 5vw; }", css)
        self.assertIn("@media (min-width: 768px)  { .page { padding-left: 7.5vw; padding-right: 7.5vw; } }", css)
        self.assertIn("@media (min-width: 1400px) { .page { padding-left: 10vw; padding-right: 10vw; } }", css)
        self.assertIn(".filters .form-check:not(.form-switch) { padding-left: 0;", css,
                      "the compact buttons rule must not remove the switch's padding (the switch would stick out)")
        self.assertIn(".filters .form-switch { display: flex; justify-content: center;", css, "Live switch centred")
        code = read_text(*APP, "app", "app.py")
        self.assertIn('className="page"', code)
        self.assertIn('"name": "viewport"', code, "phones render at device width")
        self.assertIn("xs=12", code, "columns stack on phones")

    def test_one_refresh_at_a_time(self):
        """A refresh slower than the interval must not be overtaken (Dash would drop its result: a frozen screen)."""
        code = read_text(*APP, "app", "app.py")
        gate = code.split("# One refresh at a time.", 1)[1].split("app.clientside_callback(", 1)[1].split("\n)\n", 1)[0]
        self.assertIn("if (tick && done !== tick && Date.now() - tick < {STUCK_MS})", gate)
        self.assertIn('Output("tick", "data"),\n    Input("refresh", "n_intervals")', gate)
        self.assertIn("STUCK_MS = 30000", code)
        refresh = code.split("def refresh(", 1)[0].rsplit("@app.callback(", 1)[1]
        self.assertIn('Input("tick", "data")', refresh, "the refresh follows the gate, not the interval")
        self.assertNotIn('Input("refresh", "n_intervals")', refresh)
        self.assertIn('Output("done", "data")', refresh)
        body = code.split("def refresh(", 1)[1].split("\nif __name__", 1)[0]
        self.assertEqual(body.count(", tick])"), 2, "every return reports its tick as done")
        self.assertIn("PARALLEL_QUERIES = 5", read_text(*APP, "app", "sql_warehouse.py"))

    def test_footer_shows_live_freshness_in_gmt(self):
        """Refresh, last sale, last people event: GMT times, a status dot and an age ticked every second."""
        code = read_text(*APP, "app", "app.py")
        self.assertIn('FRESH_CHIPS = (("refresh", "Refreshed"), ("sales", "Last sale"), ("people", "Last people event"))',
                      code)
        self.assertIn('dcc.Interval(id="clock", interval=1000)', code)
        self.assertIn("FRESH_OK_S, FRESH_WARN_S = 30, 120", code)
        ages = code.split("FRESH_OK_S, FRESH_WARN_S = 30, 120", 1)[1].split("\n)\n", 1)[0]
        self.assertIn('Input("clock", "n_intervals"), Input("fresh-ms", "data")', ages)
        self.assertIn("Date.now() - ms", ages, "ages are computed in the browser, between refreshes too")
        self.assertIn('f"{now:%H:%M:%S} GMT"', code)
        self.assertIn('"sales": _epoch_ms(latest("SALES", "last_ingested"))', code)
        self.assertIn('"people": _epoch_ms(latest("PEOPLE", "last_ingested"))', code)
        self.assertNotIn('Output("footer", "children")', code)
        css = read_text(*APP, "app", "assets", "dashboard.css")
        for cls in (".dot-ok", ".dot-warn", ".dot-stale", ".chip"):
            self.assertIn(cls, css)

    def test_refreshes_every_few_seconds(self):
        code = read_text(*APP, "app", "app.py")
        self.assertIn('REFRESH_SECONDS = max(2, int(os.environ.get("REFRESH_SECONDS", "5")))', code)
        self.assertIn('dcc.Interval(id="refresh", interval=REFRESH_SECONDS * 1000)', code)
        self.assertIn('value: "5"', read_text(*APP, "app", "app.yaml"))

    def test_kpis_and_levels(self):
        self.assertEqual(list(bi.KPIS), ["VALUE", "QUANTITY", "AVG_PRICE", "PEOPLE_IN"])
        self.assertEqual(list(q.GEO_LEVELS), ["REGION", "COUNTRY", "STORE"])
        self.assertEqual(list(q.PRODUCT_LEVELS), ["CATEGORY", "PRODUCT"])
        consts = constants(parse(*APP, "app", "app.py"))
        self.assertEqual(consts["CATEGORIES"], ("SHOES", "BAGS", "READY_TO_WEAR", "ACCESSORIES", "TRAVEL", "SUNGLASSES"))
        self.assertEqual(consts["REGIONS"], ("EUROPE", "AMERICAS", "ASIA"))

    def test_queries_run_in_parallel_on_reused_connections(self):
        code = read_text(*APP, "app", "sql_warehouse.py")
        self.assertIn("threading.local()", code)
        self.assertIn("ThreadPoolExecutor", code)
        self.assertIn("cursor.execute(sql, params or None)", code)


class BundleTests(unittest.TestCase):

    def test_separate_bundle(self):
        app_yml = read_text(*APP, "databricks.yml")
        self.assertIn('name: "retail_sales_dashboard_bundle"', app_yml)
        self.assertNotIn("retail_sales_dashboard_bundle", read_text("databricks.yml"))
        self.assertNotIn("retail_sales_dashboard_bundle", read_text("apps", "people_stream", "databricks.yml"))
        self.assertEqual(app_yml.count("host: https://dbc-06fb0002-68c5.cloud.databricks.com"), 2)
        self.assertIn("default: sales-bi-${workspace.current_user.domain_friendly_name}", app_yml)
        self.assertLessEqual(len("sales-bi-michele-piunti"), 30)

    def test_grants_are_read_only(self):
        res = read_text(*APP, "resources", "sales_dashboard.app.yml")
        self.assertIn("source_code_path: ../app", res)
        grants = re.findall(r"securable_full_name: \$\{var\.catalog\}\.\$\{var\.(\w+)\}\.(\w+)\s*\n\s*"
                            r"securable_type: TABLE\s*\n\s*permission: (\w+)", res)
        self.assertEqual(sorted(grants), [
            ("schema", "current_people_counter_events", "SELECT"), ("schema", "current_sales_transactions", "SELECT"),
            ("warehouse_schema", "dim_product", "SELECT"), ("warehouse_schema", "dim_store", "SELECT")])
        self.assertNotIn("MODIFY", res)
        self.assertIn("permission: CAN_USE", res)

    def test_app_yaml_tables_match_the_grants_and_the_queries(self):
        app_yaml = read_text(*APP, "app", "app.yaml")
        for var, name in q.DEFAULT_TABLES.items():
            self.assertRegex(app_yaml, rf"- name: {var}\n\s+value: {re.escape(name)}")
        self.assertIn("valueFrom: sql-warehouse", app_yaml)

    def test_requirements_are_pinned(self):
        for line in read_text(*APP, "app", "requirements.txt").split():
            self.assertRegex(line, r"^[A-Za-z0-9_.-]+==[\w.]+$")

    def test_no_coupling_with_the_people_stream_app(self):
        for f in os.listdir(path(*APP, "app")):
            if f.endswith(".py"):
                code = read_text(*APP, "app", f)
                self.assertNotIn("people_stream", code)
                self.assertNotIn("simulated_", code, f"{f}: the dashboard reads silver, not the sources")


class DocTests(unittest.TestCase):

    def test_readme_lists_app_files(self):
        readme = read_text("readme.md")
        for root, dirs, files in os.walk(path(*APP)):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", ".databricks")]
            for f in files:
                self.assertIn(f, readme, f"{os.path.join(root, f)} isn't in readme.md")

    def test_doc_describes_the_screen_and_the_rules(self):
        doc = read_text("doc", "sales_dashboard.md")
        for text in ("`silver_sales_transactions`", "`silver_people_counter_events`", "every 5 seconds",
                     "Area → Country → Store", "Merch. category → Product", "`update_title=None`",
                     "`sales-bi-<user>`", "ITEMS PER VISITOR", "one line per macro region", "`transaction_timestamp_utc`",
                     "5% of the width on phones", "`current_sales_transactions`", "Always the current simulation"):
            self.assertIn(text, doc)


if __name__ == "__main__":
    unittest.main()
