"""Transform raw Lua inspection data to EntityInspection Pydantic models.

This module bridges the gap between Lua inspection data (flat structure with
keys like 'mining_target', 'energy', 'burner') and the Python EntityInspection
model (nested structure with capability slots like 'miner', 'electric', 'burner').
"""

from typing import Dict, Any, Optional
from FactoryVerse.game.factory.entity.inspection import EntityInspection
from FactoryVerse.game.factory.entity.capabilities import (
    MinerState,
    MiningTarget,
    BurnerState,
    ElectricState,
    CrafterState,
    InserterState,
    HeldItem,
    FluidState,
    FluidBox,
    FluidConnection,
    BeltState,
    BeltNeighbour,
)
from FactoryVerse.game.factory.entity.implementations.container import ContainerState
from FactoryVerse.game.factory.entity.implementations.lab import LabState
from FactoryVerse.game.factory.entity.implementations.accumulator import AccumulatorState
from FactoryVerse.game.factory.entity.implementations.electric_pole import (
    ElectricPoleState,
    PoleNeighbour,
)
from FactoryVerse.game.factory.entity.implementations.generator import GeneratorState


def transform_inspection_data(raw_data: Dict[str, Any]) -> EntityInspection:
    """Transform raw Lua inspection data to EntityInspection model.

    Maps flat Lua data to capability slots:
    - mining_target, mining_progress → MinerState
    - burner → BurnerState
    - energy → ElectricState
    - crafting_progress, recipe → CrafterState
    - pickup_position, drop_position → InserterState
    - etc.

    Args:
        raw_data: Raw inspection data from Lua inspect_entity

    Returns:
        EntityInspection Pydantic model with populated capability slots

    Example:
        >>> raw = rcon.run("agent_1", "inspect_entity", {"entity_name": "electric-mining-drill", "position": pos})
        >>> inspection = transform_inspection_data(raw)
        >>> assert inspection.miner is not None
        >>> assert inspection.electric is not None
    """
    # Extract base fields
    entity_name = raw_data.get("entity_name", "")
    entity_type = raw_data.get("entity_type", "")
    position = raw_data.get("position", {"x": 0, "y": 0})
    direction = raw_data.get("direction")
    status = raw_data.get("status")
    is_ghost = raw_data.get("is_ghost", False)

    # Transform capability data
    miner = _transform_miner(raw_data, entity_type)
    burner = _transform_burner(raw_data)
    electric = _transform_electric(raw_data)
    crafter = _transform_crafter(raw_data, entity_type)
    inserter = _transform_inserter(raw_data, entity_type)
    fluid = _transform_fluid(raw_data)
    belt = _transform_belt(raw_data, entity_type)

    # Transform category-specific data
    container = _transform_container(raw_data, entity_type)
    lab = _transform_lab(raw_data, entity_type)
    accumulator = _transform_accumulator(raw_data, entity_type)
    electric_pole = _transform_electric_pole(raw_data, entity_type)
    generator = _transform_generator(raw_data, entity_type)

    return EntityInspection(
        name=entity_name,
        position=position,
        direction=direction,
        status=status,
        is_ghost=is_ghost,
        miner=miner,
        burner=burner,
        electric=electric,
        crafter=crafter,
        inserter=inserter,
        fluid=fluid,
        belt=belt,
        container=container,
        lab=lab,
        accumulator=accumulator,
        electric_pole=electric_pole,
        generator=generator,
    )


def _transform_miner(
    raw_data: Dict[str, Any], entity_type: str
) -> Optional[MinerState]:
    """Transform mining drill data to MinerState."""
    if entity_type != "mining-drill":
        return None

    # Check if we have mining data
    if "mining_target" not in raw_data and "mining_progress" not in raw_data:
        return None

    # Parse mining target
    mining_target = None
    target_data = raw_data.get("mining_target")
    if target_data:
        mining_target = MiningTarget(
            name=target_data.get("name", ""),
            amount=target_data.get("amount", 0),
            position=target_data.get("position"),
        )

    # Parse drop target
    drop_target = None
    drop_target_data = raw_data.get("drop_target")
    if drop_target_data:
        drop_target = drop_target_data.get("name")

    return MinerState(
        mining_progress=raw_data.get("mining_progress", 0),
        mining_target=mining_target,
        drop_position=raw_data.get("drop_position"),
        drop_target=drop_target,
    )


