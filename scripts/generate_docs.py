#!/usr/bin/env python3
"""Generate LLM documentation via pure Python introspection.

This script generates comprehensive documentation for FactoryVerse by
introspecting the actual Python code - extracting method signatures,
return types, dataclass fields, and enum values dynamically.

Usage:
    # From project root:
    uv run python scripts/generate_docs.py

    # Output: docs/for-llms/api_reference.md
"""

import sys
import argparse
import inspect
import typing
from pathlib import Path
from typing import (
    Dict,
    List,
    Type,
    Optional,
    Any,
    Tuple,
    get_type_hints,
    Union,
    Callable,
)
from datetime import datetime
from dataclasses import dataclass, fields as dataclass_fields, is_dataclass
from enum import Enum

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
from FactoryVerse.factory.types import MapPosition
from FactoryVerse.runtime import AgentRuntime

# Action classes
from FactoryVerse.agent.embodied_actions.walking import (
    MovementAction,
    WalkingStarted,
    WalkingCompleted,
    WalkingStopped,
    WalkingError,
    WalkingUnreachableError,
    WalkingEntityNotFoundError,
    WalkingNoStandableTilesError,
)
from FactoryVerse.agent.embodied_actions.crafting import (
    CraftingAction,
    CraftingStarted,
    CraftingCompleted,
)
from FactoryVerse.agent.embodied_actions.research import (
    ResearchAction,
    ResearchStatus,
    QueuedTechnology,
    ResearchQueueItem,
)
from FactoryVerse.agent.embodied_actions.inventory import AgentInventory
from FactoryVerse.agent.reachable_view import ReachableView
from FactoryVerse.agent.ghost_builder import GhostBuilderAction
from FactoryVerse.agent.placement_hints import (
    PlacementHints,
    PlacementValidator,
    GhostPlan,
    ConnectionPosition,
    ConnectionType,
    ITEM_DROP_ENTITIES,
    FLUID_PIPE_ENTITIES,
    RESOURCE_PLACEMENT_ENTITIES,
    WATER_PLACEMENT_ENTITIES,
    INSERTER_ENTITIES,
    ELECTRIC_POLE_ENTITIES,
    EntityValidationError,
)
from FactoryVerse.agent.remote_view import RemoteView
from FactoryVerse.factory.item.base import Item, PlaceableItem, ItemStack
from FactoryVerse.factory.resource.base import ResourceOrePatch, BaseResource


# =============================================================================
# INTROSPECTION HELPERS
# =============================================================================


def clean_type_str(type_str: str) -> str:
    """Clean up type string for readability."""
    replacements = [
        ("FactoryVerse.factory.types.", ""),
        ("FactoryVerse.factory.factorio_types.", ""),
        ("FactoryVerse.factory.entity.base_entity.", ""),
        ("FactoryVerse.factory.item.base.", ""),
        ("FactoryVerse.agent.placement_hints.", ""),
        ("FactoryVerse.agent.embodied_actions.research.", ""),
        ("FactoryVerse.agent.remote_view.", ""),
        ("typing.", ""),
        ("ForwardRef('", ""),
        ("')", ""),
        ("<class '", ""),
        ("'>", ""),
    ]
    for old, new in replacements:
        type_str = type_str.replace(old, new)
    return type_str


def get_return_type(method) -> Optional[str]:
    """Extract return type annotation from a method."""
    try:
        hints = get_type_hints(method)
        if "return" in hints:
            return_type = hints["return"]
            type_str = str(return_type)
            return clean_type_str(type_str)
    except Exception:
        pass

    # Fallback to signature
    try:
        sig = inspect.signature(method)
        if sig.return_annotation != inspect.Parameter.empty:
            return clean_type_str(str(sig.return_annotation))
    except Exception:
        pass

    return None


def format_signature(method) -> str:
    """Get a clean signature string for a method (parameters only, no return type)."""
    try:
        sig = inspect.signature(method)
        # Build signature without return annotation
        params = []
        for name, param in sig.parameters.items():
            if name == "self":
                continue
            param_str = name
            if param.annotation != inspect.Parameter.empty:
                ann_str = clean_type_str(str(param.annotation))
                param_str = f"{name}: {ann_str}"
            if param.default != inspect.Parameter.empty:
                default = param.default
                if isinstance(default, str):
                    param_str += f" = '{default}'"
                elif isinstance(default, Enum):
                    param_str += f" = {default.name}"
                else:
                    param_str += f" = {default}"
            params.append(param_str)
        return f"({', '.join(params)})"
    except (ValueError, TypeError):
        return "()"


def is_async_method(method) -> bool:
    """Check if a method is async (coroutine)."""
    return inspect.iscoroutinefunction(method)


def is_public_method(name: str, obj: Any) -> bool:
    """Check if an attribute is a public method."""
    if name.startswith("_"):
        return False
    if isinstance(obj, property):
        return False
    return callable(obj)


def get_first_docstring_line(obj: Any) -> str:
    """Get first line of docstring."""
    doc = obj.__doc__ or ""
    lines = doc.strip().split("\n")
    return lines[0].strip() if lines else ""


