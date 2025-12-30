"""DSL Documentation Generator.

Generates LLM-readable documentation from the agent's perspective.
Uses Python stub-style formatting for type definitions.
"""

import inspect
from typing import Any, List, Tuple, Type, get_type_hints


# =============================================================================
# MAIN GENERATION - Python Stub Style
# =============================================================================


def generate_dsl_documentation() -> str:
    """Generate agent-centric DSL documentation in stub format."""
    lines = []

    lines.append('"""')
    lines.append("FactoryVerse DSL Reference")
    lines.append("==========================")
    lines.append("")
    lines.append("This document describes types and interfaces you work with.")
    lines.append('"""')
    lines.append("")
    lines.append("from dataclasses import dataclass")
    lines.append("from typing import Optional, List, Dict")
    lines.append("from enum import Enum")
    lines.append("")
    lines.append("")

    # Core Types
    lines.append(
        "# ============================================================================"
    )
    lines.append("# CORE TYPES")
    lines.append(
        "# ============================================================================"
    )
    lines.append("")
    lines.append("@dataclass")
    lines.append("class MapPosition:")
    lines.append('    """A position on the game map."""')
    lines.append("    x: float")
    lines.append("    y: float")
    lines.append("")
    lines.append("")
    lines.append("class Direction(Enum):")
    lines.append('    """Cardinal directions for placement and movement."""')
    lines.append("    NORTH = 0")
    lines.append("    EAST = 2")
    lines.append("    SOUTH = 4")
    lines.append("    WEST = 6")
    lines.append("")
    lines.append("")

    # Ghost Entities Concept
    lines.append(
        "# ============================================================================"
    )
    lines.append("# GHOST ENTITIES")
    lines.append(
        "# ============================================================================"
    )
    lines.append(
        "# Ghosts are placeholder entities that exist in the game world but aren't"
    )
    lines.append(
        "# built yet. They're used for planning layouts before committing resources."
    )
    lines.append("#")
    lines.append("# Key concepts:")
    lines.append(
        "# - Ghosts ARE entities with is_ghost=True, they appear in entity queries"
    )
    lines.append(
        "# - This prevents silent overwrites - you'll see ghosts before placing over them"
    )
    lines.append(
        "# - Ghosts provide: build() to construct, remove() to delete, inspect() for static data"
    )
    lines.append(
        "# - Ghosts block: add_fuel(), set_recipe(), pickup() etc. (not real entities)"
    )
    lines.append("#")
    lines.append("# Query ghosts:")
    lines.append(
        "#   all_nearby = reachable.get_entities()  # includes ghosts by default"
    )
    lines.append(
        "#   only_real = reachable.get_entities(options={'include_ghosts': False})"
    )
    lines.append("#   only_ghosts = reachable.get_ghosts()")
    lines.append("#")
    lines.append("# Build ghosts:")
    lines.append("#   ghost.build()  # if reachable")
    lines.append("#   await ghost_builder.build_ghosts([ghost])  # handles walking")
    lines.append("")
    lines.append("")

    # Affordances
    lines.append(
        "# ============================================================================"
    )
    lines.append("# AFFORDANCES (what you can do)")
    lines.append(
        "# ============================================================================"
    )
    lines.append("")

    lines.append("class walking:")
    lines.append('    """Movement around the map."""')
    lines.append("    current_position: MapPosition")
    lines.append(
        "    def walk_to(self, goal: MapPosition, strict_goal: bool = True) -> MapPosition: ..."
    )
    lines.append("    def stop(self) -> None: ...")
    lines.append("")
    lines.append("")

    lines.append("class inventory:")
    lines.append('    """Your items."""')
    lines.append("    item_stacks: List[ItemStack]")
    lines.append("    def check_total(self, item_name: str) -> int: ...")
    lines.append(
        "    def get_item(self, item_name: str) -> Optional[Item | PlaceableItem]: ..."
    )
    lines.append(
        "    def create_item_stacks(self, item_name: str, count: int) -> List[ItemStack]: ..."
    )
    lines.append("")
    lines.append("")

    lines.append("class crafting:")
    lines.append('    """Make items (async operations)."""')
    lines.append(
        "    async def craft(self, recipe: str, count: int = 1) -> CraftingResult: ..."
    )
    lines.append("    def can_craft(self, recipe: str) -> bool: ...")
    lines.append("")
    lines.append("")

    lines.append("class research:")
    lines.append('    """Unlock technologies."""')
    lines.append("    def research(self, technology: str) -> ResearchResult: ...")
    lines.append("    def get_available(self) -> List[str]: ...")
    lines.append("")
    lines.append("")

    lines.append("class reachable:")
    lines.append('    """Query nearby entities you can interact with.')
    lines.append("    ")
    lines.append("    Ghosts are included by default for spatial awareness.")
    lines.append("    This prevents silent overwrites when placing entities.")
    lines.append('    """')
    lines.append(
        "    def get_entity(self, name: str, position: Optional[MapPosition] = None, options: Optional[Dict] = None) -> Optional[Entity]: ..."
    )
    lines.append(
        "    def get_entities(self, name: Optional[str] = None, options: Optional[Dict] = None) -> List[Entity]: ..."
    )
    lines.append(
        "    def get_ghosts(self, entity_name: Optional[str] = None) -> List[Entity]: ..."
    )
    lines.append(
        "    # options: include_ghosts=bool (default True), ghosts_only=bool, recipe=str, direction=Direction, status=str"
    )
    lines.append("")
    lines.append("")

    lines.append("class remote_view:")
    lines.append('    """Query distant entities (read-only)."""')
    lines.append(
        "    def query(self, entity_type: str, area: Optional[BoundingBox] = None) -> List[EntityRecord]: ..."
    )
    lines.append("")
    lines.append("")

    # Items
    lines.append(
        "# ============================================================================"
    )
    lines.append("# ITEMS")
    lines.append(
        "# ============================================================================"
    )
    lines.append("")

    lines.append("class Item:")
    lines.append('    """Something in your inventory."""')
    lines.append("    name: str")
    lines.append("    stack_size: int")
    lines.append("")
    lines.append("")

    lines.append("class PlaceableItem(Item):")
    lines.append('    """An item you can place in the world."""')
    lines.append("    tile_width: int")
    lines.append("    tile_height: int")
    lines.append("    ")
    lines.append(
        "    def place(self, position: MapPosition, direction: Direction = Direction.NORTH) -> Entity:"
    )
    lines.append('        """Place this item as an entity on the map."""')
    lines.append("        ...")
    lines.append("    ")
    lines.append(
        "    def place_ghost(self, position: MapPosition, label: Optional[str] = None) -> TrackedGhost:"
    )
    lines.append('        """Create a tracked ghost for planning (not built yet)."""')
    lines.append("        ...")
    lines.append("")
    lines.append("")

    lines.append("@dataclass")
    lines.append("class ItemStack:")
    lines.append('    """A quantity of items."""')
    lines.append("    name: str")
    lines.append("    count: int")
    lines.append("    item: Item")
    lines.append("    half: int  # half the count")
    lines.append("    full: int  # full count")
    lines.append("")
    lines.append("")

    # Entities
    lines.append(
        "# ============================================================================"
    )
    lines.append("# ENTITIES")
    lines.append(
        "# ============================================================================"
    )
    lines.append("")
    lines.append(
        "# Entities are things in the world. Access via reachable.get_entity()."
    )
    lines.append("# Each entity type has inspect() returning type-specific data.")
    lines.append("")

    lines.append("class Entity:")
    lines.append('    """Base entity interface.')
    lines.append("    ")
    lines.append("    Entities with is_ghost=True are ghost placeholders.")
    lines.append(
        "    Ghosts provide build() and remove() instead of normal operations."
    )
    lines.append('    """')
    lines.append("    name: str")
    lines.append("    position: MapPosition")
    lines.append("    direction: Direction")
    lines.append("    tile_width: int")
    lines.append("    tile_height: int")
    lines.append("    is_ghost: bool  # True for ghost entities")
    lines.append(
        "    ghost_name: Optional[str]  # Entity type this ghost represents (if is_ghost)"
    )
    lines.append("    ")
    lines.append("    def inspect(self) -> InspectionData:")
    lines.append('        """Get current state. Returns static data for ghosts."""')
    lines.append("        ...")
    lines.append("    ")
    lines.append("    def pickup(self) -> List[ItemStack]:")
    lines.append('        """Remove entity and get its contents. Error for ghosts."""')
    lines.append("        ...")
    lines.append("    ")
    lines.append("    def build(self) -> ActionResult:")
    lines.append(
        '        """Build ghost into real entity (ghosts only, requires reachability)."""'
    )
    lines.append("        ...")
    lines.append("    ")
    lines.append("    def remove(self) -> bool:")
    lines.append('        """Remove ghost entity (ghosts only)."""')
    lines.append("        ...")
    lines.append("")
    lines.append("")

    # Entity types with their inspection data
    lines.append("# --- Furnace ---")
    lines.append("")
    lines.append("class Furnace(Entity):")
    lines.append('    """Smelts ore into plates."""')
    lines.append(
        "    def add_fuel(self, items: List[ItemStack]) -> List[ItemStack]: ..."
    )
    lines.append(
        "    def add_ingredients(self, items: List[ItemStack]) -> List[ItemStack]: ..."
    )
    lines.append("    def take_products(self) -> List[ItemStack]: ...")
    lines.append("    def inspect(self) -> FurnaceInspection: ...")
    lines.append("")
    lines.append("")
    lines.append("@dataclass")
    lines.append("class FurnaceInspection:")
    lines.append('    """Furnace inspection result."""')
    lines.append("    entity_name: str")
    lines.append("    position: MapPosition")
    lines.append("    status: Optional[str]")
    lines.append("    recipe: Optional[str]")
    lines.append("    crafting_progress: Optional[float]  # 0.0 to 1.0")
    lines.append("    is_crafting: Optional[bool]")
    lines.append("    input: Optional[Dict[str, int]]   # item_name -> count")
    lines.append("    output: Optional[Dict[str, int]]  # item_name -> count")
    lines.append("    fuel: Optional[Dict[str, int]]    # item_name -> count")
    lines.append("    burner: Optional[BurnerData]")
    lines.append("    ")
    lines.append("    # Helper properties")
    lines.append("    needs_fuel: bool       # True if needs fuel")
    lines.append("    has_input: bool        # True if has input materials")
    lines.append("    has_output: bool       # True if has products to take")
    lines.append("    is_idle: bool          # True if not crafting")
    lines.append("")
    lines.append("")

    lines.append("# --- Mining Drill ---")
    lines.append("")
    lines.append("class BurnerMiningDrill(Entity):")
    lines.append('    """Mines ore, requires fuel."""')
    lines.append(
        "    def add_fuel(self, items: List[ItemStack]) -> List[ItemStack]: ..."
    )
    lines.append("    def take_products(self) -> List[ItemStack]: ...")
    lines.append("    def inspect(self) -> MiningDrillInspection: ...")
    lines.append("")
    lines.append("")
    lines.append("class ElectricMiningDrill(Entity):")
    lines.append('    """Mines ore, uses electricity."""')
    lines.append("    def take_products(self) -> List[ItemStack]: ...")
    lines.append("    def inspect(self) -> MiningDrillInspection: ...")
    lines.append("")
    lines.append("")
    lines.append("@dataclass")
    lines.append("class MiningDrillInspection:")
    lines.append('    """Mining drill inspection result."""')
    lines.append("    entity_name: str")
    lines.append("    position: MapPosition")
    lines.append("    status: Optional[str]")
    lines.append("    mining_target: Optional[MiningTargetData]")
    lines.append("    mining_progress: Optional[float]  # 0.0 to 1.0")
    lines.append("    output: Optional[Dict[str, int]]  # item_name -> count")
    lines.append("    burner: Optional[BurnerData]      # For burner drills")
    lines.append("    energy: Optional[EnergyData]      # For electric drills")
    lines.append("    ")
    lines.append("    # Helper properties")
    lines.append("    is_mining: bool        # True if actively mining")
    lines.append("    has_output: bool       # True if has items to take")
    lines.append("    needs_fuel: bool       # True if burner needs fuel")
    lines.append("    has_power: bool        # True if has power")
    lines.append("")
    lines.append("")

    lines.append("# --- Assembling Machine ---")
    lines.append("")
    lines.append("class AssemblingMachine(Entity):")
    lines.append('    """Crafts items from recipes."""')
    lines.append("    def set_recipe(self, recipe: str) -> None: ...")
    lines.append(
        "    def add_ingredients(self, items: List[ItemStack]) -> List[ItemStack]: ..."
    )
    lines.append("    def take_products(self) -> List[ItemStack]: ...")
    lines.append("    def inspect(self) -> AssemblerInspection: ...")
    lines.append("")
    lines.append("")
    lines.append("@dataclass")
    lines.append("class AssemblerInspection:")
    lines.append('    """Assembler inspection result."""')
    lines.append("    entity_name: str")
    lines.append("    position: MapPosition")
    lines.append("    status: Optional[str]")
    lines.append("    recipe: Optional[str]")
    lines.append("    crafting_progress: Optional[float]")
    lines.append("    is_crafting: Optional[bool]")
    lines.append("    input: Optional[Dict[str, int]]")
    lines.append("    output: Optional[Dict[str, int]]")
    lines.append("    modules: Optional[Dict[str, int]]")
    lines.append("    energy: Optional[EnergyData]")
    lines.append("    ")
    lines.append("    # Helper properties")
    lines.append("    has_recipe: bool")
    lines.append("    has_input: bool")
    lines.append("    has_output: bool")
    lines.append("    is_idle: bool")
    lines.append("    has_power: bool")
    lines.append("")
    lines.append("")

    lines.append("# --- Inserter ---")
    lines.append("")
    lines.append("class Inserter(Entity):")
    lines.append('    """Moves items between entities."""')
    lines.append("    def set_filter(self, item_name: str) -> None: ...")
    lines.append("    def inspect(self) -> InserterInspection: ...")
    lines.append("")
    lines.append("")
    lines.append("@dataclass")
    lines.append("class InserterInspection:")
    lines.append('    """Inserter inspection result."""')
    lines.append("    entity_name: str")
    lines.append("    position: MapPosition")
    lines.append("    status: Optional[str]")
    lines.append("    held_item: Optional[HeldItemData]")
    lines.append("    pickup_target: Optional[EntityRef]")
    lines.append("    drop_target: Optional[EntityRef]")
    lines.append("    filters: Optional[Dict[int, str]]  # slot -> item_name")
    lines.append("    burner: Optional[BurnerData]       # For burner inserter")
    lines.append("    ")
    lines.append("    # Helper properties")
    lines.append("    is_holding_item: bool")
    lines.append("    has_filters: bool")
    lines.append("    needs_fuel: bool")
    lines.append("")
    lines.append("")

    lines.append("# --- Container ---")
    lines.append("")
    lines.append("class Container(Entity):")
    lines.append('    """Stores items (chests)."""')
    lines.append("    def insert(self, items: List[ItemStack]) -> List[ItemStack]: ...")
    lines.append(
        "    def extract(self, item_name: str, count: int) -> List[ItemStack]: ..."
    )
    lines.append("    def inspect(self) -> ContainerInspection: ...")
    lines.append("")
    lines.append("")
    lines.append("@dataclass")
    lines.append("class ContainerInspection:")
    lines.append('    """Container inspection result."""')
    lines.append("    entity_name: str")
    lines.append("    position: MapPosition")
    lines.append("    status: Optional[str]")
    lines.append("    contents: Optional[Dict[str, int]]  # item_name -> count")
    lines.append("    ")
    lines.append("    # Helper properties")
    lines.append("    is_empty: bool")
    lines.append("    total_items: int")
    lines.append("    ")
    lines.append("    # Methods")
    lines.append("    def get_item_count(self, item_name: str) -> int: ...")
    lines.append("")
    lines.append("")

    lines.append("# --- Lab ---")
    lines.append("")
    lines.append("class Lab(Entity):")
    lines.append('    """Consumes science packs for research."""')
    lines.append("    def inspect(self) -> LabInspection: ...")
    lines.append("")
    lines.append("")
    lines.append("@dataclass")
    lines.append("class LabInspection:")
    lines.append('    """Lab inspection result."""')
    lines.append("    entity_name: str")
    lines.append("    position: MapPosition")
    lines.append("    status: Optional[str]")
    lines.append("    input: Optional[Dict[str, int]]    # science packs")
    lines.append("    current_research: Optional[str]")
    lines.append("    energy: Optional[EnergyData]")
    lines.append("    ")
    lines.append("    # Helper properties")
    lines.append("    is_researching: bool")
    lines.append("    has_science_packs: bool")
    lines.append("")
    lines.append("")

    # Shared data types
    lines.append(
        "# ============================================================================"
    )
    lines.append("# SHARED DATA TYPES")
    lines.append(
        "# ============================================================================"
    )
    lines.append("")

    lines.append("@dataclass")
    lines.append("class BurnerData:")
    lines.append('    """Burner component state."""')
    lines.append("    heat: Optional[float]")
    lines.append("    heat_capacity: Optional[float]")
    lines.append("    remaining_burning_fuel: Optional[float]")
    lines.append("    currently_burning: Optional[str]  # fuel item name")
    lines.append("    is_burning: bool  # property")
    lines.append("    heat_percentage: Optional[float]  # property (0-100)")
    lines.append("")
    lines.append("")

    lines.append("@dataclass")
    lines.append("class EnergyData:")
    lines.append('    """Electric energy buffer state."""')
    lines.append("    current: float")
    lines.append("    capacity: float")
    lines.append("    percentage: float  # property (0-100)")
    lines.append("    is_full: bool      # property")
    lines.append("    is_empty: bool     # property")
    lines.append("")
    lines.append("")

    lines.append("@dataclass")
    lines.append("class MiningTargetData:")
    lines.append('    """What a mining drill is extracting."""')
    lines.append("    name: str       # resource name (e.g. 'iron-ore')")
    lines.append("    type: str       # resource type")
    lines.append("    position: MapPosition")
    lines.append("    amount: int     # remaining amount")
    lines.append("")
    lines.append("")

    lines.append("@dataclass")
    lines.append("class HeldItemData:")
    lines.append('    """Item held by an inserter."""')
    lines.append("    name: str")
    lines.append("    count: int")
    lines.append("")
    lines.append("")

    lines.append("@dataclass")
    lines.append("class EntityRef:")
    lines.append('    """Reference to another entity."""')
    lines.append("    name: str")
    lines.append("    position: MapPosition")
    lines.append("")
    lines.append("")

    # Ghost planning
    lines.append(
        "# ============================================================================"
    )
    lines.append("# PLANNING WITH GHOSTS")
    lines.append(
        "# ============================================================================"
    )
    lines.append("")

    lines.append("@dataclass")
    lines.append("class TrackedGhost:")
    lines.append('    """A planned placement (Python tracking, not in-game)."""')
    lines.append("    name: str")
    lines.append("    position: MapPosition")
    lines.append("    label: Optional[str]  # for grouping")
    lines.append("")
    lines.append("")

    lines.append("class ghost_manager:")
    lines.append('    """Track planned entity placements (Python-only).')
    lines.append("    ")
    lines.append("    Note: For in-game ghosts, use reachable.get_ghosts() instead.")
    lines.append(
        "    Ghost entities from reachable have is_ghost=True and provide build()/remove()."
    )
    lines.append('    """')
    lines.append(
        "    def add_ghost(self, position: MapPosition, entity_name: str, label: Optional[str] = None) -> str: ..."
    )
    lines.append(
        "    def remove_ghost(self, position: MapPosition, entity_name: str) -> bool: ..."
    )
    lines.append("    def list_ghosts(self) -> List[TrackedGhost]: ...")
    lines.append(
        "    def get_ghosts(self, area: Optional[BoundingBox] = None, label: Optional[str] = None) -> List[TrackedGhost]: ..."
    )
    lines.append("    def can_build(self, inventory: List[ItemStack]) -> Dict: ...")
    lines.append("")
    lines.append("")

    lines.append("class ghost_builder:")
    lines.append('    """Build ghost entities (handles walking and placement).')
    lines.append("    ")
    lines.append("    This is the recommended way to build ghosts as it handles")
    lines.append("    movement orchestration automatically.")
    lines.append('    """')
    lines.append(
        "    async def build_ghosts(self, ghosts: List[Entity | TrackedGhost], count: int = 10, strict: bool = False) -> Dict: ..."
    )
    lines.append(
        "    async def build_ghost(self, ghost: Entity | TrackedGhost) -> bool: ..."
    )
    lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    print(generate_dsl_documentation())
