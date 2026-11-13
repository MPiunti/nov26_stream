
-- ============================================================
-- 10 - Create product dimension
-- Target: workspace.test02_streaming.dim_product
--
-- Products identified by their natural product_id (no surrogate
-- key). Rules: doc/product.md.
-- Idempotent. Then run 11_populate_dim_product.sql.
-- ============================================================

CREATE TABLE IF NOT EXISTS workspace.test02_streaming.dim_product
(
    product_id STRING NOT NULL
        COMMENT 'Natural product identifier (SKU), <category code>-<4-digit number>, e.g. SH-0001; primary key',

    product_name STRING NOT NULL
        COMMENT 'Product name',

    category STRING NOT NULL
        COMMENT 'Merchandise category: SHOES, BAGS, READY_TO_WEAR, ACCESSORIES, TRAVEL or SUNGLASSES',

    list_price DECIMAL(10, 2) NOT NULL
        COMMENT 'List price per unit',

    currency STRING NOT NULL
        COMMENT 'ISO 4217 currency of list_price; EUR',

    is_active BOOLEAN NOT NULL
        COMMENT 'Indicates whether the product is currently sold',

    created_at TIMESTAMP NOT NULL
        COMMENT 'Record creation timestamp',

    CONSTRAINT pk_dim_product
        PRIMARY KEY (product_id)
)
USING DELTA
COMMENT 'Dimension of fashion products by merchandise category; natural key product_id';
