"""
Programmatic documentation for EntityInspection and capability states.

Uses Pydantic's schema generation to extract structure at runtime,
ensuring documentation always matches the actual implementation.

Examples are defined as Example objects - validated and trackable.
Schema structure is introspected from actual types.
"""

from typing import Dict, Any, List, Tuple, Type, get_type_hints, get_origin, get_args
from pydantic import BaseModel
import inspect

from FactoryVerse.docs.models import Example, ValidationLevel


# =============================================================================
# EXAMPLES - Structured, validated, co-located with their documentation
# =============================================================================

INSPECTION_USAGE_EXAMPLE = Example(
    code='''
drill = reachable_view.get_entity('burner-mining-drill')
inspection = drill.inspect()

# Base fields (always present)
print(inspection.name)       # 'burner-mining-drill'
print(inspection.position)   # {'x': 10.5, 'y': 20.5}
print(inspection.status)     # EntityStatus.WORKING

# Capability slots - check for None before accessing
if inspection.burner:
    print(f"Fuel: {inspection.burner.fuel_inventory}")
    print(f"Heat: {inspection.burner.heat}")

if inspection.miner:
    print(f"Mining progress: {inspection.miner.mining_progress}")
    print(f"Target: {inspection.miner.mining_target}")

# Compact JSON output (excludes None fields)
json_str = inspection.model_dump_json(exclude_none=True)
'''.strip(),
    decision_context="Getting volatile runtime state from an entity",
    preconditions=["Entity exists and is reachable"],
    expected_outcome="EntityInspection with populated capability slots based on entity type",
    validation_level=ValidationLevel.SYNTAX,
)

INSPECTION_CONDITIONAL_EXAMPLE = Example(
    code='''
# Different entities have different capability slots populated
furnace = reachable_view.get_entity('stone-furnace')
inspection = furnace.inspect()

# Furnace has: burner (fuel), crafter (smelting)
if inspection.burner:
    remaining = inspection.burner.remaining_burning_fuel
    print(f"Fuel remaining: {remaining}")

if inspection.crafter:
    if inspection.crafter.recipe:
        print(f"Smelting: {inspection.crafter.recipe}")
        print(f"Progress: {inspection.crafter.crafting_progress:.1%}")
'''.strip(),
    decision_context="Checking entity-specific capabilities",
    preconditions=["Entity exists"],
    expected_outcome="Only relevant slots are non-None",
    validation_level=ValidationLevel.SYNTAX,
)


def get_inspection_examples() -> List[Example]:
    """Return all inspection-related examples for validation and rendering."""
    return [INSPECTION_USAGE_EXAMPLE, INSPECTION_CONDITIONAL_EXAMPLE]


def get_inspection_schema() -> Dict[str, Any]:
    """Get the complete EntityInspection JSON schema from Pydantic.

    Returns:
        JSON schema dict with all nested state definitions.
    """
    from FactoryVerse.factory.entity.inspection import EntityInspection
    return EntityInspection.model_json_schema()


def get_base_fields() -> List[Tuple[str, str, bool]]:
    """Introspect base fields from EntityInspection (non-capability slots).

    Returns:
        List of (field_name, type_str, is_optional) tuples for base fields
    """
    from FactoryVerse.factory.entity.inspection import EntityInspection

    base_fields = []
    hints = get_type_hints(EntityInspection)

    for field_name in EntityInspection.model_fields:
        field_type = hints.get(field_name)
        if field_type is None:
            continue

        # Check if this is a capability slot (has a BaseModel subclass)
        inner = _unwrap_optional(field_type)
        if inner and isinstance(inner, type) and issubclass(inner, BaseModel):
            continue  # Skip capability slots

        type_str = _format_type(field_type)
        is_optional = _is_optional(field_type)
        base_fields.append((field_name, type_str, is_optional))

    return base_fields


