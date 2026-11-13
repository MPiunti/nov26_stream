
-- ============================================================
-- 08 - Create client dimension
-- Target: workspace.test02_streaming.dim_client
--
-- Registered clients, identified by their natural client_id
-- (no surrogate key). Rules: doc/client.md.
-- Idempotent. Then run 09_populate_dim_client.sql.
-- ============================================================

CREATE TABLE IF NOT EXISTS workspace.test02_streaming.dim_client
(
    client_id STRING NOT NULL
        COMMENT 'Natural, personal identifier of the registered client, e.g. CL-IT-0000001; primary key',

    country_code STRING NOT NULL
        COMMENT 'ISO 3166-1 alpha-2 country where the client is registered; clients buy in stores of this country',

    macro_region STRING NOT NULL
        COMMENT 'Macro region of the client country: EUROPE, AMERICAS or ASIA',

    registration_date DATE NOT NULL
        COMMENT 'Date the client registered',

    is_active BOOLEAN NOT NULL
        COMMENT 'Indicates whether the client is currently active',

    created_at TIMESTAMP NOT NULL
        COMMENT 'Record creation timestamp',

    CONSTRAINT pk_dim_client
        PRIMARY KEY (client_id)
)
USING DELTA
COMMENT 'Dimension of registered (synthetic) clients; natural key client_id';
