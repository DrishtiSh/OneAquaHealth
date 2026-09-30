"""Smoke tests for Stage 3 river graph: chain structure, upstream/downstream
traversal, schema validity, and a deterministic fallback path that doesn't
depend on network availability.
"""

from __future__ import annotations

import pytest

from pipeline.common import canal_geometry, schema
from pipeline.common.sites import get_sites_df
from pipeline.graph import river_graph

TOTAL_LENGTH_TOLERANCE_M = 5.0


@pytest.fixture(scope="module")
def sites_df():
    return get_sites_df()


@pytest.fixture(scope="module")
def graph_and_used_live(sites_df):
    return river_graph.build_graph(sites_df)


def test_graph_is_a_single_chain_head_to_mouth(graph_and_used_live, sites_df):
    graph, _ = graph_and_used_live
    assert graph.number_of_nodes() == len(sites_df)
    assert graph.number_of_edges() == len(sites_df) - 1

    head = sites_df.loc[sites_df["distance_from_mouth_m"].idxmax(), "site_id"]
    mouth = sites_df.loc[sites_df["distance_from_mouth_m"].idxmin(), "site_id"]
    assert graph.in_degree(head) == 0
    assert graph.out_degree(mouth) == 0


def test_edge_distances_are_positive_and_sum_to_real_canal_length(graph_and_used_live):
    graph, _ = graph_and_used_live
    distances = [d["distance_m"] for _, _, d in graph.edges(data=True)]
    assert all(d > 0 for d in distances)
    assert abs(sum(distances) - 2930.7) < TOTAL_LENGTH_TOLERANCE_M


def test_upstream_and_downstream_helpers(graph_and_used_live):
    graph, _ = graph_and_used_live
    assert set(river_graph.upstream_of(graph, "gow-05")) == {"gow-01", "gow-02", "gow-03", "gow-04"}
    assert set(river_graph.downstream_of(graph, "gow-05")) == {"gow-06", "gow-07", "gow-08", "gow-09", "gow-10"}
    assert river_graph.upstream_of(graph, "gow-01") == []
    assert river_graph.downstream_of(graph, "gow-10") == []


def test_edges_validate_against_schema(graph_and_used_live):
    import networkx as nx

    graph, _ = graph_and_used_live
    edges_df = nx.to_pandas_edgelist(graph, source="from_site_id", target="to_site_id")[
        ["from_site_id", "to_site_id", "distance_m"]
    ]
    schema.validate_dataframe(edges_df, schema.RiverGraphEdge, name="river_graph_edges")


def test_fallback_when_osm_unavailable(sites_df, monkeypatch):
    def _always_fails():
        raise canal_geometry.GeometryFetchError("network disabled for test")

    monkeypatch.setattr(canal_geometry, "get_canal_centerline", _always_fails)

    graph, used_live = river_graph.build_graph(sites_df)
    assert used_live is False
    assert graph.number_of_nodes() == len(sites_df)
    assert graph.number_of_edges() == len(sites_df) - 1
    # Falls back to the hardcoded distances, so edge weights are exact differences.
    assert abs(graph["gow-01"]["gow-02"]["distance_m"] - 325.6) < 1.0


def test_load_graph_matches_built_graph(graph_and_used_live, tmp_path, monkeypatch):
    # Redirect outputs so the test never overwrites real data/processed files.
    from pipeline.common import config, io_utils

    sites_path, edges_path = tmp_path / "sites.parquet", tmp_path / "edges.parquet"
    io_utils.write_parquet(get_sites_df(), sites_path)
    monkeypatch.setattr(config, "SITES_PATH", sites_path)
    monkeypatch.setattr(config, "RIVER_GRAPH_EDGES_PATH", edges_path)
    river_graph.run()
    loaded = river_graph.load_graph()
    built, _ = graph_and_used_live
    assert set(loaded.nodes) == set(built.nodes)
    assert set(loaded.edges) == set(built.edges)
