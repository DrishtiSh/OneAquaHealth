"""Pydantic schemas for Stage-1 ingestion outputs, plus validation guardrails.

`Observation` is the ONLY schema stages 2-9 may read. `GroundTruthWeek` and
`ContaminationEvent` hold the simulator's hidden truth and may only be read by
pipeline/benchmark -- never by the model, detectors, or any stage in between.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

GROUND_TRUTH_ONLY_COLUMNS = {
    "W_true",
    "H_true",
    "contamination_event_active",
    "event_id",
}


class Site(BaseModel):
    model_config = ConfigDict(frozen=True)

    site_id: str
    name: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    watershed: str
    distance_from_mouth_m: float = Field(ge=0)
    is_cso_outfall_adjacent: bool
    known_context_note: Optional[str] = None


class Observation(BaseModel):
    model_config = ConfigDict(frozen=True)

    observation_id: str
    site_id: str
    observed_at: datetime
    week_start: date
    observer_id: str
    # NOTE: 1 = clear ... 5 = murky/dirty (a dirtiness rubric despite the field name).
    water_clarity: Optional[int] = Field(default=None, ge=1, le=5)
    smell: Optional[Literal["none", "earthy", "musty", "chemical", "sewage", "dead_fish"]] = None
    smell_intensity: Optional[int] = Field(default=None, ge=0, le=3)
    trash_level: Optional[int] = Field(default=None, ge=0, le=4)
    insect_presence: Optional[bool] = None
    insect_diversity: Optional[int] = Field(default=None, ge=0, le=3)
    notes: Optional[str] = Field(default=None, max_length=280)
    source: Literal["simulated", "real"]
    ingested_at: datetime
    raw_payload: Optional[str] = None


class ContaminationEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str
    source_site_id: str
    start_week: date
    end_week: date
    event_type: Literal[
        "sewage_overflow",
        "urban_runoff",
        "upstream_industrial_discharge",
        "background_noise_spike",
    ]
    rain_triggered: bool
    peak_magnitude: float = Field(ge=0, le=100)
    affected_site_ids: list[str]


class GroundTruthWeek(BaseModel):
    model_config = ConfigDict(frozen=True)

    site_id: str
    week_start: date
    W_true: float = Field(ge=0, le=100)
    H_true: float = Field(ge=0, le=100)
    contamination_event_active: bool
    event_id: Optional[str] = None


class WeatherWeek(BaseModel):
    """Stage 2 output: real (or fallback) rainfall features per site/week."""

    model_config = ConfigDict(frozen=True)

    site_id: str
    week_start: date
    weekly_rainfall_mm: float = Field(ge=0)
    max_daily_rainfall_mm: float = Field(ge=0)
    rain_days_count: int = Field(ge=0, le=7)
    antecedent_rainfall_mm_3wk: float = Field(ge=0)
    heavy_rain_week: bool
    source: Literal["real", "synthetic_fallback"]


class RiverGraphEdge(BaseModel):
    """Stage 3 output: directed site-to-site edges, pointing downstream."""

    model_config = ConfigDict(frozen=True)

    from_site_id: str  # upstream site
    to_site_id: str  # the next site downstream
    distance_m: float = Field(ge=0)


class ExposureFeature(BaseModel):
    """Stage 4 output: nearest playground/school/park per site, real or unavailable."""

    model_config = ConfigDict(frozen=True)

    site_id: str
    category: Literal["playground", "school", "park"]
    nearest_poi_distance_m: Optional[float] = Field(default=None, ge=0)
    nearest_poi_name: Optional[str] = None
    poi_count_within_threshold: int = Field(ge=0)
    is_exposure_relevant: bool
    data_source: Literal["real", "unavailable"]


class ModelScore(BaseModel):
    """Stage 5 output: posterior summaries of the latent scores per site/week.

    W = water-quality index, H = human-health-relevant hazard index, both on 0-100
    (higher W = cleaner, higher H = riskier). They are relative indices anchored to the
    citizen-facing rubrics, not calibrated measurements. `evidence` says how much direct
    observation backs the row, so downstream stages can show an honest "insufficient
    evidence" state instead of a confident-looking number.
    """

    model_config = ConfigDict(frozen=True)

    site_id: str
    week_start: date
    W_mean: float = Field(ge=0, le=100)
    W_sd: float = Field(ge=0)
    W_q05: float = Field(ge=0, le=100)
    W_q25: float = Field(ge=0, le=100)
    W_q50: float = Field(ge=0, le=100)
    W_q75: float = Field(ge=0, le=100)
    W_q95: float = Field(ge=0, le=100)
    H_mean: float = Field(ge=0, le=100)
    H_sd: float = Field(ge=0)
    H_q05: float = Field(ge=0, le=100)
    H_q25: float = Field(ge=0, le=100)
    H_q50: float = Field(ge=0, le=100)
    H_q75: float = Field(ge=0, le=100)
    H_q95: float = Field(ge=0, le=100)
    e_mean: float = Field(ge=0)  # posterior mean contamination excursion (0 for M0)
    n_reports: int = Field(ge=0)
    n_informative_fields: int = Field(ge=0)
    evidence: Literal["sufficient", "weak", "insufficient"]
    mixing_flag: bool  # posterior for this row mixed poorly (bimodal: event vs misreport)
    model_variant: Literal["M0", "M1", "M1_norain"]

    @model_validator(mode="after")
    def _quantiles_ordered(self) -> "ModelScore":
        for score in ("W", "H"):
            qs = [getattr(self, f"{score}_q{q}") for q in ("05", "25", "50", "75", "95")]
            if any(b < a - 1e-9 for a, b in zip(qs, qs[1:])):
                raise ValueError(f"{score} quantiles are not monotone: {qs}")
        return self


class DetectorAlert(BaseModel):
    """Stage 6 output: per site/week change detection on the M1 posterior.

    `p_change` = posterior probability that the contamination excursion pulled W down by more than
    `config.DETECT_DELTA` points. Rows with no alert are kept (alert_level="none") so the table
    stays dense and the dashboard can show "checked, nothing found".
    """

    model_config = ConfigDict(frozen=True)

    site_id: str
    week_start: date
    p_change: float = Field(ge=0, le=1)
    drop_W_median: float
    drop_W_q05: float
    drop_W_q95: float
    rise_H_median: Optional[float] = None  # None when the variant has no lam_H draws
    alert_level: Literal["confirmed", "possible", "none"]
    evidence: Literal["sufficient", "weak", "insufficient"]
    mixing_flag: bool
    n_reports: int = Field(ge=0)
    episode_id: Optional[str] = None
    model_variant: Literal["M0", "M1", "M1_norain"]


class Incident(BaseModel):
    """Stage 6 output: linked episodes across sites, with a posterior over the entry point."""

    model_config = ConfigDict(frozen=True)

    incident_id: str
    start_week: date
    end_week: date
    affected_site_ids: list[str]
    n_episodes: int = Field(ge=1)
    max_alert_level: Literal["confirmed", "possible"]
    top_source: Optional[str] = None  # None if no draw shows a drop above threshold anywhere
    top_source_prob: float = Field(ge=0, le=1)
    p_no_source: float = Field(ge=0, le=1)
    credible_set: list[str]
    source_probs_json: str  # {"site_id": probability, ...}
    entry_segment: str
    upstream_unobserved: bool
    decays_downstream: Optional[bool] = None
    rain_week: bool
    peak_drop_W: float
    model_variant: Literal["M0", "M1", "M1_norain"]


def _records_for_validation(df: pd.DataFrame) -> list[dict]:
    """pandas NaN -> None so pydantic's Optional fields validate cleanly."""
    clean = df.astype(object).where(df.notna(), None)
    return clean.to_dict(orient="records")


def validate_dataframe(df: pd.DataFrame, model: type[BaseModel], *, name: str) -> None:
    """Validate every row of df against a pydantic model.

    Raises ValueError with row context on the first failure.
    """
    for i, record in enumerate(_records_for_validation(df)):
        try:
            model(**record)
        except Exception as exc:  # pydantic.ValidationError, or a stray TypeError
            raise ValueError(f"{name} row {i} failed schema validation: {exc}") from exc


def assert_no_ground_truth_leak(observations_df: pd.DataFrame) -> None:
    """Guardrail: observations handed to stages 2-9 must never carry ground-truth columns."""
    leaked = GROUND_TRUTH_ONLY_COLUMNS.intersection(observations_df.columns)
    if leaked:
        raise ValueError(
            f"Ground-truth columns leaked into observations: {sorted(leaked)}. "
            "Stages 2-9 (and everything except pipeline/benchmark) must never see these."
        )
