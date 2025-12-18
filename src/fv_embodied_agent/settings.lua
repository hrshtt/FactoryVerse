data:extend({
    {
        type = "bool-setting",
        name = "fv-embodied-agent-enable-admin-api",
        setting_type = "runtime-global",
        default_value = true,  -- Default enabled for testing
        order = "a",
        localised_name = "Enable Admin API",
        localised_description = "Enable admin API for testing. Provides remote interface methods to manipulate agent state for testing purposes."
    }
})
