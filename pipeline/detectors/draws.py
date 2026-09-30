"""Stage 6 input: the Stage 5 joint posterior draws, plus the excursion counterfactuals.

Every detector works per posterior draw and aggregates afterwards, so results are probabilities
with intervals rather than yes/no calls. This module is the only place Stage 6 reads the draws.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import xarray as xr

from pipeline.common import config
from pipeline.model.bayesian_model import variant_path

_EPS = 1e-6
ROLLING_BASELINE_WEEKS = 8  # M0 fallback only (M0 has no excursion term)


@dataclass(frozen=True)
class PosteriorDraws:
    variant: str
    site_ids: list[str]
    weeks: list[date]
    W: np.ndarray  # (N, S, T), 0-100
    H: np.ndarray  # (N, S, T), 0-100
    e: np.ndarray | None  # (N, S, T) contamination excursion; None for M0
    lam_H: np.ndarray | None  # (N,)
    beta_rain: np.ndarray | None  # (N,) only for M1
    beta_ante: np.ndarray | None  # (N,) only for M1

    @property
    def n_draws(self) -> int:
        return self.W.shape[0]


def from_dataset(ds: xr.Dataset, variant: str) -> PosteriorDraws:
    def opt(name: str) -> np.ndarray | None:
        return ds[name].to_numpy() if name in ds else None

    return PosteriorDraws(
        variant=variant,
        site_ids=[str(s) for s in ds["site"].to_numpy()],
        weeks=[date.fromisoformat(str(w)) for w in ds["week"].to_numpy()],
        W=ds["W"].to_numpy(),
        H=ds["H"].to_numpy(),
        e=opt("e"),
        lam_H=opt("lam_H"),
        beta_rain=opt("beta_rain"),
        beta_ante=opt("beta_ante"),
    )


def load_draws(variant: str) -> PosteriorDraws:
    path = variant_path(config.MODEL_DRAWS_PATH, variant)
    if not path.exists():
        raise FileNotFoundError(f"{path} not found -- run Stage 5 (model) first.")
    with xr.open_dataset(path, engine="h5netcdf") as ds:
        return from_dataset(ds.load(), variant)


def _logit(score: np.ndarray) -> np.ndarray:
    p = np.clip(score / 100.0, _EPS, 1 - _EPS)
    return np.log(p) - np.log1p(-p)


def _sigmoid100(z: np.ndarray) -> np.ndarray:
    return 100.0 / (1.0 + np.exp(-z))


def _rolling_median_drop(x: np.ndarray, window: int, sign: float) -> np.ndarray:
    """sign * (median of the previous `window` weeks - x), per draw; 0 for the first week."""
    out = np.zeros_like(x)
    for t in range(1, x.shape[-1]):
        base = np.median(x[..., max(0, t - window) : t], axis=-1)
        out[..., t] = sign * (base - x[..., t])
    return out


def excursion_effects(d: PosteriorDraws) -> tuple[np.ndarray, np.ndarray | None]:
    """(drop_W, rise_H), each (N, S, T) in index points, per draw.

    M1 family: exact counterfactual from the model structure (zW = ... - e, zH = ... + lam_H * e):
        W0 = 100 * sigmoid(logit(W) + e),        drop_W = W0 - W
        H0 = 100 * sigmoid(logit(H) - lam_H * e), rise_H = H - H0
    This isolates the contamination excursion from the slow seasonal drift, and unlike a rolling
    baseline it isn't contaminated by earlier events.
    M0 (no excursion): fallback against the median of the previous 8 weeks.
    """
    if d.e is None:
        return (
            _rolling_median_drop(d.W, ROLLING_BASELINE_WEEKS, sign=1.0),
            _rolling_median_drop(d.H, ROLLING_BASELINE_WEEKS, sign=-1.0),
        )
    drop_w = _sigmoid100(_logit(d.W) + d.e) - d.W
    rise_h = None
    if d.lam_H is not None:
        rise_h = d.H - _sigmoid100(_logit(d.H) - d.lam_H[:, None, None] * d.e)
    return drop_w, rise_h
