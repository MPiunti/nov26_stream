"""Tests of the metric views (src/metrics/), their deploy job and doc/kpi_glossary.md. Standard library only."""
import re
import unittest

from helpers import read_text

METRICS = {"sales_metrics": "silver_sales_transactions", "people_metrics": "silver_people_counter_events"}
ENTRY = re.compile(r'- name: (.+)\n\s+expr: (.+)\n\s+comment: "(.+)"')


def _definition(name):
    """The ALTER VIEW part of a metric view file: the full definition."""
    return read_text("src", "metrics", f"{name}.sql").split("ALTER VIEW", 1)[1]


def _entries(name):
    """(dimensions, measures) of a metric view, each as {name: (expr, comment)}."""
    dims, measures = _definition(name).split("\nmeasures:\n", 1)
    return ({n: (e, c) for n, e, c in ENTRY.findall(dims)}, {n: (e, c) for n, e, c in ENTRY.findall(measures)})


class MetricViewTests(unittest.TestCase):

    def test_created_if_missing_then_altered_so_grants_survive(self):
        """CREATE OR REPLACE drops the grants (the dashboard lost its access that way); ALTER keeps them."""
        for name, source in METRICS.items():
            sql = re.sub(r"(?m)^--.*\n", "", read_text("src", "metrics", f"{name}.sql"))  # statements only
            target = f"workspace.test02_metric.{name}"
            self.assertNotRegex(sql, r"(?i)CREATE\s+OR\s+REPLACE")
            self.assertIn(f"CREATE VIEW IF NOT EXISTS {target}\nWITH METRICS\nLANGUAGE YAML\nAS $$", sql)
            self.assertIn(f"ALTER VIEW {target}\nAS $$", sql)
            self.assertLess(sql.index("CREATE VIEW IF NOT EXISTS"), sql.index("ALTER VIEW"))
            self.assertEqual(sql.count(f"source: workspace.test02_streaming.{source}"), 2, "both statements, silver")

    def test_yaml_starts_at_column_0(self):
        """The top-level YAML keys must not be indented, or the definition doesn't parse."""
        for name in METRICS:
            definition = _definition(name)
            for key in ("version: 1.1", "source:", "comment:", "joins:", "dimensions:", "measures:"):
                self.assertRegex(definition, rf"(?m)^{re.escape(key)}", f"{name}: {key}")

    def test_every_dimension_and_measure_has_a_functional_description(self):
        for name in METRICS:
            definition = _definition(name)
            dims, measures = _entries(name)
            self.assertEqual(len(re.findall(r"(?m)^  - name: ", definition.split("\ndimensions:\n", 1)[1])),
                             len(dims) + len(measures), f"{name}: an entry without a comment")
            for entry, (_, comment) in {**dims, **measures}.items():
                self.assertGreater(len(comment.split()), 5, f"{name}.{entry}: describe it")

    def test_joins_on_natural_keys(self):
        sales = _definition("sales_metrics")
        for dim, key in (("dim_store", "store_id"), ("dim_client", "client_id"), ("dim_product", "product_id")):
            self.assertIn(f"source: workspace.test02_warehouse.{dim}\n    'on': source.{key} = {dim}.{key}", sales)
        self.assertIn("'on': source.store_id = dim_store.store_id", _definition("people_metrics"))

    def test_the_approved_kpis(self):
        """The client and store KPIs approved in doc/kpi_metrics.md section 6."""
        sales_dims, sales = _entries("sales_metrics")
        people_dims, people = _entries("people_metrics")
        for kpi in ("Revenue", "Transactions", "Items", "Average Basket", "Items per Basket", "Stores Visited",
                    "Distinct Clients", "Online Share", "Visitor Share", "Store Transactions"):
            self.assertIn(kpi, sales)
        self.assertEqual(set(people), {"People In", "People Out"})
        self.assertIn('synonyms: ["Total spent", "Sales value", "Turnover"]', _definition("sales_metrics"),
                      "a client's total spent is Revenue by client")
        self.assertEqual(sales["Transactions"][0], "COUNT(DISTINCT source.transaction_id)", "a transaction is a basket")
        self.assertEqual(sales["Average Basket"][0], '"MEASURE(`Revenue`) / MEASURE(`Transactions`)"')
        for both in ("Simulation", "Store", "Channel", "Store Country", "Macro Region", "Date (GMT)", "Hour (GMT)"):
            self.assertIn(both, sales_dims)
            self.assertIn(both, people_dims, "Conversion divides the two views over the same slices")
        for entity in ("Client", "Client Country", "Client Type", "Category", "Product"):
            self.assertIn(entity, sales_dims)

    def test_filtered_measures_return_0_not_null(self):
        """A filtered sum with no matching row is NULL: a flagship's online share would show blank, not 0%."""
        for name in METRICS:
            for entry, (expr, _) in _entries(name)[1].items():
                if "FILTER (WHERE" in expr and expr.lstrip('"').startswith("SUM"):
                    self.fail(f"{name}.{entry}: wrap the filtered SUM in COALESCE(..., 0)")

    def test_deploy_job_runs_every_definition(self):
        job = read_text("resources", "modeling.metrics.job.yml")
        files = re.findall(r"path: \.\./src/metrics/(\w+)\.sql", job)
        self.assertEqual(sorted(files), sorted(METRICS))
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
        self.assertEqual(rows - defined, {"Conversion"}, "only Conversion combines the two views")

    def test_conversion_combines_the_two_views(self):
        glossary = read_text("doc", "kpi_glossary.md")
        self.assertIn("`Store Transactions` (sales_metrics) / `People Out` (people_metrics)", glossary)


if __name__ == "__main__":
    unittest.main()