def get_capability_states() -> Dict[str, Type[BaseModel]]:
    """Discover all capability state classes used by EntityInspection.

    Returns:
        Dict mapping slot name to state class (e.g., {"burner": BurnerState})
    """
    from FactoryVerse.factory.entity.inspection import EntityInspection

    states = {}
    hints = get_type_hints(EntityInspection)

    for field_name, field_type in hints.items():
        # Extract the actual type from Optional[X]
        inner = _unwrap_optional(field_type)
        if inner and isinstance(inner, type) and issubclass(inner, BaseModel):
            states[field_name] = inner

    return states


def _unwrap_optional(field_type: Any) -> Any:
    """Unwrap Optional[X] to get X, or return None if not Optional."""
    args = get_args(field_type)

    # Check for Union[X, None] pattern (Optional is Union[X, None])
    if args and type(None) in args:
        for arg in args:
            if arg is not type(None):
                return arg
    return None


def _is_optional(field_type: Any) -> bool:
    """Check if a type is Optional (Union with None)."""
    args = get_args(field_type)
    return bool(args and type(None) in args)


def get_state_fields(state_class: Type[BaseModel]) -> List[Tuple[str, str, str]]:
    """Extract field info from a Pydantic state model.

    Returns:
        List of (field_name, type_str, description) tuples
    """
    fields = []

    # Get field info from model_fields (Pydantic v2)
    for name, field_info in state_class.model_fields.items():
        # Get type annotation
        annotation = field_info.annotation
        type_str = _format_type(annotation)

        # Get description from docstring or field
        description = field_info.description or ""

        fields.append((name, type_str, description))

    # Also check for computed properties (skip Pydantic internals)
    pydantic_internals = {
        "model_extra", "model_fields_set", "model_computed_fields",
        "model_config", "model_fields", "model_post_init"
    }
    for name, member in inspect.getmembers(state_class):
        if isinstance(member, property) and not name.startswith("_"):
            if name in pydantic_internals:
                continue
            # Get return type from property getter
            if member.fget:
                hints = get_type_hints(member.fget) if hasattr(member.fget, "__annotations__") else {}
                return_type = hints.get("return", "Any")
                type_str = _format_type(return_type)
                doc = member.fget.__doc__ or ""
                fields.append((name, type_str, f"(property) {doc.strip()}"))

    return fields


def _format_type(annotation: Any) -> str:
    """Format a type annotation as a readable string."""
    if annotation is None:
        return "None"

    if isinstance(annotation, str):
        return annotation

    if annotation is type(None):
        return "None"

    origin = get_origin(annotation)
    if origin is not None:
        args = get_args(annotation)
        origin_name = getattr(origin, "__name__", str(origin))

        # Normalize type names
        type_map = {"list": "List", "dict": "Dict", "tuple": "Tuple"}
        origin_name = type_map.get(origin_name, origin_name)

        # Handle Optional
        if origin_name == "Union" and len(args) == 2 and type(None) in args:
            non_none = [a for a in args if a is not type(None)][0]
            return f"Optional[{_format_type(non_none)}]"

        if args:
            arg_strs = [_format_type(a) for a in args]
            return f"{origin_name}[{', '.join(arg_strs)}]"
        return origin_name

    if hasattr(annotation, "__name__"):
        return annotation.__name__

    return str(annotation)


