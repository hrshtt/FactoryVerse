This is the design document for a new **Placement Cues** module. This module serves as the **placemenr reasoning engine** for FactoryVerse, decoupling "where things *can* go" (Geometry/Validity) from "making them go there" (Execution).

# Design Document: Placement Cues Module (`placement_hints`)

## 1. Overview

The `placement_hints` module provides pure, context-aware spatial reasoning for entity placement. It mirrors the visual feedback human players receive in Factorio (green/red tile highlights, rotation indicators, drag-placement lines) but exposes this as structured data for the LLM Agent.

**Core Philosophy:** "Query the possibility space, validate it, then commit to the plan."

* **Input:** Entity types, reference positions, and geometric intent (points, lines).
* **Output:** Structured plans (`GhostPlan`) with calculated positions, rotations, and labels.
* **Validation:** Plans are validated using `PlacementValidator.can_place_entity()` before committing to ghosts.
* **Side Effects:** **None.** This module never mutates game state (validation only).

**Core Difference:**

* **Humans**: High-fidelity cursor movement with real-time visual feedback. The entity sprite is dragged across the map, showing the full footprint (all tiles the entity would occupy) with green/red highlights indicating validity. This is like fitting a puzzle piece—you see the entire shape and how it fits.

* **Agents**: Discrete, precise position references (entity center coordinates) with directions, but **without** the full footprint grid. Agents receive the final placement position (the entity's center) rather than all individual tiles that make up the entity's collision box. Validation happens at the entity center, but the agent doesn't see the multi-tile footprint breakdown.

**Key Distinction**: 
- Humans see the **full puzzle piece** (all tiles) as they drag it around
- Agents get the **puzzle piece center** (single position) and must reason about placement from that reference point 


---

## 2. Architecture & Integration

This module sits in the **Reasoning Layer**, separate from the **Action Layer** (`GhostBuilder`, `Inventory`, `PlacableItem`) and the **State Layer** (`BaseEntity`, `DuckDB Snapshot`).

### Responsibilities

1. **Geometry Calculation:** Calculating lines, grids, and rotation logic (e.g., dragging belts vs. dragging walls).
2. **Connection Solving:** determining valid positions to connect two entities (e.g., "Where can I put a pipe to connect to this refinery?").
3. **Plan Generation:** Structuring these calculations into a `GhostPlan` that can be executed by the `GhostBuilder`.
4. **Validation:** Using `PlacementValidator` to verify all positions in a plan are valid before committing to ghosts.

---

## 3. Data Structures

These structures define the "contract" between the Reasoning layer and the Execution layer.

```python
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Dict, Any, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from FactoryVerse.agent.actions.placement_validator import PlacementValidator

from FactoryVerse.factory.types import MapPosition, Direction

class ConnectionType(Enum):
    """Connection types for solving entity placement puzzles.
    
    Note: This is a design concept for future implementation.
    Used to determine valid connection positions between entities.
    """
    ITEM_DROP = "item_drop"      # Mining drill -> Chest/Belt
    FLUID_PIPE = "fluid_pipe"    # Pipe -> Machine/Pipe
    INSERTER_REACH = "inserter"  # Inserter -> Source/Target
    BELT_FLOW = "belt_flow"      # Belt -> Belt
    ELECTRIC_WIRE = "wire"       # Pole -> Pole

@dataclass
class GhostPlan:
    """A complete plan ready for commitment.
    
    Plans are validated using PlacementValidator.can_place_entity() before
    being committed as ghosts. This ensures all positions are valid before
    any state mutation occurs.
    
    Plans returned from PlacementHints methods are pre-validated (valid=True).
    Agents can re-validate plans if they modify the map before committing.
    """
    entity_name: str  # Entity type for all placements in this plan
    positions: List[Tuple[MapPosition, Optional[Direction]]]  # List of (position, direction) tuples
    label: str  # The label to be applied to all ghosts (e.g., "belt_line:123")
    description: str  # Human/LLM readable description of the plan
    valid: bool  # Whether all positions have been validated (True if pre-validated by PlacementHints)
    
    def validate(self, validator: "PlacementValidator") -> bool:
        """Re-validate all positions in the plan.
        
        Useful if the agent has modified the map (placed other entities, mined resources)
        after receiving the plan. Updates self.valid and returns the result.
        
        Args:
            validator: PlacementValidator instance to use for validation
                (from FactoryVerse.agent.actions.placement_validator)
            
        Returns:
            True if all positions are valid, False otherwise
        """
        self.valid = all(
            validator.validate_placement(self.entity_name, pos, dir)
            for pos, dir in self.positions
        )
        return self.valid

```

---

## 3.1. Tiered Placement System

FactoryVerse uses a **three-tier placement system** that progressively commits resources:

### Tier 1: Plan (Validated, Not Committed)
- **State**: Pure data structure (`GhostPlan`) with `valid=True` (pre-validated by `PlacementHints`)
- **Validation**: Uses `PlacementValidator.can_place_entity()` to verify all positions are valid
- **Re-validation**: Agent can call `plan.validate(validator)` if map changes before committing
- **Resources**: No resources required
- **Map State**: No changes to game world
- **Purpose**: Reasoning about "where things *can* go" before committing

### Tier 2: Ghost (Validated + Committed to Map)
- **State**: Ghost entities placed on map (visible, queryable via DuckDB)
- **Validation**: Already validated in Tier 1 (plan was checked)
- **Resources**: No physical items required (ghosts are placeholders)
- **Map State**: Ghost entities exist in game world, visible to agent
- **Purpose**: Committed plan that agent can work towards building

### Tier 3: Built Entity (Committed Positions + Resources)
- **State**: Real entities on map (functional, can be used)
- **Validation**: Ghosts were validated, now agent has resources
- **Resources**: Agent must have physical items in inventory
- **Map State**: Real entities replace ghosts
- **Purpose**: Fully functional factory components

**Workflow**:
```
Plan (validated) → Ghost (committed ghost positions to map) → Built Entity (entities crafted + committed real entities to map)
     ↑                    ↑                        ↑
  can_place_entity    place_ghost()         build_ghosts()
```

---

## 4. API Definition

### 4.1. Geometric Planning (`get_placement_line`)

Calculates positions for "drag-and-drop" style placement. This handles the complexity of different entity behaviors (walls connect, belts rotate).

```python
class PlacementHints:
    def get_placement_line(
        self,
        entity_name: str,
        start: MapPosition,
        end: MapPosition,
        width: int = 1
    ) -> GhostPlan:
        """
        Calculates a line of entities from start to end.
        
        Logic:
        1. Calculates vector and validates primary axis (Horizontal/Vertical).
        2. Determines consistent cardinal direction for directional entities (Belts).
        3. Generates a unique label for the group.
        
        Returns:
            GhostPlan containing the ordered list of (position, direction) tuples and the group label.
            The plan is pre-validated (valid=True) before being returned.
        """

```

**Behavioral Nuances:**

* **Belts:** All tiles in the line share the same direction (based on drag vector).
* **Walls:** No direction required (auto-connect).
* **Solar Panels:** Grid alignment logic.

### 4.2. Connection Solving (`get_connection_positions`)

Solves the "puzzle" of connecting machines. This is critical for fluids and inserters.

```python
    def get_connection_positions(
        self,
        source_entity: "BaseEntity", # The existing entity
        target_entity_name: str,     # What we want to place
        connection_type: ConnectionType
    ) -> List[Tuple[MapPosition, Optional[Direction]]]:
        """
        Returns all valid positions where 'target_entity' can connect to 'source_entity'.
        
        Example:
            source = OilRefinery at (10,10)
            target = "pipe"
            type = FLUID_PIPE
            
            Returns: [
                (MapPosition(9, 10), Direction.EAST),   # Left input
                (MapPosition(12, 10), Direction.WEST), # Right input
                ...
            ]
            
        Note: All returned positions are pre-validated using PlacementValidator.
        """

```

### 4.3. Validation (`PlacementValidator`)

A precise check for placement validity using Factorio's native `can_place_entity` API. The `PlacementValidator` class provides efficient batch validation with compressed coordinate representation to avoid stalling the simulation.

**Role in Tiered Placement System:**
- **Tier 1 (Plan)**: Validates all positions in a `GhostPlan` before committing to ghosts
- **Tier 2 (Ghost)**: Ghosts are already validated (plan was checked)
- **Tier 3 (Built)**: No additional validation needed (ghosts were valid, resources are available)

```python
class PlacementValidator:
    def __init__(self, rcon_client: RCONClient, batch_size: int = 250):
        """Initialize validator with RCON client and batch size."""
    
    def validate_placement(
        self,
        entity_name: str,
        position: MapPosition,
        direction: Optional[Direction] = None,
        ghost: bool = False
    ) -> bool:
        """
        Checks if an entity can be placed at a position.
        Uses Factorio's surface.can_place_entity() with correct build_check_type.
        
        Args:
            entity_name: Entity prototype name
            position: Position to check
            direction: Optional direction (for directional entities)
            ghost: If True, uses manual_ghost build_check_type, else manual
            
        Returns:
            True if entity can be placed, False otherwise
        """
    
    def validate_batch(
        self,
        entity_name: str,
        positions: List[MapPosition],
        direction: Optional[Direction] = None,
        ghost: bool = False
    ) -> List[bool]:
        """
        Validate multiple positions efficiently using compressed coordinate representation.
        Automatically batches large requests to avoid stalling the simulation.
        
        Returns:
            List of booleans matching input positions order
        """
    
    def validate_line(
        self,
        entity_name: str,
        start: MapPosition,
        end: MapPosition,
        direction: Optional[Direction] = None,
        ghost: bool = False
    ) -> List[Tuple[MapPosition, bool]]:
        """
        Validate positions along a line using compressed loop generation.
        Generates Lua code with for-loops instead of embedding coordinates.
        
        Returns:
            List of (position, can_place) tuples
        """
    
    def validate_grid(
        self,
        entity_name: str,
        top_left: MapPosition,
        bottom_right: MapPosition,
        direction: Optional[Direction] = None,
        ghost: bool = False
    ) -> Dict[MapPosition, bool]:
        """
        Validate positions in a rectangular grid using nested loops.
        Generates compressed Lua code: for x = x1, x2 do for y = y1, y2 do ... end end
        
        Returns:
            Dictionary mapping position -> can_place boolean
        """

```

---

## 5. Implementation Strategy

### A. Placement Validation Infrastructure (`PlacementValidator`)

The validation layer uses **direct RCON execution** with **compressed coordinate representation** to efficiently query Factorio's `can_place_entity` API without stalling the simulation.

#### Architecture

**No Remote Interface Required**: Since we're calling Factorio's built-in `game.surfaces[1].can_place_entity()` directly, we don't need a remote interface wrapper. Python generates Lua templates and executes them via RCON.

**Compressed Coordinate Representation**:
- **Lines**: Generate Lua `for` loops instead of embedding coordinates
  ```lua
  -- Horizontal line: for x = 10, 20 do ... end
  -- Vertical line: for y = 10, 20 do ... end
  -- Diagonal: Uses Bresenham-style stepping
  ```
- **Grids**: Nested loops for rectangular areas
  ```lua
  for x = x1, x2 do
      for y = y1, y2 do
          -- Check position {x=x, y=y}
      end
  end
  ```
- **Points**: Only used for scattered/non-contiguous positions (explicit list)

**Batch Size Management**:
- Default batch size: ~200-300 tile checks per RCON call (configurable)
- Large requests automatically split into multiple batches
- Balance: Minimize network overhead while avoiding simulation stalls

**Lua Template Pattern**:
```lua
local surface = game.surfaces[1]
local entity_name = "transport-belt"
local build_check_type = defines.build_check_type.manual_ghost  -- or manual
local direction = 4  -- or nil
local force = "player"

-- Compressed loop (for lines/grids)
local results = {}
for x = 10, 20 do
    for y = 30, 40 do
        local pos = {x = x, y = y}
        local params = {
            name = entity_name,
            position = pos,
            direction = direction,
            force = force,
            build_check_type = build_check_type
        }
        results[#results+1] = surface.can_place_entity(params)
    end
end

return results
```

**Error Handling**: All Lua execution wrapped in `xpcall` with traceback capture (following existing RCON patterns).

### B. The Geometry Solver (Internal Helper)

This component handles the math of rasterizing lines and grids for coordinate generation.

* **Algorithm:** 
  - **Horizontal/Vertical lines**: Simple range loops
  - **Diagonal lines**: Modified Bresenham's line algorithm or vector stepping
  - **Grids**: Rectangular nested loops
* **Direction Inference:**
  - `dx > dy`: Horizontal (East/West) - loop over x
  - `dy > dx`: Vertical (South/North) - loop over y
  - `dx == dy`: Diagonal - use stepping algorithm

### C. The Label Generator

To support the `GhostBuilder`'s optimized "batch build" mode, `PlacementHints` generates deterministic labels.

* **Format:** `plan:{entity}:{timestamp}:{random_short_hash}`
* **Usage:** The Agent commits ghosts with this label. The Builder queries `SELECT * FROM ghosts WHERE label = '...'` to execute the line as a single unit of work.

### D. Prototype Lookup

The module needs access to `get_entity_prototypes()` to know:

1. **Dimensions:** Width/Height (to calculate offsets).
2. **FluidBox Positions:** Defined in prototypes (for pipe connections).
3. **Drop Positions:** Where mining drills output items.

---

## 6. Usage Patterns (Agent Workflow)

### Scenario: Laying a Belt Line

The Agent wants to move items from a mine to a furnace.

```python
# TIER 1: PLAN (Validated, Not Committed)
# Agent decides start/end points
start, end = MapPosition(10, 10), MapPosition(20, 10)

# Agent asks cues for the plan
plan = placement_hints.get_placement_line(
    "transport-belt", start, end
)
# Plan contains:
# - entity_name: "transport-belt"
# - positions: [(MapPosition(10,10), Direction.EAST), (MapPosition(11,10), Direction.EAST), ...]
# - label: "plan:belt:17823a"
# - valid: True  # Pre-validated by PlacementHints

# Optional: Re-validate if agent modified the map (e.g., placed other entities)
# If the agent hasn't changed the map, plan.valid is already True
validator = PlacementValidator(rcon_client)
if not plan.valid or agent_modified_map:
    if not plan.validate(validator):
        raise ValueError("Plan contains invalid positions after map changes")

# TIER 2: GHOST (Validated + Committed to Map)
# Agent places ghosts using the validated plan data
item = inventory.get_item(plan.entity_name)
for position, direction in plan.positions:
    item.place_ghost(
        position, 
        direction, 
        label=plan.label # <--- Critical: Groups them in DB
    )
# Ghosts are now on the map, visible and queryable

# TIER 3: BUILD GHOSTS (Committed Positions + Resources)
# Agent queries ghosts by label and builds them (requires items in inventory)
ghosts = remote_view.get_ghosts(f"SELECT * FROM ghost WHERE label = '{plan.label}'")
await ghost_builder.build_ghosts(ghosts)  # Walks to each, places real entities

```

### Scenario: Connecting a Pipe

The Agent needs to connect a pipe to a boiler.

```python
# 1. QUERY
# "Where can I put a pipe?"
options = placement_hints.get_connection_positions(
    source_entity=boiler,
    target_entity_name="pipe",
    connection_type=ConnectionType.FLUID_PIPE
)

# 2. SELECT & COMMIT
# Agent picks the first valid option and places a ghost
best_position, best_direction = options[0]
pipe_item.place_ghost(best_position, best_direction)

```

## 7. Implementation Location

The `PlacementValidator` & `PlacementHints` classes should be located at:
- `src/FactoryVerse/agent/actions/placement_hints.py`

This module:
- Takes an `RCONClient` in its constructor (not agent-specific)
- Provides pure validation functions (no state mutation)
- Can be used by `PlacementHints` for validation checks
- Can be used directly by agents for quick placement checks

## 8. Future Extensibility

* **Blueprints:** This module can eventually ingest Blueprint strings to return `GhostPlan` relative to a cursor position.
* **Obstacle Avoidance:** `get_placement_line` could optionally take an `avoid_obstacles=True` flag to generate A* paths around rocks/trees instead of straight lines.
* **Batch Optimization:** Further optimize batch sizes based on profiling (network latency vs. simulation stall time).
* **Parallel Validation:** For very large grids, could split into parallel RCON calls (requires multiple RCON connections).