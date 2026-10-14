"""Read-only Home Credit investigation. Never modifies source CSVs or serving artifacts.

Counts scan every row. Quantiles are exact for applications and clearly sampled
for history tables. Hash duplicate diagnostics are candidates, not deletion rules.
Run from the repository root: python scripts/investigate_data.py
"""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TABLES = ["bureau", "bureau_balance", "previous_application", "POS_CASH_balance", "installments_payments", "credit_card_balance"]
GRAINS = {
    "bureau": ["SK_ID_BUREAU"], "bureau_balance": ["SK_ID_BUREAU", "MONTHS_BALANCE"],
    "previous_application": ["SK_ID_PREV"], "POS_CASH_balance": ["SK_ID_PREV", "MONTHS_BALANCE"],
    "credit_card_balance": ["SK_ID_PREV", "MONTHS_BALANCE"],
    "installments_payments": ["SK_ID_PREV", "NUM_INSTALMENT_VERSION", "NUM_INSTALMENT_NUMBER"],
}


def log(message):
    print(message, flush=True)


def native(value):
    if isinstance(value, dict):
        return {str(k): native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [native(v) for v in value]
    if isinstance(value, np.generic):
        return native(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(native(value), indent=2, allow_nan=False), encoding="utf-8")


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def wilson(events, n):
    p, z = events / n, 1.959963984540054
    d = 1 + z * z / n
    middle = (p + z * z / (2 * n)) / d
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [max(0., middle - half), min(1., middle + half)]


def rates(values, target, name):
    table = pd.DataFrame({"group": values.astype("object").where(values.notna(), "Missing").astype(str), "target": target})
    out = []
    for label, group in table.groupby("group", observed=True):
        n, events = len(group), int(group.target.sum())
        out.append({"feature": name, "group": label, "n": n, "events": events,
                    "rate": events / n, "ci95": wilson(events, n), "small_sample": n < 500 or events < 20})
    return out


def numeric_profile(series):
    valid = series.replace([np.inf, -np.inf], np.nan).dropna()
    if valid.empty:
        return {"n": 0}
    return {"n": len(valid), "min": valid.min(), "p01": valid.quantile(.01),
            "p25": valid.quantile(.25), "median": valid.median(), "p75": valid.quantile(.75),
            "p99": valid.quantile(.99), "p999": valid.quantile(.999), "max": valid.max(),
            "skew": valid.skew(), "negative": int((valid < 0).sum()), "zero": int((valid == 0).sum())}


def audit_applications(source, private):
    log("Loading applications and reserving a final holdout")
    train = pd.read_csv(source / "application_train.csv")
    test = pd.read_csv(source / "application_test.csv")
    assert train.SK_ID_CURR.is_unique and test.SK_ID_CURR.is_unique
    assert not train.SK_ID_CURR.isna().any() and not test.SK_ID_CURR.isna().any()
    assert set(train.TARGET.unique()) == {0, 1}
    # Dataset identity includes all application values; no target-driven selection.
    identity = sha256(source / "application_train.csv")
    split_path = private / "partition.csv"
    if split_path.exists():
        membership = pd.read_csv(split_path)
        saved = json.loads((private / "partition_manifest.json").read_text())
        if saved["source_sha256"] != identity:
            raise ValueError("Source changed since holdout reservation. Review partition identity before rerunning.")
        assert membership.SK_ID_CURR.is_unique and set(membership.SK_ID_CURR) == set(train.SK_ID_CURR)
    else:
        rng = np.random.default_rng(42)
        membership = train[["SK_ID_CURR"]].copy()
        membership["partition"] = "exploration"
        for outcome in (0, 1):
            index = train.index[train.TARGET == outcome].to_numpy()
            held = rng.permutation(index)[:int(np.ceil(.15 * len(index))) ]
            membership.loc[held, "partition"] = "final_holdout"
        private.mkdir(parents=True, exist_ok=True)
        membership.to_csv(split_path, index=False)
        save(private / "partition_manifest.json", {"source_sha256": identity, "seed": 42, "holdout_fraction": .15,
             "method": "stratified by TARGET, ceil per class; persist and reuse borrower IDs"})
    explore_ids = set(membership.loc[membership.partition == "exploration", "SK_ID_CURR"])
    explore = train.loc[train.SK_ID_CURR.isin(explore_ids)].copy()
    numeric = explore.select_dtypes(include="number").columns.difference(["SK_ID_CURR", "TARGET"])
    profile = {
        "integrity": {"training_rows": len(train), "test_rows": len(test), "training_columns": train.shape[1],
                      "test_columns": test.shape[1], "training_duplicate_ids": int(train.SK_ID_CURR.duplicated().sum()),
                      "test_duplicate_ids": int(test.SK_ID_CURR.duplicated().sum()),
                      "overlap_train_test_ids": len(set(train.SK_ID_CURR) & set(test.SK_ID_CURR)),
                      "training_duplicate_rows": int(train.duplicated().sum()),
                      "test_duplicate_rows": int(test.duplicated().sum()),
                      "schema_difference": sorted(set(train.columns) ^ set(test.columns)),
                      "holdout_rows": int((membership.partition == "final_holdout").sum()),
                      "exploration_rows": len(explore), "exploration_events": int(explore.TARGET.sum()),
                      "exploration_event_rate": explore.TARGET.mean(), "source_sha256": identity},
        "missing": [], "numeric": {}, "categorical": {}, "sentinels": {},
        "target_segments": [], "correlations": [], "shift": [],
    }
    for column in explore.columns.difference(["SK_ID_CURR", "TARGET"]):
        s = explore[column]
        entry = {"column": column, "dtype": str(s.dtype), "unique_nonnull": s.nunique(),
                 "missing": int(s.isna().sum()), "missing_rate": s.isna().mean(),
                 "kaggle_test_missing_rate": test[column].isna().mean()}
        if s.isna().any() and s.notna().any():
            entry["missing_target_rates"] = rates(s.isna().map({True: "Missing", False: "Present"}), explore.TARGET, column)
        profile["missing"].append(entry)
        if column in numeric:
            profile["numeric"][column] = numeric_profile(s)
            if column.startswith("DAYS_"):
                profile["sentinels"][column] = {"sentinel_365243": int((s == 365243).sum()),
                                               "positive": int((s > 0).sum()), "min": s.min(), "max": s.max()}
        else:
            counts = s.fillna("Missing").value_counts()
            profile["categorical"][column] = {"counts": counts.to_dict(), "rare_levels_under_100": int((counts < 100).sum())}
        if column in numeric:
            base = s.mask(s == 365243) if column.startswith("DAYS_") else s
            iqr = base.quantile(.75) - base.quantile(.25)
            profile["shift"].append({"column": column, "kind": "numeric",
                                     "missing_rate_difference": test[column].isna().mean() - s.isna().mean(),
                                     "exploration_median": base.median(), "test_median": test[column].median(),
                                     "median_shift_in_exploration_iqr": (test[column].median() - base.median()) / iqr if iqr else None})
        else:
            p, q = s.fillna("Missing").value_counts(normalize=True), test[column].fillna("Missing").value_counts(normalize=True)
            labels = p.index.union(q.index)
            profile["shift"].append({"column": column, "kind": "categorical",
                                     "total_variation_distance": (p.reindex(labels, fill_value=0) - q.reindex(labels, fill_value=0)).abs().sum() / 2,
                                     "test_only_categories": sorted(set(q.index) - set(p.index))})
    for column in ["NAME_INCOME_TYPE", "NAME_EDUCATION_TYPE", "NAME_CONTRACT_TYPE", "OCCUPATION_TYPE", "CODE_GENDER", "NAME_FAMILY_STATUS"]:
        profile["target_segments"].extend(rates(explore[column], explore.TARGET, column))
    age = -explore.DAYS_BIRTH / 365.25
    profile["target_segments"].extend(rates(pd.cut(age, [0, 30, 40, 50, 60, 100], right=False), explore.TARGET, "age_band"))
    for column in ["AMT_INCOME_TOTAL", "AMT_CREDIT", "AMT_ANNUITY", "EXT_SOURCE_1", "EXT_SOURCE_2", "EXT_SOURCE_3"]:
        profile["target_segments"].extend(rates(pd.qcut(explore[column], 5, duplicates="drop"), explore.TARGET, column + "_quintile"))
    # Analytical candidates only; no production preprocessing or clipping is applied.
    candidates = pd.DataFrame(index=explore.index)
    candidates["credit_to_income"] = explore.AMT_CREDIT / explore.AMT_INCOME_TOTAL.replace(0, np.nan)
    candidates["annuity_to_income"] = explore.AMT_ANNUITY / explore.AMT_INCOME_TOTAL.replace(0, np.nan)
    candidates["credit_to_annuity"] = explore.AMT_CREDIT / explore.AMT_ANNUITY.replace(0, np.nan)
    candidates["age_years"] = age
    candidates["employment_years"] = -explore.DAYS_EMPLOYED.mask(explore.DAYS_EMPLOYED == 365243) / 365.25
    candidates["income_per_family_member"] = explore.AMT_INCOME_TOTAL / explore.CNT_FAM_MEMBERS.replace(0, np.nan)
    profile["candidate_ratios"] = {name: numeric_profile(candidates[name]) for name in candidates}
    profile["candidate_ratio_missing"] = candidates.isna().sum().to_dict()
    for name in ["credit_to_income", "annuity_to_income", "credit_to_annuity"]:
        profile["target_segments"].extend(rates(pd.qcut(candidates[name], 5, duplicates="drop"), explore.TARGET, name + "_quintile"))
    correlation_data = explore[numeric].copy()
    correlation_data["DAYS_EMPLOYED"] = correlation_data.DAYS_EMPLOYED.mask(correlation_data.DAYS_EMPLOYED == 365243)
    correlation_data = pd.concat([correlation_data, candidates], axis=1)
    log("Computing exploration-only rank correlations")
    corr = correlation_data.corr(method="spearman", min_periods=1000)
    for i, a in enumerate(corr.columns):
        for b in corr.columns[i + 1:]:
            if pd.notna(corr.loc[a, b]) and abs(corr.loc[a, b]) >= .90:
                profile["correlations"].append({"a": a, "b": b, "spearman": corr.loc[a, b]})
    profile["correlations"].sort(key=lambda row: -abs(row["spearman"]))
    # Binary target ranks are an affine transform of TARGET, so this is Spearman.
    profile["target_spearman"] = correlation_data.rank().corrwith(explore.TARGET).sort_values().to_dict()
    profile["anomalies"] = {
        "income_nonpositive": int((explore.AMT_INCOME_TOTAL <= 0).sum()),
        "credit_nonpositive": int((explore.AMT_CREDIT <= 0).sum()),
        "annuity_nonpositive": int((explore.AMT_ANNUITY <= 0).sum()),
        "age_under_18_or_over_100": int(((age < 18) | (age > 100)).sum()),
        "employment_longer_than_age": int((candidates.employment_years > age).sum()),
        "employment_exceeds_age_minus_14": int((candidates.employment_years > age - 14).sum()),
        "children_exceed_family_size": int((explore.CNT_CHILDREN > explore.CNT_FAM_MEMBERS).sum()),
        "family_size_zero": int((explore.CNT_FAM_MEMBERS == 0).sum()),
        "external_scores_outside_0_1": {c: int(((explore[c] < 0) | (explore[c] > 1)).sum()) for c in ["EXT_SOURCE_1", "EXT_SOURCE_2", "EXT_SOURCE_3"]},
    }
    profile["employment_sentinel_by_income"] = pd.crosstab(explore.NAME_INCOME_TYPE, explore.DAYS_EMPLOYED == 365243).to_dict()
    # Persist only private population data, never copy it into the public report.
    explore[["SK_ID_CURR", "TARGET"]].to_csv(private / "exploration_target.csv", index=False)
    return train, test, explore, profile


def hash_duplicates(arrays):
    hashes = np.concatenate(arrays) if arrays else np.array([], dtype=np.uint64)
    _, counts = np.unique(hashes, return_counts=True)
    return {"extra_rows": int((counts - 1).sum()), "groups_with_multiple_rows": int((counts > 1).sum()),
            "maximum_multiplicity": int(counts.max()) if counts.size else 0}


def audit_history(name, source, all_ids, train_ids, previous_ids, previous_map, bureau_map, chunksize):
    path = source / f"{name}.csv"
    log(f"Scanning all rows: {name}")
    result = {"rows": 0, "columns": len(pd.read_csv(path, nrows=0).columns), "missing": Counter(),
              "sentinels": Counter(), "positive_dates": Counter(), "negative_amounts": Counter(),
              "numeric_min": {}, "numeric_max": {}, "categorical": {}, "null_borrower_ids": 0,
              "orphan_borrower_rows": 0, "orphan_parent_rows": 0, "parent_borrower_mismatch_rows": 0,
              "grain": GRAINS[name], "diagnostics": Counter(), "sha256": sha256(path)}
    hashes, grain_hashes, samples = [], [], []
    aggregate = None
    new_mapping = []
    for j, chunk in enumerate(pd.read_csv(path, chunksize=chunksize, low_memory=False)):
        result["rows"] += len(chunk)
        result["missing"].update(chunk.isna().sum().to_dict())
        hashes.append(pd.util.hash_pandas_object(chunk, index=False).to_numpy())
        grain_hashes.append(pd.util.hash_pandas_object(chunk[GRAINS[name]], index=False).to_numpy())
        if name == "bureau_balance":
            parent = chunk.SK_ID_BUREAU.map(bureau_map)
            result["orphan_parent_rows"] += int(parent.isna().sum())
            chunk["SK_ID_CURR"] = parent
        result["null_borrower_ids"] += int(chunk.SK_ID_CURR.isna().sum())
        result["orphan_borrower_rows"] += int((~chunk.SK_ID_CURR.isin(all_ids)).sum())
        if "SK_ID_PREV" in chunk and name != "previous_application":
            result["orphan_parent_rows"] += int((~chunk.SK_ID_PREV.isin(previous_ids)).sum())
            mapped = chunk.SK_ID_PREV.map(previous_map)
            result["parent_borrower_mismatch_rows"] += int((mapped.notna() & (mapped != chunk.SK_ID_CURR)).sum())
        if name == "bureau":
            new_mapping.append(chunk[["SK_ID_BUREAU", "SK_ID_CURR"]])
        for column in chunk.select_dtypes(include="number"):
            s = chunk[column]
            if s.notna().any():
                result["numeric_min"][column] = min(result["numeric_min"].get(column, np.inf), s.min())
                result["numeric_max"][column] = max(result["numeric_max"].get(column, -np.inf), s.max())
            if column.startswith("DAYS_"):
                result["sentinels"][column] += int((s == 365243).sum())
                result["positive_dates"][column] += int(((s > 0) & (s != 365243)).sum())
            if column == "MONTHS_BALANCE":
                result["positive_dates"][column] += int((s > 0).sum())
            if column.startswith("AMT_"):
                result["negative_amounts"][column] += int((s < 0).sum())
        for column in chunk.select_dtypes(exclude="number"):
            result["categorical"].setdefault(column, Counter()).update(chunk[column].fillna("Missing").value_counts().to_dict())
        sample = chunk.sample(n=min(1000, len(chunk)), random_state=42 + j).select_dtypes(include="number")
        samples.append(sample.drop(columns=[c for c in sample if c.startswith("SK_ID_")]))
        # Preview aggregations retain observation availability and numerator/denominator separately.
        values = pd.DataFrame({"SK_ID_CURR": chunk.SK_ID_CURR, "records": 1.})
        if name == "bureau":
            values["active_accounts"] = (chunk.CREDIT_ACTIVE == "Active").astype(float)
            values["debt_sum"] = chunk.AMT_CREDIT_SUM_DEBT.fillna(0)
            values["debt_known"] = chunk.AMT_CREDIT_SUM_DEBT.notna().astype(float)
            values["overdue_sum"] = chunk.AMT_CREDIT_SUM_OVERDUE.fillna(0)
            result["diagnostics"]["active_accounts_with_positive_scheduled_enddate"] += int(((chunk.CREDIT_ACTIVE == "Active") & (chunk.DAYS_CREDIT_ENDDATE > 0)).sum())
        elif name == "bureau_balance":
            status = chunk.STATUS.astype(str)
            values["delinquent_months"] = status.isin(["1", "2", "3", "4", "5"]).astype(float)
            values["known_status_months"] = status.isin(["0", "1", "2", "3", "4", "5"]).astype(float)
        elif name == "previous_application":
            values["refused_count"] = (chunk.NAME_CONTRACT_STATUS == "Refused").astype(float)
            values["recent_365_records"] = chunk.DAYS_DECISION.between(-365, 0).astype(float)
            result["diagnostics"]["zero_application_amount"] += int((chunk.AMT_APPLICATION == 0).sum())
            result["diagnostics"]["credit_exceeds_requested"] += int((chunk.AMT_CREDIT > chunk.AMT_APPLICATION).sum())
        elif name == "installments_payments":
            eligible = (chunk.DAYS_INSTALMENT <= 0) & (chunk.DAYS_ENTRY_PAYMENT <= 0)
            values["eligible_payment_records"] = eligible.astype(float)
            values["late_payment_records"] = (eligible & (chunk.DAYS_ENTRY_PAYMENT > chunk.DAYS_INSTALMENT)).astype(float)
            values["row_underpayment_records"] = (eligible & (chunk.AMT_PAYMENT < chunk.AMT_INSTALMENT)).astype(float)
            result["diagnostics"]["missing_payment_date"] += int(chunk.DAYS_ENTRY_PAYMENT.isna().sum())
            result["diagnostics"]["payment_below_scheduled_row_amount"] += int((chunk.AMT_PAYMENT < chunk.AMT_INSTALMENT).sum())
            result["diagnostics"]["payment_above_scheduled_row_amount"] += int((chunk.AMT_PAYMENT > chunk.AMT_INSTALMENT).sum())
        elif name == "POS_CASH_balance":
            values["delinquent_months"] = (chunk.SK_DPD > 0).astype(float)
            values["recent_12_records"] = chunk.MONTHS_BALANCE.between(-12, 0).astype(float)
        else:
            valid_limit = chunk.AMT_CREDIT_LIMIT_ACTUAL > 0
            utilization = chunk.AMT_BALANCE / chunk.AMT_CREDIT_LIMIT_ACTUAL.where(valid_limit)
            values["utilization_sum"] = utilization.fillna(0)
            values["utilization_known"] = utilization.notna().astype(float)
            values["delinquent_months"] = (chunk.SK_DPD > 0).astype(float)
            result["diagnostics"]["zero_limit"] += int((chunk.AMT_CREDIT_LIMIT_ACTUAL == 0).sum())
            result["diagnostics"]["positive_balance_zero_limit"] += int(((chunk.AMT_BALANCE > 0) & (chunk.AMT_CREDIT_LIMIT_ACTUAL == 0)).sum())
            result["diagnostics"]["utilization_over_one"] += int((utilization > 1).sum())
        part = values.groupby("SK_ID_CURR").sum()
        aggregate = part if aggregate is None else aggregate.add(part, fill_value=0)
        if j and j % 20 == 0:
            log(f"  {name}: {result['rows']:,} rows scanned")
    result["row_hash_duplicate_candidates"] = hash_duplicates(hashes)
    result["grain_hash_repetitions"] = hash_duplicates(grain_hashes)
    result["unique_borrowers"] = len(aggregate)
    covered = aggregate.index.intersection(pd.Index(list(train_ids)))
    result["labeled_borrowers_covered"] = len(covered)
    result["labeled_coverage_rate"] = len(covered) / len(train_ids)
    result["records_per_borrower"] = numeric_profile(aggregate.records)
    sampled = pd.concat(samples, ignore_index=True)
    result["sample_quantiles"] = {column: numeric_profile(sampled[column]) for column in sampled}
    result["sample_note"] = "1000 random rows per chunk (seed 42+chunk index); approximate, not uniformly weighted across unequal final chunks. All counts/min/max/missingness use all rows."
    if new_mapping:
        mapping = pd.concat(new_mapping, ignore_index=True)
        result["duplicate_primary_ids"] = int(mapping.SK_ID_BUREAU.duplicated().sum())
        bureau_map = mapping.set_index("SK_ID_BUREAU").SK_ID_CURR
    return result, aggregate, bureau_map


def investigate(source, output, private, chunksize):
    train, test, exploration, applications = audit_applications(source, private)
    save(output / "applications.json", applications)
    log("Application investigation saved")
    all_ids = set(train.SK_ID_CURR) | set(test.SK_ID_CURR)
    previous = pd.read_csv(source / "previous_application.csv", usecols=["SK_ID_PREV", "SK_ID_CURR"])
    previous_ids = set(previous.SK_ID_PREV)
    previous_map = previous.set_index("SK_ID_PREV").SK_ID_CURR
    if not previous_map.index.is_unique:
        raise ValueError("Previous-application IDs are not unique; parent mapping needs investigation first.")
    histories = {}
    merged = exploration[["SK_ID_CURR", "TARGET"]].set_index("SK_ID_CURR")
    bureau_map = None
    for name in TABLES:
        report, aggregate, bureau_map = audit_history(name, source, all_ids, set(train.SK_ID_CURR), previous_ids, previous_map, bureau_map, chunksize)
        histories[name] = report
        save(output / f"{name}.json", report)
        # Preview history associations are exploratory diagnostics, not approved production features.
        prefixed = aggregate.add_prefix(name + "__")
        merged = merged.join(prefixed, how="left")
        log(f"Completed {name}: {report['rows']:,} rows; {report['labeled_coverage_rate']:.1%} labeled borrower coverage")
    summaries = []
    for name in TABLES:
        column = name + "__records"
        summaries.extend(rates(merged[column].notna().map({True: "History present", False: "No matched history"}), merged.TARGET, name + "_coverage"))
    candidate_columns = {
        "bureau_active_accounts": merged["bureau__active_accounts"],
        "bureau_total_debt": merged["bureau__debt_sum"].where(merged["bureau__debt_known"] > 0),
        "bureau_monthly_delinquency_rate": merged["bureau_balance__delinquent_months"] / merged["bureau_balance__known_status_months"].replace(0, np.nan),
        "previous_refusal_rate": merged["previous_application__refused_count"] / merged["previous_application__records"],
        "installment_late_payment_record_rate": merged["installments_payments__late_payment_records"] / merged["installments_payments__eligible_payment_records"].replace(0, np.nan),
        "pos_delinquent_month_rate": merged["POS_CASH_balance__delinquent_months"] / merged["POS_CASH_balance__records"],
        "card_mean_utilization": merged["credit_card_balance__utilization_sum"] / merged["credit_card_balance__utilization_known"].replace(0, np.nan),
    }
    candidates = {}
    for name, values in candidate_columns.items():
        candidates[name] = {"profile": numeric_profile(values), "missing_rate": values.isna().mean(),
                            "target_spearman": values.rank().corr(merged.TARGET)}
        if values.nunique() > 5:
            bins = pd.qcut(values, 5, duplicates="drop")
        else:
            bins = values
        summaries.extend(rates(bins, merged.TARGET, name))
    save(output / "historical_associations.json", {"coverage_and_segments": summaries, "candidates": candidates})
    save(output / "manifest.json", {"source_directory": "data/", "run_kind": "read-only exploratory investigation",
          "full_scans": ["application_train", "application_test"] + TABLES,
          "exploration_rows": len(exploration), "holdout_rows": applications["integrity"]["holdout_rows"],
          "source_files": {name + ".csv": {"bytes": (source / f"{name}.csv").stat().st_size, "sha256": histories[name]["sha256"]} for name in TABLES},
          "limits": ["No raw values are modified", "No models trained", "No final holdout target associations inspected", "No production features selected", "64-bit hash duplicates are candidate diagnostics; no rows dropped", "Historical features are provisional previews, not approved marts"]})
    log("Investigation complete. Raw inputs, existing demo data, and model artifacts remain unchanged.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=ROOT / "data")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/eda/results")
    parser.add_argument("--private", type=Path, default=ROOT / "artifacts/eda")
    parser.add_argument("--chunksize", type=int, default=200_000)
    args = parser.parse_args()
    investigate(args.source, args.output, args.private, args.chunksize)
