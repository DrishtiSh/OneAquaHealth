"""Real Gowanus Canal centerline geometry, fetched live from OpenStreetMap.

This is the exact derivation documented (but not, until now, implemented in
code) at the top of `pipeline/common/sites.py`, used there once, by hand, to
derive the hardcoded `distance_from_mouth_m` values. Stage 3 (river_graph.py)
calls this live so it can build the actual graph from real, current geometry
rather than only trusting those hardcoded numbers -- osmnx caches its HTTP
responses on disk (see the gitignored `cache/` dir), so repeat calls are free.
"""

from __future__ import annotations

import geopandas as gpd
import osmnx as ox
from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge

# Bounding box around Gowanus, Brooklyn -- see pipeline/common/sites.py's docstring.
_BBOX = (-74.010, 40.668, -73.988, 40.688)  # (west, south, east, north)
_CANAL_NAME = "Gowanus Canal"
METRIC_CRS = "EPSG:32618"  # UTM 18N, covers Brooklyn -- reused by exposure.py for its own reprojections


class GeometryFetchError(RuntimeError):
    """Raised when the live OSM canal geometry can't be fetched or merged."""


def get_canal_centerline() -> LineString:
    """Returns the real Gowanus Canal centerline as a single LineString (EPSG:4326).

    `shapely.ops.linemerge` does not guarantee which end comes first, so
    callers must not assume head-first/mouth-first ordering -- determine which
    end is which using a known reference point (see river_graph.py, which uses
    the known mouth site's coordinates) rather than trusting line direction.
    """
    try:
        west, south, east, north = _BBOX
        gdf = ox.features_from_bbox((west, south, east, north), tags={"waterway": "canal"})
        canal = gdf[gdf["name"] == _CANAL_NAME]
        if canal.empty:
            raise GeometryFetchError(f"No OSM way named '{_CANAL_NAME}' found in the Gowanus bounding box.")
        merged = linemerge(MultiLineString(list(canal.geometry)))
        if not isinstance(merged, LineString):
            raise GeometryFetchError(f"Expected a single merged LineString, got {merged.geom_type}.")
        return merged
    except GeometryFetchError:
        raise
    except Exception as exc:
        raise GeometryFetchError(f"Failed to fetch/merge the Gowanus Canal centerline: {exc}") from exc


def to_metric(geom):
    """Reprojects a shapely geometry (assumed EPSG:4326) to the metric CRS used for distances."""
    return gpd.GeoSeries([geom], crs="EPSG:4326").to_crs(METRIC_CRS).iloc[0]


def from_metric(geom):
    """Reprojects a shapely geometry (assumed METRIC_CRS) back to EPSG:4326."""
    return gpd.GeoSeries([geom], crs=METRIC_CRS).to_crs("EPSG:4326").iloc[0]
