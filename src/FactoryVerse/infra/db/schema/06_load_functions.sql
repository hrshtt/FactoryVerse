\c factoryverse_template

SET search_path TO factoryverse, public;

-- Function to load map snapshot from CSV files for a specific instance
CREATE OR REPLACE FUNCTION load_map_snapshot_from_csv(instance_id INTEGER)
RETURNS TABLE(table_name TEXT, rows_loaded BIGINT) AS $$
DECLARE
    snapshot_base TEXT;
    chunk_list TEXT[];
    chunk_path TEXT;
    csv_pattern TEXT;
    load_count BIGINT;
BEGIN
    snapshot_base := '/var/lib/factoryverse/snapshots/factorio_' || instance_id::TEXT;
    
    -- Truncate existing data
    TRUNCATE map_entities CASCADE;
    TRUNCATE map_belts CASCADE;
    TRUNCATE map_pipes CASCADE;
    TRUNCATE map_resources CASCADE;
    TRUNCATE map_rocks CASCADE;
    TRUNCATE map_trees CASCADE;
    
    -- Load entities from chunks
    EXECUTE format('
        COPY map_entities FROM PROGRAM ''find %s/chunks -name "entities-*.csv" -exec cat {} \; | tail -n +2''
        WITH (FORMAT csv)
    ', snapshot_base);
    
    GET DIAGNOSTICS load_count = ROW_COUNT;
    RETURN QUERY SELECT 'map_entities'::TEXT, load_count;
    
    -- Load inserters
    EXECUTE format('
        COPY map_inserters FROM PROGRAM ''find %s/chunks -name "inserters-*.csv" -exec cat {} \; | tail -n +2''
        WITH (FORMAT csv)
    ', snapshot_base);
    
    GET DIAGNOSTICS load_count = ROW_COUNT;
    RETURN QUERY SELECT 'map_inserters'::TEXT, load_count;
    
    -- Load belts
    EXECUTE format('
        COPY map_belts FROM PROGRAM ''find %s/chunks -name "entities_belts-*.csv" -exec cat {} \; | tail -n +2''
        WITH (FORMAT csv)
    ', snapshot_base);
    
    GET DIAGNOSTICS load_count = ROW_COUNT;
    RETURN QUERY SELECT 'map_belts'::TEXT, load_count;
    
    -- Load pipes
    EXECUTE format('
        COPY map_pipes FROM PROGRAM ''find %s/chunks -name "entities_pipes-*.csv" -exec cat {} \; | tail -n +2''
        WITH (FORMAT csv)
    ', snapshot_base);
    
    GET DIAGNOSTICS load_count = ROW_COUNT;
    RETURN QUERY SELECT 'map_pipes'::TEXT, load_count;
    
    -- Load resources
    EXECUTE format('
        COPY map_resources FROM PROGRAM ''find %s/chunks -name "resources-*.csv" -exec cat {} \; | tail -n +2''
        WITH (FORMAT csv)
    ', snapshot_base);
    
    GET DIAGNOSTICS load_count = ROW_COUNT;
    RETURN QUERY SELECT 'map_resources'::TEXT, load_count;
    
    -- Load rocks
    EXECUTE format('
        COPY map_rocks FROM PROGRAM ''find %s/chunks -name "rocks-*.csv" -exec cat {} \; | tail -n +2''
        WITH (FORMAT csv)
    ', snapshot_base);
    
    GET DIAGNOSTICS load_count = ROW_COUNT;
    RETURN QUERY SELECT 'map_rocks'::TEXT, load_count;
    
    -- Load trees
    EXECUTE format('
        COPY map_trees FROM PROGRAM ''find %s/chunks -name "trees-*.csv" -exec cat {} \; | tail -n +2''
        WITH (FORMAT csv)
    ', snapshot_base);
    
    GET DIAGNOSTICS load_count = ROW_COUNT;
    RETURN QUERY SELECT 'map_trees'::TEXT, load_count;
END;
$$ LANGUAGE plpgsql;

-- Helper function to initialize instance after creation
CREATE OR REPLACE FUNCTION init_factorio_instance(
    p_instance_id INTEGER,
    p_rcon_port INTEGER DEFAULT 27015
)
RETURNS void AS $$
BEGIN
    -- Set instance configuration
    INSERT INTO instance_config (instance_id, rcon_host, rcon_port)
    VALUES (p_instance_id, 'factorio_' || p_instance_id::TEXT, p_rcon_port)
    ON CONFLICT (instance_id) DO UPDATE
    SET rcon_host = EXCLUDED.rcon_host,
        rcon_port = EXCLUDED.rcon_port;
    
    -- Initialize recurring snapshot foreign tables
    PERFORM init_recurring_snapshots(p_instance_id);
    
    RAISE NOTICE 'Factorio instance % initialized', p_instance_id;
END;
$$ LANGUAGE plpgsql;
