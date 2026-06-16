"""
FactorioLab Solver - Python wrapper for the Bun-based FactorioLab automation.

This is an optional utility module for FactoryVerse that calculates minimum
factory requirements (machines, power, belts) for producing items at specified rates.

Usage:
    from tools.factoriolab_solver.python import FactorioLabSolver, SolverInput

    solver = FactorioLabSolver()
    result = solver.solve(SolverInput(
        target_item="advanced-circuit",
        target_rate=30,
        mod_id="2.0"
    ))

    print(f"Machines needed: {result.machines_by_type}")
    print(f"Total power: {result.total_power} kW")
"""

from .models import SolverInput, SolverResult, ProductionStep, SolverError
from .solver import FactorioLabSolver

__all__ = [
    "FactorioLabSolver",
    "SolverInput",
    "SolverResult",
    "ProductionStep",
    "SolverError",
]
