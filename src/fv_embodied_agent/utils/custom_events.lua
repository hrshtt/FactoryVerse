--- Custom event definitions for fv_embodied_agent
--- Shared across mods for agent-related custom events
--- All events must be generated at module load time
--- Event IDs are stored in storage for cross-mod access

local M = {}

-- ============================================================================
-- AGENT CUSTOM EVENTS
-- ============================================================================

-- Agent lifecycle events
M.on_agent_created = script.generate_event_name()
M.on_agent_removed = script.generate_event_name()
M.on_chunk_charted = script.generate_event_name()

-- Agent entity operation events (for entity operations independent of actions)
-- These mirror in-game events but are raised by agent actions
M.on_agent_entity_built = script.generate_event_name()
M.on_agent_entity_destroyed = script.generate_event_name()
M.on_agent_entity_rotated = script.generate_event_name()
M.on_agent_entity_configuration_changed = script.generate_event_name()

-- ============================================================================
-- STORAGE INITIALIZATION
-- ============================================================================

--- Initialize custom events in storage for cross-mod access
--- This must be called from on_init/on_load event handlers (storage is not available at module load time)
--- This ensures FVSnapshot can access the same event IDs
function M.initialize_storage()
    if not storage.custom_events then
        storage.custom_events = {}
    end
    storage.custom_events.on_agent_created = M.on_agent_created
    storage.custom_events.on_agent_removed = M.on_agent_removed
    storage.custom_events.on_chunk_charted = M.on_chunk_charted
    storage.custom_events.on_agent_entity_built = M.on_agent_entity_built
    storage.custom_events.on_agent_entity_destroyed = M.on_agent_entity_destroyed
    storage.custom_events.on_agent_entity_rotated = M.on_agent_entity_rotated
    storage.custom_events.on_agent_entity_configuration_changed = M.on_agent_entity_configuration_changed
    log("Custom events storage initialized")
end

-- ============================================================================
-- REMOTE INTERFACE
-- ============================================================================

--- Register remote interface for custom events
--- Allows other mods (like FVSnapshot) to access event IDs via remote call
--- @return table Remote interface table
function M.register_remote_interface()
    local interface = {
        get_custom_events = function()
            -- Return from storage (source of truth) or fallback to module
            if storage.custom_events then
                return storage.custom_events
            end
            -- Fallback to module exports (shouldn't happen, but be safe)
            return M
        end
    }
    return interface
end

log("Custom events module initialized")

return M

