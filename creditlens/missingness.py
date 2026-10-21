"""Stage 2: deterministic missingness sidecars, with no fitted imputation."""

import hashlib
import json
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from creditlens.joins import META, READ, TABLES, _json
from creditlens.pipeline import digest

RULE_PATH = Path(__file__).with_name("missingness_rules.json")
RULES = json.loads(RULE_PATH.read_text(encoding="utf-8"))
KEYS = {"SK_ID_CURR", "SK_ID_BUREAU", "SK_ID_PREV"}
EXCLUDED = KEYS | set(META) | {"TARGET"}


def fields(table, columns):
    family = "application" if table.startswith("application_") else table
    categories = set(RULES["categorical_columns"].get(family, []))
    return {name: {"kind": "categorical" if name in categories else "measurement",
                   "missing_flag": name + "__missing", "reason_column": name + "__reason",
                   "prepared_category": name + "__category" if name in categories else None,
                   "conditional_rule": "car_nonownership" if table.startswith("application_") and name == "OWN_CAR_AGE" else None,
                   "imputation": "deferred; no fitted statistics", "reason_codes": RULES["reason_codes"]}
            for name in columns if name not in EXCLUDED}


def annotate(chunk, table, offset=0):
    """Return separate flags/categories; original chunk remains unchanged."""
    definitions = fields(table, chunk.columns)
    data = {"_source_row": pa.array(pd.to_numeric(chunk._source_row).to_numpy(dtype=np.int64)
              if "_source_row" in chunk else np.arange(offset + 1, offset + len(chunk) + 1), type=pa.int64())}
    for column in chunk.columns:
        if column in KEYS or column in {"_join_status", "_parent_status"}:
            data[column] = pa.array(chunk[column], type=pa.string())
    counts = {}
    for column, definition in definitions.items():
        missing = chunk[column].eq("").to_numpy()
        reason = missing.astype(np.uint8)
        conflict_count = 0
        if definition["conditional_rule"] and "FLAG_OWN_CAR" in chunk:
            nonowner = chunk.FLAG_OWN_CAR.eq("N").to_numpy()
            reason[missing & nonowner] = 2
            conflict = nonowner & ~missing
            data[column + "__context_conflict"] = pa.array(conflict, type=pa.bool_())
            conflict_count = int(conflict.sum())
        data[definition["missing_flag"]] = pa.array(missing, type=pa.bool_())
        data[definition["reason_column"]] = pa.array(reason, type=pa.uint8())
        if definition["kind"] == "categorical":
            if chunk[column].eq(RULES["unknown_category"]).any():
                raise ValueError(f"{table}.{column}: reserved unknown-category token already exists in source")
            data[definition["prepared_category"]] = pa.array(chunk[column].where(~missing, RULES["unknown_category"]), type=pa.string())
        counts[column] = {"observed": int((reason == 0).sum()), "unknown_source_blank": int((reason == 1).sum()),
                          "not_applicable_confirmed": int((reason == 2).sum()), "context_conflicts": conflict_count}
    return pa.table(data), counts


def _safe(base, relative):
    resolved = (base / relative).resolve()
    if not resolved.is_relative_to(base.resolve()):
        raise ValueError("Referenced file escapes its run directory")
    return resolved


def select_inputs(source, stage1):
    pointer = json.loads((stage1 / "current.json").read_text(encoding="utf-8"))
    manifest_path = _safe(stage1, pointer["manifest"])
    report = json.loads(manifest_path.read_text(encoding="utf-8"))
    if report["run_id"] != pointer["run_id"] or report["stage"] != 1:
        raise ValueError("Stage 1 pointer does not match its completed manifest")
    run = manifest_path.parent
    inputs = {}
    for name in ["application_train", "application_test"]:
        if name not in report["identity"]["sources"]:
            continue
        path = source / f"{name}.csv"
        expected = report["identity"]["sources"][name]["sha256"]
        if digest(path) != expected:
            raise ValueError(f"{name}: source differs from approved Stage 1 snapshot")
        inputs[name] = {"path": path, "sha256": expected,
                        "rows": report["application_rows"]["labeled" if name == "application_train" else "unlabeled"]}
    for name, totals in report["tables"].items():
        relative = f"matched/{name}.csv.gz"
        entry = report["outputs"][relative]
        path = _safe(run, relative)
        if digest(path) != entry["sha256"]:
            raise ValueError(f"{name}: Stage 1 matched output was modified")
        inputs[name] = {"path": path, "sha256": entry["sha256"], "rows": totals["matched_borrower_rows"]}
    coverage = _safe(run, "coverage/borrowers.csv.gz")
    if digest(coverage) != report["outputs"]["coverage/borrowers.csv.gz"]["sha256"]:
        raise ValueError("Stage 1 coverage checksum differs")
    return report, inputs, coverage, manifest_path


def availability_frame(frame, missing_tables):
    result = frame.copy()
    counts = {}
    for table in TABLES:
        flag = frame[f"has_{table}_history"]
        if table in missing_tables:
            if not flag.eq("").all():
                raise ValueError(f"{table}: absent-source coverage flags are inconsistent")
            status = pd.Series("source_not_supplied", index=frame.index)
        else:
            if not flag.isin(["True", "False"]).all():
                raise ValueError(f"{table}: invalid Stage 1 history-presence flags")
            status = flag.map({"True": "matched_history", "False": "no_matched_history"})
        result[table + "__availability"] = status
        counts[table] = {key: int(value) for key, value in status.value_counts().items()}
    return result, counts


