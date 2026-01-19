-- control.lua: Entry point for fv_placement_hints mod
-- Registers remote interfaces for spatial reasoning queries
--
-- This mod provides placement validation and connection solving that replicates
-- what human players see when placing entities (green/red tiles, valid directions).
-- All queries are read-only - no game state mutations.

local RemoteInterface = require("RemoteInterface")

-- ============================================================================
-- REMOTE INTERFACE REGISTRATION
-- ============================================================================

local function register_remote_interface()
    local interface_name = "placement_hints"

    -- Remove existing interface if present (for hot reload)
    if remote.interfaces[interface_name] then
        log("Removing existing '" .. interface_name .. "' interface")
        remote.remove_interface(interface_name)
    end

    local interface = RemoteInterface.get_interface()

    local method_count = 0
    for _ in pairs(interface) do method_count = method_count + 1 end
    log("Registering '" .. interface_name .. "' interface with " .. method_count .. " methods")

    remote.add_interface(interface_name, interface)
end

-- ============================================================================
-- LIFECYCLE CALLBACKS
-- ============================================================================

script.on_init(function()
    log("fv_placement_hints on_init")
    register_remote_interface()
end)

script.on_load(function()
    log("fv_placement_hints on_load")
    -- Re-register interface on reload (interfaces are cleared)
    register_remote_interface()
end)

script.on_configuration_changed(function()
    log("fv_placement_hints on_configuration_changed")
end)
