"""Smoke tests for Stage 2 weather: schema validity, a dense site x week grid,
the never-look-at-future-data guarantee, and a deterministic synthetic-fallback
path that doesn't depend on network availability.
"""

from __future__ import annotations

import pandas as pd
import pytest

from pipeline.common import rainfall_lookup, schema
from pipeline.common.dates import weekly_dates
from pipeline.common.sites import get_sites_df
from pipeline.weather import weather

N_WEEKS = 12  # short window keeps the test fast


@pytest.fixture(scope="module")
def sites_df():
    return get_sites_df()


@pytest.fixture(scope="module")
def weeks():
    return weekly_dates(N_WEEKS)


@pytest.fixture(scope="module")
def weather_df(sites_df, weeks):
    return weather.compute_weather_features(sites_df, weeks)


def test_weather_features_are_dense_and_valid(weather_df, sites_df, weeks):
    schema.validate_dataframe(weather_df, schema.WeatherWeek, name="weather_features")
    assert len(weather_df) == len(sites_df) * len(weeks)
    assert set(weather_df["site_id"]) <= set(sites_df["site_id"])


def test_antecedent_rainfall_never_leaks_future_data(weather_df):
    first_week_rows = weather_df.sort_values("week_start").groupby("site_id").first()
    assert (first_week_rows["antecedent_rainfall_mm_3wk"] == 0).all()


def test_heavy_rain_week_is_not_degenerate(weather_df):
    share = weather_df["heavy_rain_week"].mean()
    assert 0 < share < 1, "heavy-rain threshold looks like a no-op"


def test_synthetic_fallback_path_is_deterministic_and_valid(sites_df, weeks, monkeypatch):
    def _always_fails(*args, **kwargs):
        raise rainfall_lookup.RainfallFetchError("network disabled for test")

    monkeypatch.setattr(rainfall_lookup, "get_daily_rainfall", _always_fails)

    fallback_df = weather.compute_weather_features(sites_df, weeks)
    schema.validate_dataframe(fallback_df, schema.WeatherWeek, name="weather_features_fallback")
    assert (fallback_df["source"] == "synthetic_fallback").all()

    # Deterministic: rerunning with the same seed gives identical numbers.
    fallback_df_2 = weather.compute_weather_features(sites_df, weeks)
    pd.testing.assert_frame_equal(fallback_df, fallback_df_2)
