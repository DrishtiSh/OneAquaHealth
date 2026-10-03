"""D1 - "Did something really change, or is it just noise?"

For each site/week: the posterior probability that the contamination excursion pulled W down by
more than `config.DETECT_DELTA` points. Consecutive alert weeks at a site form an episode.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.common import config
from pipeline.detectors.draws import PosteriorDraws, excursion_effects


def alert_level(p_change: float, mixing_flag: bool, evidence: str) -> str:
    """Confirmed needs P >= P_CONFIRMED, a well-mixed posterior, and at least one report that week.

    A mixing-flagged (bimodal: event vs misreport) row or a week with no reports is capped at
    "possible": the probability may be right, but it isn't backed firmly enough to confirm.
    """
    if p_change >= config.P_CONFIRMED and not mixing_flag and evidence != "insufficient":
        return "confirmed"
    if p_change >= config.P_POSSIBLE:
        return "possible"
    return "none"


def _assign_episodes(alerts: pd.DataFrame, week_pos: dict) -> pd.Series:
    """Consecutive alerting weeks at the same site share an episode id."""
    ids = pd.Series([None] * len(alerts), index=alerts.index, dtype=object)
    for site_id, group in alerts[alerts["alert_level"] != "none"].groupby("site_id"):
        k, prev_t = 0, None
        for idx, row in group.sort_values("week_start").iterrows():
            t = week_pos[row["week_start"]]
            if prev_t is None or t != prev_t + 1:
                k += 1
            ids[idx] = f"{site_id}-ep{k:02d}"
            prev_t = t
    return ids


def detect_changes(d: PosteriorDraws, scores: pd.DataFrame, delta: float = config.DETECT_DELTA) -> pd.DataFrame:
    """One row per site/week -- see schema.DetectorAlert.

    `scores` is the Stage 5 score table for the same variant (evidence, mixing_flag, n_reports).
    `delta` is the W drop that counts as a change; other values feed the sensitivity toggle.
    """
    drop_w, rise_h = excursion_effects(d)
    p_change = (drop_w > delta).mean(axis=0)
    q05, q50, q95 = np.quantile(drop_w, [0.05, 0.5, 0.95], axis=0)
    rise_med = np.median(rise_h, axis=0) if rise_h is not None else None

    meta = scores.assign(week_start=pd.to_datetime(scores["week_start"]).dt.date).set_index(["site_id", "week_start"])
    rows = []
    for s, site_id in enumerate(d.site_ids):
        for t, week in enumerate(d.weeks):
            m = meta.loc[(site_id, week)]
            p = float(p_change[s, t])
            rows.append(
                {
                    "site_id": site_id,
                    "week_start": week,
                    "p_change": p,
                    "drop_W_median": float(q50[s, t]),
                    "drop_W_q05": float(q05[s, t]),
                    "drop_W_q95": float(q95[s, t]),
                    "rise_H_median": float(rise_med[s, t]) if rise_med is not None else None,
                    "alert_level": alert_level(p, bool(m["mixing_flag"]), str(m["evidence"])),
                    "evidence": str(m["evidence"]),
                    "mixing_flag": bool(m["mixing_flag"]),
                    "n_reports": int(m["n_reports"]),
                    "model_variant": d.variant,
                }
            )
    alerts = pd.DataFrame(rows)
    alerts["episode_id"] = _assign_episodes(alerts, {w: i for i, w in enumerate(d.weeks)})
    return alerts


def sensitivity_table(d: PosteriorDraws, scores: pd.DataFrame) -> pd.DataFrame:
    """p_change / alert_level at every level of config.SENSITIVITY_DELTAS (dashboard toggle).

    Same rules as the main alerts, only the change size differs. See schema.AlertSensitivity.
    """
    frames = []
    for level, delta in config.SENSITIVITY_DELTAS.items():
        a = detect_changes(d, scores, delta=delta)
        frames.append(a[["site_id", "week_start", "p_change", "alert_level", "model_variant"]].assign(
            sensitivity=level, delta=delta))
    return pd.concat(frames, ignore_index=True)[
        ["model_variant", "site_id", "week_start", "sensitivity", "delta", "p_change", "alert_level"]
    ]
