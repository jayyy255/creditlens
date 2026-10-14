"""Reconcile aggregate investigation outputs without inspecting holdout outcomes."""

import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/eda/results"


def read(name):
    return json.loads((OUT / f"{name}.json").read_text())


def check():
    app, hist, edges = read("applications"), read("historical_associations"), read("edge_cases")
    info = app["integrity"]
    membership = pd.read_csv(ROOT / "artifacts/eda/partition.csv")
    assert membership.SK_ID_CURR.is_unique
    assert len(membership) == info["training_rows"]
    assert (membership.partition == "exploration").sum() == info["exploration_rows"]
    assert (membership.partition == "final_holdout").sum() == info["holdout_rows"]
    private = pd.read_csv(ROOT / "artifacts/eda/exploration_target.csv")
    assert set(private.SK_ID_CURR) == set(membership.loc[membership.partition == "exploration", "SK_ID_CURR"])
    assert int(private.TARGET.sum()) == info["exploration_events"]
    for groups in [app["target_segments"], hist["coverage_and_segments"]]:
        totals, events = defaultdict(int), defaultdict(int)
        for row in groups:
            totals[row["feature"]] += row["n"]
            events[row["feature"]] += row["events"]
            assert abs(row["rate"] - row["events"] / row["n"]) < 1e-12
            assert 0 <= row["ci95"][0] <= row["rate"] <= row["ci95"][1] <= 1
        assert all(value == info["exploration_rows"] for value in totals.values())
        assert all(value == info["exploration_events"] for value in events.values())
    for name in ["bureau", "bureau_balance", "previous_application", "POS_CASH_balance", "installments_payments", "credit_card_balance"]:
        report = read(name)
        assert report["rows"] > 0
        assert all(0 <= value <= report["rows"] for value in report["missing"].values())
        assert abs(report["labeled_coverage_rate"] - report["labeled_borrowers_covered"] / info["training_rows"]) < 1e-12
    repeated = edges["installment_repeated_keys"]
    assert repeated["consistent_groups_fully_paid_after_summing"] + repeated["consistent_groups_still_underpaid_after_summing"] == repeated["groups_with_consistent_due_and_scheduled_amount"]
    for filename in ["investigation.md", "investigation.html", "figures/investigation-overview.png"]:
        assert (ROOT / "docs/eda" / filename).is_file()
    print("EDA reconciliation passed: partition separation, segment totals/events, confidence intervals, coverage, missingness, and payment-group arithmetic.")


if __name__ == "__main__":
    check()
