-- Runtime settings for fv_snapshot mod
-- These can be configured via remote interface or mod settings

data:extend({
    {
        type = "int-setting",
        name = "fv-snapshot-udp-port",
        setting_type = "runtime-global",
        default_value = 34400,
        minimum_value = 1024,
        maximum_value = 65535,
        order = "a",
        localised_name = "Snapshot UDP Port",
        localised_description = "UDP port for snapshot notifications. Each server instance should use a unique port."
    }
})

