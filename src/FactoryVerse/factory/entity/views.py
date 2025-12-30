"""View wrappers for entity access control.

This module defines view wrappers that control HOW you can interact with entities
based on access level:
- Reachable[T]: Full access - can mutate entity state, build/remove ghosts
- RemoteView[T]: Read-only access - can inspect but not mutate, can remove ghosts
"""

from typing import Generic, TypeVar, TYPE_CHECKING
from FactoryVerse.factory.types import ActionResult
from FactoryVerse.factory.mixins import FuelableMixin, CrafterMixin, ContainerMixin

if TYPE_CHECKING:
    from FactoryVerse.agent.actions.entity_operations import EntityOperationsAction
    from FactoryVerse.agent.actions.place_entity import PlacementAction
    from .base_entity import BaseEntity

T = TypeVar("T", bound="BaseEntity")


class Reachable(Generic[T]):
    """Full access view - allows everything.

    Pure filter that injects action dependencies and passes all attributes through.
    For ghost entities, provides build() and remove() methods.

    **For Agents**: This is what you get from reachable_entities.get_entity().
    You have full control over the entity and can perform all operations.

    For ghost entities (entity.is_ghost == True):
    - build(): Construct the ghost into a real entity
    - remove(): Delete the ghost
    - inspect(): Returns static ghost data (ghosts have no live state)
    - All other mutations error (ghosts are placeholders, not real entities)
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
        self._entity_ops = entity_ops
        self._place_ops = place_ops

        # Inject dependencies so entity methods work (for non-ghosts)
        if not entity._is_ghost:
            self._entity._entity_ops = entity_ops  # type: ignore
            self._entity._place_ops = place_ops  # type: ignore
            # Inject into mixins for their methods
            if isinstance(self._entity, (FuelableMixin, CrafterMixin, ContainerMixin)):
                self._entity._entity_ops = entity_ops  # type: ignore

    def build(self) -> ActionResult:
        """Build the ghost into a real entity (ghost entities only).

        **For Agents**: Use this to commit a ghost and create a real entity.
        Only works on ghost entities (entity.is_ghost == True).

        Returns:
            ActionResult with success status
        """
        if not self._entity._is_ghost:
            raise RuntimeError(
                f"Cannot build {self._entity.name}: not a ghost entity. "
                "Use build() only on ghost entities."
            )

        # Use ghost_name (what entity to create) for placement
        entity_name = self._entity._ghost_name or self._entity.name
        result = self._place_ops.place(
            entity_name,  # type: ignore
            self._entity.position,
            self._entity.direction,
            ghost=False,
        )
        return {"success": result.success}  # type: ignore

    def remove(self) -> bool:
        """Remove the ghost entity (ghost entities only).

        **For Agents**: Use this to delete a ghost you no longer want.
        Only works on ghost entities (entity.is_ghost == True).

        Returns:
            True if successfully removed, False otherwise
        """
        if not self._entity._is_ghost:
            raise RuntimeError(
                f"Cannot remove {self._entity.name} via remove(): not a ghost entity. "
                "Use pickup() to remove real entities."
            )

        entity_name = self._entity._ghost_name or self._entity.name
        result = self._place_ops.remove_ghost(entity_name, self._entity.position)
        return result.success

    def __getattr__(self, name):
        """Delegate all attributes to wrapped entity.

        For ghost entities, blocks mutating operations.
        """
        # For ghost entities, block all mutations except build/remove
        if self._entity._is_ghost:
            blocked_for_ghosts = {
                "pickup",
                "add_fuel",
                "add_ingredients",
                "take_products",
                "store_items",
                "take_items",
                "set_recipe",
            }
            if name in blocked_for_ghosts:
                raise AttributeError(
                    f"Cannot {name}() on ghost entity. "
                    "Ghosts are placeholders - use build() first to create a real entity."
                )

        return getattr(self._entity, name)

    def __repr__(self) -> str:
        """Show as Reachable[EntityType]."""
        ghost_marker = " [GHOST]" if self._entity._is_ghost else ""
        return f"Reachable[{self._entity.__class__.__name__}](name='{self._entity.name}', position={self._entity.position}){ghost_marker}"


class RemoteView(Generic[T]):
    """Read-only view - filters out all mutating operations.

    Pure filter that injects entity_ops for inspection and blocks mutations.
    For ghost entities, provides remove() method.

    Provides:
    - inspect() with live game data (read-only), static for ghosts
    - Spatial properties (position, direction, tile_width, etc.)
    - Prototype data
    - Entity-specific properties (e.g., drop_position for inserters)
    - remove() for ghost entities only

    Blocks:
    - All mutating operations (pickup, add_fuel, add_ingredients, store_items, etc.)
    - build() for ghosts (requires reachability)

    **For Agents**: This is what you get from map_db queries for entities
    that are not within reach. You can see their status but cannot interact with them.
    """

    def __init__(
        self,
        entity: T,
        entity_ops: "EntityOperationsAction",
        place_ops: "PlacementAction | None" = None,
    ):
        """Initialize remote view wrapper.

        Args:
            entity: Base entity instance to wrap
            entity_ops: Entity operations action for inspection
            place_ops: Optional place ops for ghost removal
        """
        self._entity = entity
        self._entity_ops = entity_ops
        self._place_ops = place_ops

        # Inject entity_ops for inspect() to work (for non-ghosts)
        if not entity._is_ghost:
            self._entity._entity_ops = entity_ops  # type: ignore

    def remove(self) -> bool:
        """Remove the ghost entity (ghost entities only).

        **For Agents**: Use this to delete a ghost you no longer want.
        Only works on ghost entities (entity.is_ghost == True).

        Note: Ghost removal can be done remotely (no reachability required).

        Returns:
            True if successfully removed, False otherwise
        """
        if not self._entity._is_ghost:
            raise RuntimeError(
                f"Cannot remove {self._entity.name} via remove(): not a ghost entity. "
                "RemoteView cannot remove real entities."
            )

        if self._place_ops is None:
            raise RuntimeError(
                "Cannot remove ghost: place_ops not available. "
                "This RemoteView was not initialized with placement capabilities."
            )

        entity_name = self._entity._ghost_name or self._entity.name
        result = self._place_ops.remove_ghost(entity_name, self._entity.position)
        return result.success

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

        # For ghost entities, also block build (requires reachability)
        if self._entity._is_ghost and name == "build":
            raise AttributeError(
                "RemoteView blocks build() on ghosts. "
                "You must be near the ghost to build it. "
                "Use reachable_entities.get_entity() to get a buildable ghost."
            )

        # Allow everything else (inspect, spatial properties, entity-specific properties)
        return getattr(self._entity, name)

    def __repr__(self) -> str:
        """Show as RemoteView[EntityType]."""
        ghost_marker = " [GHOST]" if self._entity._is_ghost else ""
        return f"RemoteView[{self._entity.__class__.__name__}](name='{self._entity.name}', position={self._entity.position}){ghost_marker}"
