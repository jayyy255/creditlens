"""Validated, chunked historical aggregation with source hashes and layer separation."""

import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

APPLICATION_COLUMNS = {
    "SK_ID_CURR", "TARGET", "AMT_INCOME_TOTAL", "AMT_CREDIT", "AMT_ANNUITY",
    "DAYS_BIRTH", "DAYS_EMPLOYED", "CODE_GENDER", "NAME_INCOME_TYPE", "EXT_SOURCE_2",
}
HISTORY = {
    "bureau": {"SK_ID_CURR", "SK_ID_BUREAU", "DAYS_CREDIT", "AMT_CREDIT_SUM_DEBT"},
    "bureau_balance": {"SK_ID_BUREAU", "MONTHS_BALANCE", "STATUS"},
    "previous_application": {"SK_ID_CURR", "DAYS_DECISION", "NAME_CONTRACT_STATUS"},
    "POS_CASH_balance": {"SK_ID_CURR", "MONTHS_BALANCE", "SK_DPD"},
    "installments_payments": {"SK_ID_CURR", "DAYS_INSTALMENT", "DAYS_ENTRY_PAYMENT", "AMT_INSTALMENT", "AMT_PAYMENT"},
    "credit_card_balance": {"SK_ID_CURR", "MONTHS_BALANCE", "AMT_BALANCE", "AMT_CREDIT_LIMIT_ACTUAL"},
}


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def check_columns(path: Path, expected: set) -> None:
    missing = expected - set(pd.read_csv(path, nrows=0).columns)
    if missing:
        raise ValueError(f"{path.name}: missing columns {sorted(missing)}")


