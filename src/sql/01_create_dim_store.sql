
-- ============================================================
-- 01 - Create Silver store dimension
-- Target: workspace.test02_streaming.dim_store
-- ============================================================

CREATE SCHEMA IF NOT EXISTS workspace.test02_streaming
COMMENT 'Silver layer for retail streaming data';


CREATE TABLE IF NOT EXISTS workspace.test02_streaming.dim_store
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
COMMENT 'Silver dimension containing global retail store master data';
