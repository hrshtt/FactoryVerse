"""View wrappers for entity access control.

This module defines view wrappers that control HOW you can interact with entities
based on access level:
- Reachable[T]: Full access - can mutate entity state
- RemoteView[T]: Read-only access - can inspect but not mutate
- Ghost[T]: Blueprint/planning access - static data only
"""

from typing import Generic, TypeVar, TYPE_CHECKING
from FactoryVerse.dsl.types import ActionResult
from FactoryVerse.dsl.mixins import FuelableMixin, CrafterMixin, ContainerMixin

if TYPE_CHECKING:
    from FactoryVerse.agent.actions.entity_operations import EntityOperationsAction
    from FactoryVerse.agent.actions.place_entity import PlacementAction
    from .base_entity import BaseEntity

T = TypeVar("T", bound="BaseEntity")


class Reachable(Generic[T]):
    """Full access view - allows everything.

    Pure filter that injects action dependencies and passes all attributes through.

    **For Agents**: This is what you get from reachable_entities.get_entity().
    You have full control over the entity and can perform all operations.
    """

    def __init__(
        self,
        entity: T,
        entity_ops: "EntityOperationsAction",
        place_ops: "PlacementAction",
    ):
        """Initialize reachable view wrapper.

        Args:
            entity: Base entity instance to wrap
            entity_ops: Entity operations action for game interactions
            place_ops: Place entity action for placement operations
        """
        self._entity = entity
        # Inject dependencies so entity methods work
        self._entity._entity_ops = entity_ops  # type: ignore
        self._entity._place_ops = place_ops  # type: ignore
        # Inject into mixins for their methods
        if isinstance(self._entity, (FuelableMixin, CrafterMixin, ContainerMixin)):
            self._entity._entity_ops = entity_ops  # type: ignore

    def __getattr__(self, name):
        """Delegate all attributes to wrapped entity.

        This allows transparent access to entity properties and methods.
        No filtering - everything passes through.
        """
        return getattr(self._entity, name)

    def __repr__(self) -> str:
        """Show as Reachable[EntityType]."""
        return f"Reachable[{self._entity.__class__.__name__}](name='{self._entity.name}', position={self._entity.position})"


class RemoteView(Generic[T]):
    """Read-only view - filters out all mutating operations.

    Pure filter that injects entity_ops for inspection and blocks mutations.

    Provides:
    - inspect() with live game data (read-only)
    - Spatial properties (position, direction, tile_width, etc.)
    - Prototype data
    - Entity-specific properties (e.g., drop_position for inserters)

    Blocks:
    - All mutating operations (pickup, add_fuel, add_ingredients, store_items, etc.)

    **For Agents**: This is what you get from map_db queries for entities
    that are not within reach. You can see their status but cannot interact with them.
    """

    def __init__(self, entity: T, entity_ops: "EntityOperationsAction"):
        """Initialize remote view wrapper.

        Args:
            entity: Base entity instance to wrap
            entity_ops: Entity operations action for inspection
        """
        self._entity = entity
        # Inject entity_ops for inspect() to work
        self._entity._entity_ops = entity_ops  # type: ignore

    def __getattr__(self, name):
        """Delegate to entity, but block mutating operations."""
        # Block all mutating operations
        blocked = {
            "pickup",
            "add_fuel",
            "add_ingredients",
            "take_products",
            "store_items",
            "take_items",
            "set_recipe",
        }

        if name in blocked:
            raise AttributeError(
                f"RemoteView blocks {name}(). Entity not reachable. "
                f"Use reachable_entities.get_entity() for full access."
            )

        # Allow everything else (inspect, spatial properties, entity-specific properties)
        return getattr(self._entity, name)

    def __repr__(self) -> str:
        """Show as RemoteView[EntityType]."""
        return f"RemoteView[{self._entity.__class__.__name__}](name='{self._entity.name}', position={self._entity.position})"


class Ghost(Generic[T]):
    """Planning view - filters operations, adds ghost-specific methods.

    Pure filter that blocks all operations and provides ghost-specific methods.

    Provides:
    - Spatial calculations (critical for planning layouts)
    - Entity-specific properties (e.g., drop_position for inserters)
    - build() to construct the ghost into a real entity
    - remove() to delete the ghost

    Blocks:
    - All operational methods (inspect, pickup, add_fuel, etc.)

    **For Agents**: This is what you get when placing entities with ghost=True
    or from ghost_manager. Use for planning layouts before committing resources.
    """

    def __init__(
        self,
        entity: T,
        entity_ops: "EntityOperationsAction",
        place_ops: "PlacementAction",
    ):
        """Initialize ghost view wrapper.

        Args:
            entity: Base entity instance to wrap
            entity_ops: Entity operations action for ghost removal
            place_ops: Place entity action for building
        """
        self._entity = entity
        # Store ops for ghost-specific methods
        self._entity_ops = entity_ops
        self._place_ops = place_ops
        # DON'T inject into entity - ghosts don't have live operations

    def build(self) -> ActionResult:
        """Build the ghost into a real entity.

        **For Agents**: Use this to commit the ghost and create a real entity.

        Returns:
            ActionResult with success status
        """
        result = self._place_ops.place(
            self._entity.name,  # type: ignore
            self._entity.position,
            self._entity.direction,
            ghost=False,
        )
        return {"success": result.success}  # type: ignore

    def remove(self) -> bool:
        """Remove the ghost.

        **For Agents**: Use this to delete a ghost you no longer want.

        Returns:
            True if successfully removed, False otherwise
        """
        result = self._place_ops.remove_ghost(self._entity.name, self._entity.position)
        return result.success

    def __getattr__(self, name):
        """Delegate spatial/entity-specific properties, block all operations."""
        # Block ALL operations including inspect
        blocked_operations = {
            "inspect",
            "pickup",
            "add_fuel",
            "add_ingredients",
            "take_products",
            "store_items",
            "take_items",
            "set_recipe",
        }

        if name in blocked_operations:
            if name == "inspect":
                raise AttributeError(
                    "Ghost view blocks inspect(). Use inspect_ghost() for static reference."
                )
            raise AttributeError(
                f"Ghost view blocks {name}(). Ghosts are for planning only."
            )

        return getattr(self._entity, name)

    def __repr__(self) -> str:
        """Show as Ghost[EntityType]."""
        return f"Ghost[{self._entity.__class__.__name__}](name='{self._entity.name}', position={self._entity.position})"
