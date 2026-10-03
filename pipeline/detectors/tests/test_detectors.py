"""Stage 6 tests on synthetic posterior draws (no sampling, fast)."""

from __future__ import annotations

import json
from datetime import date, timedelta

import networkx as nx
import numpy as np
import pandas as pd
import pytest

from pipeline.common import config, schema
from pipeline.detectors import change, rain, source
from pipeline.detectors.draws import PosteriorDraws, excursion_effects

N, S, T = 400, 5, 30
SITES = [f"s{i}" for i in range(S)]  # s0 = head ... s4 = mouth
WEEKS = [date(2025, 1, 6) + timedelta(weeks=i) for i in range(T)]


def _chain_graph() -> nx.DiGraph:
    g = nx.DiGraph()
    g.add_nodes_from(SITES)
    g.add_edges_from(zip(SITES, SITES[1:]))
    return g


def _draws(e: np.ndarray, *, W_level: float = 80.0, lam_H=1.0, beta_rain=None, variant="M1") -> PosteriorDraws:
    """Builds draws whose W/H are exactly 'baseline pushed by e' (the M1 structure)."""
    rng = np.random.default_rng(0)
    z_w = np.log(W_level / (100 - W_level)) + rng.normal(0, 0.05, (N, S, T)) - e
    z_h = np.log(20 / 80) + rng.normal(0, 0.05, (N, S, T)) + lam_H * e
    return PosteriorDraws(
        variant=variant, site_ids=SITES, weeks=WEEKS,
        W=100 / (1 + np.exp(-z_w)), H=100 / (1 + np.exp(-z_h)), e=e,
        lam_H=np.full(N, lam_H), beta_rain=beta_rain, beta_ante=None,
    )


def _scores(n_reports=None, mixing=None, evidence=None) -> pd.DataFrame:
    n_reports = np.ones((S, T), int) if n_reports is None else n_reports
    rows = []
    for s, site in enumerate(SITES):
        for t, week in enumerate(WEEKS):
            rows.append({
                "site_id": site, "week_start": week, "n_reports": int(n_reports[s, t]),
                "mixing_flag": bool(mixing[s, t]) if mixing is not None else False,
                "evidence": evidence[s][t] if evidence is not None else ("weak" if n_reports[s, t] else "insufficient"),
            })
    return pd.DataFrame(rows)


def _quiet_e() -> np.ndarray:
    return np.abs(np.random.default_rng(1).normal(0, 0.02, (N, S, T)))


# ----------------------------------------------------------------------------- counterfactual maths


def test_zero_excursion_means_zero_drop():
    d = _draws(np.zeros((N, S, T)))
    drop, rise = excursion_effects(d)
    assert np.allclose(drop, 0, atol=1e-6) and np.allclose(rise, 0, atol=1e-6)


def test_known_excursion_gives_expected_drop():
    e = np.zeros((N, S, T))
    e[:, 1, 5] = 2.0
    d = _draws(e, W_level=80.0)
    drop, rise = excursion_effects(d)
    expected = 80.0 - 100 / (1 + np.exp(-(np.log(80 / 20) - 2.0)))  # ~44.9 points
    assert np.median(drop[:, 1, 5]) == pytest.approx(expected, abs=1.0)
    assert np.median(rise[:, 1, 5]) > 20
    assert np.allclose(drop[:, 0, :], 0, atol=1e-6)


def test_m0_fallback_uses_rolling_baseline():
    d = _draws(np.zeros((N, S, T)))
    d = PosteriorDraws(**{**d.__dict__, "e": None, "lam_H": None, "variant": "M0"})
    W = d.W.copy()
    W[:, 2, 20] -= 30
    d = PosteriorDraws(**{**d.__dict__, "W": W})
    drop, _ = excursion_effects(d)
    assert np.median(drop[:, 2, 20]) == pytest.approx(30, abs=2)


# ----------------------------------------------------------------------------- D1


def test_planted_drop_is_confirmed_and_noise_is_not():
    e = _quiet_e()
    e[:, 2, 10] = 2.0
    alerts = change.detect_changes(_draws(e), _scores())
    schema.validate_dataframe(alerts, schema.DetectorAlert, name="alerts")
    hit = alerts[(alerts.site_id == "s2") & (alerts.week_start == WEEKS[10])].iloc[0]
    assert hit.alert_level == "confirmed" and hit.p_change > 0.99
    assert (alerts.alert_level != "none").sum() == 1
    assert len(alerts) == S * T


def test_mixing_flag_and_no_reports_cap_at_possible():
    e = _quiet_e()
    e[:, 1, 3] = 2.0
    e[:, 3, 7] = 2.0
    mixing = np.zeros((S, T), bool)
    mixing[1, 3] = True
    n_reports = np.ones((S, T), int)
    n_reports[3, 7] = 0
    alerts = change.detect_changes(_draws(e), _scores(n_reports=n_reports, mixing=mixing)).set_index(["site_id", "week_start"])
    assert alerts.loc[("s1", WEEKS[3]), "alert_level"] == "possible"
    assert alerts.loc[("s3", WEEKS[7]), "alert_level"] == "possible"


