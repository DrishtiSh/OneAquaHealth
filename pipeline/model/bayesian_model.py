"""Stage 5: Fit a Bayesian model (PyMC, NUTS sampler) estimating two latent scores per
site/week: W (water quality) and H (human-health-relevant risk), with uncertainty
intervals, not point guesses.

Model family (see the approved plan):
  * M0        -- per-site partially pooled level + slow AR(1) drift for W and H, tied to the
                 reports through a rubric-anchored measurement model.
  * M1        -- M0 plus a shared, sparse "contamination excursion" e_st >= 0 that pushes W
                 down and H up for a week or two, with rainfall as a weak covariate on it.
  * M1_norain -- M1 with the rainfall coefficients fixed at 0 (ablation, so Stage 6 can check
                 that a rain -> overflow finding is not simply built into this stage).

W and H are 0-100 *indices* anchored to the citizen rubrics (clarity 1-5, smell intensity
0-3), not calibrated instruments. Exposure is deliberately NOT part of the fit; H is a
contamination hazard and Stage 7 joins exposure afterwards.

The sampler is nutpie (numba backend, still NUTS). PyTensor's C++ backend is disabled
because it does not compile reliably on Windows/MinGW -- this must happen before pymc is
imported.
"""

from __future__ import annotations

import os

_flags = os.environ.get("PYTENSOR_FLAGS", "")
if "cxx" not in _flags:
    os.environ["PYTENSOR_FLAGS"] = (_flags + ",cxx=").lstrip(",")

import json  # noqa: E402
import logging  # noqa: E402
import time  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402

import arviz as az  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pymc as pm  # noqa: E402
import pytensor.tensor as pt  # noqa: E402
import xarray as xr  # noqa: E402

from pipeline.common import config, io_utils, schema  # noqa: E402
from pipeline.model import data_prep, diagnostics  # noqa: E402
from pipeline.model.data_prep import ModelInputs  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

VARIANTS = ("M0", "M1", "M1_norain")
BIG = 1e3  # stand-in for +/- infinity in probit/logit cutpoints

# Evidence flag thresholds (documented so Stage 10 can explain them).
EVIDENCE_MIN_INFORMATIVE = 2  # informative fields in the site-week for "sufficient"
EVIDENCE_MAX_W_INTERVAL = 30.0  # 90% W interval width (index points) allowed for "sufficient"

# Junk-report densities: a misreport is uniform over each field's vocabulary.
_JUNK = {
    "clarity": np.log(1 / 5),
    "smell_intensity": np.log(1 / 4),
    "trash": np.log(1 / 5),
    "presence": np.log(1 / 2),
    "diversity": np.log(1 / 4),
    "sewage_yes": np.log(1 / 6),
    "sewage_no": np.log(5 / 6),
}


# ----------------------------------------------------------------------------- building blocks


def _ar1(phi, sigma, eps, n_weeks: int):
    """Stationary AR(1) along axis 1 as a matrix filter (no scan): f[:, t] = sum_k phi^(t-k) e_k.

    Cheap for T ~ 100 and NUTS/numba-friendly. The first innovation is inflated by
    1/sqrt(1 - phi^2) so the process starts at its stationary distribution.
    """
    d = np.arange(n_weeks)[:, None] - np.arange(n_weeks)[None, :]
    lower = pt.switch(d >= 0, phi ** np.where(d >= 0, d, 0), 0.0)  # L[t, k]
    scale = pt.concatenate([(1.0 / pt.sqrt(1.0 - phi**2))[None], pt.ones(n_weeks - 1)])
    return sigma * pt.dot(eps * scale[None, :], lower.T)


def _log_sigmoid(x):
    return -pt.softplus(-x)


def _norm_cdf(x):
    return pm.math.invprobit(x)


