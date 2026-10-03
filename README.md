# OneAquaHealth (OAH)

Built for the **OneAquaHealth IEEE Global Hackathon** — Track 2: Data-to-Insight.

Citizen scientists observe local streams via the OAH app: water clarity, smell, presence of
trash, insects, etc. This project turns that messy, sparse, subjective data into trustworthy
insights about stream health and potential human-health risks (sewage contamination,
disease-vector exposure), without pretending to be a validated scientific instrument.

## Pipeline (12 stages, end to end)

1. **Ingest data** — pull real observations from the OAH API/FHIR records, plus a simulator
   that generates synthetic ground-truth data for testing.
2. **Add weather context** — pull rainfall history (Open-Meteo), since rain affects runoff and
   contamination.
3. **Build a river graph** — use OpenStreetMap to figure out which sites are
   upstream/downstream of each other.
4. **Add exposure features** — find nearby playgrounds, schools, parks, etc. (OSM) where
   contamination would actually matter to people.
5. **Fit a statistical model** — a Bayesian model (PyMC, NUTS sampler) estimates two latent
   scores per site/week: W (water quality) and H (human-health-relevant risk), with
   uncertainty intervals, not point guesses.
6. **Run detectors** on top of the model — did something really change (not just noise)? Can we
   find the likely entry point of contamination upstream? Is there a rain -> sewage overflow
   pattern?
7. **Translate to "One Health" language** — combine detected issues with exposure data
   (e.g. "risk near a playground") into human-readable findings.
8. **Freeze a snapshot** — all heavy computation happens offline into one static DuckDB file, so
   the live app doesn't need to recompute anything.
9. **Insight API** — serves this snapshot, and other insight tracks can consume it too.
10. **Dashboard** — a simple UI with scenario toggles and plain-language results, with an honest
    "insufficient evidence" state when data is too sparse.
11. **Benchmark** — test the whole pipeline against the simulator's known ground truth,
    reporting real accuracy numbers (including misses), not just success stories.

### Stage 5 model notes

- `W` (water quality, higher = cleaner) and `H` (contamination hazard, higher = riskier) are
  **relative 0-100 indices anchored to the citizen rubrics** (`water_clarity` 1-5, where 1 = clear
  and 5 = murky; `smell_intensity` 0-3), not calibrated measurements. Every site-week carries
  a 90% interval and an `evidence` flag (`sufficient` / `weak` / `insufficient`).
- Variants: `M1` (primary: slow per-site drift + sparse contamination excursions, rain as a weak
  covariate), `M1_norain` (ablation for checking the rain -> overflow finding is not built in),
  `M0` (no excursions). Outputs land in `data/processed/model_*` (scores, joint posterior draws,
  parameters, diagnostics). A fit that fails the convergence gate writes diagnostics only.
- Exposure is deliberately **not** in the fit; `site_exposure_weights.parquet` is joined in Stage 7.
- Sampler: PyMC + nutpie (NUTS, numba backend). PyTensor's C++ backend is disabled
  (`cxx=`) because it does not build reliably on Windows.

### Stage 6 detector notes

- Every detector works per posterior draw, so results are probabilities, not yes/no calls.
  Thresholds are fixed in `pipeline/common/config.py` (10-point W drop; confirmed at P >= 0.9,
  possible at P >= 0.5) and were set before any comparison with the simulator's truth.
- **Change** (M1): P(the contamination excursion pulled W down by > 10 points) per site-week.
  A week with no reports, or a bimodal (mixing-flagged) posterior, can be at most "possible".
- **Entry point** (M1): nearby episodes form incidents; the source is the most upstream site
  reachable through an unbroken run of dropping sites. Output: top source, probability, 80%
  credible set, and an `upstream_unobserved` caveat when the upstream neighbour had no reports.
- **Rain -> overflow** (M1_norain, because M1 already assumes rain matters): incidence rate ratio
  in rain vs dry weeks, a shifted-rain placebo test, and raw sewage-smell shares. M1's rain
  coefficient is reported only as corroboration.

### Stage 7 findings notes

- Deterministic, **fact-locked templates** (no LLM): every number in a finding's text traces to
  an entry in its `facts_json` (value + source table), and words like "safe" or "caused" are
  rejected. The stage fails rather than publish an ungrounded sentence.
- Output `data/processed/findings.parquet`: `incident` findings (what changed, how sure, likely
  entry point, rain context, nearby playgrounds/schools/parks), `site_status` per site for the
  latest week (with a "not enough recent reports" state), one `rain_pattern`, one `coverage`
  (with the standing disclaimer: volunteer observations, not an official health advisory).
