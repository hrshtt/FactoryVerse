# Factoriopedia Redesign

> Design document for the agent-facing knowledge lookup system.

## Motivation

### The Problem

Agents need detailed information about entities, recipes, and technologies to plan and execute factory builds. Currently this information is either:
1. **In the system prompt** - bloating context with static reference data (~30-50k tokens)
2. **Missing entirely** - agents don't know machine crafting speeds, recipe times, etc.

### The Insight: Two Mediums

**Source medium (Factorio UI):**
- Visual, click-driven
- Player hovers over entity → tooltip shows properties
- Right-click → full Factoriopedia page with all details
- The UI is external memory - players don't memorize machine speeds

**Target medium (LLM Agent):**
- Text-based, limited context window
- No visual game state understanding
- Must explicitly query for information
- Needs computed values, not formulas to apply

### The Solution

Factoriopedia becomes the agent's equivalent of "clicking on something to learn about it."

- **System prompt**: Explains the *system* (type hierarchy, mixins, top-level API, DuckDB schema)
- **Factoriopedia**: Provides *specific details* on demand (entity properties, recipe times, tech trees)

This reduces system prompt size while keeping all information accessible.

---

## What Stays in System Prompt

These cannot be sliced and must be understood upfront:

1. **Top-level API modules**: `walking`, `crafting`, `inventory`, `research`, `reachable_view`, `remote_view`, `placement_hints`, `ghost_builder`

2. **Mixin/capability system**: The concept that entities have capabilities (Burner, Electric, Crafter, Miner, etc.) that determine available methods

3. **DuckDB schema**: Table structures for spatial queries via `remote_view`

4. **Crafting speed concept** (brief):
   ```
   Machines have different crafting speeds. Use factoriopedia(name) to see
   computed crafting times for any recipe.

   Reference speeds: character=1.0x, AM1=0.5x, AM2=0.75x, AM3=1.25x
   ```

5. **Factoriopedia usage**: How and when to use the lookup tool

---

## What Moves to Factoriopedia

Specific details looked up on demand:

- Entity properties (crafting_speed, mining_speed, power consumption, footprint)
- Entity methods (introspected from Python classes)
- Recipe ingredients, products, and computed crafting times per machine
- Technology costs, prerequisites, unlocks
- "Used in" relationships (what recipes consume an item)
- Example usage snippets (optional)

---

## Tool Design

### Signature

```python
def factoriopedia(
    name: str,
    verbose: bool = False,
    include_examples: bool = False,
    time_format: Literal["ticks", "seconds", "both"] = "ticks"
) -> str
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | str | required | Entity, item, recipe, or technology name |
| `verbose` | bool | False | Show full "used in" lists vs truncated (top 5) |
| `include_examples` | bool | False | Include code usage snippets |
| `time_format` | str | "ticks" | How to display crafting times |

### Auto-Detection

The tool auto-detects which facets apply to the given name:
- **Item**: Has stack_size in item prototype data
- **Recipe**: Exists in recipe prototype data
- **Entity**: Exists in entity prototype data (any category)
- **Technology**: Exists in technology prototype data

Many things are multiple types: `fast-inserter` is Item + Recipe + Entity.

---

## Output Format

### Item Facet

```
[Item]
  Stack: 50
  Obtained: crafted | mined by: burner-mining-drill, electric-mining-drill
```

### Recipe Facet

```
[Recipe]
  Ingredients: 2x iron-plate + 2x electronic-circuit + 1x inserter
  Products: 1x fast-inserter
  Energy: 30 ticks (base)
  Made in:
    - character (30 ticks)
    - assembling-machine-1 (60 ticks)
    - assembling-machine-2 (40 ticks)
    - assembling-machine-3 (24 ticks)
  Unlocked by: fast-inserter (technology)
```

**Key design decision**: Show computed ticks per machine, not relative speeds. The agent sees actionable numbers without doing math.

### Entity Facet

```
[Entity]
  Type: inserter
  Size: 1x1
  Power: 46.2kW (electric)
  Properties:
    - rotation_speed: 864°/s
    - filterable: true
  Mixins: Electric, Inserter, Rotatable
  Methods: rotate(), set_filter(item), inspect()
