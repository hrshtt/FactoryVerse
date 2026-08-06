"""Offline regression tests for the L2.2/L2.3 fix batch (2026-06-11).

No Factorio needed. The payloads below are the VERBATIM layer-2 inspect
payloads captured during the L2.2/L2.3 certification runs
(.fv-output/certification/2026-06-11/L2.2/11_layer2_inspect.json and
L2.3/07_layer2_inspect.json), augmented with exactly the keys the fixed
inspection.lua now emits. The augmentation values are taken from the
layer-1 raw-engine truth captured in the same runs
(L2.2/10_layer1_engine.json, L2.3/05_layer1_engine.json), so these tests
pin the transform layer against engine truth, not invented fixtures.

Covers:
- FluidState capacity + connections (boiler/steam-engine previously shipped
  NO fluid data; pipes shipped contents without capacity/connectivity)
- ElectricPoleState connected_poles / supply area (previously stub defaults)
- machine electric_network_id (previously never emitted)
- burner currently_burning as a string (previously serialized to null)
- generator dispatch (steam-engine runtime type is "generator")
"""

import pytest

from FactoryVerse.game.factory.entity.transform import transform_inspection_data
from FactoryVerse.game.factory.entity.implementations.electric_pole import (
    ElectricPoleState,
)


# =============================================================================
# Fixtures: captured L2 payloads + the keys the fixed Lua now emits
# (augmentation values from the captured L1 engine truth)
# =============================================================================

BOILER_PAYLOAD = {
    # Captured base (L2.2/11_layer2_inspect.json "boiler@110,65.5")
    "entity_name": "boiler",
    "entity_type": "boiler",
    "position": {"x": 110, "y": 65.5},
    "direction": 4,
    "tick": 78586,
    "health": 200,
    "max_health": 200,
    "status": 1,
    "burner": {
        "heat": 31958.33456516266,
        "heat_capacity": 32000,
        "remaining_burning_fuel": 1026090.990781784,
        # Fixed: emitted as the prototype's name string (was null)
        "currently_burning": "coal",
        "fuel_inventory": {
            "contents": [
                {
                    "slot": 1,
                    "name": 1,
                    "count": {"name": "coal", "quality": "normal", "count": 4},
                    "quality": "normal",
                }
            ]
        },
    },
    # New: inspect_fluidboxes output (values from L1 truth 10_layer1_engine.json)
    "fluidbox": [
        {
            "index": 1,
            "capacity": 200,
            "name": "water",
            "amount": 200,
            "temperature": 15,
            "connections": [
                {"name": "pipe", "position": {"x": 109.5, "y": 67.5}},
            ],
        },
        {
            "index": 2,
            "capacity": 200,
            "name": "steam",
            "amount": 199.9569444656372,
            "temperature": 165,
            "connections": [
                {"name": "steam-engine", "position": {"x": 113.5, "y": 65.5}},
            ],
        },
    ],
}

STEAM_ENGINE_PAYLOAD = {
    # Captured base (L2.2/11_layer2_inspect.json "steam-engine@113.5,65.5" —
    # was base-fields-only because the dispatcher compared the NAME)
    "entity_name": "steam-engine",
    "entity_type": "generator",  # runtime TYPE — what the dispatcher now matches
    "position": {"x": 113.5, "y": 65.5},
    "direction": 4,
    "tick": 78589,
    "health": 400,
    "max_health": 400,
    "status": 1,
    # New: inspect_energy_producer output (values from L1 truth)
    "energy_generated_last_tick": 1291.666666666666,
    "energy": {"current": 13708.333333333334, "capacity": 15000},
    "electric_network_id": 1,
    "fluidbox": [
        {
            "index": 1,
            "capacity": 200,
            "name": "steam",
            "amount": 200,
            "temperature": 165,
            "connections": [
                {"name": "boiler", "position": {"x": 110, "y": 65.5}},
            ],
        }
    ],
}

