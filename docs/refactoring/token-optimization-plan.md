# Token Optimization Plan

> Working document for reducing token usage in FactoryVerse agent runs.

## Current State Analysis

| Component | Est. Tokens | Frequency | Issue |
|-----------|-------------|-----------|-------|
| System prompt (full) | ~30-50k | Every turn | Massive, static |
| Initial state | ~5-10k | Session start | Code+output duplication |
| Tool results | Unbounded | Per tool call | No truncation |
| Verification injection | ~500+ chars | After every tool | Always injected |
| Context compression | 80k threshold | When exceeded | Too late |

---

## Proposals

### 1. Verification as Tool Call

**Current**: Verification runs after every tool call, result injected as user message.

**Proposed**: Provide `check_progress()` tool. Agent calls it when it believes it's made meaningful changes.

**Benefits**:
- Agent controls when to check (reduces noise)
- Fewer injected messages
- Agent learns verification cadence

**Implementation**:
- Add `check_progress` to tool definitions
- Remove automatic `_check_task_verification()` call from orchestrator loop
- Agent invokes explicitly

**Open questions**:
- Should we hint in system prompt when to check? (e.g., "check after placing entities")
- Do we need a minimum interval to prevent spam?

---

### 2. System Prompt Restructuring

#### 2.1 Top-Level Module Descriptions Only

**Current**: Full method signatures with docstrings and examples for all accessors.

**Proposed**: One-liner descriptions per top-level object.

```markdown
## Available Modules

- `walking` - Movement. `await walk_to(pos)`, `current_position`
- `crafting` - Hand-craft items. `await craft(recipe, count)`
- `inventory` - Check items, create stacks
- `reachable_view` - Query nearby entities/resources
- `remote_view` - SQL queries for map-wide data
- `placement_hints` - Plan entity placements
- `ghost_builder` - Build ghost entities
```

Full signatures available via Factoriopedia or filesystem read.

---

#### 2.2 Mixin-Based Documentation (Not Entity-Based)

**Current**: API reference lists entities grouped by capability combination:
```markdown
### Burner, Crafter
**Entities:** steel-furnace, stone-furnace

### Burner, Fluid, Rotatable
**Entities:** boiler

### Electric, Crafter, SetRecipe
**Entities:** assembling-machine-1, assembling-machine-2, ...
```

This duplicates information and scales poorly with entity count.

**Proposed**: Document the mixin system, not individual entities:

```markdown
## Capability Mixins

Entities have capabilities that determine available actions and state:

| Mixin | Actions | Inspection State |
|-------|---------|------------------|
| Burner | `add_fuel(stacks)`, `take_fuel()` | `burner.fuel_inventory`, `burner.remaining_fuel` |
| Crafter | `add_ingredients(stacks)`, `take_products()` | `crafter.recipe`, `crafter.progress`, `crafter.output_inventory` |
| Electric | (passive - needs power) | `electric.status`, `electric.power_usage` |
| Miner | `get_resource_search_area()` | `miner.mining_target`, `miner.mining_progress` |
| Inserter | `set_filter(item)` | `inserter.filter`, `inserter.hand_contents` |
| Fluid | `get_fluid()` | `fluid.fluid_boxes` |
| Rotatable | `rotate()` | `direction` |
| SetRecipe | `set_recipe(name)` | (via crafter state) |
| Belt | (passive) | `belt.contents` |

Use `factoriopedia("entity:<name>")` to see which mixins a specific entity has.
```

**Benefits**:
- Entity reference section eliminated (~200 lines saved)
- Agent learns the *system*, not memorizes entity lists
- New entities automatically work if they follow mixin pattern
- Factoriopedia provides entity→mixin mapping on demand

---

#### 2.3 Early-Game Examples Only

**Current**: Examples use various entities throughout docs.

**Proposed**: System prompt examples only use early unlocks:
- `burner-mining-drill`, `stone-furnace`
- `transport-belt`, `inserter`, `burner-inserter`
- `offshore-pump`, `boiler`, `steam-engine`
- `small-electric-pole`, `wooden-chest`

Advanced entity usage (assemblers, electric drills, oil) learned via Factoriopedia.

---

#### 2.4 Factoriopedia Tool

**Concept**: Query tool for game knowledge on demand.

```python
def factoriopedia(query: str) -> str:
    """
    Query game knowledge.

    Examples:
      factoriopedia("entity:electric-mining-drill")
      factoriopedia("recipe:electronic-circuit")
      factoriopedia("category:smelting")
      factoriopedia("mixin:Burner")
      factoriopedia("connection:FLUID_PIPE")
    """
```

**Returns**:

