"""Focused offline contracts for the Factorio-side reach and walking modules."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
LUA = shutil.which("lua")


def _run_lua(source: str) -> None:
    if LUA is None:
        pytest.skip("lua interpreter is unavailable")
    completed = subprocess.run(
        [LUA, "-"],
        input=source,
        text=True,
        check=False,
        cwd=REPO_ROOT,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr


def _lua_package_path() -> str:
    module_root = REPO_ROOT / "src" / "fv_embodied_agent"
    return f"{module_root}/?.lua;{module_root}/?/init.lua"


def test_reachable_snapshot_uses_boundary_candidates_and_engine_reach() -> None:
    """Center-outside targets survive the area prefilter iff Factorio can reach."""
    _run_lua(
        f"""
        package.path = {str(_lua_package_path())!r} .. ";" .. package.path
        defines = {{
            entity_status = {{}}, inventory = {{fuel = 1, chest = 2}},
            direction = {{
                north=0, northeast=1, east=2, southeast=3,
                south=4, southwest=5, west=6, northwest=7,
            }},
        }}
        game = {{tick = 17}}

        local Reachability = require("agent_actions.reachability")
        local tree = {{
            valid = true, reachable = true, name = "tree-01", type = "tree",
            position = {{x = 2.9, y = 0}},
            prototype = {{mineable_properties = {{products = {{}}}}}},
        }}
        local chest = {{
            valid = true, reachable = true, name = "wooden-chest", type = "container",
            position = {{x = 10.2, y = 0}},
            get_inventory = function(_) return nil end,
        }}
        local unreachable = {{
            valid = true, reachable = false, name = "steel-chest", type = "container",
            position = {{x = 9.8, y = 0}},
            get_inventory = function(_) return nil end,
        }}
        local surface = {{}}
        surface.find_entities_filtered = function(filter)
            assert(filter.radius == nil, "center-radius prefilter must not be used")
            assert(filter.area ~= nil, "boundary-overlap area is required")
            if filter.type == "tree" then return {{tree}} end
            if filter.type == "resource" or filter.type == "simple-entity" then return {{}} end
            return {{chest, unreachable}}
        end
        local character = {{
            valid = true, position = {{x = 0, y = 0}}, surface = surface,
            resource_reach_distance = 2.5, reach_distance = 10,
        }}
        character.can_reach_entity = function(entity) return entity.reachable end

        local result = Reachability.get_reachable({{character = character}}, false)
        assert(#result.resources == 1 and result.resources[1].name == "tree-01")
        assert(#result.entities == 1 and result.entities[1].name == "wooden-chest")
        """
    )


def test_completed_and_stale_walks_clear_all_owned_bookkeeping() -> None:
    """Physical completion and stop reconciliation both remove stale path ids."""
    _run_lua(
        f"""
        package.path = {str(_lua_package_path())!r} .. ";" .. package.path
        defines = {{direction = {{
            east=0, northeast=1, north=2, northwest=3,
            west=4, southwest=5, south=6, southeast=7,
        }}}}
        game = {{tick = 25}}

        local Walking = require("agent_actions.walking")
        local character = {{
            position = {{x = 4, y = 5}},
            walking_state = {{walking = false}},
        }}
        character.can_reach_entity = function(_) return true end
        local target = {{
            valid = true, type = "container", position = {{x = 5, y = 5}},
        }}
        local agent = {{
            agent_id = 1,
            character = character,
            walking = {{
                action_id = "walk-1", start_tick = 10, goal = {{x=4,y=5}},
                original_goal = {{x=4,y=5}}, path_id = 99,
                path = {{{{position={{x=4,y=5}}}}}}, progress = 2,
                goal_entity = target,
                entity_ref = {{name="wooden-chest"}}, approach_candidates = {{{{x=4,y=5}}}},
                approach_index = 1, path_options = {{force="player"}},
            }},
        }}
        agent.enqueue_message = function(_, payload, channel)
            assert(payload.status == "completed")
            assert(payload.interaction_reachable == true)
            assert(channel == "walking")
        end

        Walking.process_walking(agent)
        assert(agent.walking.action_id == nil)
        assert(agent.walking.path_id == nil)
        assert(agent.walking.entity_ref == nil)
        assert(agent.walking.approach_candidates == nil)
        assert(agent.walking.path_options == nil)
        assert(agent.walking.progress == 0 and #agent.walking.path == 0)
        assert(character.walking_state.walking == false)

        agent.walking.path_id = 101
        agent.walking.action_id = "stale-walk"
        local stopped = Walking.stop_walking(agent)
        assert(stopped.success == true)
        assert(agent.walking.path_id == nil and agent.walking.action_id == nil)
        assert(character.walking_state.walking == false)
        """
    )


def test_invalid_entity_target_fails_at_both_completion_branches() -> None:
    """A destroyed entity target can never fall through to walking success."""
    _run_lua(
        f"""
        package.path = {str(_lua_package_path())!r} .. ";" .. package.path
        defines = {{direction = {{
            east=0, northeast=1, north=2, northwest=3,
            west=4, southwest=5, south=6, southeast=7,
        }}}}
        game = {{tick = 40}}

        local Walking = require("agent_actions.walking")

        local function make_agent(progress)
            local character = {{
                position = {{x = 4, y = 5}},
                walking_state = {{walking = false}},
            }}
            character.can_reach_entity = function(_)
                error("invalid targets must not be passed to can_reach_entity")
            end
            local agent = {{
                agent_id = progress,
                character = character,
                walking = {{
                    action_id = "invalid-" .. progress,
                    start_tick = 10,
                    goal = {{x=4,y=5}},
                    original_goal = {{x=5,y=5}},
                    goal_entity = {{valid=false}},
                    last_distance_to_entity = 12,
                    path_id = 99,
                    path = {{{{position={{x=4,y=5}}}}}},
                    progress = progress,
                    entity_ref = {{name="wooden-chest"}},
                    approach_candidates = {{{{x=4,y=5}}}},
                    approach_index = 1,
                    path_options = {{force="player"}},
                }},
            }}
            agent.enqueue_message = function(_, payload, channel)
                assert(payload.success == false)
                assert(payload.status == "failed")
                assert(payload.failure_type == "entity_not_found")
                assert(payload.interaction_reachable == nil)
                assert(channel == "walking")
                agent.failure = payload
            end
            return agent
        end

        -- progress > #path enters the pre-waypoint completion branch.
        local exhausted = make_agent(2)
        Walking.process_walking(exhausted)
        assert(exhausted.failure ~= nil)
        assert(exhausted.walking.action_id == nil)
        assert(exhausted.walking.last_distance_to_entity == nil)
        assert(exhausted.walking.path_id == nil)
        assert(exhausted.walking.progress == 0 and #exhausted.walking.path == 0)

        -- progress == #path reaches the same terminal check after the waypoint.
        local final_waypoint = make_agent(1)
        Walking.process_walking(final_waypoint)
        assert(final_waypoint.failure ~= nil)
        assert(final_waypoint.walking.action_id == nil)
        assert(final_waypoint.walking.last_distance_to_entity == nil)
        assert(final_waypoint.walking.path_id == nil)
        assert(final_waypoint.walking.progress == 0 and #final_waypoint.walking.path == 0)
        """
    )
