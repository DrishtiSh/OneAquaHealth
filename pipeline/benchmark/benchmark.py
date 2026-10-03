"""Stage 11: Benchmark the whole pipeline against the simulator's known ground truth, reporting
real accuracy numbers (including misses), not just success stories.

This is the only stage allowed to read the hidden truth (data/raw/ground_truth). It reads the
Stage 5-6 outputs as they were written and scores them with the thresholds fixed up front in
common/config.py -- nothing here is tuned against the truth, and nothing here feeds back into
the model, detectors or findings.

Outputs: data/processed/benchmark_report.json (all numbers, every true event, every false alarm)
and benchmark_report.md (the same, readable). Stage 8 copies the JSON into the snapshot so the
API and dashboard can show it. A real-data run has no ground truth, so this stage then skips.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.benchmark import metrics
from pipeline.benchmark.truth import Truth, build_truth
from pipeline.common import config, io_utils
from pipeline.detectors.rain import _irr, rain_exposure
from pipeline.model import data_prep
from pipeline.model.bayesian_model import variant_path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

PRIMARY_VARIANT, RAIN_VARIANT = "M1", "M1_norain"
VARIANTS = (PRIMARY_VARIANT, RAIN_VARIANT)
MATCH_TOLERANCE_WEEKS = 1  # an incident may start/end a week off the true footprint and still match
# Naive baseline: flag a site-week straight from the raw reports, no model.
BASELINE_CLARITY = 4  # clarity >= 4 (murky end of the 1-5 rubric)
BASELINE_SMELLS = ("sewage", "chemical", "dead_fish")
BASELINE_SMELL_INTENSITY = 2

CAVEATS = [
    "Measured on simulated data with a known answer. Real-world accuracy is unknown until the "
    "pipeline is compared with lab samples or confirmed reports.",
    "A site-week counts as truly changed when the simulated event pulled W down by more than the "
    "detector's own threshold (10 points at normal sensitivity); smaller ripples far downstream "
    "are not counted as misses.",
    "True drops are recomputed from the events with the simulator's decay and travel-lag rules; "
    "overlapping events add up and the clip of W at 0 is ignored.",
    "Incidents are matched to true events when they share a site and their weeks overlap within "
    f"{MATCH_TOLERANCE_WEEKS} week.",
    "Thresholds were fixed before this comparison and were not tuned against it.",
]


# ----------------------------------------------------------------------------- loading


def _as_date(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s).dt.date


def _load_variant(path: Path, variant: str, **date_cols) -> pd.DataFrame:
    p = variant_path(path, variant, PRIMARY_VARIANT)
    if not p.exists():
        raise FileNotFoundError(f"{p} not found -- run Stages 5-6 first.")
    df = io_utils.read_parquet(p)
    for col in date_cols.get("dates", ("week_start",)):
        df[col] = _as_date(df[col])
    return df


def _grid(df: pd.DataFrame, value: str, truth: Truth, fill=np.nan) -> np.ndarray:
    """Long (site_id, week_start, value) -> (S, T) aligned to the truth grid."""
    s_idx = {s: i for i, s in enumerate(truth.site_ids)}
    t_idx = {w: i for i, w in enumerate(truth.weeks)}
    dtype = float if fill is np.nan else bool if isinstance(fill, bool) else object
    out = np.full((len(truth.site_ids), len(truth.weeks)), fill, dtype=dtype)
    for s, w, v in zip(df["site_id"], df["week_start"], df[value]):
        out[s_idx[s], t_idx[w]] = v
    return out


def _r(x, nd=3):
    return None if x is None else round(float(x), nd)


def _clean(obj):
    """Round floats and turn numpy scalars into plain Python, so the JSON is stable and small."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (np.floating, float)):
        return None if np.isnan(obj) else round(float(obj), 4)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    return obj


# ----------------------------------------------------------------------------- 1. scores


def score_accuracy(truth: Truth, scores: dict[str, pd.DataFrame]) -> dict:
    changed = truth.changed(config.DETECT_DELTA)
    out = {}
    for variant, sc in scores.items():
        res = {}
        evidence = _grid(sc, "evidence", truth, fill="")
        for score, true in (("W", truth.W), ("H", truth.H)):
            est, lo, hi = (_grid(sc, f"{score}_{q}", truth) for q in ("q50", "q05", "q95"))
            subsets = {"all": np.ones_like(changed)}
            subsets |= {f"evidence_{e}": evidence == e for e in ("sufficient", "weak", "insufficient")}
            subsets |= {"event_weeks": changed, "quiet_weeks": ~changed}
            res[score] = {name: metrics.score_errors(est[m], lo[m], hi[m], true[m]) for name, m in subsets.items()}
        out[variant] = res
    return out


