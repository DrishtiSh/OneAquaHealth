// Data access layer. Everything comes from the Stage 9 Insight API (see src/lib/api.ts). If the
// API is down, the readers fall back to the JSON fixtures in src/data/ (exported from the
// pipeline's parquet files by `npm run export-data`) and say so via `source: "fallback"`, so
// the UI can show a clear "API offline" banner instead of passing mock numbers off as real.
//
// Each reader is wrapped in React.cache, so the root layout and a page share one API call per
// request.

import { cache } from "react";
import sitesData from "@/data/sites.json";
import weatherData from "@/data/weather.json";
import riverGraphData from "@/data/river-graph.json";
import exposureData from "@/data/exposure.json";
import mockRiskSummaryData from "@/data/mock-risk-summary.json";
import { apiGet, ApiUnavailable } from "@/lib/api";
import type {
  BenchmarkReport,
  ExposureFeature,
  Finding,
  Observation,
  RiskStatus,
  RiverGraphEdge,
  ScenarioOptions,
  Site,
  SiteDetail,
  SiteLatestRow,
  SiteRiskSummary,
  SnapshotInfo,
  TimeseriesWeek,
  WeatherWeek,
} from "@/lib/types";

export type DataSource = "api" | "fallback";

/** Where a reader's data came from, plus the API's provenance when it was live. */
export interface Provenance {
  source: DataSource;
  snapshot?: SnapshotInfo;
  disclaimer?: string;
  note?: string;
}

const FALLBACK_DISCLAIMER =
  "Based on volunteer observations, not laboratory tests. Not an official health advisory.";

// api.ts logs the outage itself (once, plus once on recovery). Per-reader detail is opt-in,
// because Node prints console.debug like any other line.
function logFallback(what: string, err: unknown) {
  if (process.env.OAH_API_DEBUG === "1") {
    console.debug(`[data] ${what}: using fallback (${(err as Error).message})`);
  }
}

// ----------------------------------------------------------------------------- status

/**
 * The single place an API row becomes a dashboard status. A detected change (confirmed or
 * possible) wins; otherwise too few reports means we say so rather than show "normal".
 */
export function toStatus(row: Pick<SiteLatestRow, "alert_level" | "evidence">): RiskStatus {
  if (row.alert_level === "confirmed" || row.alert_level === "possible") return "elevated_risk";
  if (row.evidence === "insufficient") return "insufficient_evidence";
  return "normal";
}

function toRiskSummary(row: SiteLatestRow): SiteRiskSummary {
  return {
    site_id: row.site_id,
    week_start: row.week_start,
    water_quality_score: row.W.q50,
    water_quality_uncertainty: [row.W.q05, row.W.q95],
    health_risk_score: row.H.q50,
    health_risk_uncertainty: [row.H.q05, row.H.q95],
    status: toStatus(row),
    finding: row.status?.headline ?? null,
    finding_body: row.status?.body ?? null,
    evidence: row.evidence,
    alert_level: row.alert_level,
    p_change: row.p_change,
    n_reports: row.n_reports,
    mixing_flag: row.mixing_flag,
  };
}

// ----------------------------------------------------------------------------- scenario options

const FALLBACK_OPTIONS: ScenarioOptions = {
  variants: [
    { id: "M1", role: "primary", rain_assumed: true, description: "Primary model, rain as a weak covariate." },
    { id: "M1_norain", role: "rain_ablation", rain_assumed: false, description: "Same model without rain." },
  ],
  sensitivity_levels: [
    { id: "sensitive", delta_W: 5 },
    { id: "normal", delta_W: 10 },
    { id: "strict", delta_W: 20 },
  ],
  default_variant: "M1",
  default_sensitivity: "normal",
};

/** The toggles the loaded snapshot supports (GET /meta). */
export const getScenarioOptions = cache(async (): Promise<ScenarioOptions> => {
  try {
    const { data } = await apiGet<ScenarioOptions>("/meta");
    return {
      variants: data.variants,
      sensitivity_levels: data.sensitivity_levels,
      default_variant: data.default_variant,
      default_sensitivity: data.default_sensitivity,
    };
  } catch (err) {
    logFallback("meta", err);
    return FALLBACK_OPTIONS;
  }
});

