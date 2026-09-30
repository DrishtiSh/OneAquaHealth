"""Stage 5 fit diagnostics: convergence gate, posterior-predictive checks, calibration helpers.

The gate is deliberately loud: a stage that emits confident-looking intervals from a
non-converged fit is worse than one that stops.

Two levels of checking:
  * Hyperparameters (loadings, scales, misreport rate, ...) must meet strict R-hat / ESS
    targets -- if they don't, the fit is not trustworthy and the stage fails.
  * Individual site-week scores are checked one by one. A lone, extreme report is either a
    real event or a misreport, which makes that site-week's posterior genuinely bimodal and
    slow to mix. Those rows are *flagged* (`mixing_flag`) and their evidence is downgraded
    rather than hidden; the stage only fails if too many rows are flagged.
"""

from __future__ import annotations

from dataclasses import dataclass

import arviz as az
import numpy as np

from pipeline.model.data_prep import ModelInputs


class ModelConvergenceError(RuntimeError):
    """Raised when the sampler output fails the convergence gate."""


@dataclass(frozen=True)
class Thresholds:
    rhat_max: float = 1.01
    ess_bulk_min: float = 400.0
    ess_tail_min: float = 400.0
    max_divergences: int = 0
    bfmi_min: float = 0.3
    max_flagged_fraction: float = 0.02  # share of site-weeks allowed to be mixing-flagged


SCORE_VARS = ("W", "H", "e")


def flag_site_weeks(idata: az.InferenceData, thresholds: Thresholds = Thresholds()) -> np.ndarray:
    """(S, T) bool: True where W, H or e fails R-hat / bulk-ESS / tail-ESS for that site-week."""
    flags = None
    for name in (v for v in SCORE_VARS if v in idata.posterior):
        rhat = az.rhat(idata, var_names=[name])[name].to_numpy()
        ess_b = az.ess(idata, var_names=[name], method="bulk")[name].to_numpy()
        ess_t = az.ess(idata, var_names=[name], method="tail")[name].to_numpy()
        bad = ~(rhat <= thresholds.rhat_max) | ~(ess_b >= thresholds.ess_bulk_min) | ~(ess_t >= thresholds.ess_tail_min)
        # e is identically 0 for M0 (not sampled); NaN diagnostics there must not flag rows.
        flags = bad if flags is None else (flags | bad)
    return flags


def compute_diagnostics(
    idata: az.InferenceData, *, hyper_vars: list[str], thresholds: Thresholds = Thresholds()
) -> tuple[dict, np.ndarray]:
    """Returns (diagnostics dict, (S, T) mixing-flag mask)."""
    hyper = [v for v in hyper_vars if v in idata.posterior]
    rhat = az.rhat(idata, var_names=hyper)
    ess_bulk = az.ess(idata, var_names=hyper, method="bulk")
    ess_tail = az.ess(idata, var_names=hyper, method="tail")
    rhat_max, rhat_var = max((float(np.nanmax(rhat[v].values)), v) for v in rhat.data_vars)
    ess_bulk_min, ess_bulk_var = min((float(np.nanmin(ess_bulk[v].values)), v) for v in ess_bulk.data_vars)
    ess_tail_min, ess_tail_var = min((float(np.nanmin(ess_tail[v].values)), v) for v in ess_tail.data_vars)

    flags = flag_site_weeks(idata, thresholds)
    n_flagged, flagged_fraction = int(flags.sum()), float(flags.mean())

    sample_stats = idata.sample_stats
    divergences = int(sample_stats["diverging"].sum()) if "diverging" in sample_stats else 0
    bfmi = float(np.min(az.bfmi(idata))) if "energy" in sample_stats else float("nan")

    failures = []
    if not rhat_max <= thresholds.rhat_max:
        failures.append(f"max hyperparameter R-hat {rhat_max:.3f} ({rhat_var}) > {thresholds.rhat_max}")
    if not ess_bulk_min >= thresholds.ess_bulk_min:
        failures.append(f"min hyperparameter bulk ESS {ess_bulk_min:.0f} ({ess_bulk_var}) < {thresholds.ess_bulk_min:.0f}")
    if not ess_tail_min >= thresholds.ess_tail_min:
        failures.append(f"min hyperparameter tail ESS {ess_tail_min:.0f} ({ess_tail_var}) < {thresholds.ess_tail_min:.0f}")
    if divergences > thresholds.max_divergences:
        failures.append(f"{divergences} divergent transitions")
    if not np.isnan(bfmi) and bfmi < thresholds.bfmi_min:
        failures.append(f"BFMI {bfmi:.2f} < {thresholds.bfmi_min}")
    if flagged_fraction > thresholds.max_flagged_fraction:
        failures.append(
            f"{n_flagged} site-weeks ({flagged_fraction:.1%}) mix poorly, above the "
            f"{thresholds.max_flagged_fraction:.0%} allowance"
        )

    diag = {
        "rhat_max": rhat_max,
        "rhat_max_var": rhat_var,
        "ess_bulk_min": ess_bulk_min,
        "ess_bulk_min_var": ess_bulk_var,
        "ess_tail_min": ess_tail_min,
        "ess_tail_min_var": ess_tail_var,
        "divergences": divergences,
        "bfmi_min": bfmi,
        "n_mixing_flagged_site_weeks": n_flagged,
        "mixing_flagged_fraction": flagged_fraction,
        "passed": not failures,
        "failures": failures,
    }
    return diag, flags


