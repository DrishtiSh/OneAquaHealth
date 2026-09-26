"""Stage 2: Pull rainfall history (Open-Meteo) since rain affects runoff and contamination.

Produces one row per (site_id, week_start) with real (or, on API failure,
synthetic-fallback) rainfall features -- a dense covariate table that Stage 5's
Bayesian model and Stage 6's rain->overflow detectors join against by that key.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.common import config, io_utils, schema
from pipeline.common.dates import weekly_dates
from pipeline.common.rainfall_lookup import aggregate_daily_to_weekly, get_daily_rainfall_with_fallback

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

ANTECEDENT_WEEKS = 3
HEAVY_RAIN_PERCENTILE = 75


def compute_weather_features(sites_df: pd.DataFrame, weeks: list[date]) -> pd.DataFrame:
    """Returns a dense (site_id, week_start) rainfall-feature table -- see schema.WeatherWeek."""
    start, end = weeks[0], weeks[-1] + timedelta(days=6)

    site_frames = []
    for _, site in sites_df.iterrows():
        daily_df, used_real = get_daily_rainfall_with_fallback(float(site["lat"]), float(site["lon"]), start, end)
        weekly_df = aggregate_daily_to_weekly(daily_df, weeks)

        weekly_df["antecedent_rainfall_mm_3wk"] = (
            weekly_df["weekly_rainfall_mm"].shift(1).rolling(ANTECEDENT_WEEKS, min_periods=1).sum().fillna(0.0)
        )
        threshold = np.percentile(weekly_df["weekly_rainfall_mm"], HEAVY_RAIN_PERCENTILE)
        weekly_df["heavy_rain_week"] = weekly_df["weekly_rainfall_mm"] >= threshold

        weekly_df["site_id"] = site["site_id"]
        weekly_df["source"] = "real" if used_real else "synthetic_fallback"
        site_frames.append(weekly_df)

    weather_df = pd.concat(site_frames, ignore_index=True)
    return weather_df[
        [
            "site_id",
            "week_start",
            "weekly_rainfall_mm",
            "max_daily_rainfall_mm",
            "rain_days_count",
            "antecedent_rainfall_mm_3wk",
            "heavy_rain_week",
            "source",
        ]
    ]


def _print_summary(weather_df: pd.DataFrame) -> None:
    source_counts = weather_df.groupby("site_id")["source"].first().value_counts().to_dict()
    print("--- Stage 2 weather summary ---")
    print(f"Site-weeks: {len(weather_df)}")
    print(f"Sites by data source: {source_counts}")
    print(f"Avg weekly rainfall: {weather_df['weekly_rainfall_mm'].mean():.1f}mm")
    print(f"Heavy-rain site-weeks: {int(weather_df['heavy_rain_week'].sum())}")
    print("--------------------------------")


def run() -> dict[str, Path]:
    if not config.SITES_PATH.exists():
        raise FileNotFoundError(f"{config.SITES_PATH} not found -- run Stage 1 (ingestion) first.")

    sites_df = io_utils.read_parquet(config.SITES_PATH)
    weeks = weekly_dates(config.N_WEEKS)

    weather_df = compute_weather_features(sites_df, weeks)
    schema.validate_dataframe(weather_df, schema.WeatherWeek, name="weather_features")

    io_utils.write_parquet(weather_df, config.WEATHER_FEATURES_PATH)
    logger.info("Wrote %d site-weeks to %s", len(weather_df), config.WEATHER_FEATURES_PATH)
    _print_summary(weather_df)

    return {"weather_features": config.WEATHER_FEATURES_PATH}


if __name__ == "__main__":
    run()
