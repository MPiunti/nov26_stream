"""Sales simulator: turns the people stream's EXIT events into sales transactions. Standard library only.

Functional description: doc/sales.md. For every person counted in an EXIT event and every merchandise
category, the person buys one item of that category with probability PURCHASE_PROB[region][category]
(percent, set by the app's horizontal sliders). Each purchase is one transaction: the store, a registered
client (from the store's country with probability clients.local_share, 70%, otherwise a visitor registered in
another country; flagships use flagships.local_share, 30%), one product of the category at list price, at
the exit's local time.

Baskets: a buyer can buy in several categories during one visit (shoes, a garment, sunglasses...). Everything
one buyer buys is ONE transaction, with one transaction_id and one line per item (line_number 1..line_count).
Transaction ids are TX-<simulation id>-<10-digit sequence>, the sequence given in GMT purchase-time order across
all stores and channels, so sorting the ids sorts the transactions by time.

The e-commerce stores (channel ECOM, one per country) have no people stream. Their sales are generated per
batch from a 24-hour online curve, sized as a share of the country's total sales value and sold at the online
price (ecommerce.* in shop_config.yml). See doc/sales.md, "E-commerce sales".
"""
import json
import math
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import shop_config

CATEGORIES = shop_config.CATEGORIES
REGIONS = shop_config.REGIONS
SALES_TOPIC = "retail-sales-app"
PARTITION = {r: i for i, r in enumerate(REGIONS)}  # same partitions as the people stream
CURRENCY = "EUR"
ECOM = "ECOM"  # dim_store.channel of the e-commerce stores; RETAIL and FLAGSHIP are the physical ones

# How online sales spread over the 24 hours of the store's local day (hour 0 to 23): quiet at night, rising
# through the day, a peak after dinner. Relative weights; ECOM_HOURLY averages 1, so a day's total is unchanged.
_ECOM_CURVE = (0.35, 0.20, 0.12, 0.08, 0.08, 0.12, 0.30, 0.60, 0.90, 1.10, 1.20, 1.25,
               1.40, 1.35, 1.20, 1.15, 1.20, 1.30, 1.50, 1.75, 1.95, 2.00, 1.60, 0.90)
ECOM_HOURLY = tuple(w * 24 / sum(_ECOM_CURVE) for w in _ECOM_CURVE)


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


def poisson(mean, rng):
    """A count with this mean: how many online orders arrive in a time window."""
    if mean <= 0:
        return 0
    if mean > 30:
        return max(0, int(round(rng.gauss(mean, math.sqrt(mean)))))
    limit, count, product = math.exp(-mean), 0, rng.random()
    while product > limit:
        count += 1
        product *= rng.random()
    return count


def ecom_factor(share_pct, price_pct):
    """E-commerce items per store item of the same country and category.

    ECOM is share_pct of the country's total sales value, so its value is share / (100 - share) of the stores'
    value; each ECOM item is worth price_pct of a store item of the same category.
    """
    return share_pct / (100 - share_pct) / (price_pct / 100)


def items_per_basket(probs):
    """Average items in a basket: expected items per person / chance that a person buys anything at all."""
    p = [probs[c] / 100 for c in CATEGORIES]
    nothing = 1.0
    for x in p:
        nothing *= 1 - x
    return sum(p) / (1 - nothing) if nothing < 1 else 0.0


@dataclass
class Basket:
    """What one buyer buys in one visit or online order: one transaction, one line per category bought."""
    utc: datetime              # purchase time in GMT: orders the transaction ids
    local_ts: str              # the store's local time, as in the people events
    store_id: str
    region: str
    client_id: str
    categories: list
    exit_event_id: object      # the EXIT event of the visit; None online
    source_timestamp: object
    price_pct: int = 100