```

For crafters:
```
[Entity]
  Type: assembling-machine
  Size: 3x3
  Power: 150kW (electric)
  Properties:
    - crafting_speed: 0.75
  Crafts: basic-crafting, crafting, advanced-crafting, crafting-with-fluid
  Mixins: Electric, Crafter, SetRecipe
  Methods: set_recipe(name), add_ingredients(stacks), take_products(), inspect()
```

### Technology Facet

```
[Technology]
  Cost: 50 x automation-science-pack (300 ticks per pack)
  Total: 15000 ticks in 1 lab
  Prerequisites: automation-science-pack
  Unlocks:
    - steel-plate (recipe)
    - steel-chest (recipe)
  Leads to: advanced-material-processing, automation-2, ...
```

### Used In (appears for items)

```
[Used in] (showing 5 of 44)
  - iron-gear-wheel, electronic-circuit, transport-belt, inserter, pipe, ...
```

With `verbose=True`:
```
[Used in] (44 recipes)
  - iron-gear-wheel, electronic-circuit, transport-belt, inserter, pipe,
    steel-plate, stone-furnace, burner-mining-drill, electric-mining-drill,
    ... (full list)
```

### Example (if include_examples=True)

```
[Example]
  inserter = reachable_view.get_entity("fast-inserter", position)
  inserter.set_filter("iron-plate")
  await inserter.rotate()
```

---

## Complete Example Output

```
=== fast-inserter ===

[Item]
  Stack: 50

[Recipe]
  Ingredients: 2x iron-plate + 2x electronic-circuit + 1x inserter
  Products: 1x fast-inserter
  Energy: 30 ticks (base)
  Made in:
    - character (30 ticks)
    - assembling-machine-1 (60 ticks)
    - assembling-machine-2 (40 ticks)
    - assembling-machine-3 (24 ticks)
  Unlocked by: fast-inserter (technology)

[Entity]
  Type: inserter
  Size: 1x1
  Power: 46.2kW max, 500W idle (electric)
  Properties:
    - rotation_speed: 864°/s
    - filterable: true
  Mixins: Electric, Inserter, Rotatable
  Methods: rotate(), set_filter(item), inspect()

[Used in] (showing 5 of 1)
  - bulk-inserter
```

---

## Implementation Plan

### Data Sources

| Data | Source | Notes |
|------|--------|-------|
| Item properties | `factorio-data-dump.json` → `item` | stack_size |
| Recipe data | `factorio-data-dump.json` → `recipe` | ingredients, energy, category |
| Entity properties | `factorio-data-dump.json` → `assembling-machine`, `furnace`, etc. | crafting_speed, power, size |
| Technology data | `factorio-data-dump.json` → `technology` | effects, prerequisites, unit |
| Machine speeds | `factorio-data-dump.json` → entity categories | For computing recipe times |
| Methods | Python class introspection | Runtime, cached at init |
| Mixins | Entity class hierarchy | Map entity type → mixins |
| Examples | TBD: docstrings or separate file | Per-entity code snippets |

### Method Introspection

To get methods for an entity type:

1. Map entity name → entity type (e.g., `fast-inserter` → `inserter`)
2. Map entity type → Python class (e.g., `inserter` → `Inserter`)
3. Introspect class for public methods (exclude `_private`, include from mixins)
4. Filter to "Factoriopedia-worthy" methods via decorator or registry

```python
# Option A: Decorator
@factoriopedia_method
def set_filter(self, item: str) -> None:
    ...

