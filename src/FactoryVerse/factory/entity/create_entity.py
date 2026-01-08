"""Entity factory functions for creating entities with view properties.

This module provides factory functions that create entity instances with
appropriate view properties (REACHABLE, REMOTE) and inject action
dependencies.

Ghosts are handled via the is_ghost property on BaseEntity. Ghost entities
are created with is_ghost=True and ghost_name set to the entity prototype
they represent.
"""

from typing import Dict, Any, TYPE_CHECKING
from FactoryVerse.factory.types import MapPosition, Direction
from .base_entity import EntityView

if TYPE_CHECKING:
    from FactoryVerse.agent.actions.entity_operations import EntityOperationsAction
    from FactoryVerse.agent.actions.place_entity import PlacementAction
    from .base_entity import BaseEntity

# Import entity implementations
from .implementations import (
    # Containers
    Container,
    WoodenChest,
    IronChest,
    SteelChest,
    ShipWreck,
    # Furnaces
    Furnace,
    StoneFurnace,
    SteelFurnace,
    ElectricFurnace,
    # Processing machines
    AssemblingMachine,
    ChemicalPlant,
    OilRefinery,
    Centrifuge,
    RocketSilo,
    # Mining drills
    ElectricMiningDrill,
    BurnerMiningDrill,
    # Pumpjack
    Pumpjack,
    # Inserters
    Inserter,
    FastInserter,
    LongHandedInserter,
    FilterInserter,
    StackInserter,
    StackFilterInserter,
    BulkInserter,
    BurnerInserter,
    # Transport belts
    TransportBelt,
    FastTransportBelt,
    ExpressTransportBelt,
    UndergroundBelt,
    FastUndergroundBelt,
    ExpressUndergroundBelt,
    Splitter,
    FastSplitter,
    ExpressSplitter,
    Loader,
    FastLoader,
    ExpressLoader,
    # Electric poles
    ElectricPole,
    SmallElectricPole,
    MediumElectricPole,
    BigElectricPole,
    Substation,
)

# Entity name -> class mapping
# Maps Factorio entity names to Python classes
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
    # Pumpjack
    "pumpjack": Pumpjack,
    # Inserters
    "inserter": Inserter,
    "fast-inserter": FastInserter,
    "long-handed-inserter": LongHandedInserter,
    "filter-inserter": FilterInserter,
    "stack-inserter": StackInserter,
    "stack-filter-inserter": StackFilterInserter,
    "bulk-inserter": BulkInserter,
    "burner-inserter": BurnerInserter,
    # Transport belts
    "transport-belt": TransportBelt,
    "fast-transport-belt": FastTransportBelt,
    "express-transport-belt": ExpressTransportBelt,
    # Underground belts
    "underground-belt": UndergroundBelt,
    "fast-underground-belt": FastUndergroundBelt,
    "express-underground-belt": ExpressUndergroundBelt,
    # Splitters
    "splitter": Splitter,
    "fast-splitter": FastSplitter,
    "express-splitter": ExpressSplitter,
    # Loaders
    "loader": Loader,
    "fast-loader": FastLoader,
    "express-loader": ExpressLoader,
    # Electric poles
    "small-electric-pole": SmallElectricPole,
    "medium-electric-pole": MediumElectricPole,
    "big-electric-pole": BigElectricPole,
    "substation": Substation,
}


def _create_base_entity(
    entity_data: Dict[str, Any],
    is_ghost: bool = False,
    view: EntityView = EntityView.REMOTE,
) -> "BaseEntity":
    """Create base entity instance from data.

    Args:
        entity_data: Raw entity data with 'name', 'position', 'direction', etc.
        is_ghost: Whether this is a ghost entity
        view: Entity view type (default: REMOTE)

    Returns:
        BaseEntity subclass instance

    Raises:
        ValueError: If entity type is unknown
    """
    # For ghosts, the actual entity name is in 'ghost_name', not 'name'
    # 'name' for ghosts is usually "entity-ghost"
    if is_ghost:
        entity_name: str = entity_data.get("ghost_name") or entity_data["name"]
        ghost_name: str | None = entity_name  # Store what entity this ghost represents
    else:
        entity_name = entity_data["name"]
        ghost_name = None

    entity_class = ENTITY_CLASS_MAP.get(entity_name)

    if entity_class is None:
        raise ValueError(
            f"Unknown entity type: {entity_name}. "
            f"This entity has not been migrated to the new architecture yet."
        )

    position = MapPosition(entity_data["position"]["x"], entity_data["position"]["y"])

    direction = None
    if "direction" in entity_data and entity_data["direction"] is not None:
        direction = Direction(entity_data["direction"])

    # Filter out keys we handle explicitly
    extra_keys = {
        k: v
        for k, v in entity_data.items()
        if k not in ["name", "position", "direction", "ghost_name", "type"]
    }

    # Create entity with ghost properties and view
    return entity_class(
        name=entity_name,
        position=position,
        direction=direction,
        is_ghost=is_ghost,
        ghost_name=ghost_name,
        view=view,
        **extra_keys,
    )


def create_reachable_entity(
    entity_data: Dict[str, Any],
    entity_ops: "EntityOperationsAction",
    place_ops: "PlacementAction",
    is_ghost: bool = False,
) -> "BaseEntity":
    """Create an entity with REACHABLE view.

    Used by: reachable_entities.get_entity(), reachable_entities.get_entities()

    Args:
        entity_data: Raw entity data from game
        entity_ops: Entity operations action for game interactions
        place_ops: Place entity action for placement operations
        is_ghost: Whether this is a ghost entity (default: False)

    Returns:
        BaseEntity instance with REACHABLE view
    """
    base_entity = _create_base_entity(entity_data, is_ghost=is_ghost, view=EntityView.REACHABLE)
    base_entity._entity_ops = entity_ops
    base_entity._place_ops = place_ops
    return base_entity


def create_remote_view_entity(
    entity_data: Dict[str, Any],
    entity_ops: "EntityOperationsAction | None" = None,
    place_ops: "PlacementAction | None" = None,
    is_ghost: bool = False,
) -> "BaseEntity":
    """Create an entity with REMOTE view.

    Used by: map_db queries (entities not in reach)

    Args:
        entity_data: Raw entity data from game/database
        entity_ops: Optional entity operations action for inspection
        place_ops: Optional place ops for ghost removal
        is_ghost: Whether this is a ghost entity (default: False)

    Returns:
        BaseEntity instance with REMOTE view
    """
    base_entity = _create_base_entity(entity_data, is_ghost=is_ghost, view=EntityView.REMOTE)
    if entity_ops is not None:
        base_entity._entity_ops = entity_ops
    if place_ops is not None:
        base_entity._place_ops = place_ops
    return base_entity
