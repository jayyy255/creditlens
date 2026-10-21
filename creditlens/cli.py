import argparse
import json
from pathlib import Path

from creditlens.model import train
from creditlens.pipeline import run_pipeline
from creditlens.synthetic import generate
from creditlens.joins import run_joins


def main():
    parser = argparse.ArgumentParser(description="CreditLens reproducible analytics")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Generate synthetic data, ingest, and train")
    demo.add_argument("--rows", type=int, default=6000)
    demo.add_argument("--source", type=Path, default=Path("data/demo-raw"))
    demo.add_argument("--seed", type=int, default=42)
    ingest = commands.add_parser("ingest", help="Validate and aggregate Home Credit CSV files")
    ingest.add_argument("--source", type=Path, default=Path("data/raw"))
    joins = commands.add_parser("joins", help="Stage 1 only: matched and anti joins without cleaning or training")
    joins.add_argument("--source", type=Path, default=Path("data"))
    joins.add_argument("--output", type=Path, default=Path("data/stage1"))
    joins.add_argument("--chunksize", type=int, default=200_000)
    missing = commands.add_parser("missingness", help="Stage 2: semantic missingness sidecars; no numerical imputation")
    missing.add_argument("--source", type=Path, default=Path("data"))
    missing.add_argument("--stage1", type=Path, default=Path("data/stage1"))
    missing.add_argument("--output", type=Path, default=Path("data/stage2"))
    missing.add_argument("--chunksize", type=int, default=100_000)
    commands.add_parser("train", help="Train and evaluate the baseline model")
    for command in (demo, ingest):
        command.add_argument("--data-root", type=Path, default=Path("data"))
    args = parser.parse_args()
    if args.command == "demo":
        # Reuse synthetic input only if its explicit marker exists.
        if not (args.source / "SYNTHETIC.txt").exists():
            generate(args.source, args.rows, args.seed)
        report = run_pipeline(args.source, args.data_root)
        model = train(args.data_root, Path("artifacts"), args.seed)
        print(json.dumps({"data_kind": report["data_kind"], "borrowers": report["gold_rows"], "test_roc_auc": model["test"]["roc_auc"]}, indent=2))
    elif args.command == "ingest":
        print(json.dumps(run_pipeline(args.source, args.data_root), indent=2))
    elif args.command == "joins":
        report = run_joins(args.source, args.output, args.chunksize, progress=lambda message: print(message, flush=True))
        print(json.dumps({"run_id": report["run_id"], "tables": report["tables"], "reverse_anti": report["reverse_anti"]}, indent=2))
    elif args.command == "missingness":
        from creditlens.missingness import run_missingness
        report = run_missingness(args.source, args.stage1, args.output, args.chunksize,
                                 progress=lambda message: print(message, flush=True))
        print(json.dumps({"run_id": report["run_id"], "rows": {name: value["rows"] for name, value in report["tables"].items()}}, indent=2))
    else:
        print(json.dumps(train(Path("data"), Path("artifacts")), indent=2))


if __name__ == "__main__":
    main()