# Option B: Registry
FACTORIOPEDIA_METHODS = {
    "Inserter": ["rotate", "set_filter", "inspect"],
    "Crafter": ["set_recipe", "add_ingredients", "take_products", "inspect"],
    ...
}
```

### Computing Recipe Times

```python
def get_crafting_times(recipe_name: str) -> dict[str, int]:
    """Return {machine_name: ticks} for all machines that can craft this recipe."""
    recipe = recipes[recipe_name]
    base_energy = recipe.energy  # ticks at speed 1.0
    category = recipe.category

    times = {}
    for machine_name, machine in machines.items():
        if category in machine.crafting_categories:
            actual_ticks = math.ceil(base_energy / machine.crafting_speed)
            times[machine_name] = actual_ticks

    # Always include character for hand-craftable
    if category == "crafting":
        times["character"] = base_energy  # speed 1.0

    return times
```

### File Structure

```
src/FactoryVerse/game/factory/
├── factoriopedia.py          # Existing file, to be refactored
├── factoriopedia/
│   ├── __init__.py           # Main Factoriopedia class
│   ├── formatters.py         # Output formatting functions
│   ├── lookups.py            # Data lookup helpers
│   ├── introspection.py      # Method/mixin introspection
│   └── examples.py           # Example snippet storage (if separate)
```

Or keep it simple in single file if complexity is manageable.

---

## System Prompt Changes

### Remove

- Detailed entity-by-mixin listings (~200+ lines)
- Per-entity method documentation
- Possibly: recipe/tech listings (moved to initial state or on-demand)

### Add

```markdown
## Factoriopedia

Use `factoriopedia(name)` to look up details about any entity, recipe, item, or technology.

Returns: properties, crafting times, ingredients, methods, unlock requirements.

Examples:
- `factoriopedia("assembling-machine-2")` - machine properties and methods
- `factoriopedia("advanced-circuit")` - recipe details with per-machine crafting times
- `factoriopedia("automation-2")` - technology cost and unlocks

Options:
- `verbose=True` - show full "used in" lists
- `include_examples=True` - show code usage snippets

### Crafting Speed Reference

Machines craft at different speeds. Factoriopedia shows computed times per machine.

| Machine | Speed | | Machine | Speed |
|---------|-------|-|---------|-------|
| character | 1.0x | | stone-furnace | 1.0x |
| assembling-machine-1 | 0.5x | | steel-furnace | 2.0x |
| assembling-machine-2 | 0.75x | | electric-furnace | 2.0x |
| assembling-machine-3 | 1.25x | | chemical-plant | 1.0x |
```

---

## Migration Path

1. **Phase 1**: Implement new Factoriopedia with computed times and method introspection
2. **Phase 2**: Wire to agent runtime (expose as tool or accessible object)
3. **Phase 3**: Update system prompt - remove entity listings, add Factoriopedia docs
4. **Phase 4**: Add example snippets (optional, based on value observed)
5. **Phase 5**: Measure token reduction and agent performance

---

## Open Questions

1. **Example snippets source**: Docstrings? Separate YAML/JSON file? Generated from tests?

2. **Method filtering**: How to mark which methods appear in Factoriopedia?
   - Decorator approach is explicit but requires touching all methods
   - Registry approach is centralized but can drift from implementation

3. **Caching**: Cache formatted output strings? Or regenerate each call?
   - Data is static (from prototype dump), so caching is safe
   - LRU cache on the lookup function seems sufficient

4. **Error handling**: What if name doesn't exist?
   - Return "Not found: {name}. Did you mean: {suggestions}?"
   - Fuzzy match against known names

5. **Integration point**: Tool call vs object method?
   - Tool call: `factoriopedia("iron-plate")` in agent code
   - Object: `wiki.lookup("iron-plate")`
   - Both could work; tool call is more explicit for LLM

---

## Implementation Details (from Data Dump Analysis)

### Data Dump Structure

The `factorio-data-dump.json` organizes data by **type** as top-level keys:

```
item                    → {name: {stack_size, subgroup, place_result?, ...}}
recipe                  → {name: {ingredients, results, energy_required, category, enabled}}
technology              → {name: {unit, prerequisites, effects}}

