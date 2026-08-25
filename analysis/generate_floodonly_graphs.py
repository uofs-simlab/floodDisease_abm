from __future__ import annotations

import argparse
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from graph_generation.scenario_generators import generate_flood_scenario_graphs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate flood-family diagnostics graphs.")
    parser.add_argument("--run-dir", required=True, help="Path to scenario run root.")
    parser.add_argument("--scenario", default="flood_only", help="Flood-family scenario folder name.")
    parser.add_argument("--out-subdir", default=None, help="Output subdirectory name.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    generate_flood_scenario_graphs(Path(args.run_dir), args.scenario, args.out_subdir)


if __name__ == "__main__":
    main()
