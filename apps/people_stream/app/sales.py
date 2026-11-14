"""Sales simulator: turns the people stream's EXIT events into sales transactions. Standard library only.

Functional description: doc/sales.md. For every person counted in an EXIT event and every merchandise
category, the person buys one item of that category with probability PURCHASE_PROB[region][category]
(percent, set by the app's horizontal sliders). Each purchase is one transaction: the store, a registered
client (from the store's country with probability clients.local_share, 70%, otherwise a visitor registered in
another country; flagships use flagships.local_share, 30%), one product of the category at list price, at
the exit's local time.
"""
import json
import math
import random
from collections import defaultdict
from dataclasses import dataclass

import shop_config

CATEGORIES = shop_config.CATEGORIES
REGIONS = shop_config.REGIONS
SALES_TOPIC = "retail-sales-app"
PARTITION = {r: i for i, r in enumerate(REGIONS)}  # same partitions as the people stream
CURRENCY = "EUR"


@dataclass(frozen=True)
class Product:
    product_id: str
    category: str
    list_price: float


class Catalog:
    """Products by category and registered clients by country, read from dim_product and dim_client."""

    def __init__(self, products, clients):
        self.products_by_category = {c: [] for c in CATEGORIES}
        for p in products:
            if p.category not in self.products_by_category:
                raise ValueError(f"product {p.product_id} has unknown category {p.category}")
            self.products_by_category[p.category].append(p)
        empty = [c for c, items in self.products_by_category.items() if not items]
        if empty:
            raise ValueError(f"no products in categories {empty}: run src/sql/11_populate_dim_product.sql")
        self.clients_by_country = defaultdict(list)
        self.all_clients = []  # (client_id, country_code), for visitors
        for client_id, country_code in clients:
            self.clients_by_country[country_code].append(client_id)
            self.all_clients.append((client_id, country_code))
        if not self.clients_by_country:
            raise ValueError("no clients: run src/sql/09_populate_dim_client.sql")


def binomial(n, p, rng):
    """People out of n who buy, each with probability p."""
    if n <= 0 or p <= 0:
        return 0
    if p >= 1:
        return n
    if n <= 2000:
        return sum(1 for _ in range(n) if rng.random() < p)
    mean, sd = n * p, math.sqrt(n * p * (1 - p))
    return max(0, min(n, int(round(rng.gauss(mean, sd)))))


class SalesGenerator:
    """Second simulator on the same timeline: reads each batch of people rows, emits sales rows."""

    def __init__(self, catalog, store_country, next_offsets=None, run_id="run", seed=None,
                 local_share=100, flagship_ids=(), flagship_local_share=100):
        self.catalog = catalog
        self.store_country = store_country  # {store_id: country_code}
        self.local_share = local_share  # percent of buyers from the store's country
        self.flagship_ids = frozenset(flagship_ids)
        self.flagship_local_share = flagship_local_share
        self.next_offset = {p: (next_offsets or {}).get(p, 1) for p in PARTITION.values()}
        self.run_id = run_id
        self.rng = random.Random(seed)

    def sales_for(self, people_rows, prob_by_region):
        """Sales rows for the EXIT events in people_rows; prob_by_region = {region: {category: percent}}."""
        rows = []
        for row in people_rows:
            event = json.loads(row["raw_event"])
            if event["event_type"] != "EXIT":
                continue
            region = REGIONS[row["source_partition"]]
            country = self.store_country.get(event["store_id"])
            if not self.catalog.clients_by_country.get(country):
                raise ValueError(f"no registered clients for the country of store {event['store_id']}")
            share = self.flagship_local_share if event["store_id"] in self.flagship_ids else self.local_share
            for category in CATEGORIES:
                buyers = binomial(event["people_count"], prob_by_region[region][category] / 100, self.rng)
                for _ in range(buyers):
                    rows.append(self._transaction(row, event, region, category, self._client(country, share)))
        return rows

    def _client(self, country, local_share):
        """A local client with probability local_share percent, otherwise a visitor from another country."""
        local = self.catalog.clients_by_country[country]
        if self.rng.random() * 100 < local_share or len(local) == len(self.catalog.all_clients):
            return self.rng.choice(local)
        while True:  # other countries hold most clients, so this ends after a draw or two
            client_id, client_country = self.rng.choice(self.catalog.all_clients)
            if client_country != country:
                return client_id

    def _transaction(self, row, event, region, category, client_id):
        product = self.rng.choice(self.catalog.products_by_category[category])
        partition = PARTITION[region]
        offset = self.next_offset[partition]
        self.next_offset[partition] += 1
        payload = {
            "transaction_id": f"tx-{self.run_id}-{partition}-{offset:010d}",
            "exit_event_id": event["event_id"],
            "store_id": event["store_id"],
            "client_id": client_id,
            "product_id": product.product_id,
            "category": category,
            "quantity": 1,
            "unit_price": round(product.list_price, 2),
            "amount": round(product.list_price, 2),
            "currency": CURRENCY,
            "transaction_timestamp": event["event_timestamp"],
        }
        return {
            "raw_event": json.dumps(payload, separators=(",", ":")),
            "source_topic": SALES_TOPIC,
            "source_partition": partition,
            "source_offset": offset,
            "source_timestamp": row["source_timestamp"],
        }
