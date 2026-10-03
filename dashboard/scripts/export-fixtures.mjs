// Dev utility (not part of the Next.js app itself): converts the pipeline's
// real Stage 1-4 data files (parquet) into JSON fixtures under src/data/.
// The dashboard reads everything from the Insight API (Stage 9); these
// fixtures are only its offline fallback when the API isn't reachable.
// Plain JavaScript, no Python involved.
//
// Run with: npm run export-data

import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { asyncBufferFromFile, parquetReadObjects } from "hyparquet";

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(__dirname, "..", "..");
const dataDir = join(__dirname, "..", "src", "data");

const EXPORTS = {
  "sites.json": join(repoRoot, "data/raw/sites.parquet"),
  "weather.json": join(repoRoot, "data/processed/weather_features.parquet"),
  "river-graph.json": join(repoRoot, "data/processed/river_graph_edges.parquet"),
  "exposure.json": join(repoRoot, "data/processed/exposure_features.parquet"),
};

// hyparquet returns BigInt for int64 columns and Date objects for date
// columns -- neither is directly JSON-serializable, so convert both.
function jsonReplacer(_key, value) {
  if (typeof value === "bigint") return Number(value);
  if (value instanceof Date) return value.toISOString().slice(0, 10);
  return value;
}

async function exportOne(filename, parquetPath) {
  let file;
  try {
    file = await asyncBufferFromFile(parquetPath);
  } catch {
    throw new Error(`${parquetPath} not found -- run the pipeline stages first.`);
  }
  const rows = await parquetReadObjects({ file });
  const outPath = join(dataDir, filename);
  writeFileSync(outPath, JSON.stringify(rows, jsonReplacer, 2) + "\n");
  console.log(`Wrote ${rows.length} rows to ${outPath}`);
}

async function main() {
  mkdirSync(dataDir, { recursive: true });
  for (const [filename, parquetPath] of Object.entries(EXPORTS)) {
    await exportOne(filename, parquetPath);
  }
}

main().catch((err) => {
  console.error(err.message);
  process.exit(1);
});