def _transform_burner(raw_data: Dict[str, Any]) -> Optional[BurnerState]:
    """Transform burner data to BurnerState."""
    burner_data = raw_data.get("burner")
    if not burner_data:
        return None

    # Parse fuel inventory
    fuel_items: Dict[str, int] = {}
    fuel_inv = burner_data.get("fuel_inventory", {})

    # Handle both dict and array-like formats
    if fuel_inv:
        contents = fuel_inv.get("contents")
        if contents:
            # If contents is a list
            if isinstance(contents, list):
                for item in contents:
                    # The actual item data is in the 'count' field (weird Lua structure)
                    # Example: {'slot': 1, 'name': 1, 'count': {'name': 'coal', 'quality': 'normal', 'count': 4}}
                    if isinstance(item, dict):
                        item_data = item.get("count")
                        if isinstance(item_data, dict) and "name" in item_data:
                            fuel_items[item_data["name"]] = item_data.get("count", 0)
                        elif "name" in item and isinstance(item["name"], str):
                            # Fallback for normal structure
                            fuel_items[item["name"]] = item.get("count", 0)
            # If contents is a dict with numeric keys (Lua array)
            elif isinstance(contents, dict):
                for key, item in contents.items():
                    if isinstance(item, dict):
                        item_data = item.get("count")
                        if isinstance(item_data, dict) and "name" in item_data:
                            fuel_items[item_data["name"]] = item_data.get("count", 0)
                        elif "name" in item and isinstance(item["name"], str):
                            fuel_items[item["name"]] = item.get("count", 0)

    return BurnerState(
        heat=burner_data.get("heat", 0),
        heat_capacity=burner_data.get("heat_capacity", 0),
        remaining_burning_fuel=burner_data.get("remaining_fuel", 0)
        or burner_data.get("remaining_burning_fuel", 0),
        currently_burning=burner_data.get("currently_burning"),
        fuel_inventory=fuel_items,
    )


def _transform_electric(raw_data: Dict[str, Any]) -> Optional[ElectricState]:
    """Transform electric data to ElectricState."""
    energy_data = raw_data.get("energy")
    if not energy_data:
        return None

    # Handle both dict format and direct values
    if isinstance(energy_data, dict):
        current = energy_data.get("current", 0)
        capacity = energy_data.get("capacity", 0)
    else:
        current = energy_data
        capacity = raw_data.get("electric_buffer_size", 0)

    return ElectricState(
        energy=current,
        buffer_capacity=capacity,
        electric_network_id=raw_data.get("electric_network_id"),
    )


def _transform_crafter(
    raw_data: Dict[str, Any], entity_type: str
) -> Optional[CrafterState]:
    """Transform crafting machine data to CrafterState."""
    # Check if this is a crafting machine type
    crafting_types = {
        "assembling-machine",
        "furnace",
        "chemical-plant",
        "oil-refinery",
        "centrifuge",
        "rocket-silo",
    }
    if entity_type not in crafting_types:
        return None

    # Check if we have crafting data
    if (
        "crafting_progress" not in raw_data
        and "recipe" not in raw_data
        and "current_recipe" not in raw_data
    ):
        return None

    # Parse inventories
    inventories = raw_data.get("inventories", {})

    def parse_inventory(inv_data: dict) -> Dict[str, int]:
        if not inv_data:
            return {}
        contents = inv_data.get("contents", [])
        result = {}
        for item in contents:
            result[item["name"]] = item.get("count", 0)
        return result

    return CrafterState(
        recipe=raw_data.get("current_recipe") or raw_data.get("recipe"),
        crafting_progress=raw_data.get("crafting_progress", 0),
        crafting_speed=raw_data.get("crafting_speed", 1.0),
        is_crafting=raw_data.get("crafting_progress", 0) > 0,
        crafter_input=parse_inventory(inventories.get("crafter_input", {})),
        crafter_output=parse_inventory(inventories.get("crafter_output", {})),
        crafter_modules=parse_inventory(inventories.get("crafter_modules", {})),
    )


