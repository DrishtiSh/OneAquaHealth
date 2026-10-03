// Insight API (stage 9): serves the frozen DuckDB snapshot produced by pipeline/snapshot.
import { createApp } from "./app.js";
import { loadConfig } from "./config.js";
import { SnapshotStore } from "./db/snapshot.js";

const config = loadConfig();
const store = new SnapshotStore({ file: config.snapshotFile, reloadMs: config.reloadMs });

// A missing or unreadable snapshot is not fatal: /health reports 503 until a good one appears,
// and the watcher loads it as soon as Stage 8 writes it.
await store.load().catch(() => {});
store.watch();

const app = createApp(store, { corsOrigin: config.corsOrigin });
const server = app.listen(config.port, () => {
  console.log(`OAH Insight API listening on port ${config.port} (snapshot: ${config.snapshotFile})`);
});

function shutdown(signal) {
  console.log(`${signal} received, shutting down`);
  server.close(async () => {
    await store.close();
    process.exit(0);
  });
  setTimeout(() => process.exit(1), 5000).unref();
}
process.on("SIGINT", () => shutdown("SIGINT"));
process.on("SIGTERM", () => shutdown("SIGTERM"));
