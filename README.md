# CreditLens

Credit risk and lending intelligence using the Home Credit Default Risk relational dataset.

## Project status

The repository is being built incrementally. This first milestone establishes the project scope, architecture, and delivery plan. No real dataset or evaluated production model is included yet.

## Intended architecture

CSV sources → Bronze / Silver / Gold pipeline → analytical warehouse → statistics and risk models → FastAPI → interactive dashboard and Power BI.

## Delivery milestones

- [x] Repository foundation and project brief.
- [ ] Reproducible synthetic demo and validated ingestion.
- [ ] Leakage-aware model evaluation and policy simulation.
- [ ] Analytics API and interactive dashboard.
- [ ] PostgreSQL analytics, BI integration, CI, and operating documentation.

## Interpretation

The Home Credit target represents the dataset's defined repayment-difficulty outcome. It is not a universal measure of banking default or loss. Lending thresholds produce hypothetical simulations; revenue, profitability, and realized policy impact are not established by these data.

## Data

Obtain Home Credit data under its applicable terms and place CSV files in `data/raw/`. Raw data, derived data, and trained model artifacts are excluded from Git. A synthetic demo will support development without the restricted dataset.

See [the project brief](docs/project-brief.md) for the requested scope.
