
-- ============================================================
-- 02 - Populate Silver store dimension
-- Target: workspace.test02_streaming.dim_store
-- Expected records: 200
--
-- Distribution:
--   Italy             40   EUROPE
--   Other EU          60   EUROPE
--   United States     60   AMERICAS
--   China             14   ASIA
--   Japan             13   ASIA
--   South Korea       13   ASIA
--
-- Macro regions: EUROPE 100, AMERICAS 60, ASIA 40.
-- Full rules: doc/dataset.md, "Store dimension".
--
-- Idempotent execution: MERGE by natural store_id. New stores are
-- inserted; existing stores get macro_region filled or corrected.
-- ============================================================

MERGE INTO workspace.test02_streaming.dim_store AS target

USING (
    WITH city_allocation AS (

        SELECT *
        FROM VALUES

        -- ITALY: 40
        ('IT', 'Italy', 'MI', 'Milan', 'Lombardy', 'Europe/Rome', 12),
        ('IT', 'Italy', 'RM', 'Rome', 'Lazio', 'Europe/Rome', 10),
        ('IT', 'Italy', 'FI', 'Florence', 'Tuscany', 'Europe/Rome', 6),
        ('IT', 'Italy', 'VE', 'Venice', 'Veneto', 'Europe/Rome', 5),
        ('IT', 'Italy', 'TO', 'Turin', 'Piedmont', 'Europe/Rome', 4),
        ('IT', 'Italy', 'NA', 'Naples', 'Campania', 'Europe/Rome', 3),

        -- OTHER EU: 60
        ('FR', 'France', 'PA', 'Paris', 'Ile-de-France', 'Europe/Paris', 15),
        ('DE', 'Germany', 'BE', 'Berlin', 'Berlin', 'Europe/Berlin', 12),
        ('ES', 'Spain', 'MD', 'Madrid', 'Community of Madrid', 'Europe/Madrid', 10),
        ('NL', 'Netherlands', 'AM', 'Amsterdam', 'North Holland', 'Europe/Amsterdam', 8),
        ('BE', 'Belgium', 'BR', 'Brussels', 'Brussels-Capital', 'Europe/Brussels', 5),
        ('AT', 'Austria', 'VI', 'Vienna', 'Vienna', 'Europe/Vienna', 4),
        ('PT', 'Portugal', 'LI', 'Lisbon', 'Lisbon', 'Europe/Lisbon', 3),
        ('SE', 'Sweden', 'ST', 'Stockholm', 'Stockholm', 'Europe/Stockholm', 3),

        -- UNITED STATES: 60
        ('US', 'United States', 'NY', 'New York', 'New York', 'America/New_York', 15),
        ('US', 'United States', 'LA', 'Los Angeles', 'California', 'America/Los_Angeles', 12),
        ('US', 'United States', 'SF', 'San Francisco', 'California', 'America/Los_Angeles', 8),
        ('US', 'United States', 'CH', 'Chicago', 'Illinois', 'America/Chicago', 7),
        ('US', 'United States', 'MI', 'Miami', 'Florida', 'America/New_York', 6),
        ('US', 'United States', 'DA', 'Dallas', 'Texas', 'America/Chicago', 5),
        ('US', 'United States', 'SE', 'Seattle', 'Washington', 'America/Los_Angeles', 4),
        ('US', 'United States', 'BO', 'Boston', 'Massachusetts', 'America/New_York', 3),

        -- CHINA: 14
        ('CN', 'China', 'SH', 'Shanghai', 'Shanghai', 'Asia/Shanghai', 8),
        ('CN', 'China', 'BJ', 'Beijing', 'Beijing', 'Asia/Shanghai', 6),

        -- JAPAN: 13
        ('JP', 'Japan', 'TK', 'Tokyo', 'Tokyo', 'Asia/Tokyo', 8),
        ('JP', 'Japan', 'OS', 'Osaka', 'Osaka', 'Asia/Tokyo', 5),

        -- SOUTH KOREA: 13
        ('KR', 'South Korea', 'SE', 'Seoul', 'Seoul', 'Asia/Seoul', 9),
        ('KR', 'South Korea', 'BU', 'Busan', 'Busan', 'Asia/Seoul', 4)

        AS allocation (
            country_code,
            country_name,
            city_code,
            city,
            region,
            timezone_id,
            store_count
        )
    ),

    generated_stores AS (
        SELECT
            CONCAT(
                country_code, '-',
                city_code, '-',
                LPAD(CAST(shop_number AS STRING), 3, '0')
            ) AS store_id,

            CONCAT(
                'Retail Store ',
                city,
                ' ',
                LPAD(CAST(shop_number AS STRING), 3, '0')
            ) AS store_name,

            country_code,
            country_name,
            city,
            region,

            CASE
                WHEN country_code IN ('IT', 'FR', 'DE', 'ES', 'NL', 'BE', 'AT', 'PT', 'SE') THEN 'EUROPE'
                WHEN country_code IN ('US') THEN 'AMERICAS'
                WHEN country_code IN ('CN', 'JP', 'KR') THEN 'ASIA'
            END AS macro_region,

            timezone_id

        FROM city_allocation

        LATERAL VIEW EXPLODE(
            SEQUENCE(1, store_count)
        ) generated AS shop_number
    )

    SELECT * FROM generated_stores

) AS source

ON target.store_id = source.store_id

WHEN MATCHED AND NOT (target.macro_region <=> source.macro_region) THEN UPDATE SET
    target.macro_region = source.macro_region,
    target.updated_at = CURRENT_TIMESTAMP()

WHEN NOT MATCHED THEN INSERT (
    store_id,
    store_name,
    country_code,
    country_name,
    city,
    region,
    macro_region,
    timezone_id,
    is_active,
    created_at,
    updated_at
)
VALUES (
    source.store_id,
    source.store_name,
    source.country_code,
    source.country_name,
    source.city,
    source.region,
    source.macro_region,
    source.timezone_id,
    TRUE,
    CURRENT_TIMESTAMP(),
    CURRENT_TIMESTAMP()
);
