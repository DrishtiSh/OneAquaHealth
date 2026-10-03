// Types mirroring the Python pipeline's schemas (pipeline/common/schema.py)
// field-for-field. This file is the contract between this dashboard and the
// backend teammate's work -- keep it in sync with schema.py as stages land.

export interface Site {
  site_id: string;
  name: string;
  lat: number;
  lon: number;
  watershed: string;
  distance_from_mouth_m: number;
  is_cso_outfall_adjacent: boolean;
  known_context_note: string | null;
}

export interface WeatherWeek {
  site_id: string;
  week_start: string; // ISO date
  weekly_rainfall_mm: number;
  max_daily_rainfall_mm: number;
  rain_days_count: number;
  antecedent_rainfall_mm_3wk: number;
  heavy_rain_week: boolean;
  source: "real" | "synthetic_fallback";
}

export interface RiverGraphEdge {
  from_site_id: string; // upstream site
  to_site_id: string; // the next site downstream
  distance_m: number;
}

export type ExposureCategory = "playground" | "school" | "park";

export interface ExposureFeature {
  site_id: string;
  category: ExposureCategory;
  nearest_poi_distance_m: number | null;
  nearest_poi_name: string | null;
  poi_count_within_threshold: number;
  is_exposure_relevant: boolean;
  data_source: "real" | "unavailable";
}

// --- Not yet real: the agreed future shape of Stage 9's Insight API ---
// Stages 5-7 (Bayesian model, detectors, NLG) haven't been built yet. This is
// the contract we're building the frontend against; once the backend serves
// GET {NEXT_PUBLIC_API_URL}/risk-summary matching this shape, src/lib/data.ts
// starts using the real thing automatically.

export type RiskStatus = "insufficient_evidence" | "normal" | "elevated_risk";

export interface SiteRiskSummary {
  site_id: string;
  week_start: string; // ISO date
  water_quality_score: number; // W, 0-100
  water_quality_uncertainty: [number, number]; // [low, high]
  health_risk_score: number; // H, 0-100
  health_risk_uncertainty: [number, number]; // [low, high]
  status: RiskStatus;
  finding: string; // plain-language, e.g. "risk near a playground"
}
