\c factoryverse_template

SET search_path TO factoryverse, public;

-- Placeholder for Multicorn FDW (to be implemented after schema setup)
-- The FDW will need to know which instance it's serving

-- Store instance configuration
CREATE TABLE IF NOT EXISTS instance_config (
    instance_id INTEGER PRIMARY KEY,
    rcon_host TEXT NOT NULL DEFAULT 'localhost',
    rcon_port INTEGER NOT NULL,
    rcon_password TEXT NOT NULL DEFAULT 'factorio',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- For now, create a regular table as placeholder for inventory data
CREATE TABLE IF NOT EXISTS ondemand_entity_inventory (
    unit_number BIGINT NOT NULL,
    tick BIGINT,
    inventories JSONB,
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (unit_number, fetched_at)
);

-- Future: Multicorn FDW will be created per instance
-- CREATE EXTENSION IF NOT EXISTS multicorn;
-- CREATE SERVER factorio_rcon_server FOREIGN DATA WRAPPER multicorn
-- OPTIONS (
--     wrapper 'factoryverse.fdw.EntityInventoryFDW',
--     rcon_host 'factorio_0',
--     rcon_port '27015'
-- );
