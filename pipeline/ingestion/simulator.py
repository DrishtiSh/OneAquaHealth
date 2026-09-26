"""Stage 1 simulator: generates hidden ground truth plus noisy, sparse citizen
observations for the Gowanus Canal watershed.

Two outputs, kept strictly separate:
  - ground truth (`GroundTruthWeek` + `ContaminationEvent`) -- dense, exact,
    hidden latent state. Only pipeline/benchmark may ever read this.
  - observations (`Observation`) -- sparse, noisy citizen reports derived from
    the ground truth. This is what stages 2-9 actually see.

Contamination events are seeded using REAL historical rainfall (via
common/rainfall_lookup) so the "rain -> sewage overflow" relationship the
pipeline is meant to detect is a physically real one, not a coincidence baked
in by construction. If the rainfall API is unreachable, a synthetic seasonal
rainfall proxy is used instead purely for event timing, so this never
hard-fails on lack of network.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
from faker import Faker

from pipeline.common import config
from pipeline.common.dates import weekly_dates
from pipeline.common.rainfall_lookup import aggregate_daily_to_weekly, get_daily_rainfall_with_fallback

logger = logging.getLogger(__name__)

SMELL_CHOICES = ["none", "earthy", "musty", "chemical", "sewage", "dead_fish"]

# How far a contamination effect reaches downstream, and how fast it travels.
DECAY_CONSTANT_M = 1200.0
FLOW_SPEED_M_PER_WEEK = 1500.0

# Event base rate: ~1 event per ~12 weeks of simulated history.
EVENT_RATE_PER_WEEK = 1.0 / 12.0
RAIN_TRIGGER_PROB = 0.65

MISREPORT_PROB = 0.04


def _weekly_rainfall(sites_df: pd.DataFrame, weeks: list[date]) -> tuple[np.ndarray, bool]:
    """Returns (weekly_rain_mm aligned to `weeks`, used_real_data flag).

    Only needs a rain/no-rain threshold for event timing, so one centroid
    fetch stands in for all sites here -- Stage 2's weather.py fetches each
    site's own real coordinates for the actual per-site feature table.
    """
    centroid_lat = float(sites_df["lat"].mean())
    centroid_lon = float(sites_df["lon"].mean())
    start, end = weeks[0], weeks[-1] + timedelta(days=6)

    daily_df, used_real = get_daily_rainfall_with_fallback(centroid_lat, centroid_lon, start, end)
    if not used_real:
        logger.warning("Using synthetic rainfall proxy for event timing (real fetch failed).")
    weekly_df = aggregate_daily_to_weekly(daily_df, weeks)
    return weekly_df["weekly_rainfall_mm"].to_numpy(), used_real


def _make_events(
    sites_df: pd.DataFrame, weeks: list[date], weekly_rain_mm: np.ndarray, rng: np.random.Generator
) -> pd.DataFrame:
    n_weeks = len(weeks)
    heavy_rain_threshold = float(np.percentile(weekly_rain_mm, 75))
    heavy_rain_week_idxs = np.where(weekly_rain_mm >= heavy_rain_threshold)[0]

    cso_site_ids = sites_df.loc[sites_df["is_cso_outfall_adjacent"], "site_id"].tolist()
    all_site_ids = sites_df["site_id"].tolist()

    n_events = rng.poisson(EVENT_RATE_PER_WEEK * n_weeks)
    n_events = max(n_events, 4)  # guarantee a demo-worthy number of events

    events = []
    for _ in range(n_events):
        rain_triggered = bool(rng.random() < RAIN_TRIGGER_PROB and len(heavy_rain_week_idxs) > 0)
        if rain_triggered:
            start_idx = int(rng.choice(heavy_rain_week_idxs))
            event_type = rng.choice(["sewage_overflow", "urban_runoff"], p=[0.7, 0.3])
            source_site_id = rng.choice(cso_site_ids or all_site_ids)
        else:
            start_idx = int(rng.integers(0, n_weeks))
            event_type = rng.choice(["upstream_industrial_discharge", "background_noise_spike"], p=[0.5, 0.5])
            source_site_id = rng.choice(all_site_ids)

        duration_weeks = int(rng.integers(1, 4))  # 1-3 weeks
        end_idx = min(start_idx + duration_weeks - 1, n_weeks - 1)
        peak_magnitude = float(rng.uniform(30, 90))

        source_dist = float(sites_df.loc[sites_df["site_id"] == source_site_id, "distance_from_mouth_m"].iloc[0])
        downstream = sites_df[sites_df["distance_from_mouth_m"] <= source_dist]
        affected_site_ids = downstream["site_id"].tolist()

        events.append(
            {
                "event_id": uuid.uuid4().hex,
                "source_site_id": str(source_site_id),
                "start_week": weeks[start_idx],
                "end_week": weeks[end_idx],
                "event_type": str(event_type),
                "rain_triggered": rain_triggered,
                "peak_magnitude": peak_magnitude,
                "affected_site_ids": affected_site_ids,
                "_start_idx": start_idx,
                "_end_idx": end_idx,
                "_source_dist": source_dist,
            }
        )
    return pd.DataFrame(events)


def generate_ground_truth(
    sites_df: pd.DataFrame, n_weeks: int, rng: np.random.Generator
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (ground_truth_df, events_df) -- both hidden, benchmark-only."""
    weeks = weekly_dates(n_weeks)
    weekly_rain_mm, used_real_rain = _weekly_rainfall(sites_df, weeks)
    logger.info(
        "Rainfall source for event triggering: %s", "real (Open-Meteo)" if used_real_rain else "synthetic proxy"
    )

    events_df = _make_events(sites_df, weeks, weekly_rain_mm, rng)

    site_ids = sites_df["site_id"].tolist()
    n_sites = len(site_ids)

    # Slow AR(1) baseline per site, plus a mild seasonal term.
    baseline_w = np.zeros((n_sites, n_weeks))
    for s in range(n_sites):
        level = 80.0 + rng.normal(0, 3)
        for t in range(n_weeks):
            level = 0.9 * level + 0.1 * 82.0 + rng.normal(0, 1.5)
            seasonal = 3 * np.sin(2 * np.pi * t / 52.0)
            baseline_w[s, t] = np.clip(level + seasonal, 0, 100)

    W_true = baseline_w.copy()
    H_true = np.clip(100 - baseline_w + rng.normal(0, 2, size=baseline_w.shape), 0, 20)
    event_active = np.zeros((n_sites, n_weeks), dtype=bool)
    event_id_grid = np.full((n_sites, n_weeks), None, dtype=object)

    site_idx = {sid: i for i, sid in enumerate(site_ids)}
    dist_by_site = dict(zip(sites_df["site_id"], sites_df["distance_from_mouth_m"]))

    for _, ev in events_df.iterrows():
        for affected_site in ev["affected_site_ids"]:
            distance_traveled = ev["_source_dist"] - dist_by_site[affected_site]
            decay = np.exp(-distance_traveled / DECAY_CONSTANT_M)
            lag_weeks = int(round(distance_traveled / FLOW_SPEED_M_PER_WEEK))
            magnitude = ev["peak_magnitude"] * decay

            start_t = min(ev["_start_idx"] + lag_weeks, n_weeks - 1)
            end_t = min(ev["_end_idx"] + lag_weeks, n_weeks - 1)
            if start_t > end_t:
                continue

            s = site_idx[affected_site]
            W_true[s, start_t : end_t + 1] = np.clip(W_true[s, start_t : end_t + 1] - magnitude, 0, 100)
            H_true[s, start_t : end_t + 1] = np.clip(H_true[s, start_t : end_t + 1] + magnitude, 0, 100)
            event_active[s, start_t : end_t + 1] = True
            event_id_grid[s, start_t : end_t + 1] = ev["event_id"]

    rows = []
    for s, sid in enumerate(site_ids):
        for t, wk in enumerate(weeks):
            rows.append(
                {
                    "site_id": sid,
                    "week_start": wk,
                    "W_true": float(W_true[s, t]),
                    "H_true": float(H_true[s, t]),
                    "contamination_event_active": bool(event_active[s, t]),
                    "event_id": event_id_grid[s, t],
                }
            )
    ground_truth_df = pd.DataFrame(rows)
    events_df = events_df.drop(columns=["_start_idx", "_end_idx", "_source_dist"])
    return ground_truth_df, events_df


