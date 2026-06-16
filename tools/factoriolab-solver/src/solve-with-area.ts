#!/usr/bin/env bun
/**
 * Combined Solver with Area Estimation
 *
 * Runs FactorioLab solver and adds area estimation to the output.
 *
 * Usage:
 *   echo '{"targetItem":"utility-science-pack","targetRate":16,"modId":"2.0"}' | bun run src/solve-with-area.ts
 */

import { solve, isError } from "./solver";
import { estimateArea } from "./area-estimator";
import type { SolverInput } from "./types";

async function main() {
  const inputText = await Bun.stdin.text();

  if (!inputText.trim()) {
    console.error(
      JSON.stringify({
        error: "No input provided",
        details: "Expected JSON input on stdin",
      })
    );
    process.exit(1);
  }

  let input: SolverInput;
  try {
    input = JSON.parse(inputText);
  } catch (e) {
    console.error(
      JSON.stringify({
        error: "Invalid JSON input",
        details: e instanceof Error ? e.message : String(e),
      })
    );
    process.exit(1);
  }

  // Run solver
  const result = await solve(input);

  if (isError(result)) {
    console.error(JSON.stringify(result, null, 2));
    process.exit(1);
  }

  // Add area estimation
  const areaEstimate = estimateArea(result);

  // Combine outputs
  const combined = {
    // Target info
    targetItem: result.targetItem,
    targetRate: result.targetRate,

    // Machine summary
    roundedMachinesByType: result.roundedMachinesByType,
    totalPower: result.totalPower,
    recipeCount: result.recipes.length,

    // Area estimates
    area: {
      machines: {
        byType: areaEstimate.machineAreaByType,
        total: areaEstimate.totalMachineArea,
        withSpacing: areaEstimate.totalFactoryArea,
      },
      ore: {
        byType: areaEstimate.oreAreaByType,
        total: areaEstimate.totalOreArea,
      },
      oilFields: areaEstimate.oilFieldCount,
      summary: {
        factoryFootprint: `${Math.ceil(Math.sqrt(areaEstimate.totalFactoryArea))}x${Math.ceil(Math.sqrt(areaEstimate.totalFactoryArea))} tiles (~${areaEstimate.totalFactoryArea} tiles²)`,
        orePatches: `${areaEstimate.totalOreArea} ore tiles needed`,
        oilFields: `${areaEstimate.oilFieldCount} pumpjacks`,
      },
    },

    // Full step details (optional, can be verbose)
    steps: result.steps,
    recipes: result.recipes,
  };

  console.log(JSON.stringify(combined, null, 2));
}

main().catch(console.error);