PIPE_PAYLOAD = {
    # Captured base (L2.2/11_layer2_inspect.json "pipe@109.5,67.5")
    "entity_name": "pipe",
    "entity_type": "pipe",
    "position": {"x": 109.5, "y": 67.5},
    "direction": 0,
    "tick": 78584,
    "health": 100,
    "max_health": 100,
    "status": 1,
    "fluidbox": [
        {
            "index": 1,
            "name": "water",
            "amount": 99.9999652504921,
            "temperature": 15,
            # New keys (values from L1 truth: cap 400; connected to boiler + pipe)
            "capacity": 400,
            "connections": [
                {"name": "boiler", "position": {"x": 110, "y": 65.5}},
                {"name": "pipe", "position": {"x": 109.5, "y": 68.5}},
            ],
        }
    ],
}


def _pole_payload(x, neighbour_x, supply_entity):
    """Captured pole base (L2.3/07_layer2_inspect.json — was base-fields-only)
    + the keys the fixed inspect_electric_pole now emits (values from
    L2.3/05_layer1_engine.json)."""
    return {
        "entity_name": "small-electric-pole",
        "entity_type": "electric-pole",  # runtime TYPE
        "position": {"x": x, "y": 63.5},
        "direction": 0,
        "tick": 78592,
        "health": 100,
        "max_health": 100,
        "electric_network_id": 67,
        "wired_to_other_pole": True,
        "connected_poles": [
            {"name": "small-electric-pole", "position": {"x": neighbour_x, "y": 63.5}},
        ],
        "supply_area_entities": [supply_entity],
        "supply_area_entity_count": 1,
    }


POLE_1_PAYLOAD = _pole_payload(
    117.5, 123.5, {"name": "steam-engine", "position": {"x": 113.5, "y": 65.5}}
)
POLE_2_PAYLOAD = _pole_payload(
    123.5, 117.5, {"name": "assembling-machine-1", "position": {"x": 124.5, "y": 66.5}}
)

ASSEMBLER_PAYLOAD = {
    # Captured base (L2.3/07_layer2_inspect.json "assembling-machine-1@124.5,66.5")
    "entity_name": "assembling-machine-1",
    "entity_type": "assembling-machine",
    "position": {"x": 124.5, "y": 66.5},
    "direction": 0,
    "tick": 78598,
    "status": 27,
    "recipe": "iron-gear-wheel",
    "crafting_progress": 0,
    "bonus_progress": 0,
    "is_crafting": False,
    "inventories": {
        "crafter_input": {"name": "crafter_input", "size": 1, "is_empty": True, "contents": {}},
        "crafter_output": {
            "name": "crafter_output",
            "size": 1,
            "is_empty": False,
            "contents": [
                {"slot": 1, "name": "iron-gear-wheel", "count": 50, "quality": "normal"}
            ],
        },
        "crafter_modules": {"name": "crafter_modules", "size": 0, "is_empty": True, "contents": {}},
    },
    "energy": {"current": 1377.7777777777778, "capacity": 1377.7777777777778},
    "beacons_count": 0,
    # New: machine inspectors now emit electric_network_id (L1 truth: asm = 1)
    "electric_network_id": 1,
}


# =============================================================================
# Fluid: capacity + connections reach FluidState (L2.2)
# =============================================================================


