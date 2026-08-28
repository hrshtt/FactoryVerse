import asyncio
from types import SimpleNamespace

from FactoryVerse.evals.freeplay.supervisor import (
    FREEPLAY_GAME_SPEED,
    FreeplaySupervisor,
)


EXPECTED_MODS = {
    "base": "2.0.76",
    "fv_embodied_agent": "0.1.3",
    "fv_snapshot": "0.1.0",
    "fv_placement_hints": "0.1.0",
}


class _RemoteView:
    is_loaded = True
    sync_state = SimpleNamespace(
        is_running=True,
        last_sequence=0,
        needs_rebuild=False,
    )

    def state_fingerprint(self):
        return {"entity_count": 0, "entity_digest": "0", "last_sequence": 0}

    def execute_raw(self, query):
        if "QUALIFY row_number" in query:
            return [
                ("coal", 4.5, 5.5, 1000),
                ("copper-ore", 6.5, 7.5, 900),
                ("iron-ore", 8.5, 9.5, 800),
                ("stone", 10.5, 11.5, 700),
            ]
        if "FROM water_tile" in query and "LIMIT 1" in query:
            return [(12.0, 13.0)]
        if "power_networks" in query:
            return [(0,)]
        return [(1, 1, 0, 0)]


class _Tier3:
    def __init__(self, hostile_count):
        self.hostile_count = hostile_count
        self.lua = None

    def run_lua(self, source, **_kwargs):
        if "remote.interfaces" in source:
            # The Stage 0 boot probe: a world that booted the named scenario
            # with the observer policy on and nothing hostile in it.
            return {
                "tick": 100,
                "interfaces": ["agent", "factoryverse_freeplay", "map", "spectator"],
                "contract": {"name": "freeplay", "version": 2},
                "world": {
                    "seed": 44340,
                    "peaceful_mode": True,
                    "no_enemies_mode": True,
                    "enemy_base": {"frequency": 0, "size": 0, "richness": 0},
                    "always_day": True,
                },
                "enemies": {"total": 0, "spawners": 0, "worms": 0, "units": 0},
                "observer": {"enabled": True, "connected_players": []},
                "ingestion": {"available": True, "charted_chunks": 1, "tracked_chunks": 1},
            }
        self.lua = source
        return {
            "tick": 100,
            "tick_paused": False,
            "game_speed": FREEPLAY_GAME_SPEED,
            "enemy_base_frequency": 0,
            "enemy_base_size": 0,
            "no_enemies_mode": True,
            "peaceful_mode": True,
            # A broad enemy-force entity must not invalidate the campaign.
            "enemy_force_entity_count": 1,
            "hostile_combat_entity_count": self.hostile_count,
            "enemy_entity_present": self.hostile_count > 0,
            "actor_position": {"x": 1.0, "y": 2.0},
            "actor_inventory": {"wood": 1},
            "researched_technology_count": 0,
        }


def _supervisor(hostile_count):
    supervisor = object.__new__(FreeplaySupervisor)
    supervisor.store = SimpleNamespace(
        manifest=lambda: {
            "agent_id": "agent_1",
            "expected_active_mods": EXPECTED_MODS,
            "game_speed": FREEPLAY_GAME_SPEED,
        }
    )
    tier3 = _Tier3(hostile_count)
    supervisor.environment = SimpleNamespace(
        tier3=tier3,
        tier4=SimpleNamespace(remote_view=_RemoteView()),
    )
    return supervisor, tier3


def test_preflight_ignores_noncombat_enemy_force_entities():
    supervisor, tier3 = _supervisor(hostile_count=0)

    result = asyncio.run(supervisor._preflight(None, active_mods=EXPECTED_MODS))

    assert result["valid"] is True
    assert result["errors"] == []
    assert result["enemy_state"]["enemy_force_entity_count"] == 1
    assert 'type={"unit", "unit-spawner", "turret"}' in tier3.lua
    assert "pairs(game.surfaces)" in tier3.lua
    assert result["actor_state"]["position"] == {"x": 1.0, "y": 2.0}
    assert result["nearest_resources"]["iron-ore"]["position"] == {
        "x": 8.5,
        "y": 9.5,
    }
    assert result["nearest_water_tile"] == {
        "position": {"x": 12.0, "y": 13.0},
        "usage": "search_hint_only",
        "walk_target": False,
        "validated_offshore_pump_anchor": False,
        "required_next_call": "placement_hints.find_offshore_pump_sites",
        "required_walk_target": "site.approach_position",
    }


def test_preflight_rejects_biter_spawner_or_worm_entities():
    supervisor, _ = _supervisor(hostile_count=1)

    result = asyncio.run(supervisor._preflight(None, active_mods=EXPECTED_MODS))

    assert result["valid"] is False
    assert result["errors"] == [
        "hostile units, spawners, or turrets exist on a loaded surface"
    ]


def test_preflight_fails_loudly_when_hostile_count_is_missing():
    supervisor, tier3 = _supervisor(hostile_count=0)
    original_run_lua = tier3.run_lua

    def without_count(source, **kwargs):
        result = original_run_lua(source, **kwargs)
        result.pop("hostile_combat_entity_count", None)
        return result

    tier3.run_lua = without_count

    result = asyncio.run(supervisor._preflight(None, active_mods=EXPECTED_MODS))

    assert result["valid"] is False
    assert result["errors"] == [
        "hostile combat entity count is missing from preflight"
    ]


def test_preflight_rejects_unexpected_dlc_before_actor_runtime():
    supervisor, _ = _supervisor(hostile_count=0)
    active = {**EXPECTED_MODS, "space-age": "2.0.76"}

    result = asyncio.run(supervisor._preflight(None, active_mods=active))

    assert result["valid"] is False
    assert result["errors"] == ["unexpected active mods: space-age"]
    assert result["active_mods"] == active


def test_preflight_rejects_wrong_game_speed():
    supervisor, tier3 = _supervisor(hostile_count=0)
    original_run_lua = tier3.run_lua

    def at_wrong_speed(source, **kwargs):
        result = original_run_lua(source, **kwargs)
        if "remote.interfaces" not in source:
            result["game_speed"] = 1
        return result

    tier3.run_lua = at_wrong_speed

    result = asyncio.run(supervisor._preflight(None, active_mods=EXPECTED_MODS))

    assert result["valid"] is False
    assert result["errors"] == [
        "game speed does not match campaign manifest (1 != 8)"
    ]