def _ordinal_probit_loglik(observed, mask, mu, sigma, n_levels: int, first_level: int):
    """log P(level | mu, sigma) for a rounding model: level k iff latent in (k-.5, k+.5).

    Ends are open (-inf below the first level, +inf above the last). `observed` may hold NaN
    where the field was not reported -- those rows are computed on a dummy value and masked.
    """
    y = np.where(mask, observed, first_level).astype(float)
    hi = np.where(y >= first_level + n_levels - 1, BIG, y + 0.5)
    lo = np.where(y <= first_level, -BIG, y - 0.5)
    p = _norm_cdf((hi - mu) / sigma) - _norm_cdf((lo - mu) / sigma)
    return pt.log(p + 1e-12) * mask


def _ordered_cutpoints(name: str, n_cuts: int, first_mean: float):
    first = pm.Normal(f"{name}_c0", first_mean, 1.0)
    if n_cuts == 1:
        return first[None]
    deltas = pm.HalfNormal(f"{name}_dc", 1.5, shape=n_cuts - 1)
    return pt.concatenate([first[None], first + pt.cumsum(deltas)])


def _ordered_logit_loglik(observed, mask, eta, cuts, n_levels: int):
    y = np.where(mask, observed, 0).astype(int)
    padded = pt.concatenate([pt.as_tensor([-BIG]), cuts, pt.as_tensor([BIG])])
    hi, lo = padded[y + 1], padded[y]
    p = pm.math.sigmoid(hi - eta) - pm.math.sigmoid(lo - eta)
    return pt.log(p + 1e-12) * mask


