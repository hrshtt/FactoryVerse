"""Abstract base entity class and entity position helper.

This module defines the core BaseEntity contract that all entity implementations
must follow. BaseEntity defines WHAT an entity is through its mixins and properties,
but does NOT define HOW to interact with it (that's the view wrapper's job).
"""

from abc import ABC, abstractmethod
from typing import Optional, Union, List, Dict, Any, TYPE_CHECKING
from FactoryVerse.factory.types import MapPosition, Direction, EntityInspectionData
from FactoryVerse.factory.mixins import SpatialPropertiesMixin, PrototypeMixin
from FactoryVerse.factory.prototypes import BasePrototype, get_entity_prototypes

if TYPE_CHECKING:
    from FactoryVerse.factory.item.base import PlaceableItem, ItemStack
    from FactoryVerse.agent.actions.entity_operations import EntityOperationsAction
    from FactoryVerse.agent.actions.place_entity import PlacementAction


class EntityPosition(MapPosition):
    """Position with entity-aware spatial operations.

    High-level position type that knows about entities, items, and prototypes.
    Provides spatial reasoning for placement and layout calculations.
    MapPosition remains pure - this handles the DSL-aware logic.

    Can be bound to a parent entity, making offset calculations more ergonomic:
        furnace.position.offset_by_entity(direction=Direction.NORTH)
    """

    def __init__(
        self,
        x: float,
        y: float,
        entity: Optional[Union["BaseEntity", "PlaceableItem"]] = None,
    ):
        """Initialize EntityPosition, optionally bound to an entity.

        Args:
            x: X coordinate
            y: Y coordinate
            entity: Optional parent entity for default dimension calculations
        """
        super().__init__(x, y)
        self._entity = entity

    def offset_by_entity(
        self,
        direction: Direction,
        entity: Optional[Union["BaseEntity", "PlaceableItem", BasePrototype]] = None,
        gap: int = 0,
    ) -> "EntityPosition":
        """Calculate position offset by entity dimensions in a cardinal direction.

        Uses parent entity dimensions if no entity is provided.

        Args:
            direction: Cardinal direction to offset (NORTH/SOUTH/EAST/WEST)
            entity: Entity, item, or prototype to get dimensions from (uses parent if None)
            gap: Additional tiles of spacing (default 0 for touching)

        Returns:
            New EntityPosition offset by entity dimensions + gap

        Examples:
            >>> # Offset using bound entity (most ergonomic)
            >>> furnace = reachable_entities.get_entity("stone-furnace")
            >>> next_pos = furnace.position.offset_by_entity(direction=Direction.NORTH)
            >>>
            >>> # Offset using different entity's dimensions
            >>> next_pos = furnace.position.offset_by_entity(drill_item, Direction.EAST)
            >>>
            >>> # Standalone usage
            >>> entity_pos = EntityPosition(x=10, y=20)
            >>> next_pos = entity_pos.offset_by_entity(furnace, Direction.NORTH, gap=1)
        """
        if direction is None:
            raise ValueError("direction is required")

        ref = entity or self._entity
        if ref is None:
            raise ValueError(
                "No entity provided and no parent entity bound to this position. "
                "Either pass an entity or use EntityPosition from an entity's .position property."
            )

        if not direction.is_cardinal():
            raise ValueError(
                f"Cannot offset in non-cardinal direction: {direction.name}"
            )

        # Extract tile dimensions (all three types have these properties)
        tile_w = ref.tile_width
        tile_h = ref.tile_height

        # Calculate distance based on direction
        # NORTH/SOUTH: use height, EAST/WEST: use width
        if direction in (Direction.NORTH, Direction.SOUTH):
            distance = tile_h + gap
        else:  # EAST or WEST
            distance = tile_w + gap

        # Calculate new position based on cardinal direction
        # Positive x = east, positive y = south
        if direction == Direction.NORTH:
            new_x, new_y = self.x, self.y - distance
        elif direction == Direction.EAST:
            new_x, new_y = self.x + distance, self.y
        elif direction == Direction.SOUTH:
            new_x, new_y = self.x, self.y + distance
        else:  # WEST
            new_x, new_y = self.x - distance, self.y

        # Return new EntityPosition, not bound to any entity (it's just a calculated position)
        return EntityPosition(x=new_x, y=new_y)


