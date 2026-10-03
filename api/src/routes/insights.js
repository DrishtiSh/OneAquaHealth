// Insight endpoints (per-site scores, detected issues, fact-locked summaries).
//
// Read-only views over the frozen snapshot: nothing here computes a new number. Rows are reshaped
// (intervals nested, JSON columns parsed, names attached) and filtered by the request's toggles.
import { Router } from "express";
import { groupBy, nestBands, send } from "../respond.js";
import { badRequest, checkRange, notFound, page, param, parseQuery, toggles, weekRange } from "../validate.js";

// Caveats that come with the toggles (from the Stage 8 table comments).
export const NOTES = {
  status: "status_headline and status_body are written for the primary model at normal sensitivity; they are null under other model variants.",
  episodes: "episode_id and incidents are linked at normal sensitivity; the sensitivity toggle changes p_change and alert_level only.",
  incidents: "Incidents are linked at normal sensitivity.",
  findings: "Findings are written for the primary model at normal sensitivity; the rain-pattern finding comes from the no-rain model so the rain result is not built in.",
  rain: "An association in the data, not proof of cause.",
};

const EXPOSURE_ORDER = "list_position(['playground', 'school', 'park'], category)";

// WHERE clause built from fixed SQL fragments; request values only ever go into `args`.
class Where {
  constructor() {
    this.parts = [];
    this.args = [];
  }

  and(sql, ...args) {
    this.parts.push(sql);
    this.args.push(...args);
    return this;
  }

  toString() {
    return this.parts.length ? `WHERE ${this.parts.join(" AND ")}` : "";
  }
}

// ----------------------------------------------------------------------------- sites

const SITE_LATEST_SQL = `
  SELECT l.site_id, l.name, l.display_order, l.lat, l.lon, s.watershed, s.distance_from_mouth_m,
         l.is_cso_outfall_adjacent, s.known_context_note, l.exposure_weight, l.week_start,
         l.W_mean, l.W_q05, l.W_q50, l.W_q95, l.H_mean, l.H_q05, l.H_q50, l.H_q95,
         l.evidence, l.mixing_flag, l.n_reports, als.p_change, als.alert_level,
         l.status_headline, l.status_body
  FROM v_site_latest l
  JOIN sites s ON s.site_id = l.site_id
  LEFT JOIN alert_sensitivity als
    ON als.model_variant = l.model_variant AND als.site_id = l.site_id
   AND als.week_start = l.week_start AND als.sensitivity = ?
  WHERE l.model_variant = ?`;

function shapeSite({ status_headline, status_body, ...row }, exposure) {
  return {
    ...nestBands(row),
    status: status_headline == null ? null : { headline: status_headline, body: status_body },
    exposure: exposure ?? [],
  };
}

async function exposureBySite(gen, siteId) {
  const rows = await gen.query(
    `SELECT site_id, category, nearest_poi_name, nearest_poi_distance_m, poi_count_within_threshold,
            is_exposure_relevant, data_source
     FROM site_exposure ${siteId ? "WHERE site_id = ?" : ""}
     ORDER BY site_id, ${EXPOSURE_ORDER}`,
    siteId ? [siteId] : [],
  );
  return groupBy(rows, "site_id");
}

async function listSites(req, res) {
  const { gen } = res.locals;
  const q = parseQuery(req.query, toggles(gen));
  const rows = await gen.query(`${SITE_LATEST_SQL} ORDER BY l.display_order`, [q.sensitivity, q.variant]);
  const exposure = await exposureBySite(gen);
  send(res, rows.map((r) => shapeSite(r, exposure[r.site_id])), { params: q, count: rows.length, note: NOTES.status });
}

const sitePath = (gen, siteId) => {
  if (!gen.siteIds.has(siteId)) throw notFound(`unknown site ${siteId}`, { allowed: [...gen.siteIds] });
  return siteId;
};

const FINDINGS_FOR_SITE = `(
  (f.finding_type = 'site_status' AND f.scope_id = ?)
  OR (f.finding_type = 'incident' AND f.scope_id IN (
        SELECT i.incident_id FROM incidents i
        WHERE i.model_variant = f.model_variant AND list_contains(i.affected_site_ids, ?))))`;

