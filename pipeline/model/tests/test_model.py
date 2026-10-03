"""Stage 5 tests. Fast tests (data prep, schema, gate, firewall) always run; the `slow`
ones actually run NUTS on a tiny synthetic world with a planted event."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pipeline.common import schema
from pipeline.model import bayesian_model as bm
from pipeline.model import data_prep, diagnostics

from conftest import EVENT_SITE, EVENT_WEEKS, N_SITES, N_WEEKS, OUTLIER_SITE, OUTLIER_WEEK

MODEL_DIR = Path(bm.__file__).parent
# Stages 5-8 all sit on the model side of the truth firewall (only benchmark may read truth).
FIREWALLED_DIRS = tuple(MODEL_DIR.parent / d for d in ("model", "detectors", "nlg", "snapshot"))
TINY = bm.SamplerSettings(draws=250, tune=250, chains=4, seed=1)


# ----------------------------------------------------------------------------- fast tests


def test_model_package_never_reads_ground_truth():
    """Structural truth firewall: nothing under pipeline/model/, detectors/, nlg/ or snapshot/ (tests
    aside) may reference the simulator's hidden truth."""
    forbidden = re.compile(r"GROUND_TRUTH|ground_truth|W_true|H_true|events\.parquet|contamination_event_active")
    offenders = []
    for path in (p for d in FIREWALLED_DIRS for p in d.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        }
        for node in ast.walk(tree):
            # Inspect code (names, attributes, imports, string literals); docstrings/comments
            # may *mention* the rule.
            texts = []
            if isinstance(node, ast.Name):
                texts.append(node.id)
            elif isinstance(node, ast.Attribute):
                texts.append(node.attr)
            elif isinstance(node, ast.alias):
                texts.append(node.name)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                texts.append(node.value)
            # The leak *guards* (schema.assert_no_ground_truth_leak and the column list it checks,
            # schema.GROUND_TRUTH_ONLY_COLUMNS) are the only allowed mentions.
            offenders += [
                f"{path.name}:{getattr(node, 'lineno', '?')}: {t}"
                for t in texts
                if forbidden.search(t.replace("assert_no_ground_truth_leak", "").replace("GROUND_TRUTH_ONLY_COLUMNS", ""))
            ]
    assert not offenders, "\n".join(offenders)


def test_build_inputs_shapes_and_alignment(toy):
    inp = data_prep.build_inputs(toy["obs"], toy["weather"], toy["sites"])
    assert inp.site_ids == ["toy-0", "toy-1", "toy-2"]  # head -> mouth
    assert (inp.n_sites, inp.n_weeks) == (N_SITES, N_WEEKS)
    assert inp.n_reports.shape == (N_SITES, N_WEEKS)
    assert inp.n_reports.sum() == len(toy["obs"])
    assert len(inp.heavy_rain) == len(inp.antecedent_z) == N_WEEKS
    assert set(np.flatnonzero(inp.heavy_rain)) == set(EVENT_WEEKS)
    assert abs(inp.antecedent_z.mean()) < 1e-9
    # Known-unobserved window has no reports.
    assert inp.n_reports[2, 5:10].sum() == 0
    # Every report index points into the grid.
    assert inp.site_idx.max() < N_SITES and inp.week_idx.max() < N_WEEKS


def test_missing_fields_stay_nan_not_imputed(toy):
    obs = toy["obs"].copy()
    obs.loc[obs.index[:5], "water_clarity"] = np.nan
    obs.loc[obs.index[:5], "smell"] = None
    inp = data_prep.build_inputs(obs, toy["weather"], toy["sites"])
    assert np.isnan(inp.clarity).sum() >= 5
    assert np.isnan(inp.sewage[:5]).all()
    # Sewage flag is 1/0 only where smell was reported.
    assert set(np.unique(inp.sewage[~np.isnan(inp.sewage)])) <= {0.0, 1.0}


def test_diversity_is_dropped_when_insects_reported_absent(toy):
    obs = toy["obs"].copy()
    obs["insect_presence"] = False
    obs["insect_diversity"] = 0.0
    inp = data_prep.build_inputs(obs, toy["weather"], toy["sites"])
    assert np.isnan(inp.diversity).all()


def test_build_inputs_rejects_ground_truth_columns(toy):
    leaky = toy["obs"].assign(W_true=50.0)
    with pytest.raises(ValueError, match="Ground-truth columns leaked"):
        data_prep.build_inputs(leaky, toy["weather"], toy["sites"])


def test_build_inputs_slicing(toy):
    inp = data_prep.build_inputs(toy["obs"], toy["weather"], toy["sites"], site_ids=["toy-1", "toy-2"], n_weeks=8)
    assert inp.site_ids == ["toy-1", "toy-2"]
    assert inp.n_weeks == 8
    assert inp.week_idx.max() < 8


