
-- ============================================================
-- 14 - One-off: drop the old dimension copies from test02_streaming
--
-- The dimensions moved to workspace.test02_warehouse (doc/warehouse.md).
-- Run this ONCE, only after:
--   1. 01, 02, 08, 09, 10, 11 have created and loaded the dimensions
--      in test02_warehouse, and 03 and 13 return PASS;
--   2. the pipeline has run with "Full refresh all", so silver's foreign
--      key points to test02_warehouse.dim_store;
--   3. the app has been redeployed (it reads test02_warehouse).
-- Idempotent: IF EXISTS.
-- ============================================================

DROP TABLE IF EXISTS workspace.test02_streaming.dim_client;

DROP TABLE IF EXISTS workspace.test02_streaming.dim_product;

DROP TABLE IF EXISTS workspace.test02_streaming.dim_store;
