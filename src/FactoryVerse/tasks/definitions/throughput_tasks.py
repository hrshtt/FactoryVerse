"""Throughput task definitions.

This module contains 24 throughput tasks ported from the Factorio Learning Environment.
Each task requires building an automated factory to produce a target item.

Task verification uses the formula:
    automation_produced = force_output - manual_crafted - manual_mined

All tasks use the LAB_STARTING_INVENTORY with all technologies researched.
"""

from ..base import TaskConfig, TaskType, VerificationCriteria
from .common import LAB_STARTING_INVENTORY

# Task key constants for easy importing
ADVANCED_CIRCUIT_THROUGHPUT = "advanced_circuit_throughput"
AUTOMATION_SCIENCE_PACK_THROUGHPUT = "automation_science_pack_throughput"
BATTERY_THROUGHPUT = "battery_throughput"
CHEMICAL_SCIENCE_PACK_THROUGHPUT = "chemical_science_pack_throughput"
CRUDE_OIL_THROUGHPUT = "crude_oil_throughput"
ELECTRONIC_CIRCUIT_THROUGHPUT = "electronic_circuit_throughput"
ENGINE_UNIT_THROUGHPUT = "engine_unit_throughput"
INSERTER_THROUGHPUT = "inserter_throughput"
IRON_GEAR_WHEEL_THROUGHPUT = "iron_gear_wheel_throughput"
IRON_ORE_THROUGHPUT = "iron_ore_throughput"
IRON_PLATE_THROUGHPUT = "iron_plate_throughput"
LOGISTICS_SCIENCE_PACK_THROUGHPUT = "logistics_science_pack_throughput"
LOW_DENSITY_STRUCTURE_THROUGHPUT = "low_density_structure_throughput"
MILITARY_SCIENCE_PACK_THROUGHPUT = "military_science_pack_throughput"
PETROLEUM_GAS_THROUGHPUT = "petroleum_gas_throughput"
PIERCING_ROUND_THROUGHPUT = "piercing_round_throughput"
PLASTIC_BAR_THROUGHPUT = "plastic_bar_throughput"
PROCESSING_UNIT_THROUGHPUT = "processing_unit_throughput"
PRODUCTION_SCIENCE_PACK_THROUGHPUT = "production_science_pack_throughput"
STEEL_PLATE_THROUGHPUT = "steel_plate_throughput"
STONE_WALL_THROUGHPUT = "stone_wall_throughput"
SULFURIC_ACID_THROUGHPUT = "sulfuric_acid_throughput"
SULFUR_THROUGHPUT = "sulfur_throughput"
UTILITY_SCIENCE_PACK_THROUGHPUT = "utility_science_pack_throughput"


def _make_throughput_task(
    task_key: str,
    target_item: str,
    quota: int,
    item_display_name: str | None = None,
) -> TaskConfig:
    """Helper to create a throughput task config.

    Args:
        task_key: Unique identifier for the task
        target_item: Factorio item name (e.g., "iron-plate")
        quota: Minimum automation-produced items required
        item_display_name: Optional display name for goal description

    Returns:
        TaskConfig for the throughput task
    """
    display_name = item_display_name or target_item
    return TaskConfig(
        task_key=task_key,
        task_type=TaskType.THROUGHPUT,
        goal_description=(
            f"Build an automated factory that produces at least {quota} {display_name} "
            f"via automation (not hand-crafting). Items produced by machines like "
            f"assembling machines, furnaces, and chemical plants count as automation."
        ),
        verification=VerificationCriteria(
            target_item=target_item,
            min_automation_produced=quota,
        ),
        starting_inventory=LAB_STARTING_INVENTORY,
        all_technologies_researched=True,
        max_trajectory_steps=64,
    )


# =============================================================================
# Circuit Tasks
# =============================================================================

advanced_circuit_throughput = _make_throughput_task(
    task_key=ADVANCED_CIRCUIT_THROUGHPUT,
    target_item="advanced-circuit",
    quota=16,
)

electronic_circuit_throughput = _make_throughput_task(
    task_key=ELECTRONIC_CIRCUIT_THROUGHPUT,
    target_item="electronic-circuit",
    quota=16,
)

processing_unit_throughput = _make_throughput_task(
    task_key=PROCESSING_UNIT_THROUGHPUT,
    target_item="processing-unit",
    quota=16,
)

# =============================================================================
# Science Pack Tasks
# =============================================================================

automation_science_pack_throughput = _make_throughput_task(
    task_key=AUTOMATION_SCIENCE_PACK_THROUGHPUT,
    target_item="automation-science-pack",
    quota=16,
)

logistics_science_pack_throughput = _make_throughput_task(
    task_key=LOGISTICS_SCIENCE_PACK_THROUGHPUT,
    target_item="logistic-science-pack",
    quota=16,
)

chemical_science_pack_throughput = _make_throughput_task(
    task_key=CHEMICAL_SCIENCE_PACK_THROUGHPUT,
    target_item="chemical-science-pack",
    quota=16,
)

military_science_pack_throughput = _make_throughput_task(
    task_key=MILITARY_SCIENCE_PACK_THROUGHPUT,
    target_item="military-science-pack",
    quota=16,
)

production_science_pack_throughput = _make_throughput_task(
    task_key=PRODUCTION_SCIENCE_PACK_THROUGHPUT,
    target_item="production-science-pack",
    quota=16,
)

utility_science_pack_throughput = _make_throughput_task(
    task_key=UTILITY_SCIENCE_PACK_THROUGHPUT,
    target_item="utility-science-pack",
    quota=16,
)

# =============================================================================
# Material and Component Tasks
# =============================================================================

