"""Checks that the bundle, the pipeline code, the setup SQL and the docs agree. Standard library only."""
import ast
import glob
import json
import os
import re
import unittest
from datetime import datetime

from helpers import ROOT, constants, parse, path, pipeline_tables, read_text

CHECK_FILE = "src/pipelines/00_check_tables.py"
PIPELINE_FILES = [CHECK_FILE, "src/pipelines/01_bronze.py", "src/pipelines/02_silver.py"]
PIPELINE_YML = ("resources", "modeling.peoplecounter.pipeline.yml")
INSERT_SQL = ("src", "pipelines", "05_insert_simulated_events.sql")


def _bundle_variable_default(name):
    m = re.search(rf"^  {name}:\n(?:    .*\n)*?    default: (\S+)", read_text("databricks.yml"), re.M)
    return m.group(1) if m else None


def _rejection_codes():
    """The codes in the rejection_reasons list of 02_silver.py: the second argument of each F.when(...)."""
    for node in ast.walk(parse("src/pipelines/02_silver.py")):
        if (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "rejection_reasons"):
            return {ast.literal_eval(call.args[1]) for call in node.value.elts}
    raise AssertionError("rejection_reasons not found in 02_silver.py")


def _store_ids():
    """The store ids 02_populate_dim_store.sql generates: <country>-<city>-<nnn>."""
    sql = read_text("src", "sql", "02_populate_dim_store.sql")
    ids = set()
    for country, city, count in re.findall(r"\('(\w\w)', '[^']*', '(\w\w)', '[^']*', '[^']*', '[^']*', (\d+)\)", sql):
        ids.update(f"{country}-{city}-{n:03d}" for n in range(1, int(count) + 1))
    return ids


def _simulated_events():
    """(offset, raw_event) pairs inserted by 05_insert_simulated_events.sql."""
    sql = read_text(*INSERT_SQL)
    return [(int(o), e) for o, e in re.findall(r"\(\s*(\d+),\s*'(.*?)'\s*\)", sql, re.S)]


def _rejections(raw_event, store_ids):
    """Plain-Python mirror of the rules in 02_silver.py, for the simulated events only."""
    try:
        e = json.loads(raw_event)
    except ValueError:
        return ["INVALID_JSON"]  # the other rules also fire, but INVALID_JSON comes first
    reasons = []
    for field, code in (("event_id", "MISSING_EVENT_ID"), ("store_id", "MISSING_STORE_ID"),
                        ("sensor_id", "MISSING_SENSOR_ID")):
        if not (e.get(field) or "").strip():
            reasons.append(code)
    try:
        datetime.fromisoformat(e.get("event_timestamp") or "")
    except ValueError:
        reasons.append("INVALID_EVENT_TIMESTAMP")
    if (e.get("event_type") or "").strip().upper() not in ("ENTRY", "EXIT"):
        reasons.append("INVALID_EVENT_TYPE")
    if not isinstance(e.get("people_count"), int) or e["people_count"] <= 0:
        reasons.append("INVALID_PEOPLE_COUNT")
    store = (e.get("store_id") or "").strip()
    if store and store not in store_ids:
        reasons.append("UNKNOWN_STORE")
    return reasons


