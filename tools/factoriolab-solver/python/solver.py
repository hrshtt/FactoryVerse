"""
Python wrapper for the FactorioLab solver.

Calls the Bun-based Playwright script via subprocess.
"""

import json
import subprocess
from pathlib import Path
from typing import Union

from .models import SolverInput, SolverResult, SolverError


class FactorioLabSolver:
    """
    Wrapper for the FactorioLab browser automation solver.

    This class calls the Bun-based Playwright script to automate FactorioLab
    and retrieve production calculations.

    Example:
        solver = FactorioLabSolver()
        result = solver.solve(SolverInput(
            target_item="advanced-circuit",
            target_rate=30,
            mod_id="2.0"
        ))

        if isinstance(result, SolverResult):
            print(f"Machines: {result.machines_by_type}")
            print(f"Power: {result.total_power} kW")
        else:
            print(f"Error: {result.error}")
    """

    def __init__(self, solver_path: Path | None = None, timeout: int = 60):
        """
        Initialize the solver.

        Args:
            solver_path: Path to the factoriolab-solver directory.
                        Defaults to the tools/factoriolab-solver directory.
            timeout: Subprocess timeout in seconds.
        """
        if solver_path is None:
            # Default to the tools/factoriolab-solver directory relative to this file
            self.solver_path = Path(__file__).parent.parent
        else:
            self.solver_path = solver_path

        self.timeout = timeout
        self._validated = False

    def _validate_setup(self) -> None:
        """Validate that Bun and dependencies are available."""
        if self._validated:
            return

        # Check that Bun is installed
        try:
            result = subprocess.run(
                ["bun", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                raise RuntimeError("Bun is not properly installed")
        except FileNotFoundError:
            raise RuntimeError(
                "Bun is not installed. Install it with: curl -fsSL https://bun.sh/install | bash"
            )

        # Check that package.json exists
        package_json = self.solver_path / "package.json"
        if not package_json.exists():
            raise RuntimeError(
                f"package.json not found at {package_json}. "
                f"Run 'bun install' in {self.solver_path}"
            )

        # Check if node_modules exists (dependencies installed)
        node_modules = self.solver_path / "node_modules"
        if not node_modules.exists():
            raise RuntimeError(
                f"Dependencies not installed. Run 'bun install' in {self.solver_path}"
            )

        self._validated = True

    def install_dependencies(self) -> None:
        """Install Bun dependencies for the solver."""
        result = subprocess.run(
            ["bun", "install"],
            cwd=self.solver_path,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to install dependencies: {result.stderr}")
        self._validated = False  # Re-validate after install

    def solve(self, input: SolverInput) -> Union[SolverResult, SolverError]:
        """
        Solve for production requirements.

        Args:
            input: Solver input parameters.

        Returns:
            SolverResult on success, SolverError on failure.
        """
        self._validate_setup()

        # Prepare input JSON
        input_json = json.dumps(input.to_json_input())

        # Run the Bun script
        try:
            result = subprocess.run(
                ["bun", "run", "src/index.ts"],
                input=input_json,
                capture_output=True,
                text=True,
                cwd=self.solver_path,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            return SolverError(
                error="Solver timed out",
                details=f"Solver did not complete within {self.timeout} seconds",
            )

        # Parse output
        if not result.stdout.strip():
            return SolverError(
                error="No output from solver",
                details=result.stderr or "Solver produced no output",
            )

        try:
            output = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            return SolverError(
                error="Invalid JSON output",
                details=f"Failed to parse solver output: {e}. Output: {result.stdout[:500]}",
            )

        # Check if it's an error response
        if "error" in output:
            return SolverError(
                error=output["error"],
                details=output.get("details"),
            )

        # Parse as success result
        return SolverResult.from_json(output)

    def solve_multiple(
        self, inputs: list[SolverInput]
    ) -> list[Union[SolverResult, SolverError]]:
        """
        Solve for multiple production targets.

        Args:
            inputs: List of solver input parameters.

        Returns:
            List of results (SolverResult or SolverError) for each input.
        """
        return [self.solve(input) for input in inputs]
