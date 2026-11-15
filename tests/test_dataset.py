"""Checks that doc/dataset.md and the store SQL scripts agree. Standard library only."""
import os
import re
import unittest
from collections import Counter
from datetime import datetime, timezone

from helpers import ROOT, path, read_text

try:
    from zoneinfo import ZoneInfo
    ZoneInfo("Europe/Rome")
except Exception:  # no time-zone database on this machine
    ZoneInfo = None

DOC = ("doc", "dataset.md")
POPULATE_SQL = ("src", "sql", "02_populate_dim_store.sql")
MACRO_REGIONS = {"EUROPE", "AMERICAS", "ASIA"}
OPEN_HOUR, CLOSE_HOUR = 10, 20


def _allocation():
    """(country, city_code, city, timezone, count) rows of 02_populate_dim_store.sql."""
    sql = read_text(*POPULATE_SQL)
    rows = re.findall(r"\('(\w\w)', '[^']*', '(\w\w)', '([^']*)', '[^']*', '([^']*)', (\d+)\)", sql)
    return [(c, code, city, tz, int(n)) for c, code, city, tz, n in rows]


def _sql_mapping(text):
    """{country_code: macro_region} from `country_code IN (...) [AND macro_region =|THEN] 'X'` clauses."""
    mapping = {}
    for m in re.finditer(r"country_code\s+(?:IN\s*\(([^)]*)\)|=\s*'(\w\w)')\s*(?:THEN|AND\s+macro_region\s*=)\s*'(\w+)'", text):
        codes = re.findall(r"'(\w\w)'", m.group(1)) if m.group(1) else [m.group(2)]
        for c in codes:
            mapping[c] = m.group(3)
    return mapping


def _doc_mapping():
    section = read_text(*DOC).split("### 2.3", 1)[1].split("###", 1)[0]
    mapping = {}
    for region, codes in re.findall(r"^\| `(\w+)` \| ([A-Z, ]+) \|", section, re.M):
        for c in codes.split(","):
            mapping[c.strip()] = region
    return mapping


