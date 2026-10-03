"""Adapter for a real OAH API / FHIR-records data source.

What actually exists (checked 2026-10-03; re-check any time with `npm run oah-check`,
i.e. `python -m pipeline.ingestion.oah_probe`):

  * OAH data API, base https://api.enora-oah.eu/api (the service behind the OAH Resilience Map).
    - Public, no key: /cities/all (5 EU cities), /sites/all (106 research sites),
      /resilience-map/health-risks (one lab pathogen/fecal/ARG sample per site, mostly 2023),
      /resilience-map/urban-parameters. None of this is repeated citizen reporting, and none of
      it covers the Gowanus Canal sites this build simulates.
    - Citizen checks from the OAH app live under /citizens/... and answer 401: they need
      credentials (other hackathon teams also report they are not public).
  * OAH FHIR sandbox (HL7 Europe, HAPI R4): https://sandbox.hl7europe.eu/oneaquahealth/fhir
    - Public: Locations, lab chemistry / air / population-health Observations. The "survey"
      Observations and QuestionnaireResponses there are other teams' demo uploads (meta tags
      `demo`, `brook-citizen-check`), not genuine citizen data.

So the simulator stays Stage 1's input until a citizen-API token is available (ask the OAH /
hackathon organisers). With OAH_API_BASE_URL=https://api.enora-oah.eu/api and OAH_API_TOKEN
set, run the probe first: it prints the real record fields, and the mapping below must be
checked against them -- the endpoint path, pagination and field names here are still a
best guess written before any real record was seen.

Assumed contract (UNVERIFIED until a token works):
    GET {base_url}/observations?since=YYYY-MM-DD&until=YYYY-MM-DD&page=N
    Headers: Authorization: Bearer {api_token}          (if a token is set)
    Response: {"results": [<record>, ...], "next_page": N | null}

    <record> field mapping -> canonical `Observation` columns:
        record["id"]                -> observation_id
        record["site_id"]           -> site_id
        record["reported_at"]       -> observed_at
        record["reporter_id"]       -> observer_id
        record["water_clarity"]     -> water_clarity      (1-5)
        record["smell"]             -> smell
        record["smell_intensity"]   -> smell_intensity
        record["trash_level"]       -> trash_level
        record["insect_presence"]   -> insect_presence
        record["insect_diversity"]  -> insect_diversity
        record["notes"]             -> notes
    `week_start` is derived from `observed_at` (Monday-aligned), `source` is
    always set to "real", and the original JSON record is kept verbatim in
    `raw_payload` for auditability.

    A future FHIR-bundle source would need its own mapping (FHIR Observation
    resources don't line up 1:1 with these fields) -- not implemented here to
    avoid building against an imaginary spec.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pandas as pd
import requests

from pipeline.common import config


class OAHNotConfiguredError(RuntimeError):
    """Raised when real-source ingestion is explicitly requested but not configured."""


def is_configured() -> bool:
    import os

    return bool(os.environ.get(config.OAH_API_BASE_URL_ENV))


def _week_start(dt: datetime) -> date:
    d = dt.date()
    return d - timedelta(days=d.weekday())


def _record_to_row(record: dict) -> dict:
    observed_at = pd.to_datetime(record["reported_at"]).to_pydatetime()
    return {
        "observation_id": str(record["id"]),
        "site_id": str(record["site_id"]),
        "observed_at": observed_at,
        "week_start": _week_start(observed_at),
        "observer_id": str(record.get("reporter_id", "unknown")),
        "water_clarity": record.get("water_clarity"),
        "smell": record.get("smell"),
        "smell_intensity": record.get("smell_intensity"),
        "trash_level": record.get("trash_level"),
        "insect_presence": record.get("insect_presence"),
        "insect_diversity": record.get("insect_diversity"),
        "notes": record.get("notes"),
        "source": "real",
        "ingested_at": datetime.now(),
        "raw_payload": json.dumps(record),
    }


def fetch_real_observations(
    base_url: str,
    api_token: str | None,
    since: date,
    until: date | None = None,
    timeout_s: float = 15.0,
) -> pd.DataFrame:
    """Fetches real observations matching the Observation schema (source="real").

    Raises OAHNotConfiguredError if base_url is falsy.
    """
    if not base_url:
        raise OAHNotConfiguredError(
            f"{config.OAH_API_BASE_URL_ENV} is not set -- no real OAH API is configured."
        )

    headers = {"Authorization": f"Bearer {api_token}"} if api_token else {}
    params = {"since": since.isoformat()}
    if until:
        params["until"] = until.isoformat()

    rows: list[dict] = []
    page = 0
    while True:
        resp = requests.get(
            f"{base_url.rstrip('/')}/observations",
            params={**params, "page": page},
            headers=headers,
            timeout=timeout_s,
        )
        resp.raise_for_status()
        payload = resp.json()
        rows.extend(_record_to_row(r) for r in payload.get("results", []))
        next_page = payload.get("next_page")
        if next_page is None:
            break
        page = next_page

    return pd.DataFrame(rows)