@dataclass
class MethodInfo:
    """Information about a method extracted via introspection."""

    name: str
    signature: str
    return_type: Optional[str]
    is_async: bool
    description: str
    is_property: bool = False


def introspect_class_methods(
    cls: Type, include_inherited: bool = False
) -> List[MethodInfo]:
    """Extract all public methods from a class with their signatures."""
    methods = []

    for name in dir(cls):
        if name.startswith("_"):
            continue

        # Check if method is directly on this class (not inherited)
        if not include_inherited and name not in cls.__dict__:
            continue

        attr = getattr(cls, name, None)
        if attr is None:
            continue

        # Handle properties
        if isinstance(getattr(cls, name, None), property):
            prop = getattr(cls, name)
            fget = prop.fget
            if fget:
                return_type = get_return_type(fget)
                methods.append(
                    MethodInfo(
                        name=name,
                        signature="",
                        return_type=return_type,
                        is_async=False,
                        description=get_first_docstring_line(fget),
                        is_property=True,
                    )
                )
            continue

        # Handle regular methods
        if callable(attr):
            methods.append(
                MethodInfo(
                    name=name,
                    signature=format_signature(attr),
                    return_type=get_return_type(attr),
                    is_async=is_async_method(attr),
                    description=get_first_docstring_line(attr),
                )
            )

    return methods


def get_dataclass_field_info(cls: Type) -> Dict[str, str]:
    """Extract field names and types from a dataclass."""
    if not is_dataclass(cls):
        return {}

    fields = {}
    for field in dataclass_fields(cls):
        type_str = str(field.type)
        fields[field.name] = clean_type_str(type_str)
    return fields


def get_enum_values(enum_cls: Type[Enum]) -> List[str]:
    """Extract enum member names."""
    return [member.name for member in enum_cls]


# =============================================================================
# MIXIN INTROSPECTION (kept from original)
# =============================================================================

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
        if name.startswith("_get_") and name.endswith("_state"):
            slot = name[5:-6]
        elif not name.startswith("_"):
            attr = getattr(mixin_cls, name, None)
            if callable(attr) and not isinstance(
                getattr(mixin_cls, name, None), property
            ):
                actions.append(name)

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


def get_pydantic_fields(model_cls: Type) -> Dict[str, str]:
    """Get field names and types from a Pydantic model."""
    fields = {}
    for name, field in model_cls.model_fields.items():
        ann = field.annotation
        type_str = str(ann)
        fields[name] = clean_type_str(type_str)
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


def format_method_doc(method: MethodInfo, accessor_name: str) -> str:
    """Format a single method for documentation."""
    prefix = "await " if method.is_async else ""

    if method.is_property:
        call = f"{accessor_name}.{method.name}"
    else:
        call = f"{accessor_name}.{method.name}{method.signature}"

    return_str = f" -> {method.return_type}" if method.return_type else ""

    return f"- `{prefix}{call}{return_str}` - {method.description}"


def generate_action_class_docs(
    cls: Type,
    accessor_name: str,
    title: str,
    description: str,
) -> str:
    """Generate documentation for an action class via introspection."""
    methods = introspect_class_methods(cls, include_inherited=False)

    doc = f"### `{accessor_name}`\n\n"
    doc += f"{description}\n\n"

    if methods:
        doc += "```python\n"
        for method in methods:
            prefix = "await " if method.is_async else ""
            if method.is_property:
                call = f"{accessor_name}.{method.name}"
            else:
                call = f"{accessor_name}.{method.name}{method.signature}"
            ret = f" -> {method.return_type}" if method.return_type else ""
            doc += f"{prefix}{call}{ret}\n"
        doc += "```\n\n"

    return doc


def generate_top_level_accessors() -> str:
    """Generate docs for all AgentRuntime accessors via introspection."""
    doc = "## Top-Level Accessors\n\n"
    doc += "These are available as global variables in your runtime.\n\n"

    # Define accessor -> action class mapping
    accessor_map = {
        "walking": (MovementAction, "Movement actions."),
        "crafting": (CraftingAction, "Crafting actions."),
        "research": (ResearchAction, "Research and technology management."),
        "inventory": (AgentInventory, "Inventory queries and operations."),
        "reachable_view": (ReachableView, "Unified reachable entity and resource queries."),
        "remote_view": (RemoteView, "Map-wide entity queries via DuckDB."),
        "ghost_builder": (GhostBuilderAction, "Ghost building orchestration."),
        "placement_hints": (PlacementHints, "Spatial reasoning for entity placement."),
    }

    for accessor_name, (cls, description) in accessor_map.items():
        doc += generate_action_class_docs(
            cls, accessor_name, accessor_name, description
        )

    return doc


