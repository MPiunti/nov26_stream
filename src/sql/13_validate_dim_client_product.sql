
-- ============================================================
-- 13 - Validate client and product dimensions
-- Targets: workspace.test02_streaming.dim_client, dim_product
-- Expected: 50,000 clients (250 per store of each country),
--           120 products (20 per category). Every row must PASS.
-- ============================================================

WITH expected_clients AS (
    SELECT country_code, COUNT(*) * 250 AS expected_count
    FROM workspace.test02_streaming.dim_store
    GROUP BY country_code
),

actual_clients AS (
    SELECT country_code, COUNT(*) AS actual_count
    FROM workspace.test02_streaming.dim_client
    GROUP BY country_code
),

expected_categories AS (
    SELECT *
    FROM VALUES
        ('SHOES'), ('BAGS'), ('READY_TO_WEAR'), ('ACCESSORIES'), ('TRAVEL'), ('SUNGLASSES')
    AS t(category)
),

checks AS (

    SELECT 'TOTAL_CLIENTS' AS validation, 50000 AS expected_value, COUNT(*) AS actual_value
    FROM workspace.test02_streaming.dim_client

    UNION ALL

    SELECT CONCAT('CLIENTS_', e.country_code), e.expected_count, COALESCE(a.actual_count, 0)
    FROM expected_clients e
    LEFT JOIN actual_clients a ON e.country_code = a.country_code

    UNION ALL

    SELECT 'DUPLICATE_CLIENT_IDS', 0, COUNT(*)
    FROM (SELECT client_id FROM workspace.test02_streaming.dim_client GROUP BY client_id HAVING COUNT(*) > 1)

    UNION ALL

    -- client_id format and agreement with the client country and region
    SELECT 'INVALID_CLIENTS', 0, COUNT(*)
    FROM workspace.test02_streaming.dim_client c
    LEFT JOIN (SELECT DISTINCT country_code, macro_region FROM workspace.test02_streaming.dim_store) s
        ON c.country_code = s.country_code
    WHERE NOT c.client_id RLIKE '^CL-[A-Z]{2}-[0-9]{7}$'
       OR SUBSTRING(c.client_id, 4, 2) <> c.country_code
       OR s.macro_region IS NULL
       OR c.macro_region <> s.macro_region

    UNION ALL

    SELECT 'TOTAL_PRODUCTS', 120, COUNT(*)
    FROM workspace.test02_streaming.dim_product

    UNION ALL

    SELECT CONCAT('PRODUCTS_', e.category), 20, COUNT(p.product_id)
    FROM expected_categories e
    LEFT JOIN workspace.test02_streaming.dim_product p ON p.category = e.category
    GROUP BY e.category

    UNION ALL

    SELECT 'DUPLICATE_PRODUCT_IDS', 0, COUNT(*)
    FROM (SELECT product_id FROM workspace.test02_streaming.dim_product GROUP BY product_id HAVING COUNT(*) > 1)

    UNION ALL

    SELECT 'INVALID_PRODUCTS', 0, COUNT(*)
    FROM workspace.test02_streaming.dim_product
    WHERE NOT product_id RLIKE '^(SH|BG|RW|AC|TR|SG)-[0-9]{4}$'
       OR category NOT IN (SELECT category FROM expected_categories)
       OR list_price <= 0
       OR currency <> 'EUR'
)

SELECT
    validation,
    expected_value,
    actual_value,
    CASE WHEN expected_value = actual_value THEN 'PASS' ELSE 'FAIL' END AS validation_status
FROM checks
ORDER BY validation;
