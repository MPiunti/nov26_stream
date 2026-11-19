"""Tests of the Genie agent bundle (agents/kpi_genie) and doc/kpi_genie.md. Standard library only."""
import json
import os
import re
import sys
import unittest

from helpers import path, read_text

AGENT = ("agents", "kpi_genie")
HEX32 = re.compile(r"[0-9a-f]{32}")
CURRENT = "(SELECT current_simulation.simulation_id FROM workspace.test02_streaming.current_simulation)"


def _agent():
    return json.loads(read_text(*AGENT, "src", "kpi_genie.json"))


def _space():
    return _agent()["serialized_space"]


def _all_sql():
    """(kind, question, sql) of every example and benchmark."""
    s = _space()
    for e in s["instructions"]["example_question_sqls"]:
        yield "example", e["question"][0], " ".join(e["sql"])
    for b in s["benchmarks"]["questions"]:
        yield "benchmark", b["question"][0], " ".join(b["answer"][0]["content"])


class DefinitionRulesTests(unittest.TestCase):
    """The rules the Genie API enforces on a serialized space (version 2)."""

    def test_version_and_sizes(self):
        s = _space()
        self.assertEqual(s["version"], 2)
        sources = s["data_sources"]["tables"] + s["data_sources"]["metric_views"]
        self.assertLessEqual(len(sources), 30)
        self.assertLessEqual(len(s["instructions"]["text_instructions"]), 1)
        text = "".join(s["instructions"]["text_instructions"][0]["content"])
        self.assertLess(len(text), 2000, "text instructions are a last resort: keep them short")
        self.assertLess(len(json.dumps(s)), 3_500_000)

    def test_ids_are_32_hex_unique_and_sorted(self):
        s = _space()
        groups = {
            "sample_questions": s["config"]["sample_questions"],
            "benchmarks": s["benchmarks"]["questions"],
            "text_instructions": s["instructions"]["text_instructions"],
            "example_question_sqls": s["instructions"]["example_question_sqls"],
            "join_specs": s["instructions"]["join_specs"],
            "filters": s["instructions"]["sql_snippets"]["filters"],
        }
        for name, items in groups.items():
            ids = [i["id"] for i in items]
            self.assertTrue(all(HEX32.fullmatch(i) for i in ids), name)
            self.assertEqual(ids, sorted(ids), f"{name} must be sorted by id")
        questions = [i["id"] for i in groups["sample_questions"] + groups["benchmarks"]]
        self.assertEqual(len(questions), len(set(questions)), "question ids unique across samples and benchmarks")
        instructions = [i["id"] for g in ("text_instructions", "example_question_sqls", "join_specs", "filters")
                        for i in groups[g]]
        self.assertEqual(len(instructions), len(set(instructions)))

    def test_sources_and_columns_sorted(self):
        ds = _space()["data_sources"]
        for key in ("tables", "metric_views"):
            ids = [t["identifier"] for t in ds[key]]
            self.assertEqual(ids, sorted(ids), f"{key} sorted by identifier")
            for t in ds[key]:
                names = [c["column_name"] for c in t.get("column_configs", [])]
                self.assertEqual(names, sorted(names), f"{t['identifier']}: column_configs sorted")

    def test_text_fields_are_arrays(self):
        s = _space()
        for q in s["config"]["sample_questions"] + s["benchmarks"]["questions"]:
            self.assertIsInstance(q["question"], list)
        for e in s["instructions"]["example_question_sqls"]:
            self.assertIsInstance(e["sql"], list)
        for b in s["benchmarks"]["questions"]:
            self.assertEqual(b["answer"][0]["format"], "SQL")
            self.assertTrue(b["answer"][0]["content"], "every benchmark has a checked SQL answer")


