"""Tests of the sales simulator, the client and product dimensions, and doc/sales.md, client.md, product.md.

Standard library only.
"""
import json
import re
import unittest
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from helpers import read_text
from test_people_stream import APP, SKIP_REASON, _FastClock, _run, _stores, sim

if sim is not None:
    import sales
    import shop_config
    import warehouse

CATEGORY_CODES = {"SHOES": "SH", "BAGS": "BG", "READY_TO_WEAR": "RW", "ACCESSORIES": "AC", "TRAVEL": "TR",
                  "SUNGLASSES": "SG"}
SQL = ("src", "sql")


def _product_rows():
    """(category, code, label, base, step) of 11_populate_dim_product.sql."""
    sql = read_text(*SQL, "11_populate_dim_product.sql")
    return [(c, code, label, int(b), int(s))
            for c, code, label, b, s in re.findall(r"\('(\w+)', '(\w\w)', '([^']+)', (\d+), (\d+)\)", sql)]


def _products():
    return [sales.Product(f"{code}-{n:04d}", c, float(b + n * s))
            for c, code, _, b, s in _product_rows() for n in range(1, 21)]


def _clients():
    """The clients 09_populate_dim_client.sql generates: 250 per store of each country."""
    per_country = Counter(s.store_id[:2] for s in _stores())
    return [(f"CL-{cc}-{n:07d}", cc) for cc, stores in per_country.items() for n in range(1, stores * 250 + 1)]


def _catalog():
    return sales.Catalog(_products(), _clients())


def _store_country():
    return {s.store_id: s.store_id[:2] for s in _stores()}


def _people_rows(days=1, n_avg=3000, seed=4):
    rows, _ = _run(sim.Generator(_stores(), run_id="peop1234", seed=seed), days=days,
                   n_avg={r: n_avg for r in sim.REGIONS})
    return rows


def _probs(value=None):
    return {r: {c: (value if value is not None else sim.PURCHASE_PROB_DEFAULTS[r][c]) for c in sim.CATEGORIES}
            for r in sim.REGIONS}


class DimensionScriptTests(unittest.TestCase):

    def test_client_script_generates_250_per_store_per_country(self):
        sql = read_text(*SQL, "09_populate_dim_client.sql")
        self.assertIn("COUNT(*) * 250 AS client_count", sql)
        self.assertIn("CONCAT('CL-', country_code, '-', LPAD(CAST(client_number AS STRING), 7, '0'))", sql)
        self.assertIn("WHEN NOT MATCHED THEN INSERT", sql)
        self.assertNotIn("WHEN MATCHED THEN", sql)

    def test_client_doc_counts_match_the_stores(self):
        doc = read_text("doc", "client.md")
        stores = Counter(s.store_id[:2] for s in _stores())
        rows = re.findall(r"^\| (\w+) \| (\w\w) \| (\d+) \| ([\d,]+) \|", doc, re.M)
        self.assertEqual({cc: (int(n), int(c.replace(",", ""))) for _, cc, n, c in rows},
                         {cc: (n, n * 250) for cc, n in stores.items()})
        self.assertIn("**50,000** (EUROPE 25,000, AMERICAS 15,000, ASIA 10,000)", doc)
        self.assertIn("50000 AS expected_value", read_text(*SQL, "13_validate_dim_client_product.sql"))

    def test_products_20_per_category_with_documented_prices(self):
        rows = _product_rows()
        self.assertEqual([r[0] for r in rows], list(CATEGORY_CODES))
        self.assertEqual({c: code for c, code, *_ in rows}, CATEGORY_CODES)
        self.assertIn("SEQUENCE(1, 20)", read_text(*SQL, "11_populate_dim_product.sql"))
        doc = read_text("doc", "product.md")
        for c, code, label, base, step in rows:
            low, high = base + step, base + 20 * step
            self.assertRegex(doc, rf"\| `{c}` \| {code} \| {label} \| 20 \| {low:,} – {high:,}, step {step} \|")

    def test_categories_agree_everywhere(self):
        expected = list(CATEGORY_CODES)
        self.assertEqual(list(shop_config.CATEGORIES) if sim else expected, expected)
        validate = read_text(*SQL, "13_validate_dim_client_product.sql")
        self.assertEqual(re.findall(r"\('(\w+)'\)", validate), expected)
        self.assertIn("^(SH|BG|RW|AC|TR|SG)-[0-9]{4}$", validate)
        self.assertEqual(re.findall(r"^\| `(\w+)` \| \d+% \|", read_text("doc", "sales.md"), re.M), expected)

    def test_sales_source_has_the_people_source_envelope(self):
        def columns(f):
            return re.findall(r"^\s{4}(\w+) [A-Z]+", read_text(*SQL, f), re.M)
        self.assertEqual(columns("12_create_simulated_sales_source.sql"),
                         columns("04_create_simulated_event_source.sql"))

    def test_dimensions_use_natural_primary_keys(self):
        for f, key in (("08_create_dim_client.sql", "client_id"), ("10_create_dim_product.sql", "product_id")):
            sql = read_text(*SQL, f)
            self.assertRegex(sql, rf"PRIMARY KEY \({key}\)")
            self.assertNotRegex(sql, r"GENERATED|IDENTITY|_sk\b", f"{f}: no surrogate keys")


