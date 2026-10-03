"""Stage 8: Freeze a snapshot - all heavy computation happens offline into one static DuckDB file, so the live app doesn't need to recompute anything.

Freeze only copies and verifies: every number in the snapshot was computed by Stages 1-7.
Reshaping (concatenating variants, de-duplicating the site-invariant weather, de-identifying
reports) is the only transformation here, so the snapshot can't disagree with the pipeline.

Order of operations:
  1. load Stage 1-7 outputs (never the simulator's hidden truth, never the posterior draws)
  2. validate each against its pydantic schema, then cross-check consistency (one week grid,
     known sites, resolvable references, unique keys, passed diagnostics, no truth columns,
     de-identified reports) -- any failure raises before a file is touched
  3. build into `<snapshot>.tmp` in a storage format the API's older DuckDB can read, add views
     and comments, reopen read-only and re-check, then atomically replace the old snapshot
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow as pa

from pipeline.common import config, io_utils, schema
from pipeline.detectors.rain import rain_exposure
from pipeline.model.bayesian_model import variant_path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

PRIMARY_VARIANT, RAIN_VARIANT = "M1", "M1_norain"
VARIANTS = (PRIMARY_VARIANT, RAIN_VARIANT)
# Storage format the API's `duckdb` npm package (1.4.x) can open; Python writes with 1.5.x.
STORAGE_VERSION = "v1.0.0"
# Report fields that could identify a volunteer, or that are ingestion metadata.
DEID_DROP_COLUMNS = ("observer_id", "raw_payload", "ingested_at", "observed_at")
WEATHER_COLUMNS = ("weekly_rainfall_mm", "max_daily_rainfall_mm", "rain_days_count",
                   "antecedent_rainfall_mm_3wk", "heavy_rain_week", "source")


class SnapshotError(RuntimeError):
    """Raised when inputs are inconsistent or the written snapshot fails its read-back check."""


# ----------------------------------------------------------------------------- inputs


def input_files() -> dict[str, Path]:
    """Every file the snapshot is built from (all produced by Stages 1-7)."""
    files = {
        "sites": config.SITES_PATH,
        "observations": config.OBSERVATIONS_PATH,
        "weather": config.WEATHER_FEATURES_PATH,
        "river_edges": config.RIVER_GRAPH_EDGES_PATH,
        "exposure": config.EXPOSURE_FEATURES_PATH,
        "exposure_weights": config.SITE_EXPOSURE_WEIGHTS_PATH,
        "sensitivity": config.DETECTOR_SENSITIVITY_PATH,
        "rain": config.DETECTOR_RAIN_PATH,
        "findings": config.FINDINGS_PATH,
    }
    for v in VARIANTS:
        files[f"scores__{v}"] = variant_path(config.MODEL_SCORES_PATH, v)
        files[f"params__{v}"] = variant_path(config.MODEL_PARAMS_PATH, v)
        files[f"diagnostics__{v}"] = variant_path(config.MODEL_DIAG_PATH, v)
        files[f"alerts__{v}"] = variant_path(config.DETECTOR_ALERTS_PATH, v)
        files[f"incidents__{v}"] = variant_path(config.DETECTOR_INCIDENTS_PATH, v)
    # Optional: Stage 11's report exists only when there was simulator ground truth to score against.
    if config.BENCHMARK_REPORT_PATH.exists():
        files["benchmark"] = config.BENCHMARK_REPORT_PATH
    return files


@dataclass(frozen=True)
class RawInputs:
    frames: dict[str, pd.DataFrame]
    json_docs: dict[str, dict]
    hashes: dict[str, str]  # label -> sha256 of the file bytes
    paths: dict[str, Path]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_raw_inputs(files: dict[str, Path] | None = None) -> RawInputs:
    files = files or input_files()
    missing = [f"{label}: {p}" for label, p in files.items() if not p.exists()]
    if missing:
        raise FileNotFoundError("Snapshot inputs missing -- run Stages 1-7 first:\n  " + "\n  ".join(missing))
    frames, docs = {}, {}
    for label, path in files.items():
        if path.suffix == ".json":
            docs[label] = json.loads(path.read_text())
        else:
            frames[label] = io_utils.read_parquet(path)
    return RawInputs(frames, docs, {label: _sha256(p) for label, p in files.items()}, dict(files))


# ----------------------------------------------------------------------------- validation


def _as_date(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s).dt.date


def validate_inputs(raw: RawInputs) -> None:
    """Schema checks on every input, row by row, with the Stage 1-7 pydantic contracts."""
    f = raw.frames
    checks = [("sites", schema.Site), ("observations", schema.Observation), ("weather", schema.WeatherWeek),
              ("river_edges", schema.RiverGraphEdge), ("exposure", schema.ExposureFeature),
              ("sensitivity", schema.AlertSensitivity), ("findings", schema.Finding)]
    checks += [(f"{kind}__{v}", model) for v in VARIANTS
               for kind, model in (("scores", schema.ModelScore), ("alerts", schema.DetectorAlert),
                                   ("incidents", schema.Incident))]
    for label, model in checks:
        try:
            schema.validate_dataframe(f[label], model, name=label)
        except ValueError as exc:
            raise SnapshotError(str(exc)) from exc


def verify_tables(tables: dict[str, pd.DataFrame], raw: RawInputs) -> None:
    """Cross-table consistency, model health, truth firewall and de-identification."""
    problems: list[str] = []

    # Truth firewall: no hidden-truth column may reach the live app.
    for name, df in tables.items():
        leaked = schema.GROUND_TRUTH_ONLY_COLUMNS.intersection(df.columns)
        if leaked:
            problems.append(f"table {name} carries ground-truth columns {sorted(leaked)}")

    # De-identification.
    kept = set(DEID_DROP_COLUMNS).intersection(tables["observations"].columns)
    if kept:
        problems.append(f"observations still carries identifying/metadata columns {sorted(kept)}")

    # Model health: never freeze results from a fit that failed its convergence gate.
    for v in VARIANTS:
        if not raw.json_docs[f"diagnostics__{v}"].get("passed", False):
            problems.append(f"model {v} failed its convergence gate -- refusing to freeze its results")

    # One week grid everywhere.
    grid = set(tables["weeks"]["week_start"])
    for name in ("scores", "alerts", "alert_sensitivity"):
        if set(tables[name]["week_start"]) != grid:
            problems.append(f"table {name} is on a different week grid than the weather (re-run Stages 5-7)")
    for name, cols in (("incidents", ("start_week", "end_week")), ("findings", ("week_start", "week_end"))):
        for col in cols:
            outside = set(tables[name][col]) - grid
            if outside:
                problems.append(f"table {name}.{col} has weeks outside the grid: {sorted(outside)[:3]}")

    # Known sites everywhere.
    sites = set(tables["sites"]["site_id"])
    for name in ("site_exposure", "scores", "alerts", "alert_sensitivity", "observations"):
        unknown = set(tables[name]["site_id"]) - sites
        if unknown:
            problems.append(f"table {name} references unknown sites {sorted(unknown)}")
    edge_sites = set(tables["river_edges"]["from_site_id"]) | set(tables["river_edges"]["to_site_id"])
    if edge_sites - sites:
        problems.append(f"river_edges references unknown sites {sorted(edge_sites - sites)}")
    for _, inc in tables["incidents"].iterrows():
        refs = set(inc["affected_site_ids"]) | set(inc["credible_set"]) | ({inc["top_source"]} if inc["top_source"] else set())
        if refs - sites:
            problems.append(f"incident {inc['incident_id']} references unknown sites {sorted(refs - sites)}")

    # Findings must point at things that exist.
    f = tables["findings"]
    primary_incidents = set(tables["incidents"].query("model_variant == @PRIMARY_VARIANT")["incident_id"])
    bad_inc = set(f.query("finding_type == 'incident'")["scope_id"]) - primary_incidents
    bad_site = set(f.query("finding_type == 'site_status'")["scope_id"]) - sites
    if bad_inc or bad_site:
        problems.append(f"findings reference missing incidents {sorted(bad_inc)} / sites {sorted(bad_site)}")

    # Both toggle states present.
    for name in ("scores", "alerts", "incidents", "alert_sensitivity"):
        missing = set(VARIANTS) - set(tables[name]["model_variant"])
        if missing:
            problems.append(f"table {name} lacks model variants {sorted(missing)}")
    levels = set(config.SENSITIVITY_DELTAS) - set(tables["alert_sensitivity"]["sensitivity"])
    if levels:
        problems.append(f"alert_sensitivity lacks levels {sorted(levels)}")

    # A benchmark report must describe these very results, not an earlier run.
    if "benchmark" in tables:
        b = raw.json_docs["benchmark"]["data"]
        if (b["first_week"], b["latest_week"], b["n_sites"]) != (str(min(grid)), str(max(grid)), len(sites)):
            problems.append("benchmark_report.json is out of date with these results -- re-run Stage 11 "
                            "(python -m pipeline.benchmark.benchmark)")

    # Unique keys.
    keys = {
        "sites": ["site_id"], "weeks": ["week_start"], "site_exposure": ["site_id", "category"],
        "scores": ["model_variant", "site_id", "week_start"], "alerts": ["model_variant", "site_id", "week_start"],
        "alert_sensitivity": ["model_variant", "site_id", "week_start", "sensitivity"],
        "incidents": ["model_variant", "incident_id"], "findings": ["finding_id"], "observations": ["observation_id"],
        "rain_pattern": ["grp"], "model_diagnostics": ["model_variant"], "model_params": ["model_variant", "param"],
    }
    for name, cols in keys.items():
        dup = tables[name].duplicated(subset=cols).sum()
        if dup:
            problems.append(f"table {name} has {dup} duplicate keys on {cols}")

    if problems:
        raise SnapshotError("Refusing to freeze:\n  - " + "\n  - ".join(problems))


# ----------------------------------------------------------------------------- building tables


def _weeks_table(weather: pd.DataFrame) -> pd.DataFrame:
    """One row per week. Rainfall is identical across sites (same Open-Meteo grid cell); verify
    that before collapsing, rather than silently picking one site."""
    w = weather.assign(week_start=_as_date(weather["week_start"]))
    varying = [c for c in WEATHER_COLUMNS if (w.groupby("week_start")[c].nunique() > 1).any()]
    if varying:
        raise SnapshotError(f"weather differs across sites for {varying}; the snapshot's weeks table assumes it doesn't")
    weeks = w.groupby("week_start", as_index=False)[list(WEATHER_COLUMNS)].first().sort_values("week_start")
    weeks["rain_exposed"] = rain_exposure(weeks["heavy_rain_week"].to_numpy(dtype=float))  # Stage 6's lag rule
    return weeks.rename(columns={"source": "weather_source"}).reset_index(drop=True)


def _deidentify(obs: pd.DataFrame) -> pd.DataFrame:
    out = obs.assign(observed_date=pd.to_datetime(obs["observed_at"]).dt.date, week_start=_as_date(obs["week_start"]))
    return out.drop(columns=[c for c in DEID_DROP_COLUMNS if c in out.columns])


def _rain_table(rain: dict) -> pd.DataFrame:
    shared = {
        "model_variant": rain["model_variant"],
        "overall_verdict": rain["verdict"],
        "delta_W": rain["thresholds"]["delta_W"],
        "rain_lag_weeks": rain["thresholds"]["rain_lag_weeks"],
        "n_rain_exposed_weeks": rain["n_rain_exposed_weeks"],
        "n_rain_exposed_weeks_with_reports": rain["n_rain_exposed_weeks_with_reports"],
        "n_placebo_shifts": rain["n_placebo_shifts"],
        "sewage_share_rain_weeks": (rain.get("sewage_smell_share") or {}).get("rain_weeks"),
        "sewage_share_dry_weeks": (rain.get("sewage_smell_share") or {}).get("dry_weeks"),
        "corroboration_json": json.dumps(rain.get("corroboration_beta_rain"), sort_keys=True),
    }
    return pd.DataFrame([{"grp": g, **rain[g], **shared} for g in ("pooled", "cso_adjacent", "other_sites")])


def _benchmark_table(report: dict) -> pd.DataFrame:
    """One row: Stage 11's headline numbers as columns, the full report as JSON."""
    return pd.DataFrame([{
        "data_source": report["data"]["source"],
        "random_seed": report["data"]["seed"],
        **report["headline"],
        "report_json": json.dumps(report, sort_keys=True),
    }])


