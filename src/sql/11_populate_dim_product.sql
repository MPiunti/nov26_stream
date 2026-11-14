
-- ============================================================
-- 11 - Populate product dimension
-- Target: workspace.test02_warehouse.dim_product
--
-- 20 products per merchandise category, 120 in total.
-- product_id = <code>-<4-digit number>; list_price = base + n * step.
-- Luxury price points: about 1,000 EUR per transaction on average
-- (doc/sales.md, "Purchase model").
--
--   Category        Code  Base   Step   Price range (EUR)
--   SHOES           SH     550    25      575 - 1,050
--   BAGS            BG   1,300    80    1,380 - 2,900
--   READY_TO_WEAR   RW     550    50      600 - 1,550
--   ACCESSORIES     AC     200    20      220 -   600
--   TRAVEL          TR   1,000    70    1,070 - 2,400
--   SUNGLASSES      SG     250    12      262 -   490
--
-- Idempotent: MERGE by natural product_id. New products are inserted;
-- an existing product whose list price differs gets the new price
-- (a dimension, not a streaming source, so updates are allowed).
-- Rules: doc/product.md.
-- ============================================================

MERGE INTO workspace.test02_warehouse.dim_product AS target

USING (
    WITH categories AS (
        SELECT *
        FROM VALUES
            ('SHOES', 'SH', 'Shoes', 550, 25),
            ('BAGS', 'BG', 'Bag', 1300, 80),
            ('READY_TO_WEAR', 'RW', 'Ready-to-wear', 550, 50),
            ('ACCESSORIES', 'AC', 'Accessory', 200, 20),
            ('TRAVEL', 'TR', 'Travel', 1000, 70),
            ('SUNGLASSES', 'SG', 'Sunglasses', 250, 12)
        AS c(category, code, label, base_price, price_step)
    )

    SELECT
        CONCAT(code, '-', LPAD(CAST(n AS STRING), 4, '0')) AS product_id,
        CONCAT(label, ' ', LPAD(CAST(n AS STRING), 3, '0')) AS product_name,
        category,
        CAST(base_price + n * price_step AS DECIMAL(10, 2)) AS list_price
    FROM categories
    LATERAL VIEW EXPLODE(SEQUENCE(1, 20)) generated AS n
) AS source

ON target.product_id = source.product_id

-- Price list change: reprice existing products.
WHEN MATCHED AND NOT (target.list_price <=> source.list_price) THEN UPDATE SET
    target.list_price = source.list_price

WHEN NOT MATCHED THEN INSERT (
    product_id,
    product_name,
    category,
    list_price,
    currency,
    is_active,
    created_at
)
VALUES (
    source.product_id,
    source.product_name,
    source.category,
    source.list_price,
    'EUR',
    TRUE,
    CURRENT_TIMESTAMP()
);