def run_missingness(source: Path, stage1: Path, output: Path, chunksize=100_000, progress=None):
    source, stage1, output = [Path(path).resolve() for path in (source, stage1, output)]
    if chunksize < 1 or any(output == path or output in path.parents for path in [source, stage1]) or output.is_relative_to(stage1):
        raise ValueError("Invalid output location or chunksize")
    emit = progress or (lambda message: None)
    emit("Verifying the selected Stage 1 inputs")
    joined, inputs, coverage, manifest_path = select_inputs(source, stage1)
    identity = {"policy": RULES["version"], "implementation_sha256": digest(Path(__file__)),
                "rules_sha256": digest(RULE_PATH), "stage1_run": joined["run_id"],
                "stage1_manifest_sha256": digest(manifest_path),
                "input_sha256": {name: spec["sha256"] for name, spec in inputs.items()}}
    run_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20]
    output.mkdir(parents=True, exist_ok=True)
    final = output / run_id
    if final.exists():
        report = json.loads((final / "manifest.json").read_text(encoding="utf-8"))
        if report["identity"] != identity:
            raise ValueError("Existing Stage 2 run identity differs")
        for name, spec in report["outputs"].items():
            if digest(final / name) != spec["sha256"]:
                raise ValueError(f"Existing Stage 2 output was modified: {name}")
        _json(output / "current.json", {"run_id": run_id, "manifest": f"{run_id}/manifest.json"})
        return report
    pending = output / (".incomplete-" + uuid.uuid4().hex)
    pending.mkdir()
    report = {"stage": 2, "run_id": run_id, "identity": identity, "tables": {}, "outputs": {},
              "excluded_stage1_rows": {name: value["unmatched_borrower_rows"] for name, value in joined["tables"].items()},
              "scope": "Deterministic missingness annotation only. No learned imputation, target analysis, sentinel conversion, feature removal, or model fitting."}
    dictionary = {"rules": RULES, "tables": {}, "metadata_not_model_inputs": sorted(EXCLUDED),
                  "availability": "Stage 1 matched-history coverage. No matched records is not proof of no borrowing or a zero financial value.",
                  "sidecars": "Original observations are referenced by checksums; sidecar row order and _source_row link to each selected input. Original measurements are not overwritten."}
    for name, spec in inputs.items():
        emit(f"Annotating missingness: {name}")
        columns = [column for column in pd.read_csv(spec["path"], nrows=0).columns if column != "TARGET"]
        definitions = fields(name, columns)
        dictionary["tables"][name] = definitions
        totals = {column: {"observed": 0, "unknown_source_blank": 0, "not_applicable_confirmed": 0, "context_conflicts": 0} for column in definitions}
        filename = name + ".parquet"
        rows, writer = 0, None
        try:
            for chunk in pd.read_csv(spec["path"], usecols=columns, chunksize=chunksize, **READ):
                table, counts = annotate(chunk, name, rows)
                if writer is None:
                    writer = pq.ParquetWriter(pending / filename, table.schema, compression="zstd")
                writer.write_table(table)
                rows += len(chunk)
                for column, values in counts.items():
                    for key, value in values.items():
                        totals[column][key] += value
        finally:
            if writer is not None:
                writer.close()
        if rows != spec["rows"]:
            raise ValueError(f"{name}: Stage 2 row count differs from Stage 1")
        for column, counts in totals.items():
            if counts["observed"] + counts["unknown_source_blank"] + counts["not_applicable_confirmed"] != rows:
                raise ValueError(f"{name}.{column}: reason counts do not reconcile")
        if digest(spec["path"]) != spec["sha256"]:
            raise ValueError(f"{name}: input changed while annotating")
        report["tables"][name] = {"rows": rows, "fields": totals,
                                  "categorical_columns": [column for column, definition in definitions.items() if definition["kind"] == "categorical"],
                                  "source_sha256": spec["sha256"], "rows_preserved": True}
        report["outputs"][filename] = {"rows": rows, "sha256": digest(pending / filename)}
        emit(f"  {rows:,} rows preserved; {len(definitions)} fields documented")
    coverage_frame = pd.read_csv(coverage, **READ)
    if digest(coverage) != joined["outputs"]["coverage/borrowers.csv.gz"]["sha256"]:
        raise ValueError("Stage 1 coverage changed while processing")
    prepared, counts = availability_frame(coverage_frame, joined["missing_tables"])
    pq.write_table(pa.Table.from_pandas(prepared, preserve_index=False), pending / "borrower_availability.parquet", compression="zstd")
    report["availability"] = counts
    report["outputs"]["borrower_availability.parquet"] = {"rows": len(prepared), "sha256": digest(pending / "borrower_availability.parquet")}
    _json(pending / "missingness_dictionary.json", dictionary)
    report["outputs"]["missingness_dictionary.json"] = {"sha256": digest(pending / "missingness_dictionary.json")}
    _json(pending / "manifest.json", report)
    pending.rename(final)
    _json(output / "current.json", {"run_id": run_id, "manifest": f"{run_id}/manifest.json"})
    emit(f"Published Stage 2 run {run_id}")
    return report
