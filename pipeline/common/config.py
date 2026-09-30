"""Shared config: paths, seeds, and env var names used across pipeline stages."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = Path(os.environ["OAH_DATA_DIR"]) if os.environ.get("OAH_DATA_DIR") else REPO_ROOT / "data"
DATA_RAW_DIR = DATA_DIR / "raw"
DATA_PROCESSED_DIR = DATA_DIR / "processed"
DATA_SNAPSHOT_DIR = DATA_DIR / "snapshot"
GROUND_TRUTH_DIR = DATA_RAW_DIR / "ground_truth"
CACHE_DIR = DATA_RAW_DIR / "_cache"

SITES_PATH = DATA_RAW_DIR / "sites.parquet"
OBSERVATIONS_PATH = DATA_RAW_DIR / "observations.parquet"
GROUND_TRUTH_WEEKLY_PATH = GROUND_TRUTH_DIR / "weekly_ground_truth.parquet"
GROUND_TRUTH_EVENTS_PATH = GROUND_TRUTH_DIR / "events.parquet"
WEATHER_FEATURES_PATH = DATA_PROCESSED_DIR / "weather_features.parquet"
RIVER_GRAPH_EDGES_PATH = DATA_PROCESSED_DIR / "river_graph_edges.parquet"
EXPOSURE_FEATURES_PATH = DATA_PROCESSED_DIR / "exposure_features.parquet"

# Stage 5 (model) outputs.
MODEL_SCORES_PATH = DATA_PROCESSED_DIR / "model_scores.parquet"
MODEL_DRAWS_PATH = DATA_PROCESSED_DIR / "model_draws.nc"
MODEL_PARAMS_PATH = DATA_PROCESSED_DIR / "model_params.parquet"
MODEL_DIAG_PATH = DATA_PROCESSED_DIR / "model_diagnostics.json"
SITE_EXPOSURE_WEIGHTS_PATH = DATA_PROCESSED_DIR / "site_exposure_weights.parquet"

# Stage 6 (detectors) outputs.
DETECTOR_ALERTS_PATH = DATA_PROCESSED_DIR / "detector_alerts.parquet"
DETECTOR_INCIDENTS_PATH = DATA_PROCESSED_DIR / "detector_incidents.parquet"
DETECTOR_RAIN_PATH = DATA_PROCESSED_DIR / "detector_rain.json"

# Stage 6 thresholds. Fixed up front, before any benchmark comparison: the benchmark reports a
# sensitivity grid around these rather than tuning them against the simulator's truth.
DETECT_DELTA = 10.0  # W drop (index points) that counts as "really changed" (~0.4 clarity-rubric step)
P_CONFIRMED = 0.9  # posterior probability for a confirmed change
P_POSSIBLE = 0.5  # posterior probability for a possible change
INCIDENT_WINDOW_WEEKS = 2  # episodes this close in time (downstream travel lag) form one incident
INCIDENT_MAX_HOPS = 2  # ...and this close along the river (a pulse decays with distance)
SOURCE_CREDIBLE_MASS = 0.8  # smallest set of candidate sources holding this much probability
RAIN_LAG_WEEKS = 1  # a week counts as rain-exposed if it or the previous week(s) had heavy rain
RAIN_MIN_OBSERVED_WEEKS = 5  # fewer rain-exposed weeks with any report -> "insufficient evidence"
RAIN_P_SUPPORTED = 0.95  # P(IRR > 1) needed for "supported"
RAIN_PLACEBO_ALPHA = 0.05  # placebo (shifted-rain) p-value needed for "supported"

# Week-grid anchor the committed data was generated with (see common/dates.py). Override with
# OAH_ANCHOR_DATE=<ISO date>, or OAH_ANCHOR_DATE=today for live mode.
DEFAULT_ANCHOR_DATE = "2026-09-14"

RANDOM_SEED = int(os.environ.get("OAH_RANDOM_SEED", "42"))
N_WEEKS = int(os.environ.get("OAH_N_WEEKS", "104"))

# Env vars consumed by the (hypothetical) real OAH API adapter -- see
# pipeline/ingestion/real_source.py for the contract these configure.
OAH_API_BASE_URL_ENV = "OAH_API_BASE_URL"
OAH_API_TOKEN_ENV = "OAH_API_TOKEN"
INGESTION_MODE_ENV = "INGESTION_MODE"  # set to "real" to require the real source
