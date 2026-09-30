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
```bash
cd api
npm install
cp .env.example .env
node src/server.js
```

### Dashboard
```bash
cd dashboard
npm install
cp .env.example .env.local
npm run dev
```