class TestFluidTransform:
    def test_boiler_fluid_state_populated(self):
        """Boiler previously had fluid=None entirely."""
        inspection = transform_inspection_data(BOILER_PAYLOAD)
        assert inspection.fluid is not None
        assert len(inspection.fluid.fluidboxes) == 2
        names = {fb.name for fb in inspection.fluid.fluidboxes}
        assert names == {"water", "steam"}

    def test_fluid_state_capacity_positive(self):
        inspection = transform_inspection_data(BOILER_PAYLOAD)
        assert inspection.fluid.capacity == 400  # 200 water + 200 steam
        for fb in inspection.fluid.fluidboxes:
            assert fb.capacity > 0

    def test_fluid_state_connections_non_empty(self):
        inspection = transform_inspection_data(BOILER_PAYLOAD)
        conns = inspection.fluid.connections
        assert len(conns) == 2
        by_name = {c.name: c for c in conns}
        assert by_name["pipe"].position == {"x": 109.5, "y": 67.5}
        assert by_name["steam-engine"].position == {"x": 113.5, "y": 65.5}

    def test_pipe_capacity_and_connections(self):
        """Pipes previously transformed with capacity=0 and no connectivity."""
        inspection = transform_inspection_data(PIPE_PAYLOAD)
        assert inspection.fluid is not None
        assert inspection.fluid.capacity == 400
        conn_names = [c.name for c in inspection.fluid.connections]
        assert sorted(conn_names) == ["boiler", "pipe"]

    def test_steam_engine_fluid_via_generator_type_dispatch(self):
        """Steam engine (runtime type 'generator') previously had fluid=None."""
        inspection = transform_inspection_data(STEAM_ENGINE_PAYLOAD)
        assert inspection.fluid is not None
        steam = inspection.fluid.get_fluid(1)
        assert steam.name == "steam"
        assert steam.capacity == 200
        assert [c.name for c in steam.connections] == ["boiler"]

    def test_connections_deduped_across_boxes(self):
        payload = dict(PIPE_PAYLOAD)
        payload["fluidbox"] = [
            dict(PIPE_PAYLOAD["fluidbox"][0]),
            {
                "index": 2,
                "name": "water",
                "amount": 1,
                "capacity": 100,
                # Same boiler ref repeated — must not double-count
                "connections": [{"name": "boiler", "position": {"x": 110, "y": 65.5}}],
            },
        ]
        inspection = transform_inspection_data(payload)
        boiler_refs = [c for c in inspection.fluid.connections if c.name == "boiler"]
        assert len(boiler_refs) == 1

    def test_empty_fluidbox_keeps_capacity_visible(self):
        """The Lua helper emits empty boxes too (no name) — capacity and
        connectivity must survive so an empty-but-connected pipe is not
        indistinguishable from a missing one."""
        payload = dict(PIPE_PAYLOAD)
        payload["fluidbox"] = [
            {
                "index": 1,
                "amount": 0,
                "capacity": 400,
                "connections": [{"name": "boiler", "position": {"x": 110, "y": 65.5}}],
            }
        ]
        inspection = transform_inspection_data(payload)
        assert inspection.fluid is not None
        assert inspection.fluid.fluidboxes[0].is_empty is True
        assert inspection.fluid.capacity == 400
        assert [c.name for c in inspection.fluid.connections] == ["boiler"]


# =============================================================================
# Burner: currently_burning string (L2.2)
# =============================================================================


class TestBurnerTransform:
    def test_currently_burning_is_item_name(self):
        """Previously a LuaItemPrototype that serialized to null."""
        inspection = transform_inspection_data(BOILER_PAYLOAD)
        assert inspection.burner is not None
        assert inspection.burner.currently_burning == "coal"

    def test_fuel_inventory_recovered(self):
        inspection = transform_inspection_data(BOILER_PAYLOAD)
        assert inspection.burner.fuel_inventory == {"coal": 4}


# =============================================================================
# Generator: dispatch on runtime type (L2.2/L2.3)
# =============================================================================


class TestGeneratorTransform:
    def test_generator_state_populated_for_generator_type(self):
        """Previously generator=None because dispatch compared NAMES."""
        inspection = transform_inspection_data(STEAM_ENGINE_PAYLOAD)
        assert inspection.generator is not None
        assert inspection.generator.power_output == pytest.approx(1291.666666666666)

    def test_generator_electric_state_with_network_id(self):
        inspection = transform_inspection_data(STEAM_ENGINE_PAYLOAD)
        assert inspection.electric is not None
        assert inspection.electric.electric_network_id == 1