class SalesGenerator:
    """Second simulator on the same timeline: reads each batch of people rows, emits sales rows (one per item)."""

    def __init__(self, catalog, store_country, next_offsets=None, run_id="run", seed=None,
                 local_share=100, flagship_ids=(), flagship_local_share=100,
                 ecom_stores=(), store_traffic=None, ecom_share=None, ecom_price_pct=100, store_zones=None):
        # E-commerce: ecom_stores are Store-like objects (store_id, macro_region, timezone_id) of channel ECOM;
        # store_traffic is {country: physical stores, flagships weighted by their traffic}, the country's
        # daily visitors in units of N_AVG_PEOPLE; ecom_share(country) is ECOM's percent of total sales value.
        # store_zones is {store_id: IANA time zone}, to put store purchases on the GMT timeline.
        self.ecom_stores = [(s, ZoneInfo(s.timezone_id)) for s in ecom_stores]
        self.store_traffic = dict(store_traffic or {})
        self.ecom_share = ecom_share or (lambda country: 0)
        self.ecom_price_pct = ecom_price_pct
        self.zones = {k: ZoneInfo(v) for k, v in (store_zones or {}).items()}
        self.catalog = catalog
        self.store_country = store_country  # {store_id: country_code}
        self.local_share = local_share  # percent of buyers from the store's country
        self.flagship_ids = frozenset(flagship_ids)
        self.flagship_local_share = flagship_local_share
        self.next_offset = {p: (next_offsets or {}).get(p, 1) for p in PARTITION.values()}
        self.next_transaction = 1  # sequence of the transaction ids, in GMT purchase-time order
        self.run_id = run_id
        self.rng = random.Random(seed)

    # ------------------------------------------------------------------ one batch

    def batch(self, people_rows, sim_from_utc, sim_to_utc, n_avg_by_region, prob_by_region, ecommerce=True):
        """All sales rows of one batch, store and e-commerce, with transaction ids in purchase-time order."""
        baskets = self.store_baskets(people_rows, prob_by_region)
        if ecommerce:
            baskets += self.ecom_baskets(sim_from_utc, sim_to_utc, n_avg_by_region, prob_by_region)
        return self.rows(baskets)

    def sales_for(self, people_rows, prob_by_region):
        """Store sales rows for the EXIT events in people_rows; prob_by_region = {region: {category: percent}}."""
        return self.rows(self.store_baskets(people_rows, prob_by_region))

    def ecom_sales(self, sim_from_utc, sim_to_utc, n_avg_by_region, prob_by_region):
        """E-commerce sales rows for one time window."""
        return self.rows(self.ecom_baskets(sim_from_utc, sim_to_utc, n_avg_by_region, prob_by_region))

    # ------------------------------------------------------------------ baskets

    def store_baskets(self, people_rows, prob_by_region):
        """Per person leaving: each category bought with probability PURCHASE_PROB; a non-empty basket is a sale."""
        baskets = []
        for row in people_rows:
            event = json.loads(row["raw_event"])
            if event["event_type"] != "EXIT":
                continue
            region = REGIONS[row["source_partition"]]
            country = self.store_country.get(event["store_id"])
            if not self.catalog.clients_by_country.get(country):
                raise ValueError(f"no registered clients for the country of store {event['store_id']}")
            share = self.flagship_local_share if event["store_id"] in self.flagship_ids else self.local_share
            probs = prob_by_region[region]
            local = datetime.fromisoformat(event["event_timestamp"])
            zone = self.zones.get(event["store_id"])
            utc = (local.replace(tzinfo=zone) if zone else local.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
            for _ in range(event["people_count"]):
                bought = self._basket(probs)
                if bought:
                    baskets.append(Basket(utc, event["event_timestamp"], event["store_id"], region,
                                          self._client(country, share), bought, event["event_id"],
                                          row["source_timestamp"]))
        return baskets

    def ecom_baskets(self, sim_from_utc, sim_to_utc, n_avg_by_region, prob_by_region):
        """Online orders of the e-commerce stores for one time window: no people, no EXIT events.

        Per ECOM store, the expected online items are the country's expected store items in the window (as if
        spread evenly over 24 hours), times ecom_factor, times the online curve at the store's local hour. They
        come in baskets like the stores' (same categories, same items per basket), so the number of orders is
        drawn around items / items_per_basket. The buyer is a client registered in the country.
        """
        baskets = []
        seconds = (sim_to_utc - sim_from_utc).total_seconds()
        if seconds <= 0:
            return baskets
        middle = sim_from_utc + (sim_to_utc - sim_from_utc) / 2
        for store, tz in self.ecom_stores:
            country, region = self.store_country[store.store_id], store.macro_region
            clients = self.catalog.clients_by_country.get(country)
            if not clients:
                raise ValueError(f"no registered clients for the country of store {store.store_id}")
            share, probs = self.ecom_share(country), prob_by_region[region]
            per_basket = items_per_basket(probs)
            if not share or not per_basket:
                continue
            visitors_per_day = self.store_traffic.get(country, 0) * n_avg_by_region[region]
            items = (visitors_per_day * sum(probs.values()) / 100 * seconds / 86400
                     * ecom_factor(share, self.ecom_price_pct) * ECOM_HOURLY[middle.astimezone(tz).hour])
            for _ in range(poisson(items / per_basket, self.rng)):
                utc = (sim_from_utc + timedelta(seconds=self.rng.random() * seconds)).astimezone(timezone.utc)
                bought = []
                while not bought:  # an order has at least one item
                    bought = self._basket(probs)
                local = utc.astimezone(tz).replace(tzinfo=None).isoformat(timespec="milliseconds")
                baskets.append(Basket(utc, local, store.store_id, region, self.rng.choice(clients), bought,
                                      None, sim_to_utc, self.ecom_price_pct))
        return baskets

    def _basket(self, probs):
        """The categories one person buys: each with its own probability, at most one item per category."""
        return [c for c in CATEGORIES if self.rng.random() * 100 < probs[c]]

    def _client(self, country, local_share):
        """A local client with probability local_share percent, otherwise a visitor from another country."""
        local = self.catalog.clients_by_country[country]
        if self.rng.random() * 100 < local_share or len(local) == len(self.catalog.all_clients):
            return self.rng.choice(local)
        while True:  # other countries hold most clients, so this ends after a draw or two
            client_id, client_country = self.rng.choice(self.catalog.all_clients)
            if client_country != country:
                return client_id

    # ------------------------------------------------------------------ rows

    def rows(self, baskets):
        """Source rows, one per item; transaction ids given in GMT purchase-time order."""
        out = []
        for b in sorted(baskets, key=lambda b: b.utc):
            transaction_id = f"TX-{self.run_id}-{self.next_transaction:010d}"
            self.next_transaction += 1
            for line, category in enumerate(b.categories, 1):
                out.append(self._row(b, transaction_id, line, category))
        return out

    def _row(self, basket, transaction_id, line_number, category):
        """One source row: one item of the category, at price_pct of its list price."""
        product = self.rng.choice(self.catalog.products_by_category[category])
        price = round(product.list_price * basket.price_pct / 100, 2)
        partition = PARTITION[basket.region]
        offset = self.next_offset[partition]
        self.next_offset[partition] += 1
        payload = {
            "transaction_id": transaction_id,
            "line_number": line_number,
            "line_count": len(basket.categories),
            "simulation_id": self.run_id,
            "exit_event_id": basket.exit_event_id,
            "store_id": basket.store_id,
            "client_id": basket.client_id,
            "product_id": product.product_id,
            "category": category,
            "quantity": 1,
            "unit_price": price,
            "amount": price,
            "currency": CURRENCY,
            "transaction_timestamp": basket.local_ts,
        }
        return {
            "raw_event": json.dumps(payload, separators=(",", ":")),
            "source_topic": SALES_TOPIC,
            "source_partition": partition,
            "source_offset": offset,
            "source_timestamp": basket.source_timestamp,
        }
