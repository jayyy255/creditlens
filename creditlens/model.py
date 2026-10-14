"""Whitelisted inputs; disjoint training, calibration, validation, and test populations."""

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.compose import ColumnTransformer
from sklearn.frozen import FrozenEstimator
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from creditlens.pipeline import digest

NUMERIC = ["AMT_INCOME_TOTAL", "AMT_CREDIT", "AMT_ANNUITY", "credit_to_income", "annuity_to_income", "employment_years", "EXT_SOURCE_2",
           "bureau_debt_mean", "late_payment_mean", "previous_refused_mean", "pos_dpd_mean", "card_utilization_mean", "bureau_delinquent_month_mean"]
CATEGORICAL = ["NAME_INCOME_TYPE"]


def evaluate(y, probabilities) -> dict:
    both = len(np.unique(y)) == 2
    observed, predicted = calibration_curve(y, probabilities, n_bins=8, strategy="quantile")
    return {"rows": len(y), "event_rate": float(np.mean(y)),
            "roc_auc": float(roc_auc_score(y, probabilities)) if both else None,
            "average_precision": float(average_precision_score(y, probabilities)) if both else None,
            "brier_score": float(brier_score_loss(y, probabilities)),
            "calibration": [{"predicted": float(p), "observed": float(o)} for p, o in zip(predicted, observed)]}


def train(data_root: Path, artifact_root: Path, seed: int = 42) -> dict:
    gold_path = data_root / "gold" / "borrowers.csv"
    quality = json.loads((data_root / "quality.json").read_text(encoding="utf-8"))
    if digest(gold_path) != quality["gold_sha256"]:
        raise ValueError("Gold data differs from its quality manifest; rerun ingestion.")
    frame = pd.read_csv(gold_path)
    if len(frame) < 500 or frame.TARGET.value_counts().min() < 30:
        raise ValueError("Training requires at least 500 borrowers and 30 observations per class.")
    features = [column for column in NUMERIC if column in frame and frame[column].notna().any()] + CATEGORICAL
    train_idx, remainder = train_test_split(np.arange(len(frame)), test_size=0.4, stratify=frame.TARGET, random_state=seed)
    calibration_idx, remainder = train_test_split(remainder, test_size=0.625, stratify=frame.iloc[remainder].TARGET, random_state=seed)
    validation_idx, test_idx = train_test_split(remainder, test_size=0.6, stratify=frame.iloc[remainder].TARGET, random_state=seed)
    partitions = {"train": train_idx, "calibration": calibration_idx, "validation": validation_idx, "test": test_idx}
    numeric = [column for column in features if column in NUMERIC]
    transform = ColumnTransformer([
        ("numeric", Pipeline([("impute", SimpleImputer(strategy="median", add_indicator=True)), ("scale", StandardScaler())]), numeric),
        ("category", Pipeline([("impute", SimpleImputer(strategy="most_frequent")), ("encode", OneHotEncoder(handle_unknown="ignore"))]), CATEGORICAL),
    ])
    base = Pipeline([("transform", transform), ("classifier", LogisticRegression(max_iter=2000, C=0.5, random_state=seed))])
    base.fit(frame.iloc[train_idx][features], frame.iloc[train_idx].TARGET)
    calibrated = CalibratedClassifierCV(FrozenEstimator(base), method="sigmoid")
    calibrated.fit(frame.iloc[calibration_idx][features], frame.iloc[calibration_idx].TARGET)
    report = {"model": "logistic_regression_sigmoid_calibration", "version": "0.1.0", "seed": seed,
              "features": features, "gold_sha256": digest(gold_path), "partitions": {name: len(index) for name, index in partitions.items()},
              "data_kind": quality["data_kind"]}
    artifact_root.mkdir(parents=True, exist_ok=True)
    (artifact_root / "model_report.json").unlink(missing_ok=True)
    membership = pd.DataFrame({"SK_ID_CURR": frame.SK_ID_CURR, "partition": ""})
    for name, index in partitions.items():
        membership.loc[index, "partition"] = name
    membership.to_csv(artifact_root / "splits.csv", index=False)
    validation = frame.iloc[validation_idx].copy()
    validation["probability"] = calibrated.predict_proba(validation[features])[:, 1]
    validation.to_csv(artifact_root / "validation_scores.csv", index=False)
    report["validation_scores_sha256"] = digest(artifact_root / "validation_scores.csv")
    for name, index in [("validation", validation_idx), ("test", test_idx)]:
        probability = calibrated.predict_proba(frame.iloc[index][features])[:, 1]
        report[name] = evaluate(frame.iloc[index].TARGET, probability)
        baseline = np.full(len(index), frame.iloc[train_idx].TARGET.mean())
        report[name]["constant_baseline"] = evaluate(frame.iloc[index].TARGET, baseline)
    report["subgroups"] = []
    for column in ["CODE_GENDER", "age_band", "NAME_INCOME_TYPE"]:
        for label, group in validation.groupby(column, dropna=False):
            report["subgroups"].append({"column": column, "group": str(label),
                                        "small_sample": bool(len(group) < 100 or group.TARGET.sum() < 20),
                                        **evaluate(group.TARGET, group.probability)})
    # Bootstrap only validation predictions; this interval does not include retraining uncertainty.
    rng = np.random.default_rng(seed)
    aucs = []
    for _ in range(200):
        sample = validation.iloc[rng.integers(0, len(validation), len(validation))]
        if sample.TARGET.nunique() == 2:
            aucs.append(roc_auc_score(sample.TARGET, sample.probability))
    report["validation"]["roc_auc_bootstrap_ci95"] = np.quantile(aucs, [0.025, 0.975]).tolist() if aucs else None
    joblib.dump({"model": calibrated, "features": features, "gold_sha256": report["gold_sha256"]}, artifact_root / "model.joblib")
    (artifact_root / "model_report.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    return report
