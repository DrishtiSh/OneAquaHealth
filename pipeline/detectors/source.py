"""D2 - "Can we find the likely entry point of contamination upstream?"

Episodes that are close in time (downstream travel lag) and close along the river (a pulse decays
with distance) are grouped into incidents. For each incident, per posterior draw, the entry point
is the most upstream site reachable from an affected site through an *unbroken* run of sites
whose W dropped by more than `config.DETECT_DELTA` -- a pulse flows downstream continuously, so an
isolated noisy exceedance far upstream can't claim to be the source. P(source = site) is the
share of draws.

Stage 5's M1 has no spatial coupling (each site's excursion is independent), so an upstream ->
downstream pattern found here comes from the reports, not from the model's assumptions.
"""

from __future__ import annotations

import json

import networkx as nx
import numpy as np
import pandas as pd

from pipeline.common import config
from pipeline.detectors.draws import PosteriorDraws, excursion_effects

_LEVEL_RANK = {"possible": 1, "confirmed": 2}


def _episodes(alerts: pd.DataFrame, week_pos: dict) -> pd.DataFrame:
    flagged = alerts[alerts["episode_id"].notna()].assign(t=lambda d: d["week_start"].map(week_pos))
    return (
        flagged.groupby("episode_id")
        .agg(
            site_id=("site_id", "first"),
            start_t=("t", "min"),
            end_t=("t", "max"),
            max_level=("alert_level", lambda s: max(s, key=_LEVEL_RANK.__getitem__)),
        )
        .reset_index()
    )


def group_incidents(
    episodes: pd.DataFrame, graph: nx.DiGraph, window: int, max_hops: int = config.INCIDENT_MAX_HOPS
) -> list[list[int]]:
    """Union-find over episodes: linked if within `window` weeks and `max_hops` river hops.

    Linking is transitive, so a pulse seen at a chain of neighbouring sites still forms one
    incident, but unrelated episodes at opposite ends of the canal do not.
    """
    parent = list(range(len(episodes)))
    hops = dict(nx.all_pairs_shortest_path_length(graph.to_undirected(), cutoff=max_hops))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    rows = episodes.to_dict("records")
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            a, b = rows[i], rows[j]
            close = a["start_t"] <= b["end_t"] + window and b["start_t"] <= a["end_t"] + window
            near = b["site_id"] in hops.get(a["site_id"], {})
            if close and near:
                parent[find(i)] = find(j)

    groups: dict[int, list[int]] = {}
    for i in range(len(rows)):
        groups.setdefault(find(i), []).append(i)
    return sorted(groups.values(), key=lambda g: min(rows[i]["start_t"] for i in g))


def source_posterior(
    max_drop: np.ndarray,
    candidates: list[str],
    affected: list[str],
    graph: nx.DiGraph,
    upstream_rank: dict[str, int],
    delta: float,
) -> tuple[dict[str, float], float]:
    """max_drop: (N, len(candidates)) per-draw largest drop in the incident window.

    Per draw: start from the affected sites that exceed `delta`, walk upstream through
    predecessors that also exceed, and take the most upstream site reached. Returns
    ({site: P(source = site)}, P(no affected site exceeds delta in the draw)).
    """
    col = {c: i for i, c in enumerate(candidates)}
    exceeds = max_drop > delta
    counts = dict.fromkeys(candidates, 0)
    n_none = 0
    for row in exceeds:
        frontier = [s for s in affected if row[col[s]]]
        if not frontier:
            n_none += 1
            continue
        seen = set(frontier)
        while frontier:
            site = frontier.pop()
            for up in graph.predecessors(site):
                if up in col and up not in seen and row[col[up]]:
                    seen.add(up)
                    frontier.append(up)
        counts[min(seen, key=upstream_rank.__getitem__)] += 1
    n = len(exceeds)
    return {c: counts[c] / n for c in candidates}, n_none / n


def credible_set(probs: dict[str, float], mass: float) -> list[str]:
    """Smallest set of sources holding `mass` of the probability assigned to *some* source."""
    total = sum(probs.values())
    if total == 0:
        return []
    chosen, acc = [], 0.0
    for site, p in sorted(probs.items(), key=lambda kv: -kv[1]):
        chosen.append(site)
        acc += p / total
        if acc >= mass - 1e-12:
            break
    return chosen