def generate_core_types() -> str:
    """Generate documentation for core types via introspection."""
    doc = "## Core Types\n\n"

    # MapPosition
    doc += "### MapPosition\n\n"
    doc += "Coordinates of a tile on the map.\n\n"
    doc += "```python\n"
    doc += "MapPosition(x: float, y: float)\n"
    doc += "```\n\n"

    methods = introspect_class_methods(MapPosition, include_inherited=False)
    if methods:
        doc += "**Methods:**\n"
        for m in methods:
            if m.is_property:
                doc += (
                    f"- `.{m.name}` -> `{m.return_type or 'Any'}` - {m.description}\n"
                )
            else:
                ret = f" -> {m.return_type}" if m.return_type else ""
                doc += f"- `.{m.name}{m.signature}{ret}` - {m.description}\n"
        doc += "\n"

    # Direction enum
    doc += "### Direction\n\n"
    doc += "Cardinal directions for entity placement and rotation.\n\n"
    cardinals = [Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST]
    doc += "```python\n"
    for d in cardinals:
        doc += f"Direction.{d.name}\n"
    doc += "```\n\n"
    all_names = get_enum_values(Direction)
    doc += f"All 16 directions: `{', '.join(all_names)}`\n\n"

    # ConnectionType enum
    doc += "### ConnectionType\n\n"
    doc += "Connection types for placement planning.\n\n"
    doc += "```python\n"
    for ct in ConnectionType:
        doc += f"ConnectionType.{ct.name}  # {ct.value}\n"
    doc += "```\n\n"

    doc += "---\n\n"
    return doc


def generate_dataclass_docs(cls: Type, name: str, description: str) -> str:
    """Generate documentation for a dataclass."""
    doc = f"### {name}\n\n"
    doc += f"{description}\n\n"

    fields = get_dataclass_field_info(cls)
    if fields:
        doc += "```python\n"
        for field_name, field_type in fields.items():
            doc += f"{name.lower()}.{field_name}  # {field_type}\n"
        doc += "```\n\n"

    # Check for validate method (GhostPlan)
    methods = introspect_class_methods(cls, include_inherited=False)
    if methods:
        doc += "**Methods:**\n"
        for m in methods:
            ret = f" -> {m.return_type}" if m.return_type else ""
            doc += f"- `.{m.name}{m.signature}{ret}` - {m.description}\n"
        doc += "\n"

    return doc


def generate_response_types() -> str:
    """Generate documentation for response dataclasses."""
    doc = "## Response Types\n\n"
    doc += "These dataclasses are returned by action methods.\n\n"

    # GhostPlan
    doc += generate_dataclass_docs(
        GhostPlan,
        "GhostPlan",
        "A validated placement plan returned by `placement_hints` methods.",
    )

    # ConnectionPosition
    doc += generate_dataclass_docs(
        ConnectionPosition,
        "ConnectionPosition",
        "A valid position for placing a target entity to connect to a source entity. "
        "Returned by `get_connection_positions()` with alignment information.",
    )

    # ResearchStatus
    doc += generate_dataclass_docs(
        ResearchStatus,
        "ResearchStatus",
        "Comprehensive research status with progressive detail levels. Returned by `research.status()`. "
        "Provides minimal info if no research, queue info if queued, and full details if actively researching.",
    )

    # QueuedTechnology
    doc += generate_dataclass_docs(
        QueuedTechnology,
        "QueuedTechnology",
        "Basic information about a technology in the research queue. Used within `ResearchStatus.queue`.",
    )

    # ResearchQueueItem (kept for backward compatibility, though not currently used)
    doc += generate_dataclass_docs(
        ResearchQueueItem,
        "ResearchQueueItem",
        "Legacy research queue item. Use `QueuedTechnology` and `ResearchStatus` instead.",
    )

    doc += "---\n\n"
    return doc


def generate_exception_types() -> str:
    """Generate documentation for exception types."""
    doc = "## Exception Types\n\n"
    doc += "These exceptions are raised by action methods when operations fail.\n\n"

    # Walking exceptions
    doc += "### Walking Exceptions\n\n"
    doc += "Raised by `walking.walk_to()`, `walking.walk_to_entity()`, and entity/resource `walk_to()` methods.\n\n"

    doc += "#### WalkingUnreachableError\n\n"
    doc += "Target is definitively unreachable after exhausting all approach options.\n\n"
    doc += "```python\n"
    doc += "class WalkingUnreachableError(WalkingError):\n"
    doc += "    failure_type: str  # e.g., 'blocked_path'\n"
    doc += "    candidates_tried: int  # Number of approach tiles tried\n"
    doc += "```\n\n"
    doc += "**When raised:**\n"
    doc += "- For entity-aware walking: all candidate tiles were tried, no path found\n"
    doc += "- For position-only walking: no path to position exists\n\n"
    doc += "**Resolution:** The agent may need to destroy/deconstruct obstacles to reach the target.\n\n"

    doc += "#### WalkingEntityNotFoundError\n\n"
    doc += "Entity reference is no longer valid.\n\n"
    doc += "```python\n"
    doc += "class WalkingEntityNotFoundError(WalkingError):\n"
    doc += "    entity_name: str  # Name of the entity\n"
    doc += "    position: MapPosition  # Expected position\n"
    doc += "```\n\n"
    doc += "**When raised:** The entity may have been destroyed, picked up, or moved.\n\n"
    doc += "**Resolution:** Refresh the entity reference and try again.\n\n"

    doc += "#### WalkingNoStandableTilesError\n\n"
    doc += "No standable tiles exist within reach of the target entity.\n\n"
    doc += "```python\n"
    doc += "class WalkingNoStandableTilesError(WalkingError):\n"
    doc += "    entity_name: str  # Name of the entity\n"
    doc += "```\n\n"
    doc += "**When raised:** The entity may be completely surrounded by obstacles.\n\n"
    doc += "**Resolution:** Clear obstacles around the entity or use a different approach path.\n\n"

    doc += "---\n\n"
    return doc


