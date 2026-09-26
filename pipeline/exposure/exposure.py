"""Stage 4: Find nearby exposure points (playgrounds, schools, parks, etc. from OSM)
where contamination would actually matter to people.

Unlike Stage 2's rainfall or Stage 3's river geometry, there's no physically
plausible synthetic substitute for "is there really a playground near this
site" -- so if OSM can't be reached, this stage doesn't fabricate one. It
honestly marks those rows `data_source="unavailable"` instead, so Stage 7's
NLG can tell "verified no nearby POI" apart from "we don't know" (the same
"insufficient evidence" idea the README describes for Stage 10's dashboard,
one layer earlier).
"""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import osmnx as ox
import pandas as pd
from osmnx._errors import InsufficientResponseError
from shapely.geometry import Point

from pipeline.common import canal_geometry, config, io_utils, schema

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

_TAGS = {
    "playground": {"leisure": "playground"},
    "school": {"amenity": "school"},
    "park": {"leisure": "park"},
}
PROXIMITY_THRESHOLD_M = 250.0
BBOX_PAD_M = 400.0


class PoiFetchError(RuntimeError):
    """Raised when a genuine network/API failure prevents fetching POIs from OSM.

    Not raised when a category simply has zero real matches -- that's a valid
    outcome (see fetch_pois_by_category), not a failure.
    """


def _padded_bbox(sites_df: pd.DataFrame, pad_m: float = BBOX_PAD_M) -> tuple[float, float, float, float]:
    """Returns (west, south, east, north) covering all sites, padded in real meters
    (not naive degree padding, since a degree of longitude/latitude isn't a fixed
    distance) so POIs just outside a site's exposure radius near the bbox edge
    are still captured for "nearest distance" purposes.
    """
    sw = canal_geometry.to_metric(Point(sites_df["lon"].min(), sites_df["lat"].min()))
    ne = canal_geometry.to_metric(Point(sites_df["lon"].max(), sites_df["lat"].max()))
    sw_deg = canal_geometry.from_metric(Point(sw.x - pad_m, sw.y - pad_m))
    ne_deg = canal_geometry.from_metric(Point(ne.x + pad_m, ne.y + pad_m))
    return (sw_deg.x, sw_deg.y, ne_deg.x, ne_deg.y)


def fetch_pois_by_category(bbox: tuple[float, float, float, float]) -> dict[str, gpd.GeoDataFrame]:
    """One OSM fetch per category. A category with zero real matches returns an
    empty GeoDataFrame (a normal outcome). Raises PoiFetchError only on a
    genuine network/API failure.
    """
    west, south, east, north = bbox
    pois_by_category = {}
    for category, tags in _TAGS.items():
        try:
            pois_by_category[category] = ox.features_from_bbox((west, south, east, north), tags=tags)
        except InsufficientResponseError:
            pois_by_category[category] = gpd.GeoDataFrame(geometry=[])
        except Exception as exc:
            raise PoiFetchError(f"Failed to fetch '{category}' POIs from OSM: {exc}") from exc
    return pois_by_category


def _nearest_poi(site_point_m, pois_gdf: gpd.GeoDataFrame) -> tuple[float | None, str | None, int]:
    """Distance via .distance() on each POI's raw geometry (point or polygon) --
    not .centroid, so a large park's near edge is measured correctly rather than
    its centroid, which would overstate distance for big/oblong polygons.
    """
    if pois_gdf.empty:
        return None, None, 0

    pois_m = pois_gdf.geometry.to_crs(canal_geometry.METRIC_CRS)
    distances = pois_m.distance(site_point_m)
    nearest_idx = distances.idxmin()
    nearest_distance = float(distances.loc[nearest_idx])
    nearest_name = pois_gdf.loc[nearest_idx].get("name")
    if not isinstance(nearest_name, str):
        nearest_name = "unnamed"
    count_within = int((distances <= PROXIMITY_THRESHOLD_M).sum())
    return nearest_distance, nearest_name, count_within


def compute_exposure_features(sites_df: pd.DataFrame) -> pd.DataFrame:
    """Returns one row per (site_id, category) -- see schema.ExposureFeature."""
    try:
        bbox = _padded_bbox(sites_df)
        pois_by_category = fetch_pois_by_category(bbox)
        used_real = True
    except PoiFetchError as exc:
        logger.warning("Falling back to 'unavailable' exposure rows: %s", exc)
        pois_by_category = {}
        used_real = False

    rows = []
    for _, site in sites_df.iterrows():
        site_point_m = canal_geometry.to_metric(Point(site["lon"], site["lat"]))
        for category in _TAGS:
            if used_real:
                nearest_distance, nearest_name, count_within = _nearest_poi(
                    site_point_m, pois_by_category[category]
                )
                data_source = "real"
            else:
                nearest_distance, nearest_name, count_within = None, None, 0
                data_source = "unavailable"

            rows.append(
                {
                    "site_id": site["site_id"],
                    "category": category,
                    "nearest_poi_distance_m": nearest_distance,
                    "nearest_poi_name": nearest_name,
                    "poi_count_within_threshold": count_within,
                    "is_exposure_relevant": nearest_distance is not None and nearest_distance <= PROXIMITY_THRESHOLD_M,
                    "data_source": data_source,
                }
            )

    return pd.DataFrame(rows)


def _print_summary(exposure_df: pd.DataFrame) -> None:
    print("--- Stage 4 exposure summary ---")
    print(f"Site-categories: {len(exposure_df)}")
    print(f"Data sources: {exposure_df['data_source'].value_counts().to_dict()}")
    print(f"Exposure-relevant rows: {int(exposure_df['is_exposure_relevant'].sum())}")
    for category, group in exposure_df.groupby("category"):
        nearest = group["nearest_poi_distance_m"].min()
        print(f"  {category}: closest overall = {nearest:.0f}m" if pd.notna(nearest) else f"  {category}: none found")
    print("---------------------------------")


def run() -> dict[str, Path]:
    if not config.SITES_PATH.exists():
        raise FileNotFoundError(f"{config.SITES_PATH} not found -- run Stage 1 (ingestion) first.")

    sites_df = io_utils.read_parquet(config.SITES_PATH)
    exposure_df = compute_exposure_features(sites_df)
    schema.validate_dataframe(exposure_df, schema.ExposureFeature, name="exposure_features")

    io_utils.write_parquet(exposure_df, config.EXPOSURE_FEATURES_PATH)
    logger.info("Wrote %d rows to %s", len(exposure_df), config.EXPOSURE_FEATURES_PATH)
    _print_summary(exposure_df)

    return {"exposure_features": config.EXPOSURE_FEATURES_PATH}


if __name__ == "__main__":
    run()
