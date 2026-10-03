// Stage 9 API tests against the real frozen snapshot.
import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import { after, before, describe, test } from "node:test";
import { listRoutes } from "../src/app.js";
import { OPENAPI_PATH } from "../src/routes/meta.js";
import { SKIP, startWithSnapshot } from "./helpers.js";

const V1 = "/api/v1";
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const SENSITIVITIES = ["sensitive", "normal", "strict"];

describe("Insight API", { skip: SKIP }, () => {
  let api;
  let meta;

  before(async () => {
    api = await startWithSnapshot();
    meta = (await api.get(`${V1}/meta`)).body.data;
  });
  after(async () => {
    await api?.close();
  });

  const ok = async (p) => {
    const res = await api.get(p);
    assert.equal(res.status, 200, `${p} -> ${res.status} ${JSON.stringify(res.body)}`);
    return res.body;
  };

  // ----------------------------------------------------------------------------- meta

  test("health reports the snapshot from the manifest", async () => {
    const body = await ok("/health");
    assert.equal(body.status, "ok");
    assert.equal(body.snapshot_id, meta.manifest.snapshot_id);
    assert.equal(body.latest_week, meta.manifest.latest_week);
  });

  test("meta lists both toggles, parsed thresholds, model health and provenance", () => {
    assert.deepEqual(meta.variants.map((v) => v.id), ["M1", "M1_norain"]);
    assert.equal(meta.default_variant, "M1");
    assert.deepEqual(meta.sensitivity_levels, [
      { id: "sensitive", delta_W: 5 },
      { id: "normal", delta_W: 10 },
      { id: "strict", delta_W: 20 },
    ]);
    assert.equal(typeof meta.thresholds.P_CONFIRMED, "number");
    assert.deepEqual(meta.model_health, { M1: true, M1_norain: true });
    assert.equal(meta.weeks.count, meta.manifest.n_weeks);
    assert.ok(meta.inputs.length > 0 && meta.inputs.every((i) => /^[0-9a-f]{64}$/.test(i.sha256)));
    assert.ok(meta.tables.every((t) => t.comment), "every table carries its Stage 8 comment");
    assert.ok(meta.views.includes("v_site_latest"));
  });

  test("every data response carries the snapshot id, disclaimer and cache headers", async () => {
    const res = await api.get(`${V1}/sites`);
    assert.equal(res.headers.get("x-oah-snapshot"), meta.manifest.snapshot_id);
    assert.equal(res.body.snapshot.id, meta.manifest.snapshot_id);
    assert.match(res.body.disclaimer, /not an official health advisory/i);
    assert.equal(res.headers.get("access-control-allow-origin"), "*");
    const etag = res.headers.get("etag");
    assert.ok(etag);
    // node:http, not fetch: fetch adds "Cache-Control: no-cache" to conditional requests.
    const status = await new Promise((resolve, reject) => {
      http.get(`${api.base}${V1}/sites`, { headers: { "If-None-Match": etag } }, (r) => {
        r.resume();
        resolve(r.statusCode);
      }).on("error", reject);
    });
    assert.equal(status, 304);
  });

  // ----------------------------------------------------------------------------- JSON hygiene

  function* walk(value, at = "$") {
    yield [at, value];
    if (Array.isArray(value)) for (const [i, v] of value.entries()) yield* walk(v, `${at}[${i}]`);
    else if (value && typeof value === "object") for (const [k, v] of Object.entries(value)) yield* walk(v, `${at}.${k}`);
  }

  test("every route returns clean JSON: plain dates, no raw *_json columns", async () => {
    const firstFinding = (await ok(`${V1}/findings?limit=1`)).data[0].finding_id;
    const firstIncident = (await ok(`${V1}/incidents`)).data[0].incident_id;
    const sample = { siteId: "gow-01", findingId: encodeURIComponent(firstFinding), incidentId: firstIncident };
    const paths = listRoutes()
      .map(([, p]) => p.replace(/:(\w+)/g, (_, name) => sample[name]))
      .filter((p) => !p.endsWith("/openapi.json")); // static schema document, not data
    const toggled = [`${V1}/sites?variant=M1_norain&sensitivity=strict`, `${V1}/scores?variant=M1_norain&week=2025-06-04`];
    for (const p of [...paths, ...toggled]) {
      const body = await ok(p);
      for (const [where, v] of walk(body)) {
        if (typeof v === "string") assert.doesNotMatch(v, /^\d{4}-\d{2}-\d{2}T00:00:00/, `${p} ${where}: timestamp-style date`);
        if (where.endsWith("_json")) assert.fail(`${p} ${where}: raw JSON column leaked`);
        const dateColumn = /\.(week_start|week_end|start_week|end_week|observed_date)$/.test(where);
        if (dateColumn && !where.includes(".facts.") && v !== null) {
          assert.match(v, DATE_RE, `${p} ${where}`);
        }
      }
    }
  });

  // ----------------------------------------------------------------------------- sites

  test("sites come head to mouth with intervals, evidence and exposure", async () => {
    const { data, count } = await ok(`${V1}/sites`);
    assert.equal(count, meta.n_sites);
    assert.deepEqual(data.map((s) => s.display_order), data.map((_, i) => i + 1));
    for (const s of data) {
      assert.equal(s.week_start, meta.manifest.latest_week);
      for (const band of [s.W, s.H]) assert.ok(band.q05 <= band.q50 && band.q50 <= band.q95, s.site_id);
      assert.ok(["sufficient", "weak", "insufficient"].includes(s.evidence));
      assert.deepEqual(s.exposure.map((e) => e.category), ["playground", "school", "park"]);
    }
  });

  test("insufficient evidence shows up as an honest 'not enough reports' status", async () => {
    const { data } = await ok(`${V1}/sites`);
    const thin = data.filter((s) => s.evidence === "insufficient");
    assert.ok(thin.length > 0, "the snapshot has at least one thin site");
    for (const s of thin) assert.match(s.status.headline, /not enough recent reports/i, s.site_id);
  });

  test("status text exists for the primary model only", async () => {
    const { data } = await ok(`${V1}/sites?variant=M1_norain`);
    assert.ok(data.every((s) => s.status === null));
  });

  test("the rain toggle changes the scores", async () => {
    const m1 = (await ok(`${V1}/sites`)).data;
    const norain = (await ok(`${V1}/sites?variant=M1_norain`)).data;
    assert.ok(m1.some((s, i) => s.W.q50 !== norain[i].W.q50));
  });

  for (const variant of ["M1", "M1_norain"]) {
    test(`latest scores equal the last timeseries week (${variant})`, async () => {
      const { data } = await ok(`${V1}/sites?variant=${variant}`);
      for (const s of data) {
        const series = (await ok(`${V1}/sites/${s.site_id}/timeseries?variant=${variant}`)).data;
        assert.equal(series.length, meta.weeks.count);
        const last = series.at(-1);
        assert.equal(last.week_start, s.week_start);
        for (const k of ["q05", "q50", "q95"]) {
          assert.equal(last.W[k], s.W[k]);
          assert.equal(last.H[k], s.H[k]);
        }
        assert.equal(last.p_change, s.p_change);
        assert.equal(last.alert_level, s.alert_level);
      }
    });

    test(`a bigger required drop is never more probable (${variant})`, async () => {
      for (const site of ["gow-01", "gow-05", "gow-10"]) {
        const [sens, norm, strict] = await Promise.all(
          SENSITIVITIES.map(async (lvl) => (await ok(`${V1}/sites/${site}/timeseries?variant=${variant}&sensitivity=${lvl}`)).data),
        );
        for (let i = 0; i < norm.length; i++) {
          assert.ok(sens[i].p_change >= norm[i].p_change && norm[i].p_change >= strict[i].p_change, `${site} ${norm[i].week_start}`);
        }
        const alerts = (rows) => rows.filter((r) => r.alert_level !== "none").length;
        assert.ok(alerts(sens) >= alerts(norm) && alerts(norm) >= alerts(strict));
      }
    });
  }

  test("site detail links neighbours, findings and incidents", async () => {
    const { data } = await ok(`${V1}/sites/gow-02`);
    assert.deepEqual(data.upstream.map((n) => n.site_id), ["gow-01"]);
    assert.deepEqual(data.downstream.map((n) => n.site_id), ["gow-03"]);
    assert.ok(data.findings.some((f) => f.finding_id === "site:gow-02"));
    for (const inc of data.incidents) assert.ok(inc.affected_site_ids.includes("gow-02"));
    const head = (await ok(`${V1}/sites/gow-01`)).data;
    assert.deepEqual(head.upstream, []);
  });

  test("timeseries honours from/to", async () => {
    const { data, params } = await ok(`${V1}/sites/gow-01/timeseries?from=2026-08-01&to=2026-08-31`);
    assert.deepEqual(params, { variant: "M1", sensitivity: "normal", from: "2026-08-01", to: "2026-08-31" });
    assert.ok(data.length === 5 && data.every((r) => r.week_start >= "2026-08-01" && r.week_start <= "2026-08-31"));
  });

  test("observations are de-identified, newest first, and paginate without overlap", async () => {
    const first = await ok(`${V1}/sites/gow-01/observations?limit=10`);
    const second = await ok(`${V1}/sites/gow-01/observations?limit=10&offset=10`);
    assert.ok(first.total > 20);
    const rows = [...first.data, ...second.data];
    assert.equal(new Set(rows.map((r) => r.observation_id)).size, 20);
    for (const r of rows) {
      for (const k of ["observer_id", "raw_payload", "observed_at", "ingested_at", "site_id"]) assert.ok(!(k in r), k);
    }
    const dates = rows.map((r) => r.observed_date);
    assert.deepEqual(dates, [...dates].sort().reverse());
    const all = await ok(`${V1}/sites/gow-01/observations?limit=500`);
    assert.equal(all.count, all.total);
  });

  // ----------------------------------------------------------------------------- network

  test("scores for a week snap any date to its grid week and match the timeseries", async () => {
    const body = await ok(`${V1}/scores?week=2025-01-01&variant=M1_norain&sensitivity=sensitive`);
    assert.equal(body.params.week, "2024-12-30");
    assert.equal(body.week.week_start, "2024-12-30");
    assert.equal(body.count, meta.n_sites);
    const gow3 = body.data.find((s) => s.site_id === "gow-03");
    const ts = (await ok(`${V1}/sites/gow-03/timeseries?variant=M1_norain&sensitivity=sensitive&from=2024-12-30&to=2024-12-30`)).data[0];
    assert.equal(gow3.W.q50, ts.W.q50);
    assert.equal(gow3.p_change, ts.p_change);
    assert.equal((await ok(`${V1}/scores`)).params.week, meta.manifest.latest_week);
  });

  test("weeks and river graph", async () => {
    const weeks = await ok(`${V1}/weeks`);
    assert.equal(weeks.count, meta.weeks.count);
    const { data } = await ok(`${V1}/river`);
    assert.equal(data.nodes.length, meta.n_sites);
    const ids = new Set(data.nodes.map((n) => n.site_id));
    assert.ok(data.edges.every((e) => ids.has(e.from_site_id) && ids.has(e.to_site_id)));
  });

  test("rain pattern comes from the no-rain model with its finding", async () => {
    const { data, note } = await ok(`${V1}/rain-pattern`);
    assert.equal(data.model_variant, meta.manifest.rain_variant);
    assert.deepEqual(data.groups.map((g) => g.grp), ["pooled", "cso_adjacent", "other_sites"]);
    for (const g of data.groups) assert.ok(g.irr_q05 <= g.irr_median && g.irr_median <= g.irr_q95);
    assert.equal(data.finding.finding_type, "rain_pattern");
    assert.match(note, /not proof of cause/);
  });

  test("model diagnostics and params", async () => {
    const diag = await ok(`${V1}/model/diagnostics`);
    assert.ok(diag.data.every((d) => d.passed === true && Array.isArray(d.failures) && typeof d.ppc === "object"));
    const params = await ok(`${V1}/model/params?variant=M1_norain`);
    assert.ok(params.count > 0 && params.data.every((p) => p.model_variant === "M1_norain"));
  });

  // ----------------------------------------------------------------------------- findings

  test("findings are ranked, with parsed facts and caveats", async () => {
    const { data, total, count } = await ok(`${V1}/findings`);
    assert.equal(total, count);
    assert.deepEqual(data.map((f) => f.display_rank), [...data.map((f) => f.display_rank)].sort((a, b) => a - b));
    for (const f of data) {
      assert.equal(typeof f.facts, "object");
      assert.ok(Array.isArray(f.caveats));
    }
    assert.ok(data.some((f) => f.finding_type === "coverage"));
  });

  test("finding filters and pagination", async () => {
    const incidents = (await ok(`${V1}/findings?type=incident`)).data;
    assert.ok(incidents.length > 0 && incidents.every((f) => f.finding_type === "incident"));
    const recent = (await ok(`${V1}/findings?recent=true`)).data;
    assert.ok(recent.every((f) => f.is_recent));
    const high = (await ok(`${V1}/findings?priority=high`)).data;
    assert.ok(high.every((f) => f.priority === "high"));
    const page2 = await ok(`${V1}/findings?limit=5&offset=5`);
    assert.deepEqual(page2.data.map((f) => f.display_rank), [6, 7, 8, 9, 10]);
    const site = (await ok(`${V1}/findings?site=gow-05`)).data;
    assert.ok(site.some((f) => f.finding_id === "site:gow-05"));
    assert.ok(site.every((f) => f.finding_type === "site_status" || f.finding_type === "incident"));
  });

  test("a finding id with a colon resolves, raw or encoded", async () => {
    const raw = await ok(`${V1}/findings/incident:inc-015`);
    const enc = await ok(`${V1}/findings/${encodeURIComponent("incident:inc-015")}`);
    assert.equal(raw.data.finding_id, "incident:inc-015");
    assert.deepEqual(raw.data, enc.data);
  });

  // ----------------------------------------------------------------------------- incidents

  test("incident source probabilities and 'no source' sum to one", async () => {
    for (const variant of ["M1", "M1_norain"]) {
      const { data } = await ok(`${V1}/incidents?variant=${variant}`);
      assert.ok(data.length > 0);
      for (const inc of data) {
        const sum = Object.values(inc.source_probs).reduce((a, b) => a + b, 0) + inc.p_no_source;
        assert.ok(Math.abs(sum - 1) < 0.02, `${inc.incident_id}: ${sum}`);
        assert.deepEqual(inc.source_ranking.map((r) => r.prob), [...inc.source_ranking.map((r) => r.prob)].sort((a, b) => b - a));
        if (inc.top_source) assert.ok(inc.credible_set.includes(inc.top_source));
      }
    }
  });

  test("incident findings and incidents point at each other and agree on recency", async () => {
    const incidents = (await ok(`${V1}/incidents`)).data;
    const byId = Object.fromEntries(incidents.map((i) => [i.incident_id, i]));
    const findings = (await ok(`${V1}/findings?type=incident`)).data;
    for (const f of findings) {
      const inc = byId[f.scope_id];
      assert.ok(inc, `finding ${f.finding_id} has an M1 incident`);
      assert.equal(inc.finding_id, f.finding_id);
      assert.equal(inc.is_recent, f.is_recent, `${f.finding_id}: same recency rule as Stage 7`);
    }
    assert.ok((await ok(`${V1}/incidents?variant=M1_norain`)).data.every((i) => i.finding_id === null));
  });

  test("incident filters", async () => {
    const all = (await ok(`${V1}/incidents`)).data;
    const recent = (await ok(`${V1}/incidents?recent=true`)).data;
    const old = (await ok(`${V1}/incidents?recent=false`)).data;
    assert.equal(recent.length + old.length, all.length);
    assert.ok(recent.every((i) => i.is_recent) && old.every((i) => !i.is_recent));
    assert.ok((await ok(`${V1}/incidents?site=gow-09`)).data.every((i) => i.affected_site_ids.includes("gow-09")));
    assert.ok((await ok(`${V1}/incidents?level=confirmed`)).data.every((i) => i.max_alert_level === "confirmed"));
  });

  test("incident detail lists its alerts, which agree with the normal-sensitivity timeseries", async () => {
    const { data } = await ok(`${V1}/incidents/inc-015`);
    assert.ok(data.alerts.length > 0);
    assert.equal(data.finding.finding_id, "incident:inc-015");
    for (const a of data.alerts) {
      assert.ok(data.affected_site_ids.includes(a.site_id));
      assert.ok(a.week_start >= data.start_week && a.week_start <= data.end_week);
      assert.notEqual(a.alert_level, "none");
    }
    const a = data.alerts[0];
    const ts = (await ok(`${V1}/sites/${a.site_id}/timeseries?from=${a.week_start}&to=${a.week_start}`)).data[0];
    assert.equal(ts.p_change, a.p_change);
    assert.equal(ts.alert_level, a.alert_level);
  });

  // ----------------------------------------------------------------------------- errors

  const expectError = async (p, status, pattern, init) => {
    const res = await api.get(p, init);
    assert.equal(res.status, status, `${p}: ${JSON.stringify(res.body)}`);
    assert.equal(res.body.error.status, status);
    if (pattern) assert.match(res.body.error.message, pattern);
    return res;
  };

  test("bad parameters are 400s that name the allowed values", async () => {
    const res = await expectError(`${V1}/sites?variant=M2`, 400, /variant must be one of: M1, M1_norain/);
    assert.deepEqual(res.body.error.details.allowed, ["M1", "M1_norain"]);
    await expectError(`${V1}/sites?sensitivity=extreme`, 400, /sensitive, normal, strict/);
    await expectError(`${V1}/sites?varient=M1`, 400, /unknown query parameter: varient/);
    await expectError(`${V1}/sites?variant=M1&variant=M1_norain`, 400, /only once/);
    await expectError(`${V1}/weeks?from=2026-02-30`, 400, /YYYY-MM-DD/);
    await expectError(`${V1}/weeks?from=2026-09-01&to=2026-01-01`, 400, /must not be after/);
    await expectError(`${V1}/findings?limit=0`, 400, /integer from 1 to 100/);
    await expectError(`${V1}/findings?recent=yes`, 400, /true or false/);
    await expectError(`${V1}/scores?week=2030-01-01`, 400, /week must fall between/);
    await expectError(`${V1}/river?x=1`, 400, /unknown query parameter/);
  });

  test("unknown ids and routes are JSON 404s", async () => {
    await expectError(`${V1}/sites/gow-99`, 404, /unknown site gow-99/);
    await expectError(`${V1}/sites/gow-99/timeseries`, 404, /unknown site/);
    await expectError(`${V1}/findings/incident:inc-999`, 404, /unknown finding/);
    await expectError(`${V1}/incidents/inc-999`, 404, /unknown incident/);
    await expectError(`${V1}/findings?site=gow-99`, 404, /unknown site/);
    await expectError(`${V1}/nope`, 404, /no route/);
  });

  test("injection attempts are treated as plain values", async () => {
    await expectError(`${V1}/sites/${encodeURIComponent("gow-01' OR '1'='1")}`, 404, /unknown site/);
    await expectError(`${V1}/incidents/${encodeURIComponent("x' OR 1=1 --")}`, 404, /unknown incident/);
    await expectError(`${V1}/findings/${encodeURIComponent("'; DROP TABLE findings; --")}`, 404);
    assert.equal((await ok(`${V1}/findings`)).total, (await ok(`${V1}/findings?limit=100`)).total);
  });

  test("the API is read-only", async () => {
    const res = await expectError(`${V1}/sites`, 405, /read-only/, { method: "POST" });
    assert.equal(res.headers.get("allow"), "GET, HEAD, OPTIONS");
    await expectError(`${V1}/findings/site:gow-01`, 405, null, { method: "DELETE" });
  });

  test("a malformed path escape is a 400, not a crash", async () => {
    await expectError(`${V1}/sites/%E0%A4%A`, 400);
  });

  test("concurrent requests are served consistently", async () => {
    const bodies = await Promise.all(Array.from({ length: 40 }, () => ok(`${V1}/sites?sensitivity=strict`)));
    for (const b of bodies) assert.deepEqual(b.data, bodies[0].data);
  });

  // ----------------------------------------------------------------------------- contract

  test("OpenAPI documents exactly the routes that are served", async () => {
    const spec = JSON.parse(fs.readFileSync(OPENAPI_PATH, "utf8"));
    const served = listRoutes().map(([m, p]) => `${m} ${p.replace(/:(\w+)/g, "{$1}")}`).sort();
    const documented = Object.entries(spec.paths).flatMap(([p, ops]) => Object.keys(ops).map((m) => `${m} ${p}`)).sort();
    assert.deepEqual(documented, served);
    assert.deepEqual(await ok(`${V1}/openapi.json`), spec);
  });
});