| Query Type | Returns |
|------------|---------|
| `entity:<name>` | Mixins, footprint, fuel type, placement constraints, connection points |
| `recipe:<name>` | Ingredients, products, category, crafting time, required machine |
| `category:<name>` | All recipes in category (smelting, crafting, chemistry, etc.) |
| `mixin:<name>` | Actions, state fields, example usage |
| `connection:<type>` | Valid source entities, placement examples |

**Example output for `entity:electric-mining-drill`**:
```
electric-mining-drill
  Mixins: Electric, Miner, Rotatable
  Footprint: 3x3
  Power: 90kW
  Mining area: 5x5 centered
  Placement: Must be on resource tiles
  Actions: rotate(), get_resource_search_area()
  Inspection: miner.mining_target, miner.mining_progress, electric.status
```

**Benefits**:
- Agent learns what it needs when it needs it
- Dramatic token reduction in system prompt (~200+ lines of entity reference eliminated)
- Natural curiosity-driven exploration
- Mixin documentation stays in system prompt (small, stable), entity specifics on-demand

---

#### 2.5 Alternative: Filesystem-Based Documentation

Per Anthropic's MCP patterns, agent can read documentation files directly.

**Structure**:
```
docs/agent-reference/
├── modules/
│   ├── walking.md
│   ├── crafting.md
│   ├── inventory.md
│   └── ...
├── entities/
│   ├── burner-mining-drill.md
│   ├── stone-furnace.md
│   └── ...
├── recipes/
│   └── by-category/
│       ├── crafting.md
│       ├── smelting.md
│       └── ...
└── patterns/
    ├── mining-setup.md
    ├── power-generation.md
    └── ...
```

Agent uses `Read` tool (or similar) to access docs as needed.

**Trade-offs vs Factoriopedia**:
| Aspect | Factoriopedia | Filesystem |
|--------|---------------|------------|
| Setup cost | Tool implementation | Doc generation |
| Agent UX | Single query interface | Must know file paths |
| Flexibility | Structured queries | Free-form exploration |
| Maintenance | Update tool logic | Update markdown files |

**Decision needed**: Which approach? Or hybrid?

---

### 3. API Consolidation (Within Each View)

**Important**: `reachable_view` and `remote_view` remain separate - they represent fundamentally different contexts (nearby/mutable vs map-wide/read-only). The consolidation is about reducing method count **within** each view.

#### 3.1 Reachable View

**Current** (5 methods):
```python
reachable_view.get_entity(name, position=None)    # singular, Optional return
reachable_view.get_entities(name=None)            # plural, List return
reachable_view.get_resource(name, position=None)  # singular
reachable_view.get_resources(name=None)           # plural (returns patches)
reachable_view.get_ghosts(name=None)              # separate ghost method
```

**Proposed** (2 methods):
```python
reachable_view.get_entities(
    name: str = None,
    position: MapPosition = None,  # filter to specific position
    ghost: bool = False,           # include/filter to ghosts
    limit: int = None,             # cap results
) -> List[Entity]

reachable_view.get_resources(
    name: str = None,
    position: MapPosition = None,
    type: str = None,  # "resource" | "tree" | "rock"
) -> List[Resource]
```

**Pattern for singular**: `entities[0] if entities else None`

---

#### 3.2 Remote View

**Current** (5 methods):
```python
remote_view.get_entity(sql)       # singular
remote_view.get_entities(sql)     # plural
remote_view.get_resources(sql)    # plural
remote_view.get_ghosts(sql)       # separate
remote_view.query(sql)            # raw rows
```

**Proposed** (3 methods):
```python
remote_view.get_entities(
    sql: str = None,              # raw SQL (full control)
    name: str = None,             # simple filter (generates SQL)
    ghost: bool = False,          # filter to ghosts
    area: BoundingBox = None,     # spatial filter
    limit: int = None,
) -> List[Entity]

remote_view.get_resources(
    sql: str = None,
    name: str = None,
    area: BoundingBox = None,
    limit: int = None,
) -> List[Resource]

remote_view.query(sql: str) -> List[Dict]  # raw SQL, raw rows
```

---

**Benefits**:
- 10 methods → 5 methods (50% reduction)
- Fewer concepts to document
- Filters are composable (name + ghost + limit)
- Singular/plural distinction removed (just use `[0]` or check length)

**Migration**:
- `get_entity(name)` → `get_entities(name=name, limit=1)[0]`
- `get_ghosts(name)` → `get_entities(name=name, ghost=True)`

---

### 4. Initial State Simplification

**Current**: Shows Python code + output for each query.

**Proposed**: Output only, with brief description.

