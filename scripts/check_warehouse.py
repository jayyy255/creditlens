"""Integration check against the dedicated local/CI analytical warehouse."""

import os
from pathlib import Path

import pandas as pd
import psycopg

ROOT = Path(__file__).resolve().parents[1]


def check():
    gold = pd.read_csv(ROOT / "data/gold/borrowers.csv")
    scores = pd.read_csv(ROOT / "artifacts/validation_scores.csv")
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        total, unique_ids, events = connection.execute(
            "SELECT count(*), count(DISTINCT sk_id_curr), sum(target) FROM creditlens.borrowers"
        ).fetchone()
        assert total == unique_ids == len(gold), "Warehouse borrower grain mismatch"
        assert events == int(gold.TARGET.sum()), "Warehouse target sum mismatch"
        assert connection.execute("SELECT count(*) FROM creditlens.validation_scores").fetchone()[0] == len(scores)
        assert connection.execute("SELECT sum(applications) FROM creditlens.segment_risk").fetchone()[0] == total
        for threshold in (0., 0.15, 1.):
            count, expected = connection.execute(
                "SELECT count(*), coalesce(sum(probability), 0) FROM creditlens.validation_scores WHERE probability <= %s",
                (threshold,),
            ).fetchone()
            selected = scores.loc[scores.probability <= threshold]
            assert count == len(selected)
            assert abs(expected - selected.probability.sum()) < 1e-8
        # Execute all advanced analyses and the execution-plan statement.
        cursor = connection.execute((ROOT / "warehouse/analyses.sql").read_text(encoding="utf-8"))
        statements = 0
        while True:
            assert cursor.fetchall(), "An analytical query unexpectedly returned no rows"
            statements += 1
            if not cursor.nextset():
                break
        assert statements == 4
    print("Warehouse grain, targets, materialized view, policy sums, and four SQL analyses verified.")


if __name__ == "__main__":
    check()
