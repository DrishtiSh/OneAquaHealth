"""Shared fixtures: a tiny synthetic world with a planted contamination event.

The generator here knows its own truth (it lives in tests, not in the model package), so
tests can check that the model recovers a planted signal without touching the pipeline's
hidden ground-truth files.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

N_SITES, N_WEEKS = 3, 20
EVENT_SITE, EVENT_WEEKS = 0, (10, 11)
BASE_W, EVENT_W = 85.0, 25.0


def _weeks(n: int) -> list[date]:
    start = date(2025, 1, 6)  # a Monday
    return [start + timedelta(weeks=i) for i in range(n)]


def _make_reports(rng, weeks, w_true, h_true, *, skip=lambda s, t: False, extra=()):
    rows = []
    for s in range(N_SITES):
        for t, wk in enumerate(weeks):
            if skip(s, t) or rng.random() > 0.65:
                continue
            for _ in range(1 + int(rng.random() < 0.4)):
                sewage = h_true[s, t] > 50
                rows.append(
                    {
                        "observation_id": f"o{len(rows)}",
                        "site_id": f"toy-{s}",
                        "week_start": wk,
                        "observer_id": f"obs{rng.integers(0, 5)}",
                        "water_clarity": float(np.clip(np.rint(1 + 4 * (1 - w_true[s, t] / 100) + rng.normal(0, 0.4)), 1, 5)),
                        "smell": "sewage" if sewage else "none",
                        "smell_intensity": float(np.clip(np.rint(3 * h_true[s, t] / 100 + rng.normal(0, 0.3)), 0, 3)),
                        "trash_level": float(rng.integers(0, 4)),
                        "insect_presence": bool(rng.random() < 0.45),
                        "insect_diversity": np.nan,
                    }
                )
    rows.extend(extra)
    return pd.DataFrame(rows)


@pytest.fixture(scope="session")
def toy():
    rng = np.random.default_rng(3)
    weeks = _weeks(N_WEEKS)
    w_true = np.full((N_SITES, N_WEEKS), BASE_W)
    h_true = np.full((N_SITES, N_WEEKS), 100 - BASE_W - 5.0)  # ~10
    for t in EVENT_WEEKS:
        w_true[EVENT_SITE, t], h_true[EVENT_SITE, t] = EVENT_W, 80.0

    # Site 2 is never reported in weeks 5-9: a known-unobserved window.
    obs = _make_reports(rng, weeks, w_true, h_true, skip=lambda s, t: s == 2 and 5 <= t <= 9)

    sites = pd.DataFrame(
        {"site_id": [f"toy-{s}" for s in range(N_SITES)], "distance_from_mouth_m": [600.0, 300.0, 0.0]}
    )
    weather = pd.DataFrame(
        [
            {
                "site_id": f"toy-{s}",
                "week_start": wk,
                "heavy_rain_week": bool(t in EVENT_WEEKS),
                "antecedent_rainfall_mm_3wk": float(20 + 5 * (t % 4)),
            }
            for s in range(N_SITES)
            for t, wk in enumerate(weeks)
        ]
    )
    return {"obs": obs, "sites": sites, "weather": weather, "weeks": weeks, "w_true": w_true, "h_true": h_true,
            "rng_seed": 3}


OUTLIER_SITE, OUTLIER_WEEK = 1, 3


@pytest.fixture(scope="session")
def toy_with_outlier(toy):
    """Same world, but site-week (1, 3) gets two ordinary clear-water reports plus one absurd
    report (worst clarity, max smell, sewage). A sane misreport model should not call that
    site-week an event."""
    week = toy["weeks"][OUTLIER_WEEK]
    base = {"site_id": f"toy-{OUTLIER_SITE}", "week_start": week, "insect_presence": False, "insect_diversity": np.nan,
            "trash_level": 1.0}
    normal = [
        {**base, "observation_id": f"n{i}", "observer_id": f"obs{i}", "water_clarity": 1.0, "smell": "none",
         "smell_intensity": 0.0}
        for i in range(2)
    ]
    absurd = {**base, "observation_id": "junk", "observer_id": "obs4", "water_clarity": 5.0, "smell": "sewage",
              "smell_intensity": 3.0}
    obs = toy["obs"]
    obs = obs[~((obs["site_id"] == base["site_id"]) & (obs["week_start"] == week))]
    return {**toy, "obs": pd.concat([obs, pd.DataFrame(normal + [absurd])], ignore_index=True)}
