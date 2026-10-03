// Types mirroring the Python pipeline's schemas (pipeline/common/schema.py) and the Stage 9
// Insight API's responses (api/openapi.json). Keep in sync with both as they change.

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

// --- Stage 9 Insight API -----------------------------------------------------------------------

export type Evidence = "sufficient" | "weak" | "insufficient";
export type AlertLevel = "confirmed" | "possible" | "none";

/** Dashboard toggles: model variant (rain assumption on/off) and detection sensitivity. */
export interface Scenario {
  variant: string;
  sensitivity: string;
}

export interface SnapshotInfo {
  id: string;
  schema_version: string;
  latest_week: string;
  created_at_utc: string;
}

/** Every data response from the API comes in this envelope. */
export interface ApiEnvelope<T> {
  snapshot: SnapshotInfo;
  disclaimer: string;
  params?: Record<string, unknown>;
  note?: string;
  count?: number;
  total?: number;
  data: T;
}

/** A posterior score with its 90% interval (mean and sd are absent on some endpoints). */
export interface Band {
  mean?: number;
  sd?: number;
  q05: number;
  q50: number;
  q95: number;
}

/** GET /sites row: the latest week for one site. */
export interface SiteLatestRow extends Site {
  display_order: number;
  exposure_weight: number;
  week_start: string;
  W: Band;
  H: Band;
  evidence: Evidence;
  mixing_flag: boolean;
  n_reports: number;
  p_change: number | null;
  alert_level: AlertLevel | null;
  status: { headline: string; body: string } | null;
  exposure: Omit<ExposureFeature, "site_id">[];
}

export interface Neighbour {
  site_id: string;
  name: string;
  distance_m: number;
}

export interface FactEntry {
  shown: string;
  source: string;
  value: unknown;
}

export type FindingType = "incident" | "site_status" | "rain_pattern" | "coverage";
export type FindingPriority = "high" | "medium" | "low" | "info";

export interface Finding {
  display_rank: number;
  finding_id: string;
  finding_type: FindingType;
  scope_id: string;
  priority: FindingPriority;
  is_recent: boolean;
  confidence_label: string | null;
  week_start: string | null;
  week_end: string | null;
  headline: string;
  body: string;
  precaution: string | null;
  caveats: string[];
  facts: Record<string, FactEntry>;
  language: string;
  model_variant: string;
}

export interface Incident {
  incident_id: string;
  start_week: string;
  end_week: string;
  affected_site_ids: string[];
  n_episodes: number;
  max_alert_level: "confirmed" | "possible";
  top_source: string;
  top_source_name: string | null;
  top_source_prob: number;
  entry_segment: string | null;
  upstream_unobserved: boolean;
  rain_week: boolean;
  peak_drop_W: number;
  model_variant: string;
  finding_id: string | null;
  is_recent: boolean;
  source_ranking: { site_id: string; name: string | null; prob: number }[];
}

/** GET /sites/{id}: the latest-week row plus river neighbours, findings and incidents. */
export interface SiteDetail extends SiteLatestRow {
  upstream: Neighbour[];
  downstream: Neighbour[];
  findings: Finding[];
  incidents: Incident[];
}

/** GET /sites/{id}/timeseries row. */
export interface TimeseriesWeek {
  week_start: string;
  W: Band;
  H: Band;
  evidence: Evidence;
  mixing_flag: boolean;
  n_reports: number;
  p_change: number | null;
  alert_level: AlertLevel | null;
  episode_id: string | null;
  weekly_rainfall_mm: number | null;
  heavy_rain_week: boolean | null;
  rain_exposed: boolean | null;
}

/** GET /sites/{id}/observations row (de-identified volunteer report). */
export interface Observation {
  observation_id: string;
  observed_date: string;
  week_start: string;
  water_clarity: number | null; // 1 = clear, 5 = murky
  smell: string | null;
  smell_intensity: number | null; // 0-3
  trash_level: number | null;
  insect_presence: boolean | null;
  insect_diversity: number | null;
  notes: string | null;
  source: string;
}

export interface ScenarioOptions {
  variants: { id: string; role: string; rain_assumed: boolean; description: string }[];
  sensitivity_levels: { id: string; delta_W: number }[];
  default_variant: string;
  default_sensitivity: string;
}

// --- GET /benchmark: Stage 11 report (pipeline/benchmark/benchmark.py) -------------------------