async function getSite(req, res) {
  const { gen } = res.locals;
  const siteId = sitePath(gen, req.params.siteId);
  const q = parseQuery(req.query, toggles(gen));
  const row = await gen.one(`${SITE_LATEST_SQL} AND l.site_id = ?`, [q.sensitivity, q.variant, siteId]);
  const exposure = await exposureBySite(gen, siteId);
  const neighbours = (dir) =>
    gen.query(
      dir === "up"
        ? `SELECT e.from_site_id AS site_id, s.name, e.distance_m FROM river_edges e
           JOIN sites s ON s.site_id = e.from_site_id WHERE e.to_site_id = ? ORDER BY s.display_order`
        : `SELECT e.to_site_id AS site_id, s.name, e.distance_m FROM river_edges e
           JOIN sites s ON s.site_id = e.to_site_id WHERE e.from_site_id = ? ORDER BY s.display_order`,
      [siteId],
    );
  const findings = await gen.query(
    `SELECT f.* FROM v_findings_ranked f WHERE ${FINDINGS_FOR_SITE} ORDER BY f.display_rank`,
    [siteId, siteId],
  );
  const incidents = await gen.query(
    `${INCIDENT_SQL} WHERE i.model_variant = ? AND list_contains(i.affected_site_ids, ?)
     ORDER BY i.start_week DESC, i.incident_id DESC`,
    [q.variant, siteId],
  );
  send(res, {
    ...shapeSite(row, exposure[siteId]),
    upstream: await neighbours("up"),
    downstream: await neighbours("down"),
    findings,
    incidents: incidents.map((i) => shapeIncident(i, gen)),
  }, { params: q, note: `${NOTES.status} ${NOTES.incidents}` });
}

async function siteTimeseries(req, res) {
  const { gen } = res.locals;
  const siteId = sitePath(gen, req.params.siteId);
  const q = parseQuery(req.query, { ...toggles(gen), ...weekRange(gen) });
  checkRange(q);
  const rows = await gen.query(
    `SELECT t.week_start, t.W_q05, t.W_q50, t.W_q95, t.H_q05, t.H_q50, t.H_q95,
            t.evidence, t.mixing_flag, t.n_reports, als.p_change, als.alert_level, t.episode_id,
            t.weekly_rainfall_mm, t.heavy_rain_week, t.rain_exposed
     FROM v_site_timeseries t
     LEFT JOIN alert_sensitivity als
       ON als.model_variant = t.model_variant AND als.site_id = t.site_id
      AND als.week_start = t.week_start AND als.sensitivity = ?
     WHERE t.model_variant = ? AND t.site_id = ? AND t.week_start BETWEEN ?::DATE AND ?::DATE
     ORDER BY t.week_start`,
    [q.sensitivity, q.variant, siteId, q.from, q.to],
  );
  send(res, rows.map(nestBands), {
    params: q,
    site: { site_id: siteId, name: gen.siteNames[siteId] },
    count: rows.length,
    note: NOTES.episodes,
  });
}

async function siteObservations(req, res) {
  const { gen } = res.locals;
  const siteId = sitePath(gen, req.params.siteId);
  const q = parseQuery(req.query, { ...weekRange(gen), ...page(500, 100) });
  checkRange(q);
  const where = "WHERE site_id = ? AND week_start BETWEEN ?::DATE AND ?::DATE";
  const args = [siteId, q.from, q.to];
  const { total } = await gen.one(`SELECT count(*) AS total FROM observations ${where}`, args);
  // Explicit column list: a column added to the table later is not published by accident.
  const rows = await gen.query(
    `SELECT observation_id, observed_date, week_start, water_clarity, smell, smell_intensity,
            trash_level, insect_presence, insect_diversity, notes, source
     FROM observations ${where}
     ORDER BY observed_date DESC, observation_id
     LIMIT ?::INTEGER OFFSET ?::INTEGER`,
    [...args, q.limit, q.offset],
  );
  send(res, rows, {
    params: q,
    site: { site_id: siteId, name: gen.siteNames[siteId] },
    count: rows.length,
    total,
    note: "De-identified volunteer reports. water_clarity: 1 = clear, 5 = murky; smell_intensity: 0-3.",
  });
}

// ----------------------------------------------------------------------------- network-wide

const addDays = (iso, n) => new Date(Date.parse(`${iso}T00:00:00Z`) + n * 86400000).toISOString().slice(0, 10);