// ----------------------------------------------------------------------------- sites (latest week)

export interface SiteData extends Provenance {
  sites: Site[];
  /** Head -> mouth. */
  orderedSiteIds: string[];
  riskBySiteId: Record<string, SiteRiskSummary>;
  exposureBySiteId: Record<string, ExposureFeature[]>;
}

function fallbackSiteData(): SiteData {
  const sites = sitesData as Site[];
  const edges = riverGraphData as RiverGraphEdge[];
  const riskBySiteId: Record<string, SiteRiskSummary> = {};
  // JSON imports widen tuples to number[], hence the cast through unknown.
  for (const r of mockRiskSummaryData as unknown as SiteRiskSummary[]) riskBySiteId[r.site_id] = r;
  const exposureBySiteId: Record<string, ExposureFeature[]> = {};
  for (const e of exposureData as ExposureFeature[]) (exposureBySiteId[e.site_id] ??= []).push(e);
  return {
    source: "fallback",
    disclaimer: FALLBACK_DISCLAIMER,
    sites,
    orderedSiteIds: orderFromEdges(sites, edges),
    riskBySiteId,
    exposureBySiteId,
  };
}

/** Sites ordered head -> mouth, derived from the chain of edges. */
function orderFromEdges(sites: Site[], edges: RiverGraphEdge[]): string[] {
  const nextOf = new Map(edges.map((e) => [e.from_site_id, e.to_site_id]));
  const hasIncoming = new Set(edges.map((e) => e.to_site_id));
  const head = sites.map((s) => s.site_id).find((id) => !hasIncoming.has(id));
  if (!head) return sites.map((s) => s.site_id);

  const ordered = [head];
  let current = head;
  while (nextOf.has(current)) {
    current = nextOf.get(current)!;
    ordered.push(current);
  }
  return ordered;
}

/** Every site with its latest-week scores, status and nearby exposure points (GET /sites). */
export const getSiteData = cache(async (variant: string, sensitivity: string): Promise<SiteData> => {
  try {
    const env = await apiGet<SiteLatestRow[]>("/sites", { variant, sensitivity });
    const rows = [...env.data].sort((a, b) => a.display_order - b.display_order);
    return {
      source: "api",
      snapshot: env.snapshot,
      disclaimer: env.disclaimer,
      note: env.note,
      sites: rows.map((r) => ({
        site_id: r.site_id,
        name: r.name,
        lat: r.lat,
        lon: r.lon,
        watershed: r.watershed,
        distance_from_mouth_m: r.distance_from_mouth_m,
        is_cso_outfall_adjacent: r.is_cso_outfall_adjacent,
        known_context_note: r.known_context_note,
      })),
      orderedSiteIds: rows.map((r) => r.site_id),
      riskBySiteId: Object.fromEntries(rows.map((r) => [r.site_id, toRiskSummary(r)])),
      exposureBySiteId: Object.fromEntries(
        rows.map((r) => [r.site_id, r.exposure.map((e) => ({ site_id: r.site_id, ...e }))]),
      ),
    };
  } catch (err) {
    logFallback("sites", err);
    return fallbackSiteData();
  }
});

// ----------------------------------------------------------------------------- one site

export interface SiteDetailResult extends Provenance {
  /** null when the API is offline (the page then renders from SiteData alone). */
  detail: SiteDetail | null;
}

/** River neighbours, findings and incidents for one site (GET /sites/{id}). */
export const getSiteDetail = cache(
  async (siteId: string, variant: string, sensitivity: string): Promise<SiteDetailResult> => {
    try {
      const env = await apiGet<SiteDetail>(`/sites/${encodeURIComponent(siteId)}`, { variant, sensitivity });
      return { source: "api", snapshot: env.snapshot, disclaimer: env.disclaimer, note: env.note, detail: env.data };
    } catch (err) {
      if (err instanceof ApiUnavailable && err.status === 404) return { source: "api", detail: null };
      logFallback(`site ${siteId}`, err);
      return { source: "fallback", detail: null };
    }
  },
);