def test_exposure_weights_distinguish_unavailable_from_far():
    df = pd.DataFrame(
        [
            {"site_id": "a", "category": "playground", "nearest_poi_distance_m": 0.0, "data_source": "real"},
            {"site_id": "a", "category": "school", "nearest_poi_distance_m": 250.0, "data_source": "real"},
            {"site_id": "a", "category": "park", "nearest_poi_distance_m": np.nan, "data_source": "real"},
            {"site_id": "b", "category": "playground", "nearest_poi_distance_m": np.nan, "data_source": "unavailable"},
            {"site_id": "b", "category": "school", "nearest_poi_distance_m": np.nan, "data_source": "unavailable"},
        ]
    )
    w = data_prep.compute_exposure_weights(df).set_index("site_id")
    assert w.loc["a", "exposure_weight"] == pytest.approx(1.0 + 0.7 * np.exp(-1))
    assert np.isnan(w.loc["b", "exposure_weight"])  # unknown, never 0
    assert w.loc["b", "data_source"] == "unavailable"


def _score_row(**overrides):
    row = {"site_id": "a", "week_start": "2025-01-06", "e_mean": 0.1, "n_reports": 1, "n_informative_fields": 2,
           "evidence": "weak", "mixing_flag": False, "model_variant": "M1"}
    for name in ("W", "H"):
        row.update({f"{name}_mean": 50.0, f"{name}_sd": 5.0, f"{name}_q05": 40.0, f"{name}_q25": 46.0,
                    f"{name}_q50": 50.0, f"{name}_q75": 54.0, f"{name}_q95": 60.0})
    return {**row, **overrides}


def test_model_score_schema_accepts_valid_and_rejects_bad_quantiles():
    from datetime import date

    schema.ModelScore(**_score_row(week_start=date(2025, 1, 6)))
    with pytest.raises(Exception, match="not monotone"):
        schema.ModelScore(**_score_row(week_start=date(2025, 1, 6), W_q25=70.0))
    with pytest.raises(Exception):
        schema.ModelScore(**_score_row(week_start=date(2025, 1, 6), W_mean=120.0))


def test_evidence_flag_rules():
    assert bm.evidence_flag(0, 5.0) == "insufficient"
    assert bm.evidence_flag(1, 5.0) == "weak"
    assert bm.evidence_flag(3, 10.0) == "sufficient"
    assert bm.evidence_flag(3, 60.0) == "weak"  # informative but wide


def test_variant_paths_keep_primary_canonical():
    p = Path("x/model_scores.parquet")
    assert bm.variant_path(p, "M1") == p
    assert bm.variant_path(p, "M1_norain").name == "model_scores__M1_norain.parquet"


def test_convergence_gate_raises_and_names_the_failure():
    bad = {"passed": False, "failures": ["max R-hat 1.150 > 1.01", "3 divergent transitions"]}
    with pytest.raises(diagnostics.ModelConvergenceError, match="R-hat.*divergent"):
        diagnostics.assert_converged(bad)
    diagnostics.assert_converged({"passed": True, "failures": []})


def test_interval_coverage_helper():
    truth = np.array([1.0, 2.0, 3.0, 4.0])
    assert diagnostics.interval_coverage(truth, truth - 0.5, truth + 0.5) == 1.0
    assert diagnostics.interval_coverage(truth, truth + 0.5, truth + 1.0) == 0.0


def test_unknown_variant_rejected(toy):
    inp = data_prep.build_inputs(toy["obs"], toy["weather"], toy["sites"])
    with pytest.raises(ValueError, match="variant"):
        bm.build_model(inp, "M9")


def test_prior_is_wide_not_degenerate(toy):
    """Prior draws of W/H must span a plausible range, else the prior dominates the data."""
    import pymc as pm

    inp = data_prep.build_inputs(toy["obs"], toy["weather"], toy["sites"])
    model = bm.build_model(inp, "M1")
    with model:
        prior = pm.sample_prior_predictive(draws=200, var_names=["W", "H"], random_seed=0)
    for name in ("W", "H"):
        vals = prior.prior[name].to_numpy()
        assert vals.min() >= 0 and vals.max() <= 100
        lo, hi = np.quantile(vals, [0.05, 0.95])
        assert hi - lo > 30, f"{name} prior 90% range only {hi - lo:.1f} wide"


# ----------------------------------------------------------------------------- slow: real sampling


@pytest.fixture(scope="module")
def toy_fit(toy):
    inp = data_prep.build_inputs(toy["obs"], toy["weather"], toy["sites"])
    result = bm.run_variant(inp, "M1", TINY, strict=False, write=False)
    return inp, result


