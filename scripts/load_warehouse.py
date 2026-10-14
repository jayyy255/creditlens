"""Load the local analytical snapshot into a dedicated CreditLens PostgreSQL schema."""

import json
import os
from pathlib import Path

import pandas as pd
import psycopg

from creditlens.pipeline import digest

ROOT = Path(__file__).resolve().parents[1]
COLUMNS = ["sk_id_curr", "target", "amt_income_total", "amt_credit", "amt_annuity", "credit_to_income", "annuity_to_income", "age_band", "code_gender", "name_income_type", "late_payment_mean", "bureau_debt_mean", "data_kind"]


def load():
    gold = ROOT / "data/gold/borrowers.csv"
    quality = json.loads((ROOT / "data/quality.json").read_text(encoding="utf-8"))
    report = json.loads((ROOT / "artifacts/model_report.json").read_text(encoding="utf-8"))
    scores = ROOT / "artifacts/validation_scores.csv"
    if digest(gold) != quality["gold_sha256"] or digest(gold) != report["gold_sha256"] or digest(scores) != report["validation_scores_sha256"]:
        raise ValueError("Snapshots are inconsistent; run ingestion and training first.")
    frame = pd.read_csv(gold).rename(columns=str.lower)
    frame["data_kind"] = quality["data_kind"]
    frame = frame.reindex(columns=COLUMNS).astype(object).where(lambda table: table.notna(), None)
    validation = pd.read_csv(scores, usecols=["SK_ID_CURR", "probability"])
    validation = validation[["SK_ID_CURR", "probability"]]
    # This is an atomic refresh of this project's dedicated analytical tables.
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute((ROOT / "warehouse/001_initial.sql").read_text(encoding="utf-8"))
        connection.execute("TRUNCATE creditlens.validation_scores, creditlens.borrowers")
        with connection.cursor().copy(f"COPY creditlens.borrowers ({','.join(COLUMNS)}) FROM STDIN") as stream:
            for row in frame.itertuples(index=False, name=None):
                stream.write_row(row)
        with connection.cursor().copy("COPY creditlens.validation_scores (sk_id_curr, probability) FROM STDIN") as stream:
            for row in validation.itertuples(index=False, name=None):
                stream.write_row(row)
        connection.execute("REFRESH MATERIALIZED VIEW creditlens.segment_risk")
        connection.execute("ANALYZE creditlens.borrowers")
        connection.execute("ANALYZE creditlens.validation_scores")
    print(f"Loaded {len(frame):,} borrowers and {len(validation):,} policy validation scores.")


if __name__ == "__main__":
    load()
