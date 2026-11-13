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

    def test_create_adds_macro_region_only_when_missing(self):
        """01 is rerunnable: the ALTER runs only if information_schema lacks the column."""
        sql = read_text("src", "sql", "01_create_dim_store.sql")
        self.assertRegex(sql, r"(?s)IF \(\s*SELECT COUNT\(\*\)\s*FROM workspace\.information_schema\.columns"
                              r".*column_name = 'macro_region'\s*\) = 0 THEN\s*ALTER TABLE")
        self.assertNotIn("IF NOT EXISTS macro_region", sql)  # not supported by Databricks SQL
        self.assertFalse(os.path.exists(path("src", "sql", "01a_add_macro_region.sql")))

    def test_populate_fills_macro_region_on_existing_rows(self):
        sql = read_text(*POPULATE_SQL)
        self.assertRegex(sql, r"WHEN MATCHED AND NOT \(target\.macro_region <=> source\.macro_region\) THEN UPDATE")

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
