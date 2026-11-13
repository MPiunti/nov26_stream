# Client dimension

Reference for `workspace.test02_streaming.dim_client`: the registered clients who buy in the stores. All clients are synthetic; the table holds no names, contacts or other personal data, only the client's natural ID and where they are registered.

Sales use clients as described in [`sales.md`](sales.md); stores are in [`dataset.md`](dataset.md).

## 1. Keys

| Key | Columns | Rule |
|---|---|---|
| Primary key | `client_id` | **Natural key**, the client's personal registration ID. No surrogate key |
| Referenced by | sales `client_id` | Every sales transaction names a registered client (see `sales.md` §5) |

## 2. Columns

| Column | Type | Rule |
|---|---|---|
| `client_id` | STRING, not null | `CL-<country_code>-<7 digits>`, e.g. `CL-IT-0000001`; numbers run from 1 to the country's client count |
| `country_code` | STRING, not null | Country where the client is registered, as in `dim_store`; equal to characters 4–5 of `client_id` |
| `macro_region` | STRING, not null | `EUROPE`, `AMERICAS` or `ASIA`: the macro region of `country_code` in `dim_store` |
| `registration_date` | DATE, not null | Spread over 2020-01-01 – 2025-12-30: `2020-01-01 + (number × 37 mod 2191)` days |
| `is_active` | BOOLEAN, not null | `TRUE` for every generated client |
| `created_at` | TIMESTAMP, not null | Set when the row is inserted |

## 3. Distribution

**250 registered clients per store** of each country, so the client base follows the store network: 50,000 clients for the 200 stores.

| Macro region | Country | Stores | Clients |
|---|---|---|---|
| EUROPE | IT | 40 | 10,000 |
| EUROPE | FR | 15 | 3,750 |
| EUROPE | DE | 12 | 3,000 |
| EUROPE | ES | 10 | 2,500 |
| EUROPE | NL | 8 | 2,000 |
| EUROPE | BE | 5 | 1,250 |
| EUROPE | AT | 4 | 1,000 |
| EUROPE | PT | 3 | 750 |
| EUROPE | SE | 3 | 750 |
| AMERICAS | US | 60 | 15,000 |
| ASIA | CN | 14 | 3,500 |
| ASIA | JP | 13 | 3,250 |
| ASIA | KR | 13 | 3,250 |
| **All** | 13 countries | **200** | **50,000** (EUROPE 25,000, AMERICAS 15,000, ASIA 10,000) |

## 4. How sales use clients

A client buys only in stores of their own country: for each purchase, the sales simulator picks one client at random, uniformly, from the active clients whose `country_code` is the store's country (the first two characters of `store_id`). The same client can buy many times.

## 5. Loading and changing it

All scripts are in `src/sql/`, run by hand on the SQL warehouse, after `01`/`02` (stores):

1. `08_create_dim_client.sql` creates the table with its primary key. Idempotent.
2. `09_populate_dim_client.sql` merges the clients from `dim_store` (250 per store of each country). Idempotent: insert-only `MERGE` on `client_id`.
3. `13_validate_dim_client_product.sql` must return `PASS` on every row: total 50,000, count per country, no duplicate IDs, ID format, country and macro region matching `dim_store`.

To change the client base, change the factor 250 in `09_…` and the expected total in `13_…`, update §3, and rerun. Clients are never deleted by the scripts; a smaller factor leaves extra clients in place.

The people-stream app reads `client_id` and `country_code` of active clients once, at START.
