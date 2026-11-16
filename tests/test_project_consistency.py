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
SALES_FILE = "src/pipelines/03_sales.py"
PIPELINE_FILES = [CHECK_FILE, "src/pipelines/01_bronze.py", "src/pipelines/02_silver.py", SALES_FILE]
PIPELINE_YML = ("resources", "modeling.peoplecounter.pipeline.yml")
INSERT_SQL = ("src", "sql", "05_insert_simulated_events.sql")


def _bundle_variable_default(name):
    m = re.search(rf"^  {name}:\n(?:    .*\n)*?    default: (\S+)", read_text("databricks.yml"), re.M)
    return m.group(1) if m else None


def _rejection_codes(file="src/pipelines/02_silver.py", list_name="rejection_reasons"):
    """The codes in a rejection list of a pipeline file: the second argument of each F.when(...)."""
    for node in ast.walk(parse(file)):
        if (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == list_name):
            return {ast.literal_eval(call.args[1]) for call in node.value.elts}
    raise AssertionError(f"{list_name} not found in {file}")


def _sales_rejections(raw_event, store_ids, client_ids, product_categories):
    """Plain-Python mirror of the rules in 03_sales.py (doc/sales.md, "Silver sales")."""
    try:
        t = json.loads(raw_event)
    except ValueError:
        return ["INVALID_JSON"]
    reasons = []
    if not (t.get("transaction_id") or "").strip():
        reasons.append("MISSING_TRANSACTION_ID")
    line, lines = t.get("line_number"), t.get("line_count")
    if not isinstance(line, int) or not isinstance(lines, int) or line < 1 or line > lines:
        reasons.append("INVALID_LINE_NUMBER")
    try:
        datetime.fromisoformat(t.get("transaction_timestamp") or "")
    except ValueError:
        reasons.append("INVALID_TRANSACTION_TIMESTAMP")
    q, price, amount = t.get("quantity"), t.get("unit_price"), t.get("amount")
    if not isinstance(q, int) or q <= 0:
        reasons.append("INVALID_QUANTITY")
    if price is None or price <= 0 or amount is None or abs(amount - (q or 0) * price) > 0.005:
        reasons.append("INVALID_AMOUNT")
    if (t.get("currency") or "").strip().upper() != "EUR":
        reasons.append("INVALID_CURRENCY")
    if (t.get("store_id") or "").strip() not in store_ids:
        reasons.append("UNKNOWN_STORE")
    if (t.get("client_id") or "").strip() not in client_ids:
        reasons.append("UNKNOWN_CLIENT")
    product = (t.get("product_id") or "").strip()
    if product not in product_categories:
        reasons.append("UNKNOWN_PRODUCT")
    elif (t.get("category") or "").strip().upper() != product_categories[product]:
        reasons.append("CATEGORY_MISMATCH")
    return reasons


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
        """continuous, development, target and trigger are deprecated on pipelines in the bundle schema.

        (A job's `continuous:` is fine: that's how the pipeline runs continuously, see the job tests.)
        """
        for res in glob.glob(path("resources", "**", "*.yml"), recursive=True):
            text = read_text(res)
            if not re.search(r"(?m)^  pipelines:", text):
                continue
            for field in ("continuous", "development", "target", "trigger"):
                self.assertNotRegex(text, rf"(?m)^\s+{field}:",
                                    f"{os.path.basename(res)} uses deprecated field {field}")

    def test_continuous_job_runs_the_pipeline(self):
        job = read_text("resources", "modeling.peoplecounter.job.yml")
        self.assertRegex(job, r"(?m)^  jobs:\n    retail_people_counter_continuous:")
        self.assertRegex(job, r"continuous:\n\s+pause_status: PAUSED", "created paused; resumed after the full refresh")
        self.assertIn("pipeline_id: ${resources.pipelines.retail_people_counter_bronze.id}", job)
        self.assertNotRegex(job, r"(?m)^\s+full_refresh:", "a full refresh on every update would wipe the tables")
        self.assertNotIn("clusters", job)

    def test_bronze_skips_the_deletes_of_an_app_start(self):
        """The app empties the source at START; bronze must skip that delete to keep streaming."""
        code = read_text("src/pipelines/01_bronze.py")
        self.assertRegex(code, r'spark\.readStream\s*\.option\("skipChangeCommits", "true"\)\s*\.table\(SOURCE_TABLE\)')

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
        """Streaming tables in `schema`, dimensions in `warehouse_schema`."""
        catalog = _bundle_variable_default("catalog")
        streaming, warehouse = _bundle_variable_default("schema"), _bundle_variable_default("warehouse_schema")
        self.assertEqual((streaming, warehouse), ("test02_streaming", "test02_warehouse"))
        for f in PIPELINE_FILES:
            for name, value in constants(parse(f)).items():
                if name.endswith("_TABLE"):
                    schema = warehouse if value.split(".")[-1].startswith("dim_") else streaming
                    self.assertTrue(value.startswith(f"{catalog}.{schema}."), f"{f}: {name} = {value}")
        self.assertIn(f"REFERENCES {catalog}.{warehouse}.dim_store(store_id)", read_text("src/pipelines/02_silver.py"))
        for dim, key in (("dim_store", "store_id"), ("dim_client", "client_id"), ("dim_product", "product_id")):
            self.assertIn(f"FOREIGN KEY ({key})\n        REFERENCES {catalog}.{warehouse}.{dim}({key})",
                          read_text(SALES_FILE))
        self.assertIn("PRIMARY KEY (transaction_id, line_number)", read_text(SALES_FILE),
                      "a transaction is a basket: one row per line")

    def test_silver_and_quarantine_select_their_schema_columns(self):
        for f, pairs in (("src/pipelines/02_silver.py", (("silver_people_counter_events", "SILVER_SCHEMA"),
                                                         ("quarantine_people_counter_events", "QUARANTINE_SCHEMA"))),
                         (SALES_FILE, (("silver_sales_transactions", "SILVER_SALES_SCHEMA"),
                                       ("quarantine_sales_transactions", "QUARANTINE_SALES_SCHEMA")))):
            consts = constants(parse(f))
            source = read_text(f)
            for table, schema_name in pairs:
                columns = re.findall(r"^\s{4}(\w+) [A-Z_]+", consts[schema_name], re.M)
                body = source.split(f"def {table}():", 1)[1].split("\n# ====", 1)[0]
                selected = re.findall(r'^\s+"(\w+)",?\s*$', body.split(".select(", 1)[1], re.M)
                self.assertEqual(selected, columns, f"{table} selects columns out of step with {schema_name}")

    def test_sales_bronze_skips_the_deletes_of_an_app_start(self):
        code = read_text(SALES_FILE)
        self.assertRegex(code, r'spark\.readStream\s*\.option\("skipChangeCommits", "true"\)\s*'
                               r'\.table\(SALES_SOURCE_TABLE\)')

    def test_silver_sales_has_the_gmt_time(self):
        """The local sale time is kept, and translated to GMT from the store's time zone."""
        code = read_text(SALES_FILE)
        self.assertIn("convert_timezone(store_timezone_id, 'UTC', transaction_timestamp)", code)
        consts = constants(parse(SALES_FILE))
        for schema in ("SILVER_SALES_SCHEMA", "QUARANTINE_SALES_SCHEMA"):
            self.assertRegex(consts[schema], r"transaction_timestamp TIMESTAMP_NTZ")
            self.assertRegex(consts[schema], r"transaction_timestamp_utc TIMESTAMP_NTZ")

    def test_silver_carries_the_simulation_id(self):
        """Both silver tables (and quarantines) have simulation_id; silver is clustered by it for the views."""
        for f, schemas, silver in (("src/pipelines/02_silver.py", ("SILVER_SCHEMA", "QUARANTINE_SCHEMA"),
                                    "silver_people_counter_events"),
                                   (SALES_FILE, ("SILVER_SALES_SCHEMA", "QUARANTINE_SALES_SCHEMA"),
                                    "silver_sales_transactions")):
            tree = parse(f)
            consts = constants(tree)
            for schema in schemas:
                self.assertRegex(consts[schema], r"simulation_id STRING", f"{f}: {schema}")
            self.assertIn('StructField("simulation_id", StringType(), True)', read_text(f))
            self.assertEqual(ast.literal_eval(pipeline_tables(tree)[silver]["cluster_by"]), ["simulation_id"])

    def test_current_simulation_views(self):
        """Plain views on silver; one definition of the current simulation, used by both."""
        sql = re.sub(r"--[^\n]*", "", read_text("src", "sql", "15_create_current_simulation_views.sql"))
        schema = "workspace.test02_streaming"
        self.assertEqual(re.findall(r"CREATE OR REPLACE VIEW (\S+)", sql),
                         [f"{schema}.current_simulation", f"{schema}.current_people_counter_events",
                          f"{schema}.current_sales_transactions"])
        self.assertNotIn("MATERIALIZED", sql.upper(), "a materialized view would lag behind silver")
        self.assertRegex(sql, rf"SELECT MAX\(simulation_id\) AS simulation_id\s+FROM {schema}\.silver_people_counter_events")
        current = f"simulation_id = (SELECT simulation_id FROM {schema}.current_simulation)"
        self.assertEqual(sql.count(current), 2)
        self.assertIn(f"FROM {schema}.silver_people_counter_events e\nWHERE e.{current}", sql)
        self.assertIn(f"FROM {schema}.silver_sales_transactions s\nWHERE s.{current}", sql)

    def test_micro_batches_every_2_seconds(self):
        self.assertRegex(read_text(*PIPELINE_YML), r'configuration:\n(\s+#.*\n)*\s+pipelines\.trigger\.interval: "2 seconds"')

    def test_sales_tables(self):
        self.assertEqual(set(pipeline_tables(parse(SALES_FILE))),
                         {"bronze_sales_transactions", "silver_sales_transactions", "quarantine_sales_transactions"})

    def test_sales_rejection_codes_are_documented(self):
        section = read_text("doc", "sales.md").split("## 10. Silver sales", 1)[1].split("\n## ", 1)[0]
        documented = set(re.findall(r"^\| `([A-Z_]+)` \|", section, re.M))
        self.assertEqual(_rejection_codes(SALES_FILE, "sales_rejection_reasons"), documented)
        self.assertEqual(set(_sales_rejections("{", set(), set(), {})), {"INVALID_JSON"})

    def test_pipelines_folder_holds_only_pipeline_sources(self):
        """Hand-run SQL scripts belong in src/sql/, not next to the pipeline sources."""
        on_disk = sorted(f"src/pipelines/{f}" for f in os.listdir(path("src", "pipelines"))
                         if os.path.isfile(path("src", "pipelines", f)))
        self.assertEqual(on_disk, sorted(PIPELINE_FILES))

    def test_check_tables_runs_first(self):
        listed = re.findall(r"path:\s*\.\./(\S+)", read_text(*PIPELINE_YML))
        self.assertEqual(listed[0], CHECK_FILE)
        self.assertRegex(read_text(CHECK_FILE), r"(?m)^check_required_tables\(\)\s*$",
                         "00_check_tables.py must call check_required_tables() at import time")

    def test_pipeline_code_avoids_blocked_catalog_api(self):
        """Pipelines block spark.catalog methods (not whitelisted), e.g. tableExists."""
        for f in PIPELINE_FILES:
            code = re.sub(r"#[^\n]*", "", read_text(f))
            self.assertNotIn("spark.catalog.", code, f"{f} uses spark.catalog, which pipelines block")

    def test_every_input_table_is_checked(self):
        """Each table a pipeline file reads but doesn't create is in REQUIRED_TABLES."""
        required = set(constants(parse(CHECK_FILE))["REQUIRED_TABLES"])
        created = set()
        for f in PIPELINE_FILES:
            created.update(pipeline_tables(parse(f)))
        catalog = _bundle_variable_default("catalog")
        prefixes = tuple(f"{catalog}.{_bundle_variable_default(v)}." for v in ("schema", "warehouse_schema"))
        for f in PIPELINE_FILES:
            for name, value in constants(parse(f)).items():
                if name.endswith("_TABLE") and value.split(".")[-1] not in created:
                    self.assertIn(value, required, f"{f} reads {value}, which 00_check_tables.py doesn't check")
        for table in required:
            self.assertTrue(table.startswith(prefixes), f"REQUIRED_TABLES: {table} isn't in {prefixes}")

    def test_rejection_codes_are_documented(self):
        documented = set(re.findall(r"^\| `([A-Z_]+)` \|", read_text("readme.md"), re.M))
        self.assertEqual(_rejection_codes(), documented)


