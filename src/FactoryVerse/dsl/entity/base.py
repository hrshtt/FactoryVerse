from __future__ import annotations
import math
from abc import ABC, abstractmethod
from typing import List, Optional, Union, Literal, Dict, Any, TYPE_CHECKING
from FactoryVerse.dsl.types import (
    MapPosition, BoundingBox, Direction, Position, AsyncActionResponse,
    EntityInspectionData, ActionResult
)
from FactoryVerse.dsl.item.base import PlaceableItemName, ItemName, Item, ItemStack, PlaceableItem
from FactoryVerse.dsl.mixins import (
    FactoryContextMixin,
    SpatialPropertiesMixin,
    PrototypeMixin,
    DirectionMixin,
    InspectableMixin,
    FuelableMixin,
    InventoryMixin,
    CrafterMixin,
    OutputPositionMixin
)
from FactoryVerse.dsl.prototypes import (
    get_entity_prototypes,
    ElectricMiningDrillPrototype,
    BurnerMiningDrillPrototype,
    PumpjackPrototype,
    InserterPrototype,
    LongHandedInserterPrototype,
    FastInserterPrototype,
    TransportBeltPrototype,
    BasePrototype,
)

if TYPE_CHECKING:
    from FactoryVerse.dsl.agent import PlayingFactory
    from FactoryVerse.dsl.recipe.base import BaseRecipe as Recipe

# from FactoryVerse.dsl.agent import _playing_factory