def build_model(inp: ModelInputs, variant: str = "M1", *, use_observer_effects: bool = True) -> pm.Model:
    if variant not in VARIANTS:
        raise ValueError(f"variant must be one of {VARIANTS}, got {variant!r}")

    S, T, R = inp.n_sites, inp.n_weeks, inp.n_reports_total
    si, wi = inp.site_idx, inp.week_idx

    coords = {"site": inp.site_ids, "week": [str(w) for w in inp.weeks]}
    with pm.Model(coords=coords) as model:
        # -- site levels (logit scale), partially pooled --------------------------------
        mu0_w = pm.Normal("mu0_W", 1.0, 1.0)
        mu0_h = pm.Normal("mu0_H", -1.0, 1.0)
        sd_mu_w = pm.HalfNormal("sd_mu_W", 0.5)
        sd_mu_h = pm.HalfNormal("sd_mu_H", 0.5)
        mu_w = pm.Deterministic("mu_W", mu0_w + sd_mu_w * pm.Normal("mu_W_raw", 0, 1, shape=S), dims="site")
        mu_h = pm.Deterministic("mu_H", mu0_h + sd_mu_h * pm.Normal("mu_H_raw", 0, 1, shape=S), dims="site")

        # -- slow drift: AR(1) per site, W and H innovations correlated -----------------
        phi_w = pm.Beta("phi_W", 8, 2)
        phi_h = pm.Beta("phi_H", 8, 2)
        # LogNormal (not HalfNormal): no pile-up at 0, which funnels the non-centered drift.
        # Median 0.15 logit units/week, 95% range ~0.04-0.55.
        sigma_fw = pm.LogNormal("sigma_f_W", np.log(0.15), 0.7)
        sigma_fh = pm.LogNormal("sigma_f_H", np.log(0.15), 0.7)
        rho = pm.Deterministic("rho", pt.tanh(pm.Normal("rho_raw", 0.0, 1.0)))
        eps_w = pm.Normal("eps_W", 0, 1, shape=(S, T))
        eps_h = rho * eps_w + pt.sqrt(1 - rho**2) * pm.Normal("eps_H_raw", 0, 1, shape=(S, T))
        f_w = _ar1(phi_w, sigma_fw, eps_w, T)
        f_h = _ar1(phi_h, sigma_fh, eps_h, T)

        z_w = mu_w[:, None] + f_w
        z_h = mu_h[:, None] + f_h

        # -- contamination excursion (M1 family) ---------------------------------------
        if variant == "M0":
            e = pt.zeros((S, T))
        else:
            m0 = pm.Normal("m0", -2.5, 0.75)
            sd_m = pm.HalfNormal("sd_m", 0.5)
            m_s = m0 + sd_m * pm.Normal("m_raw", 0, 1, shape=S)
            sigma_x = pm.HalfNormal("sigma_x", 1.5)
            u = pm.StudentT("x_raw", nu=4, mu=0, sigma=1, shape=(S, T))
            x = m_s[:, None] + sigma_x * u
            if variant == "M1":
                beta_rain = pm.Normal("beta_rain", 0, 0.5)
                beta_ante = pm.Normal("beta_ante", 0, 0.5)
                x = x + beta_rain * inp.heavy_rain[None, :] + beta_ante * inp.antecedent_z[None, :]
            e = pm.Deterministic("e", pt.softplus(x), dims=("site", "week"))
            lam_h = pm.HalfNormal("lam_H", 2.0)  # lam_W is fixed at 1 to anchor e's scale
            z_w = z_w - e
            z_h = z_h + lam_h * e

        w_frac = pm.math.sigmoid(z_w)
        h_frac = pm.math.sigmoid(z_h)
        pm.Deterministic("W", 100.0 * w_frac, dims=("site", "week"))
        pm.Deterministic("H", 100.0 * h_frac, dims=("site", "week"))
        w_r, h_r = w_frac[si, wi], h_frac[si, wi]
        # Loadings act on deviations from the typical level, which decorrelates them from their
        # intercepts/cutpoints (W and H barely vary, so uncentred they are near-collinear).
        w_ref, h_ref = pm.math.sigmoid(mu0_w), pm.math.sigmoid(mu0_h)

        # -- observer leniency (should come back ~0 on simulated data) ------------------
        if use_observer_effects and inp.n_observers > 1:
            tau_c = pm.HalfNormal("tau_clarity", 0.3)
            tau_s = pm.HalfNormal("tau_smell", 0.3)
            off_c = tau_c * pm.Normal("obs_clarity_raw", 0, 1, shape=inp.n_observers)[inp.observer_idx]
            off_s = tau_s * pm.Normal("obs_smell_raw", 0, 1, shape=inp.n_observers)[inp.observer_idx]
        else:
            off_c = off_s = 0.0

        # -- measurement model ----------------------------------------------------------
        m_clarity, m_smell = ~np.isnan(inp.clarity), ~np.isnan(inp.smell_intensity)
        m_sewage, m_trash = ~np.isnan(inp.sewage), ~np.isnan(inp.trash)
        m_pres, m_div = ~np.isnan(inp.presence), ~np.isnan(inp.diversity)

        sigma_c = pm.HalfNormal("sigma_clarity", 1.0)
        sigma_s = pm.HalfNormal("sigma_smell", 1.0)
        ll_good = pt.zeros(R)
        ll_junk = np.zeros(R)

        # clarity 1-5 (1 = clear): latent = 1 + 4 * (1 - W/100)
        ll_good += _ordinal_probit_loglik(
            inp.clarity, m_clarity, 1.0 + 4.0 * (1.0 - w_r) + off_c, sigma_c, n_levels=5, first_level=1
        )
        ll_junk += m_clarity * _JUNK["clarity"]

        # smell intensity 0-3: latent = 3 * H/100
        ll_good += _ordinal_probit_loglik(
            inp.smell_intensity, m_smell, 3.0 * h_r + off_s, sigma_s, n_levels=4, first_level=0
        )
        ll_junk += m_smell * _JUNK["smell_intensity"]

        # sewage smell flag: logistic in H (sign fixed by domain: sewage smell => hazard)
        a_sew = pm.Normal("a_sewage", -2.5, 1.5)
        b_sew = pm.HalfNormal("b_sewage", 2.0)
        eta_sew = a_sew + b_sew * 5.0 * (h_r - h_ref)
        y_sew = np.where(m_sewage, inp.sewage, 0.0)
        ll_good += (y_sew * _log_sigmoid(eta_sew) + (1 - y_sew) * _log_sigmoid(-eta_sew)) * m_sewage
        ll_junk += m_sewage * np.where(y_sew == 1, _JUNK["sewage_yes"], _JUNK["sewage_no"])

        # trash 0-4, insects: free (symmetric) loadings so uninformative fields go to ~0
        b_trash = pm.Normal("b_trash", 0, 1)
        cuts_t = _ordered_cutpoints("trash", 4, -0.5)
        ll_good += _ordered_logit_loglik(inp.trash, m_trash, b_trash * 4.0 * (w_ref - w_r), cuts_t, 5)
        ll_junk += m_trash * _JUNK["trash"]

        a_pres = pm.Normal("a_presence", 0, 1.5)
        b_pres = pm.Normal("b_presence", 0, 1)
        eta_pres = a_pres + b_pres * 5.0 * (w_r - w_ref)
        y_pres = np.where(m_pres, inp.presence, 0.0)
        ll_good += (y_pres * _log_sigmoid(eta_pres) + (1 - y_pres) * _log_sigmoid(-eta_pres)) * m_pres
        ll_junk += m_pres * _JUNK["presence"]

        b_div = pm.Normal("b_diversity", 0, 1)
        cuts_d = _ordered_cutpoints("diversity", 3, -0.5)
        ll_good += _ordered_logit_loglik(inp.diversity, m_div, b_div * 5.0 * (w_r - w_ref), cuts_d, 4)
        ll_junk += m_div * _JUNK["diversity"]

        # -- report-level misreport mixture (whole report is junk or genuine) -----------
        eps_junk = pm.Beta("eps_misreport", 1.5, 20.0)
        report_ll = pt.logaddexp(pt.log1p(-eps_junk) + ll_good, pt.log(eps_junk) + ll_junk)
        pm.Potential("reports", pt.sum(report_ll))

    return model


