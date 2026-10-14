"""Render aggregate-only investigation results into a seven-stage review report."""

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "docs/eda/results"
OUT = ROOT / "docs/eda"


def read(name):
    return json.loads((RESULTS / f"{name}.json").read_text(encoding="utf-8"))


def num(value):
    if value is None:
        return "n.a."
    return f"{value:,.0f}" if abs(value) >= 100 else f"{value:,.3g}"


def pct(value):
    return "n.a." if value is None else f"{value:.2%}"


def table(headers, rows):
    def cell(value):
        return str(value).replace("|", "/").replace("\n", " ")
    return "\n".join(["| " + " | ".join(map(cell, headers)) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"] + ["| " + " | ".join(map(cell, row)) + " |" for row in rows]) + "\n"


def build():
    app, associations, edges = read("applications"), read("historical_associations"), read("edge_cases")
    names = ["bureau", "bureau_balance", "previous_application", "POS_CASH_balance", "installments_payments", "credit_card_balance"]
    histories = {name: read(name) for name in names}
    integrity = app["integrity"]
    blocks = []
    def add(text):
        blocks.append(text.strip() + "\n")
    add("# CreditLens: seven-stage dataset investigation")
    add("Date: 14 October 2026. Source: the supplied Home Credit CSV files in `data/`, interpreted with the supplied column-description CSV. All observations below are computed from those local files. This is an investigation, not an applied cleaning policy or model comparison.")
    add(f"**Population:** {integrity['training_rows']:,} labeled applications and {integrity['test_rows']:,} unlabeled applications. A fixed, stratified final holdout of **{integrity['holdout_rows']:,} borrowers** is reserved locally. Target relationships use only the **{integrity['exploration_rows']:,} exploration borrowers**, including {integrity['exploration_events']:,} target events ({pct(integrity['exploration_event_rate'])}). Row counts, structural checks and historical scans cover full source tables. Application distributions and correlations use the exploration population unless stated otherwise.")
    add("The holdout is not yet wired into the existing demo training command. Before real-data modeling, that command must be changed to reuse `artifacts/eda/partition.csv` rather than creating a fresh final test split. No target-based final-holdout diagnostics or model evaluation were performed in this investigation.")
    add("![Overview of actual-data investigation](figures/investigation-overview.png)")
    add("## 1. Data integrity and relationships")
    rows = [["application_train", num(integrity["training_rows"]), integrity["training_columns"], "Labeled application", "100%"], ["application_test", num(integrity["test_rows"]), integrity["test_columns"], "Unlabeled application", "n.a."]]
    for name, data in histories.items():
        rows.append([name, num(data["rows"]), data["columns"], ", ".join(data["grain"]), pct(data["labeled_coverage_rate"])])
    add(table(["Table", "Rows", "Columns", "Investigated grain", "Labeled borrower coverage"], rows))
    add(f"Application IDs: {integrity['training_duplicate_ids']:,} repeated training IDs; {integrity['test_duplicate_ids']:,} repeated test IDs; {integrity['overlap_train_test_ids']:,} IDs shared between training and unlabeled test. Full-row duplicates: training {integrity['training_duplicate_rows']:,}, unlabeled test {integrity['test_duplicate_rows']:,}. Schema difference: {', '.join(integrity['schema_difference'])}.")
    add(table(["History", "Orphan borrower rows", "Unmatched parent rows", "Parent/borrower mismatch", "Repeated row-hash extras", "Repeated grain extras"], [[name, num(d["orphan_borrower_rows"]), num(d["orphan_parent_rows"]), num(d["parent_borrower_mismatch_rows"]), num(d["row_hash_duplicate_candidates"]["extra_rows"]), num(d["grain_hash_repetitions"]["extra_rows"])] for name, d in histories.items()]))
    add("History duplicate diagnostics use 64-bit pandas hashes across all chunks. They identify candidates, not a deletion rule; collisions are possible and grain repetitions can be legitimate observations. For installments, the candidate grain excludes individual payment transactions, so repeated schedule keys must not automatically be removed. Missing history means no matched records in this dataset, not proof of no prior borrowing.")
    add(f"**Important join finding:** {histories['bureau_balance']['orphan_parent_rows']:,} bureau-month rows cannot be mapped to the supplied bureau table. Their borrower is consequently unknown, not a directly observed invalid borrower ID. Other child tables contain valid direct borrower IDs even where their previous-contract ID is absent from previous_application. These are incomplete cross-table links, not automatically corrupt payment records. The current demo ingestion command rejects unmatched bureau parents and would fail on these actual source files; that policy needs an approved revision before a real-data run.")
    add("**Decision 1:** recommendation: keep all source rows in raw storage, report incomplete parent links separately, retain directly borrower-linked child records for eligible aggregation, and quarantine unmappable bureau-month records from borrower features. Do not blanket-deduplicate or use inner joins that silently discard unmatched history. Cause of missing parent coverage is not established by these files.")
    add("## 2. Missing-value investigation")
    missing = sorted(app["missing"], key=lambda row: row["missing_rate"], reverse=True)
    for threshold in [.3, .5, .7]:
        add(f"Predictor columns with exploration missingness above {threshold:.0%}: **{sum(row['missing_rate'] > threshold for row in missing)}**.")
    add(table(["Column", "Exploration missing", "Unlabeled test missing", "Unique non-null values"], [[row["column"], pct(row["missing_rate"]), pct(row["kaggle_test_missing_rate"]), num(row["unique_nonnull"])] for row in missing[:20]]))
    selected = [row for row in missing if row["column"] in ["EXT_SOURCE_1", "EXT_SOURCE_2", "EXT_SOURCE_3", "OCCUPATION_TYPE", "OWN_CAR_AGE", "AMT_ANNUITY"]]
    add(table(["Important column", "Missing", "Observed target rate if missing", "Observed target rate if present"], [[row["column"], pct(row["missing_rate"]), pct(next((r["rate"] for r in row.get("missing_target_rates", []) if r["group"] == "Missing"), None)), pct(next((r["rate"] for r in row.get("missing_target_rates", []) if r["group"] == "Present"), None))] for row in selected]))
    add("Differences between missing/present groups are unadjusted associations. They do not prove that missingness causes repayment difficulty or that imputation will improve a model. Missing-not-at-random mechanisms cannot be established from this table alone.")
    add(table(["Owns car", "Exploration borrowers", "Missing car age", "Missing share"], [[name, num(d["borrowers"]), num(d["missing_car_age"]), pct(d["missing_rate"])] for name, d in edges["car_age_missingness"].items()]))
    add("Car-age missingness should therefore be interpreted alongside car ownership instead of filling every missing age with a general median.")
    add("**Decision 2:** options are semantic imputation plus indicators, native missing-value handling for supported tree models, or removal of selected sparse features. Recommendation: retain useful external-score features despite missingness; treat housing-feature families as a group for a later ablation. Do not automatically drop every column above a fixed missingness percentage. Training-only imputation must be fitted later, after the user selects an approach.")
    add("## 3. Sentinels, dates and unusual values")
    add(table(["Application date column", "365243 sentinel count", "Positive including sentinel", "Minimum", "Maximum"], [[name, num(d["sentinel_365243"]), num(d["positive"]), num(d["min"]), num(d["max"])] for name, d in app["sentinels"].items()]))
    add(table(["Application check", "Exploration rows"], [[name, num(count)] for name, count in app["anomalies"].items() if not isinstance(count, dict)]))
    employment = app["employment_sentinel_by_income"]
    add(table(["Income category", "Employment sentinel present", "Sentinel absent"], [[name, num(employment.get("True", {}).get(name, 0)), num(employment.get("False", {}).get(name, 0))] for name in employment.get("False", {})]))
    date_rows, amount_rows = [], []
    for name, data in histories.items():
        for column, count in data["sentinels"].items():
            if count:
                date_rows.append([name, column, "365243", num(count)])
        for column, count in data["positive_dates"].items():
            if count:
                date_rows.append([name, column, "Positive, excluding sentinel", num(count)])
        for column, count in data["negative_amounts"].items():
            if count:
                amount_rows.append([name, column, num(count), num(data["numeric_min"][column])])
    add(table(["History", "Date field", "Condition", "Rows"], date_rows))
    add(table(["History", "Amount field", "Negative rows", "Minimum"], amount_rows))
    add("Positive **scheduled** credit end dates can legitimately be known at application time. Positive actual-payment, actual-end, update, or termination dates need a separate availability review. Future scheduled dates are not inherently leakage, but actual outcomes observed after the application would be. Negative account balances or payments may reflect credits/reversals and require semantic review rather than automatic deletion.")
    add("**Decision 3:** recommendation: make a field-specific sentinel and date-availability map. Convert the employment sentinel to missing only after preserving a separate indicator; examine its concentration in pensioners before interpretation. Keep valid scheduled-future obligations. Quarantine suspect actual-future observations for review. No records have been altered.")
    add("## 4. Distributions, skew and outliers")
    selected_numeric = ["AMT_INCOME_TOTAL", "AMT_CREDIT", "AMT_ANNUITY", "AMT_GOODS_PRICE", "CNT_CHILDREN", "CNT_FAM_MEMBERS", "OWN_CAR_AGE", "EXT_SOURCE_1", "EXT_SOURCE_2", "EXT_SOURCE_3"]
    add(table(["Feature", "Min", "Median", "99th percentile", "99.9th percentile", "Max", "Skew"], [[name] + [num(app["numeric"][name].get(key)) for key in ["min", "median", "p99", "p999", "max", "skew"]] for name in selected_numeric]))
    add(table(["Candidate ratio", "Median", "99th percentile", "Max", "Missing rows"], [[name, num(d.get("median")), num(d.get("p99")), num(d.get("max")), num(app["candidate_ratio_missing"][name])] for name, d in app["candidate_ratios"].items()]))
    add(table(["Additional exploration check", "Borrowers"], [[f"Income above {int(boundary):,}", num(count)] for boundary, count in edges["extreme_income"].items()] + [["Annuity/income above 1", num(edges["annuity_income_over_one"])]]))
    add("Application quantiles above are exact on the exploration population. Historical quantiles in the supporting JSON use 1,000 random rows per chunk and are approximate; history counts, missingness, minimums and maximums scan all rows. Monetary units are those supplied by the dataset; no currency conversion or denomination is assumed.")
    add("Income and annuity ratios are descriptive features. The supplied descriptions do not establish harmonized reporting periods for these amounts, so no annualization factor or regulatory debt-service ratio is assumed. Confirm period semantics before giving these ratios a lending-policy interpretation.")
    add("**Decision 4:** options are retain raw values, log-transform valid nonnegative amounts, or cap selected extremes using training-derived thresholds. Recommendation: retain an untouched raw feature and compare a log version for linear models; investigate extreme income before deciding whether a cap or quarantine is justified. Avoid deleting all outliers using a blanket IQR rule. Do not label credit/annuity as contractual tenor.")
    add("## 5. Target relationships and borrower segments")
    add("All rates below use the exploration population. Intervals are 95% Wilson intervals. They are exploratory, unadjusted for other variables and multiple comparisons. Small or rare groups are flagged rather than treated as reliable rankings.")
    segments = app["target_segments"]
    for column in ["NAME_INCOME_TYPE", "NAME_EDUCATION_TYPE", "age_band", "EXT_SOURCE_2_quintile", "credit_to_income_quintile", "annuity_to_income_quintile"]:
        add("### " + column)
        add(table(["Group", "Borrowers", "Events", "Event rate", "95% interval", "Small sample"], [[r["group"], num(r["n"]), num(r["events"]), pct(r["rate"]), f"{pct(r['ci95'][0])} to {pct(r['ci95'][1])}", "Yes" if r["small_sample"] else "No"] for r in segments if r["feature"] == column]))
    target_corr = sorted(app["target_spearman"].items(), key=lambda row: -(abs(row[1]) if row[1] is not None else -1))[:15]
    add(table(["Numeric feature", "Spearman association with target"], [[name, num(value)] for name, value in target_corr]))
    add("**Decision 5:** recommendation: use these findings to form hypotheses and prespecified features, not to build rules that automatically reject borrower groups. Keep age/gender and related sensitive categories available for descriptive/subgroup diagnostics; select any model inputs deliberately. Defer adjusted regression and formal hypothesis testing until the cleaning, missingness and variable-selection plan is agreed. Univariate associations are not model performance.")
    add("## 6. Historical grain and aggregation investigation")
    add(table(["History", "Labeled coverage", "Median rows per borrower", "99th percentile rows", "Maximum rows"], [[name, pct(d["labeled_coverage_rate"]), num(d["records_per_borrower"].get("median")), num(d["records_per_borrower"].get("p99")), num(d["records_per_borrower"].get("max"))] for name, d in histories.items()]))
    add(table(["History", "Diagnostic", "Rows"], [[name, key, num(value)] for name, data in histories.items() for key, value in data["diagnostics"].items()]))
    add("### Repeated installment keys: focused follow-up")
    add(table(["Diagnostic", "Count"], [[key, num(value)] for key, value in edges["installment_repeated_keys"].items() if isinstance(value, int)]))
    add("Payment-sum comparisons use a 0.01 dataset-unit tolerance. Fully paid here means only that the sum of recorded payments reaches the repeated scheduled amount; it is not proof of contractual settlement. These checks determine whether a per-row underpayment feature would misclassify split payments.")
    repeated = edges["installment_repeated_keys"]
    add(f"**Material result:** all {repeated['repeated_key_groups']:,} repeated installment-key groups have one consistent due date and scheduled amount. After summing their payment records, {repeated['consistent_groups_fully_paid_after_summing']:,} groups reach the scheduled amount and only {repeated['consistent_groups_still_underpaid_after_summing']:,} remain below it at the stated tolerance. Yet {repeated['rows_underpaid_when_compared_individually']:,} constituent records appear underpaid if compared individually. This is strong evidence for treating repeated keys as payment components, not duplicate installments or independent underpayments.")
    add(table(["Provisional borrower feature", "Missing", "Median", "99th percentile", "Target Spearman"], [[name, pct(d["missing_rate"]), num(d["profile"].get("median")), num(d["profile"].get("p99")), num(d["target_spearman"])] for name, d in associations["candidates"].items()]))
    add("The installment lateness preview is explicitly **payment-record-weighted**, not a final installment-level delinquency measure. Credit-card utilization is calculated only where the limit is positive. Debt sums preserve a known-debt count so all-missing debt cannot silently become zero. Bureau status X/C is excluded from the known 0–5 status denominator. Preview associations are provisional and have not been inserted into the production mart.")
    add("**Decision 6:** recommendation: aggregate bureau balances to account first, monthly balances to previous contract, and payments to a validated installment grain, then aggregate to borrower. For installment-level paid status, sum recorded payments once per schedule key and retain the scheduled amount once. Investigate the time when cumulative payments reach the scheduled amount for lateness, retaining an unknown state for missing dates and incomplete payments. Compare lifetime summaries with recent 6/12/24-month summaries only after validating relative dates and coverage. Keep history-presence flags and valid-value denominators. Avoid direct joins between raw child tables.")
    add("## 7. Redundancy, categories and preparation choices")
    add(f"There are **{len(app['correlations']):,} numeric predictor pairs with absolute Spearman correlation at least 0.90**, after excluding IDs/TARGET and masking the employment sentinel for this diagnostic. This includes deterministic derived age/employment conversions and housing-feature variants. The full pair list is in the supporting results; selecting representatives is still a user decision.")
    add(table(["Feature A", "Feature B", "Spearman"], [[r["a"], r["b"], num(r["spearman"])] for r in app["correlations"][:20]]))
    cats = sorted(app["categorical"].items(), key=lambda item: -len(item[1]["counts"]))
    add(table(["Category", "Levels including missing", "Levels with fewer than 100 exploration rows"], [[name, len(data["counts"]), data["rare_levels_under_100"]] for name, data in cats]))
    binary = []
    cardinality = {row["column"]: row["unique_nonnull"] for row in app["missing"]}
    for name, data in app["numeric"].items():
        if cardinality.get(name) == 2 and data.get("min") == 0 and data.get("max") == 1 and data.get("n"):
            minority = min(data["zero"], data["n"] - data["zero"])
            if minority / data["n"] < .001:
                binary.append([name, num(minority), pct(minority / data["n"])])
    add("Very sparse binary predictors (minority state below 0.1%):")
    add(table(["Feature", "Minority-state observations", "Minority share"], binary))
    shift = sorted([r for r in app["shift"] if r["kind"] == "categorical"], key=lambda r: -r["total_variation_distance"])
    add(table(["Category", "Exploration/test distribution distance", "Test-only levels"], [[r["column"], pct(r["total_variation_distance"]), ", ".join(r["test_only_categories"]) or "None"] for r in shift[:8]]))
    missing_shift = sorted(app["missing"], key=lambda r: -abs(r["kaggle_test_missing_rate"] - r["missing_rate"]))[:10]
    add(table(["Feature", "Exploration missing", "Unlabeled test missing", "Test minus exploration (percentage points)"], [[r["column"], pct(r["missing_rate"]), pct(r["kaggle_test_missing_rate"]), f"{100 * (r['kaggle_test_missing_rate'] - r['missing_rate']):+.2f}"] for r in missing_shift]))
    add("Distribution distances are descriptive total variation on category frequencies. They can flag covariate differences; they cannot establish performance drift without labels. Test distributions were inspected for diagnostics, not used to fit imputation, encodings or thresholds.")
    add("**Decision 7:** recommendation: create one versioned borrower-feature contract, then allow model-specific preprocessing. Use training-fitted imputation/one-hot encoding/scaling for a linear baseline, and separately consider native missing/categorical handling for eligible tree models. Review rare levels and nearly redundant housing/region fields. Do not globally encode or scale all data before splitting, and do not automatically remove every correlated variable.")
    add("## Decisions to agree before implementation")
    add(table(["Stage", "Suggested starting choice", "Alternative to consider", "Status"], [
        [1, "Keep directly borrower-linked records; quarantine unmappable bureau months", "Stricter exclusion with explicit coverage loss", "Awaiting user choice"],
        [2, "Semantic missingness + presence flags; preserve external scores", "Native missing handling; sparse-family ablation", "Awaiting user choice"],
        [3, "Field-specific sentinel/date rules", "Quarantine ambiguous dates rather than delete", "Awaiting user choice"],
        [4, "Preserve raw values; propose logs for linear models", "Selective training-fitted caps after extreme-value review", "Awaiting user choice"],
        [5, "Exploratory hypotheses and subgroup diagnostics", "Adjusted analysis after preprocessing agreement", "Awaiting user choice"],
        [6, "Contract/installment aggregation before borrower aggregation", "Recent-window features after availability review", "Awaiting user choice"],
        [7, "Shared feature definitions, separate model preprocessing", "Smaller interpretable feature family for baseline", "Awaiting user choice"],
    ]))
    add("A better sequence is to agree stages 1–3 first, because grain and sentinel meanings change the distributions and features in stages 4–7. Then implement an approved feature specification and compare preprocessing alternatives inside training/validation only. No user decision is inferred from elapsed time or from a recommendation in this report.")
    add("## Reproduction and evidence")
    add("Run `python scripts/investigate_data.py`, then `python scripts/investigate_edge_cases.py`, `python scripts/plot_eda.py`, and `python scripts/render_eda_report.py` from the repository root. The investigation requires pandas/NumPy; plotting additionally requires matplotlib. Source fingerprints, counts and detailed aggregate profiles are under `results/`. Partition membership and exploration target IDs remain local under the ignored `artifacts/eda/` folder. The existing dashboard still serves the synthetic demo. No real-data model was trained, no cleaning choices were applied, and raw CSVs are ignored by Git.")
    text = "\n".join(blocks)
    (OUT / "investigation.md").write_text(text, encoding="utf-8")
    # A buildless local report; escaped source prevents arbitrary HTML injection.
    rendered = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("| "):
            group = []
            while i < len(lines) and lines[i].startswith("| "):
                group.append(lines[i]); i += 1
            rendered.append('<div class="scroll"><table>')
            for j, row in enumerate(group):
                if j == 1:
                    continue
                tag = "th" if j == 0 else "td"
                rendered.append("<tr>" + "".join(f"<{tag}>{html.escape(c.strip())}</{tag}>" for c in row.strip("|").split("|")) + "</tr>")
            rendered.append("</table></div>")
            continue
        elif line.startswith("!["):
            rendered.append('<img src="figures/investigation-overview.png" alt="Overview of actual-data investigation" style="width:100%;height:auto">')
        elif line.startswith("#"):
            depth = len(line) - len(line.lstrip("#"))
            rendered.append(f"<h{depth}>{html.escape(line[depth:].strip())}</h{depth}>")
        elif line.strip():
            escaped = html.escape(line)
            # Only our own simple emphasis and inline-code syntax is supported.
            import re
            escaped = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", escaped)
            escaped = re.sub(r"`(.*?)`", r"<code>\1</code>", escaped)
            rendered.append("<p>" + escaped + "</p>")
        i += 1
    document = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CreditLens data investigation</title><style>body{font:15px/1.65 system-ui,sans-serif;color:#23372f;background:#f5f7f3;max-width:1150px;margin:40px auto;padding:0 24px}h1{font-size:34px}h2{border-top:2px solid #cddccf;padding-top:26px;margin-top:44px;color:#206747}h3{font-size:17px}.scroll{overflow:auto;margin:20px 0}table{border-collapse:collapse;width:100%;font-size:12px;background:white}th,td{padding:10px 12px;border:1px solid #dee5da;text-align:left}th{background:#e6eee0}tr:nth-child(even){background:#f8faf6}code{background:#e9eee5;padding:2px 4px}strong{color:#155d3e}</style><main>' + "\n".join(rendered) + "</main></html>"
    (OUT / "investigation.html").write_text(document, encoding="utf-8")
    print(f"Wrote {OUT / 'investigation.md'}")


if __name__ == "__main__":
    build()
