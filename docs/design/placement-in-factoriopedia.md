# Placement Patterns in Factoriopedia - Design Document

> Goal: Move entity-specific placement patterns from system prompt (4,077 tokens) to on-demand Factoriopedia lookup, while maintaining agent capability.

## Design Constraints

1. **Flag-based system prompt verbosity**: Different LLMs have different capabilities. Weaker models may need full examples in system prompt; stronger models can orchestrate factoriopedia lookups. This must be configurable via settings.

2. **No examples in system prompt** (for capable models): Just method signatures and one cohesive end-to-end workflow pattern.

3. **ALL placement methods are entity-specific**: Even `get_placement_line` and `get_underground_segment` - they belong to the entities they operate on.

## Current State Analysis

### System Prompt Placement Content (4,077 tokens)

| Method | Examples | Tokens (est.) | Entity-Specific? |
|--------|----------|---------------|------------------|
| `get_connection_positions` | 3 (ITEM_DROP, FLUID_PIPE, ELECTRIC_WIRE) | 566 | **Yes** (drill, fluid, pole) |
| `get_placement_line` | 2 | 200 | **Yes** (belt, pipe entities) |
| `get_inserter_placement_positions` | 2 | 250 | **Yes** (inserter entities) |
| `get_pole_line` | 2 | 200 | **Yes** (pole entities) |
| `get_pole_coverage_position` | 1 | 100 | **Yes** (pole entities) |
| `get_pole_coverage_plan` | 1 | 150 | **Yes** (pole entities) |
| `get_underground_segment` | 1 | 120 | **Yes** (underground belt/pipe) |
| `evaluate_pole_placement` | 1 | 150 | **Yes** (pole entities) |
| `validator` | 2 | 180 | No (validation utility) |
| Decision points, types, class docs | - | ~1,161 | Mixed |

**Key insight**: ALL placement methods are entity-specific. The system prompt should only contain signatures + one workflow example.

### Entity → Placement Pattern Mapping (Complete)

Every placement method belongs to specific entity types:

| Entity Type | Entities | Placement Methods |
|-------------|----------|-------------------|
| **mining-drill** | burner-mining-drill, electric-mining-drill | `get_connection_positions(ITEM_DROP)` |
| **electric-pole** | small-electric-pole, medium-electric-pole, big-electric-pole, substation | `get_connection_positions(ELECTRIC_WIRE)`, `get_pole_line`, `get_pole_coverage_position`, `get_pole_coverage_plan`, `evaluate_pole_placement` |
| **fluid entities** | boiler, steam-engine, chemical-plant, oil-refinery, pumpjack, pump, offshore-pump | `get_connection_positions(FLUID_PIPE)` |
| **pipe** | pipe, pipe-to-ground, storage-tank | `get_connection_positions(FLUID_PIPE)`, `get_placement_line` |
| **transport-belt** | transport-belt, fast-transport-belt, express-transport-belt | `get_placement_line` |
| **underground-belt** | underground-belt (4 tiles), fast-underground-belt (6), express-underground-belt (8) | `get_underground_segment` |
| **pipe-to-ground** | pipe-to-ground (10 tiles) | `get_underground_segment` |
| **inserter** | inserter, long-handed-inserter, fast-inserter, burner-inserter, etc. | `get_inserter_placement_positions` |
| **splitter** | splitter, fast-splitter, express-splitter | `get_placement_line` (for belt arrays) |

The mapping already partially exists in `placement_hints.py`:
- `ITEM_DROP_ENTITIES`: burner-mining-drill, electric-mining-drill
- `FLUID_PIPE_ENTITIES`: boiler, steam-engine, chemical-plant, oil-refinery, pumpjack, pipe, pipe-to-ground, pump, offshore-pump, storage-tank
- `ELECTRIC_POLE_ENTITIES`: small-electric-pole, medium-electric-pole, big-electric-pole, substation
- `INSERTER_ENTITIES`: inserter, long-handed-inserter, fast-inserter, etc.