def _diagnostics_table(docs: dict[str, dict]) -> pd.DataFrame:
    rows = []
    for v in VARIANTS:
        d = dict(docs[f"diagnostics__{v}"])
        rows.append({**{k: val for k, val in d.items() if k not in ("failures", "ppc")},
                     "model_variant": v, "failures_json": json.dumps(d.get("failures", [])),
                     "ppc_json": json.dumps(d.get("ppc", {}), sort_keys=True)})
    return pd.DataFrame(rows)


def build_tables(raw: RawInputs) -> dict[str, pd.DataFrame]:
    """Reshape Stage 1-7 outputs into the snapshot's tables (no new numbers are computed)."""
    f = raw.frames
    both = lambda kind: pd.concat([f[f"{kind}__{v}"] for v in VARIANTS], ignore_index=True)  # noqa: E731

    sites = f["sites"].sort_values("distance_from_mouth_m", ascending=False).reset_index(drop=True)
    sites["display_order"] = range(1, len(sites) + 1)
    sites = sites.merge(f["exposure_weights"][["site_id", "exposure_weight"]], on="site_id", how="left")

    scores, alerts = both("scores"), both("alerts")
    incidents = both("incidents")
    for col in ("affected_site_ids", "credible_set"):
        incidents[col] = incidents[col].map(list)
    findings = f["findings"].assign(display_rank=range(1, len(f["findings"]) + 1),
                                    caveats=f["findings"]["caveats"].map(list))

    tables = {
        "sites": sites,
        "site_exposure": f["exposure"],
        "river_edges": f["river_edges"],
        "weeks": _weeks_table(f["weather"]),
        "scores": scores.assign(week_start=_as_date(scores["week_start"])),
        "alerts": alerts.assign(week_start=_as_date(alerts["week_start"])),
        "alert_sensitivity": f["sensitivity"].assign(week_start=_as_date(f["sensitivity"]["week_start"])),
        "incidents": incidents.assign(start_week=_as_date(incidents["start_week"]), end_week=_as_date(incidents["end_week"])),
        "rain_pattern": _rain_table(raw.json_docs["rain"]),
        "findings": findings.assign(week_start=_as_date(findings["week_start"]), week_end=_as_date(findings["week_end"])),
        "model_params": both("params"),
        "model_diagnostics": _diagnostics_table(raw.json_docs),
        "observations": _deidentify(f["observations"]),
    }
    if "benchmark" in raw.json_docs:
        tables["benchmark"] = _benchmark_table(raw.json_docs["benchmark"])
    return tables