def run_pipeline(source: Path, root: Path, chunksize: int = 100_000) -> dict:
    source, root = source.resolve(), root.resolve()
    outputs = [root / layer for layer in ("bronze", "silver", "gold")]
    if source == root or source in root.parents or any(source == output or output in source.parents for output in outputs):
        raise ValueError("Source must be separate from generated layers.")
    app_path = source / "application_train.csv"
    check_columns(app_path, APPLICATION_COLUMNS)
    app = pd.read_csv(app_path, usecols=sorted(APPLICATION_COLUMNS))
    if app.empty or app.SK_ID_CURR.isna().any() or app.SK_ID_CURR.duplicated().any():
        raise ValueError("Applications require unique, non-null borrower IDs and at least one row.")
    if not app.TARGET.isin([0, 1]).all() or app.TARGET.nunique() != 2:
        raise ValueError("TARGET must contain both binary outcomes without missing values.")
    numeric = APPLICATION_COLUMNS - {"CODE_GENDER", "NAME_INCOME_TYPE"}
    for column in numeric:
        app[column] = pd.to_numeric(app[column], errors="raise")
    if not np.isfinite(app[list(numeric)].drop(columns="EXT_SOURCE_2").dropna().to_numpy()).all():
        raise ValueError("Application values must be finite.")
    if (app[["AMT_INCOME_TOTAL", "AMT_CREDIT", "AMT_ANNUITY"]] < 0).any().any():
        raise ValueError("Negative financial amounts are invalid.")
    if (app.DAYS_BIRTH >= 0).any():
        raise ValueError("DAYS_BIRTH must precede application date.")
    known = set(app.SK_ID_CURR)
    test_path = source / "application_test.csv"
    if test_path.exists():
        test_ids = pd.read_csv(test_path, usecols=["SK_ID_CURR"]).SK_ID_CURR
        if test_ids.isna().any() or test_ids.duplicated().any() or known.intersection(test_ids):
            raise ValueError("application_test borrower IDs must be unique, non-null, and disjoint from training.")
        known.update(test_ids)
    report = {"data_kind": "synthetic" if (source / "SYNTHETIC.txt").exists() else "home-credit",
              "application_rows": len(app), "tables": {}, "missing_history": [],
              "application_missing_rates": app.isna().mean().to_dict(), "sources": {}}
    # Validate all source headers before creating any derived output.
    for name, required in HISTORY.items():
        path = source / f"{name}.csv"
        if path.exists():
            check_columns(path, required)
        else:
            report["missing_history"].append(name)
    for layer in ("bronze", "silver", "gold"):
        (root / layer).mkdir(parents=True, exist_ok=True)
    # A failed run cannot leave a success manifest advertising partial new outputs.
    (root / "quality.json").unlink(missing_ok=True)
    paths = [app_path] + [source / f"{name}.csv" for name in HISTORY if (source / f"{name}.csv").exists()]
    if test_path.exists():
        paths.append(test_path)
    for path in paths:
        file_hash = digest(path)
        snapshot = root / "bronze" / file_hash / path.name
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        if not snapshot.exists():
            shutil.copyfile(path, snapshot)
        report["sources"][path.name] = {"sha256": file_hash, "bytes": path.stat().st_size}
    app.DAYS_EMPLOYED = app.DAYS_EMPLOYED.mask(app.DAYS_EMPLOYED == 365243)
    app["credit_to_income"] = app.AMT_CREDIT / app.AMT_INCOME_TOTAL.replace(0, np.nan)
    app["annuity_to_income"] = app.AMT_ANNUITY / app.AMT_INCOME_TOTAL.replace(0, np.nan)
    app["employment_years"] = -app.DAYS_EMPLOYED / 365.25
    app["age_band"] = pd.cut(-app.DAYS_BIRTH / 365.25, [0, 30, 40, 50, 60, np.inf], labels=["Under 30", "30–39", "40–49", "50–59", "60+"], right=False).astype(str)
    app.to_csv(root / "silver" / "applications.csv", index=False)
    gold = app.set_index("SK_ID_CURR")
    bureau_map = None
    for name, required in HISTORY.items():
        path = source / f"{name}.csv"
        if not path.exists():
            continue
        if name == "bureau_balance" and bureau_map is None:
            raise ValueError("bureau_balance requires bureau.csv for borrower mapping.")
        partials, mapping, total, excluded = [], [], 0, 0
        for chunk in pd.read_csv(path, usecols=sorted(required), chunksize=chunksize):
            total += len(chunk)
            key = "SK_ID_CURR" if "SK_ID_CURR" in chunk else "SK_ID_BUREAU"
            if chunk[key].isna().any():
                raise ValueError(f"{name}: null foreign key")
            if name == "bureau_balance":
                chunk["SK_ID_CURR"] = chunk.SK_ID_BUREAU.map(bureau_map)
                if chunk.SK_ID_CURR.isna().any():
                    raise ValueError("bureau_balance has unknown bureau IDs.")
            if not chunk.SK_ID_CURR.isin(known).all():
                raise ValueError(f"{name}: orphan borrower IDs; include application_test.csv when using full Home Credit histories.")
            if name == "bureau":
                mapping.append(chunk[["SK_ID_BUREAU", "SK_ID_CURR"]])
                keep = chunk.DAYS_CREDIT <= 0
                chunk["bureau_debt"] = chunk.AMT_CREDIT_SUM_DEBT
                values = ["bureau_debt"]
            elif name == "installments_payments":
                # Drop future scheduled installments and payments occurring after application.
                keep = (chunk.DAYS_INSTALMENT <= 0) & (chunk.DAYS_ENTRY_PAYMENT <= 0)
                chunk["late_payment"] = np.where(chunk.DAYS_ENTRY_PAYMENT.notna() & chunk.DAYS_INSTALMENT.notna(), (chunk.DAYS_ENTRY_PAYMENT > chunk.DAYS_INSTALMENT).astype(float), np.nan)
                values = ["late_payment"]
            elif name == "previous_application":
                keep = chunk.DAYS_DECISION <= 0
                chunk["previous_refused"] = chunk.NAME_CONTRACT_STATUS.map({"Refused": 1.0, "Approved": 0.0, "Canceled": 0.0, "Unused offer": 0.0})
                values = ["previous_refused"]
            elif name == "POS_CASH_balance":
                keep = chunk.MONTHS_BALANCE <= 0
                chunk["pos_dpd"] = chunk.SK_DPD
                values = ["pos_dpd"]
            elif name == "credit_card_balance":
                keep = chunk.MONTHS_BALANCE <= 0
                chunk["card_utilization"] = chunk.AMT_BALANCE / chunk.AMT_CREDIT_LIMIT_ACTUAL.replace(0, np.nan)
                values = ["card_utilization"]
            else:
                keep = chunk.MONTHS_BALANCE <= 0
                chunk["bureau_delinquent_month"] = chunk.STATUS.astype(str).map({"0": 0., "1": 1., "2": 1., "3": 1., "4": 1., "5": 1.})
                values = ["bureau_delinquent_month"]
            excluded += int((~keep).sum())
            chunk = chunk.loc[keep & chunk.SK_ID_CURR.isin(gold.index)]
            chunk[values] = chunk[values].replace([np.inf, -np.inf], np.nan)
            agg = chunk.groupby("SK_ID_CURR")[values].agg(["sum", "count"])
            agg.columns = [f"{column}_{stat}" for column, stat in agg.columns]
            agg[f"{name}_rows"] = chunk.groupby("SK_ID_CURR").size()
            partials.append(agg)
        if name == "bureau":
            bureau = pd.concat(mapping, ignore_index=True) if mapping else pd.DataFrame(columns=["SK_ID_BUREAU", "SK_ID_CURR"])
            if bureau.SK_ID_BUREAU.isna().any() or bureau.SK_ID_BUREAU.duplicated().any():
                raise ValueError("bureau IDs must be unique and non-null.")
            bureau_map = bureau.set_index("SK_ID_BUREAU").SK_ID_CURR
        if partials:
            combined = pd.concat(partials).groupby(level=0).sum()
            for column in values:
                combined[f"{column}_mean"] = combined[f"{column}_sum"] / combined[f"{column}_count"].replace(0, np.nan)
            gold = gold.join(combined)
        report["tables"][name] = {"rows": total, "excluded_future_or_unknown_date": excluded}
    gold = gold.replace([np.inf, -np.inf], np.nan)
    gold.to_csv(root / "gold" / "borrowers.csv")
    report["gold_rows"] = len(gold)
    report["gold_sha256"] = digest(root / "gold" / "borrowers.csv")
    (root / "quality.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    return report
