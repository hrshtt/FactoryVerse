"""Phase 3B: the entity reference, the bounded wait, catalogs, and the honest craft bound.

Offline. Fakes stand in for RCON; the prototype dump is the real one.

Why these tests: API_AFFORDANCE_REDESIGN §2.2 makes one invariant load-bearing —
the reference exposes a strict subset of the real object's surface under
identical names. That is checked structurally below (`dir()` inclusion per
prototype family), so a method added on the reference without its twin on
the real entity fails here, not in a model's transcript.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from FactoryVerse.game.agent.entity_reference import (
    EntityReference,
    EntityReferenceAccessor,
    SourcedValue,
)
from FactoryVerse.game.factory.types import Direction, MapPosition


# --------------------------------------------------------------------------- fakes


class _Rcon:
    """Records commands; answers from a dict keyed by remote method name."""

    def __init__(self, answers=None, tick=1200):
        self.answers = answers or {}
        self.commands = []
        self.tick = tick

    def build_command(self, method, *args):
        self.commands.append((method, args))
        return json.dumps({"method": method, "args": [repr(a) for a in args]})

    def execute_and_parse_json(self, command):
        method = json.loads(command)["method"]
        answer = self.answers.get(method)
        if callable(answer):
            return answer()
        if answer is None:
            raise RuntimeError(f"no fake answer for {method}")
        return json.loads(json.dumps(answer))

    def execute(self, command, silent=True):
        if "game.tick" in command:
            self.tick += 30
            return str(self.tick)
        return ""


class _Entity:
    def __init__(self, name, x, y, direction=None):
        self.name = name
        self.position = MapPosition(x=x, y=y)
        self.direction = direction


# ----------------------------------------------------------------- the reference


def test_accessor_refuses_unknown_and_returns_a_reference():
    acc = EntityReferenceAccessor(None)
    with pytest.raises(ValueError):
        acc("not-an-entity-in-scope")
    ref = acc("small-electric-pole")
    assert isinstance(ref, EntityReference)
    assert ref.entity_type == "electric-pole"


def test_footprint_matches_the_real_entity_arithmetic():
    ref = EntityReference("stone-furnace")
    tiles = ref.footprint(MapPosition(x=10, y=10))
    assert tiles.source == "prototype"
    assert len(tiles) == 4  # 2x2
    assert {(t.x, t.y) for t in tiles} == {(9, 9), (10, 9), (9, 10), (10, 10)}
    # A 3x3 drill facing east is still 3x3; a 1x1 pole is one tile.
    assert len(EntityReference("electric-mining-drill").footprint(MapPosition(x=0.5, y=0.5), Direction.EAST)) == 9
    assert len(EntityReference("small-electric-pole").footprint(MapPosition(x=0.5, y=0.5))) == 1


def test_supply_area_and_covers_are_box_against_box_not_a_circle():
    pole = EntityReference("small-electric-pole")  # supply 2.5
    box = pole.supply_area(MapPosition(x=0, y=0))
    assert box.source == "prototype"
    # A 3x3 drill whose centre is 4 tiles away on the diagonal: its corner
    # is inside the 2.5 square (box overlap) though its centre is outside
    # any 2.5 circle. The circle test (placement_hints L1414) says False;
    # the engine says True (TRANSPORT §8.4).
    drill = _Entity("electric-mining-drill", 3.5, 3.5)
    assert pole.covers(MapPosition(x=0, y=0), drill).value is True
    far = _Entity("electric-mining-drill", 6.5, 0)
    assert pole.covers(MapPosition(x=0, y=0), far).value is False
    with pytest.raises(AttributeError):
        EntityReference("stone-furnace").supply_area(MapPosition(x=0, y=0))


def test_wire_reach_is_the_smaller_of_the_two_prototypes():
    small = EntityReference("small-electric-pole")  # 7.5
    other_small = _Entity("small-electric-pole", 7, 0)
    assert small.wire_reach(MapPosition(x=0, y=0), other_small).value is True
    assert small.wire_reach(MapPosition(x=0, y=0), _Entity("small-electric-pole", 8, 0)).value is False


def test_drop_position_rotates_the_prototype_vector():
    drill = EntityReference("burner-mining-drill")  # vector (-0.5, -1.3)
    north = drill.drop_position(MapPosition(x=0, y=0), Direction.NORTH).value
    east = drill.drop_position(MapPosition(x=0, y=0), Direction.EAST).value
    assert (north.x, north.y) == (-0.5, -1.3)
    assert (round(east.x, 3), round(east.y, 3)) == (1.3, -0.5)
    assert drill.drop_position(MapPosition(x=0, y=0)).source == "prototype"


def test_placements_between_returns_zero_candidates_as_data_with_reason():
    rcon = _Rcon()
    # PlacementHintsClient uses rcon.execute with a pcall wrapper; feed it JSON.
    rcon.execute = lambda cmd, silent=True: json.dumps({"positions": [], "error": "gap too large: 6 > 2"})
    ref = EntityReference("inserter", rcon)
    answer = ref.placements_between(_Entity("wooden-chest", 0.5, 0.5), _Entity("stone-furnace", 7, 0.5))
    assert answer.source == "live"
    assert answer["positions"] == []
    assert "gap too large" in answer["reason"]


def test_can_place_reads_the_engine_and_says_so():
    rcon = _Rcon()
    rcon.execute = lambda cmd, silent=True: json.dumps({"valid": True})
    ok = EntityReference("wooden-chest", rcon).can_place(MapPosition(x=1.5, y=1.5))
    assert ok.value is True and ok.source == "live"
    with pytest.raises(RuntimeError):
        EntityReference("wooden-chest").can_place(MapPosition(x=1.5, y=1.5))


@pytest.mark.parametrize(
    "prototype, real_class_path",
    [
        ("small-electric-pole", "FactoryVerse.game.factory.entity.implementations.electric_pole:ElectricPole"),
        ("inserter", "FactoryVerse.game.factory.entity.implementations.inserter:Inserter"),
        ("burner-inserter", "FactoryVerse.game.factory.entity.implementations.inserter:BurnerInserter"),
        ("burner-mining-drill", "FactoryVerse.game.factory.entity.implementations.mining_drill:BurnerMiningDrill"),
        ("electric-mining-drill", "FactoryVerse.game.factory.entity.implementations.mining_drill:ElectricMiningDrill"),
        ("offshore-pump", "FactoryVerse.game.factory.entity.implementations.pump:OffshorePump"),
        ("stone-furnace", "FactoryVerse.game.factory.entity.base_entity:BaseEntity"),
    ],
)
def test_reference_surface_is_a_subset_of_the_real_class_under_identical_names(prototype, real_class_path):
    """Constitution §6 / API §2.2: one vocabulary with a capability gate."""
    import importlib

    module, cls_name = real_class_path.split(":")
    real = getattr(importlib.import_module(module), cls_name)
    ref = EntityReference(prototype)
    family_methods = {
        "electric-pole": {"supply_area", "covers", "wire_reach"},
        "inserter": {"placements_between"},
        "mining-drill": {"drop_position"},
        "offshore-pump": {"sites"},
    }.get(ref.entity_type, set())
    generic = {"footprint", "can_place", "prototype", "tile_width", "tile_height"}
    applicable = generic | family_methods
    real_names = set(dir(real))
    missing = sorted(n for n in applicable if n not in real_names)
    assert not missing, f"{prototype}: reference names with no twin on {cls_name}: {missing}"
    # And nothing on the reference is a verb that changes the world.
    for forbidden in ("place", "place_ghost", "pickup", "build", "remove", "rotate", "set_recipe"):
        assert not hasattr(ref, forbidden)


# ------------------------------------------------------------------- await_item


def _inventory(counts, queue):
    from FactoryVerse.game.agent.embodied_actions.inventory import AgentInventory
    from FactoryVerse.game.agent.embodied_actions.crafting import CraftingAction

    state = {"counts": dict(counts), "queue": list(queue), "polls": 0}

    def items():
        state["polls"] += 1
        # The craft "finishes" on the third poll.
        if state["polls"] >= 3 and state["queue"]:
            for q in state["queue"]:
                state["counts"][q["recipe"]] = state["counts"].get(q["recipe"], 0) + q["count"]
            state["queue"] = []
        return [{"name": k, "count": v, "quality": "normal"} for k, v in state["counts"].items() if v > 0]

    rcon = _Rcon({
        "get_inventory_items": items,
        "get_crafting_queue": lambda: {"queue": list(state["queue"]), "queue_size": len(state["queue"]), "progress": 0.0},
    })
    inv = AgentInventory(rcon, placement=None)
    inv._attach_crafting(CraftingAction(rcon, async_listener=None))
    return inv, state


def test_await_item_returns_at_once_when_held():
    inv, _ = _inventory({"iron-plate": 10}, [])
    r = asyncio.run(inv.await_item("iron-plate", 5))
    assert r and r.reason == "already_held" and r.waited_ticks == 0


def test_await_item_refuses_to_wait_for_something_nothing_produces():
    inv, state = _inventory({}, [])
    r = asyncio.run(inv.await_item("iron-gear-wheel", 5, timeout_ticks=6000))
    assert not r and r.well_founded is False and r.reason == "nothing_producing_it"
    assert state["polls"] <= 2  # the check and the returned stacks; no waiting


def test_await_item_waits_then_returns_actuals_on_arrival():
    inv, _ = _inventory({}, [{"recipe": "iron-gear-wheel", "count": 5, "index": 1}])
    r = asyncio.run(inv.await_item("iron-gear-wheel", 5, timeout_ticks=6000, poll_seconds=0.001))
    assert r and r.reason == "arrived" and r.have == 5 and r.well_founded


def test_await_item_returns_actuals_at_the_bound_without_raising():
    inv, state = _inventory({"iron-gear-wheel": 2}, [{"recipe": "iron-gear-wheel", "count": 5, "index": 1}])
    # Never let the craft finish: keep the queue forever.
    state["polls"] = -10_000
    r = asyncio.run(inv.await_item("iron-gear-wheel", 5, timeout_ticks=60, poll_seconds=0.001))
    assert not r and r.reason == "bound_reached" and r.have == 2 and r.remaining_in_queue == 5
    assert r.waited_ticks >= 60


# --------------------------------------------------------------------- catalogs


def test_list_technologies_annotates_availability_and_unlocks():
    from FactoryVerse.game.agent.embodied_actions.research import ResearchAction

    techs = [
        {"name": "automation", "researched": True, "prerequisites": {}, "effects": [{"type": "unlock-recipe", "recipe": "assembling-machine-1"}],
         "research_unit_ingredients": [{"name": "automation-science-pack", "amount": 1}], "research_unit_count": 10, "research_unit_energy": 10},
        {"name": "logistics", "researched": False, "prerequisites": {}, "effects": [], "research_unit_ingredients": [], "research_unit_count": 20, "research_unit_energy": 15},
        {"name": "electronics", "researched": False, "prerequisites": {"automation": "automation"}, "effects": []},
        {"name": "fast-inserter", "researched": False, "prerequisites": {"electronics": "electronics"}, "effects": []},
    ]
    rcon = _Rcon({"get_technologies": techs})
    r = ResearchAction(rcon)
    available = {t["name"] for t in r.list_technologies(available=True)}
    assert available == {"logistics", "electronics"}  # fast-inserter's prerequisite is unresearched
    done = r.list_technologies(researched=True)
    assert done[0]["name"] == "automation" and done[0]["unlocks"] == ["assembling-machine-1"]
    assert done[0]["science_packs"] == {"automation-science-pack": 1}
    assert [t["name"] for t in r.list_technologies(name_filter="inserter")] == ["fast-inserter"]
    assert rcon.commands and rcon.commands[0][0] == "get_technologies"  # a read, never enqueue_research


def test_research_dequeue_is_caller_scoped():
    from FactoryVerse.game.agent.embodied_actions.research import ResearchAction

    state = {"current": "automation", "cancelled": []}
    rcon = _Rcon({
        "enqueue_research": {"success": True, "technology": "logistics"},
        "get_research_status": lambda: {"queued": False, "active": True, "progress": 0.1, "status": "x", "tick": 1, "current_research": state["current"]},
        "cancel_current_research": lambda: (state["cancelled"].append(state["current"]) or {"success": True, "cancelled_technology": state["current"]}),
    })
    r = ResearchAction(rcon)
    # Someone else's research is active: refuse as data, cancel nothing.
    refused = r.dequeue()
    assert refused["success"] is False and refused["game_rule_failure"] and refused["current_research"] == "automation"
    assert state["cancelled"] == []
    # force=True cancels anyway.
    assert r.dequeue(force=True)["success"] is True and state["cancelled"] == ["automation"]
    # Research I enqueued myself can be cancelled without force.
    r.enqueue("logistics")
    state["current"] = "logistics"
    assert r.dequeue()["success"] is True and state["cancelled"][-1] == "logistics"


def test_list_recipes_marks_hand_craftable_and_craftable_now():
    from FactoryVerse.game.agent.embodied_actions.crafting import CraftingAction

    recipes = [
        {"name": "iron-gear-wheel", "category": "crafting", "energy": 0.5, "ingredients": [{"name": "iron-plate", "amount": 2}]},
        {"name": "iron-plate", "category": "smelting", "energy": 3.2, "ingredients": [{"name": "iron-ore", "amount": 1}]},
        {"name": "transport-belt", "category": "crafting", "energy": 0.5, "ingredients": [{"name": "iron-plate", "amount": 1}, {"name": "iron-gear-wheel", "amount": 1}]},
    ]
    rcon = _Rcon({"get_recipes": recipes, "get_inventory_items": [{"name": "iron-plate", "count": 2, "quality": "normal"}]})
    c = CraftingAction(rcon, async_listener=None)
    by_name = {r["name"]: r for r in c.list_recipes()}
    assert by_name["iron-plate"]["hand_craftable"] is False  # smelting is machine-only
    assert by_name["iron-gear-wheel"]["hand_craftable"] is True and by_name["iron-gear-wheel"]["craftable_now"] is True
    assert by_name["transport-belt"]["craftable_now"] is False  # no gear on hand
    assert [r["name"] for r in c.list_recipes(hand_craftable=False)] == ["iron-plate"]


# ------------------------------------------------------ predictions and the bound


def test_enqueue_records_a_derived_prediction_and_the_report_hook_takes_it():
    from FactoryVerse.game.agent.embodied_actions.crafting import CraftingAction

    rcon = _Rcon({
        "craft_enqueue": {"success": True, "queued": True, "count_queued": 4, "recipe": "iron-gear-wheel"},
        "get_crafting_queue": {"queue": [{"recipe": "iron-gear-wheel", "count": 4, "index": 1}], "queue_size": 1, "progress": 0.0},
    }, tick=1000)
    c = CraftingAction(rcon, async_listener=None)
    out = c.enqueue("iron-gear-wheel", 4)
    pred = out["prediction"]
    assert pred["per_craft_ticks"] == 30.0  # 0.5 s at speed 1
    assert pred["ticks_until_done"] == 120
    assert pred["predicted_completion_tick"] > 1000
    taken = c.take_predictions()
    assert len(taken) == 1 and taken[0].recipe == "iron-gear-wheel" and taken[0].count == 4
    assert c.take_predictions() == []  # cleared


# ---------------------------------------------------------- entity-side mirrors


def test_entity_status_is_live_symbolic_and_sourced():
    from FactoryVerse.game.factory.entity.base_entity import BaseEntity, LiveStatus

    class _Ops:
        _rcon = None

        def inspect_entity(self, name, position):
            return {"status": 53, "tick": 777}  # NO_FUEL in 2.0

    e = BaseEntity("stone-furnace", MapPosition(x=1, y=1), entity_ops=_Ops(), place_ops=None, walking_action=None)
    s = e.status
    assert isinstance(s, LiveStatus) and s == "no_fuel" and s.value == 53 and s.source == "live:777"
    ghost = BaseEntity("stone-furnace", MapPosition(x=1, y=1), entity_ops=_Ops(), place_ops=None, walking_action=None, is_ghost=True)
    assert ghost.status == "ghost"


def test_container_set_limit_uses_the_engine_verb_directly():
    from FactoryVerse.game.factory.entity.implementations.container import WoodenChest

    rcon = _Rcon({"set_inventory_limit": {"success": True, "limit": 4}})

    class _Ops:
        _rcon = rcon

    chest = WoodenChest("wooden-chest", MapPosition(x=2.5, y=2.5), entity_ops=_Ops(), place_ops=None, walking_action=None)
    chest._view = chest._view.__class__.REACHABLE
    assert chest.set_limit(4)["limit"] == 4
    method, args = rcon.commands[-1]
    assert method == "set_inventory_limit" and args[0] == "wooden-chest" and args[2] == "chest" and args[3] == 4


def test_docs_registry_teaches_the_new_surface():
    from FactoryVerse.utils.docs.registry import get_registry, reset_registry
    from FactoryVerse.utils.docs.reference import register_all_documentation

    reset_registry()
    register_all_documentation()
    reg = get_registry()
    accessors = {c.accessor_name for c in reg.get_all_classes()}
    assert "entity_reference" in accessors
    for key in ("AgentInventory.await_item", "CraftingAction.list_recipes", "ResearchAction.list_technologies",
                "EntityReference.covers", "BaseEntity.status", "Container.set_limit"):
        cls, m = key.split(".")
        assert reg.get_method(cls, m) is not None, key