# ----------------------------------------------------------------------------- 2. site-week detection


def _verbal_band(p: float) -> str:
    for bound, key in config.VERBAL_PROBABILITY:
        if p >= bound:
            return key
    return "unlikely"


def site_week_detection(truth: Truth, sensitivity: pd.DataFrame, n_reports: np.ndarray,
                        observations: pd.DataFrame) -> dict:
    observed = n_reports > 0
    grid = []
    for (variant, level), df in sensitivity.groupby(["model_variant", "sensitivity"]):
        delta = float(df["delta"].iloc[0])
        changed = truth.changed(delta)
        level_grid = _grid(df, "alert_level", truth, fill="")
        p = _grid(df, "p_change", truth)
        for rule, pred in (("confirmed", level_grid == "confirmed"),
                           ("confirmed_or_possible", np.isin(level_grid, ["confirmed", "possible"]))):
            grid.append({
                "model_variant": variant, "sensitivity": level, "delta_W": delta, "rule": rule,
                "n_truly_changed": int(changed.sum()),
                **metrics.confusion(pred, changed),
                "recall_observed_weeks": metrics.confusion(pred[observed], changed[observed])["recall"],
                "recall_unobserved_weeks": metrics.confusion(pred[~observed], changed[~observed])["recall"],
                "roc_auc": metrics.roc_auc(p, changed),
                "average_precision": metrics.average_precision(p, changed),
            })

    # Calibration of the words the findings use, at normal sensitivity on the primary model.
    normal = sensitivity[(sensitivity["model_variant"] == PRIMARY_VARIANT) & (sensitivity["sensitivity"] == "normal")]
    p = _grid(normal, "p_change", truth)
    changed = truth.changed(config.DETECT_DELTA)
    bands = np.vectorize(_verbal_band)(p)
    calibration = []
    for key in [k for _, k in config.VERBAL_PROBABILITY] + ["unlikely"]:
        m = bands == key
        calibration.append({
            "band": key.replace("_", " "), "n_site_weeks": int(m.sum()),
            "n_truly_changed": int(changed[m].sum()),
            "share_truly_changed": metrics._ratio(changed[m].sum(), m.sum()),
            "mean_p_change": float(p[m].mean()) if m.any() else None,
        })

    return {
        "by_variant_and_sensitivity": grid,
        "calibration": calibration,
        "baseline": naive_baseline(truth, observations, observed),
        "n_site_weeks": int(observed.size),
        "n_observed_site_weeks": int(observed.sum()),
    }


def naive_baseline(truth: Truth, observations: pd.DataFrame, observed: np.ndarray) -> dict:
    """What you'd get by flagging bad-looking reports directly, with no model."""
    obs = observations.assign(week_start=_as_date(observations["week_start"]))
    bad = (obs["water_clarity"] >= BASELINE_CLARITY) | (
        obs["smell"].isin(BASELINE_SMELLS) & (obs["smell_intensity"] >= BASELINE_SMELL_INTENSITY))
    flagged = obs.assign(flag=bad.fillna(False)).groupby(["site_id", "week_start"], as_index=False)["flag"].any()
    pred = _grid(flagged, "flag", truth, fill=False).astype(bool)
    changed = truth.changed(config.DETECT_DELTA)
    return {
        "rule": f"any report with clarity >= {BASELINE_CLARITY}, or a {'/'.join(BASELINE_SMELLS)} smell "
                f"of intensity >= {BASELINE_SMELL_INTENSITY}",
        "delta_W": config.DETECT_DELTA,
        **metrics.confusion(pred, changed),
        "recall_observed_weeks": metrics.confusion(pred[observed], changed[observed])["recall"],
    }


# ----------------------------------------------------------------------------- 3-4. events & sources


def _incident_cells(inc, truth: Truth, pad: int) -> set[tuple[int, int]]:
    s_idx = {s: i for i, s in enumerate(truth.site_ids)}
    t_idx = {w: i for i, w in enumerate(truth.weeks)}
    a, b = t_idx[inc.start_week], t_idx[inc.end_week]
    T = len(truth.weeks)
    return {(s_idx[s], t) for s in inc.affected_site_ids for t in range(max(0, a - pad), min(T, b + pad + 1))}