@unittest.skipIf(sim is None, SKIP_REASON)
class SalesGeneratorTests(unittest.TestCase):

    def setUp(self):
        self.people = _people_rows()
        self.exits = {}
        for row in self.people:
            e = json.loads(row["raw_event"])
            if e["event_type"] == "EXIT":
                self.exits[e["event_id"]] = (row, e)

    def _sales(self, probs, seed=1, offsets=None):
        gen = sales.SalesGenerator(_catalog(), _store_country(), offsets, run_id="sale1234", seed=seed)
        return gen.sales_for(self.people, probs)

    def test_buyers_per_category_match_purchase_prob(self):
        rows = self._sales(_probs())
        people_out = sum(e["people_count"] for _, e in self.exits.values())
        by_category = Counter(json.loads(r["raw_event"])["category"] for r in rows)
        for c in sim.CATEGORIES:
            expected = people_out * sim.PURCHASE_PROB_DEFAULTS["EUROPE"][c] / 100
            self.assertAlmostEqual(by_category[c] / expected, 1, delta=0.03, msg=c)

    def test_zero_and_full_probability(self):
        self.assertEqual(self._sales(_probs(0)), [])
        probs = _probs(0)
        for r in sim.REGIONS:
            probs[r]["BAGS"] = 100
        per_exit = Counter(json.loads(r["raw_event"])["exit_event_id"] for r in self._sales(probs))
        self.assertEqual(dict(per_exit), {eid: e["people_count"] for eid, (_, e) in self.exits.items()})

    def test_each_transaction_follows_its_exit(self):
        products = {p.product_id: p for p in _products()}
        clients = dict(_clients())
        for row in self._sales(_probs()):
            tx = json.loads(row["raw_event"])
            exit_row, exit_event = self.exits[tx["exit_event_id"]]  # only EXITs trigger sales
            self.assertEqual(tx["store_id"], exit_event["store_id"])
            self.assertEqual(tx["transaction_timestamp"], exit_event["event_timestamp"])
            self.assertEqual(clients[tx["client_id"]], tx["store_id"][:2], "client of the store's country")
            product = products[tx["product_id"]]
            self.assertEqual(product.category, tx["category"])
            self.assertEqual((tx["quantity"], tx["unit_price"], tx["amount"], tx["currency"]),
                             (1, product.list_price, product.list_price, "EUR"))
            self.assertEqual(row["source_partition"], exit_row["source_partition"])
            self.assertEqual(row["source_timestamp"], exit_row["source_timestamp"])
            self.assertEqual(row["source_topic"], "retail-sales-app")

    def test_ids_and_offsets(self):
        rows = self._sales(_probs(), offsets={0: 50, 1: 1, 2: 9})
        ids = [json.loads(r["raw_event"])["transaction_id"] for r in rows]
        self.assertEqual(len(ids), len(set(ids)))
        by_partition = defaultdict(list)
        for row, tx_id in zip(rows, ids):
            self.assertEqual(tx_id, f"tx-sale1234-{row['source_partition']}-{row['source_offset']:010d}")
            by_partition[row["source_partition"]].append(row["source_offset"])
        for p, first in {0: 50, 1: 1, 2: 9}.items():
            self.assertEqual(by_partition[p], list(range(first, first + len(by_partition[p]))))
        self.assertEqual(sales.PARTITION, sim.PARTITION)

    def test_missing_dimension_data_is_reported(self):
        with self.assertRaises(ValueError):
            sales.Catalog([p for p in _products() if p.category != "TRAVEL"], _clients())
        with self.assertRaises(ValueError):
            sales.Catalog(_products(), [])