```markdown
## Your Position
(10.5, 20.3)

## Inventory
- iron-plate: 50
- coal: 25

## Nearby Resources
| Resource | Tiles | Total Amount | Centroid |
|----------|-------|--------------|----------|
| iron-ore | 127 | 450,000 | (15.2, 8.1) |
| coal | 89 | 320,000 | (-22.4, 12.5) |

## Placed Entities
| Entity | Count |
|--------|-------|
| burner-mining-drill | 3 |
| stone-furnace | 2 |
```

**Implementation**: Trivial change to `InitialStateGenerator`.

---

### 5. Tool Result Truncation

**Current**: Full results added to message history.

**Proposed**: Truncate before adding to LLM context.

```python
MAX_TOOL_RESULT_CHARS = 3000

def truncate_for_context(result: str) -> str:
    if len(result) <= MAX_TOOL_RESULT_CHARS:
        return result
    return result[:MAX_TOOL_RESULT_CHARS] + f"\n... (truncated, {len(result)} total chars)"
```

**Full result still**:
- Logged to chat.md
- Written to trajectory.jsonl
- Available for debugging

---

### 6. Lower Compression Threshold

**Current**: 80k tokens (80% of 100k max)

**Proposed**: 40-50k tokens

Also consider smarter compression:
- Summarize old tool results more aggressively
- Keep user requests but compress tool outputs
- Retain task-relevant context (verification history)

---

## Implementation Priority

| Change | Effort | Impact | Priority |
|--------|--------|--------|----------|
| Initial state: output only | Low | Medium | P0 |
| Verification as tool | Medium | Medium | P0 |
| Tool result truncation | Low | High | P0 |
| Lower compression threshold | Trivial | Medium | P1 |
| System prompt: top-level only | Medium | High | P1 |
| Mixin-based docs (not entity-based) | Medium | High | P1 |
| Reduce documented method surface | Low | Medium | P1 |
| API method consolidation | Medium | Medium | P2 |
| Factoriopedia tool | High | High | P2 |
| Filesystem docs | Medium | Medium | P3 |

---

---

### 4. Placement Hints API (Under Consideration)

Exploring whether the `placement_hints` API can be simplified without losing functionality.

#### Current API Surface

**PlacementHints (9 methods):**
| Method | Purpose |
|--------|---------|
| `get_placement_line` | Line of entities (1 tile spacing) |
| `get_pole_line` | Line of poles (max wire distance spacing) |
| `get_connection_positions` | Where to place NEW entity to connect to source |
| `get_inserter_placement_positions` | Where to place inserter BETWEEN two existing entities |
| `get_pole_coverage_position` | Single pole to cover all entities (or None) |
| `get_pole_coverage_plan` | Minimum poles to cover entities (set cover) |
| `get_underground_segment` | Underground entry/exit pair |
| `evaluate_pole_placement` | Dry-run evaluation at specific position |
| `validator` | Exposes validation methods |

**Validator (4 methods):**
- `validate_placement` - single position
- `validate_batch` - multiple positions
- `validate_line` - convenience wrapper
- `validate_grid` - convenience wrapper

#### Potential Consolidations

**A. Merge `get_pole_line` into `get_placement_line`**

Both create lines of entities. Only difference is spacing logic:
- Regular entities: 1 tile apart
- Poles: max wire distance apart

Could auto-detect pole entities and adjust spacing automatically. Agent wouldn't need to know about `get_pole_line` at all.

```python
# Current: two methods
plan = placement_hints.get_placement_line("transport-belt", start, end)
plan = placement_hints.get_pole_line(start, end, "medium-electric-pole")

# Potential: one method, auto-detects poles
plan = placement_hints.get_placement_line("transport-belt", start, end)
plan = placement_hints.get_placement_line("medium-electric-pole", start, end)  # auto wire spacing
```

**Consideration**: Simple change, low risk. Reduces cognitive load.

---

**B. Remove `validate_line` and `validate_grid`**

These are convenience wrappers that:
1. Calculate positions (line or grid)
2. Call `validate_batch`

Most validation happens implicitly via `get_placement_line` (which already validates). Direct validator use is rare.

**Consideration**: Removes 2 methods from validator. Agent can still do batch validation if needed.

---

**C. Keep `get_connection_positions` and `get_inserter_placement_positions` separate**

These have different semantics that would be confusing to merge:

| Method | Target Input | Use Case |
|--------|--------------|----------|
| `get_connection_positions` | `target_entity_name: str` | Place NEW entity to connect |
| `get_inserter_placement_positions` | `target_entity: BaseEntity` | Place inserter between EXISTING entities |

Merging would require `Union[str, BaseEntity]` parameter, making API harder to understand.

**Consideration**: Keep separate. Different mental models, different use cases.

---

**D. Keep pole coverage methods separate**

- `get_pole_coverage_position`: "Can ONE pole cover all?" → `Optional[MapPosition]`
- `get_pole_coverage_plan`: "Minimum poles needed?" → `(GhostPlan, List[uncovered])`

