from __future__ import annotations

import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.defaults import MODEL_DEFAULTS, RUN_DEFAULTS
import json
import os
import subprocess
import shutil
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

_VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
if os.environ.get("FLOODDISEASE_ABM_BOOTSTRAPPED") != "1" and _VENV_PYTHON.exists() and Path(sys.executable).resolve() != _VENV_PYTHON.resolve():
    os.environ["FLOODDISEASE_ABM_BOOTSTRAPPED"] = "1"
    os.execv(str(_VENV_PYTHON), [str(_VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]])

import numpy as np
import pandas as pd
sys.path.append(str(ROOT))

from run.support import (
    aggregate_summary_rows,
    aggregate_timeseries_quantiles,
    build_common_model_kwargs,
    build_progress_snapshot,
    check_remote_progress,
    flatten_summary,
    format_hms,
    prepare_replication_kwargs,
    has_local_timeseries,
    launch_remote_batch,
    pull_results_from_remote,
    resolve_data_dir,
    sync_repo_to_remote,
    wait_for_remote_timeseries,
)

try:
    from dataCollection._dataCollect import export_summary, export_timeseries
    from model._model import Model
except ImportError as e:
    Model = None
    export_summary = None
    export_timeseries = None
    IMPORT_ERROR = str(e)

DATA = resolve_data_dir(ROOT, "uvalde")


def build_common_kwargs(args) -> dict:
    return build_common_model_kwargs(
        args,
        resolve_data_dir(ROOT, args.map),
        extra_kwargs={
            "scenario_mode": "flood_mold",
        },
    )


def run_one_replication(task: dict) -> dict:
    kwargs = prepare_replication_kwargs(task)
    kwargs["replication"] = task["replication"]
    kwargs["random_seed"] = task["seed"]
    kwargs["run_id"] = f"flood_mold_rep{task['replication']:03d}_seed{task['seed']}"

    model = Model(**kwargs)
    while model.running:
        model.step()

    out_root = Path(task["out_root"])
    rep_dir = out_root / f"rep_{task['replication']:03d}"
    rep_dir.mkdir(parents=True, exist_ok=True)

    timeseries_df, _ = export_timeseries(model, rep_dir)
    summary = export_summary(model, rep_dir)
    flat = flatten_summary(summary)

    return {
        "replication": task["replication"],
        "seed": task["seed"],
        "out_dir": str(rep_dir),
        "timeseries_df": timeseries_df,
        "summary_row": flat,
    }


