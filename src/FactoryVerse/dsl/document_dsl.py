"""DSL Documentation Generator.

Generates LLM-readable documentation of the FactoryVerse DSL public interfaces.
Focuses on type signatures and public methods without exposing implementation details.
"""

import inspect
from typing import Any, List, Tuple, Type, get_type_hints


def _get_public_methods(cls: Type) -> List[Tuple[str, str, str]]:
    """Extract public methods with signatures and docstrings.

    Returns list of (name, signature, docstring) tuples.
    """
    methods = []
    for name, method in inspect.getmembers(cls, predicate=inspect.isfunction):
        # Skip private/magic methods
        if name.startswith("_"):
            continue

        try:
            sig = inspect.signature(method)
            # Format signature without 'self'
            params = [p for p in sig.parameters.values() if p.name != "self"]
            param_strs: List[str] = []
            for p in params:
                if p.annotation != inspect.Parameter.empty:
                    ann = _format_annotation(p.annotation)
                    if p.default != inspect.Parameter.empty:
                        param_strs.append(f"{p.name}: {ann} = ...")
                    else:
                        param_strs.append(f"{p.name}: {ann}")
                else:
                    param_strs.append(p.name)

            ret = ""
            if sig.return_annotation != inspect.Signature.empty:
                ret = f" -> {_format_annotation(sig.return_annotation)}"

            signature = f"{name}({', '.join(param_strs)}){ret}"
        except (ValueError, TypeError):
            signature = f"{name}(...)"

        doc = inspect.getdoc(method) or ""
        # Take only first line of docstring
        doc = doc.split("\n")[0] if doc else ""

        methods.append((name, signature, doc))

    return sorted(methods, key=lambda x: x[0])


def _get_public_properties(cls: Type) -> List[Tuple[str, str, str]]:
    """Extract public properties with types and docstrings.

    Returns list of (name, type, docstring) tuples.
    """
    props = []
    for name in dir(cls):
        if name.startswith("_"):
            continue

        attr = getattr(cls, name, None)
        if isinstance(attr, property):
            # Get return type from getter if available
            ret_type = "Any"
            if attr.fget:
                try:
                    hints = get_type_hints(attr.fget)
                    if "return" in hints:
                        ret_type = _format_annotation(hints["return"])
                except Exception:
                    pass

            doc = inspect.getdoc(attr) or ""
            doc = doc.split("\n")[0] if doc else ""
            props.append((name, ret_type, doc))

    return sorted(props, key=lambda x: x[0])


def _format_annotation(ann: Any) -> str:
    """Format a type annotation as a readable string."""
    if ann is None:
        return "None"
    if isinstance(ann, str):
        return ann
    if hasattr(ann, "__origin__"):
        # Generic types like List[X], Optional[X], etc.
        origin = getattr(ann, "__origin__", None)
        args = getattr(ann, "__args__", ())

        origin_name = getattr(origin, "__name__", str(origin))
        if origin_name == "Union":
            # Check for Optional (Union with None)
            if len(args) == 2 and type(None) in args:
                other = [a for a in args if a is not type(None)][0]
                return f"Optional[{_format_annotation(other)}]"
            return f"Union[{', '.join(_format_annotation(a) for a in args)}]"

        if args:
            return f"{origin_name}[{', '.join(_format_annotation(a) for a in args)}]"
        return origin_name

    return getattr(ann, "__name__", str(ann))


def _format_class(cls: Type, show_bases: bool = True) -> str:
    """Format a class with its public interface."""
    lines = []

    # Class header
    if show_bases:
        bases = [b.__name__ for b in cls.__bases__ if b.__name__ != "object"]
        if bases:
            lines.append(f"class {cls.__name__}({', '.join(bases)}):")
        else:
            lines.append(f"class {cls.__name__}:")
    else:
        lines.append(f"class {cls.__name__}:")

    # Class docstring (first line only)
    doc = inspect.getdoc(cls)
    if doc:
        lines.append(f'    """{doc.split(chr(10))[0]}"""')

    # Properties
    props = _get_public_properties(cls)
    if props:
        lines.append("")
        lines.append("    # Properties")
        for name, ptype, pdoc in props:
            if pdoc:
                lines.append(f"    {name}: {ptype}  # {pdoc}")
            else:
                lines.append(f"    {name}: {ptype}")

    # Methods
    methods = _get_public_methods(cls)
    if methods:
        lines.append("")
        lines.append("    # Methods")
        for name, sig, mdoc in methods:
            if mdoc:
                lines.append(f"    {sig}  # {mdoc}")
            else:
                lines.append(f"    {sig}")

    return "\n".join(lines)


# =============================================================================
# DOCUMENTATION GENERATORS
# =============================================================================


def document_core_types() -> str:
    """Document core DSL types (MapPosition, Direction, etc.)."""
    from FactoryVerse.dsl.types import MapPosition, Direction

    output = []
    output.append("# Core Types\n")

    # MapPosition
    output.append("@dataclass")
    output.append("class MapPosition:")
    output.append('    """A position on the game map."""')
    output.append("    x: float")
    output.append("    y: float")
    output.append("")

    # Direction enum
    output.append("class Direction(Enum):")
    output.append('    """Cardinal directions for entity placement and movement."""')
    output.append("    NORTH = 0")
    output.append("    EAST = 2")
    output.append("    SOUTH = 4")
    output.append("    WEST = 6")
    output.append("")

    return "\n".join(output)


