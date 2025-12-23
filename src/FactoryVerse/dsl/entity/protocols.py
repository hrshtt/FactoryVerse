"""Entity view categories documentation.

This module documents the three entity view categories used in FactoryVerse.
These are NOT runtime protocols - they are documentation for LLM agents.

## Three View Categories

### 1. RemoteViewEntity (Read-Only)
Returned by: map_db.get_entities(), map_db.get_entity()

Allows:
- Spatial properties (position, tile_width, tile_height, direction, area, footprint)
- Prototype data access
- inspect() method
- Entity-specific planning methods (if entity has them):
  - output_position (mining drills, inserters)
  - get_search_area (mining drills)
  - get_valid_output_positions (drills, furnaces)

Blocks with clear error:
- pickup()
- add_fuel()
- store_items() / take_items()
- add_ingredients() / take_products()
- set_recipe()
- build() / remove()

### 2. ReachableEntity (Full Access)
Returned by: reachable.get_entities(), reachable.get_entity()

Allows:
- Everything from RemoteViewEntity
- All mutation methods based on entity mixins:
  - pickup() (all entities)
  - add_fuel() (entities with FuelableMixin)
  - add_ingredients() / take_products() (entities with CrafterMixin)
  - store_items() / take_items() (entities with InventoryMixin)
  - set_recipe() (assemblers)

### 3. GhostEntity (Build-Only)
Returned by: item.place_ghost(), ghosts.get_ghosts()

Allows:
- Spatial properties
- Prototype data access
- inspect() method
- Entity-specific planning methods
- build() - convert ghost to real entity
- remove() - delete ghost

Blocks with clear error:
- pickup()
- add_fuel()
- store_items() / take_items()
- add_ingredients() / take_products()
- set_recipe()

## Entity Categories (What Mixin Combinations)

Final entity types are created by mixing capability mixins:

- **Furnace**: CrafterMixin + FuelableMixin + InspectableMixin + ReachableEntity
- **BurnerMiningDrill**: CrafterMixin + FuelableMixin + InspectableMixin + OutputPositionMixin + ReachableEntity
- **ElectricMiningDrill**: InspectableMixin + OutputPositionMixin + ReachableEntity
- **Assembler**: CrafterMixin + InspectableMixin + ReachableEntity
- **Container**: InventoryMixin + InspectableMixin + ReachableEntity
- **Inserter**: InspectableMixin + ReachableEntity

## Mixins Define Capabilities

All capabilities come from mixins defined in `mixins.py`:

- **InspectableMixin**: inspect(raw_data=False)
- **FuelableMixin**: add_fuel(item, count)
- **CrafterMixin**: add_ingredients(items), take_products(items)
- **InventoryMixin**: store_items(items), take_items(items)
- **OutputPositionMixin**: output_position property, get_valid_output_positions(target)
- **SpatialPropertiesMixin**: position, tile_width, tile_height, direction, area, footprint

## How Views Work

Views are thin wrapper classes that delegate to the underlying entity:

1. **RemoteViewEntity** wraps entity instance, delegates all attributes except blocked mutations
2. **GhostEntity** wraps ghost instance, delegates all attributes except blocked mutations
3. **ReachableEntity** is returned directly (no wrapper)

The wrapper uses `__getattr__` to delegate, so:
- Entity-specific methods (like `output_position`) work automatically if entity has them
- Blocked methods raise AttributeError with helpful message
- `dir()` only shows what actually exists on the entity

This keeps the type system simple and self-documenting.
"""

__all__ = []  # This module is for documentation only, exports nothing
