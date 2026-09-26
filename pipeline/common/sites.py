"""Real monitoring-site metadata for the Gowanus Canal, Brooklyn watershed.

Coordinates are DERIVED, not hand-typed, so they land exactly on the real canal
centerline (needed for stage 3's OSM river-graph queries and stage 4's OSM
exposure-feature queries to produce meaningful results). Derivation:

1. Fetch the two OpenStreetMap ways named "Gowanus Canal" inside a bounding box
   around Gowanus, Brooklyn: `osmnx.features_from_bbox(bbox, tags={"waterway": "canal"})`.
2. Merge them into a single LineString with `shapely.ops.linemerge`.
3. Reproject to a metric CRS (EPSG:32618, UTM 18N) and sample 10 evenly spaced
   points from head to mouth via `line.interpolate(fraction, normalized=True)`,
   recording each point's true distance (in meters) from the mouth.

The result: head = "gow-01" near Butler St (real dist ~2931m from the mouth),
mouth = "gow-10" at Hamilton Ave / Gowanus Bay (dist = 0m). Total canal length
came out to ~2.93km, matching the canal's well-documented ~1.8mi length.

Street-name labels below are approximate narrative landmarks for the demo
(the real cross streets running along the canal, in order); the lat/lon values
themselves are exact points on the real canal centerline, not approximations.
CSO-outfall-adjacency flags reference the two real, publicly documented CSO
retention facilities on the canal: "Head End" (RH-034, near the head) and
"Owls Head" (OH-007, near 3rd/4th St).
"""

from __future__ import annotations

import pandas as pd

WATERSHED = "Gowanus Canal"

# Ordered from head (index 0, farthest from the mouth) to mouth (index 9).
SITES: list[dict] = [
    {
        "site_id": "gow-01",
        "name": "Butler St Head",
        "lat": 40.681577,
        "lon": -73.986926,
        "watershed": WATERSHED,
        "distance_from_mouth_m": 2930.7,
        "is_cso_outfall_adjacent": True,
        "known_context_note": "Head of the canal; near the 'Head End' (RH-034) CSO retention facility.",
    },
    {
        "site_id": "gow-02",
        "name": "Douglass St",
        "lat": 40.678973,
        "lon": -73.988701,
        "watershed": WATERSHED,
        "distance_from_mouth_m": 2605.1,
        "is_cso_outfall_adjacent": True,
        "known_context_note": "Near the 'Head End' (RH-034) CSO retention facility.",
    },
    {
        "site_id": "gow-03",
        "name": "Degraw St",
        "lat": 40.676319,
        "lon": -73.990099,
        "watershed": WATERSHED,
        "distance_from_mouth_m": 2279.4,
        "is_cso_outfall_adjacent": False,
        "known_context_note": None,
    },
    {
        "site_id": "gow-04",
        "name": "Sackett St",
        "lat": 40.676070,
        "lon": -73.993401,
        "watershed": WATERSHED,
        "distance_from_mouth_m": 1953.8,
        "is_cso_outfall_adjacent": False,
        "known_context_note": None,
    },
    {
        "site_id": "gow-05",
        "name": "Union St",
        "lat": 40.674395,
        "lon": -73.996232,
        "watershed": WATERSHED,
        "distance_from_mouth_m": 1628.2,
        "is_cso_outfall_adjacent": False,
        "known_context_note": "Near the Gowanus Canal Sponge Park.",
    },
    {
        "site_id": "gow-06",
        "name": "Carroll St",
        "lat": 40.671883,
        "lon": -73.998220,
        "watershed": WATERSHED,
        "distance_from_mouth_m": 1302.5,
        "is_cso_outfall_adjacent": True,
        "known_context_note": "Near the 'Owls Head' (OH-007) CSO retention facility.",
    },
    {
        "site_id": "gow-07",
        "name": "3rd St",
        "lat": 40.669197,
        "lon": -73.999671,
        "watershed": WATERSHED,
        "distance_from_mouth_m": 976.9,
        "is_cso_outfall_adjacent": True,
        "known_context_note": "Near the 'Owls Head' (OH-007) CSO retention facility.",
    },
    {
        "site_id": "gow-08",
        "name": "6th/7th St",
        "lat": 40.667212,
        "lon": -74.002364,
        "watershed": WATERSHED,
        "distance_from_mouth_m": 651.3,
        "is_cso_outfall_adjacent": False,
        "known_context_note": None,
    },
    {
        "site_id": "gow-09",
        "name": "9th St",
        "lat": 40.665938,
        "lon": -74.005829,
        "watershed": WATERSHED,
        "distance_from_mouth_m": 325.6,
        "is_cso_outfall_adjacent": False,
        "known_context_note": None,
    },
    {
        "site_id": "gow-10",
        "name": "Hamilton Ave Mouth",
        "lat": 40.664754,
        "lon": -74.009354,
        "watershed": WATERSHED,
        "distance_from_mouth_m": 0.0,
        "is_cso_outfall_adjacent": False,
        "known_context_note": "Mouth of the canal, discharging into Gowanus Bay.",
    },
]


def get_sites_df() -> pd.DataFrame:
    return pd.DataFrame(SITES)