# Entity categories (each contains entities of that type):
assembling-machine      → includes chemical-plant, oil-refinery, centrifuge
furnace                 → stone-furnace, steel-furnace, electric-furnace
mining-drill            → burner-mining-drill, electric-mining-drill, pumpjack
inserter                → inserter, fast-inserter, bulk-inserter, etc.
transport-belt          → transport-belt, fast-transport-belt, express-transport-belt
underground-belt        → underground-belt, fast-underground-belt, etc.
splitter                → splitter, fast-splitter, express-splitter
electric-pole           → small-electric-pole, medium-electric-pole, big-electric-pole, substation
container               → wooden-chest, iron-chest, steel-chest, + logistic chests
boiler                  → boiler, heat-exchanger
generator               → steam-engine, steam-turbine
lab                     → lab
...
```

### Entity Category List

```python
ENTITY_CATEGORIES = [
    "assembling-machine", "furnace", "mining-drill", "inserter",
    "transport-belt", "underground-belt", "splitter", "loader",
    "electric-pole", "pipe", "pipe-to-ground", "pump",
    "boiler", "generator", "offshore-pump",
    "container", "logistic-container", "storage-tank",
    "lab", "radar", "beacon", "roboport", "rocket-silo",
    "accumulator", "solar-panel", "lamp", "wall", "gate"
]
```

### Key Fields Per Entity Type

**Crafters (`assembling-machine`, `furnace`):**
```json
{
  "crafting_speed": 0.75,
  "crafting_categories": ["crafting", "advanced-crafting", "crafting-with-fluid"],
  "energy_usage": "150kW",
  "energy_source": {"type": "electric" | "burner"},
  "module_slots": 2,
  "collision_box": [[-1.2, -1.2], [1.2, 1.2]]
}
```

**Miners (`mining-drill`):**
```json
{
  "mining_speed": 0.5,
  "resource_categories": ["basic-solid"],
  "resource_searching_radius": 2.49,
  "energy_usage": "90kW",
  "energy_source": {"type": "electric" | "burner"}
}
```

**Inserters:**
```json
{
  "rotation_speed": 0.04,          // fraction of full rotation per tick
  "extension_speed": 0.1,
  "filter_count": 5,               // 0 if not filterable
  "energy_per_movement": "7kJ",
  "energy_per_rotation": "7kJ",
  "energy_source": {"type": "electric", "drain": "0.5kW"}
}
```

**Belts (`transport-belt`):**
```json
{
  "speed": 0.03125                 // tiles per tick (items/tick/lane = speed * 8)
}
```

**Electric Poles:**
```json
{
  "maximum_wire_distance": 9,
  "supply_area_distance": 3.5
}
```

**Generators (`steam-engine`):**
```json
{
  "effectivity": 1,
  "fluid_usage_per_tick": 0.5,
  "maximum_temperature": 165
}
```

**Labs:**
```json
{
  "researching_speed": 1,
  "inputs": ["automation-science-pack", "logistic-science-pack", ...]
}
```

**Containers:**
```json
{
  "inventory_size": 16
}
```

### Recipe Structure

```json
{
  "name": "advanced-circuit",
  "category": "crafting",
  "energy_required": 6,              // base ticks at speed 1.0
  "enabled": false,                  // needs tech unlock
  "ingredients": [
    {"type": "item", "name": "electronic-circuit", "amount": 2},
    {"type": "item", "name": "plastic-bar", "amount": 2},
    {"type": "fluid", "name": "petroleum-gas", "amount": 20}  // for fluid recipes
  ],
  "results": [
    {"type": "item", "name": "advanced-circuit", "amount": 1}
  ]
}
```

### Technology Structure

```json
{
  "name": "automation-2",
  "prerequisites": ["automation", "steel-processing", "logistic-science-pack"],
  "unit": {
    "count": 40,                     // number of cycles
    "time": 15,                      // seconds per cycle at speed 1.0
    "ingredients": [
      ["automation-science-pack", 1],
      ["logistic-science-pack", 1]
    ]
  },
  "effects": [
    {"type": "unlock-recipe", "recipe": "assembling-machine-2"}
  ]
}
```

### Item Structure

```json
{
  "name": "assembling-machine-2",
  "stack_size": 50,
  "subgroup": "production-machine",
  "place_result": "assembling-machine-2"   // links to entity
}
```

### Lookup Resolution Logic

```python
def resolve_name(name: str, data: dict) -> dict:
    """Resolve a name to all its facets."""
    facets = {}

    # Check if it's an item
    if name in data.get("item", {}):
        facets["item"] = data["item"][name]

    # Check if it's a recipe
    if name in data.get("recipe", {}):
        facets["recipe"] = data["recipe"][name]

    # Check if it's a technology
    if name in data.get("technology", {}):
        facets["technology"] = data["technology"][name]

    # Check all entity categories
    for category in ENTITY_CATEGORIES:
        if category in data and name in data[category]:
            facets["entity"] = data[category][name]
            facets["entity_type"] = category
            break

    return facets