def _transform_inserter(
    raw_data: Dict[str, Any], entity_type: str
) -> Optional[InserterState]:
    """Transform inserter data to InserterState."""
    if "inserter" not in entity_type:
        return None

    # Check if we have inserter data
    if "pickup_position" not in raw_data and "drop_position" not in raw_data:
        return None

    # Parse held item
    held_item = None
    held_data = raw_data.get("held_item")
    if held_data:
        held_item = HeldItem(
            name=held_data.get("name", ""),
            count=held_data.get("count", 0),
        )

    # Relational reads: what this inserter picks from / drops into.
    # Lua sends entity refs ({name, position, ...}); the drop/pickup positions
    # above pin down which tile, so the name is enough to identify the target.
    def _target_name(ref: Any) -> Optional[str]:
        if isinstance(ref, dict):
            return ref.get("name")
        return None

    # Filters come from Lua as {index: item_name}; flatten to a list.
    filters_raw = raw_data.get("filters") or {}
    filters = [v for v in filters_raw.values() if isinstance(v, str)] if isinstance(
        filters_raw, dict
    ) else []

    return InserterState(
        pickup_position=raw_data.get("pickup_position"),
        drop_position=raw_data.get("drop_position"),
        pickup_target=_target_name(raw_data.get("pickup_target")),
        drop_target=_target_name(raw_data.get("drop_target")),
        held_item=held_item,
        filters=filters,
    )


def _transform_fluid(raw_data: Dict[str, Any]) -> Optional[FluidState]:
    """Transform fluid data to FluidState.

    Lua side (shared inspect_fluidboxes helper) emits per box:
    {index, name?, amount, temperature?, capacity, connections=[{name, position}]}
    Empty boxes are included (no name) so capacity/connections stay visible.
    """
    fluidbox_data = raw_data.get("fluidbox") or raw_data.get("fluidboxes")
    if not fluidbox_data:
        return None

    def _connections(items: Any) -> list:
        refs = []
        if isinstance(items, list):
            for c in items:
                if isinstance(c, dict) and c.get("name"):
                    refs.append(
                        FluidConnection(name=c["name"], position=c.get("position"))
                    )
        return refs

    # Parse fluidboxes
    fluidboxes = []
    if isinstance(fluidbox_data, list):
        for idx, fb in enumerate(fluidbox_data, start=1):
            if fb and not fb.get("empty"):
                fluidboxes.append(
                    FluidBox(
                        index=fb.get("index", idx),
                        name=fb.get("name"),
                        amount=fb.get("amount", 0),
                        temperature=fb.get("temperature", 15),
                        capacity=fb.get("capacity", 0),
                        is_empty=fb.get("name") is None,
                        connections=_connections(fb.get("connections")),
                    )
                )

    if not fluidboxes:
        return None

    # State-level rollups: total capacity + deduped union of connections
    seen = set()
    connections = []
    for box in fluidboxes:
        for conn in box.connections:
            pos = conn.position or {}
            key = (conn.name, pos.get("x"), pos.get("y"))
            if key not in seen:
                seen.add(key)
                connections.append(conn)

    return FluidState(
        fluidboxes=fluidboxes,
        capacity=sum(box.capacity for box in fluidboxes),
        connections=connections,
    )


def _transform_belt(raw_data: Dict[str, Any], entity_type: str) -> Optional[BeltState]:
    """Transform belt data to BeltState."""
    belt_types = {"transport-belt", "underground-belt", "splitter", "lane-splitter"}
    if entity_type not in belt_types:
        return None

    def _ref(d: Any) -> Optional[BeltNeighbour]:
        if not isinstance(d, dict):
            return None
        return BeltNeighbour(name=d.get("name", ""), position=d.get("position"))

    def _refs(items: Any) -> list:
        if not isinstance(items, list):
            return []
        return [r for r in (_ref(i) for i in items) if r is not None]

    return BeltState(
        belt_shape=raw_data.get("belt_shape"),
        belt_inputs=_refs(raw_data.get("belt_inputs")),
        belt_outputs=_refs(raw_data.get("belt_outputs")),
        belt_to_ground_type=raw_data.get("belt_to_ground_type"),
        underground_neighbour=_ref(raw_data.get("underground_neighbour")),
        linked_belt_neighbour=_ref(raw_data.get("linked_belt_neighbour")),
        linked_belt_type=raw_data.get("linked_belt_type"),
        splitter_filter=raw_data.get("splitter_filter"),
        splitter_input_priority=raw_data.get("splitter_input_priority"),
        splitter_output_priority=raw_data.get("splitter_output_priority"),
    )