class EntityPosition(MapPosition):
    """Position with entity-aware spatial operations.
    
    High-level position type that knows about entities, items, and prototypes.
    Provides spatial reasoning for placement and layout calculations.
    MapPosition remains pure - this handles the DSL-aware logic.
    
    Can be bound to a parent entity, making offset calculations more ergonomic:
        furnace.position.offset_by_entity(direction=Direction.NORTH)
    """
    
    def __init__(self, x: float, y: float, entity: Optional[Union["ReachableEntity", PlaceableItem]] = None):
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
        entity: Optional[Union["ReachableEntity", PlaceableItem, BasePrototype]] = None,
        direction: Direction = None,
        gap: int = 0
    ) -> "EntityPosition":
        """Calculate position offset by entity dimensions in a cardinal direction.
        
        Uses parent entity dimensions if no entity is provided.
        
        Args:
            entity: Entity, item, or prototype to get dimensions from (uses parent if None)
            direction: Cardinal direction to offset (NORTH/SOUTH/EAST/WEST)
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
            raise ValueError(f"Cannot offset in non-cardinal direction: {direction.name}")
        
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


class ReachableEntity(FactoryContextMixin, SpatialPropertiesMixin, PrototypeMixin, ABC):
    """Base class for all reachable entities.
    
    Entities are things placed in the world with position and direction.
    They have prototypes that define their properties and behavior.
    
    **For Agents**: Entities are objects in the game world (furnaces, drills, chests, etc.).
    Use inspect() to check their status, and entity-specific methods to interact with them.
    """

    def __init__(
        self,
        name: str,
        position: MapPosition,
        direction: Optional[Direction] = None,
        **kwargs  # For backward compatibility with subclasses
    ):
        self.name = name
        self._raw_position = position  # Store raw position internally
        self.direction = direction
        self._prototype_cache: Optional[BasePrototype] = None
        
        # Handle any additional kwargs for subclasses
        for key, value in kwargs.items():
            setattr(self, key, value)
    
    @property
    def position(self) -> EntityPosition:
        """Get the entity's position as an EntityPosition bound to this entity.
        
        **For Agents**: Use this for spatial calculations:
        - next_pos = entity.position.offset_by_entity(direction=Direction.NORTH)
        - distance = entity.position.distance_to(other_pos)
        """
        return EntityPosition(x=self._raw_position.x, y=self._raw_position.y, entity=self)

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

    def __repr__(self) -> str:
        """Simple, explicit representation of the entity."""
        pos = self.position
        if self.direction is not None:
            return f"{self.__class__.__name__}(name='{self.name}', position=({pos.x}, {pos.y}), direction={self.direction.name})"
        else:
            return f"{self.__class__.__name__}(name='{self.name}', position=({pos.x}, {pos.y}))"

    def inspect(self, raw_data: bool = False) -> Union[str, EntityInspectionData]:
        """Inspect current state of the object.
        
        **For Agents**: This is your primary diagnostic tool. Use it to:
        - Check if machines are working or idle
        - See inventory contents (fuel, input, output)
        - Monitor progress (crafting, mining, research)
        - Diagnose problems (no-power, no-fuel, no-ingredients)
        
        Args:
            raw_data: If False (default), returns formatted string for reading.
                     If True, returns raw dictionary for programmatic access.
        
        Returns:
            Formatted string or EntityInspectionData TypedDict
        
        **Formatted Output Includes**:
        - Entity name and position
        - Status (working, no-power, no-fuel, etc.)
        - Progress (crafting, mining, burning)
        - Inventories (fuel, input, output, chest)
        - Energy state (for electric entities)
        """
        result = self._get_inspection_data()
        if raw_data:
            return result
        return self._format_inspection(result)
    
    def _get_inspection_data(self) -> EntityInspectionData:
        """Get raw inspection data from the game.
        
        Default implementation calls factory.inspect_entity().
        Subclasses can override for custom inspection logic.
        """
        return self._factory.inspect_entity(self.name, self.position)
    
    def _format_inspection(self, data: EntityInspectionData, raw_data: bool = False) -> str:
        """Format inspection data for agent readability.
        
        Note: Subclasses should override this method to provide entity-specific
        inspection details. This default implementation provides basic information.
        """
        if raw_data:
            return data
        
        lines = [
            f"{self.__class__.__name__}({self.name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]
        
        status = data.get("status", "unknown")
        lines.append(f"  Status: {status}")
        
        return "\n".join(lines)

    def pickup(self) -> List[ItemStack]:
        """Pick up the entity and return items added to inventory.
        
        Returns:
            List of ItemStack objects representing items extracted from the entity
        """
        return self._factory.pickup_entity(self.name, self.position)

class GhostEntity(ReachableEntity):
    """A ghost entity."""

    def __init__(
        self,
        name: str,
        position: MapPosition,
        direction: Optional[Direction] = None,
        label: Optional[str] = None,
        placed_tick: int = 0,
        **kwargs
    ):
        super().__init__(name, position, direction, **kwargs)
        self.label = label
        self.placed_tick = placed_tick

    def remove(self) -> bool:
        """Remove the ghost entity."""
        return self._factory.remove_ghost(self.name, self.position).get("success", False)
    
    def build(self) -> AsyncActionResponse:
        """Build the ghost entity."""
        return self._factory.place_entity(self.name, self.position, ghost=False)

    def inspect(self, raw_data: bool = False) -> Union[str, EntityInspectionData]:
        """Return a representation of ghost entity state.
        
        Args:
            raw_data: If False (default), returns a formatted string representation.
                      If True, returns the raw dictionary data.
        
        Returns:
            If raw_data=False: Formatted string representation
            If raw_data=True: Dictionary with entity inspection data (see ReachableEntity.inspect for schema)
        """
        if raw_data:
            return self._factory.inspect_entity(self.name, self.position)
        return f"GhostEntity(name='{self.name}', position=({self.position.x:.1f}, {self.position.y:.1f}))"

class Container(InventoryMixin, InspectableMixin, ReachableEntity):
    """A container entity with inventory.
    
    **For Agents**: Chests store items. Use store_items() and take_items() to move items in/out.
    """

    def __init__(
        self,
        name: str,
        position: MapPosition,
        direction: Optional[Direction] = None,
        inventory_size: int = 0,
        **kwargs
    ):
        super().__init__(name, position, direction, **kwargs)
        self.inventory_size = inventory_size

    def _get_inventory_type(self) -> str:
        """Containers use 'chest' inventory type."""
        return 'chest'



    def _format_inspection(self, data: Dict[str, Any]) -> str:
        """Format container inspection data for agent readability."""
        lines = [
            f"Container({self.name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]
        
        # Status
        status = data.get("status", "unknown")
        lines.append(f"  Status: {status}")
        
        # Contents
        inventories = data.get("inventories", {})
        contents = inventories.get("chest", {})
        if contents:
            contents_str = ", ".join([f"{name}: {count}" for name, count in contents.items()])
            lines.append(f"  Contents: {contents_str}")
        else:
            lines.append("  Contents: (empty)")
        
        return "\n".join(lines)

class WoodenChest(Container): ...

class IronChest(Container): ...


class ShipWreck(Container):
    """A ship wreck entity (crash-site entities)."""
    ...


class Furnace(CrafterMixin, InspectableMixin, FuelableMixin, ReachableEntity):
    """A furnace entity.
    
    **For Agents**: Furnaces smelt ore into plates. They accept any fuel type (chemical or nuclear).
    Use add_fuel() and add_ingredients() to operate them.
    """

    # CANDO: Consider accepting List[Item] and List[ItemStack] for add_ingredients
    # to work seamlessly with inventory.get_item_stacks() which returns List[ItemStack].
    # Would loop in Python and make multiple remote calls (one per item/stack), similar to
    # Container.store_items() pattern. Only implement if agents frequently fail on this use case.

    def _get_accepted_fuel_categories(self) -> List[str]:
        """Furnaces accept all fuel types."""
        return ['chemical', 'nuclear']




    def _format_inspection(self, data: Dict[str, Any]) -> str:
        """Format furnace inspection data for agent readability."""
        
        lines = [
            f"Furnace({self.name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]
        
        # Status
        status = data.get("status", "unknown")
        lines.append(f"  Status: {status}")
        
        # Recipe (if applicable)
        recipe = data.get("recipe")
        if recipe:
            lines.append(f"  Recipe: {recipe}")
        
        # Burner information (furnaces use burners)
        burner = data.get("burner")
        if burner:
            currently_burning = burner.get("currently_burning")
            remaining_fuel = burner.get("remaining_burning_fuel", 0)
            heat = burner.get("heat", 0)
            
            # Show currently burning if explicitly set, or if there's remaining fuel/heat
            # (indicates active burning even if currently_burning property is nil)
            if currently_burning:
                lines.append(f"  Currently Burning: {currently_burning}")
                burning_progress = burner.get("burning_progress")
                if burning_progress is not None:
                    lines.append(f"  Burning Progress: {burning_progress * 100:.1f}%")
                if remaining_fuel > 0:
                    lines.append(f"  Remaining Fuel Energy: {remaining_fuel:.0f} J")
            elif remaining_fuel > 0 or (heat > 0 and status == "working"):
                # Infer burning from remaining fuel or working status with heat
                # Try to get fuel name from fuel inventory
                inventories = data.get("inventories", {})
                fuel_inv = inventories.get("fuel", {})
                if fuel_inv:
                    # Use the first fuel item found
                    fuel_name = next(iter(fuel_inv.keys()), None)
                    if fuel_name:
                        lines.append(f"  Currently Burning: {fuel_name}")
                        if remaining_fuel > 0:
                            lines.append(f"  Remaining Fuel Energy: {remaining_fuel:.0f} J")
                    else:
                        lines.append("  Currently Burning: (active)")
                else:
                    lines.append("  Currently Burning: (active)")
            else:
                lines.append("  Currently Burning: (none)")
            
            heat_capacity = burner.get("heat_capacity", 0)
            if heat_capacity > 0:
                heat_pct = (heat / heat_capacity) * 100
                lines.append(f"  Heat: {heat:.0f}/{heat_capacity:.0f} ({heat_pct:.1f}%)")
        
        # Inventories
        inventories = data.get("inventories", {})
        
        # Fuel
        fuel = inventories.get("fuel", {})
        if fuel:
            fuel_str = ", ".join([f"{name}: {count}" for name, count in fuel.items()])
            lines.append(f"  Fuel: {fuel_str}")
        else:
            lines.append("  Fuel: (empty)")
        
        # Input
        input_inv = inventories.get("input", {})
        if input_inv:
            input_str = ", ".join([f"{name}: {count}" for name, count in input_inv.items()])
            lines.append(f"  Input: {input_str}")
        else:
            lines.append("  Input: (empty)")
        
        # Output
        output_inv = inventories.get("output", {})
        if output_inv:
            output_str = ", ".join([f"{name}: {count}" for name, count in output_inv.items()])
            lines.append(f"  Output: {output_str}")
        else:
            lines.append("  Output: (empty)")
        
        return "\n".join(lines)


class ElectricPole(InspectableMixin, ReachableEntity):
    """An electric pole entity."""

    def extend(self, direction: Direction, distance: Optional[float] = None) -> ActionResult:
        """Extend the electric pole to the given direction and distance.
        No distance = MAX possible for the entity"""
        raise NotImplementedError(
            "ElectricPole.extend() is not yet implemented. "
            "This method requires implementation in the Lua mod's RemoteInterface."
        )

    def _format_inspection(self, data: Dict[str, Any]) -> str:
        """Format electric pole inspection data for agent readability."""
        
        lines = [
            f"ElectricPole({self.name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]
        
        # Status
        status = data.get("status", "unknown")
        lines.append(f"  Status: {status}")
        
        # Energy (if applicable)
        energy = data.get("energy")
        if energy:
            current = energy.get("current", 0)
            capacity = energy.get("capacity", 0)
            if capacity > 0:
                energy_pct = (current / capacity) * 100
                lines.append(f"  Energy: {current:.0f}/{capacity:.0f} ({energy_pct:.1f}%)")
        
        return "\n".join(lines)


class Inserter(InspectableMixin, ReachableEntity):
    """Base inserter entity."""

    @property
    def prototype(self) -> InserterPrototype:
        """Get the prototype for this inserter type."""
        return get_entity_prototypes().inserter

    def get_drop_position(self) -> MapPosition:
        """Get the output position of the inserter."""
        if self.direction is None:
            raise ValueError("Inserter direction must be set to calculate drop position")
        return self.prototype.drop_position(self.position, self.direction)

    def get_pickup_position(self) -> MapPosition:
        """Get the input position of the inserter."""
        if self.direction is None:
            raise ValueError("Inserter direction must be set to calculate pickup position")
        return self.prototype.pickup_position(self.position, self.direction)

    def _format_inspection(self, data: Dict[str, Any]) -> str:
        """Format inserter inspection data for agent readability."""
        
        lines = [
            f"Inserter({self.name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]
        
        # Status
        status = data.get("status", "unknown")
        lines.append(f"  Status: {status}")
        
        # Held item
        held_item = data.get("held_item")
        if held_item:
            lines.append(f"  Held Item: {held_item['name']} x{held_item['count']}")
        else:
            lines.append("  Held Item: (none)")
        
        return "\n".join(lines)


class FastInserter(Inserter):
    """Fast inserter entity."""

    @property
    def prototype(self) -> FastInserterPrototype:
        """Get the prototype for this long-handed inserter type."""
        return get_entity_prototypes().fast_inserter


class LongHandInserter(Inserter):
    """Long-handed inserter entity."""

    @property
    def prototype(self) -> LongHandedInserterPrototype:
        """Get the prototype for this long-handed inserter type."""
        return get_entity_prototypes().long_handed_inserter

class ProcessingMachine(CrafterMixin, InspectableMixin, ReachableEntity):
    """Base class for entities that process recipes (assemblers, chemical plants, etc)."""

    def set_recipe(self, recipe: Union[str, "Recipe"]) -> str:
        """Set the recipe of the machine (synchronous).
        
        Args:
            recipe: Recipe name (string) or Recipe object with .name attribute
        """
        # Handle string, Recipe object, or None
        if recipe is None:
            recipe_name = None
        elif isinstance(recipe, str):
            recipe_name = recipe
        elif hasattr(recipe, 'name'):
            recipe_name = recipe.name
        else:
            raise ValueError(f"recipe must be a string, Recipe object, or None, got {type(recipe)}")
        
        return self._factory.set_entity_recipe(self.name, self.position, recipe_name)

    def get_recipe(self) -> Optional[str]:
        """Get the current recipe of the machine.
        
        Note: This method is not yet fully implemented.
        To get recipe information, use inspect() and check the 'recipe' field.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__}.get_recipe() is not yet fully implemented in the DSL. "
            "To get recipe information, use inspect() and check the 'recipe' field."
        )

    def _format_processing_inspection(self, data: Dict[str, Any], header: str) -> str:
        """Shared inspection formatting for all processing machines."""
        lines = [header]
        
        # Status
        status = data.get("status", "unknown")
        lines.append(f"  Status: {status}")
        
        # Recipe
        recipe = data.get("recipe")
        if recipe:
            lines.append(f"  Recipe: {recipe}")
        else:
            lines.append("  Recipe: (none)")
        
        # Crafting progress
        crafting_progress = data.get("crafting_progress")
        if crafting_progress is not None:
            lines.append(f"  Crafting Progress: {crafting_progress * 100:.1f}%")
        
        # Productivity bonus
        productivity_bonus = data.get("productivity_bonus")
        if productivity_bonus and productivity_bonus > 0:
            lines.append(f"  Productivity Bonus: {productivity_bonus * 100:.1f}%")
        
        # Inventories
        inventories = data.get("inventories", {})
        
        # Input
        input_inv = inventories.get("input", {})
        if input_inv:
            input_str = ", ".join([f"{name}: {count}" for name, count in input_inv.items()])
            lines.append(f"  Input: {input_str}")
        else:
            lines.append("  Input: (empty)")
        
        # Output
        output_inv = inventories.get("output", {})
        if output_inv:
            output_str = ", ".join([f"{name}: {count}" for name, count in output_inv.items()])
            lines.append(f"  Output: {output_str}")
        else:
            lines.append("  Output: (empty)")
        
        # Energy (if applicable)
        energy = data.get("energy")
        if energy:
            current = energy.get("current", 0)
            capacity = energy.get("capacity", 0)
            if capacity > 0:
                energy_pct = (current / capacity) * 100
                lines.append(f"  Energy: {current:.0f}/{capacity:.0f} ({energy_pct:.1f}%)")
        
        return "\n".join(lines)

