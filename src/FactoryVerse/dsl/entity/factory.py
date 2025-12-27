"""Entity factory functions for creating view-wrapped entities.

This module provides factory functions that create entity instances with
appropriate view wrappers (Reachable, RemoteView, Ghost) and inject action
dependencies.
"""

from typing import Dict, Any, TYPE_CHECKING
from FactoryVerse.dsl.types import MapPosition, Direction

if TYPE_CHECKING:
    from FactoryVerse.agent.actions.entity_operations import EntityOperationsAction
    from FactoryVerse.agent.actions.place_entity import PlacementAction
    from .base_entity import BaseEntity

# Import entity implementations
from .implementations import (
    Container,
    WoodenChest,
    IronChest,
    SteelChest,
    ShipWreck,
    Furnace,
    StoneFurnace,
    SteelFurnace,
    ElectricFurnace,
    AssemblingMachine,
    ChemicalPlant,
    OilRefinery,
    Centrifuge,
    RocketSilo,
    ElectricMiningDrill,
    BurnerMiningDrill,
)

# Entity name -> class mapping
ENTITY_CLASS_MAP: Dict[str, type] = {
    # Containers
    "wooden-chest": WoodenChest,
    "iron-chest": IronChest,
    "steel-chest": SteelChest,
    "crash-site-chest-1": ShipWreck,
    "crash-site-chest-2": ShipWreck,
    # Furnaces
    "stone-furnace": StoneFurnace,
    "steel-furnace": SteelFurnace,
    "electric-furnace": ElectricFurnace,
    # Assembling machines
    "assembling-machine-1": AssemblingMachine,
    "assembling-machine-2": AssemblingMachine,
    "assembling-machine-3": AssemblingMachine,
    # Processing machines
    "chemical-plant": ChemicalPlant,
    "oil-refinery": OilRefinery,
    "centrifuge": Centrifuge,
    "rocket-silo": RocketSilo,
    # Mining drills
    "electric-mining-drill": ElectricMiningDrill,
    "burner-mining-drill": BurnerMiningDrill,
}


def _create_base_entity(entity_data: Dict[str, Any]) -> "BaseEntity":
    """Create base entity instance from data.

    Args:
        entity_data: Raw entity data with 'name', 'position', 'direction', etc.

    Returns:
        BaseEntity subclass instance

    Raises:
        ValueError: If entity type is unknown
    """
    name = entity_data["name"]
    entity_class = ENTITY_CLASS_MAP.get(name)

    if entity_class is None:
        raise ValueError(
            f"Unknown entity type: {name}. "
            f"This entity has not been migrated to the new architecture yet."
        )

    position = MapPosition(entity_data["position"]["x"], entity_data["position"]["y"])

    direction = None
    if "direction" in entity_data and entity_data["direction"] is not None:
        direction = Direction(entity_data["direction"])

    # Create entity with all data
    return entity_class(
        name=name,
        position=position,
        direction=direction,
        **{
            k: v
            for k, v in entity_data.items()
            if k not in ["name", "position", "direction"]
        },
    )


def create_reachable_entity(
    entity_data: Dict[str, Any],
    entity_ops: "EntityOperationsAction",
    place_ops: "PlacementAction",
):
    """Create a Reachable view wrapper around an entity.

    Used by: reachable_entities.get_entity()

    Args:
        entity_data: Raw entity data from game
        entity_ops: Entity operations action for game interactions
        place_ops: Place entity action for placement operations

    Returns:
        Reachable[BaseEntity] view wrapper
    """
    from .views import Reachable

    base_entity = _create_base_entity(entity_data)
    return Reachable(base_entity, entity_ops, place_ops)


