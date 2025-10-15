-- Experiment Management Schema for FactoryVerse
-- Tracks experiments, agent state, and checkpoints for multi-agent Factorio gameplay

-- Enable necessary extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "postgis";

-- ============================================================================
-- Experiments Table
-- ============================================================================
-- Tracks the lifecycle of experiments (agent-server pairings)
CREATE TABLE IF NOT EXISTS experiments (
    experiment_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id TEXT NOT NULL,

    -- Factorio server instance this experiment is running on
    server_instance_id TEXT NOT NULL,
    server_rcon_port INTEGER,
    server_game_port INTEGER,

    -- Experiment configuration
    scenario TEXT NOT NULL DEFAULT 'factorio_verse',
    mode TEXT NOT NULL CHECK (mode IN ('scenario', 'save-based')),

    -- Current state
    status TEXT NOT NULL DEFAULT 'initializing'
        CHECK (status IN ('initializing', 'running', 'paused', 'completed', 'failed')),
    current_tick BIGINT DEFAULT 0,

    -- Notebook tracking
    notebook_path TEXT,
    kernel_id TEXT,

    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,

    -- Unique constraint: one active experiment per agent at a time
    CONSTRAINT unique_active_agent UNIQUE (agent_id, status)
        DEFERRABLE INITIALLY DEFERRED
);

-- Index for finding active experiments
CREATE INDEX IF NOT EXISTS idx_experiments_status ON experiments(status);
CREATE INDEX IF NOT EXISTS idx_experiments_agent_id ON experiments(agent_id);
CREATE INDEX IF NOT EXISTS idx_experiments_server ON experiments(server_instance_id);

-- Update trigger for updated_at
CREATE OR REPLACE FUNCTION update_experiments_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER experiments_updated_at_trigger
    BEFORE UPDATE ON experiments
    FOR EACH ROW
    EXECUTE FUNCTION update_experiments_updated_at();

-- ============================================================================
-- Agent State Table
-- ============================================================================
-- Stores serialized agent state (notebook variables, history, etc.)
CREATE TABLE IF NOT EXISTS agent_state (
    state_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    experiment_id UUID NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,

    -- Game tick when this state was captured
    game_tick BIGINT NOT NULL,

    -- Serialized agent variables and episode history
    -- We use JSONB for efficient querying, but store hex-encoded dill for complex objects
    agent_variables JSONB DEFAULT '{}'::jsonb,
    episode_history JSONB DEFAULT '{}'::jsonb,

    -- Optional: store raw pickled state for objects that don't serialize to JSON
    raw_state BYTEA,

    -- Metadata
    state_size_bytes INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),

    -- Constraint: one state per experiment per tick
    CONSTRAINT unique_experiment_tick UNIQUE (experiment_id, game_tick)
);

-- Indexes for efficient state lookup
CREATE INDEX IF NOT EXISTS idx_agent_state_experiment ON agent_state(experiment_id);
CREATE INDEX IF NOT EXISTS idx_agent_state_tick ON agent_state(game_tick);
CREATE INDEX IF NOT EXISTS idx_agent_state_created ON agent_state(created_at DESC);

