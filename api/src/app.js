// Express app for the Insight API, built without `listen` so tests can mount it on any port.
import cors from "cors";
import express from "express";
import { insightsRouter } from "./routes/insights.js";
import { health, metaRouter, openapi } from "./routes/meta.js";
import { HttpError } from "./validate.js";

export const API_PREFIX = "/api/v1";
const READ_METHODS = ["GET", "HEAD", "OPTIONS"];

// Bind the request to one snapshot generation until the response closes, so a hot reload
// can't mix two snapshots inside one response.
function useSnapshot(store) {
  return (_req, res, next) => {
    const lease = store.acquire();
    if (!lease) {
      throw new HttpError(503, "no snapshot is loaded", {
        error: store.lastError?.message ?? null,
        hint: "Build the snapshot with: python -m pipeline.snapshot.freeze_snapshot",
      });
    }
    res.locals.gen = lease.gen;
    res.on("close", lease.release);
    res.set("X-OAH-Snapshot", lease.gen.id);
    // The data only changes when a new snapshot is frozen; ETags (express default) cover revalidation.
    res.set("Cache-Control", "public, max-age=60");
    next();
  };
}

function errorBody(status, message, details) {
  return { error: { status, message, ...(details === undefined ? {} : { details }) } };
}

// Every route the API serves, as [method, path] with express-style params (used by the OpenAPI test).
export function listRoutes() {
  const routes = [["get", "/health"], ["get", `${API_PREFIX}/openapi.json`]];
  for (const router of [metaRouter(), insightsRouter()]) {
    for (const layer of router.stack) {
      if (!layer.route) continue;
      for (const method of Object.keys(layer.route.methods)) routes.push([method, `${API_PREFIX}${layer.route.path}`]);
    }
  }
  return routes;
}

export function createApp(store, { corsOrigin = ["*"], logger = console } = {}) {
  const app = express();
  app.disable("x-powered-by");
  app.set("query parser", "simple");

  app.use(cors({
    origin: corsOrigin.includes("*") ? "*" : corsOrigin,
    methods: READ_METHODS,
    exposedHeaders: ["X-OAH-Snapshot", "ETag"],
  }));
  // The API is read-only.
  app.use((req, res, next) => {
    if (READ_METHODS.includes(req.method)) return next();
    res.set("Allow", READ_METHODS.join(", "));
    res.status(405).json(errorBody(405, `${req.method} is not allowed; this API is read-only`));
  });

  app.get("/health", health(store));
  app.get(`${API_PREFIX}/openapi.json`, openapi());
  app.use(API_PREFIX, useSnapshot(store), metaRouter(), insightsRouter());

  app.use((req, res) => {
    res.status(404).json(errorBody(404, `no route ${req.method} ${req.path}`, { docs: `${API_PREFIX}/openapi.json` }));
  });

  // Express 5 forwards rejected promises from async handlers here.
  app.use((err, req, res, _next) => {
    if (err instanceof HttpError) {
      return res.status(err.status).json(errorBody(err.status, err.message, err.details));
    }
    // e.g. a malformed %-escape in a path parameter (http-errors sets status and expose).
    if (Number.isInteger(err.status) && err.status >= 400 && err.status < 500) {
      return res.status(err.status).json(errorBody(err.status, err.expose ? err.message : "bad request"));
    }
    logger.error?.(`${req.method} ${req.originalUrl} failed:`, err);
    res.status(500).json(errorBody(500, "internal error"));
  });

  return app;
}