def _bucket_clarity(w_true: float, rng: np.random.Generator) -> int:
    dirtiness = (100.0 - w_true) / 100.0 + rng.normal(0, 0.12)
    dirtiness = np.clip(dirtiness, 0, 1)
    return int(np.clip(1 + round(dirtiness * 4), 1, 5))


def _pick_smell(h_true: float, event_type: str | None, rng: np.random.Generator) -> tuple[str, int]:
    severity = np.clip(h_true / 100.0 + rng.normal(0, 0.1), 0, 1)
    if severity < 0.15:
        return "none", 0
    if event_type == "sewage_overflow" and rng.random() < 0.6:
        smell = "sewage"
    elif event_type == "upstream_industrial_discharge" and rng.random() < 0.5:
        smell = "chemical"
    elif severity > 0.5:
        smell = rng.choice(["sewage", "musty", "dead_fish"], p=[0.4, 0.4, 0.2])
    else:
        smell = rng.choice(["earthy", "musty", "none"], p=[0.4, 0.3, 0.3])
    intensity = int(np.clip(round(severity * 3), 0, 3))
    return str(smell), intensity


def _pick_trash(event_type: str | None, rng: np.random.Generator) -> int:
    base = rng.choice([0, 1, 2, 3], p=[0.4, 0.35, 0.2, 0.05])
    if event_type == "urban_runoff":
        base = min(base + 1, 4)
    return int(base)


