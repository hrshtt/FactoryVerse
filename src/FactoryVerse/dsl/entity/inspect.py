"""Inspection data types for all entity categories.

This module defines typed dataclasses that mirror the Lua inspection.lua output.
Each entity category has its own inspection dataclass with:
- Typed fields matching Lua output
- Helper properties for LLM decision-making
- Clean __str__ for readable output

**For Agents**: When you call entity.inspect(), you get a typed dataclass.
Access fields directly (e.g., furnace_data.recipe) or print for formatted output.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any
from FactoryVerse.dsl.types import MapPosition


# =============================================================================
# SHARED COMPONENT TYPES
# =============================================================================


@dataclass
class EntityRef:
    """Reference to another entity.

    **For Agents**: Identifies an entity by name and position.
    """

    name: str
    position: MapPosition

    def __str__(self) -> str:
        return f"{self.name} @ ({self.position.x:.1f}, {self.position.y:.1f})"


@dataclass
class BurnerData:
    """Burner component state.

    **For Agents**: Check burner status, fuel levels, and heat.
    """

    heat: Optional[float] = None
    heat_capacity: Optional[float] = None
    remaining_burning_fuel: Optional[float] = None
    currently_burning: Optional[str] = None

    @property
    def is_burning(self) -> bool:
        """Check if burner is actively burning fuel."""
        return self.currently_burning is not None

    @property
    def heat_percentage(self) -> Optional[float]:
        """Heat as percentage (0-100)."""
        if self.heat is None or self.heat_capacity is None:
            return None
        if self.heat_capacity == 0:
            return 0.0
        return (self.heat / self.heat_capacity) * 100

    def __str__(self) -> str:
        lines = []
        if self.currently_burning:
            lines.append(f"Burning: {self.currently_burning}")
            if self.remaining_burning_fuel:
                lines.append(f"  Remaining: {self.remaining_burning_fuel:.0f} J")
        else:
            lines.append("Burning: (none)")

        if self.heat is not None and self.heat_capacity:
            pct = self.heat_percentage or 0
            lines.append(
                f"  Heat: {self.heat:.0f}/{self.heat_capacity:.0f} ({pct:.1f}%)"
            )

        return "\n".join(lines)


@dataclass
class EnergyData:
    """Electric energy state.

    **For Agents**: Check energy buffer levels.
    """

    current: float
    capacity: float

    @property
    def percentage(self) -> float:
        """Energy as percentage (0-100)."""
        if self.capacity == 0:
            return 0.0
        return (self.current / self.capacity) * 100

    @property
    def is_full(self) -> bool:
        """Check if energy buffer is full."""
        return self.current >= self.capacity

    @property
    def is_empty(self) -> bool:
        """Check if energy buffer is empty."""
        return self.current <= 0

    def __str__(self) -> str:
        return f"{self.current:.0f}/{self.capacity:.0f} ({self.percentage:.1f}%)"


@dataclass
class BoundingBoxData:
    """Bounding box structure.

    **For Agents**: Defines a rectangular area.
    """

    left_top: MapPosition
    right_bottom: MapPosition

    def __str__(self) -> str:
        return f"[({self.left_top.x:.1f}, {self.left_top.y:.1f}) to ({self.right_bottom.x:.1f}, {self.right_bottom.y:.1f})]"


@dataclass
class FluidBoxData:
    """Fluid box contents.

    **For Agents**: Check fluid type, amount, and temperature.
    """

    name: str
    amount: float
    temperature: float

    def __str__(self) -> str:
        return f"{self.name}: {self.amount:.1f} @ {self.temperature:.1f}°"


@dataclass
class HeldItemData:
    """Item held by an inserter.

    **For Agents**: Check what item the inserter is currently holding.
    """

    name: str
    count: int

    def __str__(self) -> str:
        return f"{self.name} x{self.count}"


@dataclass
class MiningTargetData:
    """Mining target information.

    **For Agents**: Check what resource a mining drill is extracting.
    """

    name: str
    type: str
    position: MapPosition
    amount: int

    def __str__(self) -> str:
        return f"{self.name} ({self.type}) at ({self.position.x:.1f}, {self.position.y:.1f}), amount: {self.amount}"


# =============================================================================
# BASE INSPECTION DATA
# =============================================================================


@dataclass
class BaseInspectionData:
    """Base inspection data present on all entities.

    **For Agents**: Every entity inspection includes these base fields.
    """

    entity_name: str
    entity_type: str
    position: MapPosition
    direction: int
    tick: int
    health: Optional[float] = None
    max_health: Optional[float] = None
    status: Optional[str] = None

    @property
    def health_percentage(self) -> Optional[float]:
        """Health as percentage (0-100)."""
        if self.health is None or self.max_health is None:
            return None
        if self.max_health == 0:
            return 0.0
        return (self.health / self.max_health) * 100

    @property
    def is_damaged(self) -> bool:
        """Check if entity is damaged."""
        if self.health is None or self.max_health is None:
            return False
        return self.health < self.max_health

    def __str__(self) -> str:
        """Default formatting for base inspection."""
        lines = [
            f"{self.entity_type}({self.entity_name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]
        if self.status:
            lines.append(f"  Status: {self.status}")
        if self.health is not None:
            health_pct = self.health_percentage or 0
            lines.append(
                f"  Health: {self.health:.0f}/{self.max_health:.0f} ({health_pct:.1f}%)"
            )
        return "\n".join(lines)


# =============================================================================
# CRAFTING MACHINE INSPECTIONS
# =============================================================================


@dataclass
class FurnaceInspection(BaseInspectionData):
    """Furnace inspection data.

    **For Agents**: Use this to check furnace state, recipe, progress, and inventories.
    Access properties directly or print for formatted output.

    Lua Source: inspect_crafting_machine() for entity.type == "furnace"
    """

    recipe: Optional[str] = None
    crafting_progress: Optional[float] = None
    bonus_progress: Optional[float] = None
    is_crafting: Optional[bool] = None
    input: Optional[Dict[str, int]] = None
    output: Optional[Dict[str, int]] = None
    fuel: Optional[Dict[str, int]] = None
    energy: Optional[EnergyData] = None
    beacons_count: Optional[int] = None
    burner: Optional[BurnerData] = None
    previous_recipe: Optional[str] = None

    @property
    def needs_fuel(self) -> bool:
        """Check if furnace needs fuel.

        **For Agents**: Use this to determine if you should add fuel.
        """
        if self.burner is None:
            return False
        return (
            not self.burner.is_burning
            and (self.burner.remaining_burning_fuel or 0) == 0
        )

    @property
    def has_input(self) -> bool:
        """Check if furnace has input materials."""
        return self.input is not None and len(self.input) > 0

    @property
    def has_output(self) -> bool:
        """Check if furnace has output products.

        **For Agents**: Use this to determine if you should take products.
        """
        return self.output is not None and len(self.output) > 0

    @property
    def is_idle(self) -> bool:
        """Check if furnace is idle (no recipe or not crafting).

        **For Agents**: Idle furnaces can be given new recipes.
        """
        return self.recipe is None or (self.is_crafting is False)

    def __str__(self) -> str:
        """Format furnace inspection for human readability."""
        lines = [
            f"Furnace({self.entity_name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]

        lines.append(f"  Status: {self.status or 'unknown'}")

        if self.recipe:
            lines.append(f"  Recipe: {self.recipe}")
            if self.crafting_progress is not None:
                lines.append(f"  Progress: {self.crafting_progress * 100:.1f}%")
        else:
            lines.append("  Recipe: (none)")

        if self.burner:
            burner_lines = str(self.burner).split("\n")
            for line in burner_lines:
                lines.append(f"  {line}")

        if self.fuel:
            fuel_str = ", ".join(
                [f"{name}: {count}" for name, count in self.fuel.items()]
            )
            lines.append(f"  Fuel: {fuel_str}")
        else:
            lines.append("  Fuel: (empty)")

        if self.input:
            input_str = ", ".join(
                [f"{name}: {count}" for name, count in self.input.items()]
            )
            lines.append(f"  Input: {input_str}")
        else:
            lines.append("  Input: (empty)")

        if self.output:
            output_str = ", ".join(
                [f"{name}: {count}" for name, count in self.output.items()]
            )
            lines.append(f"  Output: {output_str}")
        else:
            lines.append("  Output: (empty)")

        return "\n".join(lines)


@dataclass
class AssemblerInspection(BaseInspectionData):
    """Assembling machine inspection data.

    **For Agents**: Use this to check assembler state, recipe, progress, and inventories.

    Lua Source: inspect_crafting_machine() for entity.type == "assembling-machine"
    """

    recipe: Optional[str] = None
    crafting_progress: Optional[float] = None
    bonus_progress: Optional[float] = None
    is_crafting: Optional[bool] = None
    input: Optional[Dict[str, int]] = None
    output: Optional[Dict[str, int]] = None
    modules: Optional[Dict[str, int]] = None
    energy: Optional[EnergyData] = None
    beacons_count: Optional[int] = None

    @property
    def has_recipe(self) -> bool:
        """Check if assembler has a recipe set."""
        return self.recipe is not None

    @property
    def has_input(self) -> bool:
        """Check if assembler has input materials."""
        return self.input is not None and len(self.input) > 0

    @property
    def has_output(self) -> bool:
        """Check if assembler has output products."""
        return self.output is not None and len(self.output) > 0

    @property
    def is_idle(self) -> bool:
        """Check if assembler is idle."""
        return self.recipe is None or (self.is_crafting is False)

    @property
    def has_power(self) -> bool:
        """Check if assembler has power."""
        if self.energy is None:
            return False
        return self.energy.current > 0

    def __str__(self) -> str:
        lines = [
            f"Assembler({self.entity_name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]

        lines.append(f"  Status: {self.status or 'unknown'}")

        if self.recipe:
            lines.append(f"  Recipe: {self.recipe}")
            if self.crafting_progress is not None:
                lines.append(f"  Progress: {self.crafting_progress * 100:.1f}%")
        else:
            lines.append("  Recipe: (none)")

        if self.energy:
            lines.append(f"  Energy: {self.energy}")

        if self.input:
            input_str = ", ".join(
                [f"{name}: {count}" for name, count in self.input.items()]
            )
            lines.append(f"  Input: {input_str}")

        if self.output:
            output_str = ", ".join(
                [f"{name}: {count}" for name, count in self.output.items()]
            )
            lines.append(f"  Output: {output_str}")

        if self.modules:
            mod_str = ", ".join(
                [f"{name}: {count}" for name, count in self.modules.items()]
            )
            lines.append(f"  Modules: {mod_str}")

        return "\n".join(lines)


@dataclass
class ChemicalPlantInspection(AssemblerInspection):
    """Chemical plant inspection data.

    **For Agents**: Same structure as Assembler, handles fluid recipes.

    Lua Source: inspect_crafting_machine() for entity.type == "chemical-plant"
    """

    pass


@dataclass
class OilRefineryInspection(AssemblerInspection):
    """Oil refinery inspection data.

    **For Agents**: Same structure as Assembler, handles oil processing.

    Lua Source: inspect_crafting_machine() for entity.type == "oil-refinery"
    """

    pass


@dataclass
class RocketSiloInspection(AssemblerInspection):
    """Rocket silo inspection data.

    **For Agents**: Includes rocket parts and silo status.

    Lua Source: inspect_crafting_machine() for entity.type == "rocket-silo"
    """

    rocket_parts: Optional[int] = None
    rocket_silo_status: Optional[str] = None

    @property
    def is_ready_to_launch(self) -> bool:
        """Check if rocket is ready to launch."""
        return self.rocket_silo_status == "rocket-ready"

    def __str__(self) -> str:
        base = super().__str__()
        lines = base.split("\n")
        if self.rocket_parts is not None:
            lines.append(f"  Rocket Parts: {self.rocket_parts}/100")
        if self.rocket_silo_status:
            lines.append(f"  Silo Status: {self.rocket_silo_status}")
        return "\n".join(lines)


# =============================================================================
# MINING DRILL INSPECTIONS
# =============================================================================


@dataclass
class MiningDrillInspection(BaseInspectionData):
    """Mining drill inspection data.

    **For Agents**: Use this to check what the drill is mining and its output.

    Lua Source: inspect_mining_drill()
    """

    mining_target: Optional[MiningTargetData] = None
    mining_progress: Optional[float] = None
    bonus_mining_progress: Optional[float] = None
    output: Optional[Dict[str, int]] = None
    drop_position: Optional[MapPosition] = None
    drop_target: Optional[EntityRef] = None
    mining_area: Optional[BoundingBoxData] = None
    energy: Optional[EnergyData] = None
    burner: Optional[BurnerData] = None
    mining_drill_filter_mode: Optional[str] = None

    @property
    def is_mining(self) -> bool:
        """Check if drill is actively mining."""
        return self.mining_target is not None

    @property
    def has_output(self) -> bool:
        """Check if drill has items in output."""
        return self.output is not None and len(self.output) > 0

    @property
    def needs_fuel(self) -> bool:
        """Check if burner drill needs fuel."""
        if self.burner is None:
            return False
        return not self.burner.is_burning

    @property
    def has_power(self) -> bool:
        """Check if electric drill has power."""
        if self.energy is None:
            return self.burner is not None  # Burner drills don't need electric power
        return self.energy.current > 0

    def __str__(self) -> str:
        lines = [
            f"MiningDrill({self.entity_name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]

        lines.append(f"  Status: {self.status or 'unknown'}")

        if self.mining_target:
            lines.append(
                f"  Mining: {self.mining_target.name} (amount: {self.mining_target.amount})"
            )
            if self.mining_progress is not None:
                lines.append(f"  Progress: {self.mining_progress * 100:.1f}%")
        else:
            lines.append("  Mining: (no target)")

        if self.energy:
            lines.append(f"  Energy: {self.energy}")

        if self.burner:
            burner_lines = str(self.burner).split("\n")
            for line in burner_lines:
                lines.append(f"  {line}")

        if self.output:
            output_str = ", ".join(
                [f"{name}: {count}" for name, count in self.output.items()]
            )
            lines.append(f"  Output: {output_str}")

        if self.drop_target:
            lines.append(f"  Drop Target: {self.drop_target}")

        return "\n".join(lines)


# =============================================================================
# INSERTER INSPECTION
# =============================================================================


@dataclass
class InserterInspection(BaseInspectionData):
    """Inserter inspection data.

    **For Agents**: Use this to check inserter configuration and what it's holding.

    Lua Source: inspect_inserter()
    """

    held_item: Optional[HeldItemData] = None
    held_stack_position: Optional[MapPosition] = None
    pickup_position: Optional[MapPosition] = None
    drop_position: Optional[MapPosition] = None
    pickup_target: Optional[EntityRef] = None
    drop_target: Optional[EntityRef] = None
    inserter_filter_mode: Optional[str] = None
    filter_slot_count: Optional[int] = None
    filters: Optional[Dict[int, str]] = None
    inserter_stack_size_override: Optional[int] = None
    inserter_target_pickup_count: Optional[int] = None
    pickup_from_left_lane: Optional[bool] = None
    pickup_from_right_lane: Optional[bool] = None
    use_filters: Optional[bool] = None
    burner: Optional[BurnerData] = None  # For burner inserters

    @property
    def is_holding_item(self) -> bool:
        """Check if inserter is holding an item."""
        return self.held_item is not None

    @property
    def has_filters(self) -> bool:
        """Check if inserter has filters set."""
        return self.filters is not None and len(self.filters) > 0

    @property
    def needs_fuel(self) -> bool:
        """Check if burner inserter needs fuel."""
        if self.burner is None:
            return False
        return not self.burner.is_burning

    def __str__(self) -> str:
        lines = [
            f"Inserter({self.entity_name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]

        lines.append(f"  Status: {self.status or 'unknown'}")

        if self.held_item:
            lines.append(f"  Holding: {self.held_item}")
        else:
            lines.append("  Holding: (empty)")

        if self.pickup_target:
            lines.append(f"  Pickup from: {self.pickup_target}")
        if self.drop_target:
            lines.append(f"  Drop to: {self.drop_target}")

        if self.filters:
            filter_str = ", ".join([f"slot{k}: {v}" for k, v in self.filters.items()])
            lines.append(f"  Filters: {filter_str}")

        if self.burner:
            burner_lines = str(self.burner).split("\n")
            for line in burner_lines:
                lines.append(f"  {line}")

        return "\n".join(lines)


# =============================================================================
# CONTAINER INSPECTION
# =============================================================================


@dataclass
class ContainerInspection(BaseInspectionData):
    """Container inspection data.

    **For Agents**: Use this to check chest contents and configuration.

    Lua Source: inspect_container()
    """

    contents: Optional[Dict[str, int]] = None
    inventory_bar: Optional[int] = None
    inventory_size_override: Optional[int] = None
    # Logistic container specific
    storage_filter: Optional[str] = None
    filter_slot_count: Optional[int] = None
    filters: Optional[Dict[int, str]] = None
    request_from_buffers: Optional[bool] = None

    @property
    def is_empty(self) -> bool:
        """Check if container is empty."""
        return self.contents is None or len(self.contents) == 0

    @property
    def total_items(self) -> int:
        """Get total number of items in container."""
        if self.contents is None:
            return 0
        return sum(self.contents.values())

    def get_item_count(self, item_name: str) -> int:
        """Get count of a specific item."""
        if self.contents is None:
            return 0
        return self.contents.get(item_name, 0)

    def __str__(self) -> str:
        lines = [
            f"Container({self.entity_name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]

        lines.append(f"  Status: {self.status or 'unknown'}")

        if self.contents:
            content_str = ", ".join(
                [f"{name}: {count}" for name, count in self.contents.items()]
            )
            lines.append(f"  Contents: {content_str}")
            lines.append(f"  Total: {self.total_items} items")
        else:
            lines.append("  Contents: (empty)")

        if self.storage_filter:
            lines.append(f"  Storage Filter: {self.storage_filter}")

        if self.filters:
            filter_str = ", ".join([f"slot{k}: {v}" for k, v in self.filters.items()])
            lines.append(f"  Filters: {filter_str}")

        return "\n".join(lines)


# =============================================================================
# TRANSPORT BELT INSPECTION
# =============================================================================


@dataclass
class TransportBeltInspection(BaseInspectionData):
    """Transport belt inspection data.

    **For Agents**: Use this to check belt configuration and connections.

    Lua Source: inspect_transport_belt()
    """

    belt_shape: Optional[str] = None
    belt_neighbours: Optional[List[EntityRef]] = None
    linked_belt_neighbour: Optional[EntityRef] = None
    linked_belt_type: Optional[str] = None
    belt_to_ground_type: Optional[str] = None  # For underground belts
    splitter_filter: Optional[str] = None  # For splitters
    splitter_input_priority: Optional[str] = None
    splitter_output_priority: Optional[str] = None

    @property
    def is_underground(self) -> bool:
        """Check if this is an underground belt."""
        return self.belt_to_ground_type is not None

    @property
    def is_splitter(self) -> bool:
        """Check if this is a splitter."""
        return (
            self.splitter_input_priority is not None
            or self.splitter_output_priority is not None
        )

    def __str__(self) -> str:
        lines = [
            f"TransportBelt({self.entity_name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]

        lines.append(f"  Status: {self.status or 'unknown'}")

        if self.belt_shape:
            lines.append(f"  Shape: {self.belt_shape}")

        if self.belt_to_ground_type:
            lines.append(f"  Underground Type: {self.belt_to_ground_type}")

        if self.splitter_filter:
            lines.append(f"  Splitter Filter: {self.splitter_filter}")
        if self.splitter_input_priority:
            lines.append(f"  Input Priority: {self.splitter_input_priority}")
        if self.splitter_output_priority:
            lines.append(f"  Output Priority: {self.splitter_output_priority}")

        if self.belt_neighbours:
            for n in self.belt_neighbours:
                lines.append(f"  Neighbour: {n}")

        return "\n".join(lines)


# =============================================================================
# LAB INSPECTION
# =============================================================================


@dataclass
class LabInspection(BaseInspectionData):
    """Lab inspection data.

    **For Agents**: Use this to check lab status and research info.

    Lua Source: inspect_lab()
    """

    input: Optional[Dict[str, int]] = None
    modules: Optional[Dict[str, int]] = None
    current_research: Optional[str] = None
    productivity_bonus: Optional[float] = None
    speed_bonus: Optional[float] = None
    beacons_count: Optional[int] = None
    effects: Optional[Dict[str, Any]] = None
    energy: Optional[EnergyData] = None

    @property
    def is_researching(self) -> bool:
        """Check if lab is researching."""
        return self.current_research is not None

    @property
    def has_science_packs(self) -> bool:
        """Check if lab has science packs."""
        return self.input is not None and len(self.input) > 0

    def __str__(self) -> str:
        lines = [
            f"Lab({self.entity_name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]

        lines.append(f"  Status: {self.status or 'unknown'}")

        if self.current_research:
            lines.append(f"  Researching: {self.current_research}")
        else:
            lines.append("  Researching: (none)")

        if self.energy:
            lines.append(f"  Energy: {self.energy}")

        if self.input:
            input_str = ", ".join(
                [f"{name}: {count}" for name, count in self.input.items()]
            )
            lines.append(f"  Science Packs: {input_str}")

        if self.productivity_bonus:
            lines.append(f"  Productivity Bonus: +{self.productivity_bonus * 100:.1f}%")
        if self.speed_bonus:
            lines.append(f"  Speed Bonus: +{self.speed_bonus * 100:.1f}%")

        return "\n".join(lines)


# =============================================================================
# ENERGY PRODUCER INSPECTION
# =============================================================================


@dataclass
class EnergyProducerInspection(BaseInspectionData):
    """Energy producer inspection data (boilers, generators, solar panels, reactors).

    **For Agents**: Use this to check power generation status.

    Lua Source: inspect_energy_producer()
    """

    energy_generated_last_tick: Optional[float] = None
    power_production: Optional[float] = None
    burner: Optional[BurnerData] = None
    temperature: Optional[float] = None
    heat_neighbours: Optional[List[EntityRef]] = None
    neighbour_bonus: Optional[float] = None
    energy: Optional[EnergyData] = None

    @property
    def is_producing(self) -> bool:
        """Check if producing power."""
        if self.energy_generated_last_tick is not None:
            return self.energy_generated_last_tick > 0
        return False

    @property
    def needs_fuel(self) -> bool:
        """Check if burner-based producer needs fuel."""
        if self.burner is None:
            return False
        return not self.burner.is_burning

    def __str__(self) -> str:
        lines = [
            f"EnergyProducer({self.entity_name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]

        lines.append(f"  Status: {self.status or 'unknown'}")

        if self.energy_generated_last_tick is not None:
            lines.append(
                f"  Generated Last Tick: {self.energy_generated_last_tick:.0f} J"
            )

        if self.power_production is not None:
            lines.append(f"  Power Production: {self.power_production:.0f} W")

        if self.temperature is not None:
            lines.append(f"  Temperature: {self.temperature:.1f}°")

        if self.burner:
            burner_lines = str(self.burner).split("\n")
            for line in burner_lines:
                lines.append(f"  {line}")

        if self.energy:
            lines.append(f"  Energy Buffer: {self.energy}")

        if self.neighbour_bonus is not None:
            lines.append(f"  Neighbour Bonus: +{self.neighbour_bonus * 100:.1f}%")

        return "\n".join(lines)


# =============================================================================
# ELECTRIC POLE INSPECTION
# =============================================================================


@dataclass
class ElectricPoleInspection(BaseInspectionData):
    """Electric pole inspection data.

    **For Agents**: Use this to check network connectivity.

    Lua Source: inspect_electric_pole()
    """

    electric_network_id: Optional[int] = None
    is_connected: bool = False
    energy: Optional[EnergyData] = None

    def __str__(self) -> str:
        lines = [
            f"ElectricPole({self.entity_name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]

        lines.append(f"  Status: {self.status or 'unknown'}")
        lines.append(f"  Connected: {'yes' if self.is_connected else 'no'}")

        if self.electric_network_id is not None:
            lines.append(f"  Network ID: {self.electric_network_id}")

        return "\n".join(lines)


# =============================================================================
# BEACON INSPECTION
# =============================================================================


@dataclass
class BeaconInspection(BaseInspectionData):
    """Beacon inspection data.

    **For Agents**: Use this to check beacon modules and effect receivers.

    Lua Source: inspect_beacon()
    """

    modules: Optional[Dict[str, int]] = None
    effects: Optional[Dict[str, Any]] = None
    energy: Optional[EnergyData] = None
    effect_receivers: Optional[List[EntityRef]] = None

    @property
    def has_modules(self) -> bool:
        """Check if beacon has modules installed."""
        return self.modules is not None and len(self.modules) > 0

    def __str__(self) -> str:
        lines = [
            f"Beacon({self.entity_name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]

        lines.append(f"  Status: {self.status or 'unknown'}")

        if self.modules:
            mod_str = ", ".join(
                [f"{name}: {count}" for name, count in self.modules.items()]
            )
            lines.append(f"  Modules: {mod_str}")
        else:
            lines.append("  Modules: (empty)")

        if self.energy:
            lines.append(f"  Energy: {self.energy}")

        if self.effect_receivers:
            lines.append(f"  Affecting: {len(self.effect_receivers)} entities")

        return "\n".join(lines)


# =============================================================================
# PUMP INSPECTION
# =============================================================================


@dataclass
class PumpInspection(BaseInspectionData):
    """Pump inspection data.

    **For Agents**: Use this to check pump status and fluid handling.

    Lua Source: inspect_pump()
    """

    pumped_last_tick: Optional[float] = None
    pump_rail_target: Optional[EntityRef] = None
    fluidbox: Optional[List[FluidBoxData]] = None
    fluid_source_fluid: Optional[str] = None  # Offshore pump
    fluid_source_tile: Optional[MapPosition] = None  # Offshore pump

    @property
    def is_pumping(self) -> bool:
        """Check if pump is actively pumping."""
        return self.pumped_last_tick is not None and self.pumped_last_tick > 0

    def __str__(self) -> str:
        lines = [
            f"Pump({self.entity_name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]

        lines.append(f"  Status: {self.status or 'unknown'}")

        if self.pumped_last_tick is not None:
            lines.append(f"  Pumped Last Tick: {self.pumped_last_tick:.1f}")

        if self.fluidbox:
            for fb in self.fluidbox:
                lines.append(f"  Fluid: {fb}")

        if self.fluid_source_fluid:
            lines.append(f"  Source Fluid: {self.fluid_source_fluid}")

        return "\n".join(lines)


# =============================================================================
# RADAR INSPECTION
# =============================================================================


@dataclass
class RadarInspection(BaseInspectionData):
    """Radar inspection data.

    **For Agents**: Use this to check radar scan progress.

    Lua Source: inspect_radar()
    """

    radar_scan_progress: Optional[float] = None
    energy: Optional[EnergyData] = None

    def __str__(self) -> str:
        lines = [
            f"Radar({self.entity_name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]

        lines.append(f"  Status: {self.status or 'unknown'}")

        if self.radar_scan_progress is not None:
            lines.append(f"  Scan Progress: {self.radar_scan_progress * 100:.1f}%")

        if self.energy:
            lines.append(f"  Energy: {self.energy}")

        return "\n".join(lines)


# =============================================================================
# ACCUMULATOR INSPECTION
# =============================================================================


@dataclass
class AccumulatorInspection(BaseInspectionData):
    """Accumulator inspection data.

    **For Agents**: Use this to check accumulator charge level.

    Lua Source: inspect_accumulator()
    """

    energy: Optional[EnergyData] = None
    electric_network_id: Optional[int] = None

    @property
    def charge_percentage(self) -> float:
        """Get charge as percentage."""
        if self.energy is None:
            return 0.0
        return self.energy.percentage

    @property
    def is_full(self) -> bool:
        """Check if accumulator is fully charged."""
        if self.energy is None:
            return False
        return self.energy.is_full

    @property
    def is_empty(self) -> bool:
        """Check if accumulator is empty."""
        if self.energy is None:
            return True
        return self.energy.is_empty

    def __str__(self) -> str:
        lines = [
            f"Accumulator({self.entity_name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]

        lines.append(f"  Status: {self.status or 'unknown'}")

        if self.energy:
            lines.append(f"  Charge: {self.energy}")
        else:
            lines.append("  Charge: unknown")

        if self.electric_network_id is not None:
            lines.append(f"  Network ID: {self.electric_network_id}")

        return "\n".join(lines)


# =============================================================================
# RESOURCE ENTITY INSPECTION
# =============================================================================


@dataclass
class ResourceEntityInspection(BaseInspectionData):
    """Resource entity inspection data (ore patches).

    **For Agents**: Use this to check resource amount.

    Lua Source: inspect_resource_entity()
    """

    amount: Optional[int] = None
    initial_amount: Optional[int] = None

    @property
    def is_depleted(self) -> bool:
        """Check if resource is depleted."""
        return self.amount is not None and self.amount <= 0

    @property
    def depletion_percentage(self) -> Optional[float]:
        """Get depletion as percentage (0 = full, 100 = depleted)."""
        if self.amount is None or self.initial_amount is None:
            return None
        if self.initial_amount == 0:
            return 100.0
        return (1 - (self.amount / self.initial_amount)) * 100

    def __str__(self) -> str:
        lines = [
            f"Resource({self.entity_name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]

        if self.amount is not None:
            if self.initial_amount is not None:
                pct = self.depletion_percentage or 0
                lines.append(
                    f"  Amount: {self.amount}/{self.initial_amount} ({100 - pct:.1f}% remaining)"
                )
            else:
                lines.append(f"  Amount: {self.amount}")

        return "\n".join(lines)