**Need to add**:
- `BELT_LINE_ENTITIES`: transport-belt, fast-transport-belt, express-transport-belt, pipe
- `UNDERGROUND_ENTITIES`: underground-belt variants + pipe-to-ground with max distances

---

## Design Questions

### Q1: What placement information belongs on an entity lookup?

**Proposal**: When `factoriopedia("burner-mining-drill", attach_placement_hints=True)`:

```
=== burner-mining-drill ===

[Entity]
  Type: mining-drill
  Size: 2x2
  Power: burner (fuel required)
  ...

[Placement Patterns]   ← NEW SECTION
  Supports: ITEM_DROP

  ITEM_DROP → furnace/chest/belt
    Place target at drill's drop position - receives items directly (no inserter)

    positions = placement_hints.get_connection_positions(
        source_entity=drill,
        target_entity_name="stone-furnace",
        connection_type=ConnectionType.ITEM_DROP
    )  # → List[ConnectionPosition]

    Best position: positions[0] (sorted by perpendicular_offset)
```

### Q2: What about return type variance?

**Key complexity**: `get_connection_positions` returns different types per ConnectionType:
- `ITEM_DROP`, `FLUID_PIPE` → `List[ConnectionPosition]`
- `ELECTRIC_WIRE` → `List[WireConnectionPosition]` (extended with wire_distance, wire_distance_utilization)

**Solution**: Document the return type in the placement pattern output:

```
[Placement Patterns]
  Supports: ELECTRIC_WIRE

  ELECTRIC_WIRE → medium-electric-pole
    Returns: List[WireConnectionPosition]
      - position: MapPosition
      - direction: Optional[Direction]
      - perpendicular_offset: float (lower = better)
      - wire_distance: float (actual tiles)
      - wire_distance_utilization: float (0.0-1.0 of max)

    positions = placement_hints.get_connection_positions(
        source_entity=pole,
        target_entity_name="medium-electric-pole",
        connection_type=ConnectionType.ELECTRIC_WIRE
    )

    Optimal spacing: wire_distance_utilization ~0.7-0.85
```

### Q3: What about pole-specific methods?

Poles have additional methods beyond `ELECTRIC_WIRE`:
- `get_pole_line` - plan a line of poles
- `get_pole_coverage_position` - find single pole to cover entities
- `get_pole_coverage_plan` - greedy coverage algorithm
- `evaluate_pole_placement` - dry-run evaluation

**Proposal**: Include these in pole entity lookups:

```
=== medium-electric-pole ===

[Entity]
  Type: electric-pole
  Wire reach: 9 tiles
  Supply area: 3.5 tile radius
  ...

[Placement Patterns]   ← with attach_placement_hints=True
  Supports: ELECTRIC_WIRE

  Additional pole methods:
    - get_pole_line(start, end, pole_name) → GhostPlan
    - get_pole_coverage_position(entities_to_power, pole_name) → Optional[MapPosition]
    - get_pole_coverage_plan(entities_to_power, pole_name) → (GhostPlan, uncovered)
    - evaluate_pole_placement(position, pole_name, source_pole) → PolePlacementResult
```

### Q4: What about inserters?

Inserters are unique - they connect ANY two entities, not just specific types.

**Proposal**: Show inserter method on inserter entities:

```
=== inserter ===

[Entity]
  Type: inserter
  Reach: 1 tile (pickup to drop)
  ...

[Placement Patterns]
  Method: get_inserter_placement_positions(source, target, inserter_name)
  Returns: List[Tuple[MapPosition, Direction]]

  positions = placement_hints.get_inserter_placement_positions(
      source_entity=chest,
      target_entity=furnace,
      inserter_name="inserter"
  )
```

### Q5: What stays in the system prompt? (Configurable)

**Two separate concerns**:

1. **Factoriopedia API** - Simple boolean gate, no verbosity:
   ```python
   factoriopedia("entity")                    # default output
   factoriopedia("entity", attach_placement_hints=True)    # adds [Placement] section if available
   ```

