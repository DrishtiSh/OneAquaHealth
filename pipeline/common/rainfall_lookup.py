"""Real historical daily rainfall via the Open-Meteo Archive API, with on-disk caching.

Shared by Stage 1 (to seed rain-triggered contamination events in the simulator
with a real, physically-grounded rain signal) and Stage 2's weather.py (to join
real rainfall as a model covariate), so there is exactly one Open-Meteo client,
and exactly one real+synthetic-fallback code path, in the codebase.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from pipeline.common import config

logger = logging.getLogger(__name__)

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


class RainfallFetchError(RuntimeError):
    """Raised when the Open-Meteo archive API can't be reached or returns bad data."""


def _cache_path(lat: float, lon: float, start: date, end: date) -> Path:
    key = f"rain_{lat:.4f}_{lon:.4f}_{start.isoformat()}_{end.isoformat()}.parquet"
    return config.CACHE_DIR / key


def get_daily_rainfall(
    lat: float, lon: float, start: date, end: date, *, timeout_s: float = 15.0
) -> pd.DataFrame:
    """Returns a DataFrame with columns [date, precipitation_mm] for [start, end] inclusive.

    Caches results on disk under data/raw/_cache/ so repeat runs don't re-hit the API.
    Raises RainfallFetchError on network/API failure -- callers decide the fallback.
    """
    cache_file = _cache_path(lat, lon, start, end)
    if cache_file.exists():
        return pd.read_parquet(cache_file)

    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "daily": "precipitation_sum",
        "timezone": "America/New_York",
    }
    try:
        resp = requests.get(ARCHIVE_URL, params=params, timeout=timeout_s)
        resp.raise_for_status()
        payload = resp.json()
        daily = payload["daily"]
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(daily["time"]).date,
                "precipitation_mm": [p if p is not None else 0.0 for p in daily["precipitation_sum"]],
            }
        )
    except Exception as exc:
        raise RainfallFetchError(f"Open-Meteo archive fetch failed for ({lat}, {lon}): {exc}") from exc

    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache_file, index=False)
    return df


def get_daily_rainfall_with_fallback(
    lat: float, lon: float, start: date, end: date, *, seed: int | None = None
) -> tuple[pd.DataFrame, bool]:
    """Returns (df[date, precipitation_mm], used_real_data) for [start, end] inclusive.

    Tries the real Open-Meteo archive first (via `get_daily_rainfall`, so still
    cached). On `RainfallFetchError`, synthesizes a seasonal-sine-plus-noise
    weekly total per 7-day block, then splits each week's total across its 7
    days via a Dirichlet draw (bursty -- a few wet days, not an even drizzle)
    so the fallback series still has usable daily-level structure. This never
    raises: callers always get a usable daily frame.
    """
    try:
        return get_daily_rainfall(lat, lon, start, end), True
    except RainfallFetchError as exc:
        logger.warning("Falling back to synthetic daily rainfall for (%s, %s): %s", lat, lon, exc)
        base_seed = seed if seed is not None else config.RANDOM_SEED
        # Vary deterministically by location so different sites don't get
        # bit-identical fallback rain -- hash() of floats/tuples is stable
        # within a run (unlike str), so this stays reproducible.
        site_seed = (base_seed + abs(hash((round(lat, 4), round(lon, 4))))) % (2**32)
        rng = np.random.default_rng(site_seed)

        days = list(pd.date_range(start, end, freq="D").date)
        n_days = len(days)
        n_blocks = -(-n_days // 7)  # ceil
        block_idx = np.arange(n_blocks)
        weekly_totals = np.clip(
            30 + 20 * np.sin(2 * np.pi * block_idx / 52.0) + rng.normal(0, 12, n_blocks), 0, None
        )

        daily_values: list[float] = []
        for total in weekly_totals:
            shares = rng.dirichlet(np.full(7, 0.3))
            daily_values.extend(total * shares)
        daily_values = daily_values[:n_days]

        return pd.DataFrame({"date": days, "precipitation_mm": daily_values}), False


def aggregate_daily_to_weekly(daily_df: pd.DataFrame, weeks: list[date]) -> pd.DataFrame:
    """Aggregates a [date, precipitation_mm] daily frame into weekly features,
    one row per entry in `weeks` (each a Mon-Sun inclusive window).

    Columns: week_start, weekly_rainfall_mm, max_daily_rainfall_mm, rain_days_count.
    """
    daily = daily_df.set_index("date")["precipitation_mm"]
    rows = []
    for w in weeks:
        vals = [float(daily.get(w + timedelta(days=d), 0.0)) for d in range(7)]
        rows.append(
            {
                "week_start": w,
                "weekly_rainfall_mm": sum(vals),
                "max_daily_rainfall_mm": max(vals),
                "rain_days_count": sum(1 for v in vals if v >= 1.0),
            }
        )
    return pd.DataFrame(rows)
