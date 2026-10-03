"""Stage 7: Translate detected issues and exposure data into human-readable 'One Health' language findings, strictly grounded in the data (no hallucinated claims).

Deterministic, fact-locked templates (no LLM): every number in a finding traces to a recorded
fact, and overclaiming words are rejected (see factlock.py). Wording lives in templates.py.

Findings:
  * incident     -- one per Stage 6 incident: what changed, how sure we are, where it likely
                    entered, rain context, and nearby playgrounds/schools/parks (One Health).
  * site_status  -- one per site for the latest week, with an honest "not enough reports" state.
  * rain_pattern -- the network-level rain -> overflow result (from the M1_norain detector).
  * coverage     -- how much of the canal citizens actually covered, plus the standing disclaimer.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from pipeline.common import config, io_utils, schema
from pipeline.nlg import facts, render

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}
_TYPE_ORDER = {"incident": 0, "rain_pattern": 1, "site_status": 2, "coverage": 3}


def build_findings(inp: facts.NlgInputs, language: str = "en") -> pd.DataFrame:
    incidents = [render.render_incident(inp, inc, language) for _, inc in inp.incidents.iterrows()]

    # Sites in a recent incident get a pointer to it from their status card.
    recent = {}
    for f, (_, inc) in zip(incidents, inp.incidents.iterrows()):
        if f["is_recent"]:
            for sid in inc["affected_site_ids"]:
                recent.setdefault(sid, inc["incident_id"])

    rows = incidents + [render.render_rain(inp, language)]
    rows += [render.render_site_status(inp, sid, recent, language) for sid in inp.sites.index]
    rows.append(render.render_coverage(inp, language))

    df = pd.DataFrame(rows)
    df = df.assign(
        _p=df["priority"].map(_PRIORITY_ORDER),
        _t=df["finding_type"].map(_TYPE_ORDER),
        _r=~df["is_recent"],
        _w=pd.to_datetime(df["week_end"]),
    )
    df = df.sort_values(["_p", "_r", "_t", "_w", "finding_id"], ascending=[True, True, True, False, True], kind="stable")
    return df.drop(columns=["_p", "_t", "_r", "_w"]).reset_index(drop=True)


def _print_summary(df: pd.DataFrame) -> None:
    print("--- Stage 7 findings summary ---")
    print(f"Findings: {len(df)}  by type: {df['finding_type'].value_counts().to_dict()}")
    print(f"Incident priorities: {df[df.finding_type == 'incident']['priority'].value_counts().to_dict()}")
    for _, f in df.head(3).iterrows():
        print(f"  [{f['priority']}] {f['headline']}")
    print("---------------------------------")


def run() -> dict[str, Path]:
    inp = facts.load_inputs()
    df = build_findings(inp)
    schema.validate_dataframe(df, schema.Finding, name="findings")
    io_utils.write_parquet(df, config.FINDINGS_PATH)
    logger.info("Wrote %d findings to %s", len(df), config.FINDINGS_PATH)
    _print_summary(df)
    return {"findings": config.FINDINGS_PATH}


if __name__ == "__main__":
    run()
