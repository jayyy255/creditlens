"""Small, deterministic relational fixtures. Never presented as Home Credit results."""

from pathlib import Path

import numpy as np
import pandas as pd


def generate(destination: Path, rows: int = 6000, seed: int = 42) -> None:
    if rows < 500:
        raise ValueError("Generate at least 500 rows for disjoint model evaluation.")
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.glob("*.csv")):
        raise ValueError("Synthetic destination already contains CSVs; choose an empty directory.")
    rng = np.random.default_rng(seed)
    ids = np.arange(100001, 100001 + rows)
    income = rng.lognormal(12.0, 0.45, rows).round(2)
    credit = (income * rng.uniform(1.0, 6.0, rows)).round(2)
    ext = rng.beta(3, 2, rows)
    late = rng.binomial(8, 0.14, rows)
    risk = 1 / (1 + np.exp(-(-3.4 + 0.26 * credit / income + 2.0 * (0.5 - ext) + 0.3 * late)))
    applications = pd.DataFrame({
        "SK_ID_CURR": ids, "TARGET": rng.binomial(1, risk),
        "AMT_INCOME_TOTAL": income, "AMT_CREDIT": credit,
        "AMT_ANNUITY": (credit / rng.uniform(12, 36, rows)).round(2),
        "DAYS_BIRTH": -rng.integers(21 * 365, 70 * 365, rows),
        "DAYS_EMPLOYED": -rng.integers(0, 30 * 365, rows),
        "CODE_GENDER": rng.choice(["F", "M"], rows),
        "NAME_INCOME_TYPE": rng.choice(["Working", "Commercial associate", "Pensioner"], rows, p=[0.6, 0.25, 0.15]),
        "EXT_SOURCE_2": ext,
    })
    applications.loc[rng.choice(rows, rows // 20, replace=False), "EXT_SOURCE_2"] = np.nan
    applications.to_csv(destination / "application_train.csv", index=False)
    historical_ids = np.repeat(ids, 8)
    previous_ids = np.arange(200001, 200001 + rows * 8)
    installment_late = np.concatenate([np.arange(8) < value for value in late])
    due = -rng.integers(30, 1500, len(historical_ids))
    pd.DataFrame({"SK_ID_CURR": historical_ids, "SK_ID_PREV": previous_ids,
                  "DAYS_INSTALMENT": due, "DAYS_ENTRY_PAYMENT": due + installment_late * 10,
                  "AMT_INSTALMENT": 1000, "AMT_PAYMENT": 1000}).to_csv(destination / "installments_payments.csv", index=False)
    bureau_ids = np.arange(300001, 300001 + rows)
    pd.DataFrame({"SK_ID_CURR": ids, "SK_ID_BUREAU": bureau_ids,
                  "DAYS_CREDIT": -rng.integers(30, 2500, rows),
                  "AMT_CREDIT_SUM_DEBT": rng.uniform(0, 200000, rows)}).to_csv(destination / "bureau.csv", index=False)
    pd.DataFrame({"SK_ID_BUREAU": bureau_ids, "MONTHS_BALANCE": -1, "STATUS": "0"}).to_csv(destination / "bureau_balance.csv", index=False)
    pd.DataFrame({"SK_ID_CURR": ids, "SK_ID_PREV": previous_ids[::8],
                  "NAME_CONTRACT_STATUS": rng.choice(["Approved", "Refused"], rows, p=[0.8, 0.2])}).to_csv(destination / "previous_application.csv", index=False)
    pd.DataFrame({"SK_ID_CURR": ids, "SK_ID_PREV": previous_ids[::8], "MONTHS_BALANCE": -1,
                  "SK_DPD": rng.poisson(1, rows)}).to_csv(destination / "POS_CASH_balance.csv", index=False)
    limit = rng.uniform(10000, 100000, rows)
    pd.DataFrame({"SK_ID_CURR": ids, "SK_ID_PREV": previous_ids[::8], "MONTHS_BALANCE": -1,
                  "AMT_BALANCE": limit * rng.uniform(0, 1, rows),
                  "AMT_CREDIT_LIMIT_ACTUAL": limit}).to_csv(destination / "credit_card_balance.csv", index=False)
    (destination / "SYNTHETIC.txt").write_text("Generated CreditLens demonstration data; not Home Credit observations.\n", encoding="utf-8")
