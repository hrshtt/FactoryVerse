-- This script must be run in each factoryverse_N database
-- It will be applied to the template, so all instance DBs get these tables

\c factoryverse_template

SET search_path TO factoryverse, public;

-- Core entity table (from ComponentSchema.entity)
CREATE TABLE IF NOT EXISTS map_entities (
    unit_number BIGINT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    force TEXT,
    direction SMALLINT,
    direction_name TEXT,
    orientation REAL,
    orientation_name TEXT,
    electric_network_id BIGINT,
    recipe TEXT,
    position_x REAL NOT NULL,
    position_y REAL NOT NULL,
    tile_width SMALLINT,
    tile_height SMALLINT,
    bounding_box_min_x REAL,
    bounding_box_min_y REAL,
    bounding_box_max_x REAL,
    bounding_box_max_y REAL,
    chunk_x INTEGER NOT NULL,
    chunk_y INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Inserter component table
CREATE TABLE IF NOT EXISTS map_inserters (
    unit_number BIGINT PRIMARY KEY REFERENCES map_entities(unit_number) ON DELETE CASCADE,
    pickup_target_unit BIGINT REFERENCES map_entities(unit_number),
    drop_target_unit BIGINT REFERENCES map_entities(unit_number),
    pickup_position_x REAL,
    pickup_position_y REAL,
    drop_position_x REAL,
    drop_position_y REAL,
    chunk_x INTEGER NOT NULL,
    chunk_y INTEGER NOT NULL
);

-- Belt component table
CREATE TABLE IF NOT EXISTS map_belts (
    unit_number BIGINT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    direction SMALLINT,
    direction_name TEXT,
    belt_neighbours_json JSONB,
    belt_to_ground_type TEXT,
    underground_neighbour_unit BIGINT,
    position_x REAL NOT NULL,
    position_y REAL NOT NULL,
    chunk_x INTEGER NOT NULL,
    chunk_y INTEGER NOT NULL
);

-- Pipe component table
CREATE TABLE IF NOT EXISTS map_pipes (
    unit_number BIGINT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    direction SMALLINT,
    direction_name TEXT,
    pipe_neighbours_json JSONB,
    position_x REAL NOT NULL,
    position_y REAL NOT NULL,
    chunk_x INTEGER NOT NULL,
    chunk_y INTEGER NOT NULL
);

-- Resources table (from ComponentSchema.resources)
CREATE TABLE IF NOT EXISTS map_resources (
    x INTEGER NOT NULL,
    y INTEGER NOT NULL,
    kind TEXT NOT NULL,
    amount REAL NOT NULL,
    PRIMARY KEY (x, y, kind)
);

-- Rocks table
CREATE TABLE IF NOT EXISTS map_rocks (
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    resource_json JSONB,
    size SMALLINT,
    position_x REAL NOT NULL,
    position_y REAL NOT NULL,
    chunk_x INTEGER NOT NULL,
    chunk_y INTEGER NOT NULL,
    PRIMARY KEY (position_x, position_y)
);

-- Trees table
CREATE TABLE IF NOT EXISTS map_trees (
    name TEXT NOT NULL,
    position_x REAL NOT NULL,
    position_y REAL NOT NULL,
    bounding_box_min_x REAL,
    bounding_box_min_y REAL,
    bounding_box_max_x REAL,
    bounding_box_max_y REAL,
    chunk_x INTEGER NOT NULL,
    chunk_y INTEGER NOT NULL,
    PRIMARY KEY (position_x, position_y)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_map_entities_chunk ON map_entities(chunk_x, chunk_y);
CREATE INDEX IF NOT EXISTS idx_map_entities_type ON map_entities(type);
CREATE INDEX IF NOT EXISTS idx_map_entities_position ON map_entities(position_x, position_y);
CREATE INDEX IF NOT EXISTS idx_map_resources_kind ON map_resources(kind);