def event_detection(truth: Truth, incidents: pd.DataFrame, alerts: pd.DataFrame, n_reports: np.ndarray) -> dict:
    p_change = _grid(alerts, "p_change", truth)
    footprints = {eid: set(zip(*np.nonzero(g > config.DETECT_DELTA))) for eid, g in truth.by_event.items()}
    inc_cells = {i.incident_id: _incident_cells(i, truth, MATCH_TOLERANCE_WEEKS) for i in incidents.itertuples()}
    inc_by_id = {i.incident_id: i for i in incidents.itertuples()}

    overlap = {(eid, iid): len(fp & cells) for eid, fp in footprints.items() for iid, cells in inc_cells.items()}
    matched_incidents = {iid for (eid, iid), n in overlap.items() if n}

    events, attribution = [], []
    for e in truth.events.sort_values("start_week").itertuples():
        fp = footprints[e.event_id]
        hits = sorted((iid for (eid, iid), n in overlap.items() if eid == e.event_id and n),
                      key=lambda iid: -overlap[(e.event_id, iid)])
        reports = int(sum(n_reports[s, t] for s, t in fp))
        max_p = max((p_change[s, t] for s, t in fp), default=0.0)
        levels = {inc_by_id[i].max_alert_level for i in hits}
        if hits:
            outcome = "detected" if "confirmed" in levels else "detected (possible only)"
            reason = None
        elif reports == 0:
            outcome, reason = "missed", "no citizen reports while the drop was large enough to detect"
        else:
            outcome, reason = "missed", f"{reports} report(s), but the change probability peaked at {max_p:.2f} (< {config.P_POSSIBLE})"

        row = {
            "event_id": e.event_id[:8], "event_type": e.event_type, "source_site_id": e.source_site_id,
            "start_week": e.start_week, "end_week": e.end_week, "rain_triggered": bool(e.rain_triggered),
            "peak_drop_W": e.peak_magnitude, "footprint_site_weeks": len(fp), "reports_in_footprint": reports,
            "max_p_change": max_p, "outcome": outcome, "miss_reason": reason, "matched_incidents": hits,
        }
        if hits:
            best = inc_by_id[hits[0]]
            probs = json.loads(best.source_probs_json)
            correct = best.top_source == e.source_site_id
            row |= {"found_source": best.top_source, "source_correct": bool(correct)}
            attribution.append({
                "event_id": e.event_id[:8], "incident_id": best.incident_id, "true_source": e.source_site_id,
                "top_source": best.top_source, "top_source_prob": best.top_source_prob,
                "prob_on_true_source": float(probs.get(e.source_site_id, 0.0)),
                "true_source_in_credible_set": e.source_site_id in list(best.credible_set),
                "correct": bool(correct), "upstream_unobserved": bool(best.upstream_unobserved),
            })
        events.append(row)

    false_alarms = []
    for iid in sorted(set(inc_by_id) - matched_incidents):
        inc = inc_by_id[iid]
        cells = _incident_cells(inc, truth, 0)
        biggest = max((truth.drop[s, t] for s, t in cells), default=0.0)
        false_alarms.append({
            "incident_id": iid, "start_week": inc.start_week, "end_week": inc.end_week,
            "affected_site_ids": list(inc.affected_site_ids), "max_alert_level": inc.max_alert_level,
            "largest_true_drop_W": biggest,
            "what_really_happened": "nothing: no simulated event touched these sites" if biggest == 0
            else f"a real but small change (largest true drop {biggest:.1f} points, below the {config.DETECT_DELTA:.0f}-point threshold)",
        })

    n_detected = sum(r["outcome"] != "missed" for r in events)
    observable = [r for r in events if r["reports_in_footprint"] > 0]
    n_attr = len(attribution)
    return {
        "n_true_events": len(events),
        "n_detected": n_detected,
        "n_detected_confirmed": sum(r["outcome"] == "detected" for r in events),
        "event_recall": metrics._ratio(n_detected, len(events)),
        "n_observable_events": len(observable),
        "event_recall_observable": metrics._ratio(sum(r["outcome"] != "missed" for r in observable), len(observable)),
        "n_incidents": len(inc_by_id),
        "n_false_alarms": len(false_alarms),
        "incident_precision": metrics._ratio(len(matched_incidents), len(inc_by_id)),
        "events": events,
        "false_alarms": false_alarms,
        "source_attribution": {
            "n_matched": n_attr,
            "top1_accuracy": metrics._ratio(sum(a["correct"] for a in attribution), n_attr),
            "credible_set_coverage": metrics._ratio(sum(a["true_source_in_credible_set"] for a in attribution), n_attr),
            "nominal_credible_mass": config.SOURCE_CREDIBLE_MASS,
            "mean_prob_on_true_source": float(np.mean([a["prob_on_true_source"] for a in attribution])) if n_attr else None,
            "wrong_with_upstream_unobserved": sum((not a["correct"]) and a["upstream_unobserved"] for a in attribution),
            "pairs": attribution,
        },
    }


