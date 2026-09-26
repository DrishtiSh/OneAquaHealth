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