Different return types, different optimization problems.

**Consideration**: Keep both. Merging would complicate return type.

---

#### Summary (If Implemented)

| Change | Methods Saved | Status |
|--------|---------------|--------|
| Merge `get_pole_line` → `get_placement_line` | 1 | Considering |
| Remove `validate_line`, `validate_grid` | 2 | Considering |
| Keep connection/inserter separate | 0 | Decided (keep) |
| Keep pole coverage methods | 0 | Decided (keep) |

**Potential reduction**: 9 → 6 methods on `placement_hints`, 4 → 2 on `validator`

**Open question**: Is this worth the migration effort? The current API is functional and documented. Simplification helps token count but requires updating examples and agent learning.

---

### 5. Top-Level Module API Review

Analysis of all action wrappers from the system prompt documentation perspective.

#### Current State

| Module | Public Methods | System Prompt Concern |
|--------|----------------|----------------------|
| `walking` | 4 | 1 internal method exposed |
| `crafting` | 4 | Clean |
| `inventory` | 4 | Clean |
| `research` | 4 | 1 redundant method |
| `reachable_view` | 5 | Consolidation planned (§3) |
| `remote_view` | 16+ | Many internal/debug methods |
| `ghost_builder` | 3 | 1 convenience wrapper |
| `placement_hints` | 9 | Consolidation planned (§4) |

#### Issues Identified

**A. `research.get_queue()` is redundant**

```python
# Current: two methods returning overlapping info
status = research.status()      # -> ResearchStatus (includes queue)
queue = research.get_queue()    # -> Dict (raw queue)
```

`ResearchStatus` already contains `queue_length`, `queue: List[QueuedTechnology]`, `current_research`. The `get_queue()` method returns the same data as raw dict.

**Consideration**: Remove `get_queue()` from documentation. Agents use `status()` only.

---

**B. `remote_view` exposes too many methods**

Current public surface:
- **Core query (5)**: `query`, `get_entities`, `get_entity`, `get_resources`, `get_ghosts`
- **Convenience (2)**: `count_entities`, `count_ghosts`
- **Spatial (4)**: `get_entity_at_tile`, `is_tile_occupied`, `get_entities_in_tile_area`, `get_entities_at_anchor_tile`
- **Lifecycle (3)**: `load`, `start`, `stop`
- **Debug (3)**: `flush`, `debug_info`, `rebuild`
- **Properties (2)**: `is_loaded`, `sync_state`

For system prompt, agent only needs:
- `query(sql)` - raw SQL, raw rows
- `get_entities(sql)` - entities from SQL
- `get_resources(sql)` - resources from SQL

Everything else is internal (lifecycle), debug utilities, or convenience that can be expressed via SQL patterns.

**Consideration**: Document only 3-4 core query methods. Teach spatial queries via SQL examples.

---

**C. `ghost_builder.build_ghost()` is a thin wrapper**

```python
async def build_ghost(self, ghost: BaseEntity) -> bool:
    result = await self.build_ghosts([ghost], count=1)
    return result["built_count"] == 1
```

Just `build_ghosts([ghost])` with bool return.

**Consideration**: Document only `build_ghosts()` and `build_plan()`.

---

**D. `walking.walk_to_entity()` is internal**

Entities have `await entity.walk_to()` which wraps this. Agent shouldn't call directly.

**Consideration**: Document only `walk_to(goal)`, `stop()`, `current_position`.

---

#### Proposed Documentation Surface

| Module | Documented | Hidden | Reduction |
|--------|------------|--------|-----------|
| `walking` | 3 | 1 | -1 |
| `crafting` | 4 | 0 | - |
| `inventory` | 4 | 0 | - |
| `research` | 3 | 1 | -1 |
| `reachable_view` | 2 | 3 | -3 |
| `remote_view` | 4 | 12+ | -12 |
| `ghost_builder` | 2 | 1 | -1 |
| `placement_hints` | 6 | 3 | -3 |

**Total documented methods**: ~28 (down from ~50+)

This is purely documentation scope - no code changes required. Internal methods remain available but aren't in the system prompt.

---

## Open Questions

1. **Factoriopedia vs Filesystem**: Which approach for on-demand docs? Or hybrid?
2. **Verification tool naming**: `check_progress()` vs `verify_task()` vs something else?
3. **Compression strategy**: Just lower threshold or smarter summarization?
4. **Caching**: Should we leverage Anthropic/OpenAI prompt caching explicitly?
5. **Filter parameters**: For `get_entities(ghost=False)`, should `ghost=False` mean "exclude ghosts" or "only real entities"? (Current: separate method avoids ambiguity)

---

## Notes

*Space for iteration notes as we work through this*

