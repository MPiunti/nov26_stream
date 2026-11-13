
-- ============================================================
-- 03 - Validate Silver store dimension
-- Target: workspace.test02_streaming.dim_store
-- Expected records: 200
-- ============================================================

WITH expected_country AS (
    SELECT *
    FROM VALUES
        ('IT', 40),
        ('FR', 15),
        ('DE', 12),
        ('ES', 10),
        ('NL', 8),
        ('BE', 5),
        ('AT', 4),
        ('PT', 3),
        ('SE', 3),
        ('US', 60),
        ('CN', 14),
        ('JP', 13),
        ('KR', 13)
    AS t(country_code, expected_count)
),

actual_country AS (
    SELECT
        country_code,
        COUNT(*) AS actual_count
    FROM workspace.test02_streaming.dim_store
    GROUP BY country_code
),

expected_macro_region AS (
    SELECT *
    FROM VALUES
        ('EUROPE', 100),
        ('AMERICAS', 60),
        ('ASIA', 40)
    AS t(macro_region, expected_count)
),

actual_macro_region AS (
    SELECT
        macro_region,
        COUNT(*) AS actual_count
    FROM workspace.test02_streaming.dim_store
    GROUP BY macro_region
),

checks AS (

    -- Total number of stores
    SELECT
        'TOTAL_STORES' AS validation,
        200 AS expected_value,
        COUNT(*) AS actual_value
    FROM workspace.test02_streaming.dim_store

    UNION ALL

    -- Expected country distribution
    SELECT
        CONCAT('COUNTRY_', e.country_code),
        e.expected_count,
        COALESCE(a.actual_count, 0)
    FROM expected_country e
    LEFT JOIN actual_country a
        ON e.country_code = a.country_code

    UNION ALL

    -- Expected macro region distribution
    SELECT
        CONCAT('MACRO_REGION_', e.macro_region),
        e.expected_count,
        COALESCE(a.actual_count, 0)
    FROM expected_macro_region e
    LEFT JOIN actual_macro_region a
        ON e.macro_region = a.macro_region

    UNION ALL

    -- Macro region missing or not matching the country
    SELECT
        'INVALID_COUNTRY_MACRO_REGION',
        0,
        COUNT(*)
    FROM workspace.test02_streaming.dim_store
    WHERE macro_region IS NULL
       OR NOT (
        (country_code IN ('IT', 'FR', 'DE', 'ES', 'NL', 'BE', 'AT', 'PT', 'SE') AND macro_region = 'EUROPE')
        OR (country_code = 'US' AND macro_region = 'AMERICAS')
        OR (country_code IN ('CN', 'JP', 'KR') AND macro_region = 'ASIA')
    )

    UNION ALL

    -- Duplicate natural keys
    SELECT
        'DUPLICATE_STORE_IDS',
        0,
        COUNT(*)
    FROM (
        SELECT store_id
        FROM workspace.test02_streaming.dim_store
        GROUP BY store_id
        HAVING COUNT(*) > 1
    ) duplicates

    UNION ALL

    -- Missing mandatory attributes
    SELECT
        'NULL_MANDATORY_ATTRIBUTES',
        0,
        COUNT(*)
    FROM workspace.test02_streaming.dim_store
    WHERE store_id IS NULL
       OR store_name IS NULL
       OR country_code IS NULL
       OR country_name IS NULL
       OR city IS NULL
       OR timezone_id IS NULL
       OR is_active IS NULL
       OR created_at IS NULL

    UNION ALL

    -- Invalid country codes
    SELECT
        'INVALID_COUNTRY_CODES',
        0,
        COUNT(*)
    FROM workspace.test02_streaming.dim_store
    WHERE LENGTH(country_code) <> 2

    UNION ALL

    -- Timezone mapping by country
    SELECT
        'INVALID_COUNTRY_TIMEZONE',
        0,
        COUNT(*)
    FROM workspace.test02_streaming.dim_store
    WHERE NOT (
        (country_code = 'IT' AND timezone_id = 'Europe/Rome')
        OR (country_code = 'FR' AND timezone_id = 'Europe/Paris')
        OR (country_code = 'DE' AND timezone_id = 'Europe/Berlin')
        OR (country_code = 'ES' AND timezone_id = 'Europe/Madrid')
        OR (country_code = 'NL' AND timezone_id = 'Europe/Amsterdam')
        OR (country_code = 'BE' AND timezone_id = 'Europe/Brussels')
        OR (country_code = 'AT' AND timezone_id = 'Europe/Vienna')
        OR (country_code = 'PT' AND timezone_id = 'Europe/Lisbon')
        OR (country_code = 'SE' AND timezone_id = 'Europe/Stockholm')
        OR (country_code = 'US' AND timezone_id IN (
            'America/New_York',
            'America/Los_Angeles',
            'America/Chicago'
        ))
        OR (country_code = 'CN' AND timezone_id = 'Asia/Shanghai')
        OR (country_code = 'JP' AND timezone_id = 'Asia/Tokyo')
        OR (country_code = 'KR' AND timezone_id = 'Asia/Seoul')
    )
)

SELECT
    validation,
    expected_value,
    actual_value,
    CASE
        WHEN expected_value = actual_value THEN 'PASS'
        ELSE 'FAIL'
    END AS validation_status
FROM checks
ORDER BY validation;
