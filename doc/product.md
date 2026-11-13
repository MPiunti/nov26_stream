# Product dimension

Reference for `workspace.test02_streaming.dim_product`: the fashion products the stores sell, by merchandise category. All products are synthetic.

Sales use products as described in [`sales.md`](sales.md).

## 1. Keys

| Key | Columns | Rule |
|---|---|---|
| Primary key | `product_id` | **Natural key**, the product's SKU. No surrogate key |
| Referenced by | sales `product_id` | Every sales transaction names one product (see `sales.md` §5) |

## 2. Merchandise categories

| `category` | Code | Name prefix | Products | List price (EUR) | Average price |
|---|---|---|---|---|---|
| `SHOES` | SH | Shoes | 20 | 420 – 800, step 20 | 610 |
| `BAGS` | BG | Bag | 20 | 960 – 2,100, step 60 | 1,530 |
| `READY_TO_WEAR` | RW | Ready-to-wear | 20 | 340 – 1,100, step 40 | 720 |
| `ACCESSORIES` | AC | Accessory | 20 | 165 – 450, step 15 | 307.50 |
| `TRAVEL` | TR | Travel | 20 | 750 – 1,700, step 50 | 1,225 |
| `SUNGLASSES` | SG | Sunglasses | 20 | 210 – 400, step 10 | 305 |
| **All** | | | **120** | 165 – 2,100 | |

The same six categories, in this order, are the PURCHASE_PROB categories of the sales simulator and of `shop_config.yml` (`sales.md` §3). A new category must be added here, in `11_populate_dim_product.sql`, in `13_validate_dim_client_product.sql`, and in `CATEGORIES` of `apps/people_stream/app/shop_config.py` and `shop_config.yml`, in the same change.

## 3. Columns

| Column | Type | Rule |
|---|---|---|
| `product_id` | STRING, not null | `<code>-<4 digits>`, e.g. `SH-0001` … `SH-0020` |
| `product_name` | STRING, not null | `<name prefix> <3 digits>`, e.g. `Shoes 001` |
| `category` | STRING, not null | One of the six categories in §2 |
| `list_price` | DECIMAL(10,2), not null | `base + n × step` for product number `n` (1–20); base and step per category in `11_…` |
| `currency` | STRING, not null | `EUR` |
| `is_active` | BOOLEAN, not null | `TRUE` for every generated product |
| `created_at` | TIMESTAMP, not null | Set when the row is inserted |

## 4. How sales use products

For each purchase in a category, the sales simulator picks one active product of that category at random, uniformly, and sells one unit at its `list_price` (`sales.md` §4). Prices are the same in every country and region.

## 5. Loading and changing it

All scripts are in `src/sql/`, run by hand on the SQL warehouse:

1. `10_create_dim_product.sql` creates the table with its primary key. Idempotent.
2. `11_populate_dim_product.sql` merges the 120 products. Idempotent: insert-only `MERGE` on `product_id`; existing products, including their prices, are not changed.
3. `13_validate_dim_client_product.sql` must return `PASS` on every row: total 120, 20 per category, no duplicate IDs, ID format, category, price above zero, currency EUR.

The people-stream app reads `product_id`, `category` and `list_price` of active products once, at START.
