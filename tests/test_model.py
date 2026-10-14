import pandas as pd
import pytest

from creditlens.analytics import interval, simulate
from creditlens.model import train
from creditlens.pipeline import run_pipeline
from creditlens.synthetic import generate


def test_disjoint_partitions_and_probability_metrics(tmp_path):
    generate(tmp_path / "raw", rows=1200)
    run_pipeline(tmp_path / "raw", tmp_path / "data")
    report = train(tmp_path / "data", tmp_path / "artifacts")
    splits = pd.read_csv(tmp_path / "artifacts" / "splits.csv")
    assert splits.SK_ID_CURR.is_unique
    assert len(splits) == 1200
    assert set(splits.partition) == {"train", "calibration", "validation", "test"}
    assert "TARGET" not in report["features"]
    assert "SK_ID_CURR" not in report["features"]
    assert "CODE_GENDER" not in report["features"]
    assert report["test"]["brier_score"] >= 0
    scores = pd.read_csv(tmp_path / "artifacts" / "validation_scores.csv")
    assert set(scores.SK_ID_CURR) == set(splits.loc[splits.partition == "validation", "SK_ID_CURR"])
    assert scores.probability.between(0, 1).all()


def test_policy_boundaries_and_expected_events():
    scores = pd.DataFrame({"probability": [0.1, 0.2, 0.8], "AMT_CREDIT": [10, 20, 30], "TARGET": [0, 1, 1]})
    none = simulate(scores, 0)
    assert none["accepted"] == 0
    assert none["average_predicted_risk"] is None
    assert none["expected_difficulty_events"] == 0
    middle = simulate(scores, 0.2)
    assert middle["accepted"] == 2
    assert middle["expected_difficulty_events"] == pytest.approx(0.3)
    assert simulate(scores, 1)["accepted"] == 3
    with pytest.raises(ValueError):
        simulate(scores, float("nan"))


def test_wilson_interval_handles_zero_and_all_events():
    assert interval(0, 0) is None
    assert interval(0, 20)[0] == 0
    assert interval(20, 20)[1] == 1
    assert interval(5, 20)[0] < 0.25 < interval(5, 20)[1]
