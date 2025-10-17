-- Experiment Management Schema
-- This script creates the core experiment management tables in the template database
-- These tables will be available in all instance databases

-- Connect to the template database (created by 00_create_template.sql)
\c factoryverse_template

SET search_path TO factoryverse, public;

-- Experiments table - tracks each experiment session
CREATE TABLE IF NOT EXISTS experiments (
    experiment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_name TEXT NOT NULL,
    factorio_instance_id INTEGER NOT NULL,
    database_name TEXT NOT NULL,
    scenario TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'paused', 'completed', 'failed')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(experiment_name),
    UNIQUE(factorio_instance_id)
);

-- Agents table - tracks agents within experiments
CREATE TABLE IF NOT EXISTS agents (
    agent_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id UUID NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
    agent_name TEXT NOT NULL,
    notebook_path TEXT NOT NULL,
    jupyter_kernel_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'paused', 'stopped')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(experiment_id, agent_name)
);

-- Checkpoints table - tracks save points for experiments
CREATE TABLE IF NOT EXISTS checkpoints (
    checkpoint_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id UUID NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
    checkpoint_name TEXT,
    game_tick BIGINT NOT NULL,
    save_file_path TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    metadata JSONB
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_experiments_status ON experiments(status);
CREATE INDEX IF NOT EXISTS idx_experiments_instance ON experiments(factorio_instance_id);
CREATE INDEX IF NOT EXISTS idx_agents_experiment ON agents(experiment_id);
CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);
CREATE INDEX IF NOT EXISTS idx_checkpoints_experiment ON checkpoints(experiment_id);
CREATE INDEX IF NOT EXISTS idx_checkpoints_tick ON checkpoints(experiment_id, game_tick DESC);

-- Helper functions for experiment management
CREATE OR REPLACE FUNCTION create_experiment(
    p_experiment_name TEXT,
    p_factorio_instance_id INTEGER,
    p_database_name TEXT,
    p_scenario TEXT
) RETURNS UUID AS $$
DECLARE
    v_experiment_id UUID;
BEGIN
    INSERT INTO experiments (experiment_name, factorio_instance_id, database_name, scenario, status)
    VALUES (p_experiment_name, p_factorio_instance_id, p_database_name, p_scenario, 'running')
    RETURNING experiment_id INTO v_experiment_id;
    
    RETURN v_experiment_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION add_agent(
    p_experiment_id UUID,
    p_agent_name TEXT,
    p_notebook_path TEXT
) RETURNS UUID AS $$
DECLARE
    v_agent_id UUID;
BEGIN
    INSERT INTO agents (experiment_id, agent_name, notebook_path, status)
    VALUES (p_experiment_id, p_agent_name, p_notebook_path, 'running')
    RETURNING agent_id INTO v_agent_id;
    
    RETURN v_agent_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION save_checkpoint(
    p_experiment_id UUID,
    p_checkpoint_name TEXT,
    p_game_tick BIGINT,
    p_save_file_path TEXT,
    p_metadata JSONB DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
    v_checkpoint_id UUID;
BEGIN
    INSERT INTO checkpoints (experiment_id, checkpoint_name, game_tick, save_file_path, metadata)
    VALUES (p_experiment_id, p_checkpoint_name, p_game_tick, p_save_file_path, p_metadata)
    RETURNING checkpoint_id INTO v_checkpoint_id;
    
    RETURN v_checkpoint_id;
END;
$$ LANGUAGE plpgsql;

-- View for experiment summary
CREATE OR REPLACE VIEW experiment_summary AS
SELECT 
    e.experiment_id,
    e.experiment_name,
    e.factorio_instance_id,
    e.database_name,
    e.scenario,
    e.status,
    e.created_at,
    e.updated_at,
    COUNT(a.agent_id) as agent_count,
    STRING_AGG(a.agent_name, ', ' ORDER BY a.agent_name) as agent_names
FROM experiments e
LEFT JOIN agents a ON e.experiment_id = a.experiment_id
GROUP BY e.experiment_id, e.experiment_name, e.factorio_instance_id, e.database_name, e.scenario, e.status, e.created_at, e.updated_at;