class BundleTests(unittest.TestCase):

    def test_bundle_name_and_targets(self):
        yml = read_text("databricks.yml")
        self.assertIn('name: "retail_people_counter_bundle"', yml)
        for target in ("dev:", "prod:", "mode: development", "mode: production", "default: true"):
            self.assertIn(target, yml)
        self.assertEqual(yml.count("host: https://dbc-06fb0002-68c5.cloud.databricks.com"), 2)

    def test_includes_nested_resources(self):
        yml = read_text("databricks.yml")
        self.assertIn("- resources/*.yml", yml)
        self.assertIn("- resources/*/*.yml", yml)

    def test_resource_variables_are_defined(self):
        yml = read_text("databricks.yml")
        for res in glob.glob(path("resources", "**", "*.yml"), recursive=True):
            for var in set(re.findall(r"\$\{var\.(\w+)\}", read_text(res))):
                self.assertRegex(yml, rf"(?m)^  {var}:", f"{os.path.basename(res)} uses undefined variable {var}")

    def test_pipeline_library_files_exist(self):
        for res in glob.glob(path("resources", "**", "*.yml"), recursive=True):
            for rel in re.findall(r"path:\s*(\S+)", read_text(res)):
                full = os.path.normpath(os.path.join(os.path.dirname(res), rel))
                self.assertTrue(os.path.exists(full), f"{os.path.basename(res)} points to missing {rel}")

    def test_pipeline_libraries_are_the_python_sources(self):
        listed = re.findall(r"path:\s*\.\./(\S+)", read_text(*PIPELINE_YML))
        self.assertEqual(listed, PIPELINE_FILES)

    def test_no_deprecated_pipeline_fields(self):
        """continuous, development, target and trigger are deprecated in the bundle schema."""
        for res in glob.glob(path("resources", "**", "*.yml"), recursive=True):
            for field in ("continuous", "development", "target", "trigger"):
                self.assertNotRegex(read_text(res), rf"(?m)^\s+{field}:",
                                    f"{os.path.basename(res)} uses deprecated field {field}")

    def test_serverless_only(self):
        for res in glob.glob(path("resources", "**", "*.yml"), recursive=True):
            text = read_text(res)
            self.assertNotIn("clusters:", text)
            self.assertNotIn("node_type_id", text)
            if "pipelines:" in text:
                self.assertIn("serverless: true", text)


class PipelineCodeTests(unittest.TestCase):

    def test_timestamp_ntz_tables_enable_the_feature(self):
        for f in PIPELINE_FILES:
            tree = parse(f)
            consts = constants(tree)
            for table, kw in pipeline_tables(tree).items():
                schema = kw.get("schema")
                schema_text = consts.get(schema.id) if isinstance(schema, ast.Name) else (
                    ast.literal_eval(schema) if schema is not None else "")
                if "TIMESTAMP_NTZ" not in (schema_text or "").upper():
                    continue
                props = ast.literal_eval(kw["table_properties"]) if "table_properties" in kw else {}
                self.assertEqual(props.get("delta.feature.timestampNtz"), "supported",
                                 f"{table} has a TIMESTAMP_NTZ column but doesn't enable timestampNtz")

    def test_table_names_use_bundle_catalog_and_schema(self):
        prefix = f"{_bundle_variable_default('catalog')}.{_bundle_variable_default('schema')}."
        for f in PIPELINE_FILES:
            for name, value in constants(parse(f)).items():
                if name.endswith("_TABLE"):
                    self.assertTrue(value.startswith(prefix), f"{f}: {name} = {value} isn't in {prefix}*")

    def test_silver_and_quarantine_select_their_schema_columns(self):
        tree = parse("src/pipelines/02_silver.py")
        consts = constants(tree)
        source = read_text("src/pipelines/02_silver.py")
        for table, schema_name in (("silver_people_counter_events", "SILVER_SCHEMA"),
                                   ("quarantine_people_counter_events", "QUARANTINE_SCHEMA")):
            columns = re.findall(r"^\s{4}(\w+) [A-Z_]+", consts[schema_name], re.M)
            body = source.split(f"def {table}():", 1)[1].split("\n# ====", 1)[0]
            selected = re.findall(r'^\s+"(\w+)",?\s*$', body.split(".select(", 1)[1], re.M)
            self.assertEqual(selected, columns, f"{table} selects columns out of step with {schema_name}")

    def test_check_tables_runs_first(self):
        listed = re.findall(r"path:\s*\.\./(\S+)", read_text(*PIPELINE_YML))
        self.assertEqual(listed[0], CHECK_FILE)
        self.assertRegex(read_text(CHECK_FILE), r"(?m)^check_required_tables\(\)\s*$",
                         "00_check_tables.py must call check_required_tables() at import time")

    def test_every_input_table_is_checked(self):
        """Each table a pipeline file reads but doesn't create is in REQUIRED_TABLES."""
        required = set(constants(parse(CHECK_FILE))["REQUIRED_TABLES"])
        created = set()
        for f in PIPELINE_FILES:
            created.update(pipeline_tables(parse(f)))
        prefix = f"{_bundle_variable_default('catalog')}.{_bundle_variable_default('schema')}."
        for f in PIPELINE_FILES:
            for name, value in constants(parse(f)).items():
                if name.endswith("_TABLE") and value.split(".")[-1] not in created:
                    self.assertIn(value, required, f"{f} reads {value}, which 00_check_tables.py doesn't check")
        for table in required:
            self.assertTrue(table.startswith(prefix), f"REQUIRED_TABLES: {table} isn't in {prefix}*")

    def test_rejection_codes_are_documented(self):
        documented = set(re.findall(r"^\| `([A-Z_]+)` \|", read_text("readme.md"), re.M))
        self.assertEqual(_rejection_codes(), documented)


