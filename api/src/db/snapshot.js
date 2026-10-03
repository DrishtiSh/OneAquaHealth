// DuckDB client reading the frozen snapshot from data/snapshot/.
//
// The snapshot file is copied into an in-memory database and then detached, so the API never
// holds the file open. That keeps Stage 8's atomic swap (os.replace) working on Windows, where an
// open handle would block it, and lets a running API pick up a newly frozen snapshot.
//
// Each load is a "generation". A request acquires the current generation and keeps it until the
// response closes, so every query in one request sees the same snapshot even if a reload lands
// mid-request. A replaced generation is closed once its last request finishes.
import fs from "node:fs";
import duckdb from "duckdb";

// The snapshot schema this API understands (config.SNAPSHOT_SCHEMA_VERSION in the pipeline).
export const SUPPORTED_SCHEMA_VERSION = "2";

export const REQUIRED_TABLES = [
  "snapshot_manifest", "snapshot_inputs", "sites", "site_exposure", "river_edges", "weeks", "scores",
  "alerts", "alert_sensitivity", "incidents", "rain_pattern", "findings", "model_params",
  "model_diagnostics", "observations",
];
export const REQUIRED_VIEWS = ["v_site_latest", "v_site_timeseries", "v_findings_ranked", "v_incidents"];

export class SnapshotError extends Error {}

// ----------------------------------------------------------------------------- row normalisation

function normalizeValue(v) {
  if (v instanceof Date) {
    // DuckDB DATE arrives as UTC midnight; send it as a plain calendar date.
    const iso = v.toISOString();
    return iso.endsWith("T00:00:00.000Z") ? iso.slice(0, 10) : iso;
  }
  if (typeof v === "bigint") {
    // Aggregates (count, sum) come back as BigInt, which JSON.stringify rejects.
    if (v > BigInt(Number.MAX_SAFE_INTEGER) || v < BigInt(Number.MIN_SAFE_INTEGER)) {
      throw new SnapshotError(`integer ${v} is too large to send as JSON`);
    }
    return Number(v);
  }
  if (Array.isArray(v)) return v.map(normalizeValue);
  if (v !== null && typeof v === "object" && !Buffer.isBuffer(v)) {
    return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, normalizeValue(x)]));
  }
  return v;
}

// JSON-safe row: dates as YYYY-MM-DD, BigInt as number, and every `<name>_json` text column
// parsed into `<name>` (facts_json -> facts, source_probs_json -> source_probs, ...).
export function normalizeRow(row) {
  const out = {};
  for (const [key, value] of Object.entries(row)) {
    if (key.endsWith("_json")) {
      out[key.slice(0, -"_json".length)] = value == null ? null : JSON.parse(value);
    } else {
      out[key] = normalizeValue(value);
    }
  }
  return out;
}

// ----------------------------------------------------------------------------- duckdb helpers

function openMemoryDatabase() {
  return new Promise((resolve, reject) => {
    const db = new duckdb.Database(":memory:", (err) => (err ? reject(err) : resolve(db)));
  });
}

function closeDatabase(db) {
  return new Promise((resolve) => db.close(() => resolve()));
}

function all(con, sql, params = []) {
  return new Promise((resolve, reject) => {
    con.all(sql, ...params, (err, rows) => (err ? reject(err) : resolve(rows)));
  });
}

const sqlString = (s) => `'${String(s).replaceAll("'", "''")}'`;

// ----------------------------------------------------------------------------- generation

export class Generation {
  constructor(db, con, file, info) {
    this.db = db;
    this.con = con;
    this.file = file;
    this.loadedAt = new Date().toISOString();
    this.inflight = 0;
    this.retired = false;
    this.closed = false;
    Object.assign(this, info); // manifest, siteIds, siteNames, weeks, languages, recentCutoff
  }

  get id() {
    return this.manifest.snapshot_id;
  }

  // Always pass user input through `params` (bound `?` placeholders), never into `sql`.
  async query(sql, params = []) {
    if (this.closed) throw new SnapshotError("snapshot generation is closed");
    return (await all(this.con, sql, params)).map(normalizeRow);
  }

  async one(sql, params = []) {
    return (await this.query(sql, params))[0] ?? null;
  }

  acquire() {
    this.inflight += 1;
    let released = false;
    return () => {
      if (released) return;
      released = true;
      this.inflight -= 1;
      if (this.retired && this.inflight === 0) this.close();
    };
  }

  retire() {
    this.retired = true;
    if (this.inflight === 0) return this.close();
    return Promise.resolve();
  }

  async close() {
    if (this.closed) return;
    this.closed = true;
    await closeDatabase(this.db);
  }
}

function parseManifest(rows) {
  const kv = Object.fromEntries(rows.map((r) => [r.key, r.value]));
  const diagnostics_passed = {};
  const manifest = {};
  for (const [key, value] of Object.entries(kv)) {
    if (key.startsWith("diagnostics_passed__")) diagnostics_passed[key.slice("diagnostics_passed__".length)] = value === "true";
    else if (key === "thresholds_json") manifest.thresholds = JSON.parse(value);
    else if (key === "n_weeks" || key === "random_seed") manifest[key] = Number(value);
    else manifest[key] = value;
  }
  return { ...manifest, diagnostics_passed };
}