# ----------------------------------------------------------------------------- 5. rain


def rain_check(truth: Truth, heavy_rain: np.ndarray, n_reports: np.ndarray, is_cso: np.ndarray,
               rain_result: dict) -> dict:
    """The true incidence ratio, computed the way detectors/rain.py computes its estimate."""
    changed = truth.changed(config.DETECT_DELTA).astype(float)
    exposed = rain_exposure(heavy_rain)
    observed = n_reports > 0
    groups = {"pooled": np.ones(len(is_cso), bool), "cso_adjacent": is_cso, "other_sites": ~is_cso}
    out = {"model_variant": rain_result["model_variant"], "groups": []}
    for name, mask in groups.items():
        est = rain_result[name]
        true_obs = float(_irr(changed, exposed, observed & mask[:, None]))
        true_all = float(_irr(changed, exposed, np.ones_like(observed) & mask[:, None]))
        present = true_all > 1
        verdict = est["verdict"]
        if verdict == "supported":
            judged = "correct" if present else "false claim"
        elif verdict == "not supported":
            judged = "wrong" if present else "correct"
        else:
            judged = f"no claim ({verdict})"
        out["groups"].append({
            "group": name, "true_irr_observed_weeks": true_obs, "true_irr_all_weeks": true_all,
            "estimated_irr_median": est["irr_median"], "estimated_irr_q05": est["irr_q05"],
            "estimated_irr_q95": est["irr_q95"],
            "interval_contains_truth": bool(est["irr_q05"] <= true_obs <= est["irr_q95"]),
            "verdict": verdict, "pattern_really_present": present, "verdict_judged": judged,
        })
    ev = truth.events
    out["share_of_events_rain_triggered"] = float(ev["rain_triggered"].mean())
    out["n_events"] = int(len(ev))
    return out


# ----------------------------------------------------------------------------- 6. latest week


def latest_week_status(truth: Truth, alerts: pd.DataFrame, scores: pd.DataFrame) -> dict:
    """The status each site shows today (same rule as the dashboard) vs what really happened."""
    week = truth.weeks[-1]
    a = alerts[alerts["week_start"] == week].set_index("site_id")
    s = scores[scores["week_start"] == week].set_index("site_id")
    rows = []
    for i, site in enumerate(truth.site_ids):
        level, evidence = a.loc[site, "alert_level"], s.loc[site, "evidence"]
        status = ("elevated_risk" if level in ("confirmed", "possible")
                  else "insufficient_evidence" if evidence == "insufficient" else "normal")
        really = bool(truth.drop[i, -1] > config.DETECT_DELTA)
        if status == "insufficient_evidence":
            judged = "honest gap (no claim made)" + (" -- a real change was missed" if really else "")
        else:
            judged = "correct" if (status == "elevated_risk") == really else ("false alarm" if status == "elevated_risk" else "missed")
        rows.append({"site_id": site, "status_shown": status, "true_drop_W": truth.drop[i, -1],
                     "W_true": truth.W[i, -1], "W_estimate": s.loc[site, "W_q50"],
                     "really_changed": really, "judged": judged})
    return {"week_start": week, "sites": rows, "summary": dict(Counter(r["judged"] for r in rows))}


# ----------------------------------------------------------------------------- report