def test_alert_level_rules():
    assert change.alert_level(0.95, False, "weak") == "confirmed"
    assert change.alert_level(0.95, True, "sufficient") == "possible"
    assert change.alert_level(0.6, False, "sufficient") == "possible"
    assert change.alert_level(0.2, False, "sufficient") == "none"


def test_consecutive_weeks_form_one_episode():
    e = _quiet_e()
    e[:, 0, 4:7] = 2.0
    e[:, 0, 12] = 2.0
    alerts = change.detect_changes(_draws(e), _scores())
    eps = alerts[alerts.site_id == "s0"].dropna(subset=["episode_id"])
    assert eps.groupby("episode_id").size().sort_values().tolist() == [1, 3]


def test_sensitivity_table_normal_level_matches_main_alerts():
    e = _quiet_e()
    e[:, 2, 10] = 2.0
    e[:, 1, 4] = 0.5  # a ~9-point drop: counts at "sensitive" (5), not at "normal" (10)
    d, scores = _draws(e), _scores()
    sens = change.sensitivity_table(d, scores)
    schema.validate_dataframe(sens, schema.AlertSensitivity, name="sensitivity")
    assert set(sens["sensitivity"]) == set(config.SENSITIVITY_DELTAS)
    assert len(sens) == len(config.SENSITIVITY_DELTAS) * S * T
    normal = sens[sens.sensitivity == "normal"].reset_index(drop=True)
    main = change.detect_changes(d, scores)
    assert np.allclose(normal["p_change"], main["p_change"])
    assert (normal["alert_level"] == main["alert_level"]).all()


def test_larger_change_size_never_raises_probability():
    e = _quiet_e()
    e[:, 1, 4] = 0.5
    e[:, 2, 10] = 2.0
    wide = change.sensitivity_table(_draws(e), _scores()).pivot_table(
        index=["site_id", "week_start"], columns="sensitivity", values="p_change")
    assert (wide["sensitive"] >= wide["normal"]).all() and (wide["normal"] >= wide["strict"]).all()
    assert (wide["sensitive"] > wide["normal"]).any()  # the borderline drop only shows at "sensitive"


def test_committed_rain_toggle_outputs_are_valid():
    from pipeline.model.bayesian_model import variant_path

    paths = [variant_path(config.DETECTOR_ALERTS_PATH, "M1_norain"), variant_path(config.DETECTOR_INCIDENTS_PATH, "M1_norain"),
             config.DETECTOR_SENSITIVITY_PATH]
    if not all(p.exists() for p in paths):
        pytest.skip("run Stage 6 first")
    alerts, incidents, sens = (pd.read_parquet(p) for p in paths)
    schema.validate_dataframe(alerts, schema.DetectorAlert, name="alerts_norain")
    schema.validate_dataframe(incidents, schema.Incident, name="incidents_norain")
    assert set(alerts["model_variant"]) == {"M1_norain"} and set(incidents["model_variant"]) <= {"M1_norain"}
    assert set(sens["model_variant"]) == {"M1", "M1_norain"}


# ----------------------------------------------------------------------------- D2


def _incident_e(source_idx: int, t: int, peak: float = 2.5) -> np.ndarray:
    """An incident entering at `source_idx`, decaying downstream (like the simulator's physics)."""
    e = _quiet_e()
    for s in range(source_idx, S):
        e[:, s, t] = peak * np.exp(-(s - source_idx) * 0.3)
    return e


def test_source_is_the_most_upstream_affected_site():
    e = _incident_e(source_idx=2, t=12)
    d = _draws(e)
    alerts = change.detect_changes(d, _scores())
    inc = source.localise_incidents(d, alerts, _chain_graph(), np.zeros(T))
    schema.validate_dataframe(inc, schema.Incident, name="incidents")
    assert len(inc) == 1
    row = inc.iloc[0]
    assert row.top_source == "s2" and row.top_source_prob > 0.9
    assert row.affected_site_ids == ["s2", "s3", "s4"]
    assert row.entry_segment == "between s1 and s2"
    assert bool(row.decays_downstream) is True and bool(row.upstream_unobserved) is False
    assert set(json.loads(row.source_probs_json)) <= {"s0", "s1", "s2"}


def test_uncertain_upstream_spreads_probability_and_flags_unobserved():
    e = _incident_e(source_idx=2, t=12)
    # Upstream neighbour s1 is unobserved: its excursion posterior is wide (sometimes large).
    e[:, 1, 12] = np.random.default_rng(5).exponential(0.8, N)
    n_reports = np.ones((S, T), int)
    n_reports[1, :] = 0
    d = _draws(e)
    alerts = change.detect_changes(d, _scores(n_reports=n_reports))
    row = source.localise_incidents(d, alerts, _chain_graph(), np.zeros(T)).iloc[0]
    probs = json.loads(row.source_probs_json)
    assert 0.05 < probs.get("s1", 0) < 0.95  # genuinely split between s1 and s2
    assert set(row.credible_set) >= {"s1", "s2"} or row.top_source_prob < 0.8
    assert bool(row.upstream_unobserved) is (row.top_source == "s2")


