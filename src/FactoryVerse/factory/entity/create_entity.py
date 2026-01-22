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
    from FactoryVerse.agent.embodied_actions.entity_operations import EntityOperationsAction
    from FactoryVerse.agent.embodied_actions.place_entity import PlacementAction
    from FactoryVerse.agent.embodied_actions.walking import MovementAction
    from .base_entity import BaseEntity

# ... (omitted)

# Import entity implementations
from .implementations import (
    # Containers
    WoodenChest,
    IronChest,
    SteelChest,
    ShipWreck,
    # Furnaces
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
    # Pumps
    OffshorePump,
    Pump,
    # Pipes and fluid storage
    Pipe,
    PipeToGround,
    StorageTank,
    # Solar panel
    SolarPanel,
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
    SmallElectricPole,
    MediumElectricPole,
    BigElectricPole,
    Substation,
    # New entities
    Lab,
    Accumulator,
    Boiler,
    SteamEngine,
    SteamTurbine,
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
    # Pumps
    "offshore-pump": OffshorePump,
    "pump": Pump,
    # Pipes and fluid storage
    "pipe": Pipe,
    "pipe-to-ground": PipeToGround,
    "storage-tank": StorageTank,
    # Solar panel
    "solar-panel": SolarPanel,
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
    # Labs
    "lab": Lab,
    # Accumulators
    "accumulator": Accumulator,
    # Generators
    "boiler": Boiler,
    "steam-engine": SteamEngine,
    "steam-turbine": SteamTurbine,
}


def _create_base_entity(
    entity_data: Dict[str, Any],
    entity_ops: "EntityOperationsAction",
    place_ops: "PlacementAction",
    walking_action: "MovementAction",
    is_ghost: bool = False,
    view: EntityView = EntityView.REMOTE,
) -> "BaseEntity":
    """Create base entity instance from data.

    Args:
        entity_data: Raw entity data with 'name', 'position', 'direction', etc.
        entity_ops: Entity operations action for game interactions
        place_ops: Placement action for placement operations
        walking_action: Movement action for navigation
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
        entity_name: str = entity_data.get("ghost_name") or entity_data.get("name", "")
        ghost_name: str | None = entity_name  # Store what entity this ghost represents
    else:
        # Handle both 'name' and 'entity_name' fields (inspect_entity returns 'entity_name')
        entity_name = entity_data.get("name") or entity_data.get("entity_name", "")
        if not entity_name:
            raise ValueError(
                f"Entity data missing 'name' or 'entity_name' field: {list(entity_data.keys())}"
            )
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
        entity_ops=entity_ops,
        place_ops=place_ops,
        walking_action=walking_action,
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
    walking_action: "MovementAction",
    is_ghost: bool = False,
) -> "BaseEntity":
    """Create an entity with REACHABLE view.

    Used by: reachable_entities.get_entity(), reachable_entities.get_entities()

    Args:
        entity_data: Raw entity data from game
        entity_ops: Entity operations action for game interactions
        place_ops: Place entity action for placement operations
        walking_action: Movement action for navigation
        is_ghost: Whether this is a ghost entity (default: False)

    Returns:
        BaseEntity instance with REACHABLE view
    """
    return _create_base_entity(
        entity_data,
        entity_ops=entity_ops,
        place_ops=place_ops,
        walking_action=walking_action,
        is_ghost=is_ghost,
        view=EntityView.REACHABLE,
    )


def create_remote_view_entity(
    entity_data: Dict[str, Any],
    entity_ops: "EntityOperationsAction",
    place_ops: "PlacementAction",
    walking_action: "MovementAction",
    is_ghost: bool = False,
) -> "BaseEntity":
    """Create an entity with REMOTE view.

    Used by: map_db queries (entities not in reach)

    Args:
        entity_data: Raw entity data from game/database
        entity_ops: Entity operations action for inspection
        place_ops: Placement action for ghost removal
        walking_action: Movement action for navigation
        is_ghost: Whether this is a ghost entity (default: False)

    Returns:
        BaseEntity instance with REMOTE view
    """
    return _create_base_entity(
        entity_data,
        entity_ops=entity_ops,
        place_ops=place_ops,
        walking_action=walking_action,
        is_ghost=is_ghost,
        view=EntityView.REMOTE,
    )