- A cautious precaution line ("avoid direct contact with the water nearby, especially children
  and dogs") appears only on confirmed incidents near a playground/school/park, or where
  exposure could not be checked.
- All wording lives in `pipeline/nlg/templates.py`, keyed by language, ready for translation.

### Stage 8 snapshot notes

- `python -m pipeline.snapshot.freeze_snapshot` packs every Stage 1-7 result the live app needs
  into `data/snapshot/oah_snapshot.duckdb` (about 5 MB, gitignored, rebuilds in seconds from the
  committed `data/processed` files). It **only copies and verifies**; no result is computed there.
- Tables: `snapshot_manifest`, `snapshot_inputs` (provenance, sha256 per input), `sites`,
  `site_exposure`, `river_edges`, `weeks`, `scores`, `alerts`, `alert_sensitivity`, `incidents`,
  `rain_pattern`, `findings`, `model_params`, `model_diagnostics`, `observations` (de-identified:
  no observer id, raw payload or time of day). Views for the API: `v_site_latest`,
  `v_site_timeseries`, `v_findings_ranked`, `v_incidents`. Every table carries a DuckDB comment.
- Dashboard toggles are precomputed in Stage 6: rain assumption on/off (`model_variant` M1 vs
  M1_norain in `scores`/`alerts`/`incidents`) and detection sensitivity (`alert_sensitivity`:
  sensitive 5 / normal 10 / strict 20 index points). Incidents use the normal level, and the
  written findings exist for the primary M1 model only.
- The freeze refuses to write if inputs disagree (week grid, unknown sites, broken references,
  duplicate keys), if either model failed its convergence gate, if any ground-truth column
  appears, or if reports are not de-identified. It builds a temp file, re-reads it, then swaps it
  in atomically, so a running API never sees a half-written snapshot.
- Written in DuckDB storage format `v1.0.0` so the API's `duckdb` 1.4.x can open it (verified).
- **Updating data:** new reports -> re-run the offline pipeline (Stages 1-8; the model fit takes
  about 6 minutes) on a schedule, e.g. weekly -> a new snapshot with a new `snapshot_id` replaces
  the old one. "No recomputation" applies to the live app only. For live data set
  `OAH_ANCHOR_DATE=today` and use real ingestion.

### Stage 9 Insight API notes

- Read-only JSON over the snapshot (`api/`, Express 5 + `duckdb`). It filters and reshapes rows
  and **computes no new numbers**. The full contract is at `GET /api/v1/openapi.json`.
- The snapshot is copied into an in-memory DuckDB at startup, so the API never holds the file
  open. Stage 8 can swap in a new snapshot while the API runs (also on Windows), and the API
  hot-reloads it (`SNAPSHOT_RELOAD_MS`). Each request stays on one snapshot from start to finish.
  A broken or unsupported file is rejected (schema version, required tables/views, both convergence
  gates) and the previous snapshot keeps serving. With no snapshot, `/health` and data routes
  return 503 with the command that builds one.
- Every data response has the same envelope:
  `{ snapshot: {id, schema_version, latest_week, created_at_utc}, disclaimer, params, note?, count?, data }`,
  plus the `X-OAH-Snapshot` header and an ETag. `params` echoes the toggles after defaults are
  applied. `note` says what a toggle does *not* change for that endpoint.
- Scores always come with their interval (`W: {mean, q05, q50, q95}`, same for `H`), an `evidence`
  flag and `mixing_flag`. Dates are `YYYY-MM-DD`. `*_json` columns arrive parsed (`facts`,
  `source_probs`, `ppc`, ...).
- Toggles: `variant=M1|M1_norain` (rain assumption on/off) and `sensitivity=sensitive|normal|strict`
  (5/10/20-point drop). Unknown, repeated or invalid parameters are 400s that list the allowed
  values. Unknown ids are 404s. Anything other than GET/HEAD/OPTIONS is 405. All SQL takes bound
  parameters.

| Endpoint (`/api/v1` unless noted) | What it serves |
|---|---|
| `/health` (root) | liveness, snapshot id, last reload error |
| `/meta` | manifest, toggles and their values, thresholds, model health, inputs + sha256, table glossary |
| `/sites`, `/sites/{id}` | latest week per site (head -> mouth), status text, nearby playgrounds/schools/parks; detail adds river neighbours, findings and incidents |
| `/sites/{id}/timeseries` | weekly W/H intervals, alerts, rainfall (`from`, `to`) |
| `/sites/{id}/observations` | de-identified reports, newest first (`from`, `to`, `limit`, `offset`) |
| `/scores?week=` | every site in one week (any date maps to its week; defaults to the latest week) |
| `/weeks`, `/river` | rainfall per week; river graph nodes and edges |
| `/findings`, `/findings/{id}` | ranked fact-locked findings (`type`, `priority`, `recent`, `site`, `lang`, paging) |
| `/incidents`, `/incidents/{id}` | incidents with source probabilities and a ranking; detail adds their site-week alerts and finding |
| `/rain-pattern` | rain -> overflow test by group, placebo, sewage-smell shares, corroboration |
| `/model/diagnostics`, `/model/params` | convergence + PPC checks, parameter summaries |

## Structure

- `pipeline/` — Python offline pipeline (stages 1-8, 12): ingestion, weather, graph, exposure,
  Bayesian model, detectors, NLG, snapshot freezing, and benchmarking.
- `api/` — Node/Express Insight API (stage 9) serving the frozen DuckDB snapshot.
- `dashboard/` — Next.js dashboard (stage 10).
- `data/` — `raw/`, `processed/`, and `snapshot/` (frozen DuckDB output, read by the API).

## Running locally

### Pipeline
```bash
source .venv/bin/activate
pip install -r pipeline/requirements.txt
python -m pipeline.main
```
The week grid is pinned (`DEFAULT_ANCHOR_DATE` in `pipeline/common/config.py`), so a rerun
regenerates the committed data. Set `OAH_ANCHOR_DATE=today` to refresh to current weeks instead.
Stage 5's posterior draws (`data/processed/model_draws*.nc`) are not committed; run
`python -m pipeline.model.bayesian_model` (about 6 minutes) before running Stage 6 on a fresh clone.

### API
The API reads `data/snapshot/oah_snapshot.duckdb`. Build it first (seconds, from committed files):
`python -m pipeline.snapshot.freeze_snapshot`.
```bash
cd api
npm install
cp .env.example .env
npm start            # or: npm run dev (restarts on code changes)
npm test             # node:test suite against the real snapshot (skips if it is missing)
curl "localhost:4000/api/v1/sites?variant=M1_norain&sensitivity=strict"
```

### Dashboard
```bash
cd dashboard
npm install
cp .env.example .env.local
npm run dev
```