def generate_item_types() -> str:
    """Generate documentation for item types."""
    doc = "## Item Types\n\n"

    # Item
    doc += "### Item\n\n"
    doc += "Base class for items in inventory.\n\n"
    doc += "```python\n"
    doc += "item.name        # str - item prototype name\n"
    doc += "item.stack_size  # int - max stack size\n"
    doc += "```\n\n"

    # PlaceableItem
    doc += "### PlaceableItem\n\n"
    doc += "Items that can be placed as entities on the map.\n\n"
    methods = introspect_class_methods(PlaceableItem, include_inherited=False)
    doc += "```python\n"
    for m in methods:
        if m.is_property:
            doc += f"item.{m.name}  # {m.return_type or 'Any'}\n"
        else:
            prefix = "await " if m.is_async else ""
            ret = f" -> {m.return_type}" if m.return_type else ""
            doc += f"{prefix}item.{m.name}{m.signature}{ret}\n"
    doc += "```\n\n"

    # ItemStack
    doc += "### ItemStack\n\n"
    doc += "A quantity of items, used for inventory operations.\n\n"
    doc += "```python\n"
    doc += "stack.name   # str - item name\n"
    doc += "stack.count  # int - quantity\n"
    doc += "```\n\n"
    doc += "Used with: `entity.add_fuel(stacks)`, `entity.add_ingredients(stacks)`\n\n"

    doc += "---\n\n"
    return doc


def generate_resource_types() -> str:
    """Generate documentation for resource types via introspection."""
    doc = "## Resource Types\n\n"
    doc += "Resources represent mineable tiles on the map (ore, trees, rocks).\n\n"

    # ResourceOrePatch
    doc += "### ResourceOrePatch\n\n"
    doc += "Consolidated patch of resource tiles. Returned by `reachable_view.get_resources()`.\n\n"
    doc += "**Note:** `reachable_view.get_resources(name)` returns a **list of patches**, not individual tiles.\n\n"

    methods = introspect_class_methods(ResourceOrePatch, include_inherited=False)
    doc += "```python\n"
    for m in methods:
        if m.is_property:
            doc += f"patch.{m.name}  # {m.return_type or 'Any'} - {m.description}\n"
        elif not m.name.startswith("_"):
            prefix = "await " if m.is_async else ""
            ret = f" -> {m.return_type}" if m.return_type else ""
            doc += f"{prefix}patch.{m.name}{m.signature}{ret}\n"
    doc += "```\n\n"

    doc += "**Indexing:** Access individual tiles via `patch[0]` -> `BaseResource`\n\n"

    # BaseResource
    doc += "### BaseResource\n\n"
    doc += "Individual resource tile. Access via `reachable_view.get_resource(name)` or `patch[index]`.\n\n"

    methods = introspect_class_methods(BaseResource, include_inherited=False)
    doc += "```python\n"
    for m in methods:
        if m.is_property:
            doc += f"resource.{m.name}  # {m.return_type or 'Any'} - {m.description}\n"
        elif not m.name.startswith("_"):
            prefix = "await " if m.is_async else ""
            ret = f" -> {m.return_type}" if m.return_type else ""
            doc += f"{prefix}resource.{m.name}{m.signature}{ret}\n"
    doc += "```\n\n"

    # Resources from remote_view (REMOTE view)
    doc += "### Resources from `remote_view.get_resources()`\n\n"
    doc += "Resources from database queries have REMOTE view. Can walk to and inspect, but cannot mine.\n\n"
    doc += "```python\n"
    doc += "resource.name       # str - resource name\n"
    doc += "resource.position   # MapPosition - location on map\n"
    doc += "resource.total      # int - total amount (if patch)\n"
    doc += "resource.amount     # Optional[int] - amount (if single tile)\n"
    doc += "resource.inspect()  # str - formatted inspection\n"
    doc += "await resource.walk_to()  # ✓ Navigate to resource\n"
    doc += "# await resource.mine()   # ✗ AttributeError - REMOTE view blocks mine()\n"
    doc += "```\n\n"

    doc += "**To mine:** Use `await resource.walk_to()` to navigate. After walking, the resource **automatically becomes REACHABLE** and you can mine it directly - no need to get it again via `reachable_view.get_resource()`.\n\n"
    doc += "```python\n"
    doc += "# Preferred pattern:\n"
    doc += "iron_ore = remote_view.get_resources(\"SELECT * FROM resource_tile WHERE name = 'iron-ore' LIMIT 1\")[0]\n"
    doc += "await iron_ore.walk_to()  # Automatically converts to REACHABLE\n"
    doc += "items = await iron_ore.mine(max_count=25)  # Use directly\n"
    doc += "```\n\n"

    # Common confusion clarification
    doc += "### Patch vs Tile Distinction\n\n"
    doc += "| Method | Returns | Use `total` | Use `amount` |\n"
    doc += "|--------|---------|-------------|--------------|\n"
    doc += "| `reachable_view.get_resources(name)` | `List[ResourceOrePatch]` | ✓ | ✗ |\n"
    doc += "| `reachable_view.get_resource(name)` | `BaseResource` | ✗ | ✓ |\n"
    doc += "| `patch[index]` | `BaseResource` | ✗ | ✓ |\n"
    doc += "| `remote_view.get_resources(sql)` | `List[BaseResource]` (REMOTE view) | ✓/✗ (depends) | ✓/✗ (depends) |\n\n"

    doc += "---\n\n"
    return doc


