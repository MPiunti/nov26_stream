"""Tests of the metric views (src/metrics/), their deploy job and doc/kpi_glossary.md. Standard library only."""
import re
import unittest

from helpers import read_text

METRICS = ("client_metrics", "store_metrics")
SALES = "workspace.test02_streaming.silver_sales_transactions"
PEOPLE = "workspace.test02_streaming.silver_people_counter_events"
ENTRY = re.compile(r'- name: (.+)\n\s+expr: (.+)\n\s+comment: "(.+)"')


def _statements(name):
    """The file without its header comments: the two statements."""
    return re.sub(r"(?m)^--.*\n", "", read_text("src", "metrics", f"{name}.sql"))


def _definition(name):
    """The ALTER VIEW part of a metric view file: the full definition."""
    return _statements(name).split("ALTER VIEW", 1)[1]


def _entries(name):
    """(dimensions, measures) of a metric view, each as {name: (expr, comment)}."""
    dims, measures = _definition(name).split("\nmeasures:\n", 1)
    return ({n: (e, c) for n, e, c in ENTRY.findall(dims)}, {n: (e, c) for n, e, c in ENTRY.findall(measures)})


class MetricViewTests(unittest.TestCase):

    def test_two_views_one_per_entity(self):
        """Client KPIs in client_metrics, store KPIs in store_metrics; nothing else in src/metrics/."""
        import os
        from helpers import path
        self.assertEqual(sorted(os.listdir(path("src", "metrics"))), [f"{m}.sql" for m in sorted(METRICS)])

    def test_created_if_missing_then_altered_so_grants_survive(self):
        """Replacing a view drops its grants (the dashboard lost its access that way); ALTER keeps them."""
        for name in METRICS:
            sql = _statements(name)
            target = f"workspace.test02_metric.{name}"
            self.assertNotRegex(sql, r"(?i)CREATE\s+OR\s+REPLACE")
            self.assertIn(f"CREATE VIEW IF NOT EXISTS {target}\nWITH METRICS\nLANGUAGE YAML\nAS $$", sql)
            self.assertIn(f"ALTER VIEW {target}\nAS $$", sql)
            self.assertLess(sql.index("CREATE VIEW IF NOT EXISTS"), sql.index("ALTER VIEW"))

    def test_yaml_starts_at_column_0(self):
        """The top-level YAML keys must not be indented, or the definition doesn't parse."""
        for name in METRICS:
            for key in ("version: 1.1", "source:", "comment:", "dimensions:", "measures:"):
                self.assertRegex(_definition(name), rf"(?m)^{re.escape(key)}", f"{name}: {key}")

    def test_every_dimension_and_measure_has_a_functional_description(self):
        for name in METRICS:
            dims, measures = _entries(name)
            listed = re.findall(r"(?m)^  - name: ", _definition(name).split("\ndimensions:\n", 1)[1])
            self.assertEqual(len(listed), len(dims) + len(measures), f"{name}: an entry without a comment")
            for entry, (_, comment) in {**dims, **measures}.items():
                self.assertGreater(len(comment.split()), 5, f"{name}.{entry}: describe it")

    def test_client_metrics_over_sales_joined_on_natural_keys(self):
        client = _definition("client_metrics")
        self.assertIn(f"source: {SALES}\n", client)
        for dim, key in (("dim_client", "client_id"), ("dim_store", "store_id"), ("dim_product", "product_id")):
            self.assertIn(f"source: workspace.test02_warehouse.{dim}\n    'on': source.{key} = {dim}.{key}", client)

    def test_store_metrics_put_sales_and_traffic_on_one_timeline(self):
        """Both silver facts in one source, so Conversion is a measure that holds for any store, region or hour."""
        store = _definition("store_metrics")
        source = store.split("source: |", 1)[1].split("\ncomment:", 1)[0]
        self.assertIn(f"FROM {SALES} s", source)
        self.assertIn(f"FROM {PEOPLE} e", source)
        self.assertIn("UNION ALL", source)
        self.assertIn("JOIN workspace.test02_warehouse.dim_store d ON s.store_id = d.store_id", source)
        self.assertIn("LEFT JOIN workspace.test02_warehouse.dim_client c ON s.client_id = c.client_id", source)
        self.assertIn("s.transaction_timestamp_utc AS time_utc", source)
        self.assertIn("convert_timezone(e.store_timezone_id, 'UTC', e.event_timestamp)", source, "GMT, like sales")
        self.assertNotIn("\njoins:", store, "a query source can't have joins")
        dims, _ = _entries("store_metrics")
        self.assertEqual((dims["Date (GMT)"][0], dims["Hour (GMT)"][0]), ('"CAST(time_utc AS DATE)"', '"HOUR(time_utc)"'))

    def test_the_approved_kpis(self):
        """The client and store KPIs approved in doc/kpi_metrics.md section 6."""
        _, client = _entries("client_metrics")
        _, store = _entries("store_metrics")
        for kpi in ("Total Spent", "Transactions", "Items", "Average Basket", "Stores Visited", "Online Share"):
            self.assertIn(kpi, client)
        for kpi in ("Revenue", "Transactions", "Average Basket", "Items per Basket", "Distinct Clients",
                    "Visitor Share", "People In", "People Out", "Conversion"):
            self.assertIn(kpi, store)
        for measures in (client, store):
            self.assertIn("COUNT(DISTINCT", measures["Transactions"][0], "a transaction is a basket")
        self.assertEqual(store["Conversion"][0], '"try_divide(MEASURE(`Store Transactions`), MEASURE(`People Out`))"')
        self.assertIn("channel <> 'ECOM'", store["Store Transactions"][0], "physical stores only")

    def test_ratios_never_fail_on_zero(self):
        """try_divide: a store with traffic but no sale yet, or e-commerce without people, gives empty, not an error."""
        for name in METRICS:
            for entry, (expr, _) in _entries(name)[1].items():
                if "/" in expr:
                    self.assertTrue(expr.strip('"').startswith("try_divide("), f"{name}.{entry}")

    def test_filtered_sums_return_0_not_null(self):
        """A filtered sum with no matching row is NULL: a flagship's online spend would show blank, not 0."""
        for name in METRICS:
            for entry, (expr, _) in _entries(name)[1].items():
                if "SUM(" in expr:
                    self.assertTrue(expr.strip('"').startswith("COALESCE(SUM("), f"{name}.{entry}")

    def test_both_views_share_the_store_and_time_dimensions(self):
        client_dims, _ = _entries("client_metrics")
        store_dims, _ = _entries("store_metrics")
        for both in ("Simulation", "Store", "Store Name", "Channel", "Store Country", "Macro Region", "Date (GMT)"):
            self.assertIn(both, client_dims)
            self.assertIn(both, store_dims)
        for entity in ("Client", "Client Country", "Client Region", "Client Type", "Category"):
            self.assertIn(entity, client_dims)

    def test_deploy_job_runs_every_definition(self):
        job = read_text("resources", "modeling.metrics.job.yml")
        self.assertEqual(sorted(re.findall(r"path: \.\./src/metrics/(\w+)\.sql", job)), sorted(METRICS))
        self.assertEqual(job.count("warehouse_id: ${var.warehouse_id}"), len(METRICS))
        for absent in ("schedule", "trigger", "continuous", "clusters"):
            self.assertNotRegex(job, rf"(?m)^\s+{absent}:", "run on demand only")
        root = read_text("databricks.yml")
        self.assertRegex(root, r"metric_schema:\n.*\n\s+default: test02_metric")
        self.assertRegex(root, r"warehouse_id:\n.*\n\s+lookup:\n\s+warehouse: Serverless Starter Warehouse")


class GlossaryTests(unittest.TestCase):

    def test_glossary_repeats_every_description_word_for_word(self):
        glossary = read_text("doc", "kpi_glossary.md")
        for name in METRICS:
            dims, measures = _entries(name)
            self.assertIn(f"`workspace.test02_metric.{name}`", glossary)
            for entry, (_, comment) in {**dims, **measures}.items():
                self.assertIn(f"| {entry} | {comment} |", glossary, f"{name}.{entry}")

    def test_nothing_in_the_glossary_that_isnt_defined(self):
        glossary = read_text("doc", "kpi_glossary.md")
        defined = set()
        for name in METRICS:
            dims, measures = _entries(name)
            defined |= set(dims) | set(measures)
        rows = set(re.findall(r"(?m)^\| ([^|`*]+?) \| (?!Functional description)", glossary)) - {"---"}
        self.assertEqual(rows - defined, set())


if __name__ == "__main__":
    unittest.main()
