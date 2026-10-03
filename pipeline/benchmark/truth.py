"""Benchmark-only view of the simulator's hidden truth: how far each event really pulled W down.

`contamination_event_active` in the weekly ground truth is True even far downstream, where the
decayed effect is a point or two -- far below anything a detector is asked to find. So the
benchmark scores against the size of the true drop instead, recomputed from the events table
with the simulator's own decay and travel-lag rules. `event_activity` cross-checks the result
against the stored ground truth, so a change to the simulator can't silently skew the labels.

Approximations (stated in the report): overlapping events add up, and the clip of W_true at 0
is ignored (it only bites when a drop exceeds the ~80-point baseline).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from pipeline.ingestion.simulator import DECAY_CONSTANT_M, FLOW_SPEED_M_PER_WEEK


@dataclass(frozen=True)
class Truth:
    site_ids: list[str]
    weeks: list[date]
    drop: np.ndarray  # (S, T) true W drop from all events, index points
    by_event: dict[str, np.ndarray]  # event_id -> (S, T) this event's own drop
    W: np.ndarray  # (S, T) W_true
    H: np.ndarray  # (S, T) H_true
    events: pd.DataFrame

    def changed(self, delta: float) -> np.ndarray:
        """(S, T) bool: the site-week truly dropped by more than `delta` points."""
        return self.drop > delta

    def frame(self) -> pd.DataFrame:
        """Long table: site_id, week_start, W_true, H_true, true_drop."""
        S, T = self.drop.shape
        return pd.DataFrame({
            "site_id": np.repeat(self.site_ids, T),
            "week_start": self.weeks * S,
            "W_true": self.W.ravel(),
            "H_true": self.H.ravel(),
            "true_drop": self.drop.ravel(),
        })


def _as_date(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s).dt.date


def build_truth(ground_truth: pd.DataFrame, events: pd.DataFrame, sites: pd.DataFrame, *, check: bool = True) -> Truth:
    """`check=False` skips the cross-check against the stored flags (tests use it to build a world)."""
    gt = ground_truth.assign(week_start=_as_date(ground_truth["week_start"]))
    site_ids = sorted(gt["site_id"].unique())
    weeks = sorted(gt["week_start"].unique())
    s_idx = {s: i for i, s in enumerate(site_ids)}
    t_idx = {w: i for i, w in enumerate(weeks)}
    S, T = len(site_ids), len(weeks)

    W = np.zeros((S, T))
    H = np.zeros((S, T))
    stored_active = np.zeros((S, T), bool)
    for row in gt.itertuples(index=False):
        s, t = s_idx[row.site_id], t_idx[row.week_start]
        W[s, t], H[s, t], stored_active[s, t] = row.W_true, row.H_true, row.contamination_event_active

    dist = dict(zip(sites["site_id"], sites["distance_from_mouth_m"]))
    ev = events.assign(start_week=_as_date(events["start_week"]), end_week=_as_date(events["end_week"]))
    by_event: dict[str, np.ndarray] = {}
    for e in ev.itertuples(index=False):
        grid = np.zeros((S, T))
        src_dist = dist[e.source_site_id]
        start_idx, end_idx = t_idx[e.start_week], t_idx[e.end_week]
        # Same rules as simulator.generate_ground_truth.
        for site in e.affected_site_ids:
            travelled = src_dist - dist[site]
            magnitude = e.peak_magnitude * np.exp(-travelled / DECAY_CONSTANT_M)
            lag = int(round(travelled / FLOW_SPEED_M_PER_WEEK))
            a, b = min(start_idx + lag, T - 1), min(end_idx + lag, T - 1)
            if a <= b:
                grid[s_idx[site], a : b + 1] += magnitude
        by_event[e.event_id] = grid

    drop = sum(by_event.values(), np.zeros((S, T)))
    if check and not np.array_equal(drop > 0, stored_active):
        raise ValueError(
            "Recomputed event footprints disagree with the stored ground truth -- the simulator's "
            "event rules changed; update pipeline/benchmark/truth.py to match."
        )
    return Truth(site_ids, weeks, drop, by_event, W, H, ev.reset_index(drop=True))
