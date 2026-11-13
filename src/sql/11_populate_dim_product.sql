
-- ============================================================
-- 11 - Populate product dimension
-- Target: workspace.test02_streaming.dim_product
--
-- 20 products per merchandise category, 120 in total.
-- product_id = <code>-<4-digit number>; list_price = base + n * step.
--
--   Category        Code  Base   Step   Price range (EUR)
--   SHOES           SH     400    20      420 -   800
--   BAGS            BG     900    60      960 - 2,100
--   READY_TO_WEAR   RW     300    40      340 - 1,100
--   ACCESSORIES     AC     150    15      165 -   450
--   TRAVEL          TR     700    50      750 - 1,700
--   SUNGLASSES      SG     200    10      210 -   400
--
-- Idempotent: MERGE by natural product_id, insert only.
-- Rules: doc/product.md.
-- ============================================================

MERGE INTO workspace.test02_streaming.dim_product AS target

USING (
    WITH categories AS (
        SELECT *
        FROM VALUES
            ('SHOES', 'SH', 'Shoes', 400, 20),
            ('BAGS', 'BG', 'Bag', 900, 60),
            ('READY_TO_WEAR', 'RW', 'Ready-to-wear', 300, 40),
            ('ACCESSORIES', 'AC', 'Accessory', 150, 15),
            ('TRAVEL', 'TR', 'Travel', 700, 50),
            ('SUNGLASSES', 'SG', 'Sunglasses', 200, 10)
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
