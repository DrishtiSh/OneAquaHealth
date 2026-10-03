// Snapshot metadata, model health and the API contract.
import fs from "node:fs";
import path from "node:path";
import { Router } from "express";
import { API_DIR } from "../config.js";
import { send } from "../respond.js";
import { parseQuery, toggles } from "../validate.js";

export const OPENAPI_PATH = path.join(API_DIR, "openapi.json");
const FREEZE_HINT = "Build the snapshot with: python -m pipeline.snapshot.freeze_snapshot";

const VARIANT_INFO = {
  primary: {
    role: "primary",
    rain_assumed: true,
    description: "Primary model: slow per-site drift plus sparse contamination excursions, rain as a weak covariate.",
  },
  rain: {
    role: "rain_ablation",
    rain_assumed: false,
    description: "Same model without rain, used to test rain -> overflow without building the answer in.",
  },
};

// Liveness plus which snapshot is being served (outside /api/v1, never cached).
export function health(store) {
  return (_req, res) => {
    res.set("Cache-Control", "no-store");
    const gen = store.current;
    if (!gen) {
      return res.status(503).json({ status: "no_snapshot", error: store.lastError?.message ?? null, hint: FREEZE_HINT });
    }
    res.json({
      status: "ok",
      snapshot_id: gen.id,
      latest_week: gen.manifest.latest_week,
      loaded_at: gen.loadedAt,
      last_reload_error: store.lastError,
    });
  };
}

// The contract is static, so it is served even before a snapshot is loaded.
export function openapi() {
  const spec = JSON.parse(fs.readFileSync(OPENAPI_PATH, "utf8"));
  return (_req, res) => res.json(spec);
}

async function meta(req, res) {
  const { gen } = res.locals;
  parseQuery(req.query, {});
  const { thresholds, diagnostics_passed, ...manifest } = gen.manifest;
  const tables = await gen.query(
    "SELECT table_name AS name, comment FROM duckdb_tables() ORDER BY table_name",
  );
  const views = await gen.query(
    "SELECT view_name AS name FROM duckdb_views() WHERE NOT internal ORDER BY view_name",
  );
  const inputs = await gen.query("SELECT label, path, sha256, n_rows FROM snapshot_inputs ORDER BY label");
  const sensitivity_levels = Object.entries(thresholds.SENSITIVITY_DELTAS)
    .map(([id, delta_W]) => ({ id, delta_W }))
    .sort((a, b) => a.delta_W - b.delta_W);
  send(res, {
    manifest,
    weeks: { first: manifest.first_week, latest: manifest.latest_week, count: gen.weeks.length },
    n_sites: gen.siteIds.size,
    variants: [
      { id: manifest.primary_variant, ...VARIANT_INFO.primary },
      { id: manifest.rain_variant, ...VARIANT_INFO.rain },
    ],
    default_variant: manifest.primary_variant,
    sensitivity_levels,
    default_sensitivity: "normal",
    recent_since: gen.recentCutoff,
    thresholds,
    model_health: diagnostics_passed,
    languages: gen.languages,
    tables,
    views: views.map((v) => v.name),
    inputs,
  });
}

async function diagnostics(req, res) {
  const { gen } = res.locals;
  parseQuery(req.query, {});
  const rows = await gen.query("SELECT * FROM model_diagnostics ORDER BY model_variant");
  send(res, rows, { count: rows.length, note: "A snapshot is only frozen when every model passed its convergence gate." });
}

async function params(req, res) {
  const { gen } = res.locals;
  const q = parseQuery(req.query, { variant: toggles(gen).variant });
  const rows = await gen.query("SELECT * FROM model_params WHERE model_variant = ? ORDER BY param", [q.variant]);
  send(res, rows, { params: q, count: rows.length, note: "Posterior summaries; hdi_5% and hdi_95% bound a 90% interval." });
}

export function metaRouter() {
  const r = Router();
  r.get("/meta", meta);
  r.get("/model/diagnostics", diagnostics);
  r.get("/model/params", params);
  return r;
}
