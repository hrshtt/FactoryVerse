#!/usr/bin/env python3
"""Generate LLM documentation via pure Python introspection.

This script generates comprehensive documentation for FactoryVerse by
introspecting the actual Python code - no hardcoded metadata.

Usage:
    # From project root:
    uv run python scripts/generate_docs.py

    # Output: docs/for-llms/reference.md
"""

import sys
import argparse
import inspect
from pathlib import Path
from typing import Dict, List, Type, Optional
from datetime import datetime
from dataclasses import dataclass

# Add src to path for imports
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# =============================================================================
# IMPORTS - These are the sources of truth
# =============================================================================

from FactoryVerse.factory.entity.create_entity import ENTITY_CLASS_MAP
from FactoryVerse.factory.entity.base_entity import BaseEntity
from FactoryVerse.factory.entity.inspection import EntityInspection
from FactoryVerse.factory.entity.capabilities import (
    BurnerMixin,
    ElectricMixin,
    CrafterMixin,
    MinerMixin,
    InserterMixin,
    FluidMixin,
    BeltMixin,
    RotatableMixin,
    Rotatable180Mixin,
    SetRecipeMixin,
)
from FactoryVerse.factory.factorio_types import Direction
from FactoryVerse.runtime import AgentRuntime


# =============================================================================
# INTROSPECTION HELPERS
# =============================================================================

# All capability mixins to check
ALL_MIXINS: List[Type] = [
    BurnerMixin,
    ElectricMixin,
    CrafterMixin,
    SetRecipeMixin,
    MinerMixin,
    InserterMixin,
    FluidMixin,
    BeltMixin,
    RotatableMixin,
    Rotatable180Mixin,
]


@dataclass
class MixinMeta:
    """Metadata derived from introspecting a mixin class."""

    name: str
    slot: Optional[str]
    actions: List[str]
    description: str


def derive_mixin_meta(mixin_cls: Type) -> MixinMeta:
    """Derive metadata from a mixin class via introspection."""
    slot = None
    actions = []

    for name in dir(mixin_cls):
        # Find slot name from _get_*_state method
        if name.startswith("_get_") and name.endswith("_state"):
            slot = name[5:-6]  # _get_burner_state -> burner
        # Find public action methods (not properties, not dunder)
        elif not name.startswith("_"):
            attr = getattr(mixin_cls, name, None)
            if callable(attr) and not isinstance(
                getattr(mixin_cls, name, None), property
            ):
                actions.append(name)

    # Get first line of docstring as description
    doc = mixin_cls.__doc__ or ""
    description = doc.split("\n")[0].strip()

    return MixinMeta(
        name=mixin_cls.__name__.replace("Mixin", ""),
        slot=slot,
        actions=actions,
        description=description,
    )


def get_entity_capabilities(entity_cls: Type) -> List[MixinMeta]:
    """Get all capabilities for an entity class."""
    return [
        derive_mixin_meta(mixin)
        for mixin in ALL_MIXINS
        if issubclass(entity_cls, mixin)
    ]


def is_async_method(method) -> bool:
    """Check if a method is async (coroutine)."""
    return inspect.iscoroutinefunction(method)


def format_signature(method) -> str:
    """Get a clean signature string for a method."""
    try:
        sig = inspect.signature(method)
        # Clean up the signature for readability
        sig_str = str(sig)
        # Remove module paths from type annotations
        sig_str = sig_str.replace("FactoryVerse.factory.types.", "")
        sig_str = sig_str.replace("FactoryVerse.factory.factorio_types.", "")
        sig_str = sig_str.replace("ForwardRef('", "").replace("')", "")
        return sig_str
    except (ValueError, TypeError):
        return "()"


def get_pydantic_fields(model_cls: Type) -> Dict[str, str]:
    """Get field names and types from a Pydantic model."""
    fields = {}
    for name, field in model_cls.model_fields.items():
        ann = field.annotation
        # Simplify type representation
        type_str = str(ann)
        type_str = type_str.replace("typing.", "")
        type_str = type_str.replace("FactoryVerse.factory.entity.capabilities.", "")
        type_str = type_str.replace("FactoryVerse.factory.entity.implementations.", "")
        type_str = type_str.replace("<class '", "").replace("'>", "")
        fields[name] = type_str
    return fields


# =============================================================================
# DOCUMENT SECTIONS
# =============================================================================


def generate_header() -> str:
    return f"""# FactoryVerse LLM Reference

> Auto-generated via introspection on {datetime.now().strftime("%Y-%m-%d %H:%M")}

You are an embodied agent in Factorio. You have a physical presence, inventory, and can walk, craft, mine, and interact with entities.

---

"""