@pytest.mark.slow
def test_fit_outputs_are_valid_scores(toy_fit):
    inp, result = toy_fit
    scores = result["scores"]
    schema.validate_dataframe(scores, schema.ModelScore, name="toy_scores")
    assert len(scores) == N_SITES * N_WEEKS
    assert scores[["W_mean", "H_mean"]].notna().all().all()
    assert result["diagnostics"]["divergences"] <= 5  # tiny run; the real gate is stricter


@pytest.mark.slow
def test_thin_draws_carries_what_stage6_needs(toy_fit):
    inp, result = toy_fit
    draws = bm.thin_draws(result["idata"], inp, n=100)
    for name in ("W", "H", "e"):
        assert draws[name].dims == ("sample", "site", "week")
    for name in ("lam_H", "beta_rain", "beta_ante"):
        assert draws[name].dims == ("sample",)
    assert draws.sizes["sample"] == 100


@pytest.mark.slow
def test_unobserved_weeks_have_wider_intervals(toy_fit):
    _, result = toy_fit
    s = result["scores"].assign(width=lambda d: d["W_q95"] - d["W_q05"])
    # Same site (toy-2), same fitted model: reported weeks vs the planted no-report window.
    site = s[s["site_id"] == "toy-2"]
    unobserved = site[site["n_reports"] == 0]["width"].mean()
    observed = site[site["n_reports"] > 0]["width"].mean()
    assert unobserved > observed
    assert (site[site["n_reports"] == 0]["evidence"] == "insufficient").all()


@pytest.mark.slow
def test_planted_event_is_recovered(toy_fit):
    inp, result = toy_fit
    s = result["scores"].set_index(["site_id", "week_start"])
    weeks = inp.weeks
    event_w = np.mean([s.loc[(f"toy-{EVENT_SITE}", weeks[t]), "W_mean"] for t in EVENT_WEEKS])
    quiet_w = np.mean([s.loc[(f"toy-{EVENT_SITE}", weeks[t]), "W_mean"] for t in (2, 3, 4, 15, 16)])
    assert quiet_w - event_w > 15, (quiet_w, event_w)
    event_h = np.mean([s.loc[(f"toy-{EVENT_SITE}", weeks[t]), "H_mean"] for t in EVENT_WEEKS])
    quiet_h = np.mean([s.loc[(f"toy-{EVENT_SITE}", weeks[t]), "H_mean"] for t in (2, 3, 4, 15, 16)])
    assert event_h - quiet_h > 10, (event_h, quiet_h)


@pytest.mark.slow
def test_posterior_mean_tracks_report_signal(toy_fit):
    inp, result = toy_fit
    s = result["scores"].set_index(["site_id", "week_start"])
    rows = [(s.loc[(inp.site_ids[si], inp.weeks[wi]), "W_mean"], c)
            for si, wi, c in zip(inp.site_idx, inp.week_idx, inp.clarity) if not np.isnan(c)]
    w, clarity = np.array(rows).T
    assert np.corrcoef(w, clarity)[0, 1] < -0.5  # cleaner posterior <-> lower (clearer) rubric value


@pytest.mark.slow
def test_single_absurd_report_does_not_create_a_false_event(toy_with_outlier):
    inp = data_prep.build_inputs(toy_with_outlier["obs"], toy_with_outlier["weather"], toy_with_outlier["sites"])
    result = bm.run_variant(inp, "M1", TINY, strict=False, write=False)
    s = result["scores"].set_index(["site_id", "week_start"])
    w = s.loc[(f"toy-{OUTLIER_SITE}", inp.weeks[OUTLIER_WEEK]), "W_mean"]
    assert w > 60, f"one junk report dragged W to {w:.1f}"
    assert result["params"].set_index("param").loc["eps_misreport", "mean"] > 0.0


@pytest.mark.slow
def test_gate_blocks_score_output_when_not_converged(toy, tmp_path, monkeypatch):
    """A failing gate must leave diagnostics on disk but write no scores/draws."""
    from pipeline.common import config

    for name in ("MODEL_SCORES_PATH", "MODEL_DRAWS_PATH", "MODEL_PARAMS_PATH", "MODEL_DIAG_PATH"):
        monkeypatch.setattr(config, name, tmp_path / getattr(config, name).name)
    inp = data_prep.build_inputs(toy["obs"], toy["weather"], toy["sites"])
    starved = bm.SamplerSettings(draws=20, tune=20, chains=2, seed=1)  # far too short to pass
    with pytest.raises(diagnostics.ModelConvergenceError):
        bm.run_variant(inp, "M1", starved, strict=True, write=True)
    assert (tmp_path / "model_diagnostics.json").exists()
    assert not (tmp_path / "model_scores.parquet").exists()
    assert not (tmp_path / "model_draws.nc").exists()
