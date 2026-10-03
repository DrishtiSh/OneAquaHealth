// Query-string and path parameter parsing. Every rejection is a 400 that names the allowed values,
// so a typo in a dashboard toggle fails loudly instead of silently falling back to a default.

export class HttpError extends Error {
  constructor(status, message, details = undefined) {
    super(message);
    this.status = status;
    this.details = details;
  }
}

export const badRequest = (message, details) => new HttpError(400, message, details);
export const notFound = (message, details) => new HttpError(404, message, details);

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

// Parsers take (raw string | undefined, name) and return the parsed value.
export const param = {
  oneOf: (values, fallback = undefined) => (raw, name) => {
    if (raw === undefined) return fallback;
    if (!values.includes(raw)) throw badRequest(`${name} must be one of: ${values.join(", ")}`, { [name]: raw, allowed: values });
    return raw;
  },

  bool: (fallback = undefined) => (raw, name) => {
    if (raw === undefined) return fallback;
    if (raw === "true") return true;
    if (raw === "false") return false;
    throw badRequest(`${name} must be true or false`, { [name]: raw, allowed: ["true", "false"] });
  },

  date: (fallback = undefined) => (raw, name) => {
    if (raw === undefined) return fallback;
    const d = new Date(`${raw}T00:00:00Z`);
    if (!DATE_RE.test(raw) || Number.isNaN(d.getTime()) || d.toISOString().slice(0, 10) !== raw) {
      throw badRequest(`${name} must be a date as YYYY-MM-DD`, { [name]: raw });
    }
    return raw;
  },

  int: ({ min = 0, max = Number.MAX_SAFE_INTEGER, fallback = undefined } = {}) => (raw, name) => {
    if (raw === undefined) return fallback;
    const n = Number(raw);
    if (!/^\d+$/.test(raw) || !Number.isSafeInteger(n) || n < min || n > max) {
      throw badRequest(`${name} must be an integer from ${min} to ${max}`, { [name]: raw });
    }
    return n;
  },

  // A site id that must exist in the loaded snapshot (404 otherwise, like a path id).
  site: (gen) => (raw, name) => {
    if (raw === undefined) return undefined;
    if (!gen.siteIds.has(raw)) throw notFound(`unknown site ${raw}`, { [name]: raw, allowed: [...gen.siteIds] });
    return raw;
  },
};

// Parse req.query against `spec` ({ name: parser }). Unknown or repeated parameters are rejected.
export function parseQuery(query, spec) {
  const unknown = Object.keys(query).filter((k) => !(k in spec));
  if (unknown.length) {
    throw badRequest(`unknown query parameter${unknown.length > 1 ? "s" : ""}: ${unknown.join(", ")}`, {
      allowed: Object.keys(spec),
    });
  }
  const out = {};
  for (const [name, parse] of Object.entries(spec)) {
    const raw = query[name];
    if (raw !== undefined && typeof raw !== "string") throw badRequest(`${name} may be given only once`);
    out[name] = parse(raw, name);
  }
  return out;
}

// Toggles shared by most endpoints; the allowed values come from the loaded snapshot itself.
export function toggles(gen) {
  const { primary_variant, rain_variant, thresholds } = gen.manifest;
  const levels = Object.entries(thresholds.SENSITIVITY_DELTAS).sort((a, b) => a[1] - b[1]).map(([id]) => id);
  return {
    variant: param.oneOf([primary_variant, rain_variant], primary_variant),
    sensitivity: param.oneOf(levels, "normal"),
  };
}

export const page = (maxLimit, defaultLimit) => ({
  limit: param.int({ min: 1, max: maxLimit, fallback: defaultLimit }),
  offset: param.int({ min: 0, fallback: 0 }),
});

// Inclusive week range, defaulting to the whole grid; `from` after `to` is a 400.
export function weekRange(gen) {
  return {
    from: param.date(gen.manifest.first_week),
    to: param.date(gen.manifest.latest_week),
  };
}

export function checkRange({ from, to }) {
  if (from > to) throw badRequest("from must not be after to", { from, to });
}
