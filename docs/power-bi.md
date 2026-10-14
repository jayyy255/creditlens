# Power BI integration guide

This repository contains integration instructions and measures, not a completed `.pbix` dashboard.

## Connect

After loading the PostgreSQL warehouse, use **Get data → PostgreSQL database** in Power BI Desktop. Connect to `localhost:5432`, database `creditlens`. Import `creditlens.borrowers`, `creditlens.validation_scores`, and optionally `creditlens.segment_risk`. The API dashboard reads local CSV snapshots; PostgreSQL is an optional separate analytics consumer.

Create a one-to-one relationship between `borrowers[sk_id_curr]` and `validation_scores[sk_id_curr]`. Use a single filtering direction from borrowers to scores. Keep score metrics scoped to the validation sample.

## Measures

```dax
Applications = COUNTROWS(borrowers)
Difficulty events = SUM(borrowers[target])
Difficulty rate = DIVIDE([Difficulty events], [Applications])
Requested credit = SUM(borrowers[amt_credit])
Median credit to income = MEDIAN(borrowers[credit_to_income])
Validation applicants = COUNTROWS(validation_scores)
```

Create a disconnected numeric what-if parameter table:

```dax
Risk threshold = GENERATESERIES(0, 1, 0.01)
Selected risk = SELECTEDVALUE('Risk threshold'[Value], 0.15)
Simulated accepted =
    VAR Threshold = [Selected risk]
    RETURN COUNTROWS(FILTER(validation_scores, validation_scores[probability] <= Threshold))
Simulated approval rate = DIVIDE([Simulated accepted], [Validation applicants])
Expected difficulty events =
    VAR Threshold = [Selected risk]
    RETURN SUMX(FILTER(validation_scores, validation_scores[probability] <= Threshold), validation_scores[probability])
```

## Suggested report pages

1. Portfolio: application count, requested credit, observed target rate, income and age slicers. Use dataset monetary units; no currency is established here.
2. Risk concentration: income and age segment matrices with counts beside rates; confidence intervals are available through the API.
3. Policy exploration: validation count, selected risk threshold, simulated approval rate, and sum of accepted probabilities.

Display `data_kind` prominently. Label synthetic results as demonstration data and policy results as hypothetical. Do not describe target events as realized loss, revenue, or profit.