def generate_top_level_accessors() -> str:
    """Generate docs for all AgentRuntime accessors."""
    doc = "## Top-Level Accessors\n\n"
    doc += "These are available as global variables in your runtime.\n\n"

    # Exclude internal implementation details
    # - entity_ops: absorbed by entity methods
    # - placement: use PlaceableItem.place() / entity.pickup() instead
    # - mining: use resource.mine() instead (object-based)
    # - resources: merged into reachable (unified interface)
    # - rcon, agent_id: infrastructure
    EXCLUDED = {"entity_ops", "placement", "mining", "resources", "rcon", "agent_id"}

    # Get all public properties with **For Agents** docstrings
    accessors = []
    for name in sorted(dir(AgentRuntime)):
        if name.startswith("_") or name in EXCLUDED:
            continue
        attr = getattr(AgentRuntime, name, None)
        if isinstance(attr, property) and attr.fget:
            docstring = attr.fget.__doc__
            if docstring and "**For Agents**" in docstring:
                accessors.append((name, docstring))

    for name, docstring in accessors:
        # Parse docstring for usage examples
        lines = docstring.strip().split("\n")
        first_line = lines[0].strip()

        # Find bullet points (usage examples)
        examples = [line.strip() for line in lines if line.strip().startswith("- ")]

        doc += f"### `{name}`\n\n"
        doc += f"{first_line}\n\n"

        if examples:
            doc += "```python\n"
            for ex in examples:  # No limit - show all examples from docstring
                # Clean up the example
                ex = ex.lstrip("- ").strip()
                doc += f"{ex}\n"
            doc += "```\n\n"

    return doc


def generate_entity_access() -> str:
    """Generate docs for how to get entities and resources."""
    return """## Getting Entities and Resources

### Reachable (Unified Query Interface)

The `reachable` accessor provides a unified interface for querying both entities and resources within interaction range.

#### Entities

```python
furnace = reachable.get_entity("stone-furnace")
drills = reachable.get_entities("burner-mining-drill")
ghosts = reachable.get_ghosts()  # Ghost entities also have REACHABLE view
```

#### Resources

```python
coal = reachable.get_resource("coal")
iron_ore = reachable.get_resource("iron-ore")
all_resources = reachable.get_resources()
```

### Mining Resources

Resources are mined using the object-based `mine()` method:

```python
# Get a resource
coal = reachable.get_resource("coal")

# Mine it (async)
items = await coal.mine(max_count=25)

# Resource patches work the same way
iron_patch = reachable.get_resources("iron-ore")
items = await iron_patch.mine(max_count=25)  # Mines first tile in patch
```

### Remote Entities (Read-Only)

Query entities anywhere on the map via SQL. **Read-only - cannot mutate.**

```python
drills = remote_view.get_entities("SELECT * FROM map_entity WHERE entity_name = 'electric-mining-drill'")
ghosts = remote_view.get_ghosts("SELECT * FROM ghost")
count = remote_view.count_entities("stone-furnace")
```

### View Distinction

| View | Source | Actions | Use Case |
|------|--------|---------|----------|
| REACHABLE | `reachable.*` | All actions available | Interact with nearby entities/resources |
| REMOTE | `remote_view.*` | Read-only (inspect only) | Query map-wide, then walk to interact |

Ghosts also have this distinction - ghosts from `reachable.get_ghosts()` can be built, ghosts from `remote_view.get_ghosts()` cannot (walk to them first).

---

"""


def generate_item_flow() -> str:
    """Generate docs for item handling."""
    return """## Items and Placement

### Getting Items from Inventory

```python
# Get a placeable item (returns PlaceableItem or Item)
furnace_item = inventory.get_item("stone-furnace")

# Get item stacks for fueling/crafting
coal_stacks = inventory.create_item_stacks("coal", count=5)

# Check how many you have
count = inventory.check_total("iron-plate")
```

### Item Types

| Type | What It Is | Key Methods |
|------|------------|-------------|
| `Item` | Non-placeable item | `.stack_size` |
| `PlaceableItem` | Can be placed as entity | `.place(position, direction)`, `.place_ghost(...)` |
| `ItemStack` | Quantity of items | Used for `add_fuel()`, `add_ingredients()` |

### Placing Entities

```python
# From inventory item (primary pattern)
furnace_item = inventory.get_item("stone-furnace")
furnace = furnace_item.place(MapPosition(10, 10), Direction.NORTH)

# Place as ghost (for planning)
furnace_item.place_ghost(MapPosition(10, 10), Direction.NORTH)
```

---

"""


