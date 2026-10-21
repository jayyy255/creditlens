"""Independently verify every Stage 2 flag/category against immutable inputs."""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from creditlens.joins import READ, TABLES
from creditlens.missingness import EXCLUDED, KEYS, RULES, _safe, select_inputs
from creditlens.pipeline import digest

ROOT = Path(__file__).resolve().parents[1]


def aligned_rows(path, sidecar, chunksize=100_000):
    columns = [column for column in pd.read_csv(path, nrows=0).columns if column != "TARGET"]
    parquet = pq.ParquetFile(sidecar)
    batches = iter(parquet.iter_batches(batch_size=chunksize))
    buffered = pa.Table.from_batches([], schema=parquet.schema_arrow)
    offset = 0
    for raw in pd.read_csv(path, usecols=columns, chunksize=chunksize, **READ):
        while len(buffered) < len(raw):
            next_batch = next(batches, None)
            if next_batch is None:
                raise AssertionError("Sidecar has fewer rows than its source")
            buffered = pa.concat_tables([buffered, pa.Table.from_batches([next_batch])])
        flags = buffered.slice(0, len(raw)).to_pandas()
        buffered = buffered.slice(len(raw))
        yield raw.reset_index(drop=True), flags, offset
        offset += len(raw)
    assert len(buffered) == 0 and next(batches, None) is None, "Sidecar has extra rows"


