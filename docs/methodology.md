# Data and model methodology

## Grain and layers

`application_train.csv` is the labeled borrower grain, with a unique non-null `SK_ID_CURR`. `application_test.csv` supplies additional legitimate borrower IDs for historical foreign-key validation; no target is inferred for those borrowers. Gold output includes only labeled applicants.

Bronze contains unchanged input copies in SHA-256 directories. Silver currently contains cleaned applications. Gold is one row per labeled borrower with application ratios and optional history aggregates. Histories are scanned in chunks, with partial sums and valid-value counts reduced across chunk boundaries. No millions-of-rows performance benchmark has been performed. Bronze copies can require substantial disk space on the full dataset.

History features: mean bureau debt, installment late-payment fraction, previous refusal fraction, mean POS days past due, mean credit-card utilization, and fraction of bureau monthly statuses 1–5 among known 0–5 statuses. Unknown bureau statuses X/C are excluded from the status-rate denominator. Installments use payment records, not a deduplicated scheduled-installment grain; split payments can create multiple records. These features must not be interpreted as complete contractual delinquency or loss measures.

Schema checks cover required columns. Application duplicate IDs, bureau duplicate IDs, and foreign-key violations fail ingestion. Application missingness is profiled. Negative application amounts fail ingestion; employment sentinel `365243` becomes missing; zero ratio denominators become missing. Historical positive decision dates, credit dates, balance months, and future installments/payment dates are excluded. Missing dates in these temporal fields are excluded too. No blanket de-duplication of historical financial records is performed.

The source manifest records hashes and sizes; the completion manifest is removed while writing a new snapshot. Ingestion reprocesses sources on each run; it is not an incremental CDC engine. A failed ingestion or training run must be repaired before serving. Pipeline and API execution should be sequential: restart the API after regeneration, since it holds a snapshot in memory.

## Model

Fixed-seed stratified borrower partitions: 60% train, 15% calibration, 10% validation, 15% final test (rounding can change counts). Numeric median imputation, missingness indicators, standard scaling, categorical mode imputation, and one-hot encoding are fitted only on training rows. Logistic regression uses a fixed regularization setting. A sigmoid calibrator is fitted only on calibration rows. No threshold tuning uses test labels.

No oversampling or class weighting is used in this baseline: natural class prevalence is retained for probability calibration. Average precision and ROC-AUC are reported alongside Brier score, reliability bins, and a constant training-prevalence baseline. Calibration is evaluated, not guaranteed. Validation ROC-AUC intervals use 200 fixed-prediction bootstrap resamples and exclude model-fitting uncertainty.

Direct gender and age inputs are excluded. Income and employment can still act as proxies. Subgroup discrimination, calibration, event rates, counts, and small-sample flags are diagnostics, not a fairness certification. No automated real-world lending decisions are supported.

Random historical splits are not out-of-time validation. The dataset's relative time fields support some leakage defenses but cannot prove every source was available at every real lending decision. Validate data availability and temporal performance before production work.

## Statistics and policy

Portfolio event-rate intervals use Wilson's 95% binomial method. Segment chi-square tests are unadjusted, exploratory observational associations; expected-count diagnostics are included. No multivariate causal claim or independent demographic effect is established.

Simulation uses validation applicants exclusively. Accept when predicted probability is at or below the selected threshold. Expected difficulty events are the sum of accepted probabilities. Empty accepted populations have no mean risk and zero expected events. Actual lending policies can change who applies, repayment behavior, and selection bias. The simulation does not estimate causal impact or realized profit.
