-- FactoryVerse freeplay scenario — a thin world-shaper.
--
-- This REPLACES base freeplay rather than wrapping it: no crash site, no
-- cutscene, no starter kit (Tier 4 injects the agent's inventory), and no
-- rocket-launch win condition. Whether a freeplay campaign has a win
-- condition is undecided (SCENARIO_BOOT_CONTRACT_DEFERRED.md §8 gates);
-- nothing here pretends to answer it.
--
-- The observer policy (joining humans become non-embodied spectators) is
-- owned by fv_embodied_agent behind the `fv-observer-spectator` setting, so
-- it also covers checkpoint-resumed worlds whose scenario script was baked
-- at creation. The scenario sets no controller.
--
-- `factoryverse_freeplay.get_contract` is how a boot proves which script it
-- loaded. Bump CONTRACT_VERSION when the shape of this world changes.

local CONTRACT_VERSION = 2

remote.add_interface("factoryverse_freeplay", {
    get_contract = function()
        return {
            name = "freeplay",
            version = CONTRACT_VERSION,
            replaces_base_freeplay = true,
            permanent_daylight = true,
            starter_kit = "tier4",
            win_condition = "undecided",
        }
    end,
})

local function enable_permanent_daylight(surface)
    if surface and surface.valid then
        surface.always_day = true
    end
end

local function enable_permanent_daylight_everywhere()
    for _, surface in pairs(game.surfaces) do
        enable_permanent_daylight(surface)
    end
end

script.on_init(enable_permanent_daylight_everywhere)
script.on_configuration_changed(enable_permanent_daylight_everywhere)

script.on_event(defines.events.on_surface_created, function(event)
    enable_permanent_daylight(game.get_surface(event.surface_index))
end)
