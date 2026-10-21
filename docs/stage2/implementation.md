# Stage 2: semantic missingness

Approved on 21 October 2026. Stage 2 preserves original observations and adds documented missingness indicators, reason codes, explicit unknown categorical values, and history-availability context. Numerical imputation and all Stage 3–7 decisions remain pending.

## Meaning before imputation

| Code | Meaning | Rule |
| --- | --- | --- |
| 0 | Observed source value | The original CSV field is not exactly empty. This is not a validity certification. |
| 1 | Unknown source blank | The original CSV field is empty, and no confirmed not-applicable rule applies. |
| 2 | Confirmed not applicable | Application car age is empty and `FLAG_OWN_CAR` explicitly equals `N`. |

The reason for other source blanks is not inferred. Missing occupation is not relabeled as unemployment or retirement. Missing housing details do not establish that an applicant lacks property. Unknown car ownership does not justify marking car age as not applicable.

Literal values including `NA`, `NULL`, `nan`, `X`, `XNA`, `C`, whitespace, and `365243` remain observed at this stage. Their interpretation and validity are deferred to Stage 3. In particular, valid closed-account status `C` is not erased, and the employment sentinel is not used as a real duration or converted here. A reported car age alongside nonownership is preserved and separately flagged as a context conflict.

## Run

From the repository root, after completing Stage 1:

```sh
python -m pip install -e ".[dev,missingness]"
python -m creditlens.cli missingness --source data --stage1 data/stage1 --output data/stage2
python -m scripts.check_stage2
```

Stage 2 reads the labeled and unlabeled application predictors directly from the originals verified against the Stage 1 hashes, plus the six Stage 1 borrower-matched history partitions. It excludes `TARGET` from reading and output. The Stage 1 unmatched records remain preserved separately and are not reintroduced into borrower-level data.

## Sidecars and original values

`data/stage2/current.json` selects a completed, content-addressed run. Each input table has a compressed Parquet sidecar with:

- `_source_row`: original data-record ordinal, carried unchanged from Stage 1 for histories. It can contain gaps after the Stage 1 unmatched partition.
- Existing identifier and join-context fields for traceability. These are not model inputs.
- `<field>__missing`: whether the original field was empty, including confirmed not-applicable blanks.
- `<field>__reason`: the documented reason code above.
- `<field>__category`: for registered categorical fields only, retaining every observed category and replacing an empty categorical field with `__UNKNOWN_SOURCE__` in this separate prepared column. The original source is never overwritten.
- `OWN_CAR_AGE__context_conflict`: when applicable, flags reported ages alongside car nonownership without changing them.

The token `__UNKNOWN_SOURCE__` is reserved; if it already exists in an original categorical field the run fails instead of conflating it with generated unknown categories. The categorical registry is explicit and versioned. Other fields receive missingness annotations but no numeric conversion, inferred dtype, numeric replacement, scaling, or encoding.

Sidecars deliberately avoid copying all financial measurements. Originals remain available through the checksum-linked raw or Stage 1 files. Use the table, input version and `_source_row` to align them. A sidecar is not a finished model matrix. The final feature set and model-specific preparation will be agreed later.

## Historical availability

`borrower_availability.parquet` preserves all Stage 1 coverage columns and adds one status per history source:

| Status | Meaning |
| --- | --- |
| `matched_history` | The supplied history has at least one retained record linked to the borrower. |
| `no_matched_history` | The source was supplied but no retained matching record exists. This does not prove that the applicant never borrowed. |
| `source_not_supplied` | The relevant table was not supplied; individual history availability is unknown. |

Missing parent context is also retained on individual historical sidecars through `_parent_status`. Unmappable bureau-month rows cannot be assigned a guessed borrower. Missing account debt remains distinct from a reported zero, and no financial aggregate is filled with zero.

## Dictionary, verification and publication

The versioned [rule registry](../../creditlens/missingness_rules.json) is packaged with CreditLens. A field-by-field dictionary is generated for the actual columns of every selected input, documenting each flag, reason and categorical preparation rule. Aggregate-only copies are published alongside the verification report; row-level sidecars are ignored by Git.

Completed runs are published only after row and reason totals reconcile and source hashes still match. Failed/incomplete runs do not replace the selected completed run. Reusing a prior run requires its checksums to pass. The independent checker streams original records alongside saved sidecars, verifies every annotation and source-row alignment, and checks preserved coverage and categorical values.

Stage 2 uses deterministic record-local rules only. It does not fit imputation on any partition, inspect target associations, learn from holdout outcomes, drop sparse columns/applicants, or alter the demo API/model artifacts. Numeric imputation will be fitted using training data only after the preparation plan is agreed.