# =============================================================================
# Electric pole: connected_poles + supply area (L2.3)
# =============================================================================


class TestElectricPoleTransform:
    def test_pole_state_populated_for_runtime_type(self):
        """Previously bare base payload -> stub defaults everywhere."""
        inspection = transform_inspection_data(POLE_1_PAYLOAD)
        assert inspection.electric_pole is not None
        assert inspection.electric_pole.electric_network_id == 67

    def test_two_pole_rig_one_copper_neighbour_each(self):
        for payload, other_x in ((POLE_1_PAYLOAD, 123.5), (POLE_2_PAYLOAD, 117.5)):
            state = transform_inspection_data(payload).electric_pole
            assert len(state.connected_poles) == 1
            neighbour = state.connected_poles[0]
            assert neighbour.name == "small-electric-pole"
            assert neighbour.position == {"x": other_x, "y": 63.5}

    def test_supply_area_count_positive_with_refs(self):
        """supply_area was previously HARDCODED to 0 in the transform."""
        state = transform_inspection_data(POLE_1_PAYLOAD).electric_pole
        assert state.supply_area_entity_count > 0
        assert len(state.supply_area_entities) == 1
        assert state.supply_area_entities[0].name == "steam-engine"

        state2 = transform_inspection_data(POLE_2_PAYLOAD).electric_pole
        assert state2.supply_area_entities[0].name == "assembling-machine-1"

    def test_count_falls_back_to_ref_length(self):
        payload = dict(POLE_1_PAYLOAD)
        payload.pop("supply_area_entity_count")
        state = transform_inspection_data(payload).electric_pole
        assert state.supply_area_entity_count == 1

    def test_wired_to_other_pole_present_and_repr(self):
        """PWR-CONN-REPR-1: honest field name replaces the misleading
        `is_connected` (which read as 'powered')."""
        state = transform_inspection_data(POLE_1_PAYLOAD).electric_pole
        assert state.wired_to_other_pole is True
        # Deprecated alias property mirrors the renamed field exactly.
        assert state.is_connected == state.wired_to_other_pole
        # The honest name must surface in the repr an agent/human reads.
        assert "wired_to_other_pole" in repr(state)

    def test_legacy_is_connected_key_still_ingests(self):
        """Older deployed mods emit the legacy `is_connected` key; the
        transform must accept it as a fallback during the rename transition."""
        payload = dict(POLE_1_PAYLOAD)
        payload.pop("wired_to_other_pole")
        payload["is_connected"] = True
        state = transform_inspection_data(payload).electric_pole
        assert state.wired_to_other_pole is True
        assert state.is_connected is True

    def test_mixin_delegates_to_transform(self):
        """The mixin previously duplicated (and drifted from) the transform."""
        from FactoryVerse.game.factory.entity.implementations.electric_pole import (
            ElectricPoleMixin,
        )

        class _Pole(ElectricPoleMixin):
            is_ghost = False

        state = _Pole()._get_electric_pole_state(POLE_1_PAYLOAD)
        assert isinstance(state, ElectricPoleState)
        assert state.electric_network_id == 67
        assert len(state.connected_poles) == 1


# =============================================================================
# Machines: electric_network_id (L2.3)
# =============================================================================


class TestMachineElectricNetworkId:
    def test_assembler_electric_network_id_not_none(self):
        """Previously machine inspectors never sent electric_network_id."""
        inspection = transform_inspection_data(ASSEMBLER_PAYLOAD)
        assert inspection.electric is not None
        assert inspection.electric.electric_network_id == 1

    def test_assembler_energy_still_correct(self):
        """The one thing that already worked must keep working."""
        inspection = transform_inspection_data(ASSEMBLER_PAYLOAD)
        assert inspection.electric.energy == pytest.approx(1377.7777777777778)
        assert inspection.crafter is not None
        assert inspection.crafter.crafter_output == {"iron-gear-wheel": 50}