class AssemblingMachine(ProcessingMachine):
    """An assembling machine entity."""

    def _format_inspection(self, data: Dict[str, Any]) -> str:
        """Format assembling machine inspection data for agent readability."""
        header = f"AssemblingMachine({self.name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        return self._format_processing_inspection(data, header)

class ChemicalPlant(ProcessingMachine):
    """A chemical plant entity."""

    def _format_inspection(self, data: Dict[str, Any]) -> str:
        """Format chemical plant inspection data for agent readability."""
        header = f"ChemicalPlant({self.name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        return self._format_processing_inspection(data, header)

class OilRefinery(ProcessingMachine):
    """An oil refinery entity."""

    def _format_inspection(self, data: Dict[str, Any]) -> str:
        """Format oil refinery inspection data for agent readability."""
        header = f"OilRefinery({self.name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        return self._format_processing_inspection(data, header)

class Centrifuge(ProcessingMachine):
    """A centrifuge entity."""

    def _format_inspection(self, data: Dict[str, Any]) -> str:
        """Format centrifuge inspection data for agent readability."""
        header = f"Centrifuge({self.name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        return self._format_processing_inspection(data, header)

class RocketSilo(ProcessingMachine):
    """A rocket silo entity."""

    def _format_inspection(self, data: Dict[str, Any]) -> str:
        """Format rocket silo inspection data for agent readability."""
        header = f"RocketSilo({self.name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        return self._format_processing_inspection(data, header)


