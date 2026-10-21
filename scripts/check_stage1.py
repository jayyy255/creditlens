"""Independently check persisted Stage 1 row partitions and publish safe totals.

Run: python -m scripts.check_stage1
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from creditlens.pipeline import digest

ROOT = Path(__file__).resolve().parents[1]


def check(output: Path, summary: Path | None = None) -> dict:
    pointer = json.loads((output / "current.json").read_text(encoding="utf-8"))
    run = output / pointer["run_id"]
    report = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    read = {"dtype": str, "keep_default_na": False, "na_filter": False}
    coverage = pd.read_csv(run / "coverage/borrowers.csv.gz", usecols=["SK_ID_CURR"], **read)
    assert coverage.SK_ID_CURR.is_unique
    assert len(coverage) == sum(report["application_rows"].values())
    known = set(coverage.SK_ID_CURR)
    result = {"stage": 1, "run_id": report["run_id"], "policy": report["policy"],
              "application_rows": report["application_rows"], "tables": {}, "reverse_anti": report["reverse_anti"],
              "checks": [], "sources": report["identity"]["sources"]}
    for filename, entry in report["outputs"].items():
        assert digest(run / filename) == entry["sha256"], f"Checksum mismatch: {filename}"
    for table, totals in report["tables"].items():
        seen = np.zeros(totals["source_rows"], dtype=bool)
        expected_anti = np.zeros(totals["source_rows"], dtype=bool)
        observed = {}
        for part in ["matched", "unmatched"]:
            filename = f"{part}/{table}.csv.gz"
            n = 0
            for chunk in pd.read_csv(run / filename, usecols=["_source_row", "_join_status", "_parent_status", "SK_ID_CURR"], chunksize=200_000, **read):
                positions = pd.to_numeric(chunk._source_row, errors="raise").to_numpy(dtype=np.int64) - 1
                assert ((positions >= 0) & (positions < len(seen))).all()
                assert len(np.unique(positions)) == len(positions), f"Repeated source rows in {filename}"
                assert not seen[positions].any(), f"Source rows repeated across primary outputs for {table}"
                seen[positions] = True
                if part == "matched":
                    assert chunk.SK_ID_CURR.isin(known).all()
                    assert chunk._join_status.eq("matched_borrower").all()
                    expected_anti[positions] = chunk._parent_status.isin(["parent_not_found", "missing_parent_id"])
                else:
                    assert chunk._join_status.ne("matched_borrower").all() and chunk._join_status.ne("").all()
                n += len(chunk)
            assert n == totals[f"{part}_borrower_rows"]
            observed[part] = n
        assert seen.all(), f"Source rows missing from both outputs for {table}"
        anti_filename = f"anti/missing_previous_application/{table}.csv.gz"
        if anti_filename in report["outputs"]:
            anti_seen = np.zeros(len(seen), dtype=bool)
            for chunk in pd.read_csv(run / anti_filename, usecols=["_source_row", "_join_status", "_parent_status"], chunksize=200_000, **read):
                positions = pd.to_numeric(chunk._source_row, errors="raise").to_numpy(dtype=np.int64) - 1
                assert len(np.unique(positions)) == len(positions) and not anti_seen[positions].any()
                assert chunk._join_status.eq("matched_borrower").all()
                assert chunk._parent_status.isin(["parent_not_found", "missing_parent_id"]).all()
                anti_seen[positions] = True
            assert np.array_equal(anti_seen, expected_anti)
        result["tables"][table] = {**totals, "persisted_source_rows_checked": int(seen.sum()),
                                   "persisted_partition_verified": True}
        print(f"Verified {table}: {observed['matched']:,} matched + {observed['unmatched']:,} unmatched", flush=True)
    for name, reverse in report["reverse_anti"].items():
        assert reverse["accounts"] == reverse["accounts_with_monthly_history"] + reverse["accounts_without_monthly_history"]
        filename = "anti/bureau_without_monthly_history.csv.gz"
        rows = sum(len(chunk) for chunk in pd.read_csv(run / filename, usecols=["SK_ID_BUREAU"], chunksize=200_000, **read))
        assert rows == reverse["accounts_without_monthly_history"]
    result["checks"] = ["Every output checksum matches its manifest", "Borrower coverage IDs are unique",
        "Every historical source row appears exactly once across matched and unmatched outputs",
        "Matched rows have known borrower IDs", "Retained missing-parent diagnostic rows exactly match their subset",
        "Bureau reverse-anti counts reconcile", "All persisted row partitions reconcile"]
    result["scope"] = "Stage 1 verification only. Later stage approvals are tracked separately. This command performs no cleaning or model comparison."
    if summary is not None:
        summary.parent.mkdir(parents=True, exist_ok=True)
        summary.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
        lines = ["# Stage 1 verified join results", "",
            "Matched joins and anti joins have been applied to the actual Home Credit histories. Raw source files, the reserved holdout, and the synthetic serving data remain unchanged. This report covers Stage 1 only; see the current README for subsequent stage approvals.", "",
            "| History | Source rows | Matched borrower rows | Unmatched rows | Retained without previous application |",
            "| --- | ---: | ---: | ---: | ---: |"]
        for name, totals in result["tables"].items():
            lines.append(f"| {name} | {totals['source_rows']:,} | {totals['matched_borrower_rows']:,} | {totals['unmatched_borrower_rows']:,} | {totals['retained_without_previous_application']:,} |")
        lines += ["", "Every historical input record appears exactly once across its matched and unmatched partitions. Missing-previous-application diagnostic files are subsets of retained rows and must not be appended again.", ""]
        for name, reverse in result["reverse_anti"].items():
            lines.append(f"Reverse anti join: **{reverse['accounts_without_monthly_history']:,} bureau accounts** have no monthly records in the supplied monthly file. They remain in the bureau matched output when their borrower is known. {reverse['accounts_with_monthly_history']:,} accounts have monthly history; together these reconcile to {reverse['accounts']:,} source accounts.")
        lines += ["", "## Independent verification", ""] + ["- " + item for item in result["checks"]]
        lines += ["", "Row-level outputs are kept in the ignored `data/stage1/` folder, with `current.json` selecting the completed run. Aggregate evidence and source hashes are in [join-results.json](join-results.json). See [the Stage 1 policy](implementation.md) for output definitions.", ""]
        summary.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "data/stage1")
    parser.add_argument("--summary", type=Path, default=ROOT / "docs/stage1/join-results.json")
    args = parser.parse_args()
    check(args.output, args.summary)