def create_remote_view_entity(
    entity_data: Dict[str, Any],
    entity_ops: "EntityOperationsAction",
):
    """Create a RemoteView wrapper around an entity.

    Used by: map_db queries (entities not in reach)

    Args:
        entity_data: Raw entity data from game/database
        entity_ops: Entity operations action for inspection

    Returns:
        RemoteView[BaseEntity] view wrapper
    """
    from .views import RemoteView

    base_entity = _create_base_entity(entity_data)
    return RemoteView(base_entity, entity_ops)


def create_ghost_entity(
    entity_data: Dict[str, Any],
    entity_ops: "EntityOperationsAction",
    place_ops: "PlacementAction",
):
    """Create a Ghost view wrapper around an entity.

    Used by: ghost_manager, place_entity with ghost=True

    Args:
        entity_data: Raw entity data (ghost or planned entity)
        entity_ops: Entity operations action for ghost removal
        place_ops: Place entity action for building

    Returns:
        Ghost[BaseEntity] view wrapper
    """
    from .views import Ghost

    base_entity = _create_base_entity(entity_data)
    return Ghost(base_entity, entity_ops, place_ops)

# ============================================================================
# INSPECTION DATA PARSING
# ============================================================================

from typing import Optional
from .inspect import BaseInspectionData, BurnerData, EnergyData, EntityRef
from .implementations.furnace import FurnaceInspection


def _parse_burner(data: Optional[Dict[str, Any]]) -> Optional[BurnerData]:
    """Parse burner data from Lua response."""
    if data is None:
        return None
    return BurnerData(
        heat=data.get("heat"),
        heat_capacity=data.get("heat_capacity"),
        remaining_burning_fuel=data.get("remaining_burning_fuel"),
        currently_burning=data.get("currently_burning"),
    )


def _parse_energy(data: Optional[Dict[str, Any]]) -> Optional[EnergyData]:
    """Parse energy data from Lua response."""
    if data is None:
        return None
    return EnergyData(
        current=data["current"],
        capacity=data["capacity"]
    )


def _parse_entity_ref(data: Optional[Dict[str, Any]]) -> Optional[EntityRef]:
    """Parse entity reference from Lua response."""
    if data is None:
        return None
    return EntityRef(
        name=data["name"],
        position=MapPosition(data["position"]["x"], data["position"]["y"])
    )


def parse_inspection_data(raw_data: Dict[str, Any]) -> BaseInspectionData:
    """Parse Lua inspection data into typed dataclass.
    
    Args:
        raw_data: Raw dictionary from Lua inspection
        
    Returns:
        Typed inspection dataclass matching entity type
    """
    entity_type = raw_data["entity_type"]
    
    # Parse furnace inspection
    if entity_type == "furnace":
        return FurnaceInspection(
            entity_name=raw_data["entity_name"],
            entity_type=entity_type,
            position=MapPosition(raw_data["position"]["x"], raw_data["position"]["y"]),
            direction=raw_data["direction"],
            tick=raw_data["tick"],
            health=raw_data.get("health"),
            max_health=raw_data.get("max_health"),
            status=raw_data.get("status"),
            recipe=raw_data.get("recipe"),
            crafting_progress=raw_data.get("crafting_progress"),
            bonus_progress=raw_data.get("bonus_progress"),
            is_crafting=raw_data.get("is_crafting"),
            input=raw_data.get("input"),
            output=raw_data.get("output"),
            fuel=raw_data.get("fuel"),
            energy=_parse_energy(raw_data.get("energy")),
            beacons_count=raw_data.get("beacons_count"),
            burner=_parse_burner(raw_data.get("burner")),
            previous_recipe=raw_data.get("previous_recipe")
        )
    
    # Fallback to base inspection
    else:
        return BaseInspectionData(
            entity_name=raw_data["entity_name"],
            entity_type=entity_type,
            position=MapPosition(raw_data["position"]["x"], raw_data["position"]["y"]),
            direction=raw_data["direction"],
            tick=raw_data["tick"],
            health=raw_data.get("health"),
            max_health=raw_data.get("max_health"),
            status=raw_data.get("status")
        )
