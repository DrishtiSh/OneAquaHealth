"""Smoke tests for Stage 4 exposure: schema validity, a dense site x category
grid, a non-brittle real-fetch sanity check, and a deterministic fallback path
that doesn't depend on network availability.
"""

from __future__ import annotations

import pandas as pd
import pytest

from pipeline.common import schema
from pipeline.common.sites import get_sites_df
from pipeline.exposure import exposure


@pytest.fixture(scope="module")
def sites_df():
    return get_sites_df()


@pytest.fixture(scope="module")
def exposure_df(sites_df):
    return exposure.compute_exposure_features(sites_df)


def test_exposure_features_are_dense_and_valid(exposure_df, sites_df):
    schema.validate_dataframe(exposure_df, schema.ExposureFeature, name="exposure_features")
    assert len(exposure_df) == len(sites_df) * len(exposure._TAGS)
    assert set(exposure_df["site_id"]) <= set(sites_df["site_id"])


@pytest.mark.network
def test_real_fetch_finds_at_least_one_poi(exposure_df):
    assert (exposure_df["data_source"] == "real").all()
    assert exposure_df["nearest_poi_distance_m"].notna().any()


def test_is_exposure_relevant_matches_threshold(exposure_df):
    real_rows = exposure_df[exposure_df["data_source"] == "real"]
    expected = real_rows["nearest_poi_distance_m"].notna() & (
        real_rows["nearest_poi_distance_m"] <= exposure.PROXIMITY_THRESHOLD_M
    )
    assert (real_rows["is_exposure_relevant"] == expected).all()


def test_fallback_path_is_deterministic_and_valid(sites_df, monkeypatch):
    def _always_fails(bbox):
        raise exposure.PoiFetchError("network disabled for test")

    monkeypatch.setattr(exposure, "fetch_pois_by_category", _always_fails)

    fallback_df = exposure.compute_exposure_features(sites_df)
    schema.validate_dataframe(fallback_df, schema.ExposureFeature, name="exposure_features_fallback")
    assert (fallback_df["data_source"] == "unavailable").all()
    assert (~fallback_df["is_exposure_relevant"]).all()
    assert fallback_df["nearest_poi_distance_m"].isna().all()

    fallback_df_2 = exposure.compute_exposure_features(sites_df)
    pd.testing.assert_frame_equal(fallback_df, fallback_df_2)