class SimulatedDataTests(unittest.TestCase):

    def test_store_dimension_has_200_physical_stores(self):
        """The city allocation: 200 physical stores (RETAIL and FLAGSHIP); the 13 ECOM stores come on top."""
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

    def test_solution_overview_matches_the_project(self):
        """doc/architecture.md is presented to others: its names and claims must be the project's."""
        doc = read_text("doc", "architecture.md")
        for name in ("simulated_event_source", "simulated_sales_source", "simulation_id",
                     "current_people_counter_events", "current_sales_transactions", "dim_store", "dim_client",
                     "dim_product", "Simulation engine", "BI engine", "Data pipeline"):
            self.assertIn(name, doc)
        # Three separate bundles.
        names = [re.search(r'name: "(\w+)"', read_text(*p, "databricks.yml")).group(1)
                 for p in ((), ("apps", "people_stream"), ("apps", "sales_dashboard"))]
        self.assertEqual(len(set(names)), 3)
        self.assertIn("Three separate bundles", doc)
        # The dashboard may only read the views and two dimensions; the simulator may only write the sources.
        dash = read_text("apps", "sales_dashboard", "resources", "sales_dashboard.app.yml")
        self.assertNotIn("MODIFY", dash)
        self.assertNotIn("silver_", re.sub(r"#[^\n]*", "", dash), "the dashboard has no access to the silver tables")
        sim_app = read_text("apps", "people_stream", "resources", "people_stream.app.yml")
        modify = re.findall(r"\.(\w+)\s*\n\s*securable_type: TABLE\s*\n\s*permission: MODIFY", sim_app)
        self.assertEqual(sorted(modify), ["simulated_event_source", "simulated_sales_source"])
        # Rule counts quoted in the overview.
        self.assertEqual((len(_rejection_codes()), len(_rejection_codes(SALES_FILE, "sales_rejection_reasons"))),
                         (8, 11))
        self.assertIn("8 rules for events, 11 for sales", doc)
        for figure in ("**200 stores**", "100,000", "About 1,097 EUR", "Every 5 seconds"):
            self.assertIn(figure, doc)

    def test_kpi_page_records_the_metric_view_decision(self):
        """doc/kpi_metrics.md feeds the executive summary: the decision, the comparison and the schema."""
        doc = read_text("doc", "kpi_metrics.md")
        for text in ("## 1. The decision: metric views", "| | **Metric views** (chosen) | **KPI table refreshed after every silver update** |",
                     "**Freshness**", "**Cost**", "**Moving parts**", "**One version of the truth**", "**Flexibility**",
                     "## 3. Feasibility: checked on the workspace", "**identical to the cent**",
                     "**`test02_metric`**", "**Total spent**", "**Revenue**"):
            self.assertIn(text, doc)
        sql = re.sub(r"--[^\n]*", "", read_text("src", "sql", "17_create_metric_schema.sql"))
        self.assertEqual(re.findall(r"CREATE SCHEMA IF NOT EXISTS (\S+)", sql), ["workspace.test02_metric"])
        self.assertNotIn("CREATE TABLE", sql.upper(), "the metric schema holds definitions only")
        self.assertIn("`test02_metric`", read_text("doc", "warehouse.md"))

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