async function scoresForWeek(req, res) {
  const { gen } = res.locals;
  const { first_week, latest_week } = gen.manifest;
  const q = parseQuery(req.query, { ...toggles(gen), week: param.date(latest_week) });
  if (q.week < first_week || q.week > addDays(latest_week, 6)) {
    throw badRequest(`week must fall between ${first_week} and the week of ${latest_week}`, { week: q.week });
  }
  // Any date maps to the grid week that contains it.
  const week = gen.weeks.filter((w) => w <= q.week).at(-1);
  const rows = await gen.query(
    `SELECT s.site_id, s.name, s.display_order, s.lat, s.lon, s.is_cso_outfall_adjacent,
            sc.W_mean, sc.W_sd, sc.W_q05, sc.W_q25, sc.W_q50, sc.W_q75, sc.W_q95,
            sc.H_mean, sc.H_sd, sc.H_q05, sc.H_q25, sc.H_q50, sc.H_q75, sc.H_q95,
            sc.evidence, sc.mixing_flag, sc.n_reports, sc.n_informative_fields,
            als.p_change, als.alert_level
     FROM scores sc
     JOIN sites s ON s.site_id = sc.site_id
     LEFT JOIN alert_sensitivity als
       ON als.model_variant = sc.model_variant AND als.site_id = sc.site_id
      AND als.week_start = sc.week_start AND als.sensitivity = ?
     WHERE sc.model_variant = ? AND sc.week_start = ?::DATE
     ORDER BY s.display_order`,
    [q.sensitivity, q.variant, week],
  );
  const weather = await gen.one("SELECT * FROM weeks WHERE week_start = ?::DATE", [week]);
  send(res, rows.map(nestBands), { params: { ...q, week }, week: weather, count: rows.length });
}

async function listWeeks(req, res) {
  const { gen } = res.locals;
  const q = parseQuery(req.query, weekRange(gen));
  checkRange(q);
  const rows = await gen.query(
    "SELECT * FROM weeks WHERE week_start BETWEEN ?::DATE AND ?::DATE ORDER BY week_start",
    [q.from, q.to],
  );
  send(res, rows, { params: q, count: rows.length });
}

async function river(req, res) {
  const { gen } = res.locals;
  parseQuery(req.query, {});
  const nodes = await gen.query(
    `SELECT site_id, name, display_order, lat, lon, distance_from_mouth_m, is_cso_outfall_adjacent
     FROM sites ORDER BY display_order`,
  );
  const edges = await gen.query(
    `SELECT e.from_site_id, e.to_site_id, e.distance_m FROM river_edges e
     JOIN sites s ON s.site_id = e.from_site_id ORDER BY s.display_order`,
  );
  send(res, { nodes, edges }, { note: "from_site_id is directly upstream of to_site_id." });
}

// ----------------------------------------------------------------------------- findings

const FINDING_TYPES = ["incident", "site_status", "rain_pattern", "coverage"];
const PRIORITIES = ["high", "medium", "low", "info"];

async function listFindings(req, res) {
  const { gen } = res.locals;
  const q = parseQuery(req.query, {
    type: param.oneOf(FINDING_TYPES),
    priority: param.oneOf(PRIORITIES),
    recent: param.bool(),
    site: param.site(gen),
    lang: param.oneOf(gen.languages, gen.languages.includes("en") ? "en" : gen.languages[0]),
    ...page(100, 100),
  });
  const w = new Where().and("f.language = ?", q.lang);
  if (q.type) w.and("f.finding_type = ?", q.type);
  if (q.priority) w.and("f.priority = ?", q.priority);
  if (q.recent !== undefined) w.and("f.is_recent = ?", q.recent);
  if (q.site) w.and(FINDINGS_FOR_SITE, q.site, q.site);
  const { total } = await gen.one(`SELECT count(*) AS total FROM v_findings_ranked f ${w}`, w.args);
  const rows = await gen.query(
    `SELECT f.* FROM v_findings_ranked f ${w} ORDER BY f.display_rank LIMIT ?::INTEGER OFFSET ?::INTEGER`,
    [...w.args, q.limit, q.offset],
  );
  send(res, rows, { params: q, count: rows.length, total, note: NOTES.findings });
}

async function getFinding(req, res) {
  const { gen } = res.locals;
  parseQuery(req.query, {});
  const row = await gen.one("SELECT * FROM v_findings_ranked WHERE finding_id = ?", [req.params.findingId]);
  if (!row) throw notFound(`unknown finding ${req.params.findingId}`);
  send(res, row, { note: NOTES.findings });
}

// ----------------------------------------------------------------------------- incidents

const INCIDENT_SQL = `
  SELECT i.*, f.finding_id
  FROM v_incidents i
  LEFT JOIN findings f
    ON f.finding_type = 'incident' AND f.scope_id = i.incident_id AND f.model_variant = i.model_variant`;

function shapeIncident(row, gen) {
  const ranking = Object.entries(row.source_probs ?? {})
    .map(([site_id, prob]) => ({ site_id, name: gen.siteNames[site_id] ?? null, prob }))
    .sort((a, b) => b.prob - a.prob || a.site_id.localeCompare(b.site_id));
  return { ...row, is_recent: row.end_week >= gen.recentCutoff, source_ranking: ranking };
}

