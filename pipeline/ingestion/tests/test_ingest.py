"""Smoke tests for Stage 1 ingestion: schema validity, referential integrity,
the ground-truth leakage guardrail, and a noisy-but-real observation signal.
"""

from __future__ import annotations

import numpy as np
import pytest

from pipeline.common import schema
from pipeline.common.sites import get_sites_df
from pipeline.ingestion import simulator

N_WEEKS = 26  # short window keeps the test fast; full runs use config.N_WEEKS (104)

BROOKLYN_LAT_RANGE = (40.65, 40.70)
BROOKLYN_LON_RANGE = (-74.02, -73.97)


@pytest.fixture(scope="module")
def sites_df():
    return get_sites_df()


@pytest.fixture(scope="module")
def simulated(sites_df):
    rng = np.random.default_rng(42)
    ground_truth_df, events_df = simulator.generate_ground_truth(sites_df, N_WEEKS, rng)
    observations_df = simulator.generate_observations(sites_df, ground_truth_df, events_df, rng)
    return observations_df, ground_truth_df, events_df


def test_sites_are_real_and_valid(sites_df):
    assert 8 <= len(sites_df) <= 15
    schema.validate_dataframe(sites_df, schema.Site, name="sites")
    assert sites_df["lat"].between(*BROOKLYN_LAT_RANGE).all()
    assert sites_df["lon"].between(*BROOKLYN_LON_RANGE).all()


def test_ground_truth_is_dense_and_in_range(simulated, sites_df):
    _, ground_truth_df, _ = simulated
    schema.validate_dataframe(ground_truth_df, schema.GroundTruthWeek, name="ground_truth")
    assert len(ground_truth_df) == len(sites_df) * N_WEEKS
    assert ground_truth_df["W_true"].between(0, 100).all()
    assert ground_truth_df["H_true"].between(0, 100).all()


def test_events_are_valid_and_referentially_sound(simulated, sites_df):
    _, ground_truth_df, events_df = simulated
    schema.validate_dataframe(events_df, schema.ContaminationEvent, name="events")

    site_ids = set(sites_df["site_id"])
    assert set(events_df["source_site_id"]) <= site_ids
    for affected in events_df["affected_site_ids"]:
        assert set(affected) <= site_ids

    rain_share = events_df["rain_triggered"].mean()
    assert 0 < rain_share < 1, "rain-linkage logic looks like a no-op"

    gt_event_ids = set(ground_truth_df["event_id"].dropna())
    assert gt_event_ids <= set(events_df["event_id"])


def test_observations_are_valid_and_dont_leak_ground_truth(simulated, sites_df):
    observations_df, _, _ = simulated
    schema.validate_dataframe(observations_df, schema.Observation, name="observations")
    schema.assert_no_ground_truth_leak(observations_df)
    assert len(observations_df) > 0
    assert set(observations_df["site_id"]) <= set(sites_df["site_id"])


def test_observations_are_a_noisy_but_real_signal_of_ground_truth(simulated):
    observations_df, ground_truth_df, _ = simulated
    severity = observations_df["water_clarity"].fillna(0) + observations_df["trash_level"].fillna(0)
    merged = observations_df.assign(severity=severity).merge(
        ground_truth_df[["site_id", "week_start", "W_true"]], on=["site_id", "week_start"], how="left"
    )
    corr = merged[["severity", "W_true"]].dropna().corr().iloc[0, 1]
    # Moderately negative: neither pure noise (~0) nor a perfect readout (~-1).
    assert -0.85 < corr < -0.1


def test_deterministic_with_fixed_seed(sites_df):
    rng1 = np.random.default_rng(7)
    gt1, ev1 = simulator.generate_ground_truth(sites_df, N_WEEKS, rng1)

    rng2 = np.random.default_rng(7)
    gt2, ev2 = simulator.generate_ground_truth(sites_df, N_WEEKS, rng2)

    assert len(gt1) == len(gt2)
    assert len(ev1) == len(ev2)
    assert np.allclose(gt1["W_true"].to_numpy(), gt2["W_true"].to_numpy())
