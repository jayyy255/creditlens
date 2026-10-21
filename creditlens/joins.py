"""Stage 1 only: matched/anti joins, provenance, and lossless row reconciliation.

CSV fields are read as strings with NA inference disabled. Raw observations are
never imputed, deduplicated, filtered by date, or converted to model features.
"""

import gzip
import hashlib
import json
import os
import uuid
from collections import Counter
from contextlib import ExitStack
from pathlib import Path

import numpy as np
import pandas as pd

from creditlens.pipeline import digest

TABLES = ("bureau", "bureau_balance", "previous_application", "POS_CASH_balance",
          "installments_payments", "credit_card_balance")
CHILDREN = {"POS_CASH_balance", "installments_payments", "credit_card_balance"}
META = ["_source_row", "_join_status", "_parent_status"]
READ = {"dtype": str, "keep_default_na": False, "na_filter": False}
POLICY = "stage1-matched-anti-v1"


def _json(path, value):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
    os.replace(temporary, path)


def _parent(path, key, borrower=True):
    columns = [key] + (["SK_ID_CURR"] if borrower and key != "SK_ID_CURR" else [])
    frame = pd.read_csv(path, usecols=columns, **READ)
    if not frame[key].str.fullmatch(r"[1-9]\d*").all() or frame[key].duplicated().any():
        raise ValueError(f"{path.name}: {key} must be unique, non-null, canonical positive integer IDs.")
    return frame


class CsvSink:
    def __init__(self, stack, path, columns):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = stack.enter_context(gzip.open(path, "wt", encoding="utf-8", newline="", compresslevel=1))
        self.columns, self.rows = list(columns), 0
        pd.DataFrame(columns=self.columns).to_csv(self.stream, index=False)

    def append(self, frame):
        if len(frame):
            frame[self.columns].to_csv(self.stream, index=False, header=False)
        self.rows += len(frame)