# ----------------------------------------------------------------------------- fitting


@dataclass(frozen=True)
class SamplerSettings:
    draws: int = 3000
    tune: int = 1500
    chains: int = 4
    target_accept: float = 0.9
    seed: int = config.RANDOM_SEED


def fit(model: pm.Model, settings: SamplerSettings = SamplerSettings()) -> az.InferenceData:
    with model:
        return pm.sample(
            draws=settings.draws,
            tune=settings.tune,
            chains=settings.chains,
            target_accept=settings.target_accept,
            random_seed=settings.seed,
            nuts_sampler="nutpie",
            progressbar=False,
        )


# ----------------------------------------------------------------------------- summarising


def _flat(idata: az.InferenceData, name: str) -> np.ndarray:
    """(chain, draw, S, T) posterior variable -> (n_samples, S, T)."""
    arr = idata.posterior[name].to_numpy()
    return arr.reshape(-1, *arr.shape[2:])


def evidence_flag(n_informative: int, w_interval_width: float) -> str:
    if n_informative == 0:
        return "insufficient"  # posterior comes from the temporal/site prior alone
    if n_informative >= EVIDENCE_MIN_INFORMATIVE and w_interval_width <= EVIDENCE_MAX_W_INTERVAL:
        return "sufficient"
    return "weak"


