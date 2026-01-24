import { chromium, type Browser, type Page } from "playwright";
import type { SolverInput, SolverResult, SolverError } from "./types";
import { buildUrl } from "./url-builder";
import { parseCsv } from "./csv-parser";

const DEFAULT_TIMEOUT = 30000; // 30 seconds

/**
 * Wait for FactorioLab to finish calculating
 */
async function waitForCalculation(page: Page): Promise<void> {
  // Wait for the table to appear with data rows
  await page.waitForSelector("table tbody tr", { timeout: DEFAULT_TIMEOUT });

  // Wait for "Solved" text in footer indicating calculation complete
  await page.waitForFunction(
    () => document.body.textContent?.includes("Solved"),
    { timeout: DEFAULT_TIMEOUT }
  );

  // Small additional wait for any final rendering
  await page.waitForTimeout(500);
}

/**
 * Download CSV using the "Download as CSV" button
 */
async function downloadCsv(page: Page): Promise<string> {
  // Set up download handler before clicking
  const downloadPromise = page.waitForEvent("download", {
    timeout: DEFAULT_TIMEOUT,
  });

  // Click the "Download as CSV" button
  const downloadButton = page.locator('button:has-text("Download as CSV")');
  await downloadButton.click();

  // Wait for download to start
  const download = await downloadPromise;

  // Read the downloaded content
  const stream = await download.createReadStream();
  const chunks: Buffer[] = [];

  return new Promise((resolve, reject) => {
    stream.on("data", (chunk: Buffer) => chunks.push(chunk));
    stream.on("end", () => resolve(Buffer.concat(chunks).toString("utf-8")));
    stream.on("error", reject);
  });
}

/**
 * Fallback: Extract data directly from the table DOM
 */
async function extractFromTable(page: Page): Promise<string> {
  const csv = await page.evaluate(() => {
    const rows: string[][] = [];

    // Build header from column headers
    const headerCells = document.querySelectorAll("table thead th");
    const headers: string[] = [];
    headerCells.forEach((th) => {
      // Get text content, clean it up
      const text = th.textContent?.trim().replace(/[↑↓]/g, "").trim() || "";
      headers.push(text);
    });

    // Map FactorioLab headers to our expected format
    const headerMap: Record<string, string> = {
      Tree: "Item",
      "Items/m": "Items",
      Belts: "Belts",
      "Wagons/m": "Wagons",
      Machines: "Machines",
      Beacons: "Beacons",
      Power: "Power",
      "Pollution/m": "Pollution",
    };

    const mappedHeaders = headers.map((h) => headerMap[h] || h);

    // Add extra columns we expect
    const fullHeaders = [
      "Item",
      "Items",
      "Inputs",
      "Outputs",
      "Targets",
      "Belts",
      "Belt",
      "Wagons",
      "Wagon",
      "Recipe",
      "Machines",
      "Machine",
      "Modules",
      "Beacons",
      "Power",
      "Pollution",
    ];
    rows.push(fullHeaders);

    // Extract data rows (skip total row)
    const dataRows = document.querySelectorAll("table tbody tr");
    dataRows.forEach((tr) => {
      // Skip total row
      if (tr.textContent?.includes("Total")) return;

      const cells = tr.querySelectorAll("td");
      const row: string[] = [];

      // Item name - first cell, look for icon title or text
      const itemCell = cells[0];
      const itemIcon = itemCell?.querySelector("img, [title]");
      const itemName =
        itemIcon?.getAttribute("title") ||
        itemIcon?.getAttribute("alt") ||
        itemCell?.textContent?.trim() ||
        "";
      row.push(itemName);

      // Items/m - second cell
      const itemsCell = cells[1];
      const itemsValue = itemsCell?.textContent?.trim() || "";
      row.push(itemsValue);

      // Inputs/Outputs/Targets - we don't have these in this view
      row.push(""); // Inputs
      row.push(""); // Outputs
      row.push(""); // Targets

      // Belts - third cell (value + type)
      const beltsCell = cells[2];
      const beltsValue = beltsCell?.textContent?.trim() || "";
      row.push(beltsValue);
      const beltIcon = beltsCell?.querySelector("img, [title]");
      row.push(beltIcon?.getAttribute("title") || "");

      // Wagons - fourth cell
      const wagonsCell = cells[3];
      const wagonsValue = wagonsCell?.textContent?.trim() || "";
      row.push(wagonsValue);
      const wagonIcon = wagonsCell?.querySelector("img, [title]");
      row.push(wagonIcon?.getAttribute("title") || "");

      // Recipe - same as item for now
      row.push(itemName);

      // Machines - fifth cell
      const machinesCell = cells[4];
      const machinesValue = machinesCell?.textContent?.trim() || "";
      row.push(machinesValue);
      const machineIcon = machinesCell?.querySelector("img, [title]");
      row.push(machineIcon?.getAttribute("title") || "");

      // Modules
      row.push("");

      // Beacons - sixth cell
      const beaconsCell = cells[5];
      row.push(beaconsCell?.textContent?.trim() || "");

      // Power - seventh cell
      const powerCell = cells[6];
      row.push(powerCell?.textContent?.trim() || "");

      // Pollution - eighth cell
      const pollutionCell = cells[7];
      row.push(pollutionCell?.textContent?.trim() || "");

      rows.push(row);
    });

    // Convert to CSV
    return rows
      .map((row) =>
        row.map((cell) => `"${cell.replace(/"/g, '""')}"`).join(",")
      )
      .join("\n");
  });

  return csv;
}

/**
 * Main solver function - automates FactorioLab to get production requirements
 */
export async function solve(
  input: SolverInput
): Promise<SolverResult | SolverError> {
  let browser: Browser | null = null;

  try {
    // Launch headless browser using system Chrome
    browser = await chromium.launch({
      headless: true,
      channel: "chrome",
    });

    const context = await browser.newContext({
      acceptDownloads: true,
    });

    const page = await context.newPage();

    // Navigate to FactorioLab with our parameters
    const url = buildUrl(input);
    await page.goto(url, { waitUntil: "networkidle" });

    // Wait for calculation to complete
    await waitForCalculation(page);

    // Try to download CSV via button
    let csv: string;
    try {
      csv = await downloadCsv(page);
    } catch (downloadError) {
      // Fallback to DOM extraction
      try {
        csv = await extractFromTable(page);
      } catch (extractError) {
        return {
          error: "Failed to extract data",
          details: `Download failed: ${downloadError}. Extract failed: ${extractError}`,
        };
      }
    }

    // Parse CSV to structured result
    const result = parseCsv(csv, input.targetItem, input.targetRate);

    return result;
  } catch (error) {
    return {
      error: "Solver failed",
      details: error instanceof Error ? error.message : String(error),
    };
  } finally {
    if (browser) {
      await browser.close();
    }
  }
}

/**
 * Check if a result is an error
 */
export function isError(
  result: SolverResult | SolverError
): result is SolverError {
  return "error" in result;
}