def generate_action_gating() -> str:
    """Generate action gating docs from BaseEntity class attributes."""
    reachable_only = sorted(BaseEntity._REACHABLE_ONLY)
    ghost_blocked = sorted(BaseEntity._GHOST_BLOCKED)

    doc = """## Action Availability

Actions are filtered based on **view type** and **ghost status**.

### View-Based Filtering

Remote entities cannot be mutated - you must walk within range first.

| Action | Reachable | Remote |
|--------|-----------|--------|
"""

    # Build the table
    all_actions = set(reachable_only) | {"inspect", "build", "remove"}
    for action in sorted(all_actions):
        reachable = "✓"
        remote = "✗" if action in reachable_only else "✓"
        doc += f"| `{action}()` | {reachable} | {remote} |\n"

    doc += """
### Ghost-Based Filtering

Ghosts are placeholders - they have no inventory or internal state.

| Action | Real Entity | Ghost |
|--------|-------------|-------|
"""

    ghost_only = {"build", "remove"}
    for action in sorted(all_actions):
        real = "✗" if action in ghost_only else "✓"
        ghost = "✗" if action in ghost_blocked else "✓"
        doc += f"| `{action}()` | {real} | {ghost} |\n"

    doc += "\n---\n\n"
    return doc


def generate_entity_reference() -> str:
    """Generate entity reference from ENTITY_CLASS_MAP."""
    doc = "## Entity Reference\n\n"

    # Group by capability pattern for compactness
    capability_groups: Dict[str, List[tuple]] = {}

    for factorio_name, entity_cls in sorted(ENTITY_CLASS_MAP.items()):
        caps = get_entity_capabilities(entity_cls)
        cap_key = ", ".join(sorted(c.name for c in caps)) or "Basic"
        if cap_key not in capability_groups:
            capability_groups[cap_key] = []
        capability_groups[cap_key].append((factorio_name, entity_cls, caps))

    for cap_pattern, entities in sorted(capability_groups.items()):
        doc += f"### {cap_pattern}\n\n"

        # Show capabilities once for the group
        if entities:
            _, _, caps = entities[0]
            if caps:
                doc += "**Capabilities:**\n"
                for cap in caps:
                    actions_str = (
                        f" → `{', '.join(cap.actions)}`" if cap.actions else ""
                    )
                    doc += f"- {cap.name}{actions_str}\n"
                doc += "\n"

        # List entities in this group
        doc += "**Entities:** "
        doc += ", ".join(f"`{name}`" for name, _, _ in entities)
        doc += "\n\n"

    return doc


def generate_inspection_reference() -> str:
    """Generate inspection reference from EntityInspection model."""
    doc = "## Inspection\n\n"
    doc += "Call `entity.inspect()` to get current state.\n\n"

    fields = get_pydantic_fields(EntityInspection)

    # Base fields
    doc += "### Base Fields (always present)\n\n"
    doc += "| Field | Type |\n|-------|------|\n"
    base_fields = ["name", "position", "direction", "status", "is_ghost"]
    for name in base_fields:
        if name in fields:
            doc += f"| `{name}` | `{fields[name]}` |\n"

    # Capability slots
    doc += "\n### Capability Slots (when applicable)\n\n"
    doc += "| Slot | State Type | When Present |\n|------|------------|-------------|\n"

    # Build slot -> mixin name mapping dynamically from ALL_MIXINS
    slot_mixin_map = {}
    for mixin in ALL_MIXINS:
        meta = derive_mixin_meta(mixin)
        if meta.slot:
            slot_mixin_map[meta.slot] = mixin.__name__
    # Add category-based slots (not mixins, but entity classes)
    slot_mixin_map.update(
        {
            "container": "Container",
            "lab": "Lab",
            "accumulator": "Accumulator",
            "electric_pole": "ElectricPole",
            "generator": "Generator",
        }
    )

    for name, type_str in fields.items():
        if name in base_fields:
            continue
        mixin = slot_mixin_map.get(name, "")
        if "State" in type_str:
            # Extract just the state class name
            state_name = (
                type_str.split(".")[-1].replace("]", "").replace("Optional[", "")
            )
            doc += f"| `{name}` | `{state_name}` | {mixin} |\n"

    doc += "\n---\n\n"
    return doc


def generate_direction_reference() -> str:
    """Generate direction enum reference."""
    cardinals = [Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST]
    all_names = [d.name for d in Direction]

    doc = "## Direction\n\n"
    doc += "Cardinal directions (most common):\n"
    doc += "```python\n"
    for d in cardinals:
        doc += f"Direction.{d.name}\n"
    doc += "```\n\n"
    doc += f"All 16 directions: `{', '.join(all_names)}`\n\n"
    doc += "---\n\n"
    return doc