def test_far_apart_episodes_are_separate_incidents():
    e = _incident_e(source_idx=0, t=3)
    e[:, 3, 25] = 2.5
    d = _draws(e)
    inc = source.localise_incidents(d, change.detect_changes(d, _scores()), _chain_graph(), np.zeros(T))
    assert len(inc) == 2
    assert inc.iloc[0].entry_segment.startswith("at or above s0")


def test_isolated_noise_far_upstream_does_not_become_the_source():
    """Regression: a distant, unobserved upstream site with a wide posterior must not win just
    because it sometimes exceeds the threshold; the pulse has to be contiguous."""
    e = _quiet_e()
    e[:, 3, 12] = 2.5
    e[:, 4, 12] = 2.0
    rng = np.random.default_rng(9)
    e[:, 0, 10:15] = rng.exponential(0.6, (N, 5))  # head site: noisy, often "exceeds" somewhere
    d = _draws(e)
    row = source.localise_incidents(d, change.detect_changes(d, _scores()), _chain_graph(), np.zeros(T)).iloc[0]
    probs = json.loads(row.source_probs_json)
    assert row.top_source == "s3" and row.top_source_prob > 0.9
    assert probs.get("s0", 0) == 0


def test_same_week_episodes_far_apart_on_the_river_are_separate_incidents():
    e = _quiet_e()
    e[:, 0, 12] = 2.5
    e[:, 4, 12] = 2.5  # 4 hops away, nothing in between
    d = _draws(e)
    inc = source.localise_incidents(d, change.detect_changes(d, _scores()), _chain_graph(), np.zeros(T))
    assert len(inc) == 2


def test_credible_set():
    assert source.credible_set({"a": 0.5, "b": 0.3, "c": 0.2}, 0.8) == ["a", "b"]
    assert source.credible_set({"a": 0.0}, 0.8) == []


# ----------------------------------------------------------------------------- D3


def _rain_pattern(link: bool):
    rng = np.random.default_rng(7)
    heavy = np.zeros(T)
    heavy[[2, 7, 13, 19, 24, 28]] = 1
    exposed = rain.rain_exposure(heavy)
    e = _quiet_e()
    is_cso = np.array([True, True, False, False, False])
    for t in range(T):
        for s in range(S):
            p = (0.6 if exposed[t] else 0.03) if link else 0.1
            if rng.random() < p:
                e[:, s, t] = 2.0
    return _draws(e, variant="M1_norain"), heavy, is_cso


def test_rain_linked_events_are_supported():
    d, heavy, is_cso = _rain_pattern(link=True)
    res = rain.analyse_rain(d, heavy, np.ones((S, T), int), is_cso)
    assert res["pooled"]["irr_median"] > 3
    assert res["pooled"]["placebo_p"] < config.RAIN_PLACEBO_ALPHA
    assert res["verdict"] == "supported"
    assert res["model_variant"] == "M1_norain"


def test_rain_independent_events_are_not_supported():
    d, heavy, is_cso = _rain_pattern(link=False)
    res = rain.analyse_rain(d, heavy, np.ones((S, T), int), is_cso)
    assert res["verdict"] in {"inconclusive", "not supported"}
    assert res["pooled"]["placebo_p"] > config.RAIN_PLACEBO_ALPHA


def test_rain_insufficient_evidence_when_rain_weeks_unobserved():
    d, heavy, is_cso = _rain_pattern(link=True)
    n_reports = np.ones((S, T), int)
    n_reports[:, rain.rain_exposure(heavy)] = 0
    assert rain.analyse_rain(d, heavy, n_reports, is_cso)["verdict"] == "insufficient evidence"


def test_rain_exposure_lag():
    heavy = np.array([0, 1, 0, 0, 1, 0], float)
    assert rain.rain_exposure(heavy, lag=1).tolist() == [False, True, True, False, True, True]


def test_rain_reports_corroboration_and_model_free_share():
    d, heavy, is_cso = _rain_pattern(link=True)
    m1 = _draws(np.zeros((N, S, T)), beta_rain=np.random.default_rng(2).normal(0.7, 0.3, N))
    week_idx = np.array([2, 3, 10, 11])
    sewage = np.array([1.0, 1.0, 0.0, np.nan])
    res = rain.analyse_rain(d, heavy, np.ones((S, T), int), is_cso, sewage_by_report=(week_idx, sewage), corroborating=m1)
    assert res["corroboration_beta_rain"]["p_positive"] > 0.9
    assert res["sewage_smell_share"] == {"rain_weeks": 1.0, "dry_weeks": 0.0, "n_reports_rain": 2, "n_reports_dry": 1}
