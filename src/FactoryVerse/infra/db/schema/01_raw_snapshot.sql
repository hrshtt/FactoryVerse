-- FactoryVerse Database Schema
-- Generated from EntitiesSnapshot.lua and ResourceSnapshot.lua table structures
-- This file is mounted to the PostgreSQL container for automatic schema creation

-- Enable PostGIS extension for spatial data
CREATE EXTENSION IF NOT EXISTS postgis;

-- Create schema for FactoryVerse data
CREATE SCHEMA IF NOT EXISTS factoryverse;

-- Set search path to include factoryverse schema
SET search_path TO factoryverse, public;

-- ============================================================================
-- ENTITIES TABLES (from EntitiesSnapshot.lua)
-- ============================================================================

-- Main entities table - base entity information
CREATE TABLE IF NOT EXISTS entities (
    unit_number BIGINT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    pos_x DOUBLE PRECISION NOT NULL,
    pos_y DOUBLE PRECISION NOT NULL,
    direction INTEGER,
    direction_name TEXT,
    orientation DOUBLE PRECISION,
    orientation_name TEXT,
    chunk_x INTEGER NOT NULL,
    chunk_y INTEGER NOT NULL,
    health DOUBLE PRECISION,
    status INTEGER,
    status_name TEXT,
    bbox_min_x DOUBLE PRECISION,
    bbox_min_y DOUBLE PRECISION,
    bbox_max_x DOUBLE PRECISION,
    bbox_max_y DOUBLE PRECISION,
    selection_box_min_x DOUBLE PRECISION,
    selection_box_min_y DOUBLE PRECISION,
    selection_box_max_x DOUBLE PRECISION,
    selection_box_max_y DOUBLE PRECISION,
    train_id BIGINT,
    train_state INTEGER,
    electric_network_id BIGINT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Entities crafting table - for assembling machines, furnaces, etc.
CREATE TABLE IF NOT EXISTS entities_crafting (
    unit_number BIGINT PRIMARY KEY REFERENCES entities(unit_number) ON DELETE CASCADE,
    recipe TEXT,
    crafting_progress DOUBLE PRECISION,
    chunk_x INTEGER NOT NULL,
    chunk_y INTEGER NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Entities burner table - for entities with fuel consumption
CREATE TABLE IF NOT EXISTS entities_burner (
    unit_number BIGINT PRIMARY KEY REFERENCES entities(unit_number) ON DELETE CASCADE,
    remaining_burning_fuel DOUBLE PRECISION,
    currently_burning TEXT,
    inventories JSONB, -- Stores fuel and burnt result inventories as JSON
    chunk_x INTEGER NOT NULL,
    chunk_y INTEGER NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Entities inventory table - for entities with item storage
CREATE TABLE IF NOT EXISTS entities_inventory (
    unit_number BIGINT PRIMARY KEY REFERENCES entities(unit_number) ON DELETE CASCADE,
    inventories JSONB, -- Stores all inventory contents as JSON
    chunk_x INTEGER NOT NULL,
    chunk_y INTEGER NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Entities fluids table - for entities with fluid storage
CREATE TABLE IF NOT EXISTS entities_fluids (
    unit_number BIGINT PRIMARY KEY REFERENCES entities(unit_number) ON DELETE CASCADE,
    fluids JSONB, -- Stores fluid contents as JSON array
    chunk_x INTEGER NOT NULL,
    chunk_y INTEGER NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Entities inserter table - for inserter-specific data
CREATE TABLE IF NOT EXISTS entities_inserter (
    unit_number BIGINT PRIMARY KEY REFERENCES entities(unit_number) ON DELETE CASCADE,
    pickup_position_x DOUBLE PRECISION,
    pickup_position_y DOUBLE PRECISION,
    drop_position_x DOUBLE PRECISION,
    drop_position_y DOUBLE PRECISION,
    pickup_target_unit BIGINT,
    drop_target_unit BIGINT,
    chunk_x INTEGER NOT NULL,
    chunk_y INTEGER NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Entities belts table - for transport belt data
CREATE TABLE IF NOT EXISTS entities_belts (
    unit_number BIGINT PRIMARY KEY REFERENCES entities(unit_number) ON DELETE CASCADE,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    pos_x DOUBLE PRECISION NOT NULL,
    pos_y DOUBLE PRECISION NOT NULL,
    direction INTEGER,
    direction_name TEXT,
    item_lines JSONB, -- Stores transport line contents as JSON
    belt_neighbours JSONB, -- Stores belt neighbor relationships as JSON
    belt_to_ground_type TEXT,
    underground_neighbour_unit BIGINT,
    chunk_x INTEGER NOT NULL,
    chunk_y INTEGER NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- RESOURCE TABLES (from ResourceSnapshot.lua)
-- ============================================================================

-- Resource tiles table - for resource deposits and water tiles
CREATE TABLE IF NOT EXISTS resource_tiles (
    id BIGSERIAL PRIMARY KEY,
    kind TEXT NOT NULL, -- Resource name or 'water'
    x INTEGER NOT NULL,
    y INTEGER NOT NULL,
    amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    chunk_x INTEGER NOT NULL,
    chunk_y INTEGER NOT NULL,
    surface_id INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Resource rocks table - for rock entities
CREATE TABLE IF NOT EXISTS resource_rocks (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    x INTEGER NOT NULL,
    y INTEGER NOT NULL,
    size_hint INTEGER NOT NULL,
    chunk_x INTEGER NOT NULL,
    chunk_y INTEGER NOT NULL,
    surface_id INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- INDEXES FOR PERFORMANCE
-- ============================================================================

-- Spatial indexes for position-based queries
CREATE INDEX IF NOT EXISTS idx_entities_position ON entities USING GIST (ST_Point(pos_x, pos_y));
CREATE INDEX IF NOT EXISTS idx_entities_chunk ON entities (chunk_x, chunk_y);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities (type);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities (name);

-- Resource tile indexes
CREATE INDEX IF NOT EXISTS idx_resource_tiles_position ON resource_tiles USING GIST (ST_Point(x, y));
CREATE INDEX IF NOT EXISTS idx_resource_tiles_chunk ON resource_tiles (chunk_x, chunk_y);
CREATE INDEX IF NOT EXISTS idx_resource_tiles_kind ON resource_tiles (kind);
CREATE INDEX IF NOT EXISTS idx_resource_tiles_amount ON resource_tiles (amount);

-- Resource rocks indexes
CREATE INDEX IF NOT EXISTS idx_resource_rocks_position ON resource_rocks USING GIST (ST_Point(x, y));
CREATE INDEX IF NOT EXISTS idx_resource_rocks_chunk ON resource_rocks (chunk_x, chunk_y);
CREATE INDEX IF NOT EXISTS idx_resource_rocks_name ON resource_rocks (name);

-- Component table indexes
CREATE INDEX IF NOT EXISTS idx_entities_crafting_chunk ON entities_crafting (chunk_x, chunk_y);
CREATE INDEX IF NOT EXISTS idx_entities_burner_chunk ON entities_burner (chunk_x, chunk_y);
CREATE INDEX IF NOT EXISTS idx_entities_inventory_chunk ON entities_inventory (chunk_x, chunk_y);
CREATE INDEX IF NOT EXISTS idx_entities_fluids_chunk ON entities_fluids (chunk_x, chunk_y);
CREATE INDEX IF NOT EXISTS idx_entities_inserter_chunk ON entities_inserter (chunk_x, chunk_y);
CREATE INDEX IF NOT EXISTS idx_entities_belts_chunk ON entities_belts (chunk_x, chunk_y);

-- JSONB indexes for efficient querying of structured data
CREATE INDEX IF NOT EXISTS idx_entities_burner_inventories ON entities_burner USING GIN (inventories);
CREATE INDEX IF NOT EXISTS idx_entities_inventory_inventories ON entities_inventory USING GIN (inventories);
CREATE INDEX IF NOT EXISTS idx_entities_fluids_fluids ON entities_fluids USING GIN (fluids);
CREATE INDEX IF NOT EXISTS idx_entities_belts_item_lines ON entities_belts USING GIN (item_lines);
CREATE INDEX IF NOT EXISTS idx_entities_belts_belt_neighbours ON entities_belts USING GIN (belt_neighbours);

-- ============================================================================
-- VIEWS FOR COMMON QUERIES
-- ============================================================================

-- View combining all entity data with spatial information
CREATE OR REPLACE VIEW entities_with_position AS
SELECT 
    e.*,
    ST_Point(e.pos_x, e.pos_y) AS position,
    ST_Point(e.bbox_min_x, e.bbox_min_y) AS bbox_min,
    ST_Point(e.bbox_max_x, e.bbox_max_y) AS bbox_max,
    ST_Point(e.selection_box_min_x, e.selection_box_min_y) AS selection_box_min,
    ST_Point(e.selection_box_max_x, e.selection_box_max_y) AS selection_box_max
FROM entities e;

-- View for resource tiles with spatial data
CREATE OR REPLACE VIEW resource_tiles_with_position AS
SELECT 
    rt.*,
    ST_Point(rt.x, rt.y) AS position
FROM resource_tiles rt;

-- View for resource rocks with spatial data
CREATE OR REPLACE VIEW resource_rocks_with_position AS
SELECT 
    rr.*,
    ST_Point(rr.x, rr.y) AS position
FROM resource_rocks rr;

-- ============================================================================
-- FUNCTIONS FOR DATA MANAGEMENT
-- ============================================================================

-- Function to update the updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply the update trigger to all tables with updated_at columns
CREATE TRIGGER update_entities_updated_at BEFORE UPDATE ON entities FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_entities_crafting_updated_at BEFORE UPDATE ON entities_crafting FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_entities_burner_updated_at BEFORE UPDATE ON entities_burner FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_entities_inventory_updated_at BEFORE UPDATE ON entities_inventory FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_entities_fluids_updated_at BEFORE UPDATE ON entities_fluids FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_entities_inserter_updated_at BEFORE UPDATE ON entities_inserter FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_entities_belts_updated_at BEFORE UPDATE ON entities_belts FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_resource_tiles_updated_at BEFORE UPDATE ON resource_tiles FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_resource_rocks_updated_at BEFORE UPDATE ON resource_rocks FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- GRANTS AND PERMISSIONS
-- ============================================================================

-- Grant permissions to the factoryverse user
GRANT USAGE ON SCHEMA factoryverse TO factoryverse;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA factoryverse TO factoryverse;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA factoryverse TO factoryverse;
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA factoryverse TO factoryverse;

-- Grant permissions on future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA factoryverse GRANT ALL ON TABLES TO factoryverse;
ALTER DEFAULT PRIVILEGES IN SCHEMA factoryverse GRANT ALL ON SEQUENCES TO factoryverse;
ALTER DEFAULT PRIVILEGES IN SCHEMA factoryverse GRANT ALL ON FUNCTIONS TO factoryverse;

-- ============================================================================
-- COMMENTS FOR DOCUMENTATION
-- ============================================================================

COMMENT ON SCHEMA factoryverse IS 'FactoryVerse game data schema - stores Factorio entity and resource data';
COMMENT ON TABLE entities IS 'Main entities table containing all Factorio entities with their basic properties';
COMMENT ON TABLE entities_crafting IS 'Crafting entities (assembling machines, furnaces) with recipe and progress data';
COMMENT ON TABLE entities_burner IS 'Entities with fuel consumption (burners, furnaces) with fuel and inventory data';
COMMENT ON TABLE entities_inventory IS 'Entities with item storage capabilities and their inventory contents';
COMMENT ON TABLE entities_fluids IS 'Entities with fluid storage (tanks, pipes) and their fluid contents';
COMMENT ON TABLE entities_inserter IS 'Inserter entities with pickup/drop positions and target information';
COMMENT ON TABLE entities_belts IS 'Transport belt entities with item lines and neighbor relationships';
COMMENT ON TABLE resource_tiles IS 'Resource deposit tiles (ore, water) with position and yield amounts';
COMMENT ON TABLE resource_rocks IS 'Rock entities with position and size information';

COMMENT ON COLUMN entities.unit_number IS 'Unique Factorio entity identifier';
COMMENT ON COLUMN entities.pos_x IS 'X coordinate of entity position';
COMMENT ON COLUMN entities.pos_y IS 'Y coordinate of entity position';
COMMENT ON COLUMN entities.chunk_x IS 'Chunk X coordinate (32x32 tile chunks)';
COMMENT ON COLUMN entities.chunk_y IS 'Chunk Y coordinate (32x32 tile chunks)';

COMMENT ON COLUMN resource_tiles.kind IS 'Resource type name (e.g., iron-ore, copper-ore, water)';
COMMENT ON COLUMN resource_tiles.amount IS 'Resource yield amount (0 for water tiles)';
COMMENT ON COLUMN resource_rocks.size_hint IS 'Estimated rock size based on collision box dimensions';
