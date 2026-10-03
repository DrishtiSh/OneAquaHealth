"""Stage 7 inputs and fact sheets.

`load_inputs()` is the only place Stage 7 reads pipeline data (Stages 1-6 outputs; never the
simulator's hidden truth). A `FactSheet` records every value a finding displays, together with
where it came from, so the text can be audited and fact-locked.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd

from pipeline.common import config, io_utils
from pipeline.nlg import templates


@dataclass
class FactSheet:
    """Registry of displayed values for one finding: {name: {"value", "shown", "source"}}."""

    language: str = "en"
    facts: dict[str, dict] = field(default_factory=dict)

    def show(self, name: str, value: Any, shown: str, source: str) -> str:
        self.facts[name] = {"value": _jsonable(value), "shown": shown, "source": source}
        return shown

    def num(self, name: str, value: float, source: str, digits: int = 0) -> str:
        return self.show(name, value, f"{value:.{digits}f}", source)

    def count(self, name: str, value: int, source: str) -> str:
        return self.show(name, int(value), str(int(value)), source)

    def pct(self, name: str, fraction: float, source: str) -> str:
        return self.show(name, fraction, f"{100 * fraction:.0f}", source)

    def when(self, name: str, start: date, end: date, source: str) -> str:
        s, e = self.date(f"{name}_start", start, source), self.date(f"{name}_end", end, source)
        if start == end:
            return templates.t(self.language, "when_single", start=s)
        return templates.t(self.language, "when_range", start=s, end=e)

    def date(self, name: str, value: date, source: str) -> str:
        shown = templates.t(self.language, "date", day=value.day, month=value.strftime("%b"), year=value.year)
        return self.show(name, value, shown, source)

    def site(self, name: str, site_id: str, site_name: str, source: str = "sites.parquet:name") -> str:
        return self.show(name, site_id, site_name, source)

    def shown_values(self) -> list[str]:
        return [f["shown"] for f in self.facts.values()]

    def to_json(self) -> str:
        return json.dumps(self.facts, sort_keys=True)


def _jsonable(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "item"):  # numpy scalar
        return value.item()
    return value


def join_names(language: str, names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    sep, conj = templates.TEMPLATES[language]["list_sep"], templates.TEMPLATES[language]["and"]
    return f"{sep.join(names[:-1])} {conj} {names[-1]}"


@dataclass(frozen=True)
class NlgInputs:
    sites: pd.DataFrame  # indexed by site_id, ordered head -> mouth: name, is_cso_outfall_adjacent
    upstream_of: dict[str, list[str]]  # immediate upstream neighbours per site (river graph)
    exposure: pd.DataFrame  # Stage 4 exposure_features
    scores: pd.DataFrame  # Stage 5 M1 scores
    alerts: pd.DataFrame  # Stage 6 detector_alerts
    incidents: pd.DataFrame  # Stage 6 detector_incidents
    rain: dict  # Stage 6 detector_rain.json
    weeks: list[date]

    @property
    def latest_week(self) -> date:
        return self.weeks[-1]

    def site_name(self, site_id: str) -> str:
        return str(self.sites.loc[site_id, "name"])


def _dates(df: pd.DataFrame, *cols: str) -> pd.DataFrame:
    return df.assign(**{c: pd.to_datetime(df[c]).dt.date for c in cols})


def build_inputs(
    sites: pd.DataFrame,
    edges: pd.DataFrame,
    exposure: pd.DataFrame,
    scores: pd.DataFrame,
    alerts: pd.DataFrame,
    incidents: pd.DataFrame,
    rain: dict,
) -> NlgInputs:
    """Pure (no disk access) so tests can pass small hand-made frames."""
    ordered = sites.sort_values("distance_from_mouth_m", ascending=False).set_index("site_id")
    upstream: dict[str, list[str]] = {s: [] for s in ordered.index}
    for _, e in edges.iterrows():
        upstream[e["to_site_id"]].append(e["from_site_id"])
    scores = _dates(scores, "week_start")
    return NlgInputs(
        sites=ordered,
        upstream_of=upstream,
        exposure=exposure,
        scores=scores,
        alerts=_dates(alerts, "week_start"),
        incidents=_dates(incidents, "start_week", "end_week") if len(incidents) else incidents,
        rain=rain,
        weeks=sorted(scores["week_start"].unique()),
    )


def load_inputs() -> NlgInputs:
    paths = {
        "sites": (config.SITES_PATH, "1 (ingestion)"),
        "edges": (config.RIVER_GRAPH_EDGES_PATH, "3 (river graph)"),
        "exposure": (config.EXPOSURE_FEATURES_PATH, "4 (exposure)"),
        "scores": (config.MODEL_SCORES_PATH, "5 (model)"),
        "alerts": (config.DETECTOR_ALERTS_PATH, "6 (detectors)"),
        "incidents": (config.DETECTOR_INCIDENTS_PATH, "6 (detectors)"),
        "rain": (config.DETECTOR_RAIN_PATH, "6 (detectors)"),
    }
    for path, stage in paths.values():
        if not path.exists():
            raise FileNotFoundError(f"{path} not found -- run Stage {stage} first.")
    frames = {k: io_utils.read_parquet(p) for k, (p, _) in paths.items() if k != "rain"}
    return build_inputs(**frames, rain=json.loads(config.DETECTOR_RAIN_PATH.read_text()))
