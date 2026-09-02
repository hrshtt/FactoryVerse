"""What actually booted — asked of the running world, not inferred from a command line.

SCENARIO_BOOT_CONTRACT_DEFERRED.md Stage 0. A boot names a scenario, a seed and
a world policy; nothing in the command that launched it proves any of those
reached the engine. This module asks the engine. Every field is a live read;
none is derived from configuration.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol

# Repo scenario name -> the remote interface its control.lua registers.
# base freeplay registers "freeplay"; it is listed so a boot that loaded the
# engine's scenario instead of ours is named, not merely "unknown".
SCENARIO_CONTRACT_INTERFACES: Dict[str, str] = {
    "freeplay": "factoryverse_freeplay",
    "lab-grid": "lab_grid",
    "test-ground": "test_ground",
    "base/freeplay": "freeplay",
}

OBSERVER_SETTING = "fv-observer-spectator"

_PROBE_LUA = """
local interfaces = {}
for name, _ in pairs(remote.interfaces) do interfaces[#interfaces + 1] = name end
table.sort(interfaces)

local contract = nil
if remote.interfaces["factoryverse_freeplay"] then
    contract = remote.call("factoryverse_freeplay", "get_contract")
end

local surface = game.surfaces[1]
local mgs = surface.map_gen_settings
local control = mgs.autoplace_controls and mgs.autoplace_controls["enemy-base"]

local enemy_total, spawners, worms, units = 0, 0, 0, 0
for _, s in pairs(game.surfaces) do
    enemy_total = enemy_total + s.count_entities_filtered{force = "enemy"}
    spawners = spawners + s.count_entities_filtered{force = "enemy", type = "unit-spawner"}
    worms = worms + s.count_entities_filtered{force = "enemy", type = "turret"}
    units = units + s.count_entities_filtered{force = "enemy", type = "unit"}
end

local observer = nil
if remote.interfaces["spectator"] then
    observer = remote.call("spectator", "get_spectator_status")
end

-- Ingestion: chunks any non-enemy force has charted versus chunks the
-- snapshot mod is tracking. A world charted before the mod was added is
-- charted but not tracked (TRANSPORT_CONNECTIVITY_PLAN §13).
local charted = 0
for chunk in surface.get_chunks() do
    local seen = false
    for _, force in pairs(game.forces) do
        if force.name ~= "enemy" and force.name ~= "neutral"
            and force.is_chunk_charted(surface, {x = chunk.x, y = chunk.y}) then
            seen = true
            break
        end
    end
    if seen then charted = charted + 1 end
end
local ingestion = { charted_chunks = charted, tracked_chunks = nil, available = false }
if remote.interfaces["map"] then
    local ok, status = pcall(remote.call, "map", "get_snapshot_status")
    if ok and type(status) == "table" then
        ingestion.available = true
        ingestion.tracked_chunks = (status.completed_chunks or 0) + (status.pending_chunks or 0)
        ingestion.completed_chunks = status.completed_chunks
        ingestion.pending_chunks = status.pending_chunks
        ingestion.system_phase = status.system_phase
    end
end

return {
    tick = game.tick,
    interfaces = interfaces,
    contract = contract,
    world = {
        seed = mgs.seed,
        peaceful_mode = mgs.peaceful_mode,
        no_enemies_mode = mgs.no_enemies_mode,
        enemy_base = control and {
            frequency = control.frequency, size = control.size, richness = control.richness,
        } or nil,
        always_day = surface.always_day,
    },
    enemies = { total = enemy_total, spawners = spawners, worms = worms, units = units },
    observer = observer,
    ingestion = ingestion,
}
"""


class _LuaRunner(Protocol):
    def run_lua(self, code: str, *, safe: bool = ..., silent: bool = ...) -> Any: ...


def loaded_scenario(probe: Dict[str, Any]) -> Optional[str]:
    """Name the scenario whose contract interface is present, or None."""
    present = set(probe.get("interfaces") or [])
    # Ours first: base freeplay's "freeplay" interface is absent when ours
    # replaces it, so an unambiguous answer exists.
    for name, interface in SCENARIO_CONTRACT_INTERFACES.items():
        if name != "base/freeplay" and interface in present:
            return name
    if "freeplay" in present:
        return "base/freeplay"
    return None


def probe_boot(runner: _LuaRunner) -> Dict[str, Any]:
    """Ask the running world what booted. Adds ``loaded_scenario``."""
    result = runner.run_lua(_PROBE_LUA, safe=True, silent=True)
    if not isinstance(result, dict):
        raise RuntimeError(f"boot probe returned {result!r}, expected a table")
    result["loaded_scenario"] = loaded_scenario(result)
    return result


def boot_errors(
    probe: Dict[str, Any],
    *,
    expected_scenario: str,
    expect_no_enemies: bool = True,
) -> list[str]:
    """The conditions under which a boot is not the one that was asked for."""
    errors: list[str] = []
    loaded = probe.get("loaded_scenario")
    if loaded != expected_scenario:
        errors.append(
            f"loaded scenario is {loaded!r}, manifest names {expected_scenario!r} "
            f"(interfaces present: {probe.get('interfaces')})"
        )
    world = probe.get("world") or {}
    if expect_no_enemies:
        if world.get("no_enemies_mode") is not True:
            errors.append("no_enemies_mode is not set on the loaded surface")
        base = world.get("enemy_base") or {}
        if any(base.get(k) not in (0, 0.0) for k in ("frequency", "size")):
            errors.append(f"enemy-base autoplace is not zero: {base}")
        enemies = probe.get("enemies") or {}
        # Gate on combat entities; `total` counts every enemy-force entity,
        # including a non-combat character the harness may create on purpose.
        hostile = sum(int(enemies.get(k) or 0) for k in ("spawners", "worms", "units"))
        if hostile > 0:
            errors.append(f"hostile enemy entities exist: {enemies}")
    observer = probe.get("observer")
    if observer is None:
        errors.append("observer policy is unreadable: no 'spectator' remote interface")
    elif observer.get("enabled") is not True:
        errors.append(f"observer policy {OBSERVER_SETTING} is disabled")
    return errors
