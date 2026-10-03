"""Read-only check of which real OneAquaHealth data sources this machine can reach.

    python -m pipeline.ingestion.oah_probe        (or: npm run oah-check)

Why it exists: Stage 1 wants real citizen observations, but the OAH app's citizen API needs
credentials. This probe shows, in one run, what is public, what is locked, and -- once
OAH_API_TOKEN is set -- what a real citizen record looks like, so the adapter in real_source.py
can be written against the real payload instead of a guess. It never writes anything.
"""

from __future__ import annotations

import os
from collections import Counter

import requests
from dotenv import load_dotenv

from pipeline.common import config

ENORA_BASE = "https://api.enora-oah.eu/api"
FHIR_BASE = "https://sandbox.hl7europe.eu/oneaquahealth/fhir"
PUBLIC_ENORA = ("cities/all", "sites/all", "resilience-map/health-risks", "resilience-map/urban-parameters")
CITIZEN_PATHS = ("citizens", "citizens/observations")
# Tags other hackathon teams put on their test uploads to the shared sandbox.
DEMO_TAGS = {"demo", "brook-citizen-check", "second-look"}
TIMEOUT_S = 30


def _get(url: str, **kw) -> requests.Response | None:
    try:
        return requests.get(url, timeout=TIMEOUT_S, **kw)
    except requests.RequestException as exc:
        print(f"  {url}: unreachable ({exc.__class__.__name__})")
        return None


def probe_enora(token: str | None) -> None:
    print(f"OAH data API: {ENORA_BASE}")
    for path in PUBLIC_ENORA:
        res = _get(f"{ENORA_BASE}/{path}")
        if res is not None:
            size = len(res.json()) if res.ok and isinstance(res.json(), list) else "-"
            print(f"  GET /{path:34s} {res.status_code}  records: {size}")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    for path in CITIZEN_PATHS:
        res = _get(f"{ENORA_BASE}/{path}", headers=headers)
        if res is None:
            continue
        note = {401: "needs credentials", 403: "token not allowed"}.get(res.status_code, "")
        print(f"  GET /{path:34s} {res.status_code}  {note}{' (sent OAH_API_TOKEN)' if token else ''}")
        if res.ok:
            body = res.json()
            first = body[0] if isinstance(body, list) and body else body
            print(f"    first record fields: {sorted(first) if isinstance(first, dict) else type(first).__name__}")


def probe_fhir() -> None:
    print(f"OAH FHIR sandbox (HL7 Europe): {FHIR_BASE}")
    headers = {"Accept": "application/fhir+json"}
    for rtype in ("Location", "Observation", "QuestionnaireResponse"):
        res = _get(f"{FHIR_BASE}/{rtype}", params={"_summary": "count"}, headers=headers)
        if res is not None and res.ok:
            print(f"  {rtype:22s} {res.json().get('total')}")
    res = _get(f"{FHIR_BASE}/Observation", params={"category": "survey", "_count": 200}, headers=headers)
    if res is None or not res.ok:
        return
    entries = [e["resource"] for e in res.json().get("entry", [])]
    tags = Counter(t.get("code") for o in entries for t in o.get("meta", {}).get("tag", []))
    places = {o.get("subject", {}).get("reference") for o in entries}
    demo = sum(n for tag, n in tags.items() if tag in DEMO_TAGS)
    print(f"  survey Observations (first page): {len(entries)} at {len(places)} location(s); "
          f"{demo} tagged as other teams' demo uploads {dict(tags)} -- not genuine citizen data")


def main() -> None:
    load_dotenv()
    token = os.environ.get(config.OAH_API_TOKEN_ENV)
    print("--- OneAquaHealth real-data check (read-only) ---")
    probe_enora(token)
    probe_fhir()
    print("Verdict: real citizen checks need an OAH API token (set OAH_API_TOKEN and re-run);")
    print("the public data is lab/air/health indicators for 5 EU cities, not repeated citizen reports.")
    print("--------------------------------------------------")


if __name__ == "__main__":
    main()
