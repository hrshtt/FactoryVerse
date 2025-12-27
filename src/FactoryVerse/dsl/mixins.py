"""DSL Mixins for reducing duplication and improving cohesion.

These mixins provide common functionality across Items, Entities, and other DSL objects.
They are designed with agent interaction in mind - docstrings explain WHEN and WHY
agents should use each method, not just WHAT it does.
"""

from abc import ABC, abstractmethod
from typing import (
    TYPE_CHECKING,
    Optional,
    List,
    Tuple,
    Literal,
)
from FactoryVerse.dsl.types import (
    MapPosition,
    Direction,
)
from FactoryVerse.dsl.prototypes import BasePrototype

if TYPE_CHECKING:
    from .entity.base_entity import EntityPosition
    from FactoryVerse.dsl.item.base import Item, ItemStack
    from FactoryVerse.agent.actions.entity_operations import EntityOperationsAction


class SpatialPropertiesMixin:
    """Provides tile-based spatial properties from prototype data."""

    # This mixin requires the class to have a 'prototype' property
    prototype: BasePrototype

    @property
    @abstractmethod
    def position(self) -> "EntityPosition": ...

    @property
    def tile_width(self) -> int:
        """Get tile width from prototype."""
        return self.prototype.tile_width

    @property
    def tile_height(self) -> int:
        """Get tile height from prototype."""
        return self.prototype.tile_height

    @property
    def footprint(self) -> Tuple[int, int]:
        """Get (width, height) tuple for convenient spatial calculations."""
        return (self.tile_width, self.tile_height)

    @property
    def area(self) -> int:
        """Get total tile area occupied by this entity."""
        return self.tile_width * self.tile_height


class PrototypeMixin(ABC):
    """Provides lazy-loaded prototype caching with type-specific loading logic."""

    _prototype_cache: Optional[BasePrototype]
    name: str  # Required by subclasses

    @property
    def prototype(self) -> BasePrototype:
        """Get cached prototype with lazy loading."""
        if not hasattr(self, "_prototype_cache") or self._prototype_cache is None:
            self._prototype_cache = self._load_prototype()
        return self._prototype_cache

    @abstractmethod
    def _load_prototype(self) -> BasePrototype:
        """Load prototype based on type-specific logic."""
        pass


class DirectionMixin:
    """Provides direction-aware spatial operations and semantics."""

    direction: Optional[Direction]  # Required by subclasses
    position: "EntityPosition"  # Required by subclasses
    name: str  # Required by subclasses

    @abstractmethod
    def is_direction_invariant(self) -> bool:
        """Return True if rotation has no functional effect."""
        pass

    def get_facing_position(self, distance: float = 1.0) -> MapPosition:
        """Get position in the direction this entity is facing."""
        if self.is_direction_invariant():
            raise ValueError(
                f"{self.name} is direction-invariant; it has no facing direction. "
                "Use is_direction_invariant() to check before calling this method."
            )

        if self.direction is None:
            raise ValueError(f"{self.name} has no direction set")

        return self._calculate_directional_offset(self.direction, distance)

    def get_opposite_position(self, distance: float = 1.0) -> MapPosition:
        """Get position opposite to the facing direction."""
        if self.is_direction_invariant():
            raise ValueError(f"{self.name} is direction-invariant; no facing direction")

        if self.direction is None:
            raise ValueError(f"{self.name} has no direction set")

        opposite = self._get_opposite_direction(self.direction)
        return self._calculate_directional_offset(opposite, distance)

    def rotate(self, clockwise: bool = True) -> Direction:
        """Rotate entity and return new direction."""
        if self.direction is None:
            raise ValueError(f"{self.name} has no direction to rotate")

        if clockwise:
            self.direction = self.direction.turn_right()
        else:
            self.direction = self.direction.turn_left()

        return self.direction

    def _calculate_directional_offset(
        self, direction: Direction, distance: float
    ) -> MapPosition:
        """Calculate position offset in given direction."""
        offsets = {
            Direction.NORTH: (0, -distance),
            Direction.EAST: (distance, 0),
            Direction.SOUTH: (0, distance),
            Direction.WEST: (-distance, 0),
        }

        if direction not in offsets:
            raise ValueError(f"Direction must be cardinal, got {direction}")

        dx, dy = offsets[direction]
        return MapPosition(self.position.x + dx, self.position.y + dy)

    def _get_opposite_direction(self, direction: Direction) -> Direction:
        """Get opposite direction."""
        opposites = {
            Direction.NORTH: Direction.SOUTH,
            Direction.SOUTH: Direction.NORTH,
            Direction.EAST: Direction.WEST,
            Direction.WEST: Direction.EAST,
        }
        return opposites[direction]


# InspectableMixin removed - inspect() is now handled by view wrappers
# Each BaseEntity subclass implements _format_inspection() for entity-specific formatting


