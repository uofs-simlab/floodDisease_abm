from __future__ import annotations

import argparse
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from graph_generation.graph_generator import generate_baseline_graphs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate infectious-disease diagnostics graphs.")
    parser.add_argument("--run-dir", required=True, help="Path to scenario run root.")
    parser.add_argument("--scenario", default="infectious_disease", help="Scenario folder name.")
    parser.add_argument("--out-subdir", default="infectious_disease_graphs", help="Output subdirectory name.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    generate_baseline_graphs(Path(args.run_dir), args.scenario, args.out_subdir)


if __name__ == "__main__":
    main()