```

### Computing Footprint from Collision Box

```python
def get_footprint(collision_box: list) -> tuple[int, int]:
    """Convert collision_box to width x height."""
    # collision_box = [[x1, y1], [x2, y2]]
    x1, y1 = collision_box[0]
    x2, y2 = collision_box[1]
    width = math.ceil(x2 - x1)
    height = math.ceil(y2 - y1)
    return (width, height)

# Examples:
# assembling-machine: [[-1.2, -1.2], [1.2, 1.2]] → 3x3
# inserter: [[-0.15, -0.15], [0.15, 0.15]] → 1x1
# boiler: [[-1.29, -0.79], [1.29, 0.79]] → 3x2
```

### Crafter Machine Index

Build once at init, used for computing recipe times:

```python
CRAFTER_MACHINES = {}  # {name: {speed, categories, energy_source}}

def build_crafter_index(data: dict) -> dict:
    """Index all machines that can craft recipes."""
    crafters = {}

    # Assembling machines (includes chemical-plant, oil-refinery, centrifuge)
    for name, entity in data.get("assembling-machine", {}).items():
        crafters[name] = {
            "speed": entity.get("crafting_speed", 1.0),
            "categories": entity.get("crafting_categories", []),
            "energy_source": entity.get("energy_source", {}).get("type", "unknown")
        }

    # Furnaces
    for name, entity in data.get("furnace", {}).items():
        crafters[name] = {
            "speed": entity.get("crafting_speed", 1.0),
            "categories": entity.get("crafting_categories", []),
            "energy_source": entity.get("energy_source", {}).get("type", "unknown")
        }

    # Character (always speed 1.0, category "crafting")
    crafters["character"] = {
        "speed": 1.0,
        "categories": ["crafting"],
        "energy_source": "none"
    }

    return crafters
```

### Recipe-to-Tech Reverse Index

```python
def build_tech_unlock_index(data: dict) -> dict:
    """Map recipe names to the tech that unlocks them."""
    recipe_to_tech = {}

    for tech_name, tech_data in data.get("technology", {}).items():
        for effect in tech_data.get("effects", []):
            if effect.get("type") == "unlock-recipe":
                recipe_to_tech[effect["recipe"]] = tech_name

    return recipe_to_tech
```

### Item Usage Reverse Index

```python
def build_usage_index(data: dict) -> dict:
    """Map item names to recipes that use them as ingredients."""
    item_to_recipes = {}

    for recipe_name, recipe_data in data.get("recipe", {}).items():
        for ingredient in recipe_data.get("ingredients", []):
            item_name = ingredient.get("name")
            if item_name:
                if item_name not in item_to_recipes:
                    item_to_recipes[item_name] = []
                item_to_recipes[item_name].append(recipe_name)

    return item_to_recipes
```

---

## Success Criteria

1. **Token reduction**: System prompt reduced by 30%+ (measure before/after)
2. **Information completeness**: Agent can find any entity/recipe/tech detail via lookup
3. **Computed values**: Agent sees actual crafting times, not formulas
4. **Method discovery**: Agent can find available methods for any entity type
5. **Usability**: Agent naturally uses Factoriopedia when planning builds
