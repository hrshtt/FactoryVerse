--- fv_snapshot/utils/forces.lua
--- Helper module for getting tracked forces across mods.
--- Uses remote interface to query agent forces from fv_embodied_agent.

local M = {}

--- Get all forces that should be tracked in snapshots.
--- Queries fv_embodied_agent via remote interface to get agent forces,
--- then combines with "player" force for comprehensive entity tracking.
--- @return table Array of force names (e.g., {"player", "agent-1", "cell_0"})
function M.get_tracked_forces()
    local forces = {"player"}
    local seen = {player = true}

    -- Query agent forces via remote interface
    -- fv_embodied_agent exposes list_agent_forces() which returns {agent_id -> force_name}
    if remote.interfaces.agent and remote.interfaces.agent.list_agent_forces then
        local agent_forces = remote.call("agent", "list_agent_forces")
        if agent_forces then
            for _, force_name in pairs(agent_forces) do
                if force_name and not seen[force_name] then
                    table.insert(forces, force_name)
                    seen[force_name] = true
                end
            end
        end
    end

    return forces
end

--- Check if a force is being tracked (player or any agent force)
--- @param force_name string Force name to check
--- @return boolean True if force is tracked
function M.is_tracked_force(force_name)
    if force_name == "player" then
        return true
    end

    -- Check if it's an agent force
    if remote.interfaces.agent and remote.interfaces.agent.list_agent_forces then
        local agent_forces = remote.call("agent", "list_agent_forces")
        if agent_forces then
            for _, tracked_force in pairs(agent_forces) do
                if tracked_force == force_name then
                    return true
                end
            end
        end
    end

    return false
end

return M