class FuelableMixin:
    """Provides fuel management with validation for burner entities.

    Requires:
    - _entity_ops: EntityOperationsAction (injected by Reachable view wrapper)
    - name: str
    - position: "EntityPosition"
    """

    _entity_ops: Optional["EntityOperationsAction"]  # Injected by view wrapper
    name: str  # Required by subclasses
    position: "EntityPosition"  # Required by subclasses

    @abstractmethod
    def _get_accepted_fuel_categories(self) -> List[str]:
        """Return accepted fuel categories for this entity."""
        pass

    def add_fuel(self, items: List["ItemStack"]) -> List:
        """Add fuel to the entity with validation.

        **For Agents**: Use this to fuel burner entities (furnaces, drills, etc.).
        The mixin validates that the fuel is compatible with this entity type.
        """
        if self._entity_ops is None:
            raise RuntimeError(
                f"Cannot add fuel to {self.__class__.__name__}: entity_ops not injected. "
                "Entity must be wrapped in a view (Reachable) for fuel operations."
            )

        results = []
        for item in items:
            # Validate fuel type
            self._validate_fuel(item.name)

            result = self._entity_ops.put_inventory_item(
                self.name, "fuel", item, self.position
            )
            results.append(result)
        return results

    def _validate_fuel(self, item_name: str):
        """Validate that item is valid fuel for this entity."""
        from FactoryVerse.dsl.prototypes import get_item_prototypes

        item_protos = get_item_prototypes()

        # Check if item is fuel at all
        if not item_protos.is_fuel(item_name):
            valid_fuels = item_protos.get_fuel_items()
            raise ValueError(
                f"Cannot add '{item_name}' as fuel to {self.name}. "
                f"Valid fuel items: {', '.join(sorted(valid_fuels))}"
            )

        # Check fuel category
        fuel_category = item_protos.get_fuel_category(item_name)
        accepted_categories = self._get_accepted_fuel_categories()

        if fuel_category not in accepted_categories:
            raise ValueError(
                f"Cannot add '{item_name}' (fuel_category={fuel_category}) to {self.name}. "
                f"Accepted fuel categories: {', '.join(accepted_categories)}"
            )


class ContainerMixin:
    """Provides inventory management for container entities.

    Requires:
    - _entity_ops: EntityOperationsAction (injected by Reachable view wrapper)
    - name: str
    - position: "EntityPosition"
    """

    _entity_ops: Optional["EntityOperationsAction"]  # Injected by view wrapper
    name: str  # Required by subclasses
    position: "EntityPosition"  # Required by subclasses

    @abstractmethod
    def _get_inventory_type(self) -> str:
        """Return inventory type for this entity.

        Returns:
            Inventory type: 'chest', 'input', 'output', 'fuel', etc.
        """
        pass

    def store_items(self, items: List["ItemStack"]) -> List:
        """Store items in the entity's inventory.

        **For Agents**: Use this to put items into chests or containers.
        """
        if self._entity_ops is None:
            raise RuntimeError(
                f"Cannot store items in {self.__class__.__name__}: entity_ops not injected. "
                "Entity must be wrapped in a view (Reachable) for inventory operations."
            )

        inventory_type = self._get_inventory_type()
        result = self._entity_ops.put_inventory_item(
            self.name, inventory_type, items, self.position
        )
        # Return as list for consistency
        return result if isinstance(result, list) else [result]

    def take_items(self, items: List["ItemStack"]) -> List["ItemStack"]:
        """Take items from the entity's inventory.

        **For Agents**: Use this to extract items from chests or containers.
        """
        if self._entity_ops is None:
            raise RuntimeError(
                f"Cannot take items from {self.__class__.__name__}: entity_ops not injected. "
                "Entity must be wrapped in a view (Reachable) for inventory operations."
            )

        results = []
        inventory_type = self._get_inventory_type()
        for item in items:
            response = self._entity_ops.take_inventory_item(
                self.name, inventory_type, item.name, item.count, self.position
            )
            # Convert response to ItemStacks
            results.extend(response.to_item_stacks())
        return results


class CrafterMixin:
    """Provides crafting input/output management for production entities.

    Requires:
    - _entity_ops: EntityOperationsAction (injected by Reachable view wrapper)
    - name: str
    - position: "EntityPosition"
    """

    _entity_ops: Optional["EntityOperationsAction"]  # Injected by view wrapper
    name: str  # Required by subclasses
    position: "EntityPosition"  # Required by subclasses

    def add_ingredients(self, items: List["ItemStack"]) -> List:
        """Add ingredients to the entity's input buffer.

        **For Agents**: Use this to supply materials to crafting machines.
        """
        if self._entity_ops is None:
            raise RuntimeError(
                f"Cannot add ingredients to {self.__class__.__name__}: entity_ops not injected. "
                "Entity must be wrapped in a view (Reachable) for crafting operations."
            )

        result = self._entity_ops.put_inventory_item(
            self.name, "input", items, self.position
        )
        # Return as list for consistency
        return result if isinstance(result, list) else [result]

    def take_products(
        self, items: Optional[List["ItemStack"]] = None
    ) -> List["ItemStack"]:
        """Take products from the entity's output buffer.

        **For Agents**: Use this to collect finished products from crafting machines.
        If items is None, takes everything from the output.
        """
        if self._entity_ops is None:
            raise RuntimeError(
                f"Cannot take products from {self.__class__.__name__}: entity_ops not injected. "
                "Entity must be wrapped in a view (Reachable) for crafting operations."
            )

        from FactoryVerse.dsl.item.base import ItemStack

        if items is None:
            # If no items specified, inspect and take everything
            data = self._entity_ops.inspect_entity(self.name, self.position)
            output_inv = data.get("inventories", {}).get("output", {})

            items = [
                ItemStack(item_name, count) for item_name, count in output_inv.items()
            ]

        results = []
        for item in items:
            response = self._entity_ops.take_inventory_item(
                self.name, "output", item.name, item.count, self.position
            )
            # Convert response to ItemStacks
            results.extend(response.to_item_stacks())
        return results


class OutputPositionMixin:
    """Provides output position calculation for production entities."""

    direction: Optional[Direction]  # Required by subclasses
    position: "EntityPosition"  # Required by subclasses

    @abstractmethod
    def _get_output_type(self) -> Literal["item", "fluid"]:
        """Return output type for this entity."""
        pass

    @property
    @abstractmethod
    def output_position(self) -> MapPosition:
        """Get primary output position based on direction."""
        pass
