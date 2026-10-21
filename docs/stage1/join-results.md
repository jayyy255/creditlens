# Stage 1 verified join results

Matched joins and anti joins have been applied to the actual Home Credit histories. Raw source files, the reserved holdout, and the synthetic serving data remain unchanged. Stages 2–7 are still pending.

| History | Source rows | Matched borrower rows | Unmatched rows | Retained without previous application |
| --- | ---: | ---: | ---: | ---: |
| bureau | 1,716,428 | 1,716,428 | 0 | 0 |
| bureau_balance | 27,299,925 | 24,179,741 | 3,120,184 | 0 |
| previous_application | 1,670,214 | 1,670,214 | 0 | 0 |
| POS_CASH_balance | 10,001,358 | 10,001,358 | 0 | 340,561 |
| installments_payments | 13,605,401 | 13,605,401 | 0 | 1,250,826 |
| credit_card_balance | 3,840,312 | 3,840,312 | 0 | 1,082,816 |

Every historical input record appears exactly once across its matched and unmatched partitions. Missing-previous-application diagnostic files are subsets of retained rows and must not be appended again.

Reverse anti join: **942,074 bureau accounts** have no monthly records in the supplied monthly file. They remain in the bureau matched output when their borrower is known. 774,354 accounts have monthly history; together these reconcile to 1,716,428 source accounts.

## Independent verification

- Every output checksum matches its manifest
- Borrower coverage IDs are unique
- Every historical source row appears exactly once across matched and unmatched outputs
- Matched rows have known borrower IDs
- Retained missing-parent diagnostic rows exactly match their subset
- Bureau reverse-anti counts reconcile
- All persisted row partitions reconcile

Row-level outputs are kept in the ignored `data/stage1/` folder, with `current.json` selecting the completed run. Aggregate evidence and source hashes are in [join-results.json](join-results.json). See [the Stage 1 policy](implementation.md) for output definitions.