def build_report() -> dict:
    sites = io_utils.read_parquet(config.SITES_PATH)
    truth = build_truth(io_utils.read_parquet(config.GROUND_TRUTH_WEEKLY_PATH),
                        io_utils.read_parquet(config.GROUND_TRUTH_EVENTS_PATH), sites)
    observations = io_utils.read_parquet(config.OBSERVATIONS_PATH)
    observations = observations[observations["source"] == "simulated"]  # real reports have no truth

    inp = data_prep.load_inputs()
    if list(inp.weeks) != list(truth.weeks):
        raise ValueError("Model inputs and ground truth use different week grids -- re-run Stages 1-6.")
    order = [inp.site_ids.index(s) for s in truth.site_ids]
    n_reports, heavy_rain = inp.n_reports[order], inp.heavy_rain
    is_cso = sites.set_index("site_id").loc[truth.site_ids, "is_cso_outfall_adjacent"].to_numpy(bool)

    scores = {v: _load_variant(config.MODEL_SCORES_PATH, v) for v in VARIANTS}
    alerts = _load_variant(config.DETECTOR_ALERTS_PATH, PRIMARY_VARIANT)
    incidents = _load_variant(config.DETECTOR_INCIDENTS_PATH, PRIMARY_VARIANT, dates=("start_week", "end_week"))
    sensitivity = io_utils.read_parquet(config.DETECTOR_SENSITIVITY_PATH)
    sensitivity["week_start"] = _as_date(sensitivity["week_start"])
    rain_result = json.loads(config.DETECTOR_RAIN_PATH.read_text())

    events = event_detection(truth, incidents, alerts, n_reports)
    detection = site_week_detection(truth, sensitivity, n_reports, observations)
    scores_acc = score_accuracy(truth, scores)
    normal = next(g for g in detection["by_variant_and_sensitivity"]
                  if g["model_variant"] == PRIMARY_VARIANT and g["sensitivity"] == "normal"
                  and g["rule"] == "confirmed_or_possible")
    headline = {
        "n_true_events": events["n_true_events"],
        "n_events_detected": events["n_detected"],
        "n_incidents": events["n_incidents"],
        "n_false_alarms": events["n_false_alarms"],
        "event_recall": events["event_recall"],
        "incident_precision": events["incident_precision"],
        "site_week_precision": normal["precision"],
        "site_week_recall": normal["recall"],
        "site_week_recall_observed": normal["recall_observed_weeks"],
        "source_top1_accuracy": events["source_attribution"]["top1_accuracy"],
        "W_mae": scores_acc[PRIMARY_VARIANT]["W"]["all"]["mae"],
        "W_coverage_90": scores_acc[PRIMARY_VARIANT]["W"]["all"]["coverage_90"],
        "H_coverage_90": scores_acc[PRIMARY_VARIANT]["H"]["all"]["coverage_90"],
    }
    return _clean({
        "stage": 11,
        "data": {"source": "simulated", "seed": config.RANDOM_SEED, "n_sites": len(truth.site_ids),
                 "n_weeks": len(truth.weeks), "first_week": truth.weeks[0], "latest_week": truth.weeks[-1],
                 "n_reports": int(len(observations))},
        "thresholds": {"delta_W": config.DETECT_DELTA, "p_confirmed": config.P_CONFIRMED,
                       "p_possible": config.P_POSSIBLE, "sensitivity_deltas": config.SENSITIVITY_DELTAS,
                       "match_tolerance_weeks": MATCH_TOLERANCE_WEEKS},
        "caveats": CAVEATS,
        "headline": headline,
        "events": events,
        "site_week_detection": detection,
        "score_accuracy": scores_acc,
        "rain_pattern": rain_check(truth, heavy_rain, n_reports, is_cso, rain_result),
        "latest_week": latest_week_status(truth, alerts, scores[PRIMARY_VARIANT]),
    })


# ----------------------------------------------------------------------------- markdown


def _pct(x) -> str:
    return "n/a" if x is None else f"{100 * x:.0f}%"


def _num(x, nd=1) -> str:
    return "n/a" if x is None else f"{x:.{nd}f}"


