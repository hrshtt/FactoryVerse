import type { ProductionStep, SolverResult } from "./types";

/**
 * Parse a numeric value from FactorioLab CSV format
 * Handles formats like "=30", "=1/30", "=0.5", "30", "<0.1"
 */
function parseNumericValue(value: string): number {
  if (!value || value.trim() === "") return 0;

  let cleaned = value.trim();

  // Remove leading "=" if present
  if (cleaned.startsWith("=")) {
    cleaned = cleaned.substring(1);
  }

  // Handle "less than" format (e.g., "<0.1")
  if (cleaned.startsWith("<")) {
    cleaned = cleaned.substring(1);
  }

  // Handle fraction format (e.g., "1/30")
  if (cleaned.includes("/")) {
    const [num, denom] = cleaned.split("/").map(Number);
    return denom !== 0 ? num / denom : 0;
  }

  return parseFloat(cleaned) || 0;
}

/**
 * Parse input/output format like "electronic-circuit:1,plastic-bar:1,copper-cable:0.4"
 * Returns a map of item -> rate
 */
function parseItemRates(value: string): Record<string, number> {
  const result: Record<string, number> = {};
  if (!value || value.trim() === "") return result;

  // Remove surrounding quotes if present
  let cleaned = value.trim();
  if (cleaned.startsWith('"') && cleaned.endsWith('"')) {
    cleaned = cleaned.slice(1, -1);
  }

  const pairs = cleaned.split(",");
  for (const pair of pairs) {
    const colonIndex = pair.lastIndexOf(":");
    if (colonIndex > 0) {
      const item = pair.substring(0, colonIndex).trim();
      const rateStr = pair.substring(colonIndex + 1).trim();
      if (item) {
        result[item] = parseNumericValue(rateStr);
      }
    }
  }
  return result;
}

/**
 * Simple CSV parser that handles quoted fields
 */
function parseCsvLine(line: string): string[] {
  const result: string[] = [];
  let current = "";
  let inQuotes = false;

  for (let i = 0; i < line.length; i++) {
    const char = line[i];

    if (char === '"') {
      if (inQuotes && line[i + 1] === '"') {
        // Escaped quote
        current += '"';
        i++;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (char === "," && !inQuotes) {
      result.push(current);
      current = "";
    } else {
      current += char;
    }
  }
  result.push(current);

  return result;
}

/**
 * Parse CSV row into a ProductionStep
 */
function parseRow(
  headers: string[],
  row: string[]
): ProductionStep | null {
  const getValue = (name: string): string => {
    const idx = headers.indexOf(name);
    return idx >= 0 && idx < row.length ? row[idx] : "";
  };

  const item = getValue("Item");
  if (!item) return null;

  return {
    item,
    rate: parseNumericValue(getValue("Items")),
    recipe: getValue("Recipe") || item,
    machineCount: parseNumericValue(getValue("Machines")),
    machineType: getValue("Machine"),
    inputs: parseItemRates(getValue("Inputs")),
    outputs: parseItemRates(getValue("Outputs")),
    power: parseNumericValue(getValue("Power")),
    beltCount: parseNumericValue(getValue("Belts")),
    beltType: getValue("Belt"),
  };
}

/**
 * Parse FactorioLab CSV export into structured SolverResult
 *
 * CSV format:
 * Line 1: URL (quoted)
 * Line 2: Headers
 * Line 3+: Data rows
 */
export function parseCsv(
  csv: string,
  targetItem: string,
  targetRate: number
): SolverResult {
  const lines = csv.trim().split(/\r?\n/);

  if (lines.length < 3) {
    throw new Error(`Invalid CSV: expected at least 3 lines, got ${lines.length}`);
  }

  // Line 0 is the URL - skip it
  // Line 1 is headers
  const headers = parseCsvLine(lines[1]);

  // Lines 2+ are data
  const steps: ProductionStep[] = [];
  for (let i = 2; i < lines.length; i++) {
    const row = parseCsvLine(lines[i]);
    const step = parseRow(headers, row);
    if (step) {
      steps.push(step);
    }
  }

  // Calculate summaries
  const machinesByType: Record<string, number> = {};
  let totalPower = 0;
  const recipes: string[] = [];

  for (const step of steps) {
    if (step.machineType && step.machineCount > 0) {
      machinesByType[step.machineType] =
        (machinesByType[step.machineType] || 0) + step.machineCount;
    }
    totalPower += step.power;
    if (step.recipe && !recipes.includes(step.recipe)) {
      recipes.push(step.recipe);
    }
  }

  // Round up machine counts (you can't build 0.5 of a machine)
  const roundedMachinesByType: Record<string, number> = {};
  for (const [type, count] of Object.entries(machinesByType)) {
    roundedMachinesByType[type] = Math.ceil(count);
  }

  return {
    targetItem,
    targetRate,
    steps,
    machinesByType,
    roundedMachinesByType,
    totalPower,
    recipes,
    rawCsv: csv,
  };
}