def generate_entity_access() -> str:
    """Generate docs for how to get entities and resources."""
    return """## Getting Entities and Resources

### Reachable (Within Interaction Range)

Entities and resources you can interact with immediately.

```python
# Entities
entity = reachable_view.get_entity("stone-furnace")  # -> Optional[BaseEntity]
entities = reachable_view.get_entities("burner-mining-drill")  # -> List[BaseEntity]
ghosts = reachable_view.get_ghosts()  # -> List[BaseEntity]

# Resources
coal = reachable_view.get_resource("coal")  # -> Optional[BaseResource]
resources = reachable_view.get_resources()  # -> List[BaseResource]

# Mining (via resource object)
items = await coal.mine(max_count=25)  # -> List[ItemStack]
```

### Remote View (Map-Wide, Read-Only)

Query entities anywhere via SQL. Cannot mutate - walk to them first.

**IMPORTANT**: Use `entity.walk_to()` or `resource.walk_to()` on remote objects. After walking, the entity/resource **automatically becomes REACHABLE** and you can use it directly - no need to get it again via `reachable_view.get_entity()` or `reachable_view.get_resource()`.

```python
# Entities
drills = remote_view.get_entities("SELECT * FROM map_entity WHERE entity_name = 'electric-mining-drill'")  # -> List[BaseEntity]
drill = drills[0]

# Walk to the drill - it automatically becomes REACHABLE
await drill.walk_to()  # Entity-aware pathfinding

# Now you can use it directly - no need to get it again!
drill.add_fuel(inventory.create_item_stacks("coal", 5))

# Ghosts  
ghosts = remote_view.get_ghosts("SELECT * FROM ghost")  # -> List[BaseEntity]

# Resources
resources = remote_view.get_resources("SELECT * FROM resource_tile WHERE name = 'iron-ore'")  # -> List[BaseResource] (REMOTE view)
iron_ore = resources[0]

# Walk to the resource - it automatically becomes REACHABLE
await iron_ore.walk_to()  # Entity-aware pathfinding

# Now you can mine it directly!
items = await iron_ore.mine(max_count=25)

# Counts
count = remote_view.count_entities("stone-furnace")  # -> int
ghost_count = remote_view.count_ghosts("transport-belt")  # -> int

# Raw queries
rows = remote_view.query("SELECT entity_name, COUNT(*) FROM map_entity GROUP BY entity_name")  # -> List[Dict]
```

### View Distinction

| View | Source | Actions | Use Case |
|------|--------|---------|----------|
| REACHABLE | `reachable_view.*` | All actions available (no `walk_to` - already in range) | Interact with nearby entities |
| REMOTE | `remote_view.*` | Read-only (inspect, `walk_to`) | Query map-wide, then walk to interact |

---

"""


def generate_action_gating() -> str:
    """Generate action gating docs from BaseEntity class attributes."""
    reachable_only = sorted(BaseEntity._REACHABLE_ONLY)
    ghost_blocked = sorted(BaseEntity._GHOST_BLOCKED)

    doc = """## Action Availability

Actions are filtered based on **view type** and **ghost status**.

### View-Based Filtering

Remote entities are read-only - walk within range first.

| Action | Reachable | Remote |
|--------|-----------|--------|
"""

    all_actions = set(reachable_only) | {"inspect", "build", "remove", "walk_to"}
    for action in sorted(all_actions):
        reachable = "✓"
        # walk_to is available on remote entities, not reachable (already in range)
        if action == "walk_to":
            reachable = "✗"
            remote = "✓"
        else:
            remote = "✗" if action in reachable_only else "✓"
        doc += f"| `{action}()` | {reachable} | {remote} |\n"

    doc += """
### Ghost-Based Filtering

Ghosts are placeholders - no inventory or internal state.

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


def generate_ghost_flow() -> str:
    """Generate placement planning and ghost documentation via introspection."""
    doc = """## Placement Planning

