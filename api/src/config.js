// Runtime configuration from the environment (and api/.env, if present).
import path from "node:path";
import { fileURLToPath } from "node:url";
import dotenv from "dotenv";

// The api/ package root, so relative paths work whatever directory the server is started from.
export const API_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const SNAPSHOT_FILENAME = "oah_snapshot.duckdb";

dotenv.config({ path: path.join(API_DIR, ".env"), quiet: true });

function intEnv(name, fallback) {
  const raw = process.env[name];
  if (raw === undefined || raw === "") return fallback;
  const n = Number(raw);
  if (!Number.isInteger(n) || n < 0) throw new Error(`${name} must be a non-negative integer, got "${raw}"`);
  return n;
}

// SNAPSHOT_PATH may name the snapshot directory (as in .env.example) or the .duckdb file itself.
export function resolveSnapshotFile(raw = process.env.SNAPSHOT_PATH) {
  const p = path.resolve(API_DIR, raw || "../data/snapshot");
  return p.endsWith(".duckdb") ? p : path.join(p, SNAPSHOT_FILENAME);
}

export function loadConfig() {
  return {
    port: intEnv("PORT", 4000),
    snapshotFile: resolveSnapshotFile(),
    // Comma-separated list of allowed origins; "*" allows any (the API is public and read-only).
    corsOrigin: (process.env.CORS_ORIGIN || "*").split(",").map((s) => s.trim()).filter(Boolean),
    // How often to check the snapshot file for a newer freeze; 0 turns hot reload off.
    reloadMs: intEnv("SNAPSHOT_RELOAD_MS", 5000),
  };
}
