"""Stage 6: Run detectors on top of the model - did something really change (not just noise), can we find the likely entry point of contamination upstream, is there a rain -> sewage overflow pattern.

Which Stage 5 variant feeds which detector:
  * D1 change detection   -> M1 (primary model)
  * D2 source localisation -> M1 (no spatial coupling in M1, so the pattern comes from the data)
  * D3 rain -> overflow    -> M1_norain (M1 already assumes rain matters; asking it would be
                              circular). M1's beta_rain is reported as corroboration only.

Dashboard toggles (precomputed here, where the posterior draws live, so the live app never
recomputes): D1/D2 are also run on M1_norain (rain-assumption toggle), and alert probabilities
are computed at every config.SENSITIVITY_DELTAS level (sensitivity toggle). Incidents and the
Stage 7 findings stay at the "normal" level.

Thresholds live in common/config.py and were fixed before any benchmark comparison.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.common import config, io_utils, schema
from pipeline.detectors import change, draws, rain, source
from pipeline.graph import river_graph
from pipeline.model import data_prep
from pipeline.model.bayesian_model import variant_path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

PRIMARY_VARIANT = "M1"
RAIN_VARIANT = "M1_norain"


def _load_scores(variant: str) -> pd.DataFrame:
    """Stage 5 score table for a variant (evidence, mixing_flag, n_reports)."""
    path = variant_path(config.MODEL_SCORES_PATH, variant)
    if not path.exists():
        raise FileNotFoundError(f"{path} not found -- run Stage 5 (model) first.")
    return io_utils.read_parquet(path)


def _print_summary(alerts: pd.DataFrame, incidents: pd.DataFrame, rain_result: dict) -> None:
    levels = alerts["alert_level"].value_counts().to_dict()
    print("--- Stage 6 detectors summary ---")
    print(f"Change alerts (M1): confirmed={levels.get('confirmed', 0)} possible={levels.get('possible', 0)} "
          f"episodes={alerts['episode_id'].nunique()}")
    print(f"Incidents: {len(incidents)}")
    for _, inc in incidents.iterrows():
        caveat = " (upstream unobserved)" if inc["upstream_unobserved"] else ""
        print(f"  {inc['incident_id']} {inc['start_week']}..{inc['end_week']} sites={','.join(inc['affected_site_ids'])} "
              f"source={inc['top_source']} P={inc['top_source_prob']:.2f}{caveat} rain={inc['rain_week']}")
    pooled = rain_result["pooled"]
    print(f"Rain -> overflow ({rain_result['model_variant']}): IRR {pooled['irr_median']:.2f} "
          f"[{pooled['irr_q05']:.2f}, {pooled['irr_q95']:.2f}], P(IRR>1)={pooled['p_irr_gt_1']:.2f}, "
          f"placebo p={pooled['placebo_p']:.3f} -> {rain_result['verdict']}")
    print(f"  CSO-adjacent: {rain_result['cso_adjacent']['verdict']}  other sites: {rain_result['other_sites']['verdict']}")
    print("----------------------------------")


def _detect_variant(d: draws.PosteriorDraws, graph, heavy_rain) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """D1 + D2 + the sensitivity toggle table for one model variant."""
    scores = _load_scores(d.variant)
    alerts = change.detect_changes(d, scores)
    schema.validate_dataframe(alerts, schema.DetectorAlert, name=f"detector_alerts[{d.variant}]")
    incidents = source.localise_incidents(d, alerts, graph, heavy_rain)
    schema.validate_dataframe(incidents, schema.Incident, name=f"detector_incidents[{d.variant}]")
    sensitivity = change.sensitivity_table(d, scores)
    schema.validate_dataframe(sensitivity, schema.AlertSensitivity, name=f"detector_sensitivity[{d.variant}]")
    return alerts, incidents, sensitivity


def run() -> dict[str, Path]:
    primary = draws.load_draws(PRIMARY_VARIANT)
    rain_draws = draws.load_draws(RAIN_VARIANT)
    inp = data_prep.load_inputs()
    for d in (primary, rain_draws):
        if inp.site_ids != d.site_ids or inp.weeks != d.weeks:
            raise ValueError(f"Stage 5 draws ({d.variant}) are out of date with the Stage 1-2 data -- re-run Stage 5.")
    graph = river_graph.load_graph()
    sites = io_utils.read_parquet(config.SITES_PATH).set_index("site_id").loc[inp.site_ids]

    # D1 + D2 for both variants: M1 drives the findings; M1_norain feeds the dashboard's
    # rain-assumption toggle. Both also get the sensitivity toggle table.
    results = {d.variant: _detect_variant(d, graph, inp.heavy_rain) for d in (primary, rain_draws)}
    alerts, incidents, _ = results[PRIMARY_VARIANT]

    # D3 (M1_norain; M1 beta_rain as corroboration)
    rain_result = rain.analyse_rain(
        rain_draws,
        inp.heavy_rain,
        inp.n_reports,
        sites["is_cso_outfall_adjacent"].to_numpy(dtype=bool),
        sewage_by_report=(inp.week_idx, inp.sewage),
        corroborating=primary,
    )

    for variant, (a, i, _) in results.items():
        io_utils.write_parquet(a, variant_path(config.DETECTOR_ALERTS_PATH, variant, PRIMARY_VARIANT))
        io_utils.write_parquet(i, variant_path(config.DETECTOR_INCIDENTS_PATH, variant, PRIMARY_VARIANT))
    io_utils.write_parquet(
        pd.concat([sens for _, _, sens in results.values()], ignore_index=True), config.DETECTOR_SENSITIVITY_PATH
    )
    config.DETECTOR_RAIN_PATH.write_text(json.dumps(rain_result, indent=2, default=float))
    logger.info("Wrote %d alert rows, %d incidents, rain verdict '%s'", len(alerts), len(incidents), rain_result["verdict"])
    _print_summary(alerts, incidents, rain_result)
    norain_levels = results[RAIN_VARIANT][0]["alert_level"].value_counts().to_dict()
    print(f"Rain-toggle view (M1_norain): confirmed={norain_levels.get('confirmed', 0)} "
          f"possible={norain_levels.get('possible', 0)} incidents={len(results[RAIN_VARIANT][1])}")

    return {
        "detector_alerts": config.DETECTOR_ALERTS_PATH,
        "detector_incidents": config.DETECTOR_INCIDENTS_PATH,
        "detector_sensitivity": config.DETECTOR_SENSITIVITY_PATH,
        "detector_rain": config.DETECTOR_RAIN_PATH,
    }


if __name__ == "__main__":
    run()