def run_joins(source: Path, output: Path, chunksize=200_000, progress=None) -> dict:
    """Publish a content-addressed Stage 1 run; leave serving data untouched."""
    source, output = Path(source).resolve(), Path(output).resolve()
    if chunksize < 1:
        raise ValueError("chunksize must be positive")
    if output == source or output in source.parents:
        raise ValueError("Output cannot be the source directory or its ancestor.")
    emit = progress or (lambda message: None)
    paths = {name: source / f"{name}.csv" for name in ("application_train", "application_test") + TABLES
             if (source / f"{name}.csv").exists()}
    if "application_train" not in paths:
        raise ValueError("application_train.csv is required")
    emit("Fingerprinting sources and validating parent keys")
    before = {name: (path.stat().st_size, path.stat().st_mtime_ns) for name, path in paths.items()}
    sources = {name: {"bytes": path.stat().st_size, "sha256": digest(path)} for name, path in paths.items()}
    headers = {name: pd.read_csv(path, nrows=0).columns.tolist() for name, path in paths.items()}
    for name, columns in headers.items():
        if set(columns) & set(META):
            raise ValueError(f"{name}: source contains reserved join metadata columns")
        required = ({"SK_ID_BUREAU"} if name == "bureau_balance" else {"SK_ID_CURR"})
        if name == "bureau":
            required.add("SK_ID_BUREAU")
        if name == "previous_application" or name in CHILDREN:
            required.add("SK_ID_PREV")
        if required - set(columns):
            raise ValueError(f"{name}: missing join keys {sorted(required - set(columns))}")
    if "bureau_balance" in headers and "SK_ID_CURR" in headers["bureau_balance"]:
        raise ValueError("bureau_balance must not provide an ambiguous direct borrower field")
    train = _parent(paths["application_train"], "SK_ID_CURR", borrower=False)
    test = (_parent(paths["application_test"], "SK_ID_CURR", borrower=False)
            if "application_test" in paths else pd.DataFrame(columns=["SK_ID_CURR"]))
    if set(train.SK_ID_CURR) & set(test.SK_ID_CURR):
        raise ValueError("Labeled and unlabeled application IDs must be disjoint")
    borrowers = pd.Index(pd.concat([train.SK_ID_CURR, test.SK_ID_CURR], ignore_index=True))
    parents = {}
    for name, key in [("bureau", "SK_ID_BUREAU"), ("previous_application", "SK_ID_PREV")]:
        if name in paths:
            parents[name] = _parent(paths[name], key).set_index(key).SK_ID_CURR
    identity = {"policy": POLICY, "implementation_sha256": digest(Path(__file__)), "sources": sources}
    run_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20]
    output.mkdir(parents=True, exist_ok=True)
    final = output / run_id
    if final.exists():
        report = json.loads((final / "manifest.json").read_text(encoding="utf-8"))
        if report["identity"] != identity:
            raise ValueError("Existing run identity differs")
        for file, entry in report["outputs"].items():
            if digest(final / file) != entry["sha256"]:
                raise ValueError(f"Existing Stage 1 output was modified: {file}")
        _json(output / "current.json", {"run_id": run_id, "manifest": f"{run_id}/manifest.json"})
        emit(f"Reusing verified completed Stage 1 run {run_id}")
        return report
    pending = output / (".incomplete-" + uuid.uuid4().hex)
    pending.mkdir()
    report = {"stage": 1, "policy": POLICY, "run_id": run_id, "identity": identity,
              "application_rows": {"labeled": len(train), "unlabeled": len(test)},
              "tables": {}, "missing_tables": [name for name in TABLES if name not in paths],
              "outputs": {}, "reverse_anti": {}, "scope": "Joins and structural flags only. No cleaning, feature engineering, target analysis, or training."}
    sinks = {}
    counts = {}
    bureau_seen = np.zeros(len(parents.get("bureau", [])), dtype=bool)
    for name in TABLES:
        if name not in paths:
            continue
        emit(f"Joining {name}")
        columns = headers[name] + (["SK_ID_CURR"] if name == "bureau_balance" else []) + META
        totals = Counter()
        parent_statuses, unmatched_reasons = Counter(), Counter()
        counts[name] = np.zeros(len(borrowers), dtype=np.int64)
        with ExitStack() as stack:
            linked_path = f"matched/{name}.csv.gz"
            unmatched_path = f"unmatched/{name}.csv.gz"
            linked = sinks[linked_path] = CsvSink(stack, pending / linked_path, columns)
            unmatched = sinks[unmatched_path] = CsvSink(stack, pending / unmatched_path, columns)
            anti = None
            if name in CHILDREN:
                anti_path = f"anti/missing_previous_application/{name}.csv.gz"
                anti = sinks[anti_path] = CsvSink(stack, pending / anti_path, columns)
            for chunk in pd.read_csv(paths[name], chunksize=chunksize, **READ):
                start = totals["source_rows"]
                totals["source_rows"] += len(chunk)
                chunk["_source_row"] = np.arange(start + 1, start + len(chunk) + 1)
                reason = pd.Series("", index=chunk.index, dtype=object)
                parent_status = pd.Series("direct_borrower", index=chunk.index, dtype=object)
                if name == "bureau_balance":
                    parent = parents.get("bureau", pd.Series(dtype=str))
                    positions = parent.index.get_indexer(chunk.SK_ID_BUREAU)
                    found = pd.Series(positions >= 0, index=chunk.index)
                    if len(parent):
                        bureau_seen[positions[positions >= 0]] = True
                    chunk["SK_ID_CURR"] = chunk.SK_ID_BUREAU.map(parent).fillna("")
                    parent_status[:] = "matched_parent"
                    parent_status.loc[~found] = "parent_not_found"
                    parent_status.loc[chunk.SK_ID_BUREAU.eq("")] = "missing_parent_id"
                    reason.loc[~found] = parent_status.loc[~found]
                elif name in CHILDREN:
                    parent = parents.get("previous_application", pd.Series(dtype=str))
                    found = chunk.SK_ID_PREV.isin(parent.index)
                    parent_status[:] = "matched_parent"
                    parent_status.loc[~found] = "parent_not_found"
                    parent_status.loc[chunk.SK_ID_PREV.eq("")] = "missing_parent_id"
                    mapped = chunk.SK_ID_PREV.map(parent)
                    conflict = found & chunk.SK_ID_CURR.ne(mapped)
                    reason.loc[conflict] = "parent_borrower_conflict"
                    parent_status.loc[conflict] = "parent_borrower_conflict"
                valid_borrower = chunk.SK_ID_CURR.isin(borrowers)
                # Preserve the missing-parent reason for bureau monthly observations.
                unresolved = reason.eq("") & ~valid_borrower
                reason.loc[unresolved] = "borrower_not_found"
                reason.loc[unresolved & chunk.SK_ID_CURR.eq("")] = "missing_borrower_id"
                keep = reason.eq("") & valid_borrower
                chunk["_parent_status"] = parent_status
                chunk["_join_status"] = np.where(keep, "matched_borrower", reason)
                linked.append(chunk.loc[keep])
                unmatched.append(chunk.loc[~keep])
                retained_anti = keep & parent_status.isin(["parent_not_found", "missing_parent_id"])
                if anti is not None:
                    anti.append(chunk.loc[retained_anti])
                totals["matched_borrower_rows"] += int(keep.sum())
                totals["unmatched_borrower_rows"] += int((~keep).sum())
                totals["retained_without_previous_application"] += int(retained_anti.sum()) if name in CHILDREN else 0
                parent_statuses.update(parent_status.value_counts().to_dict())
                unmatched_reasons.update(reason.loc[~keep].value_counts().to_dict())
                positions = borrowers.get_indexer(chunk.loc[keep, "SK_ID_CURR"])
                np.add.at(counts[name], positions, 1)
            if totals["source_rows"] != linked.rows + unmatched.rows:
                raise RuntimeError(f"{name}: row reconciliation failed")
            if anti is not None and anti.rows != totals["retained_without_previous_application"]:
                raise RuntimeError(f"{name}: retained anti-join reconciliation failed")
        report["tables"][name] = {**dict(totals), "row_reconciliation_passed": True,
                                 "parent_statuses": dict(parent_statuses), "unmatched_reasons": dict(unmatched_reasons)}
        emit(f"  {totals['source_rows']:,} source = {linked.rows:,} matched + {unmatched.rows:,} unmatched")
    if "bureau" in paths:
        filename = "anti/bureau_without_monthly_history.csv.gz"
        columns = headers["bureau"] + META
        with ExitStack() as stack:
            sink = sinks[filename] = CsvSink(stack, pending / filename, columns)
            parent = parents["bureau"]
            offset = 0
            for chunk in pd.read_csv(paths["bureau"], chunksize=chunksize, **READ):
                chunk["_source_row"] = np.arange(offset + 1, offset + len(chunk) + 1)
                offset += len(chunk)
                unseen = ~bureau_seen[parent.index.get_indexer(chunk.SK_ID_BUREAU)]
                chunk["_join_status"] = "no_monthly_history" if "bureau_balance" in paths else "monthly_source_not_supplied"
                chunk["_parent_status"] = "direct_borrower"
                sink.append(chunk.loc[unseen])
        report["reverse_anti"]["bureau"] = {"accounts": len(parent), "accounts_with_monthly_history": int(bureau_seen.sum()),
            "accounts_without_monthly_history": sink.rows, "monthly_source_supplied": "bureau_balance" in paths,
            "reconciliation_passed": len(parent) == int(bureau_seen.sum()) + sink.rows,
            "note": "Diagnostic subset of bureau; these accounts remain in the borrower-matched output when their borrower is valid."}
    coverage = pd.DataFrame({"SK_ID_CURR": borrowers, "is_labeled": [True] * len(train) + [False] * len(test)})
    for name in TABLES:
        coverage[f"{name}_records"] = counts[name] if name in counts else pd.NA
        coverage[f"has_{name}_history"] = counts[name] > 0 if name in counts else pd.NA
    with ExitStack() as stack:
        filename = "coverage/borrowers.csv.gz"
        sink = sinks[filename] = CsvSink(stack, pending / filename, coverage.columns)
        sink.append(coverage)
    for name, path in paths.items():
        if (path.stat().st_size, path.stat().st_mtime_ns) != before[name]:
            raise RuntimeError(f"{name}: source changed during processing; incomplete run not published")
    for file, sink in sinks.items():
        report["outputs"][file] = {"rows": sink.rows, "sha256": digest(pending / file)}
    _json(pending / "manifest.json", report)
    pending.rename(final)
    _json(output / "current.json", {"run_id": run_id, "manifest": f"{run_id}/manifest.json"})
    emit(f"Published Stage 1 run {run_id}")
    return report
