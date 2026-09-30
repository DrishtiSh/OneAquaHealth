"""Stage 5 input assembly -- the ONLY place the model package reads pipeline data.

Reads observations, weather, sites and (for the exposure weights) exposure features,
and turns them into dense index arrays. It never touches the simulator's hidden ground
truth; `test_model.py::test_model_package_never_reads_ground_truth` enforces that
structurally for everything under pipeline/model/.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from pipeline.common import config, io_utils, schema

# Static exposure weighting (Stage 7 consumes this; it is NOT used in the model fit).
EXPOSURE_CATEGORY_WEIGHTS = {"playground": 1.0, "school": 0.7, "park": 0.5}
EXPOSURE_DECAY_M = 250.0  # matches exposure.PROXIMITY_THRESHOLD_M


@dataclass(frozen=True)
class ModelInputs:
    """Dense, index-based view of the data the Bayesian model conditions on."""

    site_ids: list[str]  # ordered head -> mouth
    weeks: list[date]
    # One entry per report (R,). NaN = field not reported (ignorable missingness).
    site_idx: np.ndarray
    week_idx: np.ndarray
    observer_idx: np.ndarray
    n_observers: int
    clarity: np.ndarray  # 1..5, 1 = clear, 5 = murky
    smell_intensity: np.ndarray  # 0..3
    sewage: np.ndarray  # 1 if smell == "sewage", 0 for another smell, NaN if unreported
    trash: np.ndarray  # 0..4
    presence: np.ndarray  # 0/1 insects seen
    diversity: np.ndarray  # 0..3, only where insects were not reported absent
    # Time-only weather covariates (T,) -- Open-Meteo is identical across the 10 sites.
    heavy_rain: np.ndarray
    antecedent_z: np.ndarray
    # Per site-week bookkeeping (S, T) for the evidence flag.
    n_reports: np.ndarray
    n_informative: np.ndarray

    @property
    def n_sites(self) -> int:
        return len(self.site_ids)

    @property
    def n_weeks(self) -> int:
        return len(self.weeks)

    @property
    def n_reports_total(self) -> int:
        return len(self.site_idx)


def _as_dates(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series).dt.normalize()


def build_inputs(
    observations_df: pd.DataFrame,
    weather_df: pd.DataFrame,
    sites_df: pd.DataFrame,
    *,
    site_ids: list[str] | None = None,
    n_weeks: int | None = None,
) -> ModelInputs:
    """Pure function (no disk access) so tests can feed small synthetic frames.

    `site_ids` / `n_weeks` optionally restrict to a slice (the first n_weeks of the weather
    grid), used for fast development fits.
    """
    schema.assert_no_ground_truth_leak(observations_df)

    ordered = sites_df.sort_values("distance_from_mouth_m", ascending=False)
    all_site_ids = ordered["site_id"].tolist()
    keep_sites = [s for s in all_site_ids if site_ids is None or s in site_ids]
    if not keep_sites:
        raise ValueError("No sites selected for the model.")
    site_pos = {s: i for i, s in enumerate(keep_sites)}

    weather = weather_df.assign(week_start=_as_dates(weather_df["week_start"]))
    grid = sorted(weather["week_start"].unique())
    if n_weeks is not None:
        grid = grid[:n_weeks]
    week_pos = {w: i for i, w in enumerate(grid)}
    S, T = len(keep_sites), len(grid)

    obs = observations_df.assign(week_start=_as_dates(observations_df["week_start"]))
    obs = obs[obs["site_id"].isin(site_pos) & obs["week_start"].isin(week_pos)].reset_index(drop=True)

    site_idx = obs["site_id"].map(site_pos).to_numpy(dtype=int)
    week_idx = obs["week_start"].map(week_pos).to_numpy(dtype=int)
    observer_codes, observers = pd.factorize(obs["observer_id"])

    def numeric(col: str) -> np.ndarray:
        return pd.to_numeric(obs[col], errors="coerce").to_numpy(dtype=float, copy=True)

    smell = obs["smell"]
    sewage = np.where(smell.isna(), np.nan, (smell == "sewage").astype(float))
    presence = obs["insect_presence"].map({True: 1.0, False: 0.0}).to_numpy(dtype=float)
    diversity = numeric("insect_diversity")
    diversity[presence == 0.0] = np.nan  # deterministic 0 when insects absent -> uninformative

    # Weather is identical across sites (same grid cell) -> collapse to a length-T series.
    by_week = weather.groupby("week_start").agg(
        heavy=("heavy_rain_week", "mean"), ante=("antecedent_rainfall_mm_3wk", "mean")
    )
    by_week = by_week.reindex(grid)
    heavy_rain = (by_week["heavy"].to_numpy(dtype=float) >= 0.5).astype(float)
    log_ante = np.log1p(by_week["ante"].to_numpy(dtype=float))
    antecedent_z = (log_ante - log_ante.mean()) / (log_ante.std() or 1.0)

    n_reports = np.zeros((S, T), dtype=int)
    n_informative = np.zeros((S, T), dtype=int)
    informative = (
        ~np.isnan(numeric("water_clarity")) * 1
        + ~np.isnan(numeric("smell_intensity")) * 1
        + ~np.isnan(sewage) * 1
    )
    np.add.at(n_reports, (site_idx, week_idx), 1)
    np.add.at(n_informative, (site_idx, week_idx), informative)

    return ModelInputs(
        site_ids=keep_sites,
        weeks=[pd.Timestamp(w).date() for w in grid],
        site_idx=site_idx,
        week_idx=week_idx,
        observer_idx=observer_codes.astype(int),
        n_observers=len(observers),
        clarity=numeric("water_clarity"),
        smell_intensity=numeric("smell_intensity"),
        sewage=sewage,
        trash=numeric("trash_level"),
        presence=presence,
        diversity=diversity,
        heavy_rain=heavy_rain,
        antecedent_z=antecedent_z,
        n_reports=n_reports,
        n_informative=n_informative,
    )


def load_inputs(*, site_ids: list[str] | None = None, n_weeks: int | None = None) -> ModelInputs:
    """Reads Stage 1-3 outputs from disk (observations, sites, weather) and builds inputs."""
    for path, stage in (
        (config.OBSERVATIONS_PATH, "1 (ingestion)"),
        (config.SITES_PATH, "1 (ingestion)"),
        (config.WEATHER_FEATURES_PATH, "2 (weather)"),
    ):
        if not path.exists():
            raise FileNotFoundError(f"{path} not found -- run Stage {stage} first.")

    return build_inputs(
        io_utils.read_parquet(config.OBSERVATIONS_PATH),
        io_utils.read_parquet(config.WEATHER_FEATURES_PATH),
        io_utils.read_parquet(config.SITES_PATH),
        site_ids=site_ids,
        n_weeks=n_weeks,
    )


def compute_exposure_weights(exposure_df: pd.DataFrame) -> pd.DataFrame:
    """One row per site: a static, category-weighted proximity score for Stage 7.

    weight = sum_c w_c * exp(-nearest_distance_c / 250m). Sites whose exposure data was
    `unavailable` get NaN (unknown), never 0 (verified none).
    """
    rows = []
    for site_id, group in exposure_df.groupby("site_id"):
        if (group["data_source"] != "real").all():
            rows.append({"site_id": site_id, "exposure_weight": np.nan, "data_source": "unavailable"})
            continue
        weight = 0.0
        for _, r in group.iterrows():
            d = r["nearest_poi_distance_m"]
            if pd.notna(d):
                weight += EXPOSURE_CATEGORY_WEIGHTS[r["category"]] * float(np.exp(-d / EXPOSURE_DECAY_M))
        rows.append({"site_id": site_id, "exposure_weight": weight, "data_source": "real"})
    return pd.DataFrame(rows)