class SemanticsTests(unittest.TestCase):

    def test_sources_are_the_metric_views_dimensions_and_current_facts(self):
        ds = _space()["data_sources"]
        self.assertEqual([t["identifier"] for t in ds["metric_views"]],
                         ["workspace.test02_metric.client_metrics", "workspace.test02_metric.store_metrics"])
        self.assertEqual(sorted(os.listdir(path("src", "metrics"))), ["client_metrics.sql", "store_metrics.sql"])
        self.assertEqual([t["identifier"] for t in ds["tables"]], [
            "workspace.test02_streaming.current_people_counter_events",
            "workspace.test02_streaming.current_sales_transactions",
            "workspace.test02_warehouse.dim_client", "workspace.test02_warehouse.dim_product",
            "workspace.test02_warehouse.dim_store"])

    def test_sql_names_only_kpis_and_dimensions_the_metric_views_define(self):
        from test_kpi_metrics import _entries
        defined = {}
        for view in ("client_metrics", "store_metrics"):
            dims, measures = _entries(view)
            defined[view] = (set(dims), set(measures))
        for kind, question, sql in _all_sql():
            for view, name in re.findall(r"MEASURE\((\w+)\.`([^`]+)`\)", sql):
                self.assertIn(name, defined[view][1], f"{kind} '{question}': {view}.{name} isn't a KPI")
            for view, name in re.findall(r"(?<!MEASURE\()\b(client_metrics|store_metrics)\.`([^`]+)`", sql):
                self.assertIn(name, defined[view][0] | defined[view][1], f"{kind} '{question}': {view}.{name}")

    def test_every_query_defaults_to_the_current_simulation(self):
        for kind, question, sql in _all_sql():
            self.assertIn(f"`Simulation` = {CURRENT}", sql, f"{kind} '{question}'")
        filters = _space()["instructions"]["sql_snippets"]["filters"]
        self.assertEqual(sorted(f["sql"][0] for f in filters), sorted(
            f"{view}.`Simulation` = {CURRENT}" for view in ("client_metrics", "store_metrics")))

    def test_columns_are_qualified_in_snippets_and_examples(self):
        """A bare `Column` raises 'Table name or alias is required for column' when Genie composes the SQL."""
        snippets = [f["sql"][0] for f in _space()["instructions"]["sql_snippets"]["filters"]]
        for sql in snippets + [s for _, _, s in _all_sql()]:
            self.assertNotRegex(sql, r"(?<![.\w])`[A-Z][^`]*`", sql[:80])

    def test_kpis_come_from_the_metric_views_not_raw_sql(self):
        for kind, question, sql in _all_sql():
            self.assertNotIn("SUM(", sql.replace("COUNT(*)", ""), f"{kind} '{question}': use MEASURE()")
            self.assertNotIn("SELECT *", sql)

    def test_covers_glossary_store_and_client_questions(self):
        samples = " ".join(q["question"][0] for q in _space()["config"]["sample_questions"])
        for text in ("What does Conversion mean", "stores by revenue", "clients by total spent"):
            self.assertIn(text, samples)
        self.assertEqual(len(_space()["benchmarks"]["questions"]), 10)

    def test_knows_the_client_segments(self):
        s = _space()
        questions = [e["question"][0] for e in s["instructions"]["example_question_sqls"]]
        self.assertIn("How many clients are in each segment, and how much do they spend?", questions)
        client = [m for m in s["data_sources"]["metric_views"] if m["identifier"].endswith("client_metrics")][0]
        configs = {c["column_name"]: c for c in client["column_configs"]}
        self.assertTrue(configs["Client Segment"]["enable_entity_matching"])
        self.assertIn("VIC clients means VIC1 and VICSTAR", "".join(s["instructions"]["text_instructions"][0]["content"]))

    def test_knows_the_preferred_store(self):
        s = _space()
        client = [m for m in s["data_sources"]["metric_views"] if m["identifier"].endswith("client_metrics")][0]
        configs = {c["column_name"]: c for c in client["column_configs"]}
        self.assertTrue(configs["Preferred Store Name"]["enable_entity_matching"])
        text = "".join(s["instructions"]["text_instructions"][0]["content"])
        self.assertIn("preferred store", text)
        self.assertIn("not the store where they spent most", text)

    def test_join_specs_on_natural_keys(self):
        for j in _space()["instructions"]["join_specs"]:
            left, right = j["left"]["alias"], j["right"]["alias"]
            key = re.search(r"`\.`(\w+)` = ", j["sql"][0]).group(1)
            self.assertEqual(j["sql"], [f"`{left}`.`{key}` = `{right}`.`{key}`",
                                        "--rt=FROM_RELATIONSHIP_TYPE_MANY_TO_ONE--"])
            self.assertIn(key, ("store_id", "client_id", "product_id"))

    def test_hides_technical_columns_and_matches_business_terms(self):
        configs = {t["identifier"]: {c["column_name"]: c for c in t.get("column_configs", [])}
                   for t in _space()["data_sources"]["tables"] + _space()["data_sources"]["metric_views"]}
        sales = configs["workspace.test02_streaming.current_sales_transactions"]
        for column in ("raw_event", "source_topic", "source_offset", "ingestion_timestamp"):
            self.assertTrue(sales[column].get("exclude"), column)
        store = configs["workspace.test02_metric.store_metrics"]
        self.assertTrue(store["Channel"]["enable_entity_matching"])
        self.assertTrue(configs["workspace.test02_warehouse.dim_store"]["channel"]["enable_entity_matching"])