def _git_commit() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=config.REPO_ROOT, capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def snapshot_id(raw: RawInputs) -> str:
    """Content address: identical inputs + schema version -> identical id."""
    h = hashlib.sha256(f"schema={config.SNAPSHOT_SCHEMA_VERSION}".encode())
    for label in sorted(raw.hashes):
        h.update(f"{label}={raw.hashes[label]}".encode())
    return h.hexdigest()[:16]


def build_manifest(raw: RawInputs, tables: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    weeks = tables["weeks"]["week_start"]
    thresholds = {
        "DETECT_DELTA": config.DETECT_DELTA, "P_CONFIRMED": config.P_CONFIRMED, "P_POSSIBLE": config.P_POSSIBLE,
        "SENSITIVITY_DELTAS": config.SENSITIVITY_DELTAS, "INCIDENT_WINDOW_WEEKS": config.INCIDENT_WINDOW_WEEKS,
        "INCIDENT_MAX_HOPS": config.INCIDENT_MAX_HOPS, "SOURCE_CREDIBLE_MASS": config.SOURCE_CREDIBLE_MASS,
        "RAIN_LAG_WEEKS": config.RAIN_LAG_WEEKS, "EXPOSURE_RADIUS_M": config.EXPOSURE_RADIUS_M,
        "VERBAL_PROBABILITY": config.VERBAL_PROBABILITY, "SEVERITY_BANDS": config.SEVERITY_BANDS,
        "RECENT_WEEKS": config.RECENT_WEEKS,
    }
    manifest = {
        "snapshot_id": snapshot_id(raw),
        "schema_version": str(config.SNAPSHOT_SCHEMA_VERSION),
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git_commit() or "",
        "anchor_date": os.environ.get("OAH_ANCHOR_DATE") or config.DEFAULT_ANCHOR_DATE,
        "first_week": str(weeks.min()),
        "latest_week": str(weeks.max()),
        "n_weeks": str(len(weeks)),
        "random_seed": str(config.RANDOM_SEED),
        "primary_variant": PRIMARY_VARIANT,
        "rain_variant": RAIN_VARIANT,
        "thresholds_json": json.dumps(thresholds, sort_keys=True),
        **{f"diagnostics_passed__{v}": str(raw.json_docs[f"diagnostics__{v}"]["passed"]).lower() for v in VARIANTS},
        "disclaimer": "Based on volunteer observations, not laboratory tests. Not an official health advisory.",
    }
    manifest_df = pd.DataFrame({"key": list(manifest), "value": list(manifest.values())})
    inputs_df = pd.DataFrame([
        {"label": label, "path": str(raw.paths[label].relative_to(config.REPO_ROOT)) if raw.paths[label].is_relative_to(config.REPO_ROOT) else str(raw.paths[label]),
         "sha256": raw.hashes[label],
         "n_rows": len(raw.frames[label]) if label in raw.frames else None}
        for label in sorted(raw.hashes)
    ])
    return manifest_df, inputs_df


# ----------------------------------------------------------------------------- writing

TABLE_COMMENTS = {
    "snapshot_manifest": "Key/value facts about this snapshot: id, schema version, week range, thresholds, model health.",
    "snapshot_inputs": "Provenance: every pipeline file this snapshot was built from, with its sha256.",
    "sites": "Monitored spots on the Gowanus Canal, ordered head (1) to mouth; exposure_weight is a static proximity score.",
    "site_exposure": "Nearest playground/school/park per site from OpenStreetMap; data_source='unavailable' means unknown, not none.",
    "river_edges": "Directed river graph: from_site_id is directly upstream of to_site_id.",
    "weeks": "One row per week: rainfall (identical across sites) and whether the week counts as rain-exposed.",
    "scores": "Posterior W (water quality, higher=cleaner) and H (hazard, higher=riskier): relative 0-100 indices, not lab measurements. Both model variants.",
    "alerts": "Change detection at the normal sensitivity: P(W dropped by more than the threshold) per site-week, both model variants.",
    "alert_sensitivity": "Dashboard sensitivity toggle: p_change and alert_level at each precomputed change size.",
    "incidents": "Linked change episodes with a posterior over the entry point, at normal sensitivity, both model variants.",
    "rain_pattern": "Rain -> overflow test from the no-rain model (not circular); an association, not proof of cause.",
    "findings": "Plain-language, fact-locked findings (primary model, normal sensitivity); facts_json holds every number shown.",
    "model_params": "Posterior summaries of model parameters, per variant.",
    "model_diagnostics": "Convergence and posterior-predictive checks, per variant; a snapshot is only frozen if both passed.",
    "observations": "De-identified citizen reports: no observer id, raw payload or time of day. water_clarity: 1=clear, 5=murky.",
    "benchmark": "Stage 11 evaluation against the simulator's ground truth (simulated data only): headline accuracy plus "
                 "report_json with every true event, miss and false alarm. Truth-derived; never fed back into any result.",
}

VIEWS = {
    "v_site_latest": """
        SELECT s.site_id, s.name, s.display_order, s.lat, s.lon, s.is_cso_outfall_adjacent, s.exposure_weight,
               sc.model_variant, sc.week_start, sc.W_mean, sc.W_q05, sc.W_q50, sc.W_q95,
               sc.H_mean, sc.H_q05, sc.H_q50, sc.H_q95, sc.evidence, sc.mixing_flag, sc.n_reports,
               a.p_change, a.alert_level, f.headline AS status_headline, f.body AS status_body
        FROM sites s
        JOIN scores sc ON sc.site_id = s.site_id AND sc.week_start = (SELECT max(week_start) FROM weeks)
        LEFT JOIN alerts a ON a.site_id = sc.site_id AND a.week_start = sc.week_start AND a.model_variant = sc.model_variant
        LEFT JOIN findings f ON f.finding_type = 'site_status' AND f.scope_id = s.site_id AND f.model_variant = sc.model_variant
    """,
    "v_site_timeseries": """
        SELECT sc.model_variant, sc.site_id, s.name, sc.week_start,
               sc.W_q05, sc.W_q50, sc.W_q95, sc.H_q05, sc.H_q50, sc.H_q95, sc.evidence, sc.mixing_flag, sc.n_reports,
               a.p_change, a.alert_level, a.episode_id, w.weekly_rainfall_mm, w.heavy_rain_week, w.rain_exposed
        FROM scores sc
        JOIN sites s USING (site_id)
        JOIN weeks w USING (week_start)
        LEFT JOIN alerts a ON a.site_id = sc.site_id AND a.week_start = sc.week_start AND a.model_variant = sc.model_variant
    """,
    "v_findings_ranked": """
        SELECT display_rank, finding_id, finding_type, scope_id, priority, is_recent, confidence_label,
               week_start, week_end, headline, body, precaution, caveats, facts_json, language, model_variant
        FROM findings
        ORDER BY display_rank
    """,
    "v_incidents": """
        SELECT i.*, s.name AS top_source_name
        FROM incidents i
        LEFT JOIN sites s ON s.site_id = i.top_source
    """,
}


def _int32(df: pd.DataFrame) -> pd.DataFrame:
    """Store integers as 32-bit INTEGER: Node's duckdb returns BIGINT as JS BigInt, which
    JSON.stringify can't serialise. All counts here are small; out-of-range values raise."""
    cols = list(df.select_dtypes("int64").columns)
    for c in cols:
        if len(df) and (df[c].abs().max() >= 2**31):
            raise SnapshotError(f"column {c} has values too large for INTEGER")
    return df.astype({c: "int32" for c in cols})


def write_snapshot(tables: dict[str, pd.DataFrame], path: Path) -> None:
    """Build into a temp file, re-check it read-only, then atomically replace `path`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    try:
        con = duckdb.connect()
        try:
            con.execute(f"ATTACH '{tmp.as_posix()}' AS snap (STORAGE_VERSION '{STORAGE_VERSION}')")
            con.execute("USE snap")
            for name, df in tables.items():
                con.register("_src", pa.Table.from_pandas(_int32(df), preserve_index=False))
                con.execute(f"CREATE TABLE {name} AS SELECT * FROM _src")
                con.unregister("_src")
                comment = TABLE_COMMENTS[name].replace("'", "''")  # COMMENT ON takes a literal, not a parameter
                con.execute(f"COMMENT ON TABLE {name} IS '{comment}'")
            for name, sql in VIEWS.items():
                con.execute(f"CREATE VIEW {name} AS {sql}")
            con.execute("CHECKPOINT")
        finally:
            con.close()
        _read_back_check(tmp, tables)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _read_back_check(path: Path, tables: dict[str, pd.DataFrame]) -> None:
    con = duckdb.connect(str(path), read_only=True)
    try:
        for name, df in tables.items():
            n = con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
            if n != len(df):
                raise SnapshotError(f"read-back: table {name} has {n} rows, expected {len(df)}")
        for name in VIEWS:
            con.execute(f"SELECT count(*) FROM {name}").fetchone()
    finally:
        con.close()


# ----------------------------------------------------------------------------- entry point


def freeze(output_path: Path | None = None, files: dict[str, Path] | None = None) -> dict:
    output_path = output_path or config.SNAPSHOT_PATH
    raw = load_raw_inputs(files)
    validate_inputs(raw)
    tables = build_tables(raw)
    verify_tables(tables, raw)
    manifest, inputs = build_manifest(raw, tables)
    tables = {"snapshot_manifest": manifest, "snapshot_inputs": inputs, **tables}
    write_snapshot(tables, output_path)
    sid = manifest.set_index("key").loc["snapshot_id", "value"]
    return {"path": output_path, "snapshot_id": sid, "row_counts": {k: len(v) for k, v in tables.items()}}


def run() -> dict[str, Path]:
    result = freeze()
    print("--- Stage 8 snapshot summary ---")
    print(f"Snapshot {result['snapshot_id']} -> {result['path']} ({result['path'].stat().st_size / 1e6:.2f} MB)")
    for name, n in result["row_counts"].items():
        print(f"  {name:20s} {n:6d} rows")
    print(f"  views: {', '.join(VIEWS)}")
    print("---------------------------------")
    return {"snapshot": result["path"]}


if __name__ == "__main__":
    run()