def _pick_insects(w_true: float, event_active: bool, rng: np.random.Generator) -> tuple[bool, int]:
    if event_active and w_true < 40:
        presence = rng.random() < 0.15
    else:
        presence = rng.random() < 0.45
    diversity = int(rng.integers(0, 4)) if presence else 0
    return bool(presence), diversity


def _make_notes(site_name: str, smell: str, trash_level: int, clarity: int, rng: np.random.Generator) -> str | None:
    if rng.random() < 0.4:
        return None
    fragments = []
    if clarity >= 4:
        fragments.append(f"Water near {site_name} looked murky")
    elif clarity <= 2:
        fragments.append(f"Water near {site_name} looked pretty clear")
    if smell not in (None, "none"):
        fragments.append(f"noticed a {smell.replace('_', ' ')} smell")
    if trash_level >= 3:
        fragments.append("more trash than usual along the bank")
    if not fragments:
        fragments.append(f"Nothing unusual at {site_name} this week")
    return ". ".join(fragments)[:280]


def generate_observations(
    sites_df: pd.DataFrame, ground_truth_df: pd.DataFrame, events_df: pd.DataFrame, rng: np.random.Generator
) -> pd.DataFrame:
    fake = Faker()
    Faker.seed(config.RANDOM_SEED)
    observer_pool = [fake.unique.user_name() for _ in range(35)]
    observer_completeness = {oid: rng.uniform(0.55, 1.0) for oid in observer_pool}

    site_name = dict(zip(sites_df["site_id"], sites_df["name"]))
    engagement_rate = {
        sid: (0.55 if adj else 0.35)
        for sid, adj in zip(sites_df["site_id"], sites_df["is_cso_outfall_adjacent"])
    }
    event_type_by_id = dict(zip(events_df["event_id"], events_df["event_type"]))

    now = datetime.now()
    rows = []
    for _, gt in ground_truth_df.iterrows():
        sid = gt["site_id"]
        if rng.random() > engagement_rate[sid]:
            continue  # no one reported this site this week

        n_reports = 1 + int(rng.binomial(2, 0.3))
        event_type = event_type_by_id.get(gt["event_id"]) if gt["event_id"] else None

        for _ in range(n_reports):
            observer_id = str(rng.choice(observer_pool))
            completeness = observer_completeness[observer_id]

            if rng.random() < MISREPORT_PROB:
                clarity = int(rng.integers(1, 6))
                smell, smell_intensity = rng.choice(SMELL_CHOICES), int(rng.integers(0, 4))
                trash_level = int(rng.integers(0, 5))
                insect_presence, insect_diversity = bool(rng.random() < 0.4), int(rng.integers(0, 4))
            else:
                clarity = _bucket_clarity(gt["W_true"], rng)
                smell, smell_intensity = _pick_smell(gt["H_true"], event_type, rng)
                trash_level = _pick_trash(event_type, rng)
                insect_presence, insect_diversity = _pick_insects(
                    gt["W_true"], gt["contamination_event_active"], rng
                )

            def _maybe(value):
                return value if rng.random() < completeness else None

            observed_at = datetime.combine(gt["week_start"], datetime.min.time()) + timedelta(
                days=int(rng.integers(0, 7)), hours=int(rng.integers(7, 20))
            )
            notes = _make_notes(site_name[sid], smell, trash_level, clarity, rng) if rng.random() < completeness else None

            rows.append(
                {
                    "observation_id": uuid.uuid4().hex,
                    "site_id": sid,
                    "observed_at": observed_at,
                    "week_start": gt["week_start"],
                    "observer_id": observer_id,
                    "water_clarity": _maybe(clarity),
                    "smell": _maybe(smell),
                    "smell_intensity": _maybe(smell_intensity),
                    "trash_level": _maybe(trash_level),
                    "insect_presence": _maybe(insect_presence),
                    "insect_diversity": _maybe(insect_diversity) if insect_presence else None,
                    "notes": notes,
                    "source": "simulated",
                    "ingested_at": now,
                    "raw_payload": None,
                }
            )

    return pd.DataFrame(rows)


def run_simulator(sites_df: pd.DataFrame, n_weeks: int | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Returns (observations_df, ground_truth_df, events_df)."""
    rng = np.random.default_rng(config.RANDOM_SEED)
    n_weeks = n_weeks or config.N_WEEKS
    ground_truth_df, events_df = generate_ground_truth(sites_df, n_weeks, rng)
    observations_df = generate_observations(sites_df, ground_truth_df, events_df, rng)
    return observations_df, ground_truth_df, events_df
