#!/usr/bin/env bun
/**
 * Area Estimator - Calculate tile area requirements from solver results
 *
 * Takes solver JSON output and calculates:
 * 1. Machine area (production buildings footprint)
 * 2. Ore area (mining drill coverage for raw resources)
 * 3. Total estimated factory area
 */

import type { SolverResult } from "./types";

// Entity dimensions (tile_width x tile_height) from Factorio prototype data
const ENTITY_DIMENSIONS: Record<string, [number, number]> = {
  // Assembling machines
  "assembling-machine-1": [3, 3],
  "assembling-machine-2": [3, 3],
  "assembling-machine-3": [3, 3],

  // Furnaces
  "stone-furnace": [2, 2],
  "steel-furnace": [2, 2],
  "electric-furnace": [3, 3],

  // Chemical processing
  "chemical-plant": [3, 3],
  "oil-refinery": [5, 5],
  "pumpjack": [3, 3],

  // Mining
  "electric-mining-drill": [3, 3],
  "burner-mining-drill": [2, 2],

  // Fluids
  "offshore-pump": [1, 1],
  pump: [1, 2],
  "storage-tank": [3, 3],
  pipe: [1, 1],
  "pipe-to-ground": [1, 1],

  // Power
  boiler: [3, 2],
  "steam-engine": [3, 5],
  "solar-panel": [3, 3],
  accumulator: [2, 2],

  // Electric poles
  "small-electric-pole": [1, 1],
  "medium-electric-pole": [1, 1],
  "big-electric-pole": [2, 2],
  substation: [2, 2],

  // Logistics
  "transport-belt": [1, 1],
  "fast-transport-belt": [1, 1],
  "express-transport-belt": [1, 1],
  inserter: [1, 1],
  "fast-inserter": [1, 1],
  "long-handed-inserter": [1, 1],
  "stack-inserter": [1, 1],
  "bulk-inserter": [1, 1],

  // Containers
  "wooden-chest": [1, 1],
  "iron-chest": [1, 1],
  "steel-chest": [1, 1],

  // Research
  lab: [3, 3],
};

// Mining drill coverage area (tiles covered by one drill for ore extraction)
// Electric mining drill has 5x5 mining area but 3x3 footprint
const MINING_DRILL_ORE_COVERAGE = 25; // tiles of ore per drill

// Ore types that require mining area
const ORE_ITEMS = new Set([
  "iron-ore",
  "copper-ore",
  "coal",
  "stone",
  "uranium-ore",
]);

// Fluid resources that require pumpjacks (oil fields)
const FLUID_RESOURCES = new Set(["crude-oil"]);

interface AreaEstimate {
  // Machine areas by type
  machineAreaByType: Record<string, number>;
  totalMachineArea: number;

  // Ore mining areas
  oreAreaByType: Record<string, number>;
  totalOreArea: number;

  // Oil field requirements
  oilFieldCount: number;

  // Combined total
  totalFactoryArea: number;

  // Breakdown
  breakdown: {
    machineArea: number;
    oreArea: number;
    spacing: number; // Estimated spacing between machines (~30%)
  };
}

function getEntityArea(entityType: string): number {
  const dims = ENTITY_DIMENSIONS[entityType];
  if (dims) {
    return dims[0] * dims[1];
  }
  // Default to 3x3 for unknown entities (conservative estimate)
  console.warn(`Unknown entity type: ${entityType}, assuming 3x3`);
  return 9;
}

export function estimateArea(result: SolverResult): AreaEstimate {
  const machineAreaByType: Record<string, number> = {};
  const oreAreaByType: Record<string, number> = {};

  // Calculate machine areas from roundedMachinesByType
  let totalMachineArea = 0;
  const machines = result.roundedMachinesByType || {};

  for (const [machineType, count] of Object.entries(machines)) {
    const area = getEntityArea(machineType) * count;
    machineAreaByType[machineType] = area;
    totalMachineArea += area;
  }

  // Calculate ore areas from steps (looking for ore mining steps)
  let totalOreArea = 0;
  let oilFieldCount = 0;

  for (const step of result.steps) {
    // Check if this step produces an ore (has no recipe inputs)
    if (ORE_ITEMS.has(step.item) && Object.keys(step.inputs).length === 0) {
      // This is a mining step - calculate ore tiles needed
      // Mining drills cover 25 ore tiles each
      const drillCount = Math.ceil(step.machineCount);
      const oreArea = drillCount * MINING_DRILL_ORE_COVERAGE;
      oreAreaByType[step.item] = oreArea;
      totalOreArea += oreArea;
    }

    // Check for crude oil
    if (FLUID_RESOURCES.has(step.item) && step.machineType === "pumpjack") {
      oilFieldCount = Math.ceil(step.machineCount);
    }
  }

  // Add spacing estimate (30% for belts, inserters, pipes, walking paths)
  const spacingMultiplier = 1.3;
  const machineAreaWithSpacing = Math.ceil(totalMachineArea * spacingMultiplier);

  // Total factory area (machines with spacing, ore patches are separate)
  const totalFactoryArea = machineAreaWithSpacing;

  return {
    machineAreaByType,
    totalMachineArea,
    oreAreaByType,
    totalOreArea,
    oilFieldCount,
    totalFactoryArea,
    breakdown: {
      machineArea: totalMachineArea,
      oreArea: totalOreArea,
      spacing: machineAreaWithSpacing - totalMachineArea,
    },
  };
}

// CLI usage - only run if this file is the entry point
if (import.meta.main) {
  const inputText = await Bun.stdin.text();

  if (!inputText.trim()) {
    console.error("Usage: cat solver_result.json | bun run src/area-estimator.ts");
    process.exit(1);
  }

  const result: SolverResult = JSON.parse(inputText);
  const estimate = estimateArea(result);

  console.log(JSON.stringify(estimate, null, 2));
}