export type RainfallWeek = Pick<WeatherWeek, "week_start" | "weekly_rainfall_mm" | "heavy_rain_week">;

export interface SiteTimeseries extends Provenance {
  /** Weekly W/H intervals and alerts; empty when the API is offline. */
  weeks: TimeseriesWeek[];
  rainfall: RainfallWeek[];
}

/** Weekly scores, alerts and rainfall for one site (GET /sites/{id}/timeseries). */
export const getSiteTimeseries = cache(
  async (siteId: string, variant: string, sensitivity: string): Promise<SiteTimeseries> => {
    try {
      const env = await apiGet<TimeseriesWeek[]>(`/sites/${encodeURIComponent(siteId)}/timeseries`, {
        variant,
        sensitivity,
      });
      return {
        source: "api",
        note: env.note,
        weeks: env.data,
        rainfall: env.data
          .filter((w) => w.weekly_rainfall_mm != null)
          .map((w) => ({
            week_start: w.week_start,
            weekly_rainfall_mm: w.weekly_rainfall_mm!,
            heavy_rain_week: Boolean(w.heavy_rain_week),
          })),
      };
    } catch (err) {
      logFallback(`timeseries ${siteId}`, err);
      return {
        source: "fallback",
        weeks: [],
        rainfall: (weatherData as WeatherWeek[])
          .filter((w) => w.site_id === siteId)
          .sort((a, b) => a.week_start.localeCompare(b.week_start)),
      };
    }
  },
);

export interface ObservationsResult extends Provenance {
  observations: Observation[];
  total: number;
}

/** The newest de-identified citizen reports for one site (GET /sites/{id}/observations). */
export const getSiteObservations = cache(async (siteId: string, limit = 5): Promise<ObservationsResult> => {
  try {
    const env = await apiGet<Observation[]>(`/sites/${encodeURIComponent(siteId)}/observations`, { limit });
    return { source: "api", note: env.note, observations: env.data, total: env.total ?? env.data.length };
  } catch (err) {
    logFallback(`observations ${siteId}`, err);
    return { source: "fallback", observations: [], total: 0 };
  }
});

// ----------------------------------------------------------------------------- network-wide

export interface OverviewFindings extends Provenance {
  /** Highest-ranked findings (recent incidents first). */
  top: Finding[];
  /** The rain -> overflow pattern finding, if the snapshot has one. */
  rainPattern: Finding | null;
}

export interface BenchmarkResult extends Provenance {
  /** null when the API is offline, or the snapshot has no benchmark (a real-data run). */
  report: BenchmarkReport | null;
}

/** Stage 11's accuracy report against the simulator's ground truth (GET /benchmark). */
export const getBenchmark = cache(async (): Promise<BenchmarkResult> => {
  try {
    const env = await apiGet<BenchmarkReport>("/benchmark");
    return { source: "api", snapshot: env.snapshot, note: env.note, report: env.data };
  } catch (err) {
    if (err instanceof ApiUnavailable && err.status === 404) return { source: "api", report: null };
    logFallback("benchmark", err);
    return { source: "fallback", report: null };
  }
});

/** Ranked fact-locked findings for the overview (GET /findings). */
export const getOverviewFindings = cache(async (limit = 4): Promise<OverviewFindings> => {
  try {
    const [top, rain] = await Promise.all([
      apiGet<Finding[]>("/findings", { type: "incident", limit }),
      apiGet<Finding[]>("/findings", { type: "rain_pattern", limit: 1 }),
    ]);
    return { source: "api", note: top.note, top: top.data, rainPattern: rain.data[0] ?? null };
  } catch (err) {
    logFallback("findings", err);
    return { source: "fallback", top: [], rainPattern: null };
  }
});
