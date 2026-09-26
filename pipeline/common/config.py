"""Shared config: paths, seeds, and env var names used across pipeline stages."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = REPO_ROOT / "data"
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

RANDOM_SEED = int(os.environ.get("OAH_RANDOM_SEED", "42"))
N_WEEKS = int(os.environ.get("OAH_N_WEEKS", "104"))

# Env vars consumed by the (hypothetical) real OAH API adapter -- see
# pipeline/ingestion/real_source.py for the contract these configure.
OAH_API_BASE_URL_ENV = "OAH_API_BASE_URL"
OAH_API_TOKEN_ENV = "OAH_API_TOKEN"
INGESTION_MODE_ENV = "INGESTION_MODE"  # set to "real" to require the real source