2. **System prompt configuration** - Controls prompt construction:
   - **Minimal mode**: Signatures + 1 workflow + directive to use factoriopedia
   - **Verbose mode**: Full examples (current state, for weaker models)

#### Minimal System Prompt (~800-1,000 tokens)

1. **Method signatures** (compact, no examples):
```
placement_hints.get_connection_positions(source, target_name, connection_type) → List[ConnectionPosition]
placement_hints.get_inserter_placement_positions(source, target, inserter_name) → List[(MapPosition, Direction)]
placement_hints.get_line(entity_name, start, end) → GhostPlan  # consolidated
placement_hints.get_underground_segment(entity_name, start, end, direction) → GhostPlan
placement_hints.get_pole_coverage_position(entities, pole_name) → Optional[MapPosition]
placement_hints.get_pole_coverage_plan(entities, pole_name) → (GhostPlan, uncovered)
placement_hints.evaluate_pole_placement(position, pole_name) → PolePlacementResult
```

2. **Type definitions** (compact):
```
ConnectionType: ITEM_DROP | FLUID_PIPE | ELECTRIC_WIRE
ConnectionPosition: position, direction, perpendicular_offset
WireConnectionPosition: + wire_distance, wire_distance_utilization
GhostPlan: entity_name, positions, valid
```

3. **One end-to-end workflow** (no method-specific examples):
```python
# Query what you need → get positions → place
drill = reachable_view.get_entity("burner-mining-drill")
positions = placement_hints.get_connection_positions(drill, "stone-furnace", ConnectionType.ITEM_DROP)
inventory.get_item("stone-furnace").place(positions[0].position, positions[0].direction)
# Use factoriopedia("entity-name", attach_placement_hints=True) for entity-specific patterns
```

#### Verbose System Prompt (~4,077 tokens)
Keep full examples. This is the current state, for less capable models.

**Configuration** (separate from factoriopedia):
```yaml
# Agent/environment settings
system_prompt:
  placement_docs: "minimal"  # or "verbose"
```

---

## Metadata Requirements

### Entity → Placement Capability Mapping

Need to extend existing `ENTITY_CAPABILITY_SLOTS` pattern:

```python
# In factoriopedia.py
ENTITY_PLACEMENT_CAPABILITIES = {
    "mining-drill": {
        "capabilities": ["ITEM_DROP"],
        "methods": ["get_connection_positions"],
    },
    "electric-pole": {
        "capabilities": ["ELECTRIC_WIRE"],
        "methods": [
            "get_connection_positions",
            "get_pole_line",
            "get_pole_coverage_position",
            "get_pole_coverage_plan",
            "evaluate_pole_placement",
        ],
    },
    "boiler": {
        "capabilities": ["FLUID_PIPE"],
        "methods": ["get_connection_positions"],
    },
    # ... other fluid entities
    "inserter": {
        "capabilities": [],  # Special case
        "methods": ["get_inserter_placement_positions"],
    },
    # ... other inserter types
}
```

### Return Type Documentation

Need structured return type info:

```python
PLACEMENT_RETURN_TYPES = {
    ("get_connection_positions", "ITEM_DROP"): {
        "type": "List[ConnectionPosition]",
        "fields": ["position: MapPosition", "direction: Optional[Direction]", "perpendicular_offset: float"],
        "sorting": "perpendicular_offset ascending (lower = better aligned)",
    },
    ("get_connection_positions", "ELECTRIC_WIRE"): {
        "type": "List[WireConnectionPosition]",
        "fields": [
            "position: MapPosition",
            "direction: Optional[Direction]",
            "perpendicular_offset: float",
            "wire_distance: float",
            "wire_distance_utilization: float (0.0-1.0)",
        ],
        "sorting": "perpendicular_offset ascending",
        "notes": "Optimal spacing: 0.7-0.85 utilization",
    },
    # ...
}
```

