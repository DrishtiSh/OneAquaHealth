// Snapshot store: loading, validation, hot reload and the Windows file-lock guarantee.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { after, before, describe, test } from "node:test";
import { loadGeneration, normalizeRow, SnapshotError, SnapshotStore } from "../src/db/snapshot.js";
import { editedCopy, quietLogger, SKIP, startServer, tempDir, waitFor } from "./helpers.js";

describe("normalizeRow", () => {
  test("dates, BigInt, nested values and *_json columns", () => {
    const row = normalizeRow({
      week_start: new Date("2026-09-14T00:00:00.000Z"),
      at: new Date("2026-09-14T12:30:00.000Z"),
      n: 20n,
      ids: ["a", "b"],
      nested: { d: [new Date("2025-01-06T00:00:00Z")], k: 3n },
      facts_json: '{"x": {"value": 1}}',
      empty_json: null,
      plain: 1.5,
    });
    assert.deepEqual(row, {
      week_start: "2026-09-14",
      at: "2026-09-14T12:30:00.000Z",
      n: 20,
      ids: ["a", "b"],
      nested: { d: ["2025-01-06"], k: 3 },
      facts: { x: { value: 1 } },
      empty: null,
      plain: 1.5,
    });
    assert.doesNotThrow(() => JSON.stringify(row));
  });

  test("integers beyond JSON's safe range are refused, not rounded", () => {
    assert.throws(() => normalizeRow({ n: 2n ** 60n }), SnapshotError);
  });
});

describe("snapshot store", { skip: SKIP }, () => {
  let dir;
  before(() => {
    dir = tempDir();
  });
  after(() => {
    fs.rmSync(dir, { recursive: true, force: true });
  });

  const fresh = (name) => path.join(dir, name);

  test("a loaded snapshot does not lock its file, so Stage 8 can swap it in place", async () => {
    const file = await editedCopy(fresh("lock.duckdb"));
    const store = new SnapshotStore({ file, logger: quietLogger });
    try {
      await store.load();
      const next = await editedCopy(fresh("lock.next.duckdb"));
      fs.renameSync(next, file); // what os.replace does; fails on Windows if the file is open
      fs.unlinkSync(file);
      assert.ok((await store.current.query("SELECT count(*) AS n FROM sites"))[0].n > 0, "still serving from memory");
    } finally {
      await store.close();
    }
  });

  test("hot reload picks up a newly frozen snapshot", async () => {
    const file = await editedCopy(fresh("reload.duckdb"));
    const store = new SnapshotStore({ file, reloadMs: 30, logger: quietLogger });
    const srv = await startServer(store);
    try {
      await store.load();
      store.watch();
      const before = (await srv.get("/health")).body.snapshot_id;
      const next = await editedCopy(fresh("reload.next.duckdb"), [
        "UPDATE snapshot_manifest SET value = 'reloaded-0001' WHERE key = 'snapshot_id'",
      ]);
      fs.renameSync(next, file);
      await waitFor(async () => (await srv.get("/health")).body.snapshot_id === "reloaded-0001");
      const res = await srv.get("/api/v1/sites");
      assert.equal(res.headers.get("x-oah-snapshot"), "reloaded-0001");
      assert.notEqual(before, "reloaded-0001");
    } finally {
      await srv.close();
      await store.close();
    }
  });

  test("a broken replacement is rejected and the previous snapshot keeps serving", async () => {
    const file = await editedCopy(fresh("broken.duckdb"));
    const store = new SnapshotStore({ file, reloadMs: 30, logger: quietLogger });
    const srv = await startServer(store);
    try {
      const good = await store.load();
      store.watch();
      const junk = fresh("broken.next.duckdb");
      fs.writeFileSync(junk, "this is not a duckdb file");
      fs.renameSync(junk, file);
      await waitFor(() => store.lastError !== null);
      assert.equal(store.current, good);
      const health = (await srv.get("/health")).body;
      assert.equal(health.snapshot_id, good.id);
      assert.match(health.last_reload_error.message, /could not read snapshot/);
      assert.equal((await srv.get("/api/v1/sites")).status, 200);
    } finally {
      await srv.close();
      await store.close();
    }
  });

  const rejects = async (name, statements, pattern) => {
    const file = await editedCopy(fresh(name), statements);
    await assert.rejects(loadGeneration(file), (err) => err instanceof SnapshotError && pattern.test(err.message));
  };

  test("an unsupported schema version is refused", () =>
    rejects("schema.duckdb", ["UPDATE snapshot_manifest SET value = '2' WHERE key = 'schema_version'"], /schema version 2 is not supported/));

  test("a model that failed its convergence gate is refused", () =>
    rejects("gate.duckdb", ["UPDATE snapshot_manifest SET value = 'false' WHERE key = 'diagnostics_passed__M1_norain'"], /M1_norain did not pass/));

  test("a snapshot missing a view the API reads is refused", () =>
    rejects("view.duckdb", ["DROP VIEW v_incidents"], /missing v_incidents/));

  test("without a snapshot the API answers 503 with a hint, then recovers when one appears", async () => {
    const file = fresh("late.duckdb");
    const store = new SnapshotStore({ file, reloadMs: 30, logger: quietLogger });
    const srv = await startServer(store);
    try {
      await assert.rejects(store.load(), /snapshot not found/);
      store.watch();
      const health = await srv.get("/health");
      assert.equal(health.status, 503);
      assert.match(health.body.hint, /freeze_snapshot/);
      assert.equal((await srv.get("/api/v1/sites")).status, 503);
      assert.equal((await srv.get("/api/v1/openapi.json")).status, 200, "the contract is static");
      const built = await editedCopy(fresh("late.next.duckdb"));
      fs.renameSync(built, file);
      await waitFor(async () => (await srv.get("/health")).status === 200);
      assert.equal((await srv.get("/api/v1/sites")).status, 200);
    } finally {
      await srv.close();
      await store.close();
    }
  });

  test("a request keeps its snapshot across a reload; the old one closes when released", async () => {
    const file = await editedCopy(fresh("pin.duckdb"));
    const store = new SnapshotStore({ file, logger: quietLogger });
    try {
      const first = await store.load();
      const lease = store.acquire();
      const next = await editedCopy(fresh("pin.next.duckdb"), [
        "UPDATE snapshot_manifest SET value = 'pinned-0002' WHERE key = 'snapshot_id'",
      ]);
      fs.renameSync(next, file);
      await store.load();
      assert.equal(store.current.id, "pinned-0002");
      assert.equal(lease.gen, first);
      assert.ok(!first.closed, "still open for the in-flight request");
      assert.ok((await first.query("SELECT count(*) AS n FROM sites"))[0].n > 0);
      lease.release();
      lease.release(); // idempotent
      await waitFor(() => first.closed);
      assert.equal(first.inflight, 0);
    } finally {
      await store.close();
    }
  });

  test("re-freezing identical content keeps the warm generation", async () => {
    const file = await editedCopy(fresh("same.duckdb"));
    const store = new SnapshotStore({ file, logger: quietLogger });
    try {
      const first = await store.load();
      assert.equal(await store.load(), first);
      assert.ok(!first.closed);
    } finally {
      await store.close();
    }
  });
});
