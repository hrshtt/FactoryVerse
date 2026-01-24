import type { SolverInput } from "./types";

const BASE_URL = "https://factoriolab.github.io";

/**
 * Build a FactorioLab URL for a given solver input
 *
 * URL format: https://factoriolab.github.io/{modId}/list?o={item}*{rate}&v=11
 *
 * Examples:
 * - https://factoriolab.github.io/2.0/list?o=advanced-circuit*30&v=11
 * - https://factoriolab.github.io/spa/list?o=rocket-part*1&v=11
 */
export function buildUrl(input: SolverInput): string {
  const { targetItem, targetRate, modId, preset } = input;

  // Base path with mod ID
  let url = `${BASE_URL}/${modId}/list`;

  // Build query parameters
  const params = new URLSearchParams();

  // Objective: item*rate (rate per minute)
  params.set("o", `${targetItem}*${targetRate}`);

  // URL format version
  params.set("v", "11");

  // Optional preset (machine tier)
  if (preset) {
    params.set("p", preset);
  }

  return `${url}?${params.toString()}`;
}

/**
 * Parse a FactorioLab URL back into solver input
 * Useful for debugging and testing
 */
export function parseUrl(url: string): SolverInput | null {
  try {
    const urlObj = new URL(url);

    // Extract mod ID from path (e.g., "/2.0/list" -> "2.0")
    const pathParts = urlObj.pathname.split("/").filter(Boolean);
    if (pathParts.length < 2) return null;
    const modId = pathParts[0];

    // Parse objective parameter
    const objective = urlObj.searchParams.get("o");
    if (!objective) return null;

    // Parse "item*rate" format
    const match = objective.match(/^([^*]+)\*(\d+(?:\.\d+)?)$/);
    if (!match) return null;

    const [, targetItem, rateStr] = match;
    const targetRate = parseFloat(rateStr);

    // Optional preset
    const preset = urlObj.searchParams.get("p") || undefined;

    return {
      targetItem,
      targetRate,
      modId,
      preset,
    };
  } catch {
    return null;
  }
}