def summarise_scores(
    idata: az.InferenceData, inp: ModelInputs, variant: str, mixing_flags: np.ndarray | None = None
) -> pd.DataFrame:
    """One row per site_id x week_start -- see schema.ModelScore.

    `mixing_flags` (S, T) marks site-weeks whose posterior mixed poorly (typically a lone
    extreme report that is either an event or a misreport); their evidence is capped at "weak".
    """
    if mixing_flags is None:
        mixing_flags = np.zeros((inp.n_sites, inp.n_weeks), dtype=bool)
    w, h = _flat(idata, "W"), _flat(idata, "H")
    e = _flat(idata, "e") if "e" in idata.posterior else np.zeros_like(w)
    qs = [0.05, 0.25, 0.5, 0.75, 0.95]
    wq, hq = np.quantile(w, qs, axis=0), np.quantile(h, qs, axis=0)

    rows = []
    for s, site_id in enumerate(inp.site_ids):
        for t, week in enumerate(inp.weeks):
            row = {"site_id": site_id, "week_start": week}
            for name, arr, quant in (("W", w, wq), ("H", h, hq)):
                row[f"{name}_mean"] = float(arr[:, s, t].mean())
                row[f"{name}_sd"] = float(arr[:, s, t].std(ddof=1))
                for q, label in zip(range(5), ("05", "25", "50", "75", "95")):
                    row[f"{name}_q{label}"] = float(quant[q, s, t])
            row["e_mean"] = float(e[:, s, t].mean())
            row["n_reports"] = int(inp.n_reports[s, t])
            row["n_informative_fields"] = int(inp.n_informative[s, t])
            row["mixing_flag"] = bool(mixing_flags[s, t])
            row["evidence"] = evidence_flag(row["n_informative_fields"], row["W_q95"] - row["W_q05"])
            if row["mixing_flag"] and row["evidence"] == "sufficient":
                row["evidence"] = "weak"
            row["model_variant"] = variant
            rows.append(row)
    return pd.DataFrame(rows)


def _scalar_var_names(idata: az.InferenceData) -> list[str]:
    """Hyperparameters worth reporting (everything except the big latent arrays)."""
    skip = {"W", "H", "e", "eps_W", "eps_H_raw", "x_raw", "obs_clarity_raw", "obs_smell_raw"}
    return [v for v in idata.posterior.data_vars if v not in skip and not v.endswith(("__", "_raw"))]


def summarise_params(idata: az.InferenceData, inp: ModelInputs, variant: str) -> pd.DataFrame:
    summary = az.summary(idata, var_names=_scalar_var_names(idata), hdi_prob=0.9).reset_index(names="param")
    site_lookup = {str(i): s for i, s in enumerate(inp.site_ids)}
    summary["param"] = summary["param"].map(
        lambda p: (
            f"{p.split('[')[0]}[{site_lookup.get(p.split('[')[1].rstrip(']'), p.split('[')[1].rstrip(']'))}]"
            if "[" in p and p.split("[")[0] in {"mu_W", "mu_H", "mu_W_raw", "mu_H_raw", "m_raw"}
            else p
        )
    )
    summary.insert(0, "model_variant", variant)
    return summary


def thin_draws(idata: az.InferenceData, inp: ModelInputs, n: int = 500, seed: int = config.RANDOM_SEED) -> xr.Dataset:
    """Joint posterior draws for Stage 6: W, H, e with dims (sample, site, week), plus the scalar
    parameters Stage 6 needs per draw (lam_H for the H counterfactual, beta_rain/beta_ante for the
    rain corroboration) with dims (sample,). All share the same sample index."""
    names = [v for v in ("W", "H", "e", "lam_H", "beta_rain", "beta_ante") if v in idata.posterior]
    stacked = idata.posterior[names].stack(sample=("chain", "draw")).transpose("sample", ...)
    rng = np.random.default_rng(seed)
    pick = np.sort(rng.choice(stacked.sizes["sample"], size=min(n, stacked.sizes["sample"]), replace=False))
    out = stacked.isel(sample=pick).reset_index("sample", drop=True)
    return out.assign_coords(sample=np.arange(len(pick)))


def variant_path(path: Path, variant: str, primary: str = "M1") -> Path:
    """Primary variant keeps the canonical filename; others get a `__<variant>` suffix."""
    return path if variant == primary else path.with_name(f"{path.stem}__{variant}{path.suffix}")


