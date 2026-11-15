
-- ============================================================
-- 02 - Populate the store dimension
-- Target: workspace.test02_warehouse.dim_store
-- Expected records: 213 (200 physical stores and 13 e-commerce stores)
--
-- Distribution:
--   Italy             40   EUROPE
--   Other EU          60   EUROPE
--   United States     60   AMERICAS
--   China             14   ASIA
--   Japan             13   ASIA
--   South Korea       13   ASIA
--
-- Macro regions (physical stores): EUROPE 100, AMERICAS 60, ASIA 40.
-- Flagships (is_flagship = TRUE, channel FLAGSHIP, own names):
--   IT-MI-001  Milan Galleria Vittorio Emanuele
--   US-NY-001  New York Fifth Avenue
-- Channels: FLAGSHIP 2, RETAIL 198 (the other physical stores),
--   ECOM 13: one e-commerce store per country, <country>-EC-001,
--   sales only, no people counting.
-- Full rules: doc/dataset.md, "Store dimension".
--
-- Idempotent execution: MERGE by natural store_id. New stores are
-- inserted; existing stores get store_name, macro_region,
-- is_flagship and channel filled or corrected.
-- ============================================================

MERGE INTO workspace.test02_warehouse.dim_store AS target

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

            CASE CONCAT(country_code, '-', city_code, '-', LPAD(CAST(shop_number AS STRING), 3, '0'))
                WHEN 'IT-MI-001' THEN 'Milan Galleria Vittorio Emanuele'
                WHEN 'US-NY-001' THEN 'New York Fifth Avenue'
                ELSE CONCAT('Retail Store ', city, ' ', LPAD(CAST(shop_number AS STRING), 3, '0'))
            END AS store_name,

            country_code,
            country_name,
            city,
            region,

            CONCAT(country_code, '-', city_code, '-', LPAD(CAST(shop_number AS STRING), 3, '0'))
                IN ('IT-MI-001', 'US-NY-001') AS is_flagship,

            timezone_id

        FROM city_allocation

        LATERAL VIEW EXPLODE(
            SEQUENCE(1, store_count)
        ) generated AS shop_number
    ),

    -- One e-commerce store per country: channel ECOM. It sells online only: no sensor, no people
    -- counting. Its time zone (the country's main one) gives the local time of its sales.
    ecom_stores AS (
        SELECT
            CONCAT(country_code, '-EC-001') AS store_id,
            CONCAT('E-commerce ', country_name) AS store_name,
            country_code,
            country_name,
            'Online' AS city,
            CAST(NULL AS STRING) AS region,
            FALSE AS is_flagship,
            timezone_id
        FROM VALUES
            ('IT', 'Italy', 'Europe/Rome'),
            ('FR', 'France', 'Europe/Paris'),
            ('DE', 'Germany', 'Europe/Berlin'),
            ('ES', 'Spain', 'Europe/Madrid'),
            ('NL', 'Netherlands', 'Europe/Amsterdam'),
            ('BE', 'Belgium', 'Europe/Brussels'),
            ('AT', 'Austria', 'Europe/Vienna'),
            ('PT', 'Portugal', 'Europe/Lisbon'),
            ('SE', 'Sweden', 'Europe/Stockholm'),
            ('US', 'United States', 'America/New_York'),
            ('CN', 'China', 'Asia/Shanghai'),
            ('JP', 'Japan', 'Asia/Tokyo'),
            ('KR', 'South Korea', 'Asia/Seoul')
        AS e (country_code, country_name, timezone_id)
    )

    SELECT
        s.*,

        CASE
            WHEN country_code IN ('IT', 'FR', 'DE', 'ES', 'NL', 'BE', 'AT', 'PT', 'SE') THEN 'EUROPE'
            WHEN country_code IN ('US') THEN 'AMERICAS'
            WHEN country_code IN ('CN', 'JP', 'KR') THEN 'ASIA'
        END AS macro_region,

        -- Sales channel: ECOM for the e-commerce stores, FLAGSHIP for the flagships, RETAIL otherwise.
        CASE
            WHEN store_id LIKE '%-EC-001' THEN 'ECOM'
            WHEN is_flagship THEN 'FLAGSHIP'
            ELSE 'RETAIL'
        END AS channel

    FROM (
        SELECT * FROM generated_stores
        UNION ALL
        SELECT * FROM ecom_stores
    ) s

) AS source

ON target.store_id = source.store_id

WHEN MATCHED AND NOT (
    target.macro_region <=> source.macro_region
    AND target.store_name <=> source.store_name
    AND target.is_flagship <=> source.is_flagship
    AND target.channel <=> source.channel
) THEN UPDATE SET
    target.store_name = source.store_name,
    target.macro_region = source.macro_region,
    target.is_flagship = source.is_flagship,
    target.channel = source.channel,
    target.updated_at = CURRENT_TIMESTAMP()

WHEN NOT MATCHED THEN INSERT (
    store_id,
    store_name,
    country_code,
    country_name,
    city,
    region,
    macro_region,
    is_flagship,
    channel,
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
    source.is_flagship,
    source.channel,
    source.timezone_id,
    TRUE,
    CURRENT_TIMESTAMP(),
    CURRENT_TIMESTAMP()
);
