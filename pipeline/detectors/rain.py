"""D3 - "Is there a rain -> sewage overflow pattern?"

Runs on the **M1_norain** draws. M1 already assumes rain raises the chance of an excursion
(`beta_rain`), so asking M1 whether rain causes excursions would partly return its own
assumption. M1_norain never saw rain, so any association found here comes from the reports.

Evidence, in order of weight:
  1. Incidence rate ratio (IRR) of excursions in rain-exposed vs dry site-weeks, per posterior draw
     -> posterior median, 90% interval, P(IRR > 1). Pooled, and split CSO-adjacent vs other sites.
  2. Placebo: the same statistic with the rain series circularly shifted by every offset except
     +/-2 weeks -> permutation p-value (guards against seasonal coincidence).
  3. Model-free: share of sewage-smell reports in rain-exposed vs dry weeks.
  4. Corroboration only: M1's `beta_rain` posterior (model-assisted, so never decisive).

Only site-weeks with at least one report are used: elsewhere the no-rain model's excursion is
pure prior and would only dilute the comparison.
"""

from __future__ import annotations

import numpy as np

from pipeline.common import config
from pipeline.detectors.draws import PosteriorDraws, excursion_effects

PLACEBO_EXCLUDE_WEEKS = 2


def rain_exposure(heavy_rain: np.ndarray, lag: int = config.RAIN_LAG_WEEKS) -> np.ndarray:
    """(T,) bool: heavy rain this week or in any of the previous `lag` weeks."""
    heavy = heavy_rain.astype(bool)
    exposed = heavy.copy()
    for k in range(1, lag + 1):
        exposed[k:] |= heavy[:-k]
    return exposed


def _irr(events: np.ndarray, exposed_mask: np.ndarray, observed: np.ndarray) -> np.ndarray:
    """events: (..., S, T) in [0, 1]; returns IRR over the leading axes (smoothed by +0.5 / +1)."""
    rain = observed & exposed_mask[None, :]
    dry = observed & ~exposed_mask[None, :]
    k_r, n_r = (events * rain).sum(axis=(-2, -1)), rain.sum()
    k_d, n_d = (events * dry).sum(axis=(-2, -1)), dry.sum()
    return ((k_r + 0.5) / (n_r + 1)) / ((k_d + 0.5) / (n_d + 1))


def _summary(irr: np.ndarray) -> dict:
    return {
        "irr_median": float(np.median(irr)),
        "irr_q05": float(np.quantile(irr, 0.05)),
        "irr_q95": float(np.quantile(irr, 0.95)),
        "p_irr_gt_1": float(np.mean(irr > 1)),
    }


def placebo_p_value(p_event: np.ndarray, exposed: np.ndarray, observed: np.ndarray) -> tuple[float, int]:
    """Permutation p-value of the observed IRR against circularly shifted rain series."""
    T = len(exposed)
    observed_irr = float(_irr(p_event, exposed, observed))
    shifts = [k for k in range(1, T) if min(k, T - k) > PLACEBO_EXCLUDE_WEEKS]
    null = np.array([float(_irr(p_event, np.roll(exposed, k), observed)) for k in shifts])
    return float((1 + np.sum(null >= observed_irr)) / (1 + len(null))), len(null)


def verdict(p_gt_1: float, placebo_p: float, n_rain_weeks_observed: int) -> str:
    if n_rain_weeks_observed < config.RAIN_MIN_OBSERVED_WEEKS:
        return "insufficient evidence"
    if p_gt_1 >= config.RAIN_P_SUPPORTED and placebo_p < config.RAIN_PLACEBO_ALPHA:
        return "supported"
    if p_gt_1 < 0.5:
        return "not supported"
    return "inconclusive"


def analyse_rain(
    d: PosteriorDraws,
    heavy_rain: np.ndarray,
    n_reports: np.ndarray,
    is_cso: np.ndarray,
    sewage_by_report: tuple[np.ndarray, np.ndarray] | None = None,
    corroborating: PosteriorDraws | None = None,
) -> dict:
    """Returns the D3 result (see detector_rain.json).

    n_reports: (S, T); is_cso: (S,) bool; sewage_by_report: (week_idx, sewage flag with NaN).
    """
    drop_w, _ = excursion_effects(d)
    events = (drop_w > config.DETECT_DELTA).astype(float)  # (N, S, T)
    exposed = rain_exposure(heavy_rain)
    observed = n_reports > 0

    result: dict = {
        "model_variant": d.variant,
        "thresholds": {"delta_W": config.DETECT_DELTA, "rain_lag_weeks": config.RAIN_LAG_WEEKS},
        "n_rain_exposed_weeks": int(exposed.sum()),
        "n_rain_exposed_weeks_with_reports": int((observed & exposed[None, :]).any(axis=0).sum()),
        "n_observed_site_weeks": int(observed.sum()),
    }

    groups = {"pooled": np.ones(len(is_cso), bool), "cso_adjacent": is_cso, "other_sites": ~is_cso}
    for name, mask in groups.items():
        obs_g = observed & mask[:, None]
        irr = _irr(events, exposed, obs_g)
        result[name] = _summary(irr)
        p_val, n_shifts = placebo_p_value(events.mean(axis=0), exposed, obs_g)
        result[name]["placebo_p"] = p_val
        result[name]["verdict"] = verdict(
            result[name]["p_irr_gt_1"], p_val, int((obs_g & exposed[None, :]).any(axis=0).sum())
        )
    result["n_placebo_shifts"] = n_shifts
    result["verdict"] = result["pooled"]["verdict"]

    if sewage_by_report is not None:
        week_idx, sewage = sewage_by_report
        has = ~np.isnan(sewage)
        rain_rep = exposed[week_idx] & has
        dry_rep = ~exposed[week_idx] & has
        result["sewage_smell_share"] = {
            "rain_weeks": float(sewage[rain_rep].mean()) if rain_rep.any() else None,
            "dry_weeks": float(sewage[dry_rep].mean()) if dry_rep.any() else None,
            "n_reports_rain": int(rain_rep.sum()),
            "n_reports_dry": int(dry_rep.sum()),
        }

    if corroborating is not None and corroborating.beta_rain is not None:
        b = corroborating.beta_rain
        result["corroboration_beta_rain"] = {
            "model_variant": corroborating.variant,
            "median": float(np.median(b)),
            "q05": float(np.quantile(b, 0.05)),
            "q95": float(np.quantile(b, 0.95)),
            "p_positive": float(np.mean(b > 0)),
            "note": "Model-assisted (rain is inside this model's prior); supporting evidence only.",
        }
    return result
