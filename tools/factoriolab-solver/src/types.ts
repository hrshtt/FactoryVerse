/**
 * Input parameters for the FactorioLab solver
 */
export interface SolverInput {
  /** Item to produce (e.g., "advanced-circuit") */
  targetItem: string;
  /** Production rate per minute */
  targetRate: number;
  /** Mod/game version ID: "2.0", "spa" (Space Age), "1.1" */
  modId: string;
  /** Optional preset for machine tier (defaults to FactorioLab's default) */
  preset?: string;
}

/**
 * A single step in the production chain
 */
export interface ProductionStep {
  /** Item being produced */
  item: string;
  /** Production rate (items/min) */
  rate: number;
  /** Recipe used */
  recipe: string;
  /** Number of machines required */
  machineCount: number;
  /** Type of machine (e.g., "assembling-machine-1") */
  machineType: string;
  /** Input items required (item -> rate) */
  inputs: Record<string, number>;
  /** Output items produced (item -> rate) */
  outputs: Record<string, number>;
  /** Power consumption in kW */
  power: number;
  /** Belt count needed */
  beltCount: number;
  /** Belt type */
  beltType: string;
}

/**
 * Complete solver result
 */
export interface SolverResult {
  /** Target item that was requested */
  targetItem: string;
  /** Target rate that was requested */
  targetRate: number;
  /** All production steps in the chain */
  steps: ProductionStep[];
  /** Summary: total machines by type (exact) */
  machinesByType: Record<string, number>;
  /** Summary: total machines by type (rounded up - what you'd actually build) */
  roundedMachinesByType: Record<string, number>;
  /** Summary: total power consumption in kW */
  totalPower: number;
  /** Summary: all unique recipes used */
  recipes: string[];
  /** Raw CSV data (for debugging) */
  rawCsv?: string;
}

/**
 * Error response
 */
export interface SolverError {
  error: string;
  details?: string;
}