Entity placement follows a three-tier flow for safety and validation:

### 1. Plan (Dry Run)

Use `placement_hints` to generate validated plans before committing:

```python
# Plan a line of belts
plan = placement_hints.get_placement_line(
    "transport-belt",
    start=MapPosition(0, 0),
    end=MapPosition(10, 0)
)  # -> GhostPlan

# Plans are pre-validated
if plan.valid:
    print(f"Plan has {len(plan.positions)} positions")
```

### Connection Types

`get_connection_positions()` solves spatial puzzles between entities.

"""
    # Generate ConnectionType enum docs
    doc += "```python\n"
    for ct in ConnectionType:
        doc += f"ConnectionType.{ct.name}  # {ct.value}\n"
    doc += "```\n\n"

    # Entity compatibility table from introspected sets
    doc += """### Entity Compatibility

Each `ConnectionType` only works with specific source entities. Using incompatible entities raises `EntityValidationError`.

| ConnectionType | Valid Source Entities |
|----------------|----------------------|
"""
    doc += (
        f"| `ITEM_DROP` | {', '.join(f'`{e}`' for e in sorted(ITEM_DROP_ENTITIES))} |\n"
    )
    doc += f"| `FLUID_PIPE` | {', '.join(f'`{e}`' for e in sorted(FLUID_PIPE_ENTITIES))} |\n"
    doc += "| `INSERTER_REACH` | Use `get_inserter_placement_positions()` instead |\n"
    doc += "| `BELT_FLOW` | Use `get_placement_line()` |\n"
    doc += "| `ELECTRIC_WIRE` | Use `get_pole_line()` or `get_pole_coverage_*()` |\n"
    doc += "\n"

    # Resource placement constraints
    doc += """### Placement Constraints

Some entities have special placement requirements:

| Entity | Requirement |
|--------|-------------|
"""
    for entity in sorted(RESOURCE_PLACEMENT_ENTITIES):
        doc += f"| `{entity}` | Must be placed on resource tiles |\n"
    for entity in sorted(WATER_PLACEMENT_ENTITIES):
        doc += f"| `{entity}` | Must be placed on water tiles |\n"
    doc += "\n"

    # Example usage
    doc += """### Connection Example

```python
# Find where a pipe can connect to a boiler
# Note: placement_hints and ConnectionType are pre-loaded as global variables, no import needed

boiler = reachable_view.get_entity("boiler")
pipe_positions = placement_hints.get_connection_positions(
    source_entity=boiler,
    target_entity_name="pipe",
    connection_type=ConnectionType.FLUID_PIPE
)  # -> List[ConnectionPosition]

# Place pipes at valid positions
# Positions are sorted by alignment (lower perpendicular_offset = better aligned)
for conn_pos in pipe_positions:
    inventory.get_item("pipe").place(conn_pos.position, conn_pos.direction)
    # conn_pos.perpendicular_offset tells you how well-aligned this position is
```

**Return Value:**
- Returns `List[ConnectionPosition]` - structured objects with `.position`, `.direction`, and `.perpendicular_offset`
- Positions are sorted by alignment (lower `perpendicular_offset` = better aligned with source entity)
- `perpendicular_offset`: Distance from source entity perpendicular to flow direction (0.0 = perfectly aligned)
- `direction`: May be `None` if the target entity doesn't require explicit direction
- Entities like pipes, chests can be placed without direction (Factorio auto-determines it)
- Always pass `conn_pos.direction` directly to `place()` - it handles `None` gracefully

### Validation API

Access validation directly for custom checks:

"""
    # Introspect PlacementValidator
    validator_methods = introspect_class_methods(
        PlacementValidator, include_inherited=False
    )
    doc += "```python\n"
    doc += "validator = placement_hints.validator\n\n"
    for m in validator_methods:
        if not m.name.startswith("_"):
            ret = f" -> {m.return_type}" if m.return_type else ""
            doc += f"validator.{m.name}{m.signature}{ret}\n"
    doc += "```\n\n"

    doc += """**Build check types:**
- `ghost=False` → validates for real entity placement
- `ghost=True` → validates for ghost placement (less strict)

### Inserter Placement

```python
# Find where to place inserter connecting drill to furnace
drill = reachable_view.get_entity("electric-mining-drill")
furnace = reachable_view.get_entity("stone-furnace")

positions = placement_hints.get_inserter_placement_positions(
    source_entity=drill,
    target_entity=furnace,
    inserter_name="inserter"
)  # -> List[Tuple[MapPosition, Direction]]
```

### Pole Lines & Coverage

```python
# Connect distant areas with poles
plan = placement_hints.get_pole_line(
    start=mining_area,
    end=factory_pos,
    pole_name="big-electric-pole"
)  # Poles spaced at max wire distance

# Find single pole to cover multiple entities
drills = reachable_view.get_entities("electric-mining-drill")
pos = placement_hints.get_pole_coverage_position(drills)  # None if impossible

# Get minimum poles for coverage
plan, uncovered = placement_hints.get_pole_coverage_plan(drills)
```

