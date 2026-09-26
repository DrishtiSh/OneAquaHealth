"""Stage 3: Build a river/site graph using OpenStreetMap to figure out which
sites are upstream/downstream of each other.

Produces a directed graph (edges point downstream, head -> mouth) so Stage 6's
detectors can walk upstream from an affected site to find candidate
contamination sources via `nx.ancestors` (see `upstream_of` below), instead of
relying on Stage 1's `distance_from_mouth_m` shortcut directly.

Tries live OSM geometry first (via common/canal_geometry.py) and falls back to
the hardcoded `distance_from_mouth_m` values in common/sites.py if the fetch
fails, so this never hard-fails on lack of network -- same pattern as Stages
1-2's rainfall fallback.
"""

from __future__ import annotations

import logging
from pathlib import Path

import networkx as nx
import pandas as pd
from shapely.geometry import Point

from pipeline.common import canal_geometry, config, io_utils, schema

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

DRIFT_TOLERANCE_M = 50.0


def _live_distances_from_mouth(sites_df: pd.DataFrame, centerline_m) -> dict[str, float]:
    """Live arc-length distance of each site from the mouth, along the real centerline.

    Uses the known mouth site (smallest hardcoded distance_from_mouth_m) as a
    reference point rather than assuming which end of the merged line is the
    mouth -- `linemerge` doesn't guarantee a consistent direction.
    """
    mouth_row = sites_df.loc[sites_df["distance_from_mouth_m"].idxmin()]
    mouth_point_m = canal_geometry.to_metric(Point(mouth_row["lon"], mouth_row["lat"]))
    mouth_arc = centerline_m.project(mouth_point_m)

    distances = {}
    for _, row in sites_df.iterrows():
        point_m = canal_geometry.to_metric(Point(row["lon"], row["lat"]))
        arc = centerline_m.project(point_m)
        distances[row["site_id"]] = abs(arc - mouth_arc)
    return distances


def _check_drift(hardcoded: dict[str, float], live: dict[str, float]) -> None:
    for site_id, hard_val in hardcoded.items():
        diff = abs(hard_val - live[site_id])
        if diff > DRIFT_TOLERANCE_M:
            logger.warning(
                "Site %s: live OSM distance-from-mouth (%.1fm) differs from the hardcoded "
                "value (%.1fm) by %.1fm -- consider re-deriving common/sites.py.",
                site_id,
                live[site_id],
                hard_val,
                diff,
            )


def build_graph(sites_df: pd.DataFrame) -> tuple[nx.DiGraph, bool]:
    """Returns (graph, used_live_osm). Nodes = site_id; edges connect consecutive
    sites ordered head -> mouth, weighted by real distance_m.
    """
    ordered = sites_df.sort_values("distance_from_mouth_m", ascending=False).reset_index(drop=True)
    hardcoded_distances = dict(zip(ordered["site_id"], ordered["distance_from_mouth_m"]))

    try:
        centerline = canal_geometry.get_canal_centerline()
        centerline_m = canal_geometry.to_metric(centerline)
        live_distances = _live_distances_from_mouth(ordered, centerline_m)
        _check_drift(hardcoded_distances, live_distances)
        distances = live_distances
        used_live = True
    except canal_geometry.GeometryFetchError as exc:
        logger.warning("Falling back to hardcoded distances for graph edges: %s", exc)
        distances = hardcoded_distances
        used_live = False

    graph = nx.DiGraph()
    for _, row in ordered.iterrows():
        graph.add_node(
            row["site_id"],
            name=row["name"],
            lat=row["lat"],
            lon=row["lon"],
            is_cso_outfall_adjacent=row["is_cso_outfall_adjacent"],
        )
    for i in range(len(ordered) - 1):
        a, b = ordered.iloc[i]["site_id"], ordered.iloc[i + 1]["site_id"]
        graph.add_edge(a, b, distance_m=abs(distances[a] - distances[b]))

    return graph, used_live


def upstream_of(graph: nx.DiGraph, site_id: str) -> list[str]:
    """All sites upstream of `site_id` (uses ancestors, so this generalizes correctly
    even if a future watershed's graph branches instead of being a simple chain)."""
    return list(nx.ancestors(graph, site_id))


def downstream_of(graph: nx.DiGraph, site_id: str) -> list[str]:
    return list(nx.descendants(graph, site_id))


def load_graph() -> nx.DiGraph:
    """Rebuilds the graph from disk (no network call) -- what Stages 4-6 should use."""
    sites_df = io_utils.read_parquet(config.SITES_PATH)
    edges_df = io_utils.read_parquet(config.RIVER_GRAPH_EDGES_PATH)

    graph = nx.DiGraph()
    for _, row in sites_df.iterrows():
        graph.add_node(
            row["site_id"],
            name=row["name"],
            lat=row["lat"],
            lon=row["lon"],
            is_cso_outfall_adjacent=row["is_cso_outfall_adjacent"],
        )
    for _, row in edges_df.iterrows():
        graph.add_edge(row["from_site_id"], row["to_site_id"], distance_m=row["distance_m"])
    return graph


def _print_summary(graph: nx.DiGraph, used_live: bool) -> None:
    total_length = sum(d["distance_m"] for _, _, d in graph.edges(data=True))
    print("--- Stage 3 river graph summary ---")
    print(f"Nodes: {graph.number_of_nodes()}, Edges: {graph.number_of_edges()}")
    print(f"Geometry source: {'live OSM' if used_live else 'hardcoded fallback'}")
    print(f"Total chain length: {total_length:.1f}m")
    print("------------------------------------")


def run() -> dict[str, Path]:
    if not config.SITES_PATH.exists():
        raise FileNotFoundError(f"{config.SITES_PATH} not found -- run Stage 1 (ingestion) first.")

    sites_df = io_utils.read_parquet(config.SITES_PATH)
    graph, used_live = build_graph(sites_df)

    edges_df = nx.to_pandas_edgelist(graph, source="from_site_id", target="to_site_id")[
        ["from_site_id", "to_site_id", "distance_m"]
    ]
    schema.validate_dataframe(edges_df, schema.RiverGraphEdge, name="river_graph_edges")

    io_utils.write_parquet(edges_df, config.RIVER_GRAPH_EDGES_PATH)
    logger.info("Wrote %d edges to %s", len(edges_df), config.RIVER_GRAPH_EDGES_PATH)
    _print_summary(graph, used_live)

    return {"river_graph_edges": config.RIVER_GRAPH_EDGES_PATH}


if __name__ == "__main__":
    run()
