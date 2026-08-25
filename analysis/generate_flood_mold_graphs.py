from __future__ import annotations

import argparse
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from graph_generation.scenario_generators import generate_flood_scenario_graphs


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate flood-and-mold diagnostics graphs.")
    p.add_argument("--run-dir", required=True, help="Path to scenario run root (contains flood_mold/).")
    p.add_argument("--scenario", default="flood_mold", help="Scenario folder name, default flood_mold.")
    p.add_argument("--out-subdir", default="flood_mold_graphs", help="Output subdirectory name under run-dir.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    generate_flood_scenario_graphs(
        run_dir=Path(args.run_dir),
        scenario=args.scenario,
        out_subdir=args.out_subdir,
    )


if __name__ == "__main__":
    main()
