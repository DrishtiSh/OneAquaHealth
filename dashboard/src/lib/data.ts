// Data access layer. The real-data readers (sites, weather, river graph,
// exposure) load Stage 1-4's actual output directly -- regenerate them with
// `npm run export-data` whenever the pipeline re-runs.
//
// getRiskSummaries() is the "connect later" point: it tries the real backend
// API first, and only falls back to clearly-labeled mock data if that isn't
// reachable yet. Once the teammate's Stage 9 API is live at
// NEXT_PUBLIC_API_URL, this starts returning real data automatically --
// no page or component needs to change.

import { cache } from "react";
import sitesData from "@/data/sites.json";
import weatherData from "@/data/weather.json";
import riverGraphData from "@/data/river-graph.json";
import exposureData from "@/data/exposure.json";
import mockRiskSummaryData from "@/data/mock-risk-summary.json";
import type {
  ExposureFeature,
  RiverGraphEdge,
  Site,
  SiteRiskSummary,
  WeatherWeek,
} from "@/lib/types";

const sites = sitesData as Site[];
const weather = weatherData as WeatherWeek[];
const riverGraph = riverGraphData as RiverGraphEdge[];
const exposure = exposureData as ExposureFeature[];
const mockRiskSummary = mockRiskSummaryData as (SiteRiskSummary & {
  is_mock: true;
})[];

export function getSites(): Site[] {
  return sites;
}

export function getSite(siteId: string): Site | undefined {
  return sites.find((s) => s.site_id === siteId);
}

export function getWeatherForSite(siteId: string): WeatherWeek[] {
  return weather
    .filter((w) => w.site_id === siteId)
    .sort((a, b) => a.week_start.localeCompare(b.week_start));
}

export function getRiverGraph(): RiverGraphEdge[] {
  return riverGraph;
}

/** Sites ordered head -> mouth, derived from the chain of edges. */
export function getOrderedSiteIds(): string[] {
  const nextOf = new Map(riverGraph.map((e) => [e.from_site_id, e.to_site_id]));
  const hasIncoming = new Set(riverGraph.map((e) => e.to_site_id));
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

export function getExposureForSite(siteId: string): ExposureFeature[] {
  return exposure.filter((e) => e.site_id === siteId);
}

export interface RiskSummaryResult {
  data: SiteRiskSummary[];
  isMock: boolean;
}

/**
 * Tries the real Stage 9 Insight API first; falls back to mock data if it's
 * not configured or not reachable yet (the backend isn't done). This is the
 * only function that needs to exist for "connecting" the frontend and
 * backend later -- no other code changes when the real API comes online.
 *
 * Wrapped in React.cache so the root layout and a page can both call this
 * within the same request without triggering the fetch/mock lookup twice.
 */
export const getRiskSummaries = cache(async (): Promise<RiskSummaryResult> => {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL;
  if (apiUrl) {
    try {
      const res = await fetch(`${apiUrl}/risk-summary`, { cache: "no-store" });
      if (res.ok) {
        const data = (await res.json()) as SiteRiskSummary[];
        return { data, isMock: false };
      }
    } catch {
      // Backend not up yet -- fall through to mock data below.
    }
  }
  return { data: mockRiskSummary, isMock: true };
});

export async function getRiskSummaryForSite(
  siteId: string
): Promise<{ data: SiteRiskSummary | undefined; isMock: boolean }> {
  const { data, isMock } = await getRiskSummaries();
  return { data: data.find((r) => r.site_id === siteId), isMock };
}