def document_entity_views() -> str:
    """Document entity view wrappers."""
    from FactoryVerse.dsl.entity.views import Reachable, RemoteView, Ghost

    output = []
    output.append("# Entity Views\n")
    output.append("# Views wrap BaseEntity to control what operations are available.\n")

    output.append(_format_class(Reachable))
    output.append("")
    output.append(_format_class(RemoteView))
    output.append("")
    output.append(_format_class(Ghost))
    output.append("")

    return "\n".join(output)


def document_base_entity() -> str:
    """Document BaseEntity and key entity implementations."""
    from FactoryVerse.dsl.entity.base_entity import BaseEntity

    output = []
    output.append("# Entity Classes\n")

    output.append(_format_class(BaseEntity))
    output.append("")

    # Document specific entity implementations
    try:
        from FactoryVerse.dsl.entity.implementations.furnace import Furnace
        from FactoryVerse.dsl.entity.implementations.mining_drill import (
            BurnerMiningDrill,
            ElectricMiningDrill,
        )
        from FactoryVerse.dsl.entity.implementations.inserter import Inserter
        from FactoryVerse.dsl.entity.implementations.container import Container
        from FactoryVerse.dsl.entity.implementations.assembler import AssemblingMachine

        output.append("# Specific Entity Types (inherit from BaseEntity)")
        output.append("# These add entity-specific methods and properties.\n")

        for cls in [
            Furnace,
            BurnerMiningDrill,
            ElectricMiningDrill,
            Inserter,
            Container,
            AssemblingMachine,
        ]:
            output.append(_format_class(cls, show_bases=False))
            output.append("")
    except ImportError:
        pass

    return "\n".join(output)


def document_items() -> str:
    """Document Item types."""
    from FactoryVerse.dsl.item.base import Item, PlaceableItem, ItemStack

    output = []
    output.append("# Item Classes\n")

    output.append(_format_class(Item))
    output.append("")
    output.append(_format_class(PlaceableItem))
    output.append("")
    output.append(_format_class(ItemStack))
    output.append("")

    return "\n".join(output)


def document_runtime() -> str:
    """Document AgentRuntime affordances."""
    output = []
    output.append("# AgentRuntime\n")
    output.append("# The runtime provides access to all agent capabilities.\n")

    output.append("class AgentRuntime:")
    output.append('    """Main runtime providing agent affordances."""')
    output.append("")
    output.append("    # Affordances (accessed as properties)")
    output.append("    walking: MovementAction       # Movement and pathfinding")
    output.append("    inventory: AgentInventory     # Inventory management")
    output.append("    crafting: CraftingAction      # Crafting items")
    output.append("    research: ResearchAction      # Technology research")
    output.append("    reachable: ReachableEntities  # Query nearby entities")
    output.append("    placement: PlacementAction    # Place/remove entities")
    output.append("")

    # Document key action classes
    try:
        from FactoryVerse.agent.actions.walking import MovementAction
        from FactoryVerse.agent.actions.inventory import AgentInventory
        from FactoryVerse.agent.actions.reachable import ReachableEntities
        from FactoryVerse.agent.actions.place_entity import PlacementAction

        output.append(_format_class(MovementAction))
        output.append("")
        output.append(_format_class(AgentInventory))
        output.append("")
        output.append(_format_class(ReachableEntities))
        output.append("")
        output.append(_format_class(PlacementAction))
        output.append("")
    except ImportError as e:
        output.append(f"# Could not load action classes: {e}")

    return "\n".join(output)


def document_ghost_tracking() -> str:
    """Document ghost/blueprint tracking."""
    from FactoryVerse.agent.ghost.types import TrackedGhost
    from FactoryVerse.agent.ghost.manager import GhostManager

    output = []
    output.append("# Ghost Tracking\n")
    output.append("# For planning entity placements before building.\n")

    output.append("@dataclass")
    output.append("class TrackedGhost:")
    output.append('    """A tracked ghost placement (Python-only, for planning)."""')
    output.append("    name: str           # Entity prototype name")
    output.append("    position: MapPosition")
    output.append("    label: Optional[str] = None  # Grouping label")
    output.append("    placed_tick: int = 0")
    output.append("")

    output.append(_format_class(GhostManager))
    output.append("")

    return "\n".join(output)


# =============================================================================
# MAIN GENERATION FUNCTION
# =============================================================================


def generate_dsl_documentation() -> str:
    """Generate complete DSL documentation for LLM consumption."""
    sections = []

    sections.append("=" * 60)
    sections.append("FACTORYVERSE DSL REFERENCE")
    sections.append("=" * 60)
    sections.append("")
    sections.append(
        "This document describes the public interface of the FactoryVerse DSL."
    )
    sections.append("Use these types and methods to interact with the Factorio game.")
    sections.append("")

    sections.append(document_core_types())
    sections.append(document_entity_views())
    sections.append(document_base_entity())
    sections.append(document_items())
    sections.append(document_runtime())
    sections.append(document_ghost_tracking())

    return "\n".join(sections)


if __name__ == "__main__":
    print(generate_dsl_documentation())