async function validate(con) {
  const tables = new Set((await all(con, "SELECT table_name FROM duckdb_tables()")).map((r) => r.table_name));
  const views = new Set((await all(con, "SELECT view_name FROM duckdb_views() WHERE NOT internal")).map((r) => r.view_name));
  const missing = [...REQUIRED_TABLES.filter((t) => !tables.has(t)), ...REQUIRED_VIEWS.filter((v) => !views.has(v))];
  if (missing.length) throw new SnapshotError(`snapshot is missing ${missing.join(", ")}`);

  const manifest = parseManifest(await all(con, "SELECT key, value FROM snapshot_manifest"));
  if (manifest.schema_version !== SUPPORTED_SCHEMA_VERSION) {
    throw new SnapshotError(
      `snapshot schema version ${manifest.schema_version} is not supported (this API reads version ${SUPPORTED_SCHEMA_VERSION})`,
    );
  }
  for (const key of ["snapshot_id", "primary_variant", "rain_variant", "latest_week", "first_week", "disclaimer"]) {
    if (!manifest[key]) throw new SnapshotError(`snapshot manifest lacks ${key}`);
  }
  if (!manifest.thresholds?.SENSITIVITY_DELTAS) throw new SnapshotError("snapshot manifest lacks SENSITIVITY_DELTAS");
  // Stage 8 refuses to freeze a failed fit; re-check so a hand-edited file can't slip through.
  for (const v of [manifest.primary_variant, manifest.rain_variant]) {
    if (manifest.diagnostics_passed[v] !== true) throw new SnapshotError(`model ${v} did not pass its convergence gate`);
  }
  return manifest;
}

async function lookups(con, manifest) {
  const sites = (await all(con, "SELECT site_id, name FROM sites ORDER BY display_order")).map(normalizeRow);
  const weeks = (await all(con, "SELECT week_start FROM weeks ORDER BY week_start")).map((r) => normalizeRow(r).week_start);
  const languages = (await all(con, "SELECT DISTINCT language FROM findings ORDER BY 1")).map((r) => r.language);
  const recentWeeks = manifest.thresholds.RECENT_WEEKS ?? 4;
  // Optional (schema 2): Stage 11 only runs when there is simulator ground truth to score against.
  const hasBenchmark = (await all(con, "SELECT 1 FROM duckdb_tables() WHERE table_name = 'benchmark'")).length > 0;
  return {
    manifest,
    hasBenchmark,
    siteIds: new Set(sites.map((s) => s.site_id)),
    siteNames: Object.fromEntries(sites.map((s) => [s.site_id, s.name])),
    weeks,
    languages,
    // Same rule as Stage 7 (pipeline/nlg/render.py): recent = ends within the last RECENT_WEEKS grid weeks.
    recentCutoff: weeks[Math.max(0, weeks.length - recentWeeks)],
  };
}

export async function loadGeneration(file) {
  if (!fs.existsSync(file)) {
    throw new SnapshotError(`snapshot not found at ${file}; build it with: python -m pipeline.snapshot.freeze_snapshot`);
  }
  const db = await openMemoryDatabase();
  try {
    const con = db.connect();
    await all(con, `ATTACH ${sqlString(file.replaceAll("\\", "/"))} AS snap (READ_ONLY)`);
    try {
      await all(con, "COPY FROM DATABASE snap TO memory");
    } finally {
      await all(con, "DETACH snap");
    }
    const manifest = await validate(con);
    return new Generation(db, con, file, await lookups(con, manifest));
  } catch (err) {
    await closeDatabase(db);
    throw err instanceof SnapshotError ? err : new SnapshotError(`could not read snapshot ${file}: ${err.message}`);
  }
}

// ----------------------------------------------------------------------------- store

export class SnapshotStore {
  constructor({ file, reloadMs = 0, logger = console }) {
    this.file = file;
    this.reloadMs = reloadMs;
    this.logger = logger;
    this.current = null;
    this.lastError = null;
    this._reloading = null;
    this._pending = false;
    this._watching = false;
  }

  // Load (or reload) the file. On failure the previous generation keeps serving.
  async load() {
    try {
      const next = await loadGeneration(this.file);
      this.lastError = null;
      const prev = this.current;
      if (prev && prev.id === next.id) {
        await next.close(); // same content re-frozen: keep the warm generation
        return prev;
      }
      this.current = next;
      if (prev) {
        prev.retire();
        this.logger.info?.(`snapshot reloaded ${prev.id} -> ${next.id}`);
      } else {
        this.logger.info?.(`snapshot ${next.id} loaded (latest week ${next.manifest.latest_week})`);
      }
      return next;
    } catch (err) {
      this.lastError = { message: err.message, at: new Date().toISOString() };
      const serving = this.current ? `still serving ${this.current.id}` : "no snapshot loaded";
      this.logger.error?.(`snapshot load failed (${serving}): ${err.message}`);
      throw err;
    }
  }

  // Serialised reload: overlapping change notifications collapse into one follow-up load.
  reload() {
    if (this._reloading) {
      this._pending = true;
      return this._reloading;
    }
    this._reloading = (async () => {
      do {
        this._pending = false;
        await this.load().catch(() => {});
      } while (this._pending);
      this._reloading = null;
    })();
    return this._reloading;
  }

  // Poll the file (fs.watchFile copes with atomic renames, unlike fs.watch on Windows).
  watch() {
    if (!this.reloadMs || this._watching) return;
    this._watching = true;
    fs.watchFile(this.file, { interval: this.reloadMs, persistent: false }, (curr, prev) => {
      if (curr.mtimeMs !== prev.mtimeMs || curr.size !== prev.size || curr.ino !== prev.ino) {
        if (curr.mtimeMs !== 0) this.reload();
      }
    });
  }

  // Returns { gen, release } for the current snapshot, or null when none is loaded.
  acquire() {
    const gen = this.current;
    return gen ? { gen, release: gen.acquire() } : null;
  }

  async close() {
    if (this._watching) fs.unwatchFile(this.file);
    this._watching = false;
    if (this._reloading) await this._reloading;
    const gen = this.current;
    this.current = null;
    if (gen) await gen.retire();
  }
}
