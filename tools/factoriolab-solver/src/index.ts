#!/usr/bin/env bun
/**
 * FactorioLab Solver CLI
 *
 * Reads JSON input from stdin, outputs JSON result to stdout.
 *
 * Usage:
 *   echo '{"targetItem":"advanced-circuit","targetRate":30,"modId":"2.0"}' | bun run src/index.ts
 *
 * Input format (SolverInput):
 *   {
 *     "targetItem": "advanced-circuit",  // Item to produce
 *     "targetRate": 30,                  // Production rate per minute
 *     "modId": "2.0",                    // Game version: "2.0", "spa", "1.1"
 *     "preset": "minimum"                // Optional: machine preset
 *   }
 *
 * Output format (SolverResult or SolverError):
 *   {
 *     "targetItem": "advanced-circuit",
 *     "targetRate": 30,
 *     "steps": [...],
 *     "machinesByType": {"assembling-machine-1": 6, ...},
 *     "totalPower": 465,
 *     "recipes": ["advanced-circuit", "electronic-circuit", ...]
 *   }
 *
 * Or on error:
 *   {
 *     "error": "Error message",
 *     "details": "Additional details"
 *   }
 */

import { solve, isError } from "./solver";
import type { SolverInput } from "./types";

async function main() {
  try {
    // Read input from stdin
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

    // Parse input
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

    // Validate required fields
    if (!input.targetItem || typeof input.targetItem !== "string") {
      console.error(
        JSON.stringify({
          error: "Missing or invalid targetItem",
          details: "targetItem must be a non-empty string",
        })
      );
      process.exit(1);
    }

    if (!input.targetRate || typeof input.targetRate !== "number") {
      console.error(
        JSON.stringify({
          error: "Missing or invalid targetRate",
          details: "targetRate must be a positive number",
        })
      );
      process.exit(1);
    }

    if (!input.modId || typeof input.modId !== "string") {
      console.error(
        JSON.stringify({
          error: "Missing or invalid modId",
          details: 'modId must be a string like "2.0", "spa", or "1.1"',
        })
      );
      process.exit(1);
    }

    // Run solver
    const result = await solve(input);

    // Output result
    console.log(JSON.stringify(result, null, 2));

    // Exit with error code if solver failed
    if (isError(result)) {
      process.exit(1);
    }
  } catch (error) {
    console.error(
      JSON.stringify({
        error: "Unexpected error",
        details: error instanceof Error ? error.message : String(error),
      })
    );
    process.exit(1);
  }
}

main();