def render_markdown(r: dict) -> str:
    h, ev = r["headline"], r["events"]
    sa = ev["source_attribution"]
    lines = [
        "# Stage 11 benchmark: the pipeline vs the simulator's ground truth",
        "",
        f"Simulated data (seed {r['data']['seed']}): {r['data']['n_sites']} sites x {r['data']['n_weeks']} weeks "
        f"({r['data']['first_week']} to {r['data']['latest_week']}), {r['data']['n_reports']} citizen reports. "
        "Generated by `python -m pipeline.benchmark.benchmark`; do not edit by hand.",
        "",
        "## Headline",
        "",
        f"- **Events found:** {h['n_events_detected']} of {h['n_true_events']} true contamination events "
        f"({_pct(h['event_recall'])}); {ev['n_detected_confirmed']} of them at the confirmed level.",
        f"- **False alarms:** {h['n_false_alarms']} of {h['n_incidents']} reported incidents matched no true event "
        f"(incident precision {_pct(h['incident_precision'])}).",
        f"- **Site-week alerts (normal sensitivity, confirmed or possible):** precision {_pct(h['site_week_precision'])}, "
        f"recall {_pct(h['site_week_recall'])} overall and {_pct(h['site_week_recall_observed'])} on weeks with at least one report.",
        f"- **Entry point:** the top-ranked source was right for {_pct(h['source_top1_accuracy'])} of found events.",
        f"- **Scores:** water-quality index off by {_num(h['W_mae'])} points on average; the 90% intervals "
        f"contained the true W {_pct(h['W_coverage_90'])} and the true H {_pct(h['H_coverage_90'])} of the time.",
        "",
        "## Every true event (misses first)",
        "",
        "| Event | Type | Source | Weeks | Peak drop | Rain | Reports | Outcome | Why / matched incident | Source found |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for e in sorted(ev["events"], key=lambda e: (e["outcome"] != "missed", e["start_week"])):
        why = e["miss_reason"] or ", ".join(e["matched_incidents"])
        found = "" if "source_correct" not in e else (f"{e['found_source']} ({'right' if e['source_correct'] else 'wrong'})")
        lines.append(f"| {e['event_id']} | {e['event_type']} | {e['source_site_id']} | {e['start_week']} to {e['end_week']} | "
                     f"{_num(e['peak_drop_W'])} | {'yes' if e['rain_triggered'] else 'no'} | {e['reports_in_footprint']} | "
                     f"**{e['outcome']}** | {why} | {found} |")
    lines += ["", "## False alarms (incidents that matched no true event)", ""]
    if ev["false_alarms"]:
        lines += ["| Incident | Weeks | Sites | Level | What really happened |", "|---|---|---|---|---|"]
        for f in ev["false_alarms"]:
            lines.append(f"| {f['incident_id']} | {f['start_week']} to {f['end_week']} | {', '.join(f['affected_site_ids'])} | "
                         f"{f['max_alert_level']} | {f['what_really_happened']} |")
    else:
        lines.append("None.")
    lines += [
        "", "## Entry-point accuracy", "",
        f"Matched events: {sa['n_matched']}. Top-1 correct: {_pct(sa['top1_accuracy'])}. True source inside the "
        f"{_pct(sa['nominal_credible_mass'])} credible set: {_pct(sa['credible_set_coverage'])}. Mean probability on the "
        f"true source: {_num(sa['mean_prob_on_true_source'], 2)}. Wrong answers flagged 'upstream unobserved': "
        f"{sa['wrong_with_upstream_unobserved']}.",
        "", "## Site-week detection by model and sensitivity", "",
        "| Model | Sensitivity | Rule | Truly changed | TP | FP | FN | Precision | Recall | Recall (observed weeks) | ROC-AUC | Avg precision |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for g in r["site_week_detection"]["by_variant_and_sensitivity"]:
        lines.append(f"| {g['model_variant']} | {g['sensitivity']} ({_num(g['delta_W'], 0)}) | {g['rule'].replace('_', ' ')} | "
                     f"{g['n_truly_changed']} | {g['tp']} | {g['fp']} | {g['fn']} | {_pct(g['precision'])} | {_pct(g['recall'])} | "
                     f"{_pct(g['recall_observed_weeks'])} | {_num(g['roc_auc'], 2)} | {_num(g['average_precision'], 2)} |")
    b = r["site_week_detection"]["baseline"]
    lines += [
        "", f"**No-model baseline** ({b['rule']}): precision {_pct(b['precision'])}, recall {_pct(b['recall'])} "
        f"(observed weeks {_pct(b['recall_observed_weeks'])}), {b['fp']} false positives.",
        "", "## Do the probability words mean what they say? (M1, normal sensitivity)", "",
        "| Word used | Site-weeks | Truly changed | Share | Mean p_change |", "|---|---|---|---|---|",
    ]
    for c in r["site_week_detection"]["calibration"]:
        lines.append(f"| {c['band']} | {c['n_site_weeks']} | {c['n_truly_changed']} | {_pct(c['share_truly_changed'])} | {_num(c['mean_p_change'], 2)} |")
    lines += ["", "## Score accuracy (posterior median vs truth)", "",
              "| Model | Score | Subset | n | MAE | Bias | Spearman | 90% coverage | Interval width |",
              "|---|---|---|---|---|---|---|---|---|"]
    for variant, res in r["score_accuracy"].items():
        for score, subsets in res.items():
            for name, m in subsets.items():
                if m.get("n"):
                    lines.append(f"| {variant} | {score} | {name.replace('_', ' ')} | {m['n']} | {_num(m['mae'])} | {_num(m['bias'])} | "
                                 f"{_num(m['spearman'], 2)} | {_pct(m['coverage_90'])} | {_num(m['mean_interval_width'])} |")
    rp = r["rain_pattern"]
    lines += ["", f"## Rain -> overflow finding ({rp['model_variant']})", "",
              f"{_pct(rp['share_of_events_rain_triggered'])} of the {rp['n_events']} simulated events were rain-triggered.", "",
              "| Group | True IRR (observed weeks) | Estimated IRR [90%] | Contains truth | Verdict | Judged |", "|---|---|---|---|---|---|"]
    for g in rp["groups"]:
        lines.append(f"| {g['group'].replace('_', ' ')} | {_num(g['true_irr_observed_weeks'], 2)} | {_num(g['estimated_irr_median'], 2)} "
                     f"[{_num(g['estimated_irr_q05'], 2)}, {_num(g['estimated_irr_q95'], 2)}] | {'yes' if g['interval_contains_truth'] else 'no'} | "
                     f"{g['verdict']} | {g['verdict_judged']} |")
    lw = r["latest_week"]
    lines += ["", f"## Latest week ({lw['week_start']}): status shown vs reality", "",
              "| Site | Status shown | True drop | W true | W estimate | Judged |", "|---|---|---|---|---|---|"]
    for s in lw["sites"]:
        lines.append(f"| {s['site_id']} | {s['status_shown'].replace('_', ' ')} | {_num(s['true_drop_W'])} | {_num(s['W_true'])} | "
                     f"{_num(s['W_estimate'])} | {s['judged']} |")
    lines += ["", "## Caveats", ""] + [f"- {c}" for c in r["caveats"]] + [""]
    return "\n".join(lines)


def _print_summary(r: dict) -> None:
    h = r["headline"]
    print("--- Stage 11 benchmark summary ---")
    print(f"Events detected: {h['n_events_detected']}/{h['n_true_events']}  false alarms: {h['n_false_alarms']}/{h['n_incidents']} incidents")
    print(f"Site-week alerts (M1, normal): precision {_pct(h['site_week_precision'])}, recall {_pct(h['site_week_recall'])} "
          f"(observed weeks {_pct(h['site_week_recall_observed'])})")
    print(f"Source top-1: {_pct(h['source_top1_accuracy'])}   W MAE {_num(h['W_mae'])}   "
          f"90% coverage W {_pct(h['W_coverage_90'])} / H {_pct(h['H_coverage_90'])}")
    for e in r["events"]["events"]:
        if e["outcome"] == "missed":
            print(f"  MISSED {e['event_id']} {e['event_type']} at {e['source_site_id']} {e['start_week']}: {e['miss_reason']}")
    for f in r["events"]["false_alarms"]:
        print(f"  FALSE ALARM {f['incident_id']} {f['start_week']}: {f['what_really_happened']}")
    print("-----------------------------------")


def run() -> dict[str, Path]:
    if not (config.GROUND_TRUTH_WEEKLY_PATH.exists() and config.GROUND_TRUTH_EVENTS_PATH.exists()):
        logger.warning("No simulator ground truth found -- skipping the benchmark (nothing to score against).")
        return {}
    report = build_report()
    config.BENCHMARK_REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n")
    config.BENCHMARK_MD_PATH.write_text(render_markdown(report), encoding="utf-8")
    logger.info("Wrote %s and %s", config.BENCHMARK_REPORT_PATH, config.BENCHMARK_MD_PATH)
    _print_summary(report)
    return {"benchmark_report": config.BENCHMARK_REPORT_PATH, "benchmark_md": config.BENCHMARK_MD_PATH}


if __name__ == "__main__":
    run()
