"""Benchmark tests: scoring helpers, truth reconstruction and event matching on hand-built
worlds (answers worked out by hand), plus a smoke run on the committed pipeline outputs."""

from __future__ import annotations

import json
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from pipeline.benchmark import metrics
from pipeline.benchmark.truth import build_truth
from pipeline.common import config

WEEKS = [date(2025, 1, 6) + timedelta(weeks=i) for i in range(5)]
SITES = pd.DataFrame({"site_id": ["a", "b", "c"], "distance_from_mouth_m": [2400.0, 1200.0, 0.0]})


# ----------------------------------------------------------------------------- metrics


def test_confusion_counts_and_rates():
    m = metrics.confusion(np.array([1, 1, 0, 0, 1]), np.array([1, 0, 1, 0, 1]))
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (2, 1, 1, 1)
    assert m["precision"] == pytest.approx(2 / 3)
    assert m["recall"] == pytest.approx(2 / 3)
    assert m["f1"] == pytest.approx(2 / 3)
    assert m["false_positive_rate"] == pytest.approx(0.5)


def test_confusion_undefined_rates_are_none():
    m = metrics.confusion(np.zeros(3), np.zeros(3))
    assert m["precision"] is None and m["recall"] is None and m["f1"] is None


def test_auc_and_average_precision_by_hand():
    scores, labels = np.array([0.1, 0.4, 0.35, 0.8]), np.array([0, 0, 1, 1])
    # Pairs (pos, neg): (0.35,0.1) win, (0.35,0.4) loss, (0.8,*) 2 wins -> 3/4.
    assert metrics.roc_auc(scores, labels) == pytest.approx(0.75)
    # Ranked: 0.8 (hit, P=1), 0.4, 0.35 (hit, P=2/3), 0.1 -> (1 + 2/3) / 2.
    assert metrics.average_precision(scores, labels) == pytest.approx((1 + 2 / 3) / 2)
    assert metrics.roc_auc(scores, np.zeros(4)) is None


def test_score_errors_coverage():
    e = metrics.score_errors(np.array([50, 60]), np.array([40, 65]), np.array([60, 70]), np.array([55, 61]))
    assert e["mae"] == pytest.approx(3.0)
    assert e["coverage_90"] == pytest.approx(0.5)  # 61 is outside [65, 70]


# ----------------------------------------------------------------------------- truth


def _world(event_rows):
    """Ground truth consistent with `event_rows` (the stored active flags must match the rules)."""
    events = pd.DataFrame(event_rows)
    truth_probe = build_truth(  # build once with flags left empty, then store its own active cells
        _gt(np.zeros((3, len(WEEKS)), bool)), events, SITES, check=False)
    return _gt(truth_probe.drop > 0), events


def _gt(active):
    return pd.DataFrame([
        {"site_id": s, "week_start": w, "W_true": 80.0, "H_true": 15.0,
         "contamination_event_active": bool(active[i, t]), "event_id": None}
        for i, s in enumerate(SITES["site_id"]) for t, w in enumerate(WEEKS)
    ])


EVENT_A = {"event_id": "evA" + "0" * 29, "source_site_id": "a", "start_week": WEEKS[0], "end_week": WEEKS[0],
           "event_type": "sewage_overflow", "rain_triggered": True, "peak_magnitude": 50.0,
           "affected_site_ids": ["a", "b", "c"]}


def test_truth_applies_decay_and_lag():
    gt, events = _world([EVENT_A])
    t = build_truth(gt, events, SITES)
    assert t.drop[0, 0] == pytest.approx(50.0)  # at the source, same week
    assert t.drop[1, 1] == pytest.approx(50 * np.exp(-1))  # 1200 m on: e^-1, one week later
    assert t.drop[2, 2] == pytest.approx(50 * np.exp(-2))  # 2400 m on: e^-2, round(1.6) = 2 weeks
    assert t.changed(10).sum() == 2  # the 6.8-point ripple at c is below the threshold


def test_truth_rejects_a_mismatched_simulator():
    gt, events = _world([EVENT_A])
    gt.loc[0, "contamination_event_active"] = False
    with pytest.raises(ValueError, match="simulator"):
        build_truth(gt, events, SITES)


# ----------------------------------------------------------------------------- event matching


def _incident(iid, sites, start, end, level="confirmed", top="a", probs=None):
    return {"incident_id": iid, "start_week": WEEKS[start], "end_week": WEEKS[end], "affected_site_ids": sites,
            "max_alert_level": level, "top_source": top, "top_source_prob": 0.7,
            "source_probs_json": json.dumps(probs or {top: 0.7}), "credible_set": [top],
            "upstream_unobserved": False}


def test_event_detection_finds_hits_misses_and_false_alarms():
    from pipeline.benchmark.benchmark import event_detection

    event_b = {**EVENT_A, "event_id": "evB" + "0" * 29, "source_site_id": "c", "start_week": WEEKS[4],
               "end_week": WEEKS[4], "affected_site_ids": ["c"], "rain_triggered": False}
    gt, events = _world([EVENT_A, event_b])
    t = build_truth(gt, events, SITES)
    incidents = pd.DataFrame([
        _incident("inc-1", ["a", "b"], 0, 1),  # matches event A
        _incident("inc-2", ["c"], 2, 2, level="possible", top="c"),  # only A's 6.8-point ripple there
    ])
    alerts = pd.DataFrame([{"site_id": s, "week_start": w, "p_change": 0.1}
                           for s in SITES["site_id"] for w in WEEKS])
    n_reports = np.zeros((3, len(WEEKS)), int)
    n_reports[0, 0] = 2

    r = event_detection(t, incidents, alerts, n_reports)
    by_id = {e["event_id"]: e for e in r["events"]}
    assert by_id["evA00000"]["outcome"] == "detected"
    assert by_id["evA00000"]["source_correct"] is True
    assert by_id["evB00000"]["outcome"] == "missed"
    assert "no citizen reports" in by_id["evB00000"]["miss_reason"]
    assert [f["incident_id"] for f in r["false_alarms"]] == ["inc-2"]
    assert "small change" in r["false_alarms"][0]["what_really_happened"]
    assert r["event_recall"] == pytest.approx(0.5)
    assert r["incident_precision"] == pytest.approx(0.5)


# ----------------------------------------------------------------------------- committed data


@pytest.mark.skipif(not config.GROUND_TRUTH_EVENTS_PATH.exists() or not config.DETECTOR_RAIN_PATH.exists(),
                    reason="pipeline outputs not built")
def test_report_on_committed_outputs():
    from pipeline.benchmark.benchmark import build_report, render_markdown

    r = build_report()
    n_events = len(pd.read_parquet(config.GROUND_TRUTH_EVENTS_PATH))
    assert r["headline"]["n_true_events"] == n_events == len(r["events"]["events"])
    assert {e["outcome"] for e in r["events"]["events"]} <= {"detected", "detected (possible only)", "missed"}
    assert r["events"]["n_false_alarms"] == len(r["events"]["false_alarms"])
    assert 0 <= r["headline"]["W_coverage_90"] <= 1
    json.dumps(r)  # plain JSON all the way down
    assert "Every true event" in render_markdown(r)
