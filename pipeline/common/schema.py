"""Pydantic schemas for Stage-1 ingestion outputs, plus validation guardrails.

`Observation` is the ONLY schema stages 2-9 may read. `GroundTruthWeek` and
`ContaminationEvent` hold the simulator's hidden truth and may only be read by
pipeline/benchmark -- never by the model, detectors, or any stage in between.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

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