### Underground Segments

```python
# Plan underground belt section
plan = placement_hints.get_underground_segment(
    entity_name="underground-belt",
    start=MapPosition(0, 0),
    end=MapPosition(5, 0),
    direction=Direction.EAST
)  # Raises ValueError if distance > max_distance (5 for belts)
```

---

### 2. Place Ghosts

Commit the plan by placing ghosts:

```python
# Option 1: Build plan (places ghosts + builds them)
result = await ghost_builder.build_plan(plan, strict=True)  # -> Dict

# Option 2: Manual ghost placement
belt_item = inventory.get_item("transport-belt")
for position, direction in plan.positions:
    belt_item.place_ghost(position, direction)
```

**Ghost Labels:** Each GhostPlan has a unique `label` for grouping related ghosts.

### 3. Build to Real Entities

Convert ghosts to real entities:

```python
# Build from reachable ghosts
ghost = reachable_view.get_ghosts()[0]
ghost.build()

# Or build multiple via ghost_builder
ghosts = reachable_view.get_ghosts("transport-belt")
result = await ghost_builder.build_ghosts(ghosts, count=10, strict=True)
```

"""
    # Add GhostPlan structure
    doc += generate_dataclass_docs(
        GhostPlan,
        "GhostPlan",
        "Validated placement plan from `placement_hints` methods.",
    )

    doc += """### Strict Mode

The `strict` parameter validates inventory before building:

```python
# strict=True: Fails fast if agent lacks required items
result = await ghost_builder.build_plan(plan, strict=True)
if "error" in result:
    print(f"Insufficient items: {result['error']}")

# strict=False (default): Builds what it can, reports failures
result = await ghost_builder.build_ghosts(ghosts, count=10)
print(f"Built {result['built_count']}, Failed {result['failed_count']}")
```

---

"""
    return doc


def generate_entity_reference() -> str:
    """Generate entity reference from ENTITY_CLASS_MAP."""
    doc = "## Entity Reference\n\n"

    capability_groups: Dict[str, List[tuple]] = {}

    for factorio_name, entity_cls in sorted(ENTITY_CLASS_MAP.items()):
        caps = get_entity_capabilities(entity_cls)
        cap_key = ", ".join(sorted(c.name for c in caps)) or "Basic"
        if cap_key not in capability_groups:
            capability_groups[cap_key] = []
        capability_groups[cap_key].append((factorio_name, entity_cls, caps))

    for cap_pattern, entities in sorted(capability_groups.items()):
        doc += f"### {cap_pattern}\n\n"

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

        doc += "**Entities:** "
        doc += ", ".join(f"`{name}`" for name, _, _ in entities)
        doc += "\n\n"

    return doc


def generate_inspection_reference() -> str:
    """Generate inspection reference from EntityInspection model."""
    doc = "## Inspection\n\n"
    doc += "Call `entity.inspect()` to get current state.\n\n"

    fields = get_pydantic_fields(EntityInspection)

    doc += "### Base Fields (always present)\n\n"
    doc += "| Field | Type |\n|-------|------|\n"
    base_fields = ["name", "position", "direction", "status", "is_ghost"]
    for name in base_fields:
        if name in fields:
            doc += f"| `{name}` | `{fields[name]}` |\n"

    doc += "\n### Capability Slots (when applicable)\n\n"
    doc += "| Slot | State Type | When Present |\n|------|------------|-------------|\n"

    slot_mixin_map = {}
    for mixin in ALL_MIXINS:
        meta = derive_mixin_meta(mixin)
        if meta.slot:
            slot_mixin_map[meta.slot] = mixin.__name__

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
            state_name = (
                type_str.split(".")[-1].replace("]", "").replace("Optional[", "")
            )
            doc += f"| `{name}` | `{state_name}` | {mixin} |\n"

    doc += "\n---\n\n"
    return doc


def generate_examples() -> str:
    """Generate common pattern examples."""
    return """## Common Patterns

### Complete Mining Setup

```python
# 1. Find resources via remote SQL query
ore_deposits = remote_view.get_resources("SELECT * FROM resource_tile WHERE name = 'iron-ore' LIMIT 5")
target_resource = ore_deposits[0]

# 2. Walk to the resource - it automatically becomes REACHABLE
await target_resource.walk_to()  # Entity-aware pathfinding

# 3. Use it directly - no need to get it again!
items = await target_resource.mine(max_count=25)

# 4. Manual mining for bootstrap resources (if needed)
coal_resources = remote_view.get_resources("SELECT * FROM resource_tile WHERE name = 'coal' LIMIT 1")
if coal_resources:
    await coal_resources[0].walk_to()
    coal_items = await coal_resources[0].mine(max_count=10)

# 5. Place automated mining
drill_item = inventory.get_item("burner-mining-drill")
drill = drill_item.place(target_resource.position, Direction.SOUTH)

# 6. Fuel the drill
fuel = inventory.create_item_stacks("coal", 5)
drill.add_fuel(fuel)

# 7. Check drill status
state = drill.inspect()
print(f"Mining: {state.miner.mining_target}")
```