def assert_converged(diag: dict) -> None:
    if not diag["passed"]:
        raise ModelConvergenceError(
            "Stage 5 fit failed the convergence gate: " + "; ".join(diag["failures"])
            + ". Refusing to emit scores. (Diagnostics were still written for inspection.)"
        )


def posterior_predictive_summary(idata: az.InferenceData, inp: ModelInputs, n_draws: int = 200, seed: int = 0) -> dict:
    """Compare observed field frequencies with what the fitted model would generate.

    Simulates clarity / smell-intensity / sewage-flag for the *same* reports (same site-weeks)
    from posterior draws (genuine-report branch of the mixture, plus junk at rate eps).
    Returns observed vs predicted shares; big gaps mean the measurement model is misspecified.
    """
    rng = np.random.default_rng(seed)
    post = idata.posterior
    n = post.sizes["chain"] * post.sizes["draw"]
    pick = rng.choice(n, size=min(n_draws, n), replace=False)

    def flat(name):
        a = post[name].to_numpy()
        return a.reshape(-1, *a.shape[2:])[pick]

    w, h = flat("W")[:, inp.site_idx, inp.week_idx] / 100.0, flat("H")[:, inp.site_idx, inp.week_idx] / 100.0
    sig_c, sig_s = flat("sigma_clarity")[:, None], flat("sigma_smell")[:, None]
    eps = flat("eps_misreport")[:, None]
    junk = rng.random(w.shape) < eps

    out: dict = {}
    has_c = ~np.isnan(inp.clarity)
    clar = np.clip(np.rint(1 + 4 * (1 - w) + sig_c * rng.standard_normal(w.shape)), 1, 5)
    clar = np.where(junk, rng.integers(1, 6, w.shape), clar)[:, has_c]
    out["clarity"] = {
        "observed": [round(float((inp.clarity[has_c] == k).mean()), 3) for k in range(1, 6)],
        "predicted": [round(float((clar == k).mean()), 3) for k in range(1, 6)],
    }

    has_s = ~np.isnan(inp.smell_intensity)
    smell = np.clip(np.rint(3 * h + sig_s * rng.standard_normal(h.shape)), 0, 3)
    smell = np.where(junk, rng.integers(0, 4, h.shape), smell)[:, has_s]
    out["smell_intensity"] = {
        "observed": [round(float((inp.smell_intensity[has_s] == k).mean()), 3) for k in range(4)],
        "predicted": [round(float((smell == k).mean()), 3) for k in range(4)],
    }

    has_w = ~np.isnan(inp.sewage)
    h_ref = 1 / (1 + np.exp(-flat("mu0_H")))[:, None]
    eta = flat("a_sewage")[:, None] + flat("b_sewage")[:, None] * 5.0 * (h - h_ref)
    sew = rng.random(h.shape) < 1 / (1 + np.exp(-eta))
    sew = np.where(junk, rng.random(h.shape) < 1 / 6, sew)[:, has_w]
    out["sewage_share"] = {
        "observed": round(float(inp.sewage[has_w].mean()), 3),
        "predicted": round(float(sew.mean()), 3),
    }
    return out


def interval_coverage(truth: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> float:
    """Fraction of truths inside [lo, hi]. Used by the benchmark; no truth is read here."""
    return float(np.mean((truth >= lo) & (truth <= hi)))
