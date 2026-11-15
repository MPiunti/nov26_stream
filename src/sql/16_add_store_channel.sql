-- ============================================================
-- 16 - Add the sales channel to an existing store dimension
-- Target: workspace.test02_warehouse.dim_store
--
-- One-off migration for a dim_store created before the channel
-- column existed. A new workspace doesn't need it: 01_create_dim_store.sql
-- creates the table with the column.
--
-- Run it once, then run 02_populate_dim_store.sql (fills channel for
-- the 200 physical stores and adds the 13 e-commerce stores) and check
-- with 03_validate_dim_store.sql. Running it a second time fails with
-- "column already exists" and changes nothing.
-- Rules: doc/dataset.md, "Sales channels".
-- ============================================================

ALTER TABLE workspace.test02_warehouse.dim_store
ADD COLUMN channel STRING
    COMMENT 'Sales channel: RETAIL, FLAGSHIP (both physical, with people counting) or ECOM (online, sales only)';