class FakeClient:
    def __init__(self, spaces):
        self.spaces, self.calls = spaces, []

    def do(self, method, url, query=None, body=None):
        self.calls.append((method, url, body))
        if method == "GET":
            return {"spaces": self.spaces}
        if method == "POST":
            return {"space_id": "new123"}
        return {}


class FakeWorkspace:
    def __init__(self):
        self.made = []

    def mkdirs(self, p):
        self.made.append(p)


class DeployScriptTests(unittest.TestCase):

    def setUp(self):
        sys.path.insert(0, path(*AGENT, "src"))
        import deploy_genie
        self.deploy = deploy_genie

    def test_updates_the_agent_when_it_exists(self):
        agent = _agent()
        client = FakeClient([{"space_id": "abc", "title": agent["title"], "parent_path": "/p"}])
        action, space_id = self.deploy.deploy(client, FakeWorkspace(), agent, "wh1", "/p")
        self.assertEqual((action, space_id), ("updated", "abc"))
        method, url, body = client.calls[-1]
        self.assertEqual((method, url), ("PATCH", "/api/2.0/genie/spaces/abc"))
        self.assertEqual(json.loads(body["serialized_space"]), agent["serialized_space"], "sent as a JSON string")
        self.assertEqual(body["warehouse_id"], "wh1")

    def test_creates_the_agent_and_its_folder_otherwise(self):
        agent, ws = _agent(), FakeWorkspace()
        client = FakeClient([{"space_id": "other", "title": "Another agent"}])
        action, space_id = self.deploy.deploy(client, ws, agent, "wh1", "/Workspace/Users/x/genie")
        self.assertEqual((action, space_id), ("created", "new123"))
        self.assertEqual(ws.made, ["/Workspace/Users/x/genie"])
        method, url, body = client.calls[-1]
        self.assertEqual((method, url, body["parent_path"], body["title"]),
                         ("POST", "/api/2.0/genie/spaces", "/Workspace/Users/x/genie", "Retail KPI Assistant"))


class BundleTests(unittest.TestCase):

    def test_separate_bundle(self):
        yml = read_text(*AGENT, "databricks.yml")
        self.assertIn('name: "retail_kpi_genie_bundle"', yml)
        self.assertEqual(yml.count("host: https://dbc-06fb0002-68c5.cloud.databricks.com"), 2)
        self.assertRegex(read_text("databricks.yml"), r"exclude:\n\s+- apps/\*\*\n\s+- agents/\*\*",
                         "the pipeline bundle doesn't upload agents/")

    def test_job_runs_the_deploy_script_on_demand(self):
        job = read_text(*AGENT, "resources", "kpi_genie.job.yml")
        self.assertIn("python_file: ../src/deploy_genie.py", job)
        self.assertIn("- ${workspace.file_path}/src/kpi_genie.json", job)
        self.assertIn("- ${var.warehouse_id}", job)
        for absent in ("schedule", "trigger", "continuous", "clusters"):
            self.assertNotRegex(job, rf"(?m)^\s+{absent}:", "serverless, on demand only")

    def test_docs_and_readme(self):
        self.assertIn("retail_kpi_genie_bundle", read_text("readme.md"))
        layout = read_text("doc", "development.md")
        for f in ("kpi_genie.json", "deploy_genie.py", "kpi_genie.job.yml", "test_kpi_genie.py"):
            self.assertIn(f, layout)
        doc = read_text("doc", "kpi_genie.md")
        for text in ("**Retail KPI Assistant**", "**current simulation**", "`deploy-kpi-genie-dev`", "10 questions"):
            self.assertIn(text, doc)


if __name__ == "__main__":
    unittest.main()