async function listIncidents(req, res) {
  const { gen } = res.locals;
  const q = parseQuery(req.query, {
    variant: toggles(gen).variant,
    recent: param.bool(),
    site: param.site(gen),
    level: param.oneOf(["confirmed", "possible"]),
  });
  const w = new Where().and("i.model_variant = ?", q.variant);
  if (q.recent !== undefined) w.and(`${q.recent ? "" : "NOT "}(i.end_week >= ?::DATE)`, gen.recentCutoff);
  if (q.site) w.and("list_contains(i.affected_site_ids, ?)", q.site);
  if (q.level) w.and("i.max_alert_level = ?", q.level);
  const rows = await gen.query(`${INCIDENT_SQL} ${w} ORDER BY i.start_week DESC, i.incident_id DESC`, w.args);
  send(res, rows.map((r) => shapeIncident(r, gen)), { params: q, count: rows.length, note: NOTES.incidents });
}

async function getIncident(req, res) {
  const { gen } = res.locals;
  const q = parseQuery(req.query, { variant: toggles(gen).variant });
  const { incidentId } = req.params;
  const row = await gen.one(`${INCIDENT_SQL} WHERE i.model_variant = ? AND i.incident_id = ?`, [q.variant, incidentId]);
  if (!row) throw notFound(`unknown incident ${incidentId} for model variant ${q.variant}`);
  // The site-weeks that make up the incident: alerts on its affected sites inside its window.
  const alerts = await gen.query(
    `SELECT a.site_id, s.name, a.week_start, a.p_change, a.drop_W_median, a.drop_W_q05, a.drop_W_q95,
            a.rise_H_median, a.alert_level, a.evidence, a.mixing_flag, a.n_reports, a.episode_id
     FROM alerts a
     JOIN sites s ON s.site_id = a.site_id
     JOIN incidents i
       ON i.model_variant = a.model_variant AND i.incident_id = ?
      AND list_contains(i.affected_site_ids, a.site_id) AND a.week_start BETWEEN i.start_week AND i.end_week
     WHERE a.model_variant = ? AND a.alert_level <> 'none'
     ORDER BY a.week_start, s.display_order`,
    [incidentId, q.variant],
  );
  const finding = row.finding_id
    ? await gen.one("SELECT * FROM v_findings_ranked WHERE finding_id = ?", [row.finding_id])
    : null;
  send(res, { ...shapeIncident(row, gen), alerts, finding }, { params: q, note: NOTES.incidents });
}

// ----------------------------------------------------------------------------- rain pattern

const RAIN_GROUP_COLUMNS = ["grp", "irr_median", "irr_q05", "irr_q95", "p_irr_gt_1", "placebo_p", "verdict"];

async function rainPattern(req, res) {
  const { gen } = res.locals;
  parseQuery(req.query, {});
  const rows = await gen.query(
    "SELECT * FROM rain_pattern ORDER BY list_position(['pooled', 'cso_adjacent', 'other_sites'], grp)",
  );
  if (!rows.length) throw notFound("this snapshot has no rain-pattern result");
  const { sewage_share_rain_weeks, sewage_share_dry_weeks, ...shared } = rows[0];
  for (const c of RAIN_GROUP_COLUMNS) delete shared[c];
  const groups = rows.map((r) => Object.fromEntries(RAIN_GROUP_COLUMNS.map((c) => [c, r[c]])));
  const finding = await gen.one("SELECT * FROM v_findings_ranked WHERE finding_type = 'rain_pattern' ORDER BY display_rank LIMIT 1");
  send(res, {
    ...shared,
    sewage_smell_share: { rain_weeks: sewage_share_rain_weeks, dry_weeks: sewage_share_dry_weeks },
    groups,
    finding,
  }, { note: NOTES.rain });
}

// ----------------------------------------------------------------------------- router

export function insightsRouter() {
  const r = Router();
  r.get("/sites", listSites);
  r.get("/sites/:siteId", getSite);
  r.get("/sites/:siteId/timeseries", siteTimeseries);
  r.get("/sites/:siteId/observations", siteObservations);
  r.get("/scores", scoresForWeek);
  r.get("/weeks", listWeeks);
  r.get("/river", river);
  r.get("/findings", listFindings);
  r.get("/findings/:findingId", getFinding);
  r.get("/incidents", listIncidents);
  r.get("/incidents/:incidentId", getIncident);
  r.get("/rain-pattern", rainPattern);
  return r;
}