def generate_inspection_markdown() -> str:
    """Generate markdown documentation for EntityInspection from runtime introspection.

    This is fully programmatic - no hardcoded field descriptions.
    """
    lines = []

    # Header
    lines.append("## Entity Inspection Schema")
    lines.append("")
    lines.append("The `EntityInspection` class is returned by `.inspect()` on all entities.")
    lines.append("It uses optional capability slots - only relevant slots are populated.")
    lines.append("")

    # Base fields - INTROSPECTED
    lines.append("### Base Fields")
    lines.append("")
    lines.append("| Field | Type |")
    lines.append("|-------|------|")

    base_fields = get_base_fields()
    for name, type_str, _is_optional in base_fields:
        lines.append(f"| `{name}` | `{type_str}` |")
    lines.append("")

    # Capability slots
    lines.append("### Capability Slots")
    lines.append("")
    lines.append("Each slot is `Optional` - only populated if the entity has that capability.")
    lines.append("")

    states = get_capability_states()

    for slot_name, state_class in sorted(states.items()):
        lines.append(f"#### `{slot_name}`: `{state_class.__name__}`")
        lines.append("")

        # Get docstring
        if state_class.__doc__:
            doc_first_line = state_class.__doc__.strip().split("\n")[0]
            lines.append(f"*{doc_first_line}*")
            lines.append("")

        # Get fields
        fields = get_state_fields(state_class)
        if fields:
            lines.append("| Field | Type | Notes |")
            lines.append("|-------|------|-------|")
            for name, type_str, desc in fields:
                desc_short = desc[:50] + "..." if len(desc) > 50 else desc
                lines.append(f"| `{name}` | `{type_str}` | {desc_short} |")
            lines.append("")

    # Examples - pulled from structured Example objects
    lines.append("### Examples")
    lines.append("")

    for example in get_inspection_examples():
        if example.decision_context:
            lines.append(f"**{example.decision_context}:**")
            lines.append("")
        if example.preconditions:
            lines.append(f"*Preconditions: {', '.join(example.preconditions)}*")
            lines.append("")
        lines.append("```python")
        lines.append(example.code)
        lines.append("```")
        if example.expected_outcome:
            lines.append("")
            lines.append(f"→ {example.expected_outcome}")
        lines.append("")

    return "\n".join(lines)


def get_preimported_types() -> List[Tuple[str, str]]:
    """Extract pre-imported types available in agent runtime namespace.

    Returns the types that are automatically available in Tier4 execute_code(),
    which is the execution context for agent code.

    Returns:
        List of (type_name, module_path) tuples
    """
    # These types are injected into the execute_code namespace by Tier4Runtime.
    # Keep this list in sync with builtin_names in tier4_runtime.py execute_code().
    preimported = [
        # Core spatial types
        ("MapPosition", "FactoryVerse.factory.types"),
        ("Direction", "FactoryVerse.factory.types"),
        ("BoundingBox", "FactoryVerse.factory.types"),
        # Placement planning types
        ("ConnectionType", "FactoryVerse.agent.placement_hints"),
        ("ConnectionPosition", "FactoryVerse.agent.placement_hints"),
        ("WireConnectionPosition", "FactoryVerse.agent.placement_hints"),
        ("GhostPlan", "FactoryVerse.agent.placement_hints"),
        ("PolePlacementResult", "FactoryVerse.agent.placement_hints"),
        ("EntityValidationError", "FactoryVerse.agent.placement_hints"),
        # Item types
        ("Item", "FactoryVerse.factory.item.base"),
        ("PlaceableItem", "FactoryVerse.factory.item.base"),
        ("ItemStack", "FactoryVerse.factory.item.base"),
        # Status types
        ("CraftingQueueStatus", "FactoryVerse.factory.types"),
        ("ResearchStatus", "FactoryVerse.agent.embodied_actions.research"),
        ("ResearchQueueItem", "FactoryVerse.factory.types"),
        ("QueuedTechnology", "FactoryVerse.agent.embodied_actions.research"),
        # Walking exception types
        ("WalkingError", "FactoryVerse.agent.embodied_actions.walking"),
        ("WalkingUnreachableError", "FactoryVerse.agent.embodied_actions.walking"),
        ("WalkingEntityNotFoundError", "FactoryVerse.agent.embodied_actions.walking"),
        ("WalkingNoStandableTilesError", "FactoryVerse.agent.embodied_actions.walking"),
    ]

    return preimported


def generate_preimported_types_markdown() -> str:
    """Generate markdown documenting types pre-imported in agent runtime.

    Documents types available in the Tier4 execute_code() namespace.
    """
    preimported = get_preimported_types()

    lines = []
    lines.append("## Pre-Imported Types")
    lines.append("")
    lines.append("These types are automatically imported in the agent runtime.")
    lines.append("You can use them directly without importing.")
    lines.append("")
    lines.append("| Type | Module |")
    lines.append("|------|--------|")

    for type_name, module in sorted(preimported):
        lines.append(f"| `{type_name}` | `{module}` |")

    lines.append("")

    return "\n".join(lines)
