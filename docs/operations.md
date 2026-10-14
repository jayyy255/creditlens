# Local operation and remaining production work

## Start

```sh
python -m pip install -e ".[dev]"
python -m creditlens.cli demo
python -m uvicorn creditlens.api:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. Interactive API documentation is at `/docs`. Use a second terminal for tests. The default demo reuses existing `data/demo-raw/` inputs; `--rows` and `--seed` affect newly generated inputs only. To generate another sample, select a new empty `--source` directory. A destination containing CSV files without the synthetic marker is never overwritten.

For real CSVs: `python -m creditlens.cli ingest --source data/raw`, then `python -m creditlens.cli train`. Keep the raw source separate from generated `bronze`, `silver`, and `gold` folders. The run requires both target classes and model training requires at least 500 applicants with at least 30 per class.

The API checks data and validation-score fingerprints at startup. `/api/health` returns 503 when setup is incomplete or inconsistent. The dashboard shows actionable setup errors. Regenerate artifacts and restart to refresh the API snapshot. The API does not unpickle trained models and exposes only aggregate analytics.

## Containers

After generating local data/artifacts, copy `.env.example` to `.env` and choose a local password. Run `docker compose up --build app`. Local snapshots are mounted read-only. To also start PostgreSQL, run `docker compose --profile warehouse up -d postgres`.

To load PostgreSQL, install `python -m pip install -e ".[warehouse]"`, set `DATABASE_URL` in your shell, then run `python scripts/load_warehouse.py`. The loader atomically refreshes this project's dedicated analytical tables and materialized view, preserving other schemas. For PowerShell:

```powershell
$env:DATABASE_URL = 'postgresql://creditlens:YOUR_URL_ENCODED_PASSWORD@localhost:5432/creditlens'
python scripts/load_warehouse.py
```

The versioned initial SQL uses idempotent DDL and a schema version record; future incompatible schema changes require new migrations. `warehouse/analyses.sql` includes segment concentration, risk deciles, policy frontiers, and an execution-plan query.

## Verification

Run `python -m pytest -q` and `node --check creditlens/static/app.js`. In restricted environments, pytest may need an explicitly writable `--basetemp` folder. GitHub Actions runs the tests, full synthetic demo, JavaScript syntax check, and a PostgreSQL integration check on pushes and pull requests. The integration check refreshes the mart twice to verify repeat loading, compares row and event totals and simulated policy sums, and executes all four analytical queries. Run it locally after loading with `python scripts/check_warehouse.py`.

## Current boundaries

This is a working local baseline, not the complete production platform in the brief. The UI uses static HTML/CSS/JavaScript served by FastAPI. A Next.js frontend, dbt star schema, Prefect orchestration, Redis caching, SHAP, boosted models, multivariate statistical notebooks, drift jobs, authentication, persistent monitoring, deployment, and a finished Power BI report remain future work. PostgreSQL is an optional mart; it is not yet the API's serving backend.

No external dataset download is automated. Raw/derived observations and model artifacts are excluded from Git. No dataset license is granted by this repository. Add project licensing deliberately before distributing third-party assets. Bind locally; authentication and production network controls must be implemented before hosting real borrower analytics.
