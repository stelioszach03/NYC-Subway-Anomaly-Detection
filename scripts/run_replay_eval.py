#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation.replay import run_replay_evaluation


def main() -> None:
    parser = argparse.ArgumentParser(description="Run historical replay evaluation for subway anomalies")
    parser.add_argument(
        "--input",
        default="evaluation/data/sample_subway_headways.csv",
        help="Path to replay CSV (defaults to the representative sample dataset)",
    )
    parser.add_argument(
        "--out-dir",
        default="docs/generated/replay",
        help="Directory where replay artifacts will be written",
    )
    args = parser.parse_args()

    payload = run_replay_evaluation(dataset_path=Path(args.input), out_dir=Path(args.out_dir))
    summary = {
        "dataset": payload["summary"].get("dataset", {}),
        "methods": payload["metrics"],
        "artifacts_dir": str(Path(args.out_dir)),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