export type EventOutcome = "detected" | "detected (possible only)" | "missed";

export interface BenchmarkEvent {
  event_id: string;
  event_type: string;
  source_site_id: string;
  start_week: string;
  end_week: string;
  rain_triggered: boolean;
  peak_drop_W: number;
  footprint_site_weeks: number;
  reports_in_footprint: number;
  max_p_change: number;
  outcome: EventOutcome;
  miss_reason: string | null;
  matched_incidents: string[];
  found_source?: string;
  source_correct?: boolean;
}

export interface BenchmarkFalseAlarm {
  incident_id: string;
  start_week: string;
  end_week: string;
  affected_site_ids: string[];
  max_alert_level: string;
  largest_true_drop_W: number;
  what_really_happened: string;
}

export interface BenchmarkDetectionRow {
  model_variant: string;
  sensitivity: string;
  delta_W: number;
  rule: "confirmed" | "confirmed_or_possible";
  n_truly_changed: number;
  tp: number;
  fp: number;
  fn: number;
  precision: number | null;
  recall: number | null;
  recall_observed_weeks: number | null;
  roc_auc: number | null;
  average_precision: number | null;
}

export interface BenchmarkScoreErrors {
  n: number;
  mae?: number;
  bias?: number;
  spearman?: number | null;
  coverage_90?: number;
  mean_interval_width?: number;
}

export interface BenchmarkReport {
  data: { source: string; seed: number; n_sites: number; n_weeks: number; first_week: string; latest_week: string; n_reports: number };
  thresholds: { delta_W: number; p_confirmed: number; p_possible: number; match_tolerance_weeks: number };
  caveats: string[];
  headline: {
    n_true_events: number;
    n_events_detected: number;
    n_incidents: number;
    n_false_alarms: number;
    event_recall: number | null;
    incident_precision: number | null;
    site_week_precision: number | null;
    site_week_recall: number | null;
    site_week_recall_observed: number | null;
    source_top1_accuracy: number | null;
    W_mae: number;
    W_coverage_90: number;
    H_coverage_90: number;
  };
  events: {
    n_detected_confirmed: number;
    n_observable_events: number;
    event_recall_observable: number | null;
    events: BenchmarkEvent[];
    false_alarms: BenchmarkFalseAlarm[];
    source_attribution: {
      n_matched: number;
      top1_accuracy: number | null;
      credible_set_coverage: number | null;
      nominal_credible_mass: number;
      mean_prob_on_true_source: number | null;
      wrong_with_upstream_unobserved: number;
    };
  };
  site_week_detection: {
    by_variant_and_sensitivity: BenchmarkDetectionRow[];
    calibration: { band: string; n_site_weeks: number; n_truly_changed: number; share_truly_changed: number | null; mean_p_change: number | null }[];
    baseline: { rule: string; precision: number | null; recall: number | null; recall_observed_weeks: number | null; fp: number };
    n_site_weeks: number;
    n_observed_site_weeks: number;
  };
  score_accuracy: Record<string, Record<"W" | "H", Record<string, BenchmarkScoreErrors>>>;
  rain_pattern: {
    model_variant: string;
    share_of_events_rain_triggered: number;
    n_events: number;
    groups: {
      group: string;
      true_irr_observed_weeks: number;
      estimated_irr_median: number;
      estimated_irr_q05: number;
      estimated_irr_q95: number;
      interval_contains_truth: boolean;
      verdict: string;
      verdict_judged: string;
    }[];
  };
  latest_week: {
    week_start: string;
    summary: Record<string, number>;
    sites: { site_id: string; status_shown: string; true_drop_W: number; really_changed: boolean; judged: string }[];
  };
}

// --- What the UI renders per site ---------------------------------------------------------------

export type RiskStatus = "insufficient_evidence" | "normal" | "elevated_risk";

export interface SiteRiskSummary {
  site_id: string;
  week_start: string; // ISO date
  water_quality_score: number; // W median, 0-100
  water_quality_uncertainty: [number, number]; // 90% interval [low, high]
  health_risk_score: number; // H median, 0-100
  health_risk_uncertainty: [number, number]; // 90% interval [low, high]
  status: RiskStatus;
  finding: string | null; // plain-language status headline
  finding_body?: string | null;
  evidence?: Evidence;
  alert_level?: AlertLevel | null;
  p_change?: number | null;
  n_reports?: number;
  mixing_flag?: boolean;
}
