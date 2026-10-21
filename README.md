# CreditLens

[![CreditLens checks](https://github.com/jayyy255/creditlens/actions/workflows/ci.yml/badge.svg)](https://github.com/jayyy255/creditlens/actions/workflows/ci.yml)

Credit risk and lending intelligence using the Home Credit Default Risk relational dataset.

## Project status

The repository is being built incrementally. A working local baseline generates synthetic relational data, validates source files, creates analytical features, evaluates a calibrated logistic regression, and serves an interactive analytics dashboard. Actual Home Credit data has now undergone exploratory investigation; model performance and the live dashboard still use the synthetic baseline.

## Actual-data investigation

**Stage 2 is approved and implemented:** [semantic missingness flags and reasons](docs/stage2/implementation.md). Install `python -m pip install -e ".[missingness]"`, then run `python -m creditlens.cli missingness --source data --stage1 data/stage1 --output data/stage2` and `python -m scripts.check_stage2`. Originals remain unchanged; numerical imputation is deferred. Stage 3 sentinel/special-code rules and later choices remain pending.

The actual-data Stage 2 run is independently verified across **55,369,709 application and matched-history rows**, with **325 table-field rules** documented. In labeled applications, missing car age is separated into **202,924 confirmed non-car-owners** and **5 unknown ages**. External scores are retained with missingness indicators. See [verified Stage 2 results](docs/stage2/missingness-results.md), [aggregate evidence](docs/stage2/missingness-results.json), and the [field dictionary](docs/stage2/field-dictionary.json). All row-level sidecars stay local and excluded from Git.

**Stage 1 is approved and implemented:** [matched joins and anti joins](docs/stage1/implementation.md). Run `python -m creditlens.cli joins --source data --output data/stage1` for the standalone join stage, then `python -m scripts.check_stage1` to independently verify the persisted outputs. Stage 1 preserves directly borrower-linked history, separates unmappable records, and identifies bureau accounts without monthly history. The dashboard/model still use synthetic data.

The full actual-data Stage 1 run is complete: **58,133,638 historical records** were independently reconciled by source-row identity. Bureau monthly records split into **24,179,741 matched** and **3,120,184 unmatched** rows. **942,074 bureau accounts without monthly history** remain retained, as do **2,674,203 directly borrower-linked history rows without previous-application parents**. See [verified results](docs/stage1/join-results.md) and [aggregate evidence](docs/stage1/join-results.json). Raw and row-level outputs remain local and excluded from Git.

The supplied Home Credit CSVs have now been investigated across all eight analytical tables. The [seven-stage investigation](docs/eda/investigation.md) is the original EDA snapshot covering key integrity, missingness, sentinels, distributions, target associations, historical grain, and feature-preparation findings. Stage 1 joins and Stage 2 semantic missingness have since been approved; Stage 3 onward remains open. A [standalone HTML report](docs/eda/investigation.html) and [overview chart](docs/eda/figures/investigation-overview.png) are also included.

The analysis reserves 46,127 labeled borrowers as a final holdout and uses 261,384 borrowers for target-based exploration. Raw data and borrower-level partition files remain excluded from Git. No real-data model has been trained and the existing dashboard still shows synthetic data. The separate Stage 1 command implements the approved join policy; the legacy demo ingestion command still rejects incomplete parent links and has not yet been integrated with the remaining real-data stages.

Reproduce from the repository root (pandas, NumPy, and matplotlib required):

```sh
python scripts/investigate_data.py
python scripts/investigate_edge_cases.py
python scripts/plot_eda.py
python scripts/render_eda_report.py
python scripts/check_eda.py
```

Keep the locally persisted `artifacts/eda/partition.csv` for subsequent real-data modeling. The current demo training command does not yet reuse it. Application quantiles are exact on the exploration sample; historical quantiles are sampled and labeled. Structural counts cover all input rows. Stage 1 joins and Stage 2 missingness annotation are approved; numerical imputation, later transformations and model comparisons remain pending.

## Run the demo

Requires Python 3.11 or newer. From the repository root:

```sh
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m creditlens.cli demo
python -m uvicorn creditlens.api:app --host 127.0.0.1 --port 8000
# In a second terminal:
python -m pytest
```

Open [the local dashboard](http://127.0.0.1:8000) or [API documentation](http://127.0.0.1:8000/docs). Filter income categories, compare segment event rates, move the policy risk slider, inspect calibration, and export a portfolio summary.

![CreditLens dashboard using synthetic demonstration data](docs/dashboard-preview.png)

The demo produces 6,000 deterministic synthetic applications and six historical tables. Derived CSVs live in `data/silver/` and `data/gold/`; quality and source-hash reports are in `data/quality.json`. Model metrics, split membership, validation scores, and the trusted local model artifact are in `artifacts/`. All generated data and model files are ignored by Git.

For actual Home Credit data, use the standalone Stage 1 and Stage 2 commands above. Include `application_test.csv` so borrower matching recognizes unlabeled applicants. Do not run the legacy demo ingestion/training commands on the actual files yet; the remaining transformation choices and reserved holdout still need integration.

## Model protocol

A borrower appears in exactly one partition: training 60%, sigmoid calibration 15%, policy validation 10%, final test 15%. Preprocessing is fitted on training rows. Only whitelisted financial and historical features enter the model. Gender and age are retained for diagnostics, not direct model inputs. Reports include ROC-AUC, average precision, Brier score, calibration bins, a constant-risk baseline, exploratory subgroup metrics, and a validation ROC-AUC bootstrap interval. Random borrower splits cannot establish temporal generalization; demographic omission cannot establish fairness.

## Intended architecture

CSV sources → Bronze / Silver / Gold pipeline → analytical warehouse → statistics and risk models → FastAPI → interactive dashboard and Power BI.

## Delivery milestones

- [x] Repository foundation and project brief.
- [x] Reproducible synthetic demo and validated ingestion.
- [x] Leakage-aware baseline evaluation and policy simulation engine.
- [x] Analytics API and interactive dashboard.
- [x] Optional PostgreSQL mart and advanced analytics SQL (execution unverified locally).
- [x] Power BI connection guide and DAX starter measures; CI and operating documentation.
- [ ] Full Home Credit run, PostgreSQL/container validation, completed Power BI report, and deployed production services.

## Documentation

- [Data and model methodology](docs/methodology.md)
- [Local operation, containers, warehouse loading, and production backlog](docs/operations.md)
- [Power BI integration](docs/power-bi.md)
- [Advanced SQL analyses](warehouse/analyses.sql)

The current web interface is a lightweight static frontend served by FastAPI. Next.js, dbt, Prefect, Redis, SHAP, advanced models, and monitoring are planned extensions, not implemented capabilities. Local verification: 28 automated tests passed, including 10 Stage 1 join tests and 7 Stage 2 tests; browser filtering and 0%/100% policy boundaries were previously checked. CI additionally checks standalone stage outputs, repeat PostgreSQL loading, mart totals, policy sums, and analytical SQL execution.

## Interpretation

The Home Credit target represents the dataset's defined repayment-difficulty outcome. It is not a universal measure of banking default or loss. Lending thresholds produce hypothetical simulations; revenue, profitability, and realized policy impact are not established by these data.

## Data

Obtain Home Credit data under its applicable terms and place CSV files in `data/raw/`. Raw data, derived data, and trained model artifacts are excluded from Git. A synthetic demo will support development without the restricted dataset.

See [the project brief](docs/project-brief.md) for the requested scope.