def generate_ghost_flow() -> str:
    """Generate placement planning and ghost documentation."""
    return """## Placement Planning

Entity placement follows a three-tier flow for safety and validation:

### 1. Plan (Dry Run)

Use `placement_hints` to generate validated plans before committing:

```python
# Plan a line of belts
plan = placement_hints.get_placement_line(
    "transport-belt",
    start=MapPosition(0, 0),
    end=MapPosition(10, 0)
)

# Check if plan is valid
if plan.valid:
    print(f"Plan has {len(plan.positions)} positions")
else:
    print("Invalid placement")

# Find connection points for pipes
positions = placement_hints.get_connection_positions(
    source_entity=refinery,  # Existing entity
    target_entity_name="pipe",
    connection_type=ConnectionType.FLUID_PIPE
)
```

### 2. Place Ghosts

Place ghosts for visual planning or incremental building:

```python
# From inventory item
belt_item = inventory.get_item("transport-belt")
belt_item.place_ghost(MapPosition(0, 0), Direction.EAST)

# Build plan as ghosts then build
await ghost_builder.build_plan(plan)
```

### 3. Build to Real Entities

Convert ghosts to real entities when ready:

```python
# Build a single ghost
ghost = reachable.get_ghosts()[0]
ghost.build()  # Converts to real entity

# Build multiple ghosts
await ghost_builder.build_ghosts(ghosts, count=10)
```

### Ghost Queries

```python
# Nearby ghosts (REACHABLE - can build)
ghosts = reachable.get_ghosts()
ghosts = reachable.get_ghosts("stone-furnace")

# Map-wide ghosts (REMOTE - walk to them first)
ghosts = remote_view.get_ghosts("SELECT * FROM ghost")
```

### GhostPlan Structure

```python
plan.positions   # List[MapPosition] - validated positions
plan.directions  # List[Direction] - directions for each position
plan.valid       # bool - True if all positions are valid
plan.validate(placement_hints.validator)  # Re-validate after map changes
```

---

"""


def generate_examples() -> str:
    """Generate common pattern examples."""
    return """## Common Patterns

### Manual Mining

```python
# Get a resource
coal = reachable.get_resource("coal")

# Mine it (async, max 25 items per call)
items = await coal.mine(max_count=25)

# Or mine from a patch
iron_patch = reachable.get_resources("iron-ore")
items = await iron_patch.mine(max_count=25)
```

### Automated Mining Setup

```python
# Find a resource
coal = reachable.get_resource("coal")

# Place a drill on the resource
drill_item = inventory.get_item("burner-mining-drill")
drill = drill_item.place(coal.position, Direction.SOUTH)

# Fuel it
fuel = inventory.create_item_stacks("wood", 5)
drill.add_fuel(fuel)

# Check status
state = drill.inspect()
print(state.miner.mining_target)
print(state.burner.fuel_inventory)
```

### Smelting Chain

```python
# Place furnace next to drill
furnace_pos = drill.position.offset_by_entity(Direction.SOUTH)
furnace = inventory.get_item("stone-furnace").place(furnace_pos)

# Fuel and add ore
furnace.add_fuel(inventory.create_item_stacks("coal", 10))
furnace.add_ingredients(inventory.create_item_stacks("iron-ore", 50))

# Later, collect output
plates = furnace.take_products()
```

### Walking and Interacting

```python
# Find a remote entity
drills = remote_view.get_entities("SELECT * FROM map_entity WHERE entity_name = 'burner-mining-drill' LIMIT 1")

# Walk to it
await walking.walk_to(drills[0].position)

# Now get reachable version for full access
drill = reachable.get_entity("burner-mining-drill", drills[0].position)
drill.add_fuel(fuel)
```

"""


def generate_document() -> str:
    """Generate the complete documentation."""
    sections = [
        generate_header(),
        generate_top_level_accessors(),
        generate_entity_access(),
        generate_item_flow(),
        generate_action_gating(),
        generate_ghost_flow(),
        generate_entity_reference(),
        generate_inspection_reference(),
        generate_direction_reference(),
        generate_examples(),
    ]
    return "\n".join(sections)


# =============================================================================
# MAIN
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Generate LLM documentation via introspection"
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=str(PROJECT_ROOT / "docs" / "for-llms" / "reference.md"),
        help="Output file path",
    )
    args = parser.parse_args()

    doc = generate_document()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(doc)

    print(f"✅ Documentation written to {output_path}")
    print(f"   Size: {len(doc):,} characters")
    print(f"   Lines: {len(doc.splitlines()):,}")


if __name__ == "__main__":
    main()