class SimulatedDataTests(unittest.TestCase):

    def test_store_dimension_has_200_stores(self):
        self.assertEqual(len(_store_ids()), 200)

    def test_simulated_events_insert_is_idempotent(self):
        sql = re.sub(r"--[^\n]*", "", read_text(*INSERT_SQL)).upper()
        self.assertNotRegex(sql, r"\bINSERT\s+INTO\b", "use MERGE, not INSERT INTO, so reruns add nothing")
        self.assertIn("MERGE INTO WORKSPACE.TEST02_STREAMING.SIMULATED_EVENT_SOURCE", sql)
        on_clause = re.search(r"\)\s*AS\s+SOURCE\s+ON\s(.*?)\bWHEN\b", sql, re.S).group(1)
        for col in ("SOURCE_TOPIC", "SOURCE_PARTITION", "SOURCE_OFFSET"):
            self.assertIn(f"TARGET.{col}", on_clause, f"the MERGE key must include {col}")
        self.assertIn("WHEN NOT MATCHED THEN INSERT", sql)
        self.assertNotIn("WHEN MATCHED", sql.replace("WHEN NOT MATCHED", ""),
                         "keep the MERGE insert-only; bronze streams from this table")

    def test_simulated_event_offsets_are_unique(self):
        offsets = [o for o, _ in _simulated_events()]
        self.assertEqual(len(offsets), len(set(offsets)))

    def test_simulated_events_outcome(self):
        stores = _store_ids()
        events = _simulated_events()
        self.assertEqual([o for o, _ in events], list(range(1, 9)))
        outcome = {o: _rejections(e, stores) for o, e in events}
        self.assertEqual({o for o, r in outcome.items() if not r}, {1, 2, 3, 4, 5})
        self.assertEqual(outcome[6], ["INVALID_JSON"])
        self.assertEqual(outcome[7], ["UNKNOWN_STORE"])
        self.assertEqual(outcome[8], ["INVALID_EVENT_TYPE"])


class DocsTests(unittest.TestCase):

    def test_claude_md_loads_readme_and_keeps_mandatory_rules(self):
        text = read_text("CLAUDE.md")
        self.assertIn("@readme.md", text)
        self.assertIn("python -m unittest discover -s tests", text)
        self.assertIn("**Mandatory: never commit or push.**", text)

    def test_readme_lists_every_test_file(self):
        readme = read_text("readme.md")
        for f in os.listdir(path("tests")):
            if f.endswith(".py"):
                self.assertIn(f, readme, f"tests/{f} isn't listed in readme.md")

    def test_readme_lists_every_source_file(self):
        readme = read_text("readme.md")
        for f in glob.glob(path("src", "**", "*.*"), recursive=True) + glob.glob(path("resources", "*.yml")):
            self.assertIn(os.path.basename(f), readme, f"{os.path.relpath(f, ROOT)} isn't in readme.md")


if __name__ == "__main__":
    unittest.main()