def orchestrate_remote_flood_mold(args):
    """Run the flood-mold pipeline remotely, monitor progress, pull results, and generate graphs."""
    print("[ORCHESTRATION] Starting remote flood-and-mold pipeline...")
    target = args.remote_target.lower()
    user = args.remote_user
    password = args.remote_password
    remote_repo = args.remote_repo

    experiment_name = f"flood_mold_{args.persons}x{args.replications}"
    remote_out_dir = f"outputs/flood_mold/{experiment_name}"

    print(f"[1/4] Syncing code and launching remote batch run on {target}...")
    try:
        if not sync_repo_to_remote(
            local_root=ROOT,
            target=target,
            user=user,
            password=password,
            remote_repo=remote_repo,
        ):
            return False

        batch_args = (
            f"--persons {args.persons} "
            f"--replications {args.replications} "
            f"--workers 12 "
            f"--seed-base {args.seed_base}"
        )

        if args.out_dir:
            batch_args += f" --out-dir {args.out_dir}"
        else:
            batch_args += f" --out-dir {remote_out_dir}"

        if not launch_remote_batch(
            target=target,
            user=user,
            password=password,
            remote_repo=remote_repo,
            batch_args=batch_args,
            runner="flood_mold",
            session_name=f"flood_mold_{args.persons}x{args.replications}_{target}",
            kill_existing_session=True,
            clean_output_dir=remote_out_dir,
        ):
            print("[WARN] Python SSH launcher failed, falling back to PowerShell launcher (may prompt for password).")
            sync_script = HERE / ".." / "scripts" / "run_remote_batch_via_tux.ps1"
            if not sync_script.exists():
                print(f"[ERR] Fallback script not found: {sync_script}")
                return False

            ps_cmd = [
                "powershell",
                "-NoProfile",
                "-Command",
                f"& {sync_script} "
                f"-Target {target} "
                f"-TargetUser {user} "
                f"-Runner flood_mold "
                f"-BatchArgs '{batch_args}'",
            ]
            result = subprocess.run(ps_cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                print(f"[ERR] Fallback launch failed: {result.stderr}")
                return False
            if result.stdout.strip():
                print(result.stdout)
        print("[OK] Remote run launched")
    except Exception as e:
        print(f"[ERR] Could not launch remote run: {e}")
        return False

    print("[2/4] Polling remote progress (every 5 min)...")
    poll_interval = 300
    max_polls = 240
    poll_count = 0
    missed_progress_checks = 0
    max_missed_progress_checks = 3

    while poll_count < max_polls:
        time.sleep(poll_interval)
        poll_count += 1

        progress = check_remote_progress(
            target=target,
            user=user,
            password=password,
            remote_repo=remote_repo,
            remote_out_dir=remote_out_dir,
        )

        if progress is None:
            missed_progress_checks += 1
            if missed_progress_checks == 1:
                print(f"[{poll_count}] Could not read progress (may still be running)...")
            else:
                print(f"[{poll_count}] Progress still unavailable ({missed_progress_checks}/{max_missed_progress_checks})...")
            if missed_progress_checks >= max_missed_progress_checks:
                print("[WARN] Progress polling unavailable; waiting for remote timeseries files before pull.")
                ready = wait_for_remote_timeseries(
                    target=target,
                    user=user,
                    password=password,
                    remote_repo=remote_repo,
                    remote_out_dir=remote_out_dir,
                    max_wait_seconds=3600,
                    poll_seconds=120,
                )
                if not ready:
                    print("[ERR] Remote outputs still missing aggregated timeseries files; aborting pull/graph steps.")
                    return False
                print("[OK] Remote timeseries detected; continuing.")
                break
            continue
        missed_progress_checks = 0

        percent = progress.get("percent", 0)
        completed = progress.get("completed", 0)
        total = progress.get("total", 0)
        remaining = progress.get("remaining", max(0, total - completed))
        elapsed = progress.get("elapsed_seconds", 0)
        eta = progress.get("eta_seconds", 0)
        rate_h = progress.get("rate_tasks_per_hour")
        rss = progress.get("driver_rss_gb")

        rate_txt = f" rate={rate_h:.2f}/hr" if isinstance(rate_h, (int, float)) else ""
        rss_txt = f" rss={rss:.2f}GB" if isinstance(rss, (int, float)) else ""
        print(
            f"[{poll_count}] Progress: {completed}/{total} remaining={remaining} ({percent:.1f}%) "
            f"elapsed={format_hms(elapsed)} eta={format_hms(eta)}{rate_txt}{rss_txt}"
        )

        if percent >= 100.0:
            print("[OK] Remote run completed!")
            break
    else:
        print(f"[WARN] Max polls ({max_polls}) reached, continuing with pull...")

    print(f"[3/4] Downloading results from {target}...")
    if args.out_dir:
        local_out_dir = Path(args.out_dir).resolve()
    else:
        local_out_dir = (ROOT / "outputs" / "flood_mold" / experiment_name).resolve()

    if not pull_results_from_remote(
        target=target,
        user=user,
        password=password,
        remote_repo=remote_repo,
        remote_out_dir=remote_out_dir,
        local_out_dir=local_out_dir,
    ):
        print("[ERR] Failed to pull results")
        return False

    if not has_local_timeseries(local_out_dir):
        print(f"[ERR] Pull completed but no timeseries CSV files were found under {local_out_dir}")
        return False

    print("[4/4] Generating flood-and-mold graphs...")
    try:
        graph_script = ROOT / "analysis" / "generate_flood_mold_graphs.py"
        if not graph_script.exists():
            print(f"[WARN] Graph script not found: {graph_script}")
        else:
            cmd = [
                sys.executable,
                str(graph_script),
                "--run-dir", str(local_out_dir),
                "--scenario", "flood_mold",
                "--out-subdir", "flood_mold_graphs",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                print(f"[OK] Graphs generated in {local_out_dir}/flood_mold_graphs/")
            else:
                print(f"[WARN] Graph generation had issues: {result.stderr}")
    except Exception as e:
        print(f"[WARN] Could not generate graphs: {e}")

    print(f"[OK] Orchestration complete! Results in {local_out_dir}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Run flood-and-mold replicated batches with clean flood-and-mold outputs.")
    parser.add_argument("--persons", type=int, default=RUN_DEFAULTS["N_persons"])
    parser.add_argument("--house-mold-rate", type=float, default=MODEL_DEFAULTS["house_mold_rate"])
    parser.add_argument("--business-mold-rate", type=float, default=MODEL_DEFAULTS["business_mold_rate"])
    parser.add_argument("--baseline-days", type=int, default=RUN_DEFAULTS["baseline_days"])
    parser.add_argument("--pre-flood-days", type=int, default=RUN_DEFAULTS["pre_flood_days"])
    parser.add_argument("--flood-days", type=int, default=RUN_DEFAULTS["flood_days"])
    parser.add_argument("--post-flood-days", type=int, default=RUN_DEFAULTS["post_flood_days"])
    parser.add_argument("--replications", type=int, default=RUN_DEFAULTS["replications"])
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of parallel worker processes. Use 0 to auto-detect CPU count.",
    )
    parser.add_argument("--heartbeat-seconds", type=int, default=60, help="Progress heartbeat interval in seconds.")
    parser.add_argument("--seed-base", type=int, default=RUN_DEFAULTS["seed_base"])
    parser.add_argument("--map", type=str, default="uvalde", choices=["uvalde"], help="Map data folder to use.")
    parser.add_argument(
        "--gov-baseline-grant-every-hours",
        type=int,
        default=None,
        help="Optional override for government baseline grant cadence (hours). Default comes from Model.",
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default=None,
        help=(
            "Output directory. If omitted, outputs are written under "
            "ROOT/outputs/flood_mold/flood_mold_<persons>x<replications>."
        ),
    )
    parser.add_argument(
        "--keep-rep-folders",
        action="store_true",
        help="Keep flood-and-mold rep_XXX folders. By default, replication folders are cleaned up after aggregation.",
    )
    parser.add_argument(
        "--gottlieb",
        action="store_true",
        help="Run on Gottlieb HPC (shorthand for --remote --remote-target gottlieb).",
    )
    parser.add_argument(
        "--richardson",
        action="store_true",
        help="Run on Richardson HPC (shorthand for --remote --remote-target richardson).",
    )
    parser.add_argument(
        "--hundsdorfer",
        action="store_true",
        help="Run on Hundsdorfer HPC (shorthand for --remote --remote-target hundsdorfer).",
    )
    parser.add_argument(
        "--remote",
        action="store_true",
        help="Enable orchestration: sync code, run remotely, poll progress every 5 min, pull results, and generate graphs.",
    )
    parser.add_argument(
        "--remote-target",
        type=str,
        default="gottlieb",
        choices=["gottlieb", "richardson", "hundsdorfer"],
        help="Remote HPC target for orchestration (gottlieb, richardson, or hundsdorfer).",
    )
    parser.add_argument(
        "--remote-user",
        type=str,
        default="oaa721",
        help="Remote HPC username for SSH.",
    )
    parser.add_argument(
        "--remote-password",
        type=str,
        default=os.environ.get("FLOODDISEASE_ABM_REMOTE_PASSWORD"),
        help="Remote HPC password for SSH. May also be supplied through FLOODDISEASE_ABM_REMOTE_PASSWORD.",
    )
    parser.add_argument(
        "--remote-repo",
        type=str,
        default="floodDisease_abm",
        help="Remote repository name (folder name in /scratch-gladwell/...).",
    )
    args = parser.parse_args()

    if args.gottlieb:
        args.remote = True
        args.remote_target = "gottlieb"
    elif args.richardson:
        args.remote = True
        args.remote_target = "richardson"
    elif args.hundsdorfer:
        args.remote = True
        args.remote_target = "hundsdorfer"

    if args.remote:
        success = orchestrate_remote_flood_mold(args)
        return 0 if success else 1

    if Model is None or export_summary is None or export_timeseries is None:
        print(f"[ERR] Cannot run local flood-and-mold: {IMPORT_ERROR}")
        print("[ERR] For remote orchestration, use: python run/flood_mold.py --persons 350 --replications 12 --gottlieb")
        return 1

    if args.out_dir:
        out_root = Path(args.out_dir).resolve()
    else:
        experiment_name = f"flood_mold_{args.persons}x{args.replications}"
        out_root = (ROOT / "outputs" / "flood_mold" / experiment_name).resolve()

    out_root.mkdir(parents=True, exist_ok=True)
    progress_file = out_root / "_progress.json"

    common_kwargs = build_common_kwargs(args)
    workers = int(args.workers)
    if workers <= 0:
        workers = max(1, os.cpu_count() or 1)
    heartbeat_seconds = max(1, int(args.heartbeat_seconds))

    seed_seq = np.random.SeedSequence(args.seed_base)
    child_sequences = seed_seq.spawn(max(1, args.replications))
    tasks = []
    for replication in range(args.replications):
        seed = int(child_sequences[replication].generate_state(1, dtype=np.uint32)[0])
        tasks.append(
            {
                "common_kwargs": common_kwargs,
                "out_root": str(out_root),
                "replication": replication,
                "seed": seed,
            }
        )

    print(f"Running flood-and-mold batch with {args.replications} replications")

    started_at = time.time()
    results = []

    if workers == 1:
        for task in tasks:
            print(f"  replication {task['replication'] + 1}/{args.replications} seed={task['seed']}")
            result = run_one_replication(task)
            results.append(result)
            snapshot = build_progress_snapshot(len(results), len(tasks), started_at)
            with open(progress_file, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=2)
    else:
        print(f"Running in parallel with {workers} workers across {len(tasks)} tasks")
        with ProcessPoolExecutor(max_workers=workers) as executor:
            future_to_task = {executor.submit(run_one_replication, task): task for task in tasks}
            pending = set(future_to_task.keys())
            completed = 0
            last_heartbeat = 0.0
            while pending:
                done, pending = wait(pending, timeout=heartbeat_seconds, return_when=FIRST_COMPLETED)

                for future in done:
                    task = future_to_task[future]
                    completed += 1
                    try:
                        result = future.result()
                    except Exception as exc:
                        print(
                            f"  FAILED (flood-mold rep {task['replication'] + 1}, "
                            f"seed={task['seed']}): {type(exc).__name__}: {exc}"
                        )
                        continue
                    print(
                        f"  completed {completed}/{len(tasks)} "
                        f"(flood-and-mold rep {task['replication'] + 1}, seed={task['seed']})"
                    )
                    results.append(result)

                now = time.time()
                if done or (now - last_heartbeat) >= heartbeat_seconds:
                    snapshot = build_progress_snapshot(completed, len(tasks), started_at)
                    elapsed_s = snapshot["elapsed_seconds"]
                    rate_h = snapshot["rate_tasks_per_hour"]
                    eta_s = snapshot["eta_seconds"]
                    rss = snapshot["driver_rss_gb"]
                    rss_txt = f" rss={rss:.2f}GB" if rss is not None else ""
                    print(
                        f"[progress] done={snapshot['completed']}/{snapshot['total']} "
                        f"({snapshot['percent']:.1f}%) elapsed={format_hms(elapsed_s)} "
                        f"rate={rate_h:.2f}/hr eta={format_hms(eta_s)}{rss_txt}"
                    )
                    with open(progress_file, "w", encoding="utf-8") as f:
                        json.dump(snapshot, f, ensure_ascii=False, indent=2)
                    last_heartbeat = now

    if not results:
        raise RuntimeError("All flood-mold replications failed; no results were produced")
    results = sorted(results, key=lambda x: x["replication"])
    timeseries_frames = [r["timeseries_df"] for r in results if isinstance(r.get("timeseries_df"), pd.DataFrame)]
    summary_rows = [r["summary_row"] for r in results]

    all_timeseries = pd.concat(timeseries_frames, ignore_index=True) if timeseries_frames else pd.DataFrame()
    if not all_timeseries.empty:
        all_timeseries.to_csv(out_root / "timeseries_all_replications.csv", index=False)

    summary_df = pd.DataFrame(summary_rows)
    if not summary_df.empty:
        summary_df.to_csv(out_root / "summary_by_replication.csv", index=False)

    quantile_df = aggregate_timeseries_quantiles(timeseries_frames)
    if not quantile_df.empty:
        quantile_df.to_csv(out_root / "timeseries_quantiles.csv", index=False)

    stats_df = aggregate_summary_rows(summary_rows, default_scenario="flood_mold")
    if not stats_df.empty:
        stats_df.to_csv(out_root / "summary_stats.csv", index=False)

    if not args.keep_rep_folders:
        for rep_dir in out_root.glob("rep_*"):
            if rep_dir.is_dir():
                shutil.rmtree(rep_dir, ignore_errors=True)

    print(f"Saved flood-and-mold outputs to {out_root}")
    return 0


if __name__ == "__main__":
    exit_code = main()

