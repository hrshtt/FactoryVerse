# FactorioLab Solver

Browser automation tool that uses [FactorioLab](https://factoriolab.github.io/) to calculate minimum factory requirements for producing items at specified throughput rates.

## Overview

This is an **optional utility** for FactoryVerse that calculates:
- Number and type of machines needed
- Power consumption
- Belt requirements
- Complete recipe chains

It works by automating FactorioLab via Playwright and extracting the calculated results.

## Prerequisites

- [Bun](https://bun.sh/) runtime
- Google Chrome installed (uses system Chrome, no separate download needed)
- Internet connection (uses factoriolab.github.io)

## Installation

```bash
# Navigate to the solver directory
cd tools/factoriolab-solver

# Install dependencies
bun install
```

## Usage

### CLI (Bun)

```bash
# Pass JSON input via stdin
echo '{"targetItem":"advanced-circuit","targetRate":30,"modId":"2.0"}' | bun run src/index.ts
```

Input format:
```json
{
  "targetItem": "advanced-circuit",  // Item to produce
  "targetRate": 30,                  // Production rate per minute
  "modId": "2.0",                    // Game version: "2.0", "spa", "1.1"
  "preset": "minimum"                // Optional: machine preset
}
```

Output format:
```json
{
  "targetItem": "advanced-circuit",
  "targetRate": 30,
  "steps": [...],
  "machinesByType": {
    "assembling-machine-1": 6,
    "chemical-plant": 0.5
  },
  "totalPower": 465,
  "recipes": ["advanced-circuit", "electronic-circuit", "plastic-bar", ...]
}
```

### Python

```python
import sys
sys.path.insert(0, '/path/to/FactoryVerse/tools/factoriolab-solver')

from python import FactorioLabSolver, SolverInput, SolverResult

solver = FactorioLabSolver()
result = solver.solve(SolverInput(
    target_item="advanced-circuit",
    target_rate=30,
    mod_id="2.0"
))

if isinstance(result, SolverResult):
    print(f"Machines: {result.machines_by_type}")
    print(f"Power: {result.total_power} kW")
    print(f"Recipes: {result.recipes}")
else:
    print(f"Error: {result.error}")
```

## Supported Game Versions

| mod_id | Description |
|--------|-------------|
| `2.0`  | Factorio 2.0 (base game) |
| `spa`  | Space Age expansion |
| `1.1`  | Factorio 1.1 (legacy) |

## How It Works

1. Builds a FactorioLab URL with the target item and rate
2. Launches headless Chromium via Playwright
3. Navigates to FactorioLab and waits for calculation
4. Extracts production data from the rendered page
5. Returns structured JSON with machines, power, and recipe chain

## Limitations

- Requires internet connection
- Calculations take 1-3 seconds per request
- Depends on FactorioLab's UI structure (may break if site changes)
- No offline mode

## File Structure

```
tools/factoriolab-solver/
├── package.json          # Bun project config
├── src/
│   ├── index.ts          # CLI entry point
│   ├── solver.ts         # Playwright automation
│   ├── url-builder.ts    # URL construction
│   ├── csv-parser.ts     # Result parsing
│   └── types.ts          # TypeScript interfaces
├── python/
│   ├── __init__.py       # Python package
│   ├── models.py         # Pydantic models
│   └── solver.py         # Python wrapper
└── README.md
```

## Development

```bash
# Run tests
bun test

# Type check
bun run typecheck
```

## Integration with FactoryVerse

This tool is **optional** and not a core dependency. To use it from FactoryVerse:

```python
# Add to your script/notebook
from pathlib import Path
import sys

# Add the solver to path
solver_path = Path("/path/to/FactoryVerse/tools/factoriolab-solver")
sys.path.insert(0, str(solver_path))

from python import FactorioLabSolver, SolverInput

# Use for throughput evaluation tasks
solver = FactorioLabSolver(solver_path=solver_path)
```