@unittest.skipIf(sim is None, SKIP_REASON)
class SimulationWithSalesTests(unittest.TestCase):

    def test_sales_written_after_people_in_every_batch(self):
        log, people, sold = [], [], []

        def write(rows):
            log.append("people")
            people.extend(rows)

        def write_sales(rows):
            log.append("sales")
            sold.extend(rows)

        s = sim.Simulation(lambda: _stores(), lambda: {}, write, tick_seconds=0.001, clock=_FastClock(7),
                           now=lambda: datetime(2026, 11, 13, 21, 0, tzinfo=timezone.utc),
                           load_catalog=_catalog, load_sales_offsets=lambda: {}, write_sales=write_sales)
        s.start()
        s._thread.join(timeout=30)
        snap = s.snapshot()
        self.assertEqual(snap["state"], "FINISHED")
        self.assertTrue(sold)
        for i, step in enumerate(log):
            if step == "sales":
                self.assertEqual(log[i - 1], "people")
        exit_ids = {json.loads(r["raw_event"])["event_id"] for r in people
                    if json.loads(r["raw_event"])["event_type"] == "EXIT"}
        self.assertTrue({json.loads(r["raw_event"])["exit_event_id"] for r in sold} <= exit_ids)
        self.assertEqual(sum(snap["sales"][r]["transactions"] for r in sim.REGIONS), len(sold))
        self.assertEqual(snap["sales_rows_written"], len(sold))
        amount = sum(json.loads(r["raw_event"])["amount"] for r in sold)
        self.assertAlmostEqual(sum(snap["sales"][r]["amount"] for r in sim.REGIONS), amount, places=2)

    def test_no_catalog_means_no_sales(self):
        s = sim.Simulation(lambda: _stores()[:5], lambda: {}, lambda rows: None, tick_seconds=0.001,
                           clock=_FastClock(7), now=lambda: datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc))
        s.start()
        s._thread.join(timeout=10)
        self.assertEqual(s.snapshot()["sales_rows_written"], 0)

    def test_probability_sliders_set_and_clamp(self):
        s = sim.Simulation(lambda: [], lambda: {}, lambda rows: None)
        s.set_purchase_prob("ASIA", "BAGS", 37.6)
        s.set_purchase_prob("EUROPE", "SHOES", 140)
        snap = s.snapshot()["purchase_prob"]
        self.assertEqual((snap["ASIA"]["BAGS"], snap["EUROPE"]["SHOES"], snap["AMERICAS"]["SHOES"]), (38, 100, 5))

    def test_defaults_come_from_shop_config(self):
        self.assertEqual(sim.PURCHASE_PROB_DEFAULTS,
                         {r: {"SHOES": 5, "BAGS": 2, "READY_TO_WEAR": 6, "ACCESSORIES": 3, "TRAVEL": 2,
                              "SUNGLASSES": 2} for r in sim.REGIONS})
        self.assertEqual((sim.PROB_MIN, sim.PROB_MAX, sim.PROB_STEP), (0, 100, 1))


@unittest.skipIf(sim is None, SKIP_REASON)
class SalesWarehouseTests(unittest.TestCase):

    def test_sales_written_in_chunks_of_insert_only_merges(self):
        wh, statements = warehouse.Warehouse(), []
        wh._execute = lambda sql, fetch=False: statements.append(sql)
        rows = [{"raw_event": "{}", "source_topic": sales.SALES_TOPIC, "source_partition": 0, "source_offset": i,
                 "source_timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc)} for i in range(2500)]
        wh.write_sales(rows)
        self.assertEqual(len(statements), 3)
        for sql in statements:
            self.assertTrue(sql.startswith("MERGE INTO workspace.test02_streaming.simulated_sales_source"))
            self.assertNotIn("WHEN MATCHED", sql.replace("WHEN NOT MATCHED", ""))

    def test_sales_offsets_use_the_sales_topic(self):
        wh, statements = warehouse.Warehouse(), []
        wh._execute = lambda sql, fetch=False: statements.append(sql) or [(0, 41)]
        self.assertEqual(wh.load_sales_offsets(), {0: 42, 1: 1, 2: 1})
        self.assertIn("simulated_sales_source WHERE source_topic = 'retail-sales-app'", statements[0])


class SalesAppAndDocTests(unittest.TestCase):

    def test_app_has_six_probability_sliders_per_region(self):
        app = read_text(*APP, "app", "app.py")
        self.assertIn("html.Div([probability_slider(region, c, probs[c]) for c in sim.CATEGORIES])", app)
        self.assertIn("dbc.Row([equalizer(r, n_avg[r], probs[r]) for r in sim.REGIONS])", app)
        self.assertIn('id={"type": "prob", "region": region, "category": category}', app)
        self.assertIn('Output({"type": "prob", "region": ALL, "category": ALL}, "value")', app)  # reset
        self.assertIn('id="sales-stats"', app)

    def test_app_settings_name_the_sales_tables(self):
        app_yaml = read_text(*APP, "app", "app.yaml")
        for var, table in (("CLIENT_TABLE", "dim_client"), ("PRODUCT_TABLE", "dim_product"),
                           ("SALES_TABLE", "simulated_sales_source")):
            self.assertRegex(app_yaml, rf"name: {var}\n\s+value: workspace\.test02_streaming\.{table}")

    def test_sales_doc_matches_the_code(self):
        doc = read_text("doc", "sales.md")
        for text in ("`retail-sales-app`", "tx-<run id>-<partition>-<offset, 10 digits>", "chunks of at most 1,000",
                     "`store_id` → `dim_store`, `client_id` → `dim_client`, `product_id` → `dim_product`"):
            self.assertIn(text, doc)
        if sim is not None:
            self.assertEqual(sales.SALES_TOPIC, "retail-sales-app")
            self.assertEqual(warehouse.CHUNK_ROWS, 1000)


if __name__ == "__main__":
    unittest.main()
