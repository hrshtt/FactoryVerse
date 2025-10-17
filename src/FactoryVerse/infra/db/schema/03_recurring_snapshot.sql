-- This creates the foreign table structure in the template
-- Each instance will have its own foreign tables pointing to its CSV files

\c factoryverse_template

SET search_path TO factoryverse, public;

-- Create a function to initialize foreign tables for a specific instance
-- This will be called after database creation with the instance ID

CREATE OR REPLACE FUNCTION init_recurring_snapshots(instance_id INTEGER)
RETURNS void AS $$
DECLARE
    snapshot_path TEXT;
BEGIN
    snapshot_path := '/var/lib/factoryverse/snapshots/factorio_' || instance_id::TEXT;
    
    -- Create server if not exists
    EXECUTE format('
        CREATE SERVER IF NOT EXISTS factorio_csv_server FOREIGN DATA WRAPPER file_fdw
    ');
    
    -- Drop existing foreign tables if they exist
    DROP FOREIGN TABLE IF EXISTS recurring_entity_status;
    DROP FOREIGN TABLE IF EXISTS recurring_resource_yields;
    
    -- Entity status foreign table
    EXECUTE format('
        CREATE FOREIGN TABLE recurring_entity_status (
            unit_number BIGINT NOT NULL,
            status INTEGER,
            status_name TEXT,
            health REAL,
            tick BIGINT
        ) SERVER factorio_csv_server
        OPTIONS (
            filename %L,
            format ''csv'',
            header ''true''
        )
    ', snapshot_path || '/recurring/entity_status-*.csv');
    
    -- Resource yields foreign table
    EXECUTE format('
        CREATE FOREIGN TABLE recurring_resource_yields (
            x INTEGER NOT NULL,
            y INTEGER NOT NULL,
            kind TEXT NOT NULL,
            amount REAL NOT NULL,
            tick BIGINT
        ) SERVER factorio_csv_server
        OPTIONS (
            filename %L,
            format ''csv'',
            header ''true''
        )
    ', snapshot_path || '/recurring/resource_yields-*.csv');
    
    -- Helper view to join entity status with map entities
    CREATE OR REPLACE VIEW entity_status_current AS
    SELECT 
        e.unit_number,
        e.name,
        e.type,
        e.position_x,
        e.position_y,
        s.status,
        s.status_name,
        s.health,
        s.tick
    FROM map_entities e
    LEFT JOIN recurring_entity_status s ON e.unit_number = s.unit_number;
END;
$$ LANGUAGE plpgsql;
