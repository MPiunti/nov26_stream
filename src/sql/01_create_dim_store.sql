
-- ============================================================
-- 01 - Create the warehouse schema and the store dimension
-- Target: workspace.test02_warehouse.dim_store
--
-- test02_warehouse holds the dimensions (natural keys only);
-- test02_streaming holds the streaming sources and pipeline tables.
-- See doc/warehouse.md. Idempotent. Then run 02_populate_dim_store.sql.
-- ============================================================

CREATE SCHEMA IF NOT EXISTS workspace.test02_warehouse
COMMENT 'Data warehouse dimensions (stores, clients, products), natural keys only';


CREATE TABLE IF NOT EXISTS workspace.test02_warehouse.dim_store
(
    store_id STRING NOT NULL
        COMMENT 'Natural business identifier of the store; primary key',

    store_name STRING NOT NULL
        COMMENT 'Official store name',

    country_code STRING NOT NULL
        COMMENT 'ISO 3166-1 alpha-2 country code',

    country_name STRING NOT NULL
        COMMENT 'Country name',

    city STRING NOT NULL
        COMMENT 'City where the store is located',

    region STRING
        COMMENT 'State, province or administrative region',

    macro_region STRING NOT NULL
        COMMENT 'Macro region derived from country_code: EUROPE, AMERICAS or ASIA',

    is_flagship BOOLEAN NOT NULL
        COMMENT 'Flagship store: more traffic and more visitors from abroad (doc/dataset.md)',

    timezone_id STRING NOT NULL
        COMMENT 'IANA timezone identifier',

    is_active BOOLEAN NOT NULL
        COMMENT 'Indicates whether the store is currently active',

    created_at TIMESTAMP NOT NULL
        COMMENT 'Record creation timestamp',

    updated_at TIMESTAMP
        COMMENT 'Last record update timestamp',

    CONSTRAINT pk_dim_store
        PRIMARY KEY (store_id)
)
USING DELTA
COMMENT 'Store dimension: global retail store master data; natural key store_id';