class StoreDimensionTests(unittest.TestCase):

    def test_macro_region_column_in_every_store_script(self):
        for f in ("01_create_dim_store.sql", "02_populate_dim_store.sql",
                  "03_validate_dim_store.sql"):
            self.assertIn("macro_region", read_text("src", "sql", f), f"{f} doesn't handle macro_region")

    def test_every_country_has_one_macro_region(self):
        countries = {c for c, *_ in _allocation()}
        populate = _sql_mapping(read_text(*POPULATE_SQL))
        self.assertEqual(set(populate), countries, "02_populate: every country needs a macro region")
        self.assertLessEqual(set(populate.values()), MACRO_REGIONS)

    def test_macro_region_mapping_agrees_everywhere(self):
        populate = _sql_mapping(read_text(*POPULATE_SQL))
        self.assertEqual(_sql_mapping(read_text("src", "sql", "03_validate_dim_store.sql")), populate,
                         "03_validate's INVALID_COUNTRY_MACRO_REGION check differs from 02_populate")
        self.assertEqual(_doc_mapping(), populate, "doc/dataset.md §2.3 differs from 02_populate")

    def test_create_builds_the_warehouse_schema_and_store_table(self):
        sql = read_text("src", "sql", "01_create_dim_store.sql")
        self.assertIn("CREATE SCHEMA IF NOT EXISTS workspace.test02_warehouse", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS workspace.test02_warehouse.dim_store", sql)
        self.assertRegex(sql, r"macro_region STRING NOT NULL")
        self.assertRegex(sql, r"is_flagship BOOLEAN NOT NULL")
        self.assertFalse(os.path.exists(path("src", "sql", "01a_add_macro_region.sql")))

    def test_validation_scripts_name_their_columns_in_the_first_select(self):
        """A UNION takes its column names from its first SELECT; the final SELECT reads them by name."""
        for f in ("03_validate_dim_store.sql", "13_validate_dim_client_product.sql"):
            sql = re.sub(r"--[^\n]*", "", read_text("src", "sql", f))
            first = sql.split("checks AS (", 1)[1].split("UNION ALL", 1)[0]
            for alias in ("AS validation", "AS expected_value", "AS actual_value"):
                self.assertIn(alias, first, f"{f}: first check needs {alias}")

    def test_populate_corrects_existing_rows(self):
        sql = read_text(*POPULATE_SQL)
        for col in ("macro_region", "store_name", "is_flagship"):
            self.assertIn(f"target.{col} <=> source.{col}", sql)
            self.assertIn(f"target.{col} = source.{col}", sql)

    def test_flagships(self):
        """IT-MI-001 and US-NY-001 are the two flagships, with their names, everywhere."""
        names = {"IT-MI-001": "Milan Galleria Vittorio Emanuele", "US-NY-001": "New York Fifth Avenue"}
        populate, validate = read_text(*POPULATE_SQL), read_text("src", "sql", "03_validate_dim_store.sql")
        for store_id, name in names.items():
            self.assertIn(f"WHEN '{store_id}' THEN '{name}'", populate)
            self.assertIn(f"store_id = '{store_id}' AND store_name = '{name}'", validate)
            self.assertIn(f"`{store_id}`", read_text(*DOC))
        self.assertIn("IN ('IT-MI-001', 'US-NY-001') AS is_flagship", populate)
        self.assertIn("store_ids: IT-MI-001, US-NY-001", read_text("apps", "people_stream", "app", "shop_config.yml"))
        self.assertIn(("IT", "MI"), {(c, code) for c, code, *_ in _allocation()})

    def test_dimensions_live_in_the_warehouse_schema(self):
        """Dimensions in test02_warehouse; test02_streaming only for sources and pipeline tables."""
        import glob
        files = glob.glob(path("src", "**", "*.*"), recursive=True) + glob.glob(path("apps", "**", "*.*"), recursive=True)
        for f in files:
            if f.endswith((".py", ".sql", ".yml", ".yaml")) and "14_drop_old_streaming_dimensions" not in f:
                text = open(f, encoding="utf-8").read()
                self.assertNotRegex(text, r"test02_streaming\.dim_", f"{f} still uses a dimension in test02_streaming")
        for f in ("04_create_simulated_event_source.sql", "12_create_simulated_sales_source.sql"):
            self.assertIn("workspace.test02_streaming.simulated_", read_text("src", "sql", f))
        self.assertIn("CREATE SCHEMA IF NOT EXISTS workspace.test02_streaming",
                      read_text("src", "sql", "04_create_simulated_event_source.sql"))
        drop = read_text("src", "sql", "14_drop_old_streaming_dimensions.sql")
        self.assertEqual(re.findall(r"DROP TABLE IF EXISTS (\S+);", drop),
                         [f"workspace.test02_streaming.dim_{t}" for t in ("client", "product", "store")])

    def test_validation_expects_the_generated_totals(self):
        populate = _sql_mapping(read_text(*POPULATE_SQL))
        totals = Counter()
        for c, _, _, _, n in _allocation():
            totals[populate[c]] += n
        validate = read_text("src", "sql", "03_validate_dim_store.sql")
        expected = {r: int(n) for r, n in re.findall(r"\('(EUROPE|AMERICAS|ASIA)', (\d+)\)", validate)}
        self.assertEqual(expected, dict(totals))
        self.assertEqual(dict(totals), {"EUROPE": 100, "AMERICAS": 60, "ASIA": 40})

    def test_doc_distribution_matches_populate(self):
        doc = read_text(*DOC).split("### 2.2", 1)[1].split("###", 1)[0]
        populate = _sql_mapping(read_text(*POPULATE_SQL))
        doc_rows = re.findall(r"^\| (\w+) \| (\w\w) [^|]+\| ([^|(]+) \((\w\w)\) \| ([\w/]+) \| (\d+) \|", doc, re.M)
        expected = [(populate[c], c, city, code, tz, str(n)) for c, code, city, tz, n in _allocation()]
        self.assertEqual([(r, c, city.strip(), code, tz, n) for r, c, city, code, tz, n in doc_rows], expected)
        total = sum(n for *_, n in _allocation())
        self.assertIn(f"**All** | 13 countries, 28 cities | **{total}**", doc)


def _ecom_stores():
    """(country_code, country_name, timezone) of the e-commerce stores in 02_populate_dim_store.sql."""
    sql = read_text(*POPULATE_SQL).split("ecom_stores AS (", 1)[1].split("AS e (", 1)[0]
    return re.findall(r"\('(\w\w)', '([^']*)', '([\w/]+)'\)", sql)


class ChannelTests(unittest.TestCase):
    """Sales channels of dim_store: RETAIL and FLAGSHIP (physical, people counting) and ECOM (online)."""

    def test_one_ecom_store_per_country_in_its_main_time_zone(self):
        ecom = _ecom_stores()
        countries = [c for c, *_ in _allocation()]
        self.assertEqual([c for c, *_ in ecom], list(dict.fromkeys(countries)), "one per country, same order")
        first_zone = {}
        for c, _, _, tz, _ in _allocation():
            first_zone.setdefault(c, tz)
        self.assertEqual({c: tz for c, _, tz in ecom}, first_zone, "the country's first (main) time zone")
        self.assertEqual(len(ecom), 13)
        self.assertIn("CONCAT(country_code, '-EC-001') AS store_id", read_text(*POPULATE_SQL))

    def test_channel_is_derived_the_same_way_everywhere(self):
        populate = read_text(*POPULATE_SQL)
        self.assertIn("""WHEN store_id LIKE '%-EC-001' THEN 'ECOM'
            WHEN is_flagship THEN 'FLAGSHIP'
            ELSE 'RETAIL'
        END AS channel""", populate)
        for text in ("target.channel <=> source.channel", "target.channel = source.channel", "source.channel,"):
            self.assertIn(text, populate)
        self.assertIn("channel STRING", read_text("src", "sql", "01_create_dim_store.sql"))
        migration = read_text("src", "sql", "16_add_store_channel.sql")
        self.assertIn("ALTER TABLE workspace.test02_warehouse.dim_store\nADD COLUMN channel STRING", migration)

    def test_validation_expects_the_channels(self):
        validate = read_text("src", "sql", "03_validate_dim_store.sql")
        physical = sum(n for *_, n in _allocation())
        flagships = 2
        expected = {"RETAIL": physical - flagships, "FLAGSHIP": flagships, "ECOM": len(_ecom_stores())}
        found = {c: int(n) for c, n in re.findall(r"\('(RETAIL|FLAGSHIP|ECOM)', (\d+)\)", validate)}
        self.assertEqual(found, expected)
        self.assertIn(f"{physical + expected['ECOM']} AS expected_value", validate)
        self.assertEqual(validate.count("WHERE channel <> 'ECOM'"), 2, "country and region counts: physical stores")
        for check in ("INVALID_CHANNEL", "COUNTRIES_WITHOUT_ONE_ECOM_STORE"):
            self.assertIn(f"'{check}'", validate)

    def test_clients_are_counted_on_physical_stores_only(self):
        """500 clients per physical store: the ECOM stores mustn't add 6,500 clients."""
        for f in ("09_populate_dim_client.sql", "13_validate_dim_client_product.sql"):
            sql = read_text("src", "sql", f)
            self.assertRegex(sql, r"COUNT\(\*\) \* 500 AS \w+\s+FROM workspace\.test02_warehouse\.dim_store\s+"
                                  r"WHERE channel <> 'ECOM'", f)

    def test_doc_describes_the_channels(self):
        doc = read_text(*DOC)
        for text in ("### 2.6 Sales channels", "| `RETAIL` | 198 |", "| `FLAGSHIP` | 2 |", "| `ECOM` | 13 |",
                     "`<country>-EC-001`", "no people counting"):
            self.assertIn(text, doc)


class PeopleFlowTests(unittest.TestCase):

    def test_volume_parameters_documented(self):
        doc = read_text(*DOC)
        for name in ("N_AVG_PEOPLE_EUROPE", "N_AVG_PEOPLE_AMERICA", "N_AVG_PEOPLE_ASIA"):
            self.assertRegex(doc, rf"\| `{name}` \| [^|]+\| 3000 \|", f"{name} default 3000 not documented")

    def test_opening_hours_documented(self):
        self.assertIn(f"{OPEN_HOUR}:00 to {CLOSE_HOUR}:00 local time", read_text(*DOC))

    @unittest.skipIf(ZoneInfo is None, "no time-zone database (pip install tzdata)")
    def test_people_flow_at_every_utc_hour(self):
        """With stores open 10:00-20:00 local time, some store is open at every UTC hour."""
        zones = {tz for *_, tz, _ in _allocation()}
        for day in ("2026-01-15", "2026-07-15"):  # winter and summer time
            for hour in range(24):
                for minute in (0, 30):
                    t = datetime.fromisoformat(f"{day}T{hour:02d}:{minute:02d}").replace(tzinfo=timezone.utc)
                    open_zones = [z for z in zones if OPEN_HOUR <= t.astimezone(ZoneInfo(z)).hour < CLOSE_HOUR]
                    self.assertTrue(open_zones, f"no store open at {t:%Y-%m-%d %H:%M} UTC")


class AgentsDocTests(unittest.TestCase):

    def test_agents_md_lists_every_doc_page(self):
        agents = read_text("agents.md")
        for f in os.listdir(path("doc")):
            if f.endswith(".md"):
                self.assertIn(f"](doc/{f})", agents, f"doc/{f} isn't listed in agents.md")

    def test_doc_links_resolve(self):
        pages = ["agents.md", "readme.md", "CLAUDE.md"] + [os.path.join("doc", f) for f in os.listdir(path("doc"))]
        for page in pages:
            base = os.path.dirname(path(page))
            for target in re.findall(r"\]\(([^)#:]+)(?:#[^)]*)?\)", read_text(page)):
                self.assertTrue(os.path.exists(os.path.join(base, target)), f"{page}: broken link {target}")

    def test_claude_md_loads_agents_md(self):
        self.assertIn("@agents.md", read_text("CLAUDE.md"))


if __name__ == "__main__":
    unittest.main()
