# Product dimension

Reference for `workspace.test02_warehouse.dim_product`: the luxury products the stores sell (outdoor and leather garments, leather goods, accessories), by merchandise category. All products are synthetic. Price points and the resulting average transaction (about 1,000 EUR) are explained in [`sales.md`](sales.md) §11.

Sales use products as described in [`sales.md`](sales.md); the schemas and keys are in [`warehouse.md`](warehouse.md).

## 1. Keys

| Key | Columns | Rule |
|---|---|---|
| Primary key | `product_id` | **Natural key**, the product's SKU. No surrogate key |
| Referenced by | sales `product_id` | Every sales transaction names one product (see `sales.md` §5) |

## 2. Merchandise categories

| `category` | Code | Name prefix | Products | List price (EUR) | Average price |
|---|---|---|---|---|---|
| `SHOES` | SH | Shoes | 20 | 575 – 1,050, step 25 | 812.50 |
| `BAGS` | BG | Bag | 20 | 1,380 – 2,900, step 80 | 2,140 |
| `READY_TO_WEAR` | RW | Ready-to-wear | 20 | 600 – 1,550, step 50 | 1,075 |
| `ACCESSORIES` | AC | Accessory | 20 | 220 – 600, step 20 | 410 |
| `TRAVEL` | TR | Travel | 20 | 1,070 – 2,400, step 70 | 1,735 |
| `SUNGLASSES` | SG | Sunglasses | 20 | 262 – 490, step 12 | 376 |
| **All** | | | **120** | 220 – 2,900 | |

The same six categories, in this order, are the PURCHASE_PROB categories of the sales simulator and of `shop_config.yml` (`sales.md` §3). A new category must be added here, in `11_populate_dim_product.sql`, in `13_validate_dim_client_product.sql`, and in `CATEGORIES` of `apps/people_stream/app/shop_config.py` and `shop_config.yml`, in the same change.

## 3. Columns

| Column | Type | Rule |
|---|---|---|
| `product_id` | STRING, not null | `<code>-<4 digits>`, e.g. `SH-0001` … `SH-0020` |
| `product_name` | STRING, not null | `<name prefix> <3 digits>`, e.g. `Shoes 001` |
| `category` | STRING, not null | One of the six categories in §2 |
| `list_price` | DECIMAL(10,2), not null | `base + n × step` for product number `n` (1–20); base and step per category in `11_…` |
| `currency` | STRING, not null | `EUR`: prices and transaction values are always in euro |
| `is_active` | BOOLEAN, not null | `TRUE` for every generated product |
| `created_at` | TIMESTAMP, not null | Set when the row is inserted |

## 4. How sales use products

For each purchase in a category, the sales simulator picks one active product of that category at random, uniformly, and sells one unit at its `list_price` (`sales.md` §4). Prices are the same in every country and region. Online, in the e-commerce stores, the same products sell at 90% of `list_price` (`ecommerce.price_pct`, `sales.md` §12).

## 5. Loading and changing it

All scripts are in `src/sql/`, run by hand on the SQL warehouse:

1. `10_create_dim_product.sql` creates the table with its primary key. Idempotent.
2. `11_populate_dim_product.sql` merges the 120 products. Idempotent `MERGE` on `product_id`: new products are inserted, and an existing product whose list price differs from the script gets the script's price. To change a price list, edit the base and step in `11_…` and run it again.
3. `13_validate_dim_client_product.sql` must return `PASS` on every row: total 120, 20 per category, no duplicate IDs, ID format, category, price above zero, currency EUR.

The people-stream app reads `product_id`, `category` and `list_price` of active products once, at START.