def run_variant(
    inp: ModelInputs,
    variant: str,
    settings: SamplerSettings = SamplerSettings(),
    *,
    strict: bool = True,
    write: bool = True,
) -> dict:
    """Fit one variant, gate on diagnostics, write outputs. Returns a dict of results."""
    logger.info("Fitting %s (%d sites x %d weeks, %d reports)", variant, inp.n_sites, inp.n_weeks, inp.n_reports_total)
    model = build_model(inp, variant)
    t0 = time.time()
    idata = fit(model, settings)
    runtime = time.time() - t0

    diag, mixing_flags = diagnostics.compute_diagnostics(idata, hyper_vars=_scalar_var_names(idata))
    diag.update({"model_variant": variant, "runtime_s": round(runtime, 1), "seed": settings.seed,
                 "n_reports": inp.n_reports_total, "n_sites": inp.n_sites, "n_weeks": inp.n_weeks})
    diag["ppc"] = diagnostics.posterior_predictive_summary(idata, inp)

    scores = summarise_scores(idata, inp, variant, mixing_flags)
    params = summarise_params(idata, inp, variant)
    result = {"variant": variant, "idata": idata, "scores": scores, "params": params, "diagnostics": diag}

    blocked = strict and not diag["passed"]
    if write:
        # A failed gate still records diagnostics (for inspection) but never scores/draws.
        _write_outputs(result, inp, diagnostics_only=blocked)
    if blocked:
        diagnostics.assert_converged(diag)
    return result


def _write_outputs(result: dict, inp: ModelInputs, *, diagnostics_only: bool = False) -> None:
    variant = result["variant"]
    diag_path = variant_path(config.MODEL_DIAG_PATH, variant)
    diag_path.parent.mkdir(parents=True, exist_ok=True)
    diag_path.write_text(json.dumps(result["diagnostics"], indent=2, default=float))
    if diagnostics_only:
        return

    schema.validate_dataframe(result["scores"], schema.ModelScore, name=f"model_scores[{variant}]")
    io_utils.write_parquet(result["scores"], variant_path(config.MODEL_SCORES_PATH, variant))
    io_utils.write_parquet(result["params"], variant_path(config.MODEL_PARAMS_PATH, variant))

    draws_path = variant_path(config.MODEL_DRAWS_PATH, variant)
    draws_path.parent.mkdir(parents=True, exist_ok=True)
    thin_draws(result["idata"], inp).to_netcdf(draws_path, engine="h5netcdf")


def _print_summary(result: dict) -> None:
    d, sc = result["diagnostics"], result["scores"]
    print(f"--- Stage 5 model summary ({result['variant']}) ---")
    print(f"Runtime: {d['runtime_s']}s  max R-hat: {d['rhat_max']:.3f}  min ESS bulk: {d['ess_bulk_min']:.0f}  "
          f"divergences: {d['divergences']}  mixing-flagged site-weeks: {d['n_mixing_flagged_site_weeks']}  "
          f"converged: {d['passed']}")
    print(f"Site-weeks: {len(sc)}  evidence: {sc['evidence'].value_counts().to_dict()}")
    print(f"Mean W: {sc['W_mean'].mean():.1f}  Mean H: {sc['H_mean'].mean():.1f}  "
          f"mean 90% W-interval width: {(sc['W_q95'] - sc['W_q05']).mean():.1f}")
    print("---------------------------------------------")


def run(variants: tuple[str, ...] = ("M1", "M1_norain"), settings: SamplerSettings | None = None) -> dict[str, Path]:
    """Stage 5 entry point: fit the primary model (M1) plus the no-rain ablation."""
    settings = settings or SamplerSettings()
    inp = data_prep.load_inputs()

    if config.EXPOSURE_FEATURES_PATH.exists():
        weights = data_prep.compute_exposure_weights(io_utils.read_parquet(config.EXPOSURE_FEATURES_PATH))
        io_utils.write_parquet(weights, config.SITE_EXPOSURE_WEIGHTS_PATH)

    for variant in variants:
        result = run_variant(inp, variant, settings)
        _print_summary(result)

    return {
        "model_scores": config.MODEL_SCORES_PATH,
        "model_draws": config.MODEL_DRAWS_PATH,
        "model_params": config.MODEL_PARAMS_PATH,
        "model_diagnostics": config.MODEL_DIAG_PATH,
        "site_exposure_weights": config.SITE_EXPOSURE_WEIGHTS_PATH,
    }


if __name__ == "__main__":
    run()