def check(source, stage1, stage2, summary=None, chunksize=100_000):
    source, stage1, stage2 = map(Path, [source, stage1, stage2])
    pointer = json.loads((stage2 / "current.json").read_text(encoding="utf-8"))
    manifest_path = _safe(stage2, pointer["manifest"])
    run = manifest_path.parent
    report = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert report["run_id"] == pointer["run_id"]
    joined, inputs, coverage_path, joined_manifest = select_inputs(source, stage1)
    assert joined["run_id"] == report["identity"]["stage1_run"], "Stage 2 refers to another Stage 1 run"
    assert digest(joined_manifest) == report["identity"]["stage1_manifest_sha256"]
    assert {name: spec["sha256"] for name, spec in inputs.items()} == report["identity"]["input_sha256"]
    for filename, entry in report["outputs"].items():
        assert digest(run / filename) == entry["sha256"], f"Checksum mismatch: {filename}"
    dictionary = json.loads((run / "missingness_dictionary.json").read_text(encoding="utf-8"))
    assert dictionary["rules"] == RULES
    for name, spec in inputs.items():
        totals = {column: dict.fromkeys(["observed", "unknown_source_blank", "not_applicable_confirmed", "context_conflicts"], 0)
                  for column in dictionary["tables"][name]}
        rows = 0
        for raw, flags, offset in aligned_rows(spec["path"], run / f"{name}.parquet", chunksize):
            columns = set(raw.columns) - EXCLUDED
            assert columns == set(totals)
            assert "TARGET" not in flags and "TARGET__missing" not in flags
            source_rows = pd.to_numeric(raw._source_row).to_numpy(dtype=np.int64) if "_source_row" in raw else np.arange(offset + 1, offset + len(raw) + 1)
            np.testing.assert_array_equal(flags._source_row, source_rows)
            expected_columns = {"_source_row"}
            for column in raw:
                if column in KEYS or column in {"_join_status", "_parent_status"}:
                    assert list(raw[column]) == list(flags[column])
                    expected_columns.add(column)
            family = "application" if name.startswith("application_") else name
            categorical = set(RULES["categorical_columns"].get(family, []))
            for column in columns:
                blank = raw[column].eq("").to_numpy()
                expected = blank.astype(np.uint8)
                conflict = np.zeros(len(raw), dtype=bool)
                if name.startswith("application_") and column == "OWN_CAR_AGE" and "FLAG_OWN_CAR" in raw:
                    nonowner = raw.FLAG_OWN_CAR.eq("N").to_numpy()
                    expected[blank & nonowner] = 2
                    conflict = nonowner & ~blank
                    np.testing.assert_array_equal(flags[column + "__context_conflict"], conflict)
                    expected_columns.add(column + "__context_conflict")
                np.testing.assert_array_equal(flags[column + "__missing"], blank)
                np.testing.assert_array_equal(flags[column + "__reason"], expected)
                expected_columns.update([column + "__missing", column + "__reason"])
                if column in categorical:
                    expected_categories = np.where(blank, RULES["unknown_category"], raw[column])
                    np.testing.assert_array_equal(flags[column + "__category"], expected_categories)
                    expected_columns.add(column + "__category")
                for code, key in [(0, "observed"), (1, "unknown_source_blank"), (2, "not_applicable_confirmed")]:
                    totals[column][key] += int((expected == code).sum())
                totals[column]["context_conflicts"] += int(conflict.sum())
            assert set(flags.columns) == expected_columns, "Undocumented/imputed values unexpectedly stored in sidecar"
            rows += len(raw)
        assert rows == spec["rows"] == report["tables"][name]["rows"]
        assert totals == report["tables"][name]["fields"]
        assert digest(spec["path"]) == spec["sha256"]
        print(f"Verified {name}: {rows:,} rows and every field's flags/categories", flush=True)
    coverage = pd.read_csv(coverage_path, **READ)
    availability = pq.read_table(run / "borrower_availability.parquet").to_pandas()
    for column in coverage:
        assert list(coverage[column]) == list(availability[column])
    for table in TABLES:
        expected = np.full(len(coverage), "source_not_supplied", dtype=object) if table in joined["missing_tables"] else np.where(coverage[f"has_{table}_history"].eq("True"), "matched_history", "no_matched_history")
        np.testing.assert_array_equal(availability[table + "__availability"], expected)
    result = {"stage": 2, "run_id": report["run_id"], "stage1_run": joined["run_id"],
              "policy": RULES["version"], "tables": report["tables"], "availability": report["availability"],
              "excluded_stage1_rows": report["excluded_stage1_rows"],
              "verified_rows": sum(spec["rows"] for spec in inputs.values()),
              "checks": ["All output checksums match", "Every selected source row and its identifiers align",
                         "Every missing flag and reason matches original fields", "Prepared categories preserve all nonblank values",
                         "No target or imputed measurement is present in sidecars", "All field reason counts reconcile",
                         "Original Stage 1 coverage values are preserved", "No matched history is distinct from source not supplied",
                         "Source hashes remain unchanged"],
              "scope": "Stage 2 verified. No numeric imputation or model fitting. Stage 3 and later choices pending."}
    if summary is not None:
        summary = Path(summary)
        summary.parent.mkdir(parents=True, exist_ok=True)
        summary.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
        (summary.parent / "field-dictionary.json").write_text(json.dumps(dictionary, indent=2), encoding="utf-8")
        lines = ["# Stage 2 verified missingness results", "",
            "Semantic missingness annotation is complete on the actual data. Originals are referenced unchanged; flags, reason codes and prepared categorical values are separate sidecars. No numerical imputation was fitted. Stages 3–7 remain pending.", "",
            "| Input | Rows retained | Documented fields | Unknown blank cells | Structurally not-applicable cells |",
            "| --- | ---: | ---: | ---: | ---: |"]
        for name, spec in result["tables"].items():
            counts = spec["fields"]
            lines.append(f"| {name} | {spec['rows']:,} | {len(counts)} | {sum(value['unknown_source_blank'] for value in counts.values()):,} | {sum(value['not_applicable_confirmed'] for value in counts.values()):,} |")
        lines += ["", f"All **{result['verified_rows']:,} selected source rows** and every saved field annotation were checked independently. The input includes both labeled and unlabeled applications; target values are excluded from annotation and verification.", "",
                  "## Application fields to review", "", "| Source | Field | Unknown blanks | Confirmed not applicable | Observed |", "| --- | --- | ---: | ---: | ---: |"]
        for name in ["application_train", "application_test"]:
            for column in ["OWN_CAR_AGE", "EXT_SOURCE_1", "EXT_SOURCE_2", "EXT_SOURCE_3", "OCCUPATION_TYPE", "NAME_INCOME_TYPE"]:
                values = result["tables"].get(name, {}).get("fields", {}).get(column)
                if values:
                    lines.append(f"| {name} | {column} | {values['unknown_source_blank']:,} | {values['not_applicable_confirmed']:,} | {values['observed']:,} |")
        lines += ["", "## Verification", ""] + ["- " + item for item in result["checks"]]
        lines += ["", "Literal special codes and sentinels are retained as observed source values for Stage 3 review. Numeric blanks remain blank in their original sources. No features or applicants were removed for sparse data. Missing occupation is not relabeled as unemployed or retired, and absent housing details are not treated as lack of property ownership.", "",
                  "See [the field dictionary](field-dictionary.json) for column-by-column rules, [aggregate counts](missingness-results.json), and [the Stage 2 implementation](implementation.md) for how to use the local sidecars.", ""]
        summary.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=ROOT / "data")
    parser.add_argument("--stage1", type=Path, default=ROOT / "data/stage1")
    parser.add_argument("--stage2", type=Path, default=ROOT / "data/stage2")
    parser.add_argument("--summary", type=Path, default=ROOT / "docs/stage2/missingness-results.json")
    args = parser.parse_args()
    check(args.source, args.stage1, args.stage2, args.summary)
