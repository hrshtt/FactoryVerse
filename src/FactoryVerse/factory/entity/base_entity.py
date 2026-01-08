"""Abstract base entity class and entity position helper.

This module defines the core BaseEntity contract that all entity implementations
must follow. BaseEntity defines WHAT an entity is through its mixins and properties,
and HOW to interact with it through the view property that controls access.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, Union, List, Dict, Any, TYPE_CHECKING
from FactoryVerse.factory.types import MapPosition, Direction, EntityInspectionData
from FactoryVerse.factory.mixins import SpatialPropertiesMixin, PrototypeMixin
from FactoryVerse.factory.prototypes import BasePrototype, get_entity_prototypes

if TYPE_CHECKING:
    from FactoryVerse.factory.item.base import PlaceableItem, ItemStack
    from FactoryVerse.agent.actions.entity_operations import EntityOperationsAction
    from FactoryVerse.agent.actions.place_entity import PlacementAction


class EntityView(Enum):
    REMOTE = "remote"
    REACHABLE = "reachable"


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

    Defines WHAT an entity is through its mixins and properties,
    and HOW to interact with it through the view property that controls access.

    **For Agents**: Entities are returned with appropriate view settings:
    - Reachable entities: Full access - can mutate entity state, build/remove ghosts
    - Remote entities: Read-only access - can inspect but not mutate, can remove ghosts
    - Ghost entities: Limited operations (build, remove, static inspect)

    Ghosts are entities with is_ghost=True. They appear in entity queries
    for spatial awareness but have limited operations (build, remove, static inspect).
    """

    # Blocked methods by view/ghost status
    _REACHABLE_ONLY = frozenset({
        "pickup", "add_fuel", "add_ingredients", "take_products",
        "store_items", "take_items", "set_recipe", "build"
    })
    _GHOST_BLOCKED = frozenset({
        "pickup", "add_fuel", "add_ingredients", "take_products",
        "store_items", "take_items", "set_recipe"
    })

    def __init__(
        self,
        name: str,
        position: MapPosition,
        direction: Optional[Direction] = None,
        is_ghost: bool = False,
        ghost_name: Optional[str] = None,
        view: EntityView = EntityView.REMOTE,
        **kwargs,
    ):
        """Initialize base entity.

        Args:
            name: Entity prototype name (e.g., "stone-furnace")
            position: Entity position in the world
            direction: Entity direction (if applicable)
            is_ghost: Whether this is a ghost entity (default: False)
            ghost_name: For ghosts, the entity prototype this ghost represents
            view: Entity view type (REMOTE or REACHABLE, default: REMOTE)
            **kwargs: Additional entity-specific properties
        """
        self.name = name
        self._raw_position = position
        self.direction = direction
        self._is_ghost = is_ghost
        self._ghost_name = ghost_name
        self._view = view
        self._prototype_cache: Optional[BasePrototype] = None

        # Action dependencies (injected during entity creation)
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

    def __getattribute__(self, name: str):
        """Filter method access based on view and ghost status.
        
        Control flow makes the distinction clear:
        1. View (REACHABLE vs REMOTE) controls proximity-based access:
           - REMOTE entities: read-only (can inspect, can remove ghosts, cannot build/mutate)
           - REACHABLE entities: full access (can build ghosts, can mutate)
        2. Ghost status controls what operations make sense:
           - Ghosts: can build/remove, cannot mutate (no live state to mutate)
           - Real entities: can mutate (have live state)
        
        This means:
        - REACHABLE ghost: can build (proximity + is ghost) ✅
        - REMOTE ghost: cannot build (no proximity) ❌
        - REACHABLE real entity: can mutate ✅
        - REMOTE real entity: cannot mutate ❌
        """
        attr = super().__getattribute__(name)
        
        # Only filter callable methods (not properties or private attributes)
        if not callable(attr) or name.startswith('_'):
            return attr
        
        # Get view and ghost status (using super() to avoid recursion)
        view = super().__getattribute__('_view')
        is_ghost = super().__getattribute__('_is_ghost')
        
        # Step 1: View-based filtering (proximity check)
        # REMOTE entities cannot perform mutations, including building ghosts
        if view == EntityView.REMOTE and name in BaseEntity._REACHABLE_ONLY:
            raise AttributeError(
                f"Cannot {name}() remotely. Entity not reachable. "
                "Use reachable_entities.get_entity() for full access."
            )
        
        # Step 2: Ghost-based filtering (state check)
        # Ghosts cannot be mutated (they have no live state), but can be built/removed if REACHABLE
        if is_ghost and name in BaseEntity._GHOST_BLOCKED:
            raise AttributeError(
                f"Cannot {name}() on ghost entity. "
                "Ghosts are placeholders - use build() first to create a real entity."
            )
        
        return attr

    def build(self) -> Dict[str, Any]:
        """Build ghost into real entity. Ghost-only.

        **For Agents**: Use this to commit a ghost and create a real entity.
        Only works on ghost entities (entity.is_ghost == True).

        Returns:
            ActionResult dict with success status
        """
        if not self._is_ghost:
            raise RuntimeError(
                f"Cannot build {self.name}: not a ghost entity. "
                "Use build() only on ghost entities."
            )
        
        if self._place_ops is None:
            raise RuntimeError(
                f"Cannot build {self.name}: place_ops not injected. "
                "Entity must be created with placement capabilities."
            )
        
        # Use ghost_name (what entity to create) for placement
        entity_name = self._ghost_name or self.name
        result = self._place_ops.place(
            entity_name,  # type: ignore
            self.position,
            self.direction,
            ghost=False,
        )
        return {"success": result.success}  # type: ignore

    def remove(self) -> bool:
        """Remove ghost entity. Ghost-only.

        **For Agents**: Use this to delete a ghost you no longer want.
        Only works on ghost entities (entity.is_ghost == True).

        Note: Ghost removal can be done remotely (no reachability required).

        Returns:
            True if successfully removed, False otherwise
        """
        if not self._is_ghost:
            raise RuntimeError(
                f"Cannot remove {self.name} via remove(): not a ghost entity. "
                "Use pickup() to remove real entities."
            )
        
        if self._place_ops is None:
            raise RuntimeError(
                f"Cannot remove {self.name}: place_ops not injected. "
                "Entity must be created with placement capabilities."
            )
        
        entity_name = self._ghost_name or self.name
        result = self._place_ops.remove_ghost(entity_name, self.position)
        return result.success

    def pickup(self) -> List["ItemStack"]:
        """Pick up the entity and return extracted items.

        **For Agents**: Use this to remove an entity and get its contents.
        Entity must be reachable for this to work.

        Returns:
            List of ItemStack objects representing items extracted from the entity
        """
        if self._entity_ops is None:
            raise RuntimeError(
                f"Cannot pickup {self.__class__.__name__}: entity_ops not injected. "
                "Entity must be reachable."
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
        """Show entity with view prefix (Reachable or Remote), with GHOST: prefix for ghosts."""
        pos = self.position
        prefix = self._view.value.capitalize()
        entity_name = f"GHOST:{self.__class__.__name__}" if self._is_ghost else self.__class__.__name__
        dir_str = f", direction={self.direction.name}" if self.direction is not None else ""
        return f"{prefix}[{entity_name}](name='{self.name}', position=({pos.x}, {pos.y}){dir_str})"
