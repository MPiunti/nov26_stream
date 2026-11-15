"""Tests of the sales simulator, the client and product dimensions, and doc/sales.md, client.md, product.md.

Standard library only.
"""
import json
import re
import unittest
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from helpers import read_text
from test_people_stream import APP, HALF_HOUR, MACRO, SKIP_REASON, _FastClock, _run, _stores, sim

if sim is not None:
    import sales
    import shop_config
    import sql_warehouse as warehouse

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
    """The clients 09_populate_dim_client.sql generates: 500 per store of each country."""
    per_country = Counter(s.store_id[:2] for s in _stores())
    return [(f"CL-{cc}-{n:07d}", cc) for cc, stores in per_country.items() for n in range(1, stores * 500 + 1)]


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

    def test_client_script_generates_500_per_store_per_country(self):
        sql = read_text(*SQL, "09_populate_dim_client.sql")
        self.assertIn("COUNT(*) * 500 AS client_count", sql)
        self.assertEqual(len(_clients()), 100000)
        self.assertEqual(len({c for c, _ in _clients()}), 100000, "distinct clients")
        self.assertIn("CONCAT('CL-', country_code, '-', LPAD(CAST(client_number AS STRING), 7, '0'))", sql)
        self.assertIn("WHEN NOT MATCHED THEN INSERT", sql)
        self.assertNotIn("WHEN MATCHED THEN", sql)

    def test_client_doc_counts_match_the_stores(self):
        doc = read_text("doc", "client.md")
        stores = Counter(s.store_id[:2] for s in _stores())
        rows = re.findall(r"^\| (\w+) \| (\w\w) \| (\d+) \| ([\d,]+) \|", doc, re.M)
        self.assertEqual({cc: (int(n), int(c.replace(",", ""))) for _, cc, n, c in rows},
                         {cc: (n, n * 500) for cc, n in stores.items()})
        self.assertIn("**100,000** (EUROPE 50,000, AMERICAS 30,000, ASIA 20,000)", doc)
        validate = read_text(*SQL, "13_validate_dim_client_product.sql")
        self.assertIn("100000 AS expected_value", validate)
        self.assertIn("COUNT(*) * 500 AS expected_count", validate)

    def test_products_20_per_category_with_documented_prices(self):
        rows = _product_rows()
        self.assertEqual([r[0] for r in rows], list(CATEGORY_CODES))
        self.assertEqual({c: code for c, code, *_ in rows}, CATEGORY_CODES)
        self.assertIn("SEQUENCE(1, 20)", read_text(*SQL, "11_populate_dim_product.sql"))
        doc = read_text("doc", "product.md")
        for c, code, label, base, step in rows:
            low, high = base + step, base + 20 * step
            self.assertRegex(doc, rf"\| `{c}` \| {code} \| {label} \| 20 \| {low:,} – {high:,}, step {step} \|")

    def test_average_transaction_is_about_1000_euro(self):
        """Luxury price points: one item per transaction, so the average transaction is the average item price,
        weighted by how often each category is bought (PURCHASE_PROB). doc/sales.md, "Purchase model"."""
        probs = {"SHOES": 5, "BAGS": 2, "READY_TO_WEAR": 6, "ACCESSORIES": 3, "TRAVEL": 2, "SUNGLASSES": 2}
        if sim is not None:
            self.assertEqual(sim.PURCHASE_PROB_DEFAULTS["EUROPE"], probs)
        mean = {c: b + 10.5 * s for c, _, _, b, s in _product_rows()}  # n = 1..20
        average = sum(probs[c] * mean[c] for c in probs) / sum(probs.values())
        self.assertAlmostEqual(average, 1012.225, places=3)
        self.assertIn("≈ 1,012 EUR", read_text("doc", "sales.md"))
        self.assertGreaterEqual(min(b + s for *_, b, s in _product_rows()), 200, "luxury: no item under 200 EUR")

    def test_product_load_reprices_existing_products(self):
        sql = read_text(*SQL, "11_populate_dim_product.sql")
        self.assertIn("WHEN MATCHED AND NOT (target.list_price <=> source.list_price) THEN UPDATE SET", sql)
        self.assertIn("'EUR'", sql)

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

    def test_every_simulated_transaction_passes_the_silver_sales_rules(self):
        from test_project_consistency import _sales_rejections
        stores = {s.store_id for s in _stores()}
        clients = {c for c, _ in _clients()}
        products = {p.product_id: p.category for p in _products()}
        rows = self._sales(_probs())
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(_sales_rejections(row["raw_event"], stores, clients, products), [], row["raw_event"])

    def _ecom_run(self, days=2, seed=7):
        """People stream and every sale, store and e-commerce, of `days` simulated days for all stores."""
        from test_dataset import _ecom_stores
        stores = _stores()
        ecom = [sim.Store(f"{c}-EC-001", MACRO[c], tz, "ECOM") for c, _, tz in _ecom_stores()]
        countries = {s.store_id: s.store_id[:2] for s in stores + ecom}
        seller = sales.SalesGenerator(_catalog(), countries, run_id="ecom1234", seed=seed,
                                      ecom_stores=ecom, store_traffic=sim.store_traffic(stores),
                                      ecom_share=sim.CONFIG.ecom_share, ecom_price_pct=sim.CONFIG.ecom_price_pct)
        gen = sim.Generator(stores, run_id="ecom1234", seed=seed)
        n_avg = {r: 3000 for r in sim.REGIONS}
        people, store_sales, ecom_sales = [], [], []
        t = datetime(2026, 11, 13, tzinfo=timezone.utc)
        for _ in range(int(days * 48)):
            rows = gen.tick(t, t + HALF_HOUR, n_avg)
            people += rows
            store_sales += seller.sales_for(rows, _probs())
            ecom_sales += seller.ecom_sales(t, t + HALF_HOUR, n_avg, _probs())
            t += HALF_HOUR
        return people, store_sales, ecom_sales

    def test_ecom_is_10_percent_of_sales_value_15_in_us_and_china(self):
        _, store_sales, ecom_sales = self._ecom_run()
        value = defaultdict(lambda: [0.0, 0.0])  # country: [stores, ecom]
        for i, rows in ((0, store_sales), (1, ecom_sales)):
            for row in rows:
                tx = json.loads(row["raw_event"])
                value[tx["store_id"][:2]][i] += tx["amount"]
        share = {c: e / (s + e) * 100 for c, (s, e) in value.items()}
        high = [c for c in share if c in ("US", "CN")]
        for country, pct in share.items():
            target = 15 if country in high else 10
            self.assertAlmostEqual(pct, target, delta=2.5, msg=f"{country}: {pct:.1f}%")
        group = lambda cs: sum(value[c][1] for c in cs) / sum(sum(value[c]) for c in cs) * 100
        self.assertAlmostEqual(group(high), 15, delta=1)
        self.assertAlmostEqual(group([c for c in share if c not in high]), 10, delta=1)

    def test_ecom_transactions_are_10_percent_cheaper_and_online(self):
        people, store_sales, ecom_sales = self._ecom_run(days=1)
        products = {p.product_id: p for p in _products()}
        avg = lambda rows: sum(json.loads(r["raw_event"])["amount"] for r in rows) / len(rows)
        self.assertAlmostEqual(avg(ecom_sales) / avg(store_sales), 0.90, delta=0.03)
        exit_ids = {json.loads(r["raw_event"])["event_id"] for r in people}
        clients = dict(_clients())
        for row in ecom_sales:
            tx = json.loads(row["raw_event"])
            self.assertTrue(tx["store_id"].endswith("-EC-001"))
            self.assertIsNone(tx["exit_event_id"], "online: no visit, no EXIT event")
            self.assertEqual(tx["unit_price"], round(products[tx["product_id"]].list_price * 0.9, 2))
            self.assertEqual(tx["amount"], tx["unit_price"])
            self.assertEqual(clients[tx["client_id"]], tx["store_id"][:2], "a client of the store's country")
        self.assertFalse(any(json.loads(r["raw_event"])["store_id"].endswith("-EC-001") for r in people),
                         "e-commerce stores never produce people events")
        self.assertTrue(all(json.loads(r["raw_event"])["exit_event_id"] in exit_ids for r in store_sales))

    def test_ecom_sales_follow_the_online_day_curve(self):
        """More online orders in the local evening than at night; some at every hour (24-hour shop)."""
        from zoneinfo import ZoneInfo
        _, _, ecom_sales = self._ecom_run(days=2)
        by_hour = Counter()
        for row in ecom_sales:
            tx = json.loads(row["raw_event"])
            if tx["store_id"] == "IT-EC-001":
                by_hour[int(tx["transaction_timestamp"][11:13])] += 1
        self.assertGreater(by_hour[20] + by_hour[21], 4 * (by_hour[3] + by_hour[4]))
        self.assertAlmostEqual(sum(sales.ECOM_HOURLY) / 24, 1.0)
        self.assertEqual(len(sales.ECOM_HOURLY), 24)

    def test_ecom_sales_pass_the_silver_sales_rules(self):
        from test_dataset import _ecom_stores
        from test_project_consistency import _sales_rejections
        stores = {s.store_id for s in _stores()} | {f"{c}-EC-001" for c, *_ in _ecom_stores()}
        clients = {c for c, _ in _clients()}
        products = {p.product_id: p.category for p in _products()}
        _, _, ecom_sales = self._ecom_run(days=0.5)
        self.assertTrue(ecom_sales)
        for row in ecom_sales:
            self.assertEqual(_sales_rejections(row["raw_event"], stores, clients, products), [], row["raw_event"])

    def test_ecom_factor(self):
        """ECOM value = share of the total, so share / (100 - share) of the stores' value, at 90% prices."""
        self.assertAlmostEqual(sales.ecom_factor(10, 100), 1 / 9)
        self.assertAlmostEqual(sales.ecom_factor(15, 90), 15 / 85 / 0.9)
        self.assertEqual((sim.CONFIG.ecom_share("US"), sim.CONFIG.ecom_share("CN"), sim.CONFIG.ecom_share("IT")),
                         (15, 15, 10))
        self.assertEqual(sim.CONFIG.ecom_price_pct, 90)

    def test_only_physical_stores_count_people(self):
        self.assertFalse(sim.Store("IT-EC-001", "EUROPE", "Europe/Rome", "ECOM").counts_people)
        self.assertTrue(sim.Store("IT-MI-001", "EUROPE", "Europe/Rome", "FLAGSHIP").counts_people)
        code = read_text(*APP, "app", "simulator.py")
        self.assertIn("stores = [s for s in all_stores if s.counts_people]", code)
        self.assertIn("generator = Generator(stores, self._load_offsets())", code)
        self.assertIn("SELECT store_id, macro_region, timezone_id, channel FROM", read_text(*APP, "app", "sql_warehouse.py"))

    def test_70_percent_local_clients_and_inverse_at_flagships(self):
        gen = sales.SalesGenerator(_catalog(), _store_country(), run_id="mix12345", seed=5,
                                   local_share=sim.CONFIG.local_share, flagship_ids=sim.FLAGSHIP_IDS,
                                   flagship_local_share=sim.CONFIG.flagship_local_share)
        probs = _probs(20)
        rows = []
        for _ in range(3):  # the people rows of one day, sold three times over for a large sample
            rows += gen.sales_for(self.people, probs)
        clients = dict(_clients())
        local, total = Counter(), Counter()
        for row in rows:
            tx = json.loads(row["raw_event"])
            kind = "flagship" if tx["store_id"] in sim.FLAGSHIP_IDS else "other"
            total[kind] += 1
            local[kind] += clients[tx["client_id"]] == tx["store_id"][:2]
        self.assertEqual((sim.CONFIG.local_share, sim.CONFIG.flagship_local_share), (70, 30))
        self.assertAlmostEqual(local["other"] / total["other"], 0.70, delta=0.01)
        self.assertAlmostEqual(local["flagship"] / total["flagship"], 0.30, delta=0.04)
        visitor_countries = {clients[json.loads(r["raw_event"])["client_id"]] for r in rows}
        self.assertEqual(len(visitor_countries), 13, "visitors come from every country")

    def test_ids_and_offsets(self):
        rows = self._sales(_probs(), offsets={0: 50, 1: 1, 2: 9})
        txs = [json.loads(r["raw_event"]) for r in rows]
        keys = [(t["transaction_id"], t["line_number"]) for t in txs]
        self.assertEqual(len(keys), len(set(keys)), "(transaction_id, line_number) is unique")
        ids = list(dict.fromkeys(t["transaction_id"] for t in txs))
        self.assertEqual(ids, [f"TX-sale1234-{n:010d}" for n in range(1, len(ids) + 1)], "consecutive, in order")
        by_partition = defaultdict(list)
        for row in rows:
            by_partition[row["source_partition"]].append(row["source_offset"])
        for p, first in {0: 50, 1: 1, 2: 9}.items():
            self.assertEqual(by_partition[p], list(range(first, first + len(by_partition[p]))))
        self.assertEqual(sales.PARTITION, sim.PARTITION)

    def test_one_transaction_per_buyer_with_one_line_per_item(self):
        """Everything one buyer buys in a visit is one transaction: same id, store, client, exit and time."""
        rows = self._sales(_probs(20), seed=3)  # 20% per category: many baskets with several items
        baskets = defaultdict(list)
        for row in rows:
            tx = json.loads(row["raw_event"])
            baskets[tx["transaction_id"]].append(tx)
        multi = 0
        for tx_id, lines in baskets.items():
            self.assertEqual([t["line_number"] for t in lines], list(range(1, len(lines) + 1)), tx_id)
            self.assertTrue(all(t["line_count"] == len(lines) for t in lines))
            for field in ("store_id", "client_id", "exit_event_id", "transaction_timestamp", "simulation_id"):
                self.assertEqual(len({t[field] for t in lines}), 1, f"{tx_id}: {field}")
            categories = [t["category"] for t in lines]
            self.assertEqual(len(categories), len(set(categories)), "at most one item per category")
            self.assertEqual(categories, [c for c in sim.CATEGORIES if c in categories], "lines in category order")
            multi += len(lines) > 1
        self.assertGreater(multi, len(baskets) / 4, "with 20% per category many baskets hold several items")

    def test_items_per_basket(self):
        """Items stay as PURCHASE_PROB says; the baskets hold about 1.08 items with the default probabilities."""
        probs = sim.PURCHASE_PROB_DEFAULTS["EUROPE"]
        self.assertAlmostEqual(sales.items_per_basket(probs), 0.20 / (1 - 0.95 * 0.98 * 0.94 * 0.97 * 0.98 * 0.98))
        self.assertAlmostEqual(sales.items_per_basket(probs), 1.083, places=3)
        self.assertEqual(sales.items_per_basket({c: 0 for c in sim.CATEGORIES}), 0.0)
        rows = self._sales(_probs())
        transactions = len({json.loads(r["raw_event"])["transaction_id"] for r in rows})
        self.assertAlmostEqual(len(rows) / transactions, 1.083, delta=0.02)
        self.assertIn("≈ 1.08 items", read_text("doc", "sales.md"))

    def test_transaction_ids_grow_with_purchase_time_across_channels(self):
        """Sorting the ids sorts the transactions by their GMT time, stores and e-commerce together, over batches."""
        from zoneinfo import ZoneInfo
        from test_dataset import _ecom_stores
        stores = _stores()
        ecom = [sim.Store(f"{c}-EC-001", MACRO[c], tz, "ECOM") for c, _, tz in _ecom_stores()]
        seller = sales.SalesGenerator(_catalog(), {s.store_id: s.store_id[:2] for s in stores + ecom},
                                      run_id="20261115T101648660", seed=2, ecom_stores=ecom,
                                      store_traffic=sim.store_traffic(stores), ecom_share=sim.CONFIG.ecom_share,
                                      ecom_price_pct=90, store_zones={s.store_id: s.timezone_id for s in stores + ecom})
        gen = sim.Generator(stores, run_id="20261115T101648660", seed=2)
        n_avg = {r: 3000 for r in sim.REGIONS}
        rows, t = [], datetime(2026, 11, 13, 6, tzinfo=timezone.utc)
        for _ in range(12):  # six hours, twelve batches
            rows += seller.batch(gen.tick(t, t + HALF_HOUR, n_avg), t, t + HALF_HOUR, n_avg, _probs())
            t += HALF_HOUR
        zones = {s.store_id: ZoneInfo(s.timezone_id) for s in stores + ecom}
        first = {}
        for row in rows:
            tx = json.loads(row["raw_event"])
            local = datetime.fromisoformat(tx["transaction_timestamp"]).replace(tzinfo=zones[tx["store_id"]])
            first.setdefault(tx["transaction_id"], local.astimezone(timezone.utc))
        ids = list(first)
        self.assertEqual(ids, sorted(ids), "ids come out in increasing order")
        times = [first[i] for i in ids]
        self.assertEqual(times, sorted(times), "a higher id is never an earlier purchase")
        self.assertTrue(any("-EC-" in r["raw_event"] for r in rows) and any("-EC-" not in r["raw_event"] for r in rows))
        self.assertTrue(all(i.startswith("TX-20261115T101648660-") for i in ids), "ids carry the simulation")

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
        transactions = {json.loads(r["raw_event"])["transaction_id"] for r in sold}
        self.assertEqual(sum(snap["sales"][r]["transactions"] for r in sim.REGIONS), len(transactions))
        self.assertEqual(sum(snap["sales"][r]["items"] for r in sim.REGIONS), len(sold))
        self.assertEqual(snap["sales_rows_written"], len(sold))
        amount = sum(json.loads(r["raw_event"])["amount"] for r in sold)
        self.assertAlmostEqual(sum(snap["sales"][r]["amount"] for r in sim.REGIONS), amount, places=2)

    def _cockpit_run(self, sales_on, ecommerce_on):
        from test_dataset import _ecom_stores
        sold = []
        stores = _stores()[:20] + [sim.Store("IT-EC-001", "EUROPE", "Europe/Rome", "ECOM")]
        s = sim.Simulation(lambda: stores, lambda: {}, lambda rows: None, tick_seconds=0.001, clock=_FastClock(7),
                           now=lambda: datetime(2026, 11, 13, 6, 0, tzinfo=timezone.utc),
                           load_catalog=_catalog, load_sales_offsets=lambda: {}, write_sales=sold.extend)
        s.set_cockpit(sales_on, ecommerce_on)
        s.start()
        s._thread.join(timeout=60)
        self.assertEqual(s.snapshot()["state"], "FINISHED")
        return [json.loads(r["raw_event"]) for r in sold], s.snapshot()

    def test_cockpit_switches_sales_and_ecommerce(self):
        both, snap = self._cockpit_run(True, True)
        self.assertTrue(any(t["store_id"] == "IT-EC-001" for t in both) and any(t["exit_event_id"] for t in both))
        self.assertEqual((snap["sales_enabled"], snap["ecommerce_enabled"]), (True, True))
        stores_only, _ = self._cockpit_run(True, False)
        self.assertTrue(stores_only)
        self.assertFalse(any(t["store_id"] == "IT-EC-001" for t in stores_only), "e-commerce off")
        nothing, snap = self._cockpit_run(False, True)
        self.assertEqual(nothing, [], "sales off: no sales at all, e-commerce included")
        self.assertEqual(snap["sales"]["EUROPE"]["transactions"], 0)

    def test_cockpit_defaults_and_screen(self):
        self.assertEqual((sim.CONFIG.cockpit_sales, sim.CONFIG.cockpit_ecommerce), (True, True))
        fresh = sim.Simulation(lambda: [], lambda: {}, lambda rows: None)
        self.assertEqual((fresh.sales_enabled, fresh.ecommerce_enabled), (True, True))
        app = read_text(*APP, "app", "app.py")
        for text in ('dbc.Switch(id="cockpit-sales"', 'dbc.Switch(id="cockpit-ecommerce"',
                     'Output("cockpit-ecommerce", "disabled"), Input("cockpit-sales", "value")',
                     "simulation.set_cockpit(sales_on, ecommerce_on)", "return not sales_on", "cockpit(snapshot),"):
            self.assertIn(text, app)
        layout = app.split("def serve_layout():", 1)[1]
        self.assertLess(layout.index('id="stop"'), layout.index("cockpit(snapshot)"), "just below START/STOP")
        self.assertLess(layout.index("cockpit(snapshot)"), layout.index("dbc.Tabs("))

    def test_every_start_first_empties_the_sources(self):
        log = []
        s = sim.Simulation(lambda: log.append("stores") or _stores()[:5], lambda: log.append("offsets") or {},
                           lambda rows: log.append("write"), tick_seconds=0.001, clock=_FastClock(7),
                           now=lambda: datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc),
                           clear_sources=lambda: log.append("clear"))
        for _ in range(2):
            s.start()
            s._thread.join(timeout=10)
            self.assertTrue(s.snapshot()["sources_cleared"])
        starts = [i for i, step in enumerate(log) if step == "clear"]
        self.assertEqual(len(starts), 2, "cleared once per START")
        for i in starts:
            self.assertEqual(log[i + 1], "stores", "nothing is read or written before the sources are emptied")
        self.assertIn("clear_sources=wh.clear_sources", read_text(*APP, "app", "app.py"))

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
                 "source_timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc)} for i in range(25000)]
        wh.write_sales(rows)
        self.assertEqual(len(statements), 3)
        for sql in statements:
            self.assertTrue(sql.startswith("MERGE INTO workspace.test02_streaming.simulated_sales_source"))
            self.assertNotIn("WHEN MATCHED", sql.replace("WHEN NOT MATCHED", ""))

    def test_clear_sources_empties_both_tables(self):
        wh, statements = warehouse.Warehouse(), []
        wh._execute = lambda sql, fetch=False: statements.append(sql)
        wh.clear_sources()
        self.assertEqual(statements, ["DELETE FROM workspace.test02_streaming.simulated_event_source",
                                      "DELETE FROM workspace.test02_streaming.simulated_sales_source"])

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
        for var, table in (("CLIENT_TABLE", "test02_warehouse.dim_client"),
                           ("PRODUCT_TABLE", "test02_warehouse.dim_product"),
                           ("SALES_TABLE", "test02_streaming.simulated_sales_source")):
            self.assertRegex(app_yaml, rf"name: {var}\n\s+value: workspace\.{table}")

    def test_sales_doc_matches_the_code(self):
        doc = read_text("doc", "sales.md")
        for text in ("`retail-sales-app`", "`TX-<simulation id>-<sequence, 10 digits>`", "chunks of at most 10,000",
                     "`store_id` → `dim_store`, `client_id` → `dim_client`, `product_id` → `dim_product`"):
            self.assertIn(text, doc)
        if sim is not None:
            self.assertEqual(sales.SALES_TOPIC, "retail-sales-app")
            self.assertEqual(warehouse.CHUNK_ROWS, 10000)


if __name__ == "__main__":
    unittest.main()
