
-- ============================================================
-- 09 - Populate client dimension
-- Target: workspace.test02_warehouse.dim_client
--
-- 500 registered clients per store of each country, so 100,000
-- distinct clients for the 200 stores (IT 20,000 ... SE 1,500).
-- client_id = CL-<country_code>-<7-digit number>.
-- Needs dim_store with macro_region (run 01 and 02 first).
--
-- Idempotent: MERGE by natural client_id, insert only.
-- Rules: doc/client.md.
-- ============================================================

MERGE INTO workspace.test02_warehouse.dim_client AS target

USING (
    WITH per_country AS (
        SELECT
            country_code,
            macro_region,
            COUNT(*) * 500 AS client_count
        FROM workspace.test02_warehouse.dim_store
        GROUP BY country_code, macro_region
    )

    SELECT
        CONCAT('CL-', country_code, '-', LPAD(CAST(client_number AS STRING), 7, '0')) AS client_id,
        country_code,
        macro_region,
        -- Spread registrations over 2020-2025 (2,191 days), deterministically.
        DATE_ADD(DATE'2020-01-01', CAST(PMOD(client_number * 37, 2191) AS INT)) AS registration_date
    FROM per_country
    LATERAL VIEW EXPLODE(SEQUENCE(1, CAST(client_count AS INT))) generated AS client_number
) AS source

ON target.client_id = source.client_id

WHEN NOT MATCHED THEN INSERT (
    client_id,
    country_code,
    macro_region,
    registration_date,
    is_active,
    created_at
)
VALUES (
    source.client_id,
    source.country_code,
    source.macro_region,
    source.registration_date,
    TRUE,
    CURRENT_TIMESTAMP()
);
