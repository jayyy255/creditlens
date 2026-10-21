# Stage 1: matched joins and anti joins

Approved on 21 October 2026. This implements the chosen join policy only. [Stage 2 semantic missingness](../stage2/implementation.md) has since been approved separately. Numerical imputation, sentinel/date rules, outlier handling, feature engineering, and model comparison remain pending. The original exploratory investigation and Stage 1 results are preserved as historical reports.

The actual-data run and independent persisted-output verification are complete. See [verified join results](join-results.md) for counts across all 58,133,638 historical source records. Local tests: 21 passed, including 10 Stage 1 tests. The implementation's GitHub Actions run also passed the standalone Stage 1 smoke test and persisted-partition verifier.

## Policy

1. Validate that application IDs and parent account/contract IDs are unique, non-null positive integer identifiers, and that labeled/unlabeled application IDs are disjoint. A duplicate parent key fails the run before output publication, preventing join multiplication.
2. Match bureau monthly records to bureau accounts using `SK_ID_BUREAU`, then resolve their borrower through `SK_ID_CURR`. Preserve unmappable monthly rows in the unmatched partition with a reason.
3. Retain other histories with a valid direct borrower ID even when `SK_ID_PREV` has no previous-application match. The missing-parent anti join is separately exported as a diagnostic subset. A conflicting known parent/borrower mapping is quarantined rather than guessed.
4. Compute a reverse anti join to identify bureau accounts with no monthly records. Keep these accounts in the matched bureau output when their borrower is valid.
5. Do not impute, normalize fields, remove duplicate financial observations, filter by date, aggregate installment payments, or train a model. These decisions are outside Stage 1.

## Run

From the repository root:

```sh
python -m creditlens.cli joins --source data --output data/stage1
python -m scripts.check_stage1
```

All supplied analytical histories are scanned in chunks. CSV fields are read as strings with automatic NA conversion disabled, preserving literal category values, numeric text, sentinels and blanks. Input CSVs remain unchanged. Only `SK_ID_CURR` is added to bureau monthly outputs, plus these provenance fields on historical outputs:

- `_source_row`: one-based data-record ordinal within the original source file, excluding the header.
- `_join_status`: `matched_borrower` or an unmatched reason.
- `_parent_status`: parent matched, parent missing, direct borrower link, or conflicting mapping.

Missing parent links do not mean zero prior borrowing, zero debt, or zero delinquency.

## Local outputs

`data/stage1/current.json` points to a content-addressed completed run. Row-level files are compressed CSVs under the run directory:

| Location | Meaning |
| --- | --- |
| `matched/<table>.csv.gz` | All records linked to a known labeled or unlabeled borrower. For directly linked histories this includes retained missing-parent records. |
| `unmatched/<table>.csv.gz` | The disjoint primary anti partition: unresolved borrower/account links or conflicting mappings, with explicit reasons. |
| `anti/missing_previous_application/<table>.csv.gz` | Diagnostic copies of retained records whose optional previous-application parent is unavailable. Already included in `matched/`; do not concatenate these copies back into it. |
| `anti/bureau_without_monthly_history.csv.gz` | Reverse anti join: bureau accounts without observed monthly records. These are already included in the bureau primary partition and must not be counted twice. |
| `coverage/borrowers.csv.gz` | One row per application ID with structural record counts and history-presence flags. This contains no inferred debt, delinquency, or target outcome. |
| `manifest.json` | Source fingerprints, output checksums, counts, parent-link statuses and reconciliation checks. |

An absent history source has blank coverage values and is disclosed in `missing_tables`; an available source with no matched observations has a false history-presence flag. Neither case is used to impute financial values.

Primary reconciliation for every table:

```text
source rows = matched borrower rows + unmatched borrower rows
```

Every source-row ordinal must appear exactly once across those two outputs. Secondary anti-join diagnostics intentionally overlap the primary outputs and are not extra records. Reverse reconciliation is:

```text
bureau accounts = accounts with monthly history + accounts without monthly history
```

## Publication and verification

Runs are first written to a new incomplete directory. A completed run and its `current.json` pointer are published only after counts reconcile and source size/modification-time checks pass. Failures leave the previous completed run selected. Identical input content and implementation reuse a prior completed run only after output checksums pass; source changes or implementation changes create a new run.

`scripts/check_stage1.py` independently rereads the saved outputs and checks checksums, source-row uniqueness/completeness, borrower membership, retained anti subsets and reverse counts. The aggregate-only findings are written to [join-results.json](join-results.json). The entire row-level output folder is ignored by Git.

This command does not update the existing Silver/Gold demo layers or API snapshot. The legacy `ingest` command still includes later-stage transformations and its original strict join checks; do not use it for the real-data workflow until the remaining stages have been agreed and integrated. No model is trained by `joins` or its verifier.
