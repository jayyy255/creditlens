import json

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("pyarrow")
import pyarrow.parquet as pq

from creditlens.joins import run_joins
from creditlens.missingness import RULES, annotate, availability_frame, run_missingness
from scripts.check_stage2 import check


def test_semantic_flags_preserve_sources_and_separate_nonownership():
    raw = pd.DataFrame({"SK_ID_CURR": ["1", "2", "3", "4"], "TARGET": ["0", "1", "0", "1"],
        "FLAG_OWN_CAR": ["N", "Y", "", "N"], "OWN_CAR_AGE": ["", "", "", "8"],
        "EXT_SOURCE_1": ["", "0", "0.8", ""], "DAYS_EMPLOYED": ["365243", "0", "-12", ""],
        "OCCUPATION_TYPE": ["", "NA", "XNA", "NULL"], "NAME_INCOME_TYPE": ["Pensioner", "", "Working", "Working"]})
    untouched = raw.copy(deep=True)
    table, counts = annotate(raw, "application_train")
    flags = table.to_pandas()
    pd.testing.assert_frame_equal(raw, untouched)
    assert "TARGET" not in flags and "TARGET__missing" not in flags
    assert list(flags.OWN_CAR_AGE__reason) == [2, 1, 1, 0]
    assert list(flags.OWN_CAR_AGE__context_conflict) == [False, False, False, True]
    assert list(flags.EXT_SOURCE_1__missing) == [True, False, False, True]
    assert list(flags.OCCUPATION_TYPE__category) == [RULES["unknown_category"], "NA", "XNA", "NULL"]
    assert flags.NAME_INCOME_TYPE__category.iloc[1] == RULES["unknown_category"]
    assert not flags.DAYS_EMPLOYED__missing.iloc[0]  # Sentinel handling is Stage 3.
    assert counts["OWN_CAR_AGE"]["not_applicable_confirmed"] == 1


def test_valid_statuses_and_whitespace_are_not_reclassified():
    raw = pd.DataFrame({"SK_ID_BUREAU": ["10"] * 5, "SK_ID_CURR": ["1"] * 5,
                        "STATUS": ["C", "X", "0", "", " "]})
    prepared, _ = annotate(raw, "bureau_balance")
    frame = prepared.to_pandas()
    assert list(frame.STATUS__missing) == [False, False, False, True, False]
    assert list(frame.STATUS__category) == ["C", "X", "0", RULES["unknown_category"], " "]


def test_reserved_unknown_token_collision_is_not_silent():
    with pytest.raises(ValueError, match="reserved"):
        annotate(pd.DataFrame({"OCCUPATION_TYPE": [RULES["unknown_category"]]}), "application_train")


@pytest.fixture
def prepared(tmp_path):
    source = tmp_path / "raw"
    source.mkdir()
    pd.DataFrame({"SK_ID_CURR": [1, 2, 3], "TARGET": [0, 1, 0],
        "FLAG_OWN_CAR": ["N", "Y", "Y"], "OWN_CAR_AGE": ["", "", "5"],
        "EXT_SOURCE_1": ["", "0", "0.5"], "NAME_INCOME_TYPE": ["Pensioner", "Working", ""],
        "OCCUPATION_TYPE": ["", "NA", "Laborers"], "DAYS_EMPLOYED": [365243, -50, -100]}).to_csv(source / "application_train.csv", index=False)
    pd.DataFrame({"SK_ID_BUREAU": [10, 11], "SK_ID_CURR": [1, 2], "AMT_CREDIT_SUM_DEBT": ["0", ""]}).to_csv(source / "bureau.csv", index=False)
    pd.DataFrame({"SK_ID_BUREAU": [10, 99, 10], "MONTHS_BALANCE": [-1, -2, -3], "STATUS": ["C", "X", ""]}).to_csv(source / "bureau_balance.csv", index=False)
    stage1 = tmp_path / "stage1"
    run_joins(source, stage1, chunksize=1)
    return source, stage1


def test_row_counts_dictionary_and_history_availability(prepared, tmp_path):
    source, stage1 = prepared
    output = tmp_path / "stage2"
    report = run_missingness(source, stage1, output, chunksize=1)
    root = output / report["run_id"]
    assert report["tables"]["application_train"]["rows"] == 3
    assert report["tables"]["bureau_balance"]["rows"] == 2
    assert report["excluded_stage1_rows"]["bureau_balance"] == 1
    apps = pq.read_table(root / "application_train.parquet").to_pandas()
    assert list(apps._source_row) == [1, 2, 3]
    assert list(apps.OWN_CAR_AGE__reason) == [2, 1, 0]
    assert "EXT_SOURCE_1" not in apps  # No invented numeric values or imputed originals.
    months = pq.read_table(root / "bureau_balance.parquet").to_pandas()
    assert list(months._source_row) == [1, 3]  # Stage 1 provenance gaps preserved.
    coverage = pq.read_table(root / "borrower_availability.parquet").to_pandas().set_index("SK_ID_CURR")
    assert coverage.loc["2", "bureau_balance__availability"] == "no_matched_history"
    assert coverage.loc["2", "bureau__availability"] == "matched_history"
    assert coverage.loc["1", "credit_card_balance__availability"] == "source_not_supplied"
    dictionary = json.loads((root / "missingness_dictionary.json").read_text())
    assert dictionary["tables"]["application_train"]["OWN_CAR_AGE"]["conditional_rule"] == "car_nonownership"
    verified = check(source, stage1, output, tmp_path / "report/missingness-results.json", chunksize=2)
    assert verified["verified_rows"] == 7


def test_chunk_boundaries_and_reuse(prepared, tmp_path):
    source, stage1 = prepared
    first = run_missingness(source, stage1, tmp_path / "a", chunksize=1)
    second = run_missingness(source, stage1, tmp_path / "b", chunksize=100)
    assert first["tables"] == second["tables"]
    assert first["run_id"] == second["run_id"]
    for name in first["tables"]:
        assert pq.read_table(tmp_path / "a" / first["run_id"] / f"{name}.parquet").equals(
            pq.read_table(tmp_path / "b" / second["run_id"] / f"{name}.parquet"))
    assert run_missingness(source, stage1, tmp_path / "a") == first


def test_source_or_stage1_changes_are_rejected(prepared, tmp_path):
    source, stage1 = prepared
    path = source / "application_train.csv"
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="differs"):
        run_missingness(source, stage1, tmp_path / "out")


def test_sidecar_tampering_detected(prepared, tmp_path):
    source, stage1 = prepared
    output = tmp_path / "out"
    report = run_missingness(source, stage1, output)
    file = output / report["run_id"] / "bureau.parquet"
    file.write_bytes(file.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="modified"):
        run_missingness(source, stage1, output)