### Example Templates

Minimal code templates per capability:

```python
PLACEMENT_EXAMPLES = {
    "ITEM_DROP": """drill = reachable_view.get_entity("{source}")
positions = placement_hints.get_connection_positions(
    drill, "{target}", ConnectionType.ITEM_DROP
)  # → List[ConnectionPosition]
# positions[0] is best aligned; place target there - receives items directly""",

    "FLUID_PIPE": """entity = reachable_view.get_entity("{source}")
positions = placement_hints.get_connection_positions(
    entity, "pipe", ConnectionType.FLUID_PIPE
)  # → List[ConnectionPosition] with required directions""",

    "ELECTRIC_WIRE": """pole = reachable_view.get_entity("{source}")
positions = placement_hints.get_connection_positions(
    pole, "{target}", ConnectionType.ELECTRIC_WIRE
)  # → List[WireConnectionPosition]
# Optimal: wire_distance_utilization ~0.7-0.85""",
}
```

---

## Resolved Design Decisions

### 1. Consolidate line methods ✓
Merge `get_placement_line` and `get_pole_line` into a single method. The method should be entity-aware:
- Belts/pipes: place entities along vector
- Poles: calculate optimal wire-distance spacing automatically

**Implementation**: Single `get_line` method that checks entity type and applies appropriate spacing logic.

### 2. Examples in Factoriopedia ✓
Include examples when `attach_placement_hints=True`. The examples are entity-specific and show the actual pattern for that entity type.

### 3. No examples in system prompt ✓
Just:
- Method signatures (compact)
- Type definitions
- One cohesive end-to-end workflow pattern
- Directive to use `factoriopedia(entity, attach_placement_hints=True)`

### 4. Multi-capability entities: verbose and bespoke ✓
e.g., `pumpjack`:
- Is a mining-drill but outputs fluid (NOT ITEM_DROP)
- Supports FLUID_PIPE connections
- Show all applicable patterns explicitly

### 5. ALL methods are entity-specific ✓
Every placement method belongs to specific entity types. There are no "general purpose" placement methods - they all attach to entities in factoriopedia.

---

## Implementation Plan

### Phase 1: Factoriopedia Placement Support

1. **Add `attach_placement_hints: bool = False` parameter to `factoriopedia()`**

2. **Create comprehensive entity → placement mapping**
   ```python
   ENTITY_PLACEMENT_PATTERNS = {
       # Connection-based
       "burner-mining-drill": {
           "methods": [("get_connection_positions", "ITEM_DROP")],
           "notes": "Output ore directly to furnace/chest - no inserter needed",
       },
       "medium-electric-pole": {
           "methods": [
               ("get_connection_positions", "ELECTRIC_WIRE"),
               ("get_line", None),  # consolidated method
               ("get_pole_coverage_position", None),
               ("get_pole_coverage_plan", None),
               ("evaluate_pole_placement", None),
           ],
           "properties": {"wire_reach": 9, "supply_area": 3.5},
       },
       "boiler": {
           "methods": [("get_connection_positions", "FLUID_PIPE")],
           "notes": "Connect to pipes for water input and steam output",
       },
       # Line-based
       "transport-belt": {
           "methods": [("get_line", None)],
       },
       "underground-belt": {
           "methods": [("get_underground_segment", None)],
           "properties": {"max_distance": 4},
       },
       # Inserter
       "inserter": {
           "methods": [("get_inserter_placement_positions", None)],
       },
       # ... all other entities
   }
   ```

3. **Create `_format_placement_section()` method**
   - Shows applicable methods for this entity
   - Shows return type with field documentation
   - Shows bespoke example for each method
   - Handle multi-capability entities verbosely

4. **Consolidate line methods** (separate task)
   - Merge `get_placement_line` and `get_pole_line` into `get_line`
   - Entity-aware spacing logic

### Phase 2: System Prompt Configurability (Separate from Factoriopedia)