class BaseEntity(SpatialPropertiesMixin, PrototypeMixin, ABC):
    """Abstract base class for all entity implementations.

    Defines WHAT an entity is through its mixins and properties.
    Does NOT define HOW to interact with it (that's the view wrapper's job).

    **For Agents**: You won't interact with BaseEntity directly. You'll get
    view-wrapped entities like Reachable[Furnace] or RemoteView[Assembler]
    that control what operations are available.

    Ghosts are entities with is_ghost=True. They appear in entity queries
    for spatial awareness but have limited operations (build, remove, static inspect).
    """

    def __init__(
        self,
        name: str,
        position: MapPosition,
        direction: Optional[Direction] = None,
        is_ghost: bool = False,
        ghost_name: Optional[str] = None,
        **kwargs,
    ):
        """Initialize base entity.

        Args:
            name: Entity prototype name (e.g., "stone-furnace")
            position: Entity position in the world
            direction: Entity direction (if applicable)
            is_ghost: Whether this is a ghost entity (default: False)
            ghost_name: For ghosts, the entity prototype this ghost represents
            **kwargs: Additional entity-specific properties
        """
        self.name = name
        self._raw_position = position
        self.direction = direction
        self._is_ghost = is_ghost
        self._ghost_name = ghost_name
        self._prototype_cache: Optional[BasePrototype] = None

        # Action dependencies (injected by view wrappers)
        self._entity_ops: Optional["EntityOperationsAction"] = None
        self._place_ops: Optional["PlacementAction"] = None

        # Handle any additional kwargs for entity-specific properties
        for key, value in kwargs.items():
            setattr(self, key, value)

    @property
    def position(self) -> EntityPosition:
        """Get entity position as EntityPosition bound to this entity.

        **For Agents**: Use this for spatial calculations:
        - next_pos = entity.position.offset_by_entity(direction=Direction.NORTH)
        - distance = entity.position.distance_to(other_pos)
        """
        return EntityPosition(
            x=self._raw_position.x, y=self._raw_position.y, entity=self
        )

    def _load_prototype(self) -> BasePrototype:
        """Load entity prototype by direct lookup.

        Entities have a simpler prototype loading path than items:
        1. Get entity type from name
        2. Load prototype data for that type
        """
        protos = get_entity_prototypes()
        entity_type = protos.get_entity_type(self.name)
        if entity_type and entity_type in protos.data:
            entity_data = protos.data[entity_type].get(self.name, {})
            return BasePrototype(_data=entity_data)
        # Fallback to empty prototype
        return BasePrototype(_data={})

    @property
    def is_ghost(self) -> bool:
        """Whether this is a ghost entity.

        **For Agents**: Ghosts are placeholder entities that can be built.
        They appear in spatial queries but have limited operations.
        """
        return self._is_ghost

    @property
    def ghost_name(self) -> Optional[str]:
        """For ghost entities, the entity prototype this ghost represents.

        **For Agents**: Use this to know what entity will be created when building.
        Returns None for non-ghost entities.
        """
        return self._ghost_name if self._is_ghost else None

    def inspect(self, raw_data: bool = False) -> Union[str, "EntityInspectionData"]:
        """Inspect entity state with live game data.

        **For Agents**: Use this to check entity status, inventories, progress, etc.
        Entity must be wrapped in a view (Reachable/RemoteView) for this to work.

        For ghost entities, returns static data (ghosts don't have live state).

        Args:
            raw_data: If False (default), returns formatted string for reading.
                     If True, returns raw dictionary for programmatic access.

        Returns:
            Formatted string or EntityInspectionData TypedDict
        """
        # Ghosts return static inspection (no live state)
        if self._is_ghost:
            return self._format_ghost_inspection()

        if self._entity_ops is None:
            raise RuntimeError(
                f"Cannot inspect {self.__class__.__name__}: entity_ops not injected. "
                "Entity must be wrapped in a view (Reachable/RemoteView) for inspection."
            )
        data = self._entity_ops.inspect_entity(self.name, self.position)
        if raw_data:
            return data  # type: ignore
        return self._format_inspection(data)

    def _format_ghost_inspection(self) -> str:
        """Format static ghost inspection data.

        Ghosts don't have live state (no fuel, no recipe progress, no inventory).
        Returns a static representation based on the ghost's planned entity type.
        """
        lines = [
            f"=== {self.name} (GHOST) ===",
            f"Position: ({self.position.x}, {self.position.y})",
            f"Will build: {self._ghost_name or self.name}",
        ]
        if self.direction is not None:
            lines.append(f"Direction: {self.direction.name}")
        lines.append("Status: Ghost (no live state)")
        lines.append("")
        lines.append("Use .build() to construct this ghost into a real entity.")
        lines.append("Use .remove() to delete this ghost.")
        return "\n".join(lines)

    def pickup(self) -> List["ItemStack"]:
        """Pick up the entity and return extracted items.

        **For Agents**: Use this to remove an entity and get its contents.
        Entity must be wrapped in Reachable view for this to work.

        Returns:
            List of ItemStack objects representing items extracted from the entity
        """
        if self._entity_ops is None:
            raise RuntimeError(
                f"Cannot pickup {self.__class__.__name__}: entity_ops not injected. "
                "Entity must be wrapped in Reachable view."
            )
        result = self._entity_ops.pickup_entity(self.name, self.position)
        from FactoryVerse.factory.item.base import ItemStack

        if result.extracted_items:
            return [
                ItemStack(name, count) for name, count in result.extracted_items.items()
            ]
        return []

    @abstractmethod
    def _format_inspection(self, data: Dict[str, Any]) -> str:
        """Format inspection data for agent readability.

        Entity-specific formatting logic. Each entity type knows how to
        present its data (furnace shows burner info, assembler shows recipe, etc.)

        Args:
            data: Raw inspection data from the game

        Returns:
            Formatted string for agent consumption
        """
        pass

    def __repr__(self) -> str:
        """Simple, explicit representation of the entity."""
        pos = self.position
        ghost_indicator = " [GHOST]" if self._is_ghost else ""
        if self.direction is not None:
            return f"{self.__class__.__name__}(name='{self.name}', position=({pos.x}, {pos.y}), direction={self.direction.name}){ghost_indicator}"
        return f"{self.__class__.__name__}(name='{self.name}', position=({pos.x}, {pos.y})){ghost_indicator}"
