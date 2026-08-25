from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import sys
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dataCollection._dataCollect import export_summary, export_timeseries
from config.defaults import MODEL_DEFAULTS, RUN_DEFAULTS, infectious_start_hour
from model._model import Model
from run.support import (
    aggregate_summary_rows,
    aggregate_timeseries_quantiles,
    build_common_model_kwargs,
    prepare_replication_kwargs,
    resolve_data_dir,
)

ROOT = Path(__file__).resolve().parent.parent


def build_common_kwargs(args) -> dict:
    start_hour = infectious_start_hour("flood_infectious", args.baseline_days, args.pre_flood_days, args.flood_days)
    return build_common_model_kwargs(
        args,
        resolve_data_dir(ROOT, args.map),
        extra_kwargs={
            "scenario_mode": "flood_infectious",
            "enable_infectious": 1,
            "enable_stagnant": 0,
            "enable_mold": 0,
            "infectious_seed_start_hour": start_hour,
        },
    )


def run_one(task: dict) -> dict:
    kwargs = prepare_replication_kwargs(task)
    kwargs.update(replication=task["replication"], random_seed=task["seed"])
    kwargs["run_id"] = f"flood_infectious_rep{task['replication']:03d}_seed{task['seed']}"
    model = Model(**kwargs)
    while model.running:
        model.step()
    rep_dir = Path(task["out_root"]) / f"rep_{task['replication']:03d}"
    rep_dir.mkdir(parents=True, exist_ok=True)
    timeseries, _ = export_timeseries(model, rep_dir)
    return {
        "replication": task["replication"],
        "timeseries": timeseries,
        "summary": export_summary(model, rep_dir),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run flood plus infectious disease batches.")
    parser.add_argument("--persons", type=int, default=RUN_DEFAULTS["N_persons"])
    parser.add_argument("--house-mold-rate", type=float, default=MODEL_DEFAULTS["house_mold_rate"])
    parser.add_argument("--business-mold-rate", type=float, default=MODEL_DEFAULTS["business_mold_rate"])
    parser.add_argument("--baseline-days", type=int, default=RUN_DEFAULTS["baseline_days"])
    parser.add_argument("--pre-flood-days", type=int, default=RUN_DEFAULTS["pre_flood_days"])
    parser.add_argument("--flood-days", type=int, default=RUN_DEFAULTS["flood_days"])
    parser.add_argument("--post-flood-days", type=int, default=RUN_DEFAULTS["post_flood_days"])
    parser.add_argument("--replications", type=int, default=RUN_DEFAULTS["replications"])
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--seed-base", type=int, default=RUN_DEFAULTS["seed_base"])
    parser.add_argument("--map", choices=["uvalde"], default="uvalde")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--keep-rep-folders", action="store_true")
    args = parser.parse_args()
    out_root = Path(args.out_dir or ROOT / "outputs" / "flood_infectious" / f"flood_infectious_{args.persons}x{args.replications}").resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    common = build_common_kwargs(args)
    workers = int(args.workers)
    if workers <= 0:
        workers = max(1, os.cpu_count() or 1)
    child_sequences = np.random.SeedSequence(args.seed_base).spawn(max(1, args.replications))
    tasks = []
    for replication in range(args.replications):
        seed = int(child_sequences[replication].generate_state(1, dtype=np.uint32)[0])
        tasks.append(
            {
                "common_kwargs": common,
                "out_root": str(out_root),
                "replication": replication,
                "seed": seed,
            }
        )

    results = []
    print(f"Running flood-infectious batch with {args.replications} replications")
    if workers == 1:
        for task in tasks:
            print(f"  replication {task['replication'] + 1}/{args.replications} seed={task['seed']}")
            results.append(run_one(task))
    else:
        print(f"Running in parallel with {workers} workers across {len(tasks)} tasks")
        with ProcessPoolExecutor(max_workers=workers) as executor:
            future_to_task = {executor.submit(run_one, task): task for task in tasks}
            pending = set(future_to_task)
            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    task = future_to_task[future]
                    try:
                        results.append(future.result())
                    except Exception as exc:
                        print(
                            f"  FAILED (flood-infectious rep {task['replication'] + 1}, "
                            f"seed={task['seed']}): {type(exc).__name__}: {exc}"
                        )
                        continue
                    print(
                        f"  completed {len(results)}/{len(tasks)} "
                        f"(flood-infectious rep {task['replication'] + 1}, seed={task['seed']})"
                    )

    if not results:
        raise RuntimeError("All flood-infectious replications failed; no results were produced")
    results = sorted(results, key=lambda result: result["replication"] if "replication" in result else 0)
    frames = [result["timeseries"] for result in results if isinstance(result["timeseries"], pd.DataFrame)]
    summaries = [result["summary"] for result in results]
    if frames:
        pd.concat(frames, ignore_index=True).to_csv(out_root / "timeseries_all_replications.csv", index=False)
        aggregate_timeseries_quantiles(frames).to_csv(out_root / "timeseries_quantiles.csv", index=False)
    rows = [row for summary in summaries for row in [summary]]
    pd.DataFrame(rows).to_csv(out_root / "summary_by_replication.csv", index=False)
    flat = []
    for summary in summaries:
        row = {}
        for section in ("scenario", "peaks", "totals", "end_state", "auc"):
            for key, value in (summary.get(section, {}) or {}).items():
                row[f"{section}_{key}"] = value.get("value") if isinstance(value, dict) and "value" in value else value
        flat.append(row)
    aggregate_summary_rows(flat, default_scenario="flood_infectious").to_csv(out_root / "summary_stats.csv", index=False)

    if not args.keep_rep_folders:
        for rep_dir in out_root.glob("rep_*"):
            if rep_dir.is_dir():
                shutil.rmtree(rep_dir, ignore_errors=True)

    print(f"Saved flood-infectious outputs to {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