battery_throughput = _make_throughput_task(
    task_key=BATTERY_THROUGHPUT,
    target_item="battery",
    quota=16,
)

engine_unit_throughput = _make_throughput_task(
    task_key=ENGINE_UNIT_THROUGHPUT,
    target_item="engine-unit",
    quota=16,
)

inserter_throughput = _make_throughput_task(
    task_key=INSERTER_THROUGHPUT,
    target_item="inserter",
    quota=16,
)

iron_gear_wheel_throughput = _make_throughput_task(
    task_key=IRON_GEAR_WHEEL_THROUGHPUT,
    target_item="iron-gear-wheel",
    quota=16,
)

low_density_structure_throughput = _make_throughput_task(
    task_key=LOW_DENSITY_STRUCTURE_THROUGHPUT,
    target_item="low-density-structure",
    quota=16,
)

# =============================================================================
# Raw Material and Plate Tasks
# =============================================================================

iron_ore_throughput = _make_throughput_task(
    task_key=IRON_ORE_THROUGHPUT,
    target_item="iron-ore",
    quota=16,
)

iron_plate_throughput = _make_throughput_task(
    task_key=IRON_PLATE_THROUGHPUT,
    target_item="iron-plate",
    quota=16,
)

steel_plate_throughput = _make_throughput_task(
    task_key=STEEL_PLATE_THROUGHPUT,
    target_item="steel-plate",
    quota=16,
)

plastic_bar_throughput = _make_throughput_task(
    task_key=PLASTIC_BAR_THROUGHPUT,
    target_item="plastic-bar",
    quota=16,
)

# =============================================================================
# Oil and Chemical Tasks
# =============================================================================

crude_oil_throughput = _make_throughput_task(
    task_key=CRUDE_OIL_THROUGHPUT,
    target_item="crude-oil",
    quota=250,
)

petroleum_gas_throughput = _make_throughput_task(
    task_key=PETROLEUM_GAS_THROUGHPUT,
    target_item="petroleum-gas",
    quota=250,
)

sulfuric_acid_throughput = _make_throughput_task(
    task_key=SULFURIC_ACID_THROUGHPUT,
    target_item="sulfuric-acid",
    quota=250,
)

sulfur_throughput = _make_throughput_task(
    task_key=SULFUR_THROUGHPUT,
    target_item="sulfur",
    quota=16,
)

# =============================================================================
# Military Tasks
# =============================================================================

piercing_round_throughput = _make_throughput_task(
    task_key=PIERCING_ROUND_THROUGHPUT,
    target_item="piercing-rounds-magazine",
    quota=16,
    item_display_name="piercing rounds magazine",
)

stone_wall_throughput = _make_throughput_task(
    task_key=STONE_WALL_THROUGHPUT,
    target_item="stone-wall",
    quota=16,
)


# =============================================================================
# Task Collection
# =============================================================================

THROUGHPUT_TASKS: dict[str, TaskConfig] = {
    # Circuits
    ADVANCED_CIRCUIT_THROUGHPUT: advanced_circuit_throughput,
    ELECTRONIC_CIRCUIT_THROUGHPUT: electronic_circuit_throughput,
    PROCESSING_UNIT_THROUGHPUT: processing_unit_throughput,
    # Science packs
    AUTOMATION_SCIENCE_PACK_THROUGHPUT: automation_science_pack_throughput,
    LOGISTICS_SCIENCE_PACK_THROUGHPUT: logistics_science_pack_throughput,
    CHEMICAL_SCIENCE_PACK_THROUGHPUT: chemical_science_pack_throughput,
    MILITARY_SCIENCE_PACK_THROUGHPUT: military_science_pack_throughput,
    PRODUCTION_SCIENCE_PACK_THROUGHPUT: production_science_pack_throughput,
    UTILITY_SCIENCE_PACK_THROUGHPUT: utility_science_pack_throughput,
    # Materials
    BATTERY_THROUGHPUT: battery_throughput,
    ENGINE_UNIT_THROUGHPUT: engine_unit_throughput,
    INSERTER_THROUGHPUT: inserter_throughput,
    IRON_GEAR_WHEEL_THROUGHPUT: iron_gear_wheel_throughput,
    LOW_DENSITY_STRUCTURE_THROUGHPUT: low_density_structure_throughput,
    # Raw materials and plates
    IRON_ORE_THROUGHPUT: iron_ore_throughput,
    IRON_PLATE_THROUGHPUT: iron_plate_throughput,
    STEEL_PLATE_THROUGHPUT: steel_plate_throughput,
    PLASTIC_BAR_THROUGHPUT: plastic_bar_throughput,
    # Oil and chemicals
    CRUDE_OIL_THROUGHPUT: crude_oil_throughput,
    PETROLEUM_GAS_THROUGHPUT: petroleum_gas_throughput,
    SULFURIC_ACID_THROUGHPUT: sulfuric_acid_throughput,
    SULFUR_THROUGHPUT: sulfur_throughput,
    # Military
    PIERCING_ROUND_THROUGHPUT: piercing_round_throughput,
    STONE_WALL_THROUGHPUT: stone_wall_throughput,
}


def get_throughput_task(task_key: str) -> TaskConfig:
    """Get a throughput task by key.

    Args:
        task_key: Task identifier

    Returns:
        TaskConfig for the task

    Raises:
        KeyError: If task doesn't exist
    """
    if task_key not in THROUGHPUT_TASKS:
        raise KeyError(f"Unknown throughput task: {task_key}")
    return THROUGHPUT_TASKS[task_key]


def list_throughput_tasks() -> list[str]:
    """Get list of all throughput task keys."""
    return list(THROUGHPUT_TASKS.keys())
