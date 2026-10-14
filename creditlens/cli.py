import argparse
import json
from pathlib import Path

from creditlens.model import train
from creditlens.pipeline import run_pipeline
from creditlens.synthetic import generate


def main():
    parser = argparse.ArgumentParser(description="CreditLens reproducible analytics")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Generate synthetic data, ingest, and train")
    demo.add_argument("--rows", type=int, default=6000)
    demo.add_argument("--source", type=Path, default=Path("data/demo-raw"))
    demo.add_argument("--seed", type=int, default=42)
    ingest = commands.add_parser("ingest", help="Validate and aggregate Home Credit CSV files")
    ingest.add_argument("--source", type=Path, default=Path("data/raw"))
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
    else:
        print(json.dumps(train(Path("data"), Path("artifacts")), indent=2))


if __name__ == "__main__":
    main()