### Belt Line with Placement Planning

```python
# 1. Create validated belt line plan
start = reachable_view.get_entity("burner-mining-drill").position
end = start.offset((0, 10), Direction.SOUTH)

plan = placement_hints.get_placement_line("transport-belt", start=start, end=end)

# 2. Check if plan is valid
if not plan.valid:
    print("Invalid placement - obstacles detected")

# 3. Build the plan (places ghosts + builds to real)
result = await ghost_builder.build_plan(plan, strict=True)
print(f"Built {result.get('built_count', 0)} entities")
```

### Remote Query and Maintenance Loop

```python
# 1. Find all drills needing fuel
drills = remote_view.get_entities(
    "SELECT * FROM map_entity WHERE entity_name = 'burner-mining-drill'"
)

for remote_drill in drills:
    # 2. Walk to the drill - it automatically becomes REACHABLE
    await remote_drill.walk_to()  # Entity-aware pathfinding
    
    # 3. Use it directly - no need to get it again!
    state = remote_drill.inspect()
    if state.burner.fuel_inventory.get("coal", 0) < 5:
        fuel = inventory.create_item_stacks("coal", 10)
        remote_drill.add_fuel(fuel)

# 4. Stop walking when done
walking.stop()
```

### Crafting Recipes

**IMPORTANT: Handcraftability**
- Only recipes with `category="crafting"` can be handcrafted
- Recipes like `iron-plate`, `copper-plate`, `steel-plate`, `stone-brick` have `category="smelting"` and **require a furnace**
- Other categories like `chemistry`, `oil-processing` require specific machines

```python
# 1. Basic crafting (waits for completion)
initial_gears = inventory.check_total("iron-gear-wheel")
print("Initial gear count:", initial_gears)

# Craft 5 iron-gear-wheel (requires 2 iron-plate each)
items = await crafting.craft("iron-gear-wheel", count=5)
print("Crafted items:", len(items), "stacks")
for item in items:
    print("  -", item.count, "x", item.name)

final_gears = inventory.check_total("iron-gear-wheel")
print("Gears added:", final_gears - initial_gears)
```

```python
# 2. Crafting with ingredient verification
# Get initial counts
initial_cables = inventory.check_total("copper-cable")
initial_plates = inventory.check_total("copper-plate")
print("Initial:", initial_plates, "plates,", initial_cables, "cables")

# Craft 10 copper-cable (requires 1 copper-plate each)
items = await crafting.craft("copper-cable", count=10)

# Check results
final_cables = inventory.check_total("copper-cable")
final_plates = inventory.check_total("copper-plate")
print("Final:", final_plates, "plates,", final_cables, "cables")
print("Cables added:", final_cables - initial_cables)
```

```python
# 3. Multi-ingredient recipes
# Craft electronic-circuit (requires 1 iron-plate + 3 copper-cable)
initial_circuits = inventory.check_total("electronic-circuit")
items = await crafting.craft("electronic-circuit", count=5)

final_circuits = inventory.check_total("electronic-circuit")
print("Circuits added:", final_circuits - initial_circuits)
```

```python
# 4. Queue management (non-blocking)
# Enqueue recipe for crafting (returns immediately)
crafting.enqueue("iron-gear-wheel", count=10)

# Check crafting status
status = crafting.status()
print("Active:", status.get("active"))
print("Recipe:", status.get("recipe"))
print("Action ID:", status.get("action_id"))

# Cancel queued crafting
crafting.dequeue("iron-gear-wheel", count=5)  # Cancel 5
crafting.dequeue("iron-gear-wheel")  # Cancel all remaining
```

```python
# 5. Error handling for unavailable recipes
try:
    items = await crafting.craft("iron-plate", count=10)
except RuntimeError as e:
    if "not available" in str(e):
        print("Recipe not available - may require furnace or technology research")
    else:
        raise
```

**Common Handcraftable Recipes:**
- `iron-gear-wheel` - Craft from 2x iron-plate
- `copper-cable` - Craft from 1x copper-plate
- `electronic-circuit` - Craft from 1x iron-plate + 3x copper-cable
- `iron-stick` - Craft from 1x iron-plate
- `wooden-chest` - Craft from 2x wood

**NOT Handcraftable (require machines):**
- `iron-plate` - Requires furnace (category=smelting)
- `copper-plate` - Requires furnace (category=smelting)
- `steel-plate` - Requires furnace (category=smelting)
- `stone-brick` - Requires furnace (category=smelting)

"""


def generate_document() -> str:
    """Generate the complete documentation."""
    sections = [
        generate_header(),
        generate_top_level_accessors(),
        generate_core_types(),
        generate_entity_access(),
        generate_item_types(),
        generate_resource_types(),
        generate_action_gating(),
        generate_ghost_flow(),
        generate_entity_reference(),
        generate_inspection_reference(),
        generate_response_types(),
        generate_exception_types(),
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
        default=str(PROJECT_ROOT / "docs" / "for-llms" / "api_reference.md"),
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