-- ============================================================================
-- Checkpoints Table
-- ============================================================================
-- Links Factorio save files with agent state snapshots
CREATE TABLE IF NOT EXISTS checkpoints (
    checkpoint_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    experiment_id UUID NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,

    -- Game state
    game_tick BIGINT NOT NULL,
    factorio_save_path TEXT NOT NULL,

    -- Agent state reference
    agent_state_id UUID REFERENCES agent_state(state_id) ON DELETE SET NULL,

    -- Snapshot references (optional - links to snapshot data)
    resource_snapshot_tick BIGINT,
    entities_snapshot_tick BIGINT,

    -- Checkpoint metadata
    checkpoint_type TEXT DEFAULT 'manual'
        CHECK (checkpoint_type IN ('manual', 'auto', 'milestone')),
    description TEXT,

    -- Storage
    save_file_size_bytes BIGINT,

    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for checkpoint queries
CREATE INDEX IF NOT EXISTS idx_checkpoints_experiment ON checkpoints(experiment_id);
CREATE INDEX IF NOT EXISTS idx_checkpoints_tick ON checkpoints(game_tick);
CREATE INDEX IF NOT EXISTS idx_checkpoints_created ON checkpoints(created_at DESC);

-- ============================================================================
-- Experiment Metrics Table (Optional - for tracking agent performance)
-- ============================================================================
CREATE TABLE IF NOT EXISTS experiment_metrics (
    metric_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    experiment_id UUID NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,

    -- Metric metadata
    game_tick BIGINT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value NUMERIC,
    metric_json JSONB,

    created_at TIMESTAMP DEFAULT NOW(),

    -- Allow multiple metrics per tick
    CONSTRAINT unique_experiment_tick_metric UNIQUE (experiment_id, game_tick, metric_name)
);

CREATE INDEX IF NOT EXISTS idx_metrics_experiment ON experiment_metrics(experiment_id);
CREATE INDEX IF NOT EXISTS idx_metrics_name ON experiment_metrics(metric_name);
CREATE INDEX IF NOT EXISTS idx_metrics_tick ON experiment_metrics(game_tick);

-- ============================================================================
-- Snapshot Links Table
-- ============================================================================
-- Links experiments to raw snapshot data (resources, entities, etc.)
-- This allows queries like "get all snapshots for experiment X"
CREATE TABLE IF NOT EXISTS experiment_snapshots (
    experiment_id UUID NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
    snapshot_tick BIGINT NOT NULL,
    snapshot_type TEXT NOT NULL CHECK (snapshot_type IN ('resource', 'entities', 'water', 'crude')),

    -- Metadata about the snapshot
    snapshot_path TEXT,
    loaded_at TIMESTAMP DEFAULT NOW(),

    PRIMARY KEY (experiment_id, snapshot_tick, snapshot_type)
);

CREATE INDEX IF NOT EXISTS idx_exp_snapshots_experiment ON experiment_snapshots(experiment_id);
CREATE INDEX IF NOT EXISTS idx_exp_snapshots_tick ON experiment_snapshots(snapshot_tick);

-- ============================================================================
-- Helper Views
-- ============================================================================

-- View: Latest state per experiment
CREATE OR REPLACE VIEW latest_agent_state AS
SELECT DISTINCT ON (experiment_id)
    experiment_id,
    state_id,
    game_tick,
    agent_variables,
    episode_history,
    created_at
FROM agent_state
ORDER BY experiment_id, game_tick DESC;

-- View: Latest checkpoint per experiment
CREATE OR REPLACE VIEW latest_checkpoint AS
SELECT DISTINCT ON (experiment_id)
    experiment_id,
    checkpoint_id,
    game_tick,
    factorio_save_path,
    agent_state_id,
    checkpoint_type,
    created_at
FROM checkpoints
ORDER BY experiment_id, game_tick DESC;

-- View: Experiment summary with latest state and checkpoint
CREATE OR REPLACE VIEW experiment_summary AS
SELECT
    e.experiment_id,
    e.agent_id,
    e.server_instance_id,
    e.status,
    e.current_tick,
    e.scenario,
    e.mode,
    e.created_at,
    e.updated_at,
    las.game_tick AS latest_state_tick,
    las.state_id AS latest_state_id,
    lc.game_tick AS latest_checkpoint_tick,
    lc.checkpoint_id AS latest_checkpoint_id,
    lc.factorio_save_path AS latest_save_path
FROM experiments e
LEFT JOIN latest_agent_state las ON e.experiment_id = las.experiment_id
LEFT JOIN latest_checkpoint lc ON e.experiment_id = lc.experiment_id;

-- ============================================================================
-- Helper Functions
-- ============================================================================

-- Function: Create new experiment with initialized state
CREATE OR REPLACE FUNCTION create_experiment(
    p_agent_id TEXT,
    p_server_instance_id TEXT,
    p_scenario TEXT DEFAULT 'factorio_verse',
    p_mode TEXT DEFAULT 'scenario',
    p_notebook_path TEXT DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
    v_experiment_id UUID;
BEGIN
    INSERT INTO experiments (
        agent_id,
        server_instance_id,
        scenario,
        mode,
        notebook_path,
        status
    ) VALUES (
        p_agent_id,
        p_server_instance_id,
        p_scenario,
        p_mode,
        p_notebook_path,
        'running'
    ) RETURNING experiment_id INTO v_experiment_id;

    -- Initialize agent state at tick 0
    INSERT INTO agent_state (
        experiment_id,
        game_tick,
        agent_variables,
        episode_history
    ) VALUES (
        v_experiment_id,
        0,
        '{}'::jsonb,
        '{"actions": [], "observations": [], "rewards": []}'::jsonb
    );

    RETURN v_experiment_id;
END;
$$ LANGUAGE plpgsql;

-- Function: Save checkpoint (links Factorio save with agent state)
CREATE OR REPLACE FUNCTION save_checkpoint(
    p_experiment_id UUID,
    p_game_tick BIGINT,
    p_factorio_save_path TEXT,
    p_checkpoint_type TEXT DEFAULT 'manual',
    p_description TEXT DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
    v_checkpoint_id UUID;
    v_agent_state_id UUID;
BEGIN
    -- Get the most recent agent state for this tick or earlier
    SELECT state_id INTO v_agent_state_id
    FROM agent_state
    WHERE experiment_id = p_experiment_id
      AND game_tick <= p_game_tick
    ORDER BY game_tick DESC
    LIMIT 1;

    -- Create checkpoint
    INSERT INTO checkpoints (
        experiment_id,
        game_tick,
        factorio_save_path,
        agent_state_id,
        checkpoint_type,
        description
    ) VALUES (
        p_experiment_id,
        p_game_tick,
        p_factorio_save_path,
        v_agent_state_id,
        p_checkpoint_type,
        p_description
    ) RETURNING checkpoint_id INTO v_checkpoint_id;

    -- Update experiment current tick
    UPDATE experiments
    SET current_tick = p_game_tick,
        updated_at = NOW()
    WHERE experiment_id = p_experiment_id;

    RETURN v_checkpoint_id;
END;
$$ LANGUAGE plpgsql;

-- Function: Restore experiment from checkpoint
CREATE OR REPLACE FUNCTION get_checkpoint_data(
    p_checkpoint_id UUID
) RETURNS TABLE (
    experiment_id UUID,
    agent_id TEXT,
    game_tick BIGINT,
    factorio_save_path TEXT,
    agent_variables JSONB,
    episode_history JSONB,
    scenario TEXT,
    mode TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        e.experiment_id,
        e.agent_id,
        c.game_tick,
        c.factorio_save_path,
        COALESCE(a.agent_variables, '{}'::jsonb) AS agent_variables,
        COALESCE(a.episode_history, '{}'::jsonb) AS episode_history,
        e.scenario,
        e.mode
    FROM checkpoints c
    JOIN experiments e ON c.experiment_id = e.experiment_id
    LEFT JOIN agent_state a ON c.agent_state_id = a.state_id
    WHERE c.checkpoint_id = p_checkpoint_id;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- Comments
-- ============================================================================
COMMENT ON TABLE experiments IS 'Tracks agent-server experiment lifecycle';
COMMENT ON TABLE agent_state IS 'Stores serialized agent state (notebook variables, episode history)';
COMMENT ON TABLE checkpoints IS 'Links Factorio save files with agent state for restore';
COMMENT ON TABLE experiment_metrics IS 'Optional metrics tracking for agent performance analysis';
COMMENT ON TABLE experiment_snapshots IS 'Links experiments to raw snapshot data';
COMMENT ON FUNCTION create_experiment IS 'Creates new experiment with initialized agent state';
COMMENT ON FUNCTION save_checkpoint IS 'Saves checkpoint linking Factorio save with agent state';
COMMENT ON FUNCTION get_checkpoint_data IS 'Retrieves all data needed to restore experiment from checkpoint';
