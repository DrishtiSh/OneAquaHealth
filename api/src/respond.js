// Response envelope and row shaping shared by the routers.

// Every data response says which snapshot it came from and carries the standing disclaimer.
export function send(res, data, extra = {}) {
  const { manifest } = res.locals.gen;
  res.json({
    snapshot: {
      id: manifest.snapshot_id,
      schema_version: manifest.schema_version,
      latest_week: manifest.latest_week,
      created_at_utc: manifest.created_at_utc,
    },
    disclaimer: manifest.disclaimer,
    ...extra,
    data,
  });
}

const BAND_RE = /^([WH])_(mean|sd|q\d\d)$/;

// Group flat posterior columns (W_mean, W_q05, ..., H_q95) into { W: {...}, H: {...} }, so every
// score travels with its interval.
export function nestBands(row) {
  const out = {};
  for (const [key, value] of Object.entries(row)) {
    const m = BAND_RE.exec(key);
    if (m) (out[m[1]] ??= {})[m[2]] = value;
    else out[key] = value;
  }
  return out;
}

// Group rows into { key: [rows without the key] }.
export function groupBy(rows, key) {
  const out = {};
  for (const { [key]: k, ...rest } of rows) (out[k] ??= []).push(rest);
  return out;
}
