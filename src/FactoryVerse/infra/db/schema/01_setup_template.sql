-- Setup the factoryverse_template database
-- This script runs in the factoryverse_template database context

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS file_fdw;

-- Set schema
CREATE SCHEMA IF NOT EXISTS factoryverse;
SET search_path TO factoryverse, public;

-- Metadata table to track snapshot state
CREATE TABLE IF NOT EXISTS snapshot_metadata (
    id SERIAL PRIMARY KEY,
    snapshot_type TEXT NOT NULL, -- 'map', 'recurring', 'ondemand'
    tick BIGINT NOT NULL,
    surface TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    file_count INTEGER,
    record_count INTEGER
);

CREATE INDEX IF NOT EXISTS idx_snapshot_metadata_type_tick ON snapshot_metadata(snapshot_type, tick DESC);
