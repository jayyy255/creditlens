import json

import pandas as pd
import pytest

from creditlens.pipeline import run_pipeline
from creditlens.synthetic import generate


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "raw"
    generate(path, rows=600)
    return path


def test_chunk_boundaries_preserve_aggregation_and_source(source, tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    report = run_pipeline(source, first, chunksize=17)
    run_pipeline(source, second, chunksize=10_000)
    a, b = [pd.read_csv(path / "gold" / "borrowers.csv") for path in [first, second]]
    pd.testing.assert_frame_equal(a, b)
    assert report["data_kind"] == "synthetic"
    assert len(report["sources"]) == 7
    assert report["gold_rows"] == 600
    assert len(list((first / "bronze").glob("*/*.csv"))) == 7


def test_duplicate_applications_rejected(source, tmp_path):
    path = source / "application_train.csv"
    frame = pd.read_csv(path)
    pd.concat([frame, frame.iloc[:1]]).to_csv(path, index=False)
    with pytest.raises(ValueError, match="unique"):
        run_pipeline(source, tmp_path / "out")


def test_orphan_history_rejected(source, tmp_path):
    path = source / "bureau.csv"
    frame = pd.read_csv(path)
    frame.loc[0, "SK_ID_CURR"] = 999999
    frame.to_csv(path, index=False)
    with pytest.raises(ValueError, match="orphan"):
        run_pipeline(source, tmp_path / "out")


def test_future_payments_excluded(source, tmp_path):
    path = source / "installments_payments.csv"
    frame = pd.read_csv(path)
    frame.loc[0, "DAYS_ENTRY_PAYMENT"] = 5
    frame.to_csv(path, index=False)
    result = run_pipeline(source, tmp_path / "out")
    assert result["tables"]["installments_payments"]["excluded_future_or_unknown_date"] == 1


def test_real_sources_never_labeled_synthetic(source, tmp_path):
    (source / "SYNTHETIC.txt").unlink()
    report = run_pipeline(source, tmp_path / "out")
    assert report["data_kind"] == "home-credit"
