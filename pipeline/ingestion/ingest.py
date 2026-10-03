"""Stage 1: Pull real observations from the OAH API/FHIR records, plus a simulator
that generates synthetic ground-truth data for testing.

Real OAH citizen checks need an API token we don't have yet (see real_source.py and
`npm run oah-check`), so this stage's primary, always-on output is the simulator -- it also generates the hidden ground truth
that Stage 11 (benchmark) needs to score the pipeline against. Any real
observations are unioned in as extra, best-effort rows purely for demo realism
and are never fed to the benchmark.
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from pipeline.common import config, io_utils, schema
from pipeline.common.sites import get_sites_df
from pipeline.ingestion import real_source, simulator

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def _load_real_observations() -> pd.DataFrame | None:
    ingestion_mode = os.environ.get(config.INGESTION_MODE_ENV, "").lower()
    configured = real_source.is_configured()

    if not configured:
        if ingestion_mode == "real":
            raise real_source.OAHNotConfiguredError(
                f"{config.INGESTION_MODE_ENV}=real was set but {config.OAH_API_BASE_URL_ENV} is not. "
                "Refusing to silently fall back to simulator-only data when real data was requested."
            )
        logger.info("%s not set -- using simulator only.", config.OAH_API_BASE_URL_ENV)
        return None

    base_url = os.environ[config.OAH_API_BASE_URL_ENV]
    api_token = os.environ.get(config.OAH_API_TOKEN_ENV)
    since = date.today() - timedelta(days=365)  # not .replace(year=...): raises on Feb 29
    logger.info("Fetching real observations from %s since %s", base_url, since)
    real_df = real_source.fetch_real_observations(base_url, api_token, since)
    logger.info("Fetched %d real observation(s).", len(real_df))
    return real_df


def run() -> dict[str, Path]:
    load_dotenv()

    sites_df = get_sites_df()
    schema.validate_dataframe(sites_df, schema.Site, name="sites")
    io_utils.write_parquet(sites_df, config.SITES_PATH)
    logger.info("Wrote %d sites to %s", len(sites_df), config.SITES_PATH)

    sim_obs_df, ground_truth_df, events_df = simulator.run_simulator(sites_df)

    real_obs_df = _load_real_observations()
    observations_df = pd.concat([sim_obs_df, real_obs_df], ignore_index=True) if real_obs_df is not None else sim_obs_df

    schema.validate_dataframe(observations_df, schema.Observation, name="observations")
    schema.assert_no_ground_truth_leak(observations_df)
    schema.validate_dataframe(ground_truth_df, schema.GroundTruthWeek, name="ground_truth")
    schema.validate_dataframe(events_df, schema.ContaminationEvent, name="events")

    io_utils.write_parquet(observations_df, config.OBSERVATIONS_PATH)
    io_utils.write_parquet(ground_truth_df, config.GROUND_TRUTH_WEEKLY_PATH)
    io_utils.write_parquet(events_df, config.GROUND_TRUTH_EVENTS_PATH)

    _print_summary(sites_df, observations_df, ground_truth_df, events_df)

    return {
        "sites": config.SITES_PATH,
        "observations": config.OBSERVATIONS_PATH,
        "ground_truth_weekly": config.GROUND_TRUTH_WEEKLY_PATH,
        "ground_truth_events": config.GROUND_TRUTH_EVENTS_PATH,
    }


def _print_summary(
    sites_df: pd.DataFrame, observations_df: pd.DataFrame, ground_truth_df: pd.DataFrame, events_df: pd.DataFrame
) -> None:
    n_site_weeks = len(ground_truth_df)
    n_observed_site_weeks = observations_df[["site_id", "week_start"]].drop_duplicates().shape[0]
    sparsity = 1 - (n_observed_site_weeks / n_site_weeks) if n_site_weeks else 0.0

    severity = (observations_df["water_clarity"].fillna(0) + observations_df["trash_level"].fillna(0)).astype(float)
    merged = observations_df.assign(severity=severity).merge(
        ground_truth_df[["site_id", "week_start", "W_true"]], on=["site_id", "week_start"], how="left"
    )
    corr = merged[["severity", "W_true"]].dropna().corr().iloc[0, 1] if len(merged) > 1 else float("nan")

    print("--- Stage 1 ingestion summary ---")
    print(f"Sites: {len(sites_df)}")
    print(f"Observations: {len(observations_df)} (source counts: {observations_df['source'].value_counts().to_dict()})")
    print(f"Site-weeks observed: {n_observed_site_weeks}/{n_site_weeks} (sparsity: {sparsity:.1%})")
    print(f"Contamination events: {len(events_df)} (rain-triggered: {events_df['rain_triggered'].sum()})")
    print(f"Observed-severity vs W_true correlation: {corr:.3f} (expect moderately negative)")
    print("----------------------------------")


if __name__ == "__main__":
    run()
