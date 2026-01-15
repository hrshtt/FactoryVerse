# Entity Inspection Design Document

This document summarizes the runtime entity inspection analysis and presents the final mixin-based architecture for entity state management in FactoryVerse.

## Table of Contents

1. [Overview](#overview)
2. [Methodology](#methodology)
3. [Runtime Inspection Results](#runtime-inspection-results)
4. [Mixin Capability Summary](#mixin-capability-summary)
5. [Mixin Co-occurrence Analysis](#mixin-co-occurrence-analysis)
6. [Final Mixin Design](#final-mixin-design)
7. [Implementation Guidelines](#implementation-guidelines)

---

## Overview

### Goal

Create a type system where:
- **Entity classes** are regular Python classes with behavior (methods)
- **Mixins** define both behavior AND own their state contracts
- **State** is represented via Pydantic `BaseModel` nested within each mixin
- **Inspection** returns composed state from all entity mixins

### Key Principle: Component Registry Pattern

Instead of dynamically merging mixin states into a flat structure (which is unstable and prone to field collisions), we use a **Static Component Registry** approach:

- `inspect()` **always** returns a single `EntityInspection` object
- The object has common fields (`name`, `status`) and **optional namespaced slots** for every possible mixin (`burner`, `miner`, `electric`, etc.)
- Mixin data is strictly typed and namespaced — no field collisions possible

```python
class BurnerMiningDrill(BaseEntity, BurnerMixin, MinerMixin):
    pass

drill = BurnerMiningDrill(...)
inspection = drill.inspect()  # Always returns EntityInspection

# inspection.name = "burner-mining-drill"
# inspection.status = EntityStatus.WORKING
# inspection.burner = BurnerState(heat=100, remaining_fuel=50, ...)
# inspection.miner = MinerState(mining_progress=0.5, ...)
# inspection.inserter = None  # Not applicable to this entity
# inspection.electric = None  # Not applicable to this entity
```

This pattern ensures the LLM learns **one single schema** that works for all 104+ entities.

---

## Methodology

This section describes the step-by-step process used to derive the mixin design.

### Step 1: Identify the Problem

The existing `inspection.lua` used **category-based dispatching**:

```lua
if entity_type == "assembling-machine" then
    category_data = inspect_crafting_machine(entity)
elseif entity_type == "mining-drill" then
    category_data = inspect_mining_drill(entity)
-- ... 15+ more branches
```

**Problems identified:**
1. Tight coupling between entity type and inspection logic
2. Hardcoded entity names (e.g., checking for "burner-inserter" by name)
3. No clear mapping to Python type system
4. Difficult to document for LLM consumption

### Step 2: Research Factorio Lua API

**Key findings:**

1. **Inventory helpers exist**: `get_fuel_inventory()`, `get_output_inventory()`, `get_module_inventory()` are entity-type aware
2. **`defines.inventory`** provides entity-specific inventory slots (e.g., `crafter_input`, `lab_input`, `turret_ammo`)
3. **`prototype.supports_direction`** indicates if entity can be rotated
4. **`storage` vs `global`**: Factorio 2.0 uses `storage` for persistent data, but RCON console commands don't persist `storage` between calls
5. **`electric-energy-interface`**: Testing entity that provides infinite power when configured

### Step 3: Build Runtime Inspector

Created `scripts/runtime_inspector.py` to inspect entities at runtime:

**Technical approach:**
1. **Self-contained RCON calls**: Each batch includes all helper functions inline (since `storage` doesn't persist between RCON commands)
2. **Smart placement**: Used `surface.find_non_colliding_position()` to find valid spots
3. **Environment creation**: Spawned ore for miners, oil for pumpjacks, water tiles for offshore pumps
4. **Power provision**: Placed `substation` + `electric-energy-interface` per entity
5. **Immediate cleanup**: Destroyed entities after inspection to avoid map pollution
6. **Error handling**: Wrapped all Lua in `xpcall` with `debug.traceback` for stack traces

**Key code pattern:**
```lua
local function create_with_environment(surface, name, proto, base_pos)
    local etype = proto.type
    local pos = surface.find_non_colliding_position(name, base_pos, 50, 1)
    
    if etype == "mining-drill" then
        -- Spawn ore first
        surface.create_entity{name = "iron-ore", position = pos, amount = 10000}
    elseif etype == "offshore-pump" then
        -- Create water tile
        surface.set_tiles({{name = "water", position = {x = pos.x, y = pos.y + 1}}})
    end
    
    return surface.create_entity{name = name, position = pos, ...}
end
```

### Step 4: Analyze Runtime Data

Processed the inspection output to derive mixin assignments:

**Detection logic for each mixin:**
```python
caps = {
    "supports_direction": entity.get("supports_direction", False),  # ROTATABLE
    "has_burner": "burner" in entity,                               # BURNER
    "has_electric_buffer": "electric_buffer_size" in entity,        # ELECTRIC
    "has_crafting": "crafting_progress" in entity,                  # CRAFTER
    "has_mining": "mining_progress" in entity,                      # MINER
    "has_fluidbox": "fluidboxes" in entity,                         # FLUID
    "is_inserter": etype == "inserter" and "pickup_position" in entity,  # INSERTER
}
```

### Step 5: Mixin Co-occurrence Analysis

Analyzed which mixins always appear together:

```python
for m1, m2 in combinations(all_mixins, 2):
    m1_sets = mixin_occurrences[m1]
    m2_sets = mixin_occurrences[m2]
    
    m1_always_has_m2 = all(m2 in s for s in m1_sets)
    m2_always_has_m1 = all(m1 in s for s in m2_sets)
    
    if m1_always_has_m2 and m2_always_has_m1:
        print(f"CONSOLIDATION CANDIDATE: {m1} ↔ {m2}")
```

**Result:** MINER and OUTPUT_VECTOR always appear together → consolidated into single MINER mixin.

### Step 6: Differentiate INSERTER vs OUTPUT_VECTOR

**Problem discovered:** Mining drills have `drop_position`, but they are NOT inserters.

**Research:** Found `prototype.vector_to_place_result` — a prototype property for mining drills and crafting machines that defines output direction.

**Solution:**
- `INSERTER`: Only for `type == "inserter"` with `pickup_position` + `drop_position`
- `MINER`: Has `output_position` (from `drop_position`) but is NOT an inserter

### Step 7: Design Mixin-Owned State

**Requirement from user:** Entity classes should be regular Python classes; only state should use Pydantic BaseModel.

**Final design principle:**
```python
class BurnerMixin:
    """The mixin OWNS its state definition."""
    
    class State(BaseModel):  # <-- Nested, owned by mixin
        heat: float
        remaining_fuel: float
        currently_burning: Optional[str]
    
    def refuel(self, item): ...  # <-- Behavior
```

**Benefits:**
1. One mixin = one state definition
2. Entity inspection = composition of mixin states
3. ~9 state definitions cover 104 entities
4. LLM documentation: "BurnerDrill = BaseEntity + BurnerMixin + MinerMixin"

### Tools and Scripts

| Script | Purpose |
|--------|---------|
| `scripts/runtime_inspector.py` | Runtime entity inspection via RCON |
| Analysis in RCON | Co-occurrence computation, field mapping |

### Output Artifacts

| File | Purpose |
|------|---------|
| `.fv-output/inspection/runtime_inspection.json` | Raw inspection data (104 entities) |
| `.fv-output/inspection/capability_summary.json` | Entity → mixin mapping |
| `.fv-output/inspection/defines.json` | Factorio defines (inventory, status, direction) |
| `docs/entity-inspection-design.md` | This design document |

---

## Runtime Inspection Results

We inspected **104 placeable entities** at runtime using the `scripts/runtime_inspector.py` script. This script:

1. Places each entity using `find_non_colliding_position`
2. Creates required environment (ore for miners, oil for pumpjacks, water for offshore pumps)
3. Powers each entity with `substation` + `electric-energy-interface`
4. Inspects entity state and prototype properties
5. Immediately cleans up

### Output Files

| File | Description |
|------|-------------|
| `.fv-output/inspection/runtime_inspection.json` | Full inspection data (104 entities) |
| `.fv-output/inspection/capability_summary.json` | Per-entity mixin assignments |
| `.fv-output/inspection/defines.json` | Factorio defines mappings |
| `.fv-output/inspection/entity_list.json` | All placeable entity names |

### Failed Entities (5)

Rail vehicles require rails to be placed:
- `artillery-wagon`
- `cargo-wagon`
- `fluid-wagon`
- `infinity-cargo-wagon`
- `locomotive`

---

## Mixin Capability Summary

### Detection Criteria

| Mixin | Detection Criteria | Source |
|-------|-------------------|--------|
| **ROTATABLE** | `prototype.supports_direction == true` | Prototype property |
| **BURNER** | `entity.burner` exists | Runtime property |
| **ELECTRIC** | `entity.electric_buffer_size > 0` or `entity.energy > 0` | Runtime property |
| **CRAFTER** | `entity.crafting_progress` or `entity.crafting_speed` exists | Runtime property |
| **MINER** | `entity.mining_progress` exists | Runtime property |
| **FLUID** | `entity.fluidbox` has entries | Runtime property |
| **INSERTER** | `entity.type == "inserter"` AND has `pickup_position` | Type + runtime |
| **CONTAINER** | Has `chest` or similar inventory | Runtime property |
| **ROCKET** | `entity.rocket_parts` exists | Runtime property |

### Entity Counts by Type

```
assembling-machine: 6   (assembling-machine-1/2/3, centrifuge, chemical-plant, oil-refinery)
furnace: 3              (stone-furnace, steel-furnace, electric-furnace)
inserter: 5             (inserter, fast-inserter, bulk-inserter, long-handed-inserter, burner-inserter)
mining-drill: 3         (burner-mining-drill, electric-mining-drill, pumpjack)
container: 4            (wooden-chest, iron-chest, steel-chest, bottomless-chest)
logistic-container: 5   (active-provider, passive-provider, storage, buffer, requester)
transport-belt: 3       (transport-belt, fast-transport-belt, express-transport-belt)
electric-pole: 4        (small, medium, big, substation)
...
```

### Sample Mixin Assignments

| Entity | Mixins |
|--------|--------|
| `stone-furnace` | ROTATABLE, BURNER, CRAFTER |
| `electric-furnace` | ROTATABLE, ELECTRIC, CRAFTER |
| `burner-mining-drill` | ROTATABLE, BURNER, MINER |
| `electric-mining-drill` | ROTATABLE, ELECTRIC, MINER |
| `pumpjack` | ROTATABLE, ELECTRIC, MINER, FLUID |
| `burner-inserter` | ROTATABLE, BURNER, INSERTER |
| `fast-inserter` | ROTATABLE, ELECTRIC, INSERTER |
| `chemical-plant` | ROTATABLE, ELECTRIC, CRAFTER, FLUID |
| `rocket-silo` | ELECTRIC, CRAFTER, ROCKET |
| `boiler` | ROTATABLE, BURNER, FLUID |
| `steam-engine` | ROTATABLE, ELECTRIC, FLUID |

---

## Mixin Co-occurrence Analysis

### Consolidation Finding

**MINER ↔ OUTPUT_VECTOR**: These always appear together in both directions.
- Every entity with MINER has OUTPUT_VECTOR
- Every entity with OUTPUT_VECTOR has MINER

**Recommendation**: Consolidate into single **MINER** mixin. The output position is an implementation detail of miners.

### One-way Implications

| If entity has... | It always has... |
|------------------|------------------|
| `INSERTER` | `ROTATABLE` |
| `MINER` | `ROTATABLE` |
| `ROCKET` | `CRAFTER` + `ELECTRIC` |

### Mutually Exclusive Mixins

| Mixin | Never appears with |
|-------|-------------------|
| `INSERTER` | CRAFTER, FLUID, MINER, ROCKET |
| `CRAFTER` | INSERTER, MINER |
| `ROCKET` | BURNER, FLUID, INSERTER, MINER, ROTATABLE |

### Mixin Frequency

```
ROTATABLE:  63 entities
ELECTRIC:   37 entities
FLUID:      17 entities
BURNER:      9 entities
CRAFTER:    10 entities
INSERTER:    5 entities
MINER:       3 entities
ROCKET:      1 entity
```

---

## Final Mixin Design

### Architecture: Component Registry Pattern

The Component Registry pattern uses a **single master schema** (`EntityInspection`) that acts as a capability registry. Each mixin's state is placed in a namespaced, optional slot.

```
┌─────────────────────────────────────────────────────────────────┐
│                      EntityInspection                            │
│  (The Master Schema - One Schema to Rule Them All)               │
├─────────────────────────────────────────────────────────────────┤
│  Base Fields (always present):                                   │
│    - name: str                                                   │
│    - position: Position                                          │
│    - status: Optional[EntityStatus]                              │
│    - is_ghost: bool                                              │
├─────────────────────────────────────────────────────────────────┤
│  Capability Slots (Optional - namespaced by mixin):              │
│    - burner: Optional[BurnerState]                               │
│    - electric: Optional[ElectricState]                           │
│    - crafter: Optional[CrafterState]                             │
│    - miner: Optional[MinerState]                                 │
│    - inserter: Optional[InserterState]                           │
│    - fluid: Optional[FluidState]                                 │
│    - container: Optional[ContainerState]                         │
│    - rocket: Optional[RocketState]                               │
│    - belt: Optional[BeltState]                                   │
└─────────────────────────────────────────────────────────────────┘
```

**Key Benefits:**
1. **Single schema**: LLMs learn one `EntityInspection` type, not 100+ variants
2. **No field collisions**: Each mixin's data is namespaced (e.g., `inspection.burner.heat`)
3. **Zero boilerplate**: Adding a new entity requires no inspection code
4. **Predictable output**: Schema is always the same, only populated fields vary

### A. Master Schema: `EntityInspection`

```python
class EntityInspection(BaseModel):
    """The master inspection schema - capability registry for all entities.
    
    This single class is returned by ALL entity inspect() calls.
    Mixin-specific data is placed in namespaced optional slots.
    Use model.model_dump_json(exclude_none=True) for concise LLM output.
    """
    
    # Base fields (always present)
    name: str
    position: Position
    status: Optional[EntityStatus] = None
    is_ghost: bool = False
    direction: Optional[Direction] = None
    
    # Capability slots - each corresponds to a mixin
    burner: Optional[BurnerState] = None
    electric: Optional[ElectricState] = None
    crafter: Optional[CrafterState] = None
    miner: Optional[MinerState] = None
    inserter: Optional[InserterState] = None
    fluid: Optional[FluidState] = None
    container: Optional[ContainerState] = None
    rocket: Optional[RocketState] = None
    belt: Optional[BeltState] = None

    class Config:
        """Pydantic config for clean serialization."""
        extra = "forbid"  # Strict schema - no unknown fields
```

### B. BaseEntity Definition

```python
class BaseEntity(ABC):
    """Base class for all Factorio entities."""
    name: EntityID
    position: Position
    is_ghost: bool
    _view: EntityView
    
    def inspect(self) -> EntityInspection:
        """Return inspection state using the Component Registry pattern.
        
        This method:
        1. Initializes EntityInspection with base data
        2. Checks for each mixin via isinstance()
        3. Populates the corresponding slot by calling the mixin's _get_state() helper
        
        Returns:
            EntityInspection: The master schema with applicable slots populated.
        """
        inspection = EntityInspection(
            name=self.name,
            position=self.position,
            status=self._get_status(),
            is_ghost=self.is_ghost,
            direction=getattr(self, 'direction', None),
        )
        
        # Populate capability slots based on mixin presence
        if isinstance(self, BurnerMixin):
            inspection.burner = self._get_burner_state()
        
        if isinstance(self, ElectricMixin):
            inspection.electric = self._get_electric_state()
        
        if isinstance(self, CrafterMixin):
            inspection.crafter = self._get_crafter_state()
        
        if isinstance(self, MinerMixin):
            inspection.miner = self._get_miner_state()
        
        if isinstance(self, InserterMixin):
            inspection.inserter = self._get_inserter_state()
        
        if isinstance(self, FluidMixin):
            inspection.fluid = self._get_fluid_state()
        
        if isinstance(self, ContainerMixin):
            inspection.container = self._get_container_state()
        
        if isinstance(self, RocketMixin):
            inspection.rocket = self._get_rocket_state()
        
        if isinstance(self, BeltMixin):
            inspection.belt = self._get_belt_state()
        
        return inspection
    
    def pickup(self) -> PlaceableItem:
        """Pickup the entity."""
        ...

    _prototype_cache: Optional[BasePrototype]

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

    def _get_status(self) -> Optional[EntityStatus]:
        """Get entity status. Override in subclasses if needed."""
        return None
```

### C. Entity Types Definitions

```python
class EntityView(Enum):
    REACHABLE = "reachable"
    REMOTE = "remote"
```

### D. Mixin State Definitions

Each mixin defines:
1. A rigid `State` Pydantic model for its data
2. A `_get_<mixin>_state()` helper method that `BaseEntity.inspect()` calls
3. **Ghost handling**: Mixins return partial data for ghosts internally

#### RotatableMixin

```python
class RotatableMixin:
    """Mixin for entities that can be rotated."""
    direction: Direction
    
    def rotate(self, direction: Direction) -> None:
        """Rotate entity to face direction."""
        ...
```

```python
class Rotatable180Mixin:
    """Mixin for entities that can be rotated."""
    direction: Direction
    
    def rotate_180(self) -> None:
        """Rotate entity by 180 degrees."""
        ...
```

#### BurnerMixin

```python
class BurnerState(BaseModel):
    """State for burner-powered entities."""
    heat: float = 0
    remaining_burning_fuel: float = 0
    currently_burning: Optional[str] = None
    burner_fuel: Optional[ItemStack] = None


class BurnerMixin:
    """Mixin for entities that burn fuel for energy."""
    
    def _get_burner_state(self) -> BurnerState:
        """Get burner state for inspection. Handles ghost vs real entity."""
        if self.is_ghost:
            return BurnerState()  # Ghosts have no burner data
        return BurnerState(
            heat=self._get_heat(),
            remaining_burning_fuel=self._get_remaining_fuel(),
            currently_burning=self._get_currently_burning(),
            burner_fuel=self._get_burner_fuel(),
        )
    
    def add_fuel(self, item_stack: ItemStack) -> None:
        """Add fuel to the burner."""
        ...
    
    def take_fuel(self, item_stack: Optional[ItemStack]) -> None:
        """Take fuel from the burner."""
        ...
```

#### ElectricMixin

```python
class ElectricState(BaseModel):
    """State for electric-powered entities."""
    energy: float = 0
    buffer_capacity: float = 0
    electric_network_id: Optional[int] = None


class ElectricMixin:
    """Mixin for entities that consume/store electricity."""
    
    def _get_electric_state(self) -> ElectricState:
        """Get electric state for inspection. Handles ghost vs real entity."""
        if self.is_ghost:
            return ElectricState()  # Ghosts have no electric data
        return ElectricState(
            energy=self._get_energy(),
            buffer_capacity=self._get_buffer_capacity(),
            electric_network_id=self._get_network_id(),
        )
```

#### CrafterMixin & SetRecipeMixin

```python
class CrafterState(BaseModel):
    """State for crafting machines."""
    recipe: Optional[str] = None
    crafting_progress: float = 0
    crafting_speed: float = 1.0
    is_crafting: bool = False
    crafter_input: List[ItemStack] = Field(default_factory=list)
    crafter_output: List[ItemStack] = Field(default_factory=list)
    crafter_modules: List[ItemStack] = Field(default_factory=list)


class CrafterMixin:
    """Mixin for crafting machines (assemblers, furnaces, chemical plants)."""
    
    def _get_crafter_state(self) -> CrafterState:
        """Get crafter state for inspection. Handles ghost vs real entity."""
        if self.is_ghost:
            return CrafterState()  # Ghosts have no crafting data
        return CrafterState(
            recipe=self._get_recipe(),
            crafting_progress=self._get_crafting_progress(),
            crafting_speed=self._get_crafting_speed(),
            is_crafting=self._get_is_crafting(),
            crafter_input=self._get_crafter_input(),
            crafter_output=self._get_crafter_output(),
            crafter_modules=self._get_crafter_modules(),
        )

    def add_ingredients(self, items):
        ...

    def take_products(self, items):
        ...


class SetRecipeMixin:
    def set_recipe(self, recipe: str) -> None:
        """Set the crafting recipe."""
        ...
```

#### MinerMixin

```python
class MinerState(BaseModel):
    """State for mining drills."""
    mining_progress: float = 0
    mining_target: Optional[ResourceOrePatch] = None  # {name, amount}
    insert_target: Optional[str] = None  # Entity name at drop position
    drop_position: Optional[Position] = None


class MinerMixin:
    """Mixin for mining drills (ore extraction)."""
    
    def _get_miner_state(self) -> MinerState:
        """Get miner state for inspection. Handles ghost vs real entity."""
        if self.is_ghost:
            return MinerState(drop_position=self._get_drop_position())
        return MinerState(
            mining_progress=self._get_mining_progress(),
            mining_target=self._get_mining_target(),
            insert_target=self._get_insert_target(),
            drop_position=self._get_drop_position(),
        )

    @property
    def drop_position(self) -> Position: ...
    
    def get_insert_target_positions(self, target_entity: BaseEntity|PlaceableItem|Prototype) -> List[Position]:
        """Get the possible valid insert target positions, based on target entity."""
        ...
```

#### FluidMixin

```python
class FluidState(BaseModel):
    """State for fluid-handling entities."""
    fluidboxes: List[FluidBox] = Field(default_factory=list)


class FluidMixin:
    """Mixin for entities with fluid connections."""
    
    def _get_fluid_state(self) -> FluidState:
        """Get fluid state for inspection. Handles ghost vs real entity."""
        if self.is_ghost:
            return FluidState()  # Ghosts have no fluid data
        return FluidState(fluidboxes=self._get_fluidboxes())
    
    def get_fluid(self, index: int) -> Optional[FluidBox]:
        """Get fluid in specific fluidbox."""
        ...
```

#### ContainerMixin

```python
class ContainerState(BaseModel):
    """State for storage containers."""
    contents: Dict[str, int] = Field(default_factory=dict)
    inventory_size: Optional[int] = None


class ContainerMixin:
    """Mixin for storage containers."""
    
    def _get_container_state(self) -> ContainerState:
        """Get container state for inspection. Handles ghost vs real entity."""
        if self.is_ghost:
            return ContainerState(inventory_size=self._get_inventory_size())
        return ContainerState(
            contents=self._get_contents(),
            inventory_size=self._get_inventory_size(),
        )
    
    def get_item_count(self, item: str) -> int:
        """Get count of specific item."""
        ...

    def store_item(self, item: str, count: int) -> None:
        """Store item in container."""
        ...
        
    def take_item(self, item: str, count: int) -> None:
        """Take item from container."""
        ...
```

#### RocketMixin

```python
class RocketState(BaseModel):
    """State for rocket silos."""
    rocket_parts: int = 0
    rocket_silo_status: Optional[str] = None


class RocketMixin:
    """Mixin for rocket silos."""
    
    def _get_rocket_state(self) -> RocketState:
        """Get rocket state for inspection. Handles ghost vs real entity."""
        if self.is_ghost:
            return RocketState()  # Ghosts have no rocket data
        return RocketState(
            rocket_parts=self._get_rocket_parts(),
            rocket_silo_status=self._get_silo_status(),
        )
    
    def launch_rocket(self) -> bool:
        """Launch the rocket if ready."""
        ...
```

#### InserterMixin

```python
class InserterState(BaseModel):
    """State for inserter entities."""
    held_item: Optional[ItemStack] = None
    pickup_target: Optional[str] = None  # Entity name
    insert_target: Optional[str] = None  # Entity name
    filters: List[str] = Field(default_factory=list)
    pickup_position: Optional[Position] = None
    insert_position: Optional[Position] = None


class InserterMixin:
    """Mixin for inserter entities that transfer items."""
    
    def _get_inserter_state(self) -> InserterState:
        """Get inserter state for inspection. Handles ghost vs real entity."""
        base_state = InserterState(
            pickup_position=self._get_pickup_position(),
            insert_position=self._get_insert_position(),
        )
        if self.is_ghost:
            return base_state  # Ghosts only have position data
        return InserterState(
            held_item=self._get_held_item(),
            pickup_target=self._get_pickup_target(),
            insert_target=self._get_insert_target(),
            filters=self._get_filters(),
            pickup_position=self._get_pickup_position(),
            insert_position=self._get_insert_position(),
        )
    
    def set_filter(self, slot: int, item: str) -> None:
        """Set inserter filter."""
        ...
```

#### BeltMixin

```python
class BeltState(BaseModel):
    """State for transport belt entities."""
    items_in_transit: Dict[Literal["left_lane", "right_lane"], List[ItemStack]] = Field(
        default_factory=lambda: {"left_lane": [], "right_lane": []}
    )
    input_belts: List[str] = Field(default_factory=list)  # Entity names
    output_belt: Optional[str] = None  # Entity name
    belt_line_id: Optional[str] = None
    belt_group_id: Optional[str] = None


class BeltMixin:
    """Mixin for transport belt entities."""
    
    def _get_belt_state(self) -> BeltState:
        """Get belt state for inspection. Handles ghost vs real entity."""
        if self.is_ghost:
            return BeltState(
                belt_line_id=self.belt_line_id,
                belt_group_id=self.belt_group_id,
            )
        return BeltState(
            items_in_transit=self._get_items_in_transit(),
            input_belts=self._get_input_belts(),
            output_belt=self._get_output_belt(),
            belt_line_id=self.belt_line_id,
            belt_group_id=self.belt_group_id,
        )
```

---

## Implementation Guidelines

### Entity Implementations

#### Mining Drills

```python
class BurnerMiningDrill(BaseEntity, RotatableMixin, BurnerMixin, MinerMixin):
    """A mining drill powered by burning fuel."""
    ...
```

```python
class ElectricMiningDrill(BaseEntity, RotatableMixin, ElectricMixin, MinerMixin):
    """A mining drill powered by burning fuel."""
    ...
```

#### Furnaces

```python
class StoneFurnace(BaseEntity, BurnerMixin, CrafterMixin):
    """A stone furnace powered by burning fuel."""
    ...
```

```python
class SteelFurnace(BaseEntity, BurnerMixin, CrafterMixin):
    """A steel furnace powered by burning fuel."""
    ...
```

```python
class ElectricFurnace(BaseEntity, ElectricMixin, CrafterMixin):
    """An Electric furnace powered by electricity."""
    ...
```

#### Assemblers

```python
class AssemblingMachine1(BaseEntity, ElectricMixin, CrafterMixin, SetRecipeMixin):
    """An assembling machine 1, for automating basic recipes."""
    ...
```

```python
class AssemblingMachine2(BaseEntity, ElectricMixin, CrafterMixin, SetRecipeMixin, FluidMixin):
    """An assembling machine 2, for automating medium recipes."""
    ...
```

```python
class AssemblingMachine3(BaseEntity, ElectricMixin, CrafterMixin, SetRecipeMixin, FluidMixin):
    """An assembling machine 2, for automating advanced recipes."""
    ...
```

#### Inserters

```python
class Inserter(BaseEntity, RotatableMixin, ElectricMixin, InserterMixin):
    """Inserter Entity, transfers items between entities.
    
    Note: InserterMixin provides the state via _get_inserter_state().
    No custom State class needed - inspect() populates EntityInspection.inserter automatically.
    """
    
    def set_filter(self, slot: int, item: str) -> None:
        """Set inserter filter."""
        ...
    
    @property
    def pickup_position(self) -> Position: ...

    @property
    def insert_position(self) -> Position: ...
```

```python
class FastInserter(Inserter):
    """Fast Inserter, transfers items between entities."""
    ...
```

```python
class LongHandedInserter(Inserter):
    """Long Handed Inserter, transfers items between entities."""
    ...
```

#### Transport Belts

```python
class TransportBelt(BaseEntity, RotatableMixin, BeltMixin):
    """Transport Belt Entity, connects with other belts to move items across the factory.
    
    Note: BeltMixin provides the state via _get_belt_state().
    No custom State class needed - inspect() populates EntityInspection.belt automatically.
    """
    pass
```

```python
class FastTransportBelt(TransportBelt):
    """Fast Transport Belt Entity, connects with other belts to move items across the factory."""
```

```python
class ExpressTransportBelt(TransportBelt):
    """Express Transport Belt Entity, connects with other belts to move items across the factory."""
```

#### Underground Belt

```python
class UndergroundBelt(BaseEntity, RotatableMixin, BeltMixin):
    """Underground Belt Entity, connects with other belts to move items across the factory.
    
    Note: BeltMixin provides the state via _get_belt_state().
    """
    pass
```

```python
class FastUndergroundBelt(UndergroundBelt):
    """Fast Underground Belt Entity, connects with other belts to move items across the factory."""
```

```python
class ExpressUndergroundBelt(UndergroundBelt):
    """Express Underground Belt Entity, connects with other belts to move items across the factory."""
```

#### Splitter

```python
class Splitter(BaseEntity, Rotatable180Mixin, BeltMixin):
    """Splitter Entity, splits items between two belts.
    
    Note: BeltMixin provides the state via _get_belt_state().
    """
    pass
```

```python
class FastSplitter(Splitter):
    """Fast Splitter Entity, splits items between two belts."""
```

```python
class ExpressSplitter(Splitter):
    """Express Splitter Entity, splits items between two belts."""
```

#### Off-Shore Pump

```python
class OffshorePump(BaseEntity, FluidMixin):
    """Off-Shore Pump Entity, extracts fluid from the ground.
    
    Note: FluidMixin provides the state via _get_fluid_state().
    No custom State class needed.
    """

    def get_pipe_connection_point(self) -> Position:
        """Get the position for pipe connection."""
        ...
```

#### Boiler

```python
class Boiler(BaseEntity, RotatableMixin, BurnerMixin, FluidMixin):
    """Boiler Entity, heats up fluid.
    
    Note: BurnerMixin and FluidMixin provide their states via _get_burner_state()
    and _get_fluid_state() respectively. EntityInspection.burner and 
    EntityInspection.fluid will be populated automatically.
    """

    @property
    def steam_output_port(self) -> Position:
        """Get the position for steam output port."""
        ...
    @property
    def water_port_a(self) -> Position:
        """Get the position for water port a."""
        ...
    @property
    def water_port_b(self) -> Position:
        """Get the position for water port b."""
        ...
```

#### Steam Engine

```python
class SteamEngine(BaseEntity, RotatableMixin, FluidMixin, ElectricMixin):
    """Steam Engine Entity, generates electricity from steam."""

    @property
    def steam_port_a(self) -> Position:
        """Get the position for steam port a."""
        ...
    @property
    def steam_port_b(self) -> Position:
        """Get the position for steam port b."""
        ...
```

### 2. State Composition: Namespaced Capability Registry

The `inspect()` method populates the `EntityInspection` registry using `isinstance` checks:

```python
def inspect(self) -> EntityInspection:
    """Populate the EntityInspection registry based on entity capabilities.
    
    Unlike the old MRO-iteration approach that merged dicts (prone to collisions),
    we now use a static schema with namespaced slots filled via isinstance checks.
    """
    # Initialize with base data
    inspection = EntityInspection(
        name=self.name,
        position=self.position,
        status=self._get_status(),
        is_ghost=self.is_ghost,
        direction=getattr(self, 'direction', None),
    )
    
    # Selectively populate capability slots
    if isinstance(self, BurnerMixin):
        inspection.burner = self._get_burner_state()
    
    if isinstance(self, ElectricMixin):
        inspection.electric = self._get_electric_state()
    
    # ... etc for all mixins
    
    return inspection
```

**Key difference from old approach:**
- **Old (Flat Merging):** Iterated MRO, called `_get_mixin_state()` on each, merged all dicts into one flat structure. Risk of field collisions (e.g., both `BurnerMixin` and `MinerMixin` could have a `progress` field).
- **New (Namespaced Composition):** Each mixin's data lives in its own namespace slot (`inspection.burner`, `inspection.miner`, etc.). No collisions possible.

### 3. Lua Side (inspection.lua)

The Lua inspection module should dump ALL relevant data generically:

```lua
local function inspect_entity(entity)
    local state = {
        -- Base
        name = entity.name,
        type = entity.type,
        position = {x = entity.position.x, y = entity.position.y},
        direction = entity.direction,
        status = entity.status,
    }
    
    -- Burner (if applicable)
    if entity.burner then
        state.burner = {
            heat = entity.burner.heat,
            remaining_burning_fuel = entity.burner.remaining_burning_fuel,
            currently_burning = entity.burner.currently_burning and entity.burner.currently_burning.name,
        }
    end
    
    -- Electric (if applicable)
    if entity.energy then
        state.electric = {
            energy = entity.energy,
            buffer_capacity = entity.electric_buffer_size,
        }
    end
    
    -- Crafter (if applicable)
    if entity.crafting_progress then
        local recipe = entity.get_recipe and entity.get_recipe()
        state.crafter = {
            recipe = recipe and recipe.name,
            crafting_progress = entity.crafting_progress,
            crafting_speed = entity.crafting_speed,
        }
    end
    
    -- ... etc for each mixin
    
    return state
end
```

### 4. LLM Documentation

The Component Registry pattern is designed for optimal LLM consumption:

**Rationale:**
- The LLM learns **one single schema** (`EntityInspection`) instead of 100+ entity-specific schemas
- The schema is always predictable — only the populated fields vary
- Namespaced data prevents ambiguity (e.g., `inspection.burner.heat` vs `inspection.miner.mining_progress`)

**Concise Output via `exclude_none`:**

For LLM prompts, we serialize with:
```python
inspection.model_dump_json(exclude_none=True)
```

This sends only active components, keeping the output concise:

```json
// BurnerMiningDrill inspection (only burner + miner slots populated)
{
  "name": "burner-mining-drill",
  "position": {"x": 10, "y": 20},
  "status": "working",
  "is_ghost": false,
  "direction": "north",
  "burner": {
    "heat": 100,
    "remaining_burning_fuel": 50,
    "currently_burning": "coal"
  },
  "miner": {
    "mining_progress": 0.5,
    "mining_target": {"name": "iron-ore", "amount": 10000},
    "drop_position": {"x": 11, "y": 20}
  }
}
// Note: electric, crafter, inserter, etc. are NOT included (they were None)
```

**For documentation, we describe the master schema once:**

```markdown
## EntityInspection Schema

All entities return `EntityInspection` from `inspect()`. 
Base fields are always present; capability slots are populated based on entity type.

### Base Fields
- `name: str` - Entity name
- `position: Position` - World position
- `status: Optional[EntityStatus]` - Current status
- `is_ghost: bool` - Whether this is a ghost entity
- `direction: Optional[Direction]` - Facing direction

### Capability Slots
- `burner: Optional[BurnerState]` - For fuel-burning entities
- `electric: Optional[ElectricState]` - For electric entities
- `crafter: Optional[CrafterState]` - For crafting machines
- `miner: Optional[MinerState]` - For mining drills
- `inserter: Optional[InserterState]` - For inserters
- `fluid: Optional[FluidState]` - For fluid-handling entities
- `container: Optional[ContainerState]` - For storage containers
- `rocket: Optional[RocketState]` - For rocket silos
- `belt: Optional[BeltState]` - For transport belts
```

This reduces context usage dramatically: define 9 state schemas once, then simply state which slots each entity uses.

---

## Summary

| Aspect | Count |
|--------|-------|
| Total entities inspected | 104 |
| Mixin types | 9 (Burner, Electric, Crafter, Miner, Inserter, Fluid, Container, Rocket, Belt) |
| State BaseModels needed | 9 (one per mixin) + 1 master (`EntityInspection`) |
| Entity classes | ~104 (composed from mixins, no custom inspection code) |

### Key Insights

1. **One Schema to Rule Them All:** `EntityInspection` is the single return type for all `inspect()` calls
2. **Namespaced Composition:** Each mixin's data lives in its own slot (`inspection.burner`, `inspection.miner`, etc.)
3. **Zero Boilerplate for New Entities:** Adding a new entity requires no inspection code — just inherit from the right mixins
4. **Minimal Boilerplate for New Mixins:** Adding a new mixin requires:
   - Define `<Mixin>State(BaseModel)`
   - Add `<mixin>: Optional[<Mixin>State] = None` to `EntityInspection`
   - Add `isinstance` check in `BaseEntity.inspect()`
5. **LLM-Optimized:** Stable schema + `exclude_none=True` = concise, predictable output