def _transform_container(
    raw_data: Dict[str, Any], entity_type: str
) -> Optional[ContainerState]:
    """Transform container data to ContainerState."""
    container_types = {"container", "logistic-container", "cargo-wagon"}
    if entity_type not in container_types:
        return None

    contents = raw_data.get("contents", {})
    return ContainerState(contents=contents)


def _transform_lab(raw_data: Dict[str, Any], entity_type: str) -> Optional[LabState]:
    """Transform lab data to LabState."""
    if entity_type != "lab":
        return None

    return LabState(
        current_research=raw_data.get("current_research"),
        research_progress=raw_data.get("research_progress", 0),
    )


def _transform_accumulator(
    raw_data: Dict[str, Any], entity_type: str
) -> Optional[AccumulatorState]:
    """Transform accumulator data to AccumulatorState."""
    if entity_type != "accumulator":
        return None

    energy_data = raw_data.get("energy", {})
    if isinstance(energy_data, dict):
        current = energy_data.get("current", 0)
        capacity = energy_data.get("capacity", 0)
    else:
        current = energy_data
        capacity = raw_data.get("electric_buffer_size", 0)

    return AccumulatorState(
        charge=current,
        capacity=capacity,
    )


def _pole_refs(items: Any) -> list:
    """Parse a Lua list of {name, position} refs into PoleNeighbour models."""
    refs = []
    if isinstance(items, list):
        for n in items:
            if isinstance(n, dict) and n.get("name"):
                refs.append(PoleNeighbour(name=n["name"], position=n.get("position")))
    return refs


def _transform_electric_pole(
    raw_data: Dict[str, Any], entity_type: str
) -> Optional[ElectricPoleState]:
    """Transform electric pole data to ElectricPoleState.

    Lua inspect_electric_pole emits: electric_network_id, is_connected,
    connected_poles (name+position refs via the 2.0 wire connector API),
    supply_area_entities (refs, capped) + supply_area_entity_count (exact).
    """
    # Runtime TYPE is "electric-pole" for all poles incl. substation;
    # names kept for compatibility with older captured payloads.
    pole_types = {
        "electric-pole",
        "small-electric-pole",
        "medium-electric-pole",
        "big-electric-pole",
        "substation",
    }
    if entity_type not in pole_types:
        return None

    supply_refs = _pole_refs(raw_data.get("supply_area_entities"))
    count = raw_data.get("supply_area_entity_count")
    if not isinstance(count, int):
        count = len(supply_refs)

    return ElectricPoleState(
        electric_network_id=raw_data.get("electric_network_id"),
        is_connected=raw_data.get("is_connected"),
        connected_poles=_pole_refs(raw_data.get("connected_poles")),
        supply_area_entities=supply_refs,
        supply_area_entity_count=count,
    )


def _transform_generator(
    raw_data: Dict[str, Any], entity_type: str
) -> Optional[GeneratorState]:
    """Transform generator data to GeneratorState."""
    # Runtime TYPES (Factorio 2.0): steam-engine/steam-turbine -> "generator",
    # nuclear-reactor -> "reactor"; names kept for older captured payloads.
    generator_types = {
        "generator",
        "burner-generator",
        "reactor",
        "solar-panel",
        "boiler",
        "steam-engine",
        "steam-turbine",
        "nuclear-reactor",
    }
    if entity_type not in generator_types:
        return None

    return GeneratorState(
        power_output=raw_data.get("power_production", 0)
        or raw_data.get("power_output", 0)
        # Generator types report actual production via energy_generated_last_tick (J/tick)
        or raw_data.get("energy_generated_last_tick", 0),
        max_power_output=raw_data.get("max_power_output", 0),
        effectivity=raw_data.get("effectivity", 1.0),
    )