class TransportBelt(InspectableMixin, ReachableEntity):
    """A transport belt entity."""

    @property
    def prototype(self) -> TransportBeltPrototype:
        """Get the prototype for this transport belt type."""
        return get_entity_prototypes().transport_belt
    
    @property
    def selection_box(self) -> BoundingBox:
        """Get the selection box of the transport belt."""
        return BoundingBox.from_tuple(self.prototype["selection_box"])

    def extend(self, turn: Optional[Literal["left", "right"]] = None) -> bool:
        """Extend the transport belt by one entity."""
        if turn is not None and turn not in ["left", "right"]:
            raise ValueError(f"Invalid turn: {turn}")
        direction = self.direction
        if turn == "left":
            direction = self.direction.turn_left()
        elif turn == "right":
            direction = self.direction.turn_right()
        position = self.position.offset(offset=(1, 1), direction=direction) # TODO: get offset from prototypes
        return self._factory.place_entity(self.name, position, direction)

    def _format_inspection(self, data: Dict[str, Any]) -> str:
        """Format transport belt inspection data for agent readability."""
        
        lines = [
            f"TransportBelt({self.name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]
        
        status = data.get("status", "unknown")
        lines.append(f"  Status: {status}")
        
        return "\n".join(lines)


class Splitter(ReachableEntity):
    """A splitter entity."""
    
    def inspect(self, raw_data: bool = False) -> Union[str, EntityInspectionData]:
        """Return a representation of splitter state.
        
        Args:
            raw_data: If False (default), returns a formatted string representation.
                      If True, returns the raw dictionary data.
        
        Returns:
            If raw_data=False: Formatted string representation
            If raw_data=True: Dictionary with entity inspection data (see ReachableEntity.inspect for schema)
        """
        data = self._factory.inspect_entity(self.name, self.position)
        
        if raw_data:
            return data
        
        lines = [
            f"Splitter({self.name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]
        
        status = data.get("status", "unknown")
        lines.append(f"  Status: {status}")
        
        return "\n".join(lines)

class ElectricMiningDrill(InspectableMixin, ReachableEntity):
    """An electric mining drill entity.
    
    Direction is REQUIRED for mining drills as they have directional output positions.
    """
    
    def __init__(self, name: str, position: MapPosition, direction: Optional[Direction] = None, **kwargs):
        super().__init__(name, position, direction, **kwargs)
        if self.direction is None:
            raise ValueError(
                f"ElectricMiningDrill requires direction to be set. "
                f"Entity at ({position.x}, {position.y}) is missing direction data. "
                f"This is likely a data serialization issue - direction should be provided by the mod."
            )

    @property
    def prototype(self) -> ElectricMiningDrillPrototype:
        """Get the prototype for this electric mining drill type."""
        return get_entity_prototypes().electric_mining_drill

    def place_adjacent(self, side: Literal["left", "right"]) -> bool:
        """Place an adjacent mining drill on left or right side."""
        placeable_item = "electric-mining-drill"
        return self._factory.place_entity(placeable_item, self.position, self.direction)

    def output_position(self) -> MapPosition:
        """Get the output position of the mining drill."""
        # Direction is guaranteed to exist due to __init__ assertion
        return self.prototype.output_position(self.position, self.direction)

    def get_search_area(self) -> BoundingBox:
        """Get the search area of the mining drill."""
        return self.prototype.get_resource_search_area(self.position)

    def _format_inspection(self, data: Dict[str, Any]) -> str:
        """Format electric mining drill inspection data for agent readability."""
        
        lines = [
            f"ElectricMiningDrill({self.name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]
        
        status = data.get("status", "unknown")
        lines.append(f"  Status: {status}")
        
        # Mining progress
        mining_progress = data.get("mining_progress")
        if mining_progress is not None:
            lines.append(f"  Mining Progress: {mining_progress:.1f}")
        
        # Energy (if applicable)
        energy = data.get("energy")
        if energy:
            current = energy.get("current", 0)
            capacity = energy.get("capacity", 0)
            if capacity > 0:
                energy_pct = (current / capacity) * 100
                lines.append(f"  Energy: {current:.0f}/{capacity:.0f} ({energy_pct:.1f}%)")
        
        return "\n".join(lines)


class BurnerMiningDrill(CrafterMixin, InspectableMixin, FuelableMixin, ReachableEntity):
    """A burner mining drill entity.
    
    Direction is REQUIRED for mining drills as they have directional output positions.
    """
    
    def __init__(self, name: str, position: MapPosition, direction: Optional[Direction] = None, **kwargs):
        super().__init__(name, position, direction, **kwargs)
        if self.direction is None:
            raise ValueError(
                f"BurnerMiningDrill requires direction to be set. "
                f"Entity at ({position.x}, {position.y}) is missing direction data. "
                f"This is likely a data serialization issue - direction should be provided by the mod."
            )
    
    @property
    def prototype(self) -> BurnerMiningDrillPrototype:
        """Get the prototype for this burner mining drill type."""
        return get_entity_prototypes().burner_mining_drill
    
    @property
    def output_position(self) -> MapPosition:
        """Get the output position of the mining drill."""
        # Direction is guaranteed to exist due to __init__ assertion
        return self.prototype.output_position(self.position, self.direction)

    def get_valid_output_positions(self, target: Union['ReachableEntity', 'PlaceableItem']) -> List[MapPosition]:
        """
        Returns valid center positions for a target entity to pick up items from this drill.
        Enforces strict grid exclusivity (no tile overlap).
        """
        candidates = []
        
        # 1. Determine Source (Self) Tile Footprint
        # Factorio centers even-sized entities on integer coordinates.
        # A 2x2 at x=42 occupies x=[41, 43].
        s_half_w = self.tile_width / 2.0
        s_half_h = self.tile_height / 2.0
        
        src_left = self.position.x - s_half_w
        src_right = self.position.x + s_half_w
        src_top = self.position.y - s_half_h
        src_bottom = self.position.y + s_half_h

        # 2. Determine Target Geometry
        t_width = target.tile_width
        t_height = target.tile_height
        t_half_w = t_width / 2.0
        t_half_h = t_height / 2.0

        # 3. Identify Drop Tile
        # Use the exact output position
        drop_pos = self.output_position
        drop_tile_x = math.floor(drop_pos.x)
        drop_tile_y = math.floor(drop_pos.y)

        # 4. Generate Candidates
        # Iterate over every relative tile offset the target could have
        for dx in range(t_width):
            for dy in range(t_height):
                # Calculate Candidate Footprint
                # If target's (dx, dy) tile is the drop tile:
                target_left = drop_tile_x - dx
                target_top = drop_tile_y - dy
                
                target_right = target_left + t_width
                target_bottom = target_top + t_height
                
                # 5. Strict Grid Overlap Check (AABB)
                # Logic: If max_x < min_x, they are disjoint.
                # Since we are using exact tile boundaries (integers), 
                # we use strictly less/greater to allow touching edges.
                # E.g. Src Right (41) can touch Target Left (41).
                
                is_disjoint = (
                    target_right <= src_left or  # Target is fully to the left
                    target_left >= src_right or  # Target is fully to the right
                    target_bottom <= src_top or  # Target is fully above
                    target_top >= src_bottom     # Target is fully below
                )
                
                if not is_disjoint:
                    continue # They overlap on the grid
                
                # If valid, calculate center
                center_x = target_left + t_half_w
                center_y = target_top + t_half_h
                candidates.append(MapPosition(center_x, center_y))
                
        def alignment_deviation(pos: MapPosition) -> float:
            # Calculate how far 'pos' is off-center relative to 'self.position'
            # perpendicular to the direction of flow.
            
            if self.direction in (Direction.NORTH, Direction.SOUTH):
                # Vertical Flow: Minimize Horizontal (X) Deviation
                return abs(pos.x - self.position.x)
            
            elif self.direction in (Direction.EAST, Direction.WEST):
                # Horizontal Flow: Minimize Vertical (Y) Deviation
                return abs(pos.y - self.position.y)
            
            return 0.0 # Should not happen for cardinal directions

        # Sort in place: Smallest deviation (0.0) comes first
        candidates.sort(key=alignment_deviation)
        return candidates
    
    def get_search_area(self) -> BoundingBox:
        """Get the search area of the mining drill."""
        return self.prototype.get_resource_search_area(self.position)
    
    def _format_inspection(self, data: Dict[str, Any]) -> str:
        """Format burner mining drill inspection data for agent readability."""
        
        lines = [
            f"BurnerMiningDrill({self.name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]
        
        status = data.get("status", "unknown")
        lines.append(f"  Status: {status}")
        
        # Mining progress
        mining_progress = data.get("mining_progress")
        if mining_progress is not None:
            lines.append(f"  Mining Progress: {mining_progress:.1f}")
        
        # Burner information
        burner = data.get("burner")
        if burner:
            currently_burning = burner.get("currently_burning")
            if currently_burning:
                lines.append(f"  Currently Burning: {currently_burning}")
            heat = burner.get("heat", 0)
            heat_capacity = burner.get("heat_capacity", 0)
            if heat_capacity > 0:
                heat_pct = (heat / heat_capacity) * 100
                lines.append(f"  Heat: {heat:.0f}/{heat_capacity:.0f} ({heat_pct:.1f}%)")
        
        # Fuel inventory
        inventories = data.get("inventories", {})
        fuel = inventories.get("fuel", {})
        if fuel:
            fuel_str = ", ".join([f"{name}: {count}" for name, count in fuel.items()])
            lines.append(f"  Fuel Inventory: {fuel_str}")
        else:
            lines.append("  Fuel Inventory: (empty)")
        
        # Output inventory
        output = inventories.get("output", {})
        if output:
            output_str = ", ".join([f"{name}: {count}" for name, count in output.items()])
            lines.append(f"  Output: {output_str}")
        else:
            lines.append("  Output: (empty)")
        
        return "\n".join(lines)
    
    def _get_accepted_fuel_categories(self) -> List[str]:
        """Burner mining drills only accept chemical fuel."""
        return ['chemical']



class Pumpjack(InspectableMixin, ReachableEntity):
    """A pumpjack entity."""

    @property
    def prototype(self) -> PumpjackPrototype:
        """Get the prototype for this pumpjack type."""
        return get_entity_prototypes().pumpjack

    def get_output_pipe_connections(self) -> List[MapPosition]:
        """Get the output pipe connections of the pumpjack."""
        return self.prototype.output_pipe_connections(self.position)

    def _format_inspection(self, data: Dict[str, Any]) -> str:
        """Format pumpjack inspection data for agent readability."""
        
        lines = [
            f"Pumpjack({self.name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]
        
        status = data.get("status", "unknown")
        lines.append(f"  Status: {status}")
        
        # Energy (if applicable)
        energy = data.get("energy")
        if energy:
            current = energy.get("current", 0)
            capacity = energy.get("capacity", 0)
            if capacity > 0:
                energy_pct = (current / capacity) * 100
                lines.append(f"  Energy: {current:.0f}/{capacity:.0f} ({energy_pct:.1f}%)")
        
        return "\n".join(lines)


def create_entity_from_data(entity_data: Dict[str, Any]) -> ReachableEntity:
    """Factory function to create the appropriate Entity subclass from raw data.
    
    Args:
        entity_data: Raw entity data dict from get_reachable() or database
        
    Returns:
        ReachableEntity instance (or appropriate subclass)
    """
    # Normalize database column names
    # Database uses 'entity_name', we use 'name'
    if 'entity_name' in entity_data and 'name' not in entity_data:
        entity_data['name'] = entity_data['entity_name']
    
    name = entity_data.get("name", "")
    
    # Handle position as both dict and direct x/y columns
    if 'position' in entity_data:
        position_data = entity_data.get("position", {})
        if isinstance(position_data, dict):
            position = MapPosition(x=position_data.get("x", 0), y=position_data.get("y", 0))
        elif hasattr(position_data, 'x') and hasattr(position_data, 'y'):
            # Already a MapPosition or similar
            position = position_data
        else:
            position = MapPosition(x=0, y=0)
    else:
        # Try direct x, y columns (from database)
        position = MapPosition(
            x=entity_data.get('x', 0),
            y=entity_data.get('y', 0)
        )
    
    # Parse bounding box if available
    bbox_data = entity_data.get("bounding_box")
    if bbox_data:
        # Handle different bounding box formats
        if "left_top" in bbox_data and "right_bottom" in bbox_data:
            left_top = Position(x=bbox_data["left_top"]["x"], y=bbox_data["left_top"]["y"])
            right_bottom = Position(x=bbox_data["right_bottom"]["x"], y=bbox_data["right_bottom"]["y"])
        elif "min_x" in bbox_data:
            # Alternative format from serialize.lua
            left_top = Position(x=bbox_data["min_x"], y=bbox_data["min_y"])
            right_bottom = Position(x=bbox_data["max_x"], y=bbox_data["max_y"])
        else:
            # Fallback
            left_top = Position(x=position.x, y=position.y)
            right_bottom = Position(x=position.x + 1, y=position.y + 1)
        bounding_box = BoundingBox(left_top=left_top, right_bottom=right_bottom)
    else:
        # Create minimal bounding box
        bounding_box = BoundingBox(
            left_top=Position(x=position.x, y=position.y),
            right_bottom=Position(x=position.x + 1, y=position.y + 1)
        )
    
    # Parse direction if available
    direction = None
    if "direction" in entity_data:
        try:
            dir_value = entity_data["direction"]
            # Handle both int and string representations
            if isinstance(dir_value, (int, float)):
                direction = Direction(int(dir_value))
            elif isinstance(dir_value, str):
                # Try to parse string representation of number
                direction = Direction(int(float(dir_value)))
        except (ValueError, KeyError, TypeError):
            pass
    
    # Fallback to direction_name if direction parsing failed
    if direction is None and "direction_name" in entity_data:
        direction_name = entity_data["direction_name"].upper()
        direction_map = {
            "NORTH": Direction.NORTH,
            "EAST": Direction.EAST,
            "SOUTH": Direction.SOUTH,
            "WEST": Direction.WEST,
        }
        direction = direction_map.get(direction_name)
    
    # Map entity names to specific classes
    entity_map = {
        "electric-mining-drill": ElectricMiningDrill,
        "burner-mining-drill": BurnerMiningDrill,
        "pumpjack": Pumpjack,
        "inserter": Inserter,
        "fast-inserter": FastInserter,
        "long-handed-inserter": LongHandInserter,
        "transport-belt": TransportBelt,
        "splitter": Splitter,
        "assembling-machine-1": AssemblingMachine,
        "assembling-machine-2": AssemblingMachine,
        "assembling-machine-3": AssemblingMachine,
        "chemical-plant": ChemicalPlant,
        "oil-refinery": OilRefinery,
        "centrifuge": Centrifuge,
        "rocket-silo": RocketSilo,
        "stone-furnace": Furnace,
        "steel-furnace": Furnace,
        "electric-furnace": Furnace,
        "small-electric-pole": ElectricPole,
        "medium-electric-pole": ElectricPole,
        "big-electric-pole": ElectricPole,
        "substation": ElectricPole,
        "wooden-chest": WoodenChest,
        "iron-chest": IronChest,
        "steel-chest": Container,
        "crash-site-chest-1": ShipWreck,
        "crash-site-chest-2": ShipWreck,
        "crash-site-spaceship": ShipWreck,
        "crash-site-spaceship-wreck-big-1": ShipWreck,
        "crash-site-spaceship-wreck-big-2": ShipWreck,
        "crash-site-spaceship-wreck-medium-1": ShipWreck,
        "crash-site-spaceship-wreck-medium-2": ShipWreck,
        "crash-site-spaceship-wreck-medium-3": ShipWreck,
    }
    
    entity_class = entity_map.get(name, ReachableEntity)
    
    return entity_class(
        name=name,
        position=position,
        bounding_box=bounding_box,
        direction=direction
    )


def create_entity_from_reachable(entity_data: Dict[str, Any]):
    """Create entity with full ReachableEntity interface from reachable data.
    
    Returns an entity that satisfies the ReachableEntity protocol:
    - Has all spatial properties and prototype data
    - Can be inspected
    - Can be picked up
    - May have additional capabilities (Fuelable, HasInventory, etc.)
    
    Args:
        entity_data: Raw entity data dict from get_reachable()
    
    Returns:
        Entity instance satisfying ReachableEntity protocol
    
    Example:
        >>> drill = create_entity_from_reachable(data)
        >>> isinstance(drill, ReachableEntity)  # True
        >>> drill.pickup()  # Works
        >>> drill.add_fuel(coal)  # Works (if Fuelable)
    """
    from FactoryVerse.dsl.entity.protocols import ReachableEntity
    
    entity = create_entity_from_data(entity_data)
    # Entity has all methods - satisfies ReachableEntity protocol
    return entity


def create_ghost_entity_from_data(entity_data: Dict[str, Any]):
    """Create ghost entity with Buildable interface.
    
    Returns a GhostEntity that satisfies the GhostEntity protocol:
    - Has all spatial properties and prototype data
    - Can be inspected
    - Can be built (convert to real entity)
    - Can be removed (delete ghost)
    - Does NOT have pickup, add_fuel, etc.
    
    Args:
        entity_data: Raw ghost entity data
    
    Returns:
        GhostEntity instance satisfying GhostEntity protocol
    
    Example:
        >>> ghost = create_ghost_entity_from_data(data)
        >>> isinstance(ghost, GhostEntity)  # True
        >>> ghost.build()  # Works
        >>> ghost.pickup()  # AttributeError - ghosts can't be picked up
    """
    from FactoryVerse.dsl.entity.protocols import GhostEntity as GhostEntityProtocol
    
    name = entity_data.get("name", "")
    position_data = entity_data.get("position", {})
    position = MapPosition(x=position_data.get("x", 0), y=position_data.get("y", 0))
    
    # Parse direction
    direction = None
    if "direction" in entity_data:
        try:
            dir_value = entity_data["direction"]
            if isinstance(dir_value, (int, float)):
                direction = Direction(int(dir_value))
            elif isinstance(dir_value, str):
                direction = Direction(int(float(dir_value)))
        except (ValueError, KeyError, TypeError):
            pass
    
    # GhostEntity class already has correct interface
    return GhostEntity(name=name, position=position, direction=direction)


def create_entity_from_db(entity_data: Dict[str, Any]):
    """Create entity with read-only RemoteViewEntity interface from DB data.
    
    Returns an entity that satisfies the RemoteViewEntity protocol:
    - Has all spatial properties and prototype data
    - Can be inspected (requires context manager)
    - May have planning capabilities (output_position, get_search_area)
    - Does NOT have mutation methods (pickup, add_fuel, store_items, etc.)
    
    This is achieved by dynamically removing mutation methods from the entity.
    
    Args:
        entity_data: Raw entity data dict from DuckDB query
    
    Returns:
        Entity instance satisfying RemoteViewEntity protocol
    
    Example:
        >>> db_drill = create_entity_from_db(data)
        >>> isinstance(db_drill, RemoteViewEntity)  # True
        >>> db_drill.output_position  # Works (planning capability)
        >>> db_drill.inspect()  # Works (requires context manager)
        >>> db_drill.pickup()  # AttributeError - no mutation methods
    """
    from FactoryVerse.dsl.entity.remote_view_entity import RemoteViewEntity
    
    # Create the appropriate entity type using the standard factory function
    # This handles all the column normalization (entity_name -> name, etc.)
    entity = create_entity_from_data(entity_data)
    
    # Wrap in RemoteViewEntity for read-only access
    return RemoteViewEntity(entity)