def localise_incidents(
    d: PosteriorDraws,
    alerts: pd.DataFrame,
    graph: nx.DiGraph,
    heavy_rain: np.ndarray,
) -> pd.DataFrame:
    """One row per incident -- see schema.Incident."""
    week_pos = {w: i for i, w in enumerate(d.weeks)}
    site_pos = {s: i for i, s in enumerate(d.site_ids)}
    episodes = _episodes(alerts, week_pos)
    if episodes.empty:
        return pd.DataFrame(columns=list(_empty_incident_columns()))

    drop_w, _ = excursion_effects(d)
    upstream_rank = {s: i for i, s in enumerate(nx.topological_sort(graph))}
    n_reports = alerts.pivot(index="site_id", columns="week_start", values="n_reports").reindex(
        index=d.site_ids, columns=d.weeks
    ).to_numpy()
    drop_median = np.median(drop_w, axis=0)
    window = config.INCIDENT_WINDOW_WEEKS
    T = len(d.weeks)

    rows = []
    for k, members in enumerate(group_incidents(episodes, graph, window), start=1):
        ep = episodes.iloc[members]
        affected = sorted(set(ep["site_id"]), key=upstream_rank.get)
        start_t, end_t = int(ep["start_t"].min()), int(ep["end_t"].max())
        lo, hi = max(0, start_t - window), end_t  # upstream shows the change at the same time or earlier

        # Candidates: the affected sites and everything upstream of them.
        candidates = sorted(
            set(affected).union(*(nx.ancestors(graph, s) for s in affected)), key=upstream_rank.get
        )
        idx = [site_pos[c] for c in candidates]
        max_drop = drop_w[:, idx, lo : hi + 1].max(axis=2)
        probs, p_none = source_posterior(max_drop, candidates, affected, graph, upstream_rank, config.DETECT_DELTA)
        top = max(probs, key=probs.get) if any(probs.values()) else None

        parents = list(graph.predecessors(top)) if top else []
        entry = (
            f"between {', '.join(parents)} and {top}" if parents
            else f"at or above {top} (head of the monitored network)" if top
            else "undetermined"
        )
        upstream_unobserved = bool(
            parents and all(n_reports[site_pos[p], lo : hi + 1].sum() == 0 for p in parents)
        )

        decays = None
        if top is not None:
            chain = [top] + [s for s in affected if s in nx.descendants(graph, top)]
            if len(chain) >= 2:
                peak = [drop_median[site_pos[s], lo : hi + 1].max() for s in chain]
                decays = bool(peak[0] > peak[-1])

        rows.append(
            {
                "incident_id": f"inc-{k:03d}",
                "start_week": d.weeks[start_t],
                "end_week": d.weeks[end_t],
                "affected_site_ids": affected,
                "n_episodes": len(ep),
                "max_alert_level": max(ep["max_level"], key=_LEVEL_RANK.__getitem__),
                "top_source": top,
                "top_source_prob": probs.get(top, 0.0) if top else 0.0,
                "p_no_source": p_none,
                "credible_set": credible_set(probs, config.SOURCE_CREDIBLE_MASS),
                "source_probs_json": json.dumps({s: round(p, 4) for s, p in probs.items() if p > 0}),
                "entry_segment": entry,
                "upstream_unobserved": upstream_unobserved,
                "decays_downstream": decays,
                "rain_week": bool(heavy_rain[max(0, start_t - config.RAIN_LAG_WEEKS) : min(T, end_t + 1)].any()),
                "peak_drop_W": float(max(drop_median[site_pos[s], start_t : end_t + 1].max() for s in affected)),
                "model_variant": d.variant,
            }
        )
    return pd.DataFrame(rows)


def _empty_incident_columns():
    return (
        "incident_id", "start_week", "end_week", "affected_site_ids", "n_episodes", "max_alert_level",
        "top_source", "top_source_prob", "p_no_source", "credible_set", "source_probs_json", "entry_segment",
        "upstream_unobserved", "decays_downstream", "rain_week", "peak_drop_W", "model_variant",
    )
