# Stage 2 verified missingness results

Semantic missingness annotation is complete on the actual data. Originals are referenced unchanged; flags, reason codes and prepared categorical values are separate sidecars. No numerical imputation was fitted. Stages 3–7 remain pending.

| Input | Rows retained | Documented fields | Unknown blank cells | Structurally not-applicable cells |
| --- | ---: | ---: | ---: | ---: |
| application_train | 307,511 | 120 | 8,949,541 | 202,924 |
| application_test | 48,744 | 120 | 1,372,108 | 32,311 |
| bureau | 1,716,428 | 15 | 3,939,947 | 0 |
| bureau_balance | 24,179,741 | 2 | 0 | 0 |
| previous_application | 1,670,214 | 35 | 11,109,336 | 0 |
| POS_CASH_balance | 10,001,358 | 6 | 52,158 | 0 |
| installments_payments | 13,605,401 | 6 | 5,810 | 0 |
| credit_card_balance | 3,840,312 | 21 | 5,877,356 | 0 |

All **55,369,709 selected source rows** and every saved field annotation were checked independently. The input includes both labeled and unlabeled applications; target values are excluded from annotation and verification.

## Application fields to review

| Source | Field | Unknown blanks | Confirmed not applicable | Observed |
| --- | --- | ---: | ---: | ---: |
| application_train | OWN_CAR_AGE | 5 | 202,924 | 104,582 |
| application_train | EXT_SOURCE_1 | 173,378 | 0 | 134,133 |
| application_train | EXT_SOURCE_2 | 660 | 0 | 306,851 |
| application_train | EXT_SOURCE_3 | 60,965 | 0 | 246,546 |
| application_train | OCCUPATION_TYPE | 96,391 | 0 | 211,120 |
| application_train | NAME_INCOME_TYPE | 0 | 0 | 307,511 |
| application_test | OWN_CAR_AGE | 1 | 32,311 | 16,432 |
| application_test | EXT_SOURCE_1 | 20,532 | 0 | 28,212 |
| application_test | EXT_SOURCE_2 | 8 | 0 | 48,736 |
| application_test | EXT_SOURCE_3 | 8,668 | 0 | 40,076 |
| application_test | OCCUPATION_TYPE | 15,605 | 0 | 33,139 |
| application_test | NAME_INCOME_TYPE | 0 | 0 | 48,744 |

## Verification

- All output checksums match
- Every selected source row and its identifiers align
- Every missing flag and reason matches original fields
- Prepared categories preserve all nonblank values
- No target or imputed measurement is present in sidecars
- All field reason counts reconcile
- Original Stage 1 coverage values are preserved
- No matched history is distinct from source not supplied
- Source hashes remain unchanged

Literal special codes and sentinels are retained as observed source values for Stage 3 review. Numeric blanks remain blank in their original sources. No features or applicants were removed for sparse data. Missing occupation is not relabeled as unemployed or retired, and absent housing details are not treated as lack of property ownership.

See [the field dictionary](field-dictionary.json) for column-by-column rules, [aggregate counts](missingness-results.json), and [the Stage 2 implementation](implementation.md) for how to use the local sidecars.
