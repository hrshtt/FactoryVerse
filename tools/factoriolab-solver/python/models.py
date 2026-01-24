"""
Pydantic models for FactorioLab solver input/output.
"""

from typing import Optional
from pydantic import BaseModel, Field


class SolverInput(BaseModel):
    """Input parameters for the FactorioLab solver."""

    target_item: str = Field(
        ..., description="Item to produce (e.g., 'advanced-circuit')"
    )
    target_rate: float = Field(..., description="Production rate per minute", gt=0)
    mod_id: str = Field(
        default="2.0",
        description="Mod/game version ID: '2.0', 'spa' (Space Age), '1.1'",
    )
    preset: Optional[str] = Field(
        default=None, description="Optional preset for machine tier"
    )

    def to_json_input(self) -> dict:
        """Convert to JSON format expected by the Bun CLI."""
        result = {
            "targetItem": self.target_item,
            "targetRate": self.target_rate,
            "modId": self.mod_id,
        }
        if self.preset:
            result["preset"] = self.preset
        return result


class ProductionStep(BaseModel):
    """A single step in the production chain."""

    item: str = Field(..., description="Item being produced")
    rate: float = Field(..., description="Production rate (items/min)")
    recipe: str = Field(..., description="Recipe used")
    machine_count: float = Field(..., description="Number of machines required")
    machine_type: str = Field(
        ..., description="Type of machine (e.g., 'assembling-machine-1')"
    )
    inputs: dict[str, float] = Field(
        default_factory=dict, description="Input items required (item -> rate)"
    )
    outputs: dict[str, float] = Field(
        default_factory=dict, description="Output items produced (item -> rate)"
    )
    power: float = Field(default=0, description="Power consumption in kW")
    belt_count: float = Field(default=0, description="Belt count needed")
    belt_type: str = Field(default="", description="Belt type")


class SolverResult(BaseModel):
    """Complete solver result."""

    target_item: str = Field(..., description="Target item that was requested")
    target_rate: float = Field(..., description="Target rate that was requested")
    steps: list[ProductionStep] = Field(
        default_factory=list, description="All production steps in the chain"
    )
    machines_by_type: dict[str, float] = Field(
        default_factory=dict, description="Total machines by type (exact)"
    )
    rounded_machines_by_type: dict[str, int] = Field(
        default_factory=dict, description="Total machines by type (rounded up - what you'd build)"
    )
    total_power: float = Field(default=0, description="Total power consumption in kW")
    recipes: list[str] = Field(
        default_factory=list, description="All unique recipes used"
    )
    raw_csv: Optional[str] = Field(
        default=None, description="Raw CSV data (for debugging)"
    )

    @classmethod
    def from_json(cls, data: dict) -> "SolverResult":
        """Parse from JSON output of the Bun CLI."""
        steps = []
        for step_data in data.get("steps", []):
            steps.append(
                ProductionStep(
                    item=step_data.get("item", ""),
                    rate=step_data.get("rate", 0),
                    recipe=step_data.get("recipe", ""),
                    machine_count=step_data.get("machineCount", 0),
                    machine_type=step_data.get("machineType", ""),
                    inputs=step_data.get("inputs", {}),
                    outputs=step_data.get("outputs", {}),
                    power=step_data.get("power", 0),
                    belt_count=step_data.get("beltCount", 0),
                    belt_type=step_data.get("beltType", ""),
                )
            )

        return cls(
            target_item=data.get("targetItem", ""),
            target_rate=data.get("targetRate", 0),
            steps=steps,
            machines_by_type=data.get("machinesByType", {}),
            rounded_machines_by_type=data.get("roundedMachinesByType", {}),
            total_power=data.get("totalPower", 0),
            recipes=data.get("recipes", []),
            raw_csv=data.get("rawCsv"),
        )


class SolverError(BaseModel):
    """Error response from the solver."""

    error: str = Field(..., description="Error message")
    details: Optional[str] = Field(default=None, description="Additional details")