5. **Add placement docs setting** (in environment/agent config, NOT factoriopedia)
   ```python
   # In environment or agent config
   class SystemPromptConfig:
       placement_docs: Literal["minimal", "verbose"] = "minimal"
   ```

6. **Create two prompt templates**
   - `placement_minimal.md` - signatures + 1 workflow + directive (~800 tokens)
   - `placement_verbose.md` - current full examples (~4,077 tokens)

7. **Update prompt generator** to select based on config

### Phase 3: Measurement

8. **Token measurement**
   - Baseline: 4,077 tokens (placement section)
   - Target (minimal): ~800 tokens
   - Savings: ~3,200 tokens (78% reduction in placement section)

### Phase 4: Validation

9. **Test with agent runs**
   - Verify factoriopedia provides sufficient context
   - Verify capable models use factoriopedia appropriately
   - Verify verbose mode still works for weaker models

---

## Example Output

```
$ factoriopedia burner-mining-drill --placement

=== burner-mining-drill ===

[Item]
  Stack: 50
  Obtained: crafted (see [Recipe])

[Recipe]
  Ingredients: 3x iron-gear-wheel + 3x iron-plate + 1x stone-furnace
  Products: 1x burner-mining-drill
  Energy: 120 ticks (base)
  Made in:
    - assembling-machine-3 (96 ticks)
    - assembling-machine-2 (160 ticks)
    - assembling-machine-1 (240 ticks)
    - character (120 ticks)
  Unlocked by: available from start

[Entity]
  Type: mining-drill
  Size: 2x2
  Power: burner (fuel required)
  Properties:
    - mining_speed: 0.25
    - mining_radius: 0.99
  Inspection slots (.inspect()):
    - burner: heat, remaining_burning_fuel, fuel_inventory, currently_burning
    - miner: mining_progress, mining_target

[Placement]
  Supports: ITEM_DROP

  ITEM_DROP: Output ore directly to adjacent furnace/chest/belt
    Returns: List[ConnectionPosition]
      - position: MapPosition
      - direction: Optional[Direction]
      - perpendicular_offset: float (lower = better)

    positions = placement_hints.get_connection_positions(
        drill, "stone-furnace", ConnectionType.ITEM_DROP
    )
    # Place furnace at positions[0] - receives ore without inserters
```

---

## Summary

| What | Where (minimal mode) | Notes |
|------|----------------------|-------|
| Entity → placement patterns | factoriopedia | `attach_placement_hints=True` parameter, bespoke per entity |
| Return types per method | factoriopedia | Structured field documentation |
| Code examples per method | factoriopedia | Entity-specific, verbose |
| Method signatures | system prompt | Compact, no examples |
| Type definitions | system prompt | ConnectionType, ConnectionPosition, GhostPlan |
| 1 end-to-end workflow | system prompt | Shows pattern + directive to use factoriopedia |
| All placement examples | *removed* | Moved to factoriopedia lookups |

### Token Budget

| Mode | Placement Tokens | Notes |
|------|------------------|-------|
| Current (verbose) | 4,077 | All examples in system prompt |
| Minimal (capable models) | ~800 | Signatures + 1 workflow + directive |
| **Savings** | **~3,200 (78%)** | Factoriopedia provides on-demand context |

### Two Separate Concerns

**1. Factoriopedia API** - Simple boolean gate:
```python
factoriopedia("burner-mining-drill")                  # default
factoriopedia("burner-mining-drill", attach_placement_hints=True)  # adds [Placement] section
```
No verbosity levels. Just attach placement hints or don't.

**2. System prompt configuration** - Separate from factoriopedia:
```yaml
# Agent/environment settings
system_prompt:
  placement_docs: "minimal"   # signatures + directive
  # or
  placement_docs: "verbose"   # full examples (current state)
```

This separation ensures:
- Factoriopedia stays simple and predictable
- System prompt optimization is an orthogonal configuration concern
- Weaker models can still get verbose prompts while capable models benefit from reduced size
