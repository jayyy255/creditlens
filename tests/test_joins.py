import json
from pathlib import Path

import pandas as pd
import pytest

from creditlens.joins import run_joins
from scripts.check_stage1 import check


@pytest.fixture
def source(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    tables = {
        "application_train": pd.DataFrame({"SK_ID_CURR": [1, 2], "TARGET": [0, 1]}),
        "application_test": pd.DataFrame({"SK_ID_CURR": [3]}),
        "bureau": pd.DataFrame({"SK_ID_BUREAU": [10, 11, 12, 13], "SK_ID_CURR": [1, 2, 3, 1],
                                "AMT_CREDIT_SUM_DEBT": [0, -25, 999, 123]}),
        "bureau_balance": pd.DataFrame({"SK_ID_BUREAU": [10, 10, 12, 99, ""], "MONTHS_BALANCE": [-1, -1, 1, -2, -3],
                                        "STATUS": ["0", "0", "X", "NA", "C"]}),
        "previous_application": pd.DataFrame({"SK_ID_PREV": [20, 21], "SK_ID_CURR": [1, 2], "DAYS_FIRST_DUE": [365243, 100]}),
        "POS_CASH_balance": pd.DataFrame({"SK_ID_PREV": [20, 888, 21, 22, ""], "SK_ID_CURR": [1, 2, 1, 999, 3],
                                          "MONTHS_BALANCE": [-1, -2, -3, -4, -5]}),
        "installments_payments": pd.DataFrame({"SK_ID_PREV": [888, 888], "SK_ID_CURR": [2, 2],
                                               "AMT_PAYMENT": [20, 30], "DAYS_ENTRY_PAYMENT": [1, 2]}),
    }
    for name, frame in tables.items():
        frame.to_csv(source / f"{name}.csv", index=False)
    return source


def load(root, report, file):
    return pd.read_csv(root / report["run_id"] / file, dtype=str, keep_default_na=False)


def test_monthly_match_anti_and_reverse_are_reconciled(source, tmp_path):
    root = tmp_path / "stage1"
    report = run_joins(source, root, chunksize=2)
    totals = report["tables"]["bureau_balance"]
    assert totals["source_rows"] == 5
    assert totals["matched_borrower_rows"] == 3
    assert totals["unmatched_borrower_rows"] == 2
    matched = load(root, report, "matched/bureau_balance.csv.gz")
    unmatched = load(root, report, "unmatched/bureau_balance.csv.gz")
    assert list(matched.SK_ID_CURR) == ["1", "1", "3"]
    assert list(unmatched._join_status) == ["parent_not_found", "missing_parent_id"]
    assert list(unmatched.STATUS) == ["NA", "C"]  # Literal category never becomes missing.
    assert set(matched._source_row).isdisjoint(unmatched._source_row)
    assert set(matched._source_row) | set(unmatched._source_row) == {"1", "2", "3", "4", "5"}
    # Duplicate months and future months remain; later-stage decisions are pending.
    assert len(matched) == 3 and "1" in set(matched.MONTHS_BALANCE)
    reverse = load(root, report, "anti/bureau_without_monthly_history.csv.gz")
    assert set(reverse.SK_ID_BUREAU) == {"11", "13"}
    assert set(reverse.SK_ID_BUREAU).issubset(set(load(root, report, "matched/bureau.csv.gz").SK_ID_BUREAU))
    verified = check(root)
    assert verified["tables"]["bureau_balance"]["persisted_source_rows_checked"] == 5


def test_direct_borrower_history_survives_missing_previous_parent(source, tmp_path):
    root = tmp_path / "stage1"
    report = run_joins(source, root, chunksize=2)
    matched = load(root, report, "matched/POS_CASH_balance.csv.gz")
    unmatched = load(root, report, "unmatched/POS_CASH_balance.csv.gz")
    anti = load(root, report, "anti/missing_previous_application/POS_CASH_balance.csv.gz")
    assert list(matched._source_row) == ["1", "2", "5"]
    assert list(anti._source_row) == ["2", "5"]
    assert set(unmatched._join_status) == {"parent_borrower_conflict", "borrower_not_found"}
    assert report["tables"]["POS_CASH_balance"]["retained_without_previous_application"] == 2
    payments = load(root, report, "matched/installments_payments.csv.gz")
    assert list(payments.AMT_PAYMENT) == ["20", "30"]  # No installment aggregation or date filtering.
    previous = load(root, report, "matched/previous_application.csv.gz")
    assert "365243" in set(previous.DAYS_FIRST_DUE)


def test_structural_flags_distinguish_absent_history_and_absent_source(source, tmp_path):
    root = tmp_path / "stage1"
    report = run_joins(source, root)
    coverage = load(root, report, "coverage/borrowers.csv.gz").set_index("SK_ID_CURR")
    assert coverage.loc["2", "has_bureau_history"] == "True"
    assert coverage.loc["2", "has_bureau_balance_history"] == "False"
    assert coverage.loc["2", "has_credit_card_balance_history"] == ""
    assert coverage.loc["3", "is_labeled"] == "False"
    assert coverage.loc["2", "installments_payments_records"] == "2"


@pytest.mark.parametrize("parent,key", [("bureau", "SK_ID_BUREAU"), ("previous_application", "SK_ID_PREV")])
def test_duplicate_parent_keys_rejected_before_publication(source, tmp_path, parent, key):
    path = source / f"{parent}.csv"
    frame = pd.read_csv(path)
    pd.concat([frame, frame.iloc[:1]]).to_csv(path, index=False)
    root = tmp_path / "stage1"
    with pytest.raises(ValueError, match="unique"):
        run_joins(source, root, chunksize=1)
    assert not (root / "current.json").exists()


def test_application_overlap_rejected(source, tmp_path):
    pd.DataFrame({"SK_ID_CURR": [1]}).to_csv(source / "application_test.csv", index=False)
    with pytest.raises(ValueError, match="disjoint"):
        run_joins(source, tmp_path / "out")


def test_chunk_sizes_preserve_rows_and_raw_sources(source, tmp_path):
    original = {path.name: path.read_bytes() for path in source.glob("*.csv")}
    a, b = tmp_path / "a", tmp_path / "b"
    first = run_joins(source, a, chunksize=1)
    second = run_joins(source, b, chunksize=100)
    assert first["run_id"] == second["run_id"]
    assert first["tables"] == second["tables"]
    for file in first["outputs"]:
        pd.testing.assert_frame_equal(load(a, first, file), load(b, second, file))
    assert original == {path.name: path.read_bytes() for path in source.glob("*.csv")}


def test_completed_run_reuse_and_output_tampering_detection(source, tmp_path):
    root = tmp_path / "stage1"
    first = run_joins(source, root)
    assert run_joins(source, root) == first
    pointer = json.loads((root / "current.json").read_text())
    assert pointer["run_id"] == first["run_id"]
    path = root / first["run_id"] / "matched/bureau.csv.gz"
    path.write_bytes(path.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="modified"):
        run_joins(source, root)


def test_missing_bureau_parent_table_preserves_unmapped_months(source, tmp_path):
    (source / "bureau.csv").unlink()
    root = tmp_path / "stage1"
    report = run_joins(source, root)
    assert report["tables"]["bureau_balance"]["matched_borrower_rows"] == 0
    assert report["tables"]["bureau_balance"]["unmatched_borrower_rows"] == 5


def test_parent_with_unknown_borrower_cannot_supply_a_borrower_link(source, tmp_path):
    path = source / "bureau.csv"
    frame = pd.read_csv(path)
    frame.loc[0, "SK_ID_CURR"] = 999
    frame.to_csv(path, index=False)
    root = tmp_path / "stage1"
    report = run_joins(source, root)
    assert report["tables"]["bureau"]["unmatched_borrower_rows"] == 1
    assert report["tables"]["bureau_balance"]["matched_borrower_rows"] == 1
    assert report["tables"]["bureau_balance"]["unmatched_reasons"]["borrower_not_found"] == 2
