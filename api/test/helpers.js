// Shared test helpers: the real snapshot (like the pipeline tests, which use the committed data),
// an app on a random port, and scratch copies of the snapshot that tests may edit.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import duckdb from "duckdb";
import { createApp } from "../src/app.js";
import { resolveSnapshotFile } from "../src/config.js";
import { SnapshotStore } from "../src/db/snapshot.js";

export const SNAPSHOT_FILE = resolveSnapshotFile();
export const SKIP = fs.existsSync(SNAPSHOT_FILE)
  ? false
  : `snapshot missing at ${SNAPSHOT_FILE}; run: python -m pipeline.snapshot.freeze_snapshot`;

export const quietLogger = { info() {}, error() {} };

export async function startServer(store) {
  const app = createApp(store, { logger: quietLogger });
  const server = await new Promise((resolve) => {
    const s = app.listen(0, () => resolve(s));
  });
  const base = `http://127.0.0.1:${server.address().port}`;
  const get = async (p, init) => {
    const res = await fetch(base + p, init);
    const text = await res.text();
    return { status: res.status, headers: res.headers, body: text ? JSON.parse(text) : null };
  };
  const close = () => new Promise((resolve) => server.close(resolve));
  return { base, get, close };
}

export async function startWithSnapshot(file = SNAPSHOT_FILE, opts = {}) {
  const store = new SnapshotStore({ file, logger: quietLogger, ...opts });
  await store.load();
  const srv = await startServer(store);
  return {
    store,
    ...srv,
    close: async () => {
      await srv.close();
      await store.close();
    },
  };
}

export function tempDir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "oah-api-test-"));
}

// Copy the real snapshot to `dest`, then run `statements` against the copy (to simulate a newer
// freeze, a corrupted manifest, ...). Edits go through ATTACH/DETACH from an in-memory database:
// on Windows a file-backed duckdb.Database keeps its handle open after close() until GC.
export async function editedCopy(dest, statements = []) {
  fs.copyFileSync(SNAPSHOT_FILE, dest);
  if (!statements.length) return dest;
  const db = new duckdb.Database(":memory:");
  const run = (sql) => new Promise((resolve, reject) => db.run(sql, (err) => (err ? reject(err) : resolve())));
  try {
    await run(`ATTACH '${dest.replaceAll("\\", "/").replaceAll("'", "''")}' AS edit`);
    await run("USE edit");
    for (const sql of statements) await run(sql);
    await run("USE memory");
    await run("DETACH edit");
  } finally {
    await new Promise((resolve) => db.close(resolve));
  }
  return dest;
}

export async function waitFor(predicate, { timeoutMs = 10000, everyMs = 25 } = {}) {
  const until = Date.now() + timeoutMs;
  while (Date.now() < until) {
    if (await predicate()) return true;
    await new Promise((r) => setTimeout(r, everyMs));
  }
  throw new Error("timed out waiting for condition");
}
