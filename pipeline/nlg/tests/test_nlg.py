"""Stage 7 tests on a small hand-made world (no model, no network)."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from pipeline.common import config, schema
from pipeline.nlg import factlock, facts, render, summarize

WEEKS = [date(2025, 1, 6) + timedelta(weeks=i) for i in range(6)]
SITES = ["s1", "s2", "s3"]  # head -> mouth


def _sites():
    return pd.DataFrame({
        "site_id": SITES,
        "name": ["Head St", "Mid St", "Mouth St"],
        "distance_from_mouth_m": [600.0, 300.0, 0.0],
        "is_cso_outfall_adjacent": [True, False, False],
    })


def _edges():
    return pd.DataFrame({"from_site_id": ["s1", "s2"], "to_site_id": ["s2", "s3"], "distance_m": [300.0, 300.0]})


def _exposure():
    rows = [
        ("s1", "playground", 100.0, "unnamed", True, "real"),
        ("s1", "school", 300.0, "P.S. 7", False, "real"),
        ("s1", "park", 50.0, "Big Park", True, "real"),
        ("s2", "playground", 400.0, "unnamed", False, "real"),
        ("s2", "school", 500.0, "Far School", False, "real"),
        ("s2", "park", 450.0, "Far Park", False, "real"),
    ] + [("s3", c, None, None, False, "unavailable") for c in ("playground", "school", "park")]
    return pd.DataFrame(rows, columns=["site_id", "category", "nearest_poi_distance_m", "nearest_poi_name",
                                       "is_exposure_relevant", "data_source"])


def _scores():
    rows = []
    for s in SITES:
        for i, w in enumerate(WEEKS):
            insufficient = s == "s2" and i >= 4  # s2: no reports in the last two weeks
            rows.append({
                "site_id": s, "week_start": w,
                "W_q05": 70.0, "W_q50": 80.0, "W_q95": 88.0, "H_q05": 12.0, "H_q50": 18.0, "H_q95": 26.0,
                "n_reports": 0 if insufficient else 2, "evidence": "insufficient" if insufficient else "sufficient",
                "mixing_flag": False, "model_variant": "M1",
            })
    return pd.DataFrame(rows)


def _alerts(incident_rows=(("s1", 2), ("s2", 3))):
    rows = []
    for s in SITES:
        for i, w in enumerate(WEEKS):
            hit = (s, i) in incident_rows
            rows.append({"site_id": s, "week_start": w, "p_change": 0.97 if hit else 0.02,
                         "rise_H_median": 35.0 if hit else 0.1, "alert_level": "confirmed" if hit else "none",
                         "mixing_flag": False, "n_reports": 2})
    return pd.DataFrame(rows)


def _incident(**overrides):
    base = {
        "incident_id": "inc-001", "start_week": WEEKS[2], "end_week": WEEKS[3], "affected_site_ids": ["s1", "s2"],
        "n_episodes": 2, "max_alert_level": "confirmed", "top_source": "s1", "top_source_prob": 0.95,
        "p_no_source": 0.0, "credible_set": ["s1"], "source_probs_json": "{}", "entry_segment": "",
        "upstream_unobserved": False, "decays_downstream": True, "rain_week": True, "peak_drop_W": 40.0,
        "model_variant": "M1",
    }
    return {**base, **overrides}


def _rain(verdict="supported", cso="supported", other="inconclusive"):
    stats = {"irr_median": 2.26, "irr_q05": 1.69, "irr_q95": 3.26, "p_irr_gt_1": 1.0, "placebo_p": 0.01}
    return {
        "model_variant": "M1_norain", "verdict": verdict, "pooled": {**stats, "verdict": verdict},
        "cso_adjacent": {**stats, "verdict": cso}, "other_sites": {**stats, "verdict": other},
        "sewage_smell_share": {"rain_weeks": 0.11, "dry_weeks": 0.034, "n_reports_rain": 200, "n_reports_dry": 300},
        "corroboration_beta_rain": {"median": 0.68},
    }


def _inputs(incidents=None, alerts=None, rain=None, exposure=None):
    incidents = pd.DataFrame([_incident()] if incidents is None else incidents)
    return facts.build_inputs(_sites(), _edges(), _exposure() if exposure is None else exposure, _scores(),
                              _alerts() if alerts is None else alerts, incidents, _rain() if rain is None else rain)


def _incident_finding(**overrides) -> dict:
    inp = _inputs(incidents=[_incident(**overrides)])
    return render.render_incident(inp, inp.incidents.iloc[0])


def _text(f: dict) -> str:
    return " ".join([f["headline"], f["body"], f.get("precaution") or "", *f["caveats"]])


# ----------------------------------------------------------------------------- whole-stage properties


def test_all_findings_validate_and_are_fact_locked():
    df = summarize.build_findings(_inputs())
    schema.validate_dataframe(df, schema.Finding, name="findings")
    assert df["finding_type"].value_counts().to_dict() == {"site_status": 3, "incident": 1, "rain_pattern": 1, "coverage": 1}
    for _, f in df.iterrows():
        shown = [v["shown"] for v in json.loads(f["facts_json"]).values()]
        precaution = f["precaution"] if isinstance(f["precaution"], str) else ""  # pandas stores None as NaN
        for part in (f["headline"], f["body"], precaution, *f["caveats"]):
            factlock.check(part, shown)  # re-check from the stored facts alone
    assert df.iloc[0]["finding_type"] == "incident"  # highest priority first


def test_deterministic():
    pd.testing.assert_frame_equal(summarize.build_findings(_inputs()), summarize.build_findings(_inputs()))


def test_no_banned_words_in_committed_findings():
    if not config.FINDINGS_PATH.exists():
        pytest.skip("run Stage 7 first")
    df = pd.read_parquet(config.FINDINGS_PATH)
    pattern = re.compile(r"\b(" + "|".join(factlock.BANNED_WORDS) + r")\b", re.I)
    for col in ("headline", "body", "precaution"):
        assert not df[col].dropna().str.contains(pattern).any()


# ----------------------------------------------------------------------------- fact-lock


def test_factlock_rejects_ungrounded_number_banned_word_and_placeholder():
    factlock.check("fell by about 40 points", ["40"])
    with pytest.raises(factlock.FactLockError, match="not backed"):
        factlock.check("fell by about 42 points", ["40"])
    with pytest.raises(factlock.FactLockError, match="banned"):
        factlock.check("The water is safe", [])
    with pytest.raises(factlock.FactLockError, match="placeholder"):
        factlock.check("At {site}", [])


def test_numbers_inside_names_are_allowed_because_names_are_facts():
    f = _incident_finding()
    assert "P.S. 7" not in f["body"]  # the school is 300 m away: outside the radius, not mentioned
    factlock.check("Near 6th/7th St", ["6th/7th St"])


# ----------------------------------------------------------------------------- exposure


def test_exposure_lines_order_children_first_and_handle_unnamed():
    body = _incident_finding()["body"]
    assert body.index("a playground") < body.index("Big Park (park)")
    assert "(playground)" not in body  # unnamed places are not labelled twice


def test_unavailable_exposure_says_could_not_check_never_none():
    f = _incident_finding(affected_site_ids=["s3"], top_source="s3", credible_set=["s3"])
    assert "could not check" in f["body"]
    assert "No playgrounds" not in f["body"]
    inp = _inputs()
    status = render.render_site_status(inp, "s3", {})
    assert "could not check" in status["body"]


def test_checked_and_nothing_nearby_says_none_within_radius():
    f = _incident_finding(affected_site_ids=["s2"], top_source="s2", credible_set=["s2"])
    assert "No playgrounds, schools or parks were found within 250 m" in f["body"]


# ----------------------------------------------------------------------------- rain wording


@pytest.mark.parametrize(
    "top, cso_verdict, rain_week, expected",
    [
        ("s1", "supported", True, "consistent with a combined sewer overflow"),
        ("s2", "supported", True, "It followed a week of heavy rain."),  # source not CSO-adjacent
        ("s1", "inconclusive", True, "It followed a week of heavy rain."),  # CSO pattern not supported
        ("s1", "supported", False, None),  # no rain that week
    ],
)
def test_cso_attribution_needs_all_three_conditions(top, cso_verdict, rain_week, expected):
    inp = _inputs(incidents=[_incident(top_source=top, rain_week=rain_week, credible_set=[top])],
                  rain=_rain(cso=cso_verdict))
    body = render.render_incident(inp, inp.incidents.iloc[0])["body"]
    if expected is None:
        assert "heavy rain" not in body
    else:
        assert expected in body
    if expected != "consistent with a combined sewer overflow":
        assert "sewer overflow" not in body


def test_rain_supported_text_and_inconclusive_makes_no_claim():
    supported = render.render_rain(_inputs())
    assert "2.3 times as common" in supported["body"] and "Head St" in supported["body"]
    assert "(11% vs 3%)" in supported["body"]
    assert supported["caveats"] == ["This is an association in the data, not proof of cause."]
    assert "0.68" not in _text(supported)  # model-assisted corroboration stays out of the text

    inconclusive = render.render_rain(_inputs(rain=_rain(verdict="inconclusive")))
    assert "times as common" not in inconclusive["body"]
    assert "not strong enough" in inconclusive["body"]


# ----------------------------------------------------------------------------- uncertainty wording


@pytest.mark.parametrize("p, key", [(0.9, "very_likely"), (0.8999, "likely"), (0.66, "likely"),
                                    (0.33, "possibly"), (0.3299, "unlikely")])
def test_verbal_probability_scale(p, key):
    assert render.verbal_key(p) == key


def test_entry_point_wording():
    body = _incident_finding(top_source="s2", top_source_prob=0.5, credible_set=["s2", "s1"], upstream_unobserved=True)["body"]
    assert "possibly entered between Head St and Mid St" in body
    assert "It could also have entered near Head St." in body
    assert "may have entered further up the canal" in body
    unclear = _incident_finding(top_source_prob=0.2)["body"]
    assert "could not pin down where it entered" in unclear
    head = _incident_finding()["body"]
    assert "very likely entered at or above Head St" in head


def test_possible_incident_is_never_called_very_likely():
    f = _incident_finding(max_alert_level="possible")
    assert f["confidence_label"] == "likely"
    assert "very likely dropped" not in f["headline"]


def test_headline_fits_with_many_sites():
    f = _incident_finding(affected_site_ids=["s1", "s2", "s3"])
    assert "Head St and 2 nearby sites" in f["headline"] and len(f["headline"]) <= 120


# ----------------------------------------------------------------------------- priority & precaution


@pytest.mark.parametrize(
    "level, exposure_state, priority, precaution",
    [
        ("confirmed", "relevant", "high", True),
        ("confirmed", "unknown", "medium", True),
        ("confirmed", "none", "medium", False),
        ("possible", "relevant", "medium", False),
        ("possible", "none", "low", False),
    ],
)
def test_priority_and_precaution_rules(level, exposure_state, priority, precaution):
    assert render.incident_priority(level, exposure_state) == priority
    assert render.needs_precaution(level, exposure_state) is precaution


def test_precaution_text_on_confirmed_incident_near_playground():
    f = _incident_finding()
    assert f["priority"] == "high"
    assert "especially children and dogs" in f["precaution"]


# ----------------------------------------------------------------------------- site status


def test_insufficient_evidence_site_shows_no_score_and_last_report_age():
    f = render.render_site_status(_inputs(), "s2", {})
    assert f["headline"] == "Mid St: not enough recent reports to say"
    assert "The last report here was 2 weeks before" in f["body"]
    assert f["confidence_label"] == "insufficient evidence"


def test_site_status_with_evidence_and_recent_incident_pointer():
    f = render.render_site_status(_inputs(), "s1", {"s1": "inc-001"})
    assert f["headline"] == "Head St: water quality index 80 (likely 70 to 88), typical for this site"
    assert "inc-001" in f["body"]
    assert "Within 250 m: a playground and Big Park (park)." in f["body"]


def test_coverage_includes_disclaimer_and_least_covered_site():
    f = render.render_coverage(_inputs())
    assert "not an official health advisory" in f["body"]
    assert "Mid St had reports in 4 of 6 weeks" in f["body"]
