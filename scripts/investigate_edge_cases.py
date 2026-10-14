"""Focused follow-up checks for missingness semantics and repeated installment keys."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def main():
    membership = pd.read_csv(ROOT / "artifacts/eda/partition.csv")
    ids = set(membership.loc[membership.partition == "exploration", "SK_ID_CURR"])
    app = pd.read_csv(ROOT / "data/application_train.csv", usecols=["SK_ID_CURR", "FLAG_OWN_CAR", "OWN_CAR_AGE", "AMT_INCOME_TOTAL", "AMT_CREDIT", "AMT_ANNUITY", "NAME_INCOME_TYPE", "DAYS_EMPLOYED", "CODE_GENDER"])
    app = app.loc[app.SK_ID_CURR.isin(ids)]
    result = {"population": "exploration applicants; all installment rows for structural checks", "car_age_missingness": {}, "extreme_income": {}}
    for category, group in app.groupby("FLAG_OWN_CAR"):
        result["car_age_missingness"][str(category)] = {"borrowers": len(group), "missing_car_age": int(group.OWN_CAR_AGE.isna().sum()), "missing_rate": float(group.OWN_CAR_AGE.isna().mean())}
    for boundary in [1_000_000, 5_000_000, 10_000_000]:
        result["extreme_income"][str(boundary)] = int((app.AMT_INCOME_TOTAL > boundary).sum())
    result["annuity_income_over_one"] = int((app.AMT_ANNUITY / app.AMT_INCOME_TOTAL > 1).sum())
    print("Inspecting repeated installment keys across all payment records", flush=True)
    keys = ["SK_ID_PREV", "NUM_INSTALMENT_VERSION", "NUM_INSTALMENT_NUMBER"]
    columns = keys + ["DAYS_INSTALMENT", "DAYS_ENTRY_PAYMENT", "AMT_INSTALMENT", "AMT_PAYMENT"]
    frame = pd.read_csv(ROOT / "data/installments_payments.csv", usecols=columns,
                        dtype={"SK_ID_PREV": "int32", "NUM_INSTALMENT_VERSION": "float32", "NUM_INSTALMENT_NUMBER": "int32"})
    repeated = frame.loc[frame.duplicated(keys, keep=False)]
    del frame
    summary = repeated.groupby(keys).agg(records=("AMT_PAYMENT", "size"),
        scheduled_values=("AMT_INSTALMENT", "nunique"), due_dates=("DAYS_INSTALMENT", "nunique"),
        scheduled_amount=("AMT_INSTALMENT", "first"), total_paid=("AMT_PAYMENT", "sum"),
        known_payments=("AMT_PAYMENT", "count"), known_payment_dates=("DAYS_ENTRY_PAYMENT", "count"))
    consistent = summary.loc[(summary.scheduled_values == 1) & (summary.due_dates == 1)]
    result["installment_repeated_keys"] = {
        "rows_in_repeated_keys": len(repeated), "repeated_key_groups": len(summary),
        "maximum_records_per_key": int(summary.records.max()),
        "groups_with_multiple_scheduled_amounts": int((summary.scheduled_values > 1).sum()),
        "groups_with_multiple_due_dates": int((summary.due_dates > 1).sum()),
        "groups_with_consistent_due_and_scheduled_amount": len(consistent),
        "consistent_groups_fully_paid_after_summing": int((consistent.total_paid >= consistent.scheduled_amount - .01).sum()),
        "consistent_groups_still_underpaid_after_summing": int((consistent.total_paid < consistent.scheduled_amount - .01).sum()),
        "consistent_groups_with_unknown_payment_dates": int((consistent.known_payment_dates < consistent.records).sum()),
        "rows_underpaid_when_compared_individually": int((repeated.AMT_PAYMENT < repeated.AMT_INSTALMENT - .01).sum()),
        "groups_with_missing_payment_amounts": int((summary.known_payments < summary.records).sum()),
        "comparison_tolerance": .01,
        "note": "Aggregate diagnostic only. Sum of payment amounts does not establish contractual settlement or the absence of reversals. No rows deduplicated and no production feature computed.",
    }
    path = ROOT / "docs/eda/results/edge_cases.json"
    path.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
