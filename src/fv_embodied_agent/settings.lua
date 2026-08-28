data:extend({
    {
        type = "bool-setting",
        name = "fv-embodied-agent-enable-admin-api",
        setting_type = "runtime-global",
        default_value = true,  -- Default enabled for testing
        order = "a",
        localised_name = "Enable Admin API",
        localised_description = "Enable admin API for testing. Provides remote interface methods to manipulate agent state for testing purposes."
    },
    {
        -- The observer policy. A human who joins a world this mod runs in is
        -- made a spectator: no character, cannot alter the world, can look at
        -- everything. Runtime-global so it can be switched off for a session
        -- (e.g. the interactive REPL where a human is meant to play) and
        -- toggled later without a restart. Agents are bare characters with
        -- no LuaPlayer, so they are never affected.
        type = "bool-setting",
        name = "fv-observer-spectator",
        setting_type = "runtime-global",
        default_value = true,
        order = "b",
        localised_name = "Joining humans are spectators",
        localised_description = "When enabled, any human who joins is switched to the spectator controller and their character is destroyed. They can see everything and change nothing. Disable to let humans play with a character."
    }
})
