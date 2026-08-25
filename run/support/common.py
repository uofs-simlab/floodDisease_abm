from __future__ import annotations

import json
import math
import os
import shlex
import stat
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import numpy as np
from config.defaults import (
    MAP_POPULATION_PRESETS,
    MODEL_DEFAULTS,
    RUN_DEFAULTS,
    SERVICE_DEFAULTS,
    infectious_start_hour,
)

try:
    import psutil
except Exception:
    psutil = None

try:
    import paramiko
except Exception:
    paramiko = None


SYNC_INCLUDE_PATHS = (
    "agents",
    "config",
    "analysis",
    "dataCollection",
    "docs",
    "model",
    "run",
    "scripts",
    "space",
    "space/Uvalde_TX_map_data",
    "baseline.py",
    "requirements.txt",
    "readme.md",
    "license.txt",
)

SYNC_EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "outputs",
    "__pycache__",
    ".pytest_cache",
    ".vscode",
}

SYNC_EXCLUDED_SUFFIXES = {".pyc", ".pyo"}

UVALDE_DATA_DIR = "space/Uvalde_TX_map_data"

# Flood-only service policy defaults shared by every scenario runner.
FLOOD_ONLY_SERVICE_DEFAULTS = SERVICE_DEFAULTS


def resolve_data_dir(root: Path, map_name: str | None) -> Path:
    _ = map_name
    return (root / UVALDE_DATA_DIR).resolve()


def build_common_model_kwargs(args, data_dir: Path, extra_kwargs: dict | None = None) -> dict:
    map_population = dict(MAP_POPULATION_PRESETS["uvalde"])

    gpkg = data_dir / "processed" / "abm_places.gpkg"
    house_override = data_dir / "processed" / "houses_augmented.geojson"
    school_override = data_dir / "processed" / "schools_campuses.geojson"
    flood_source = data_dir / "uvalde_twdb_scenario5_1in100_flood.geojson"
    if not gpkg.exists():
        raise FileNotFoundError(f"Required Uvalde place dataset is missing: {gpkg}")
    if not flood_source.exists():
        raise FileNotFoundError(f"Required Uvalde flood dataset is missing: {flood_source}")

    houses_source = str(house_override if house_override.exists() else gpkg)
    businesses_source = str(gpkg)
    schools_source = str(school_override if school_override.exists() else gpkg)
    shelter_source = str(gpkg)
    healthcare_source = str(gpkg)
    government_source = str(gpkg)

    persons = int(getattr(args, "persons", RUN_DEFAULTS["N_persons"]))

    kwargs = {
        "N_persons": persons,
        "baseline_days": args.baseline_days,
        "pre_flood_days": args.pre_flood_days,
        "flood_days": args.flood_days,
        "post_flood_days": args.post_flood_days,
        "houses_file": houses_source,
        "businesses_file": businesses_source,
        "schools_file": schools_source,
        "shelter_file": shelter_source,
        "healthcare_file": healthcare_source,
        "government_file": government_source,
        "flood_file": str(flood_source),
        "model_crs": "EPSG:3857",
        "stagnant_max_spots_per_wave": MODEL_DEFAULTS["stagnant_max_spots_per_wave"],
        "stagnant_area_fraction": MODEL_DEFAULTS["stagnant_area_fraction"],
        "infectious_seed_start_hour": MODEL_DEFAULTS["infectious_seed_start_hour"],
        "house_mold_rate": float(getattr(args, "house_mold_rate", MODEL_DEFAULTS["house_mold_rate"])),
        "business_mold_rate": float(getattr(args, "business_mold_rate", MODEL_DEFAULTS["business_mold_rate"])),
    }
    kwargs.update(map_population)
    kwargs.update(FLOOD_ONLY_SERVICE_DEFAULTS)
    # Keep policy defaults scenario-invariant unless the caller overrides them.
    cadence_override = getattr(args, "gov_baseline_grant_every_hours", None)
    if cadence_override is not None:
        kwargs["gov_baseline_grant_every_hours"] = int(cadence_override)
    if extra_kwargs:
        kwargs.update(extra_kwargs)
    scenario_name = str(kwargs.get("scenario_mode", "baseline"))
    kwargs["infectious_seed_start_hour"] = infectious_start_hour(
        scenario_name,
        kwargs["baseline_days"],
        kwargs["pre_flood_days"],
        kwargs["flood_days"],
    )
    return kwargs


def prepare_replication_kwargs(task: dict) -> dict:
    kwargs = dict(task["common_kwargs"])
    kwargs["progress_file"] = str(
        Path(task["out_root"]) / f"rep_{int(task['replication']):03d}_progress.json"
    )
    return kwargs


def flatten_summary(summary: dict) -> dict:
    row = {}
    scenario_meta = summary.get("scenario", {}) or {}
    row.update({f"scenario_{k}": v for k, v in scenario_meta.items()})

    for section in ("peaks", "totals", "end_state", "auc"):
        values = summary.get(section, {}) or {}
        for key, value in values.items():
            if isinstance(value, dict) and "value" in value:
                row[f"{section}_{key}_value"] = value.get("value")
                row[f"{section}_{key}_hour"] = value.get("hour")
            else:
                row[f"{section}_{key}"] = value
    return row


def aggregate_summary_rows(rows: list[dict], group_col: str | None = None, default_scenario: str = "baseline") -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    numeric_cols = [
        col for col in df.columns
        if pd.api.types.is_numeric_dtype(df[col]) and col not in {"scenario_replication", "scenario_random_seed"}
    ]
    if not numeric_cols:
        return pd.DataFrame()

    effective_group_col = None
    if group_col and group_col in df.columns:
        effective_group_col = group_col
    elif "scenario_scenario_mode" in df.columns:
        effective_group_col = "scenario_scenario_mode"

    grouped = []
    if effective_group_col is None:
        records = [(default_scenario, df)]
    else:
        records = list(df.groupby(effective_group_col, dropna=False))

    for scenario_name, grp in records:
        record = {
            "scenario": scenario_name,
            "replications": int(len(grp)),
            "valid_replications": int(len(grp)),
        }
        for col in numeric_cols:
            vals = grp[col].dropna().astype(float)
            if vals.empty:
                continue
            record[f"{col}_mean"] = float(vals.mean())
            record[f"{col}_std"] = float(vals.std(ddof=0))
            record[f"{col}_q05"] = float(vals.quantile(0.05))
            record[f"{col}_q25"] = float(vals.quantile(0.25))
            record[f"{col}_median"] = float(vals.quantile(0.50))
            record[f"{col}_q75"] = float(vals.quantile(0.75))
            record[f"{col}_q95"] = float(vals.quantile(0.95))
            if len(vals) > 1:
                standard_error = float(vals.std(ddof=1)) / math.sqrt(len(vals))
                record[f"{col}_mean_ci95_low"] = float(vals.mean() - 1.96 * standard_error)
                record[f"{col}_mean_ci95_high"] = float(vals.mean() + 1.96 * standard_error)
            else:
                record[f"{col}_mean_ci95_low"] = float(vals.mean())
                record[f"{col}_mean_ci95_high"] = float(vals.mean())
        grouped.append(record)
    return pd.DataFrame(grouped)


def aggregate_timeseries_quantiles(frames: list[pd.DataFrame]) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    if df.empty or "hours" not in df.columns:
        return df

    non_metric = {"hours", "day", "phase", "event_phase", "scenario", "run_id", "replication", "random_seed"}
    metric_cols = [col for col in df.columns if col not in non_metric and pd.api.types.is_numeric_dtype(df[col])]

    rows = []
    for hour, grp in df.groupby("hours", dropna=False):
        row = {"hours": hour}
        if "day" in grp.columns:
            row["day"] = int(grp["day"].iloc[0])
        for col in metric_cols:
            vals = grp[col].dropna().astype(float)
            if vals.empty:
                continue
            row[f"{col}_q25"] = float(vals.quantile(0.25))
            row[f"{col}_median"] = float(vals.quantile(0.50))
            row[f"{col}_q75"] = float(vals.quantile(0.75))
            row[f"{col}_mean"] = float(vals.mean())
        rows.append(row)
    return pd.DataFrame(rows).sort_values("hours").reset_index(drop=True)


def format_hms(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    total = max(0, int(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def build_progress_snapshot(completed: int, total: int, started_at: float, results_by_scenario: dict | None = None) -> dict:
    now = time.time()
    elapsed = max(0.0, now - started_at)
    rate_per_sec = (completed / elapsed) if elapsed > 0 and completed > 0 else 0.0
    remaining = max(0, total - completed)
    eta_seconds = (remaining / rate_per_sec) if rate_per_sec > 0 else None

    rss_gb = None
    if psutil is not None:
        try:
            rss_gb = psutil.Process(os.getpid()).memory_info().rss / (1024 ** 3)
        except Exception:
            rss_gb = None

    snapshot = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "completed": int(completed),
        "total": int(total),
        "remaining": int(remaining),
        "percent": float((completed / total) * 100.0) if total > 0 else 0.0,
        "elapsed_seconds": float(elapsed),
        "rate_tasks_per_hour": float(rate_per_sec * 3600.0),
        "eta_seconds": float(eta_seconds) if eta_seconds is not None else None,
        "driver_rss_gb": float(rss_gb) if rss_gb is not None else None,
    }
    if results_by_scenario is not None:
        snapshot["by_scenario"] = {k: int(len(v)) for k, v in results_by_scenario.items()}
    return snapshot


def _resolve_remote_target(target: str, user: str, remote_repo: str) -> tuple[str, str, str]:
    target_lower = target.lower()
    if target_lower == "gottlieb":
        target_host = "gottlieb"
        remote_root = f"/scratch-gladwell/{user}"
    elif target_lower == "richardson":
        target_host = "richardson"
        remote_root = f"/scratch/{user}"
    elif target_lower == "hundsdorfer":
        target_host = "hundsdorfer"
        remote_root = f"/scratch/{user}"
    else:
        raise ValueError(f"Unknown target: {target}")

    remote_repo_path = remote_repo if remote_repo.startswith("/") else f"{remote_root}/{remote_repo}"
    return target_host, remote_root, remote_repo_path


def _exec_remote_via_paramiko(
    command: str,
    target_host: str,
    target_user: str,
    target_password: str,
    tux_user: str,
    tux_host: str,
    timeout: int = 120,
) -> tuple[int, str, str]:
    if paramiko is None:
        raise RuntimeError("paramiko is not installed")

    tux_client = paramiko.SSHClient()
    target_client = paramiko.SSHClient()
    tux_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    target_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        tux_client.connect(
            hostname=tux_host,
            username=tux_user,
            password=target_password,
            look_for_keys=False,
            allow_agent=False,
            timeout=timeout,
        )
        chan = tux_client.get_transport().open_channel("direct-tcpip", (target_host, 22), ("127.0.0.1", 0))
        target_client.connect(
            hostname=target_host,
            username=target_user,
            password=target_password,
            sock=chan,
            look_for_keys=False,
            allow_agent=False,
            timeout=timeout,
        )
        stdin, stdout, stderr = target_client.exec_command(command, timeout=timeout)
        _ = stdin
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        rc = stdout.channel.recv_exit_status()
        return rc, out, err
    finally:
        try:
            target_client.close()
        except Exception:
            pass
        try:
            tux_client.close()
        except Exception:
            pass


def _connect_paramiko_clients(
    target_host: str,
    target_user: str,
    target_password: str,
    tux_user: str,
    tux_host: str,
    timeout: int = 120,
):
    if paramiko is None:
        raise RuntimeError("paramiko is not installed")

    tux_client = paramiko.SSHClient()
    target_client = paramiko.SSHClient()
    tux_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    target_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    tux_client.connect(
        hostname=tux_host,
        username=tux_user,
        password=target_password,
        look_for_keys=False,
        allow_agent=False,
        timeout=timeout,
    )
    chan = tux_client.get_transport().open_channel("direct-tcpip", (target_host, 22), ("127.0.0.1", 0))
    target_client.connect(
        hostname=target_host,
        username=target_user,
        password=target_password,
        sock=chan,
        look_for_keys=False,
        allow_agent=False,
        timeout=timeout,
    )
    return tux_client, target_client


def _sftp_mkdir_p(sftp, remote_dir: str) -> None:
    parts = remote_dir.strip("/").split("/")
    current = ""
    for part in parts:
        current = f"{current}/{part}" if current else f"/{part}"
        try:
            sftp.stat(current)
        except FileNotFoundError:
            sftp.mkdir(current)


def _sync_local_path_to_remote(sftp, local_path: Path, remote_path: str) -> None:
    if local_path.is_dir():
        _sftp_mkdir_p(sftp, remote_path)
        for child in local_path.iterdir():
            if child.name in SYNC_EXCLUDED_DIRS:
                continue
            if child.suffix.lower() in SYNC_EXCLUDED_SUFFIXES:
                continue
            _sync_local_path_to_remote(sftp, child, f"{remote_path}/{child.name}")
        return

    _sftp_mkdir_p(sftp, str(Path(remote_path).parent).replace("\\", "/"))
    sftp.put(str(local_path), remote_path)


def sync_repo_to_remote(
    local_root: Path,
    target: str,
    user: str,
    password: str,
    remote_repo: str,
    tux_user: str = "oaa721",
    tux_host: str = "tuxworld.usask.ca",
) -> bool:
    """Upload the current local workspace code to the remote repo path before launch."""
    target_host, _remote_root, remote_repo_path = _resolve_remote_target(target, user, remote_repo)
    if paramiko is None:
        print("[ERR] Cannot sync repo: paramiko is not installed")
        return False

    tux_client = None
    target_client = None
    try:
        tux_client, target_client = _connect_paramiko_clients(
            target_host=target_host,
            target_user=user,
            target_password=password,
            tux_user=tux_user,
            tux_host=tux_host,
            timeout=120,
        )
        sftp = target_client.open_sftp()
        try:
            _sftp_mkdir_p(sftp, remote_repo_path)
            for rel_path in SYNC_INCLUDE_PATHS:
                local_path = local_root / rel_path
                if not local_path.exists():
                    continue
                remote_path = f"{remote_repo_path}/{rel_path}".replace("\\", "/")
                _sync_local_path_to_remote(sftp, local_path, remote_path)
        finally:
            sftp.close()
        print(f"[OK] Synced workspace to {target}:{remote_repo_path}")
        return True
    except Exception as e:
        print(f"[ERR] Could not sync repo to remote: {e}")
        return False
    finally:
        try:
            if target_client is not None:
                target_client.close()
        except Exception:
            pass
        try:
            if tux_client is not None:
                tux_client.close()
        except Exception:
            pass


def launch_remote_batch(
    target: str,
    user: str,
    password: str,
    remote_repo: str,
    batch_args: str,
    runner: str = "baseline",
    session_name: str = "flood_batch",
    tux_user: str = "oaa721",
    tux_host: str = "tuxworld.usask.ca",
    kill_existing_session: bool = False,
    clean_output_dir: str | None = None,
) -> bool:
    """Launch remote batch in tmux using password auth through tuxworld proxy."""
    target_host, _remote_root, remote_repo_path = _resolve_remote_target(target, user, remote_repo)
    _runner_script_map = {
        "baseline":   "scripts/run_lab_baseline.sh",
        "infectious_disease": "scripts/run_lab_infectious_disease.sh",
        "flood_only": "scripts/run_lab_flood_only.sh",
        "flood_vectorborne": "scripts/run_lab_flood_vectorborne.sh",
        "flood_infectious": "scripts/run_lab_flood_infectious.sh",
        "flood_mold": "scripts/run_lab_flood_mold.sh",
        "flood_mold_vectorborne": "scripts/run_lab_flood_mold_vectorborne.sh",
        "full_compound": "scripts/run_lab_full_compound.sh",
    }
    run_script = _runner_script_map.get(runner)
    if run_script is None:
        raise ValueError(f"Unknown runner '{runner}'. Expected one of: {', '.join(sorted(_runner_script_map.keys()))}")

    lines = [
        "set -euo pipefail",
        f"cd {shlex.quote(remote_repo_path)}",
        "if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then",
        "  git pull --ff-only || true",
        "fi",
        "if [ ! -f .venv/bin/activate ]; then",
        "  bash scripts/setup_lab_env.sh",
        "fi",
        "if ! .venv/bin/python -c \"import numpy\" >/dev/null 2>&1; then",
        "  echo \"[ENV] Existing .venv is missing required packages - reinstalling requirements.\"",
        "  bash scripts/setup_lab_env.sh",
        "fi",
        "source scripts/activate_project_env.sh",
    ]

    if clean_output_dir:
        # Safety gate: only allow cleaning within outputs/ to prevent destructive paths.
        if clean_output_dir.startswith("/") or ".." in clean_output_dir or not clean_output_dir.startswith("outputs/"):
            raise ValueError(f"Unsafe clean_output_dir: {clean_output_dir}")
        lines.append(f"rm -rf -- {shlex.quote(clean_output_dir)}")

    if kill_existing_session:
        lines.append(f"tmux kill-session -t {shlex.quote(session_name)} 2>/dev/null || true")
    lines.extend(
        [
            f"tmux new-session -d -s {shlex.quote(session_name)} \"bash {run_script} {batch_args}\"",
            f"echo \"[RUN] Attach with: tmux attach -t {session_name}\"",
        ]
    )
    command = "\n".join(lines)

    try:
        rc, out, err = _exec_remote_via_paramiko(
            command=command,
            target_host=target_host,
            target_user=user,
            target_password=password,
            tux_user=tux_user,
            tux_host=tux_host,
            timeout=240,
        )
        if out.strip():
            print(out)
        if err.strip():
            print(err)
        if rc != 0:
            print(f"[ERR] Remote launch failed with exit code {rc}")
            return False
        return True
    except Exception as e:
        print(f"[ERR] Could not launch remote batch: {e}")
        if paramiko is None:
            print("[ERR] Install paramiko locally: pip install paramiko")
        return False


def check_remote_progress(
    target: str,
    user: str,
    password: str,
    remote_repo: str,
    remote_out_dir: str,
    tux_user: str = "oaa721",
    tux_host: str = "tuxworld.usask.ca",
) -> dict | None:
    """Check remote progress via SSH. Returns parsed _progress.json or None if not ready."""
    if paramiko is None:
        return None

    target_host, _remote_root, remote_repo_path = _resolve_remote_target(target, user, remote_repo)
    progress_file = f"{remote_repo_path}/{remote_out_dir}/_progress.json"
    command = f"cat {shlex.quote(progress_file)} 2>/dev/null || echo '{{}}'"

    try:
        rc, out, err = _exec_remote_via_paramiko(
            command=command,
            target_host=target_host,
            target_user=user,
            target_password=password,
            tux_user=tux_user,
            tux_host=tux_host,
            timeout=45,
        )
        if rc == 0 and out.strip():
            payload = json.loads(out.strip())
            if not isinstance(payload, dict) or not payload:
                return None
            total = payload.get("total")
            completed = payload.get("completed")
            if total is None or completed is None:
                return None
            if int(total) <= 0:
                return None
            return payload
        if err.strip():
            print(f"[WARN] Progress check stderr: {err.strip()}")
    except Exception as e:
        print(f"[WARN] Could not check remote progress: {e}")

    return None


def check_remote_timeseries_ready(
    target: str,
    user: str,
    password: str,
    remote_repo: str,
    remote_out_dir: str,
    tux_user: str = "oaa721",
    tux_host: str = "tuxworld.usask.ca",
) -> bool:
    """Return True when remote aggregated timeseries files exist in remote_out_dir."""
    if paramiko is None:
        return False

    target_host, _remote_root, remote_repo_path = _resolve_remote_target(target, user, remote_repo)
    remote_dir = f"{remote_repo_path}/{remote_out_dir}"
    command = (
        f"if [ -f {shlex.quote(remote_dir + '/timeseries_all_replications.csv')} ] "
        f"|| [ -f {shlex.quote(remote_dir + '/timeseries_quantiles.csv')} ]; then echo READY; else echo NOT_READY; fi"
    )

    try:
        rc, out, _err = _exec_remote_via_paramiko(
            command=command,
            target_host=target_host,
            target_user=user,
            target_password=password,
            tux_user=tux_user,
            tux_host=tux_host,
            timeout=45,
        )
        status = str(out or "").strip()
        return rc == 0 and status == "READY"
    except Exception:
        return False


def wait_for_remote_timeseries(
    target: str,
    user: str,
    password: str,
    remote_repo: str,
    remote_out_dir: str,
    max_wait_seconds: int = 1800,
    poll_seconds: int = 120,
    tux_user: str = "oaa721",
    tux_host: str = "tuxworld.usask.ca",
) -> bool:
    """Wait up to max_wait_seconds for remote aggregated timeseries files to appear."""
    deadline = time.time() + max(1, int(max_wait_seconds))
    while time.time() <= deadline:
        if check_remote_timeseries_ready(
            target=target,
            user=user,
            password=password,
            remote_repo=remote_repo,
            remote_out_dir=remote_out_dir,
            tux_user=tux_user,
            tux_host=tux_host,
        ):
            return True
        time.sleep(max(5, int(poll_seconds)))
    return False


def has_local_timeseries(out_dir: Path) -> bool:
    """Return True if local output directory contains aggregated timeseries CSV files."""
    root = Path(out_dir)
    if not root.exists():
        return False
    candidates = [
        root / "timeseries_all_replications.csv",
        root / "timeseries_quantiles.csv",
    ]
    if any(p.exists() for p in candidates):
        return True
    # Be resilient to nested layout variants from manual copies.
    for name in ("timeseries_all_replications.csv", "timeseries_quantiles.csv"):
        if list(root.rglob(name)):
            return True
    return False


def _sftp_download_dir(sftp, remote_dir: str, local_dir: Path) -> None:
    local_dir.mkdir(parents=True, exist_ok=True)
    for entry in sftp.listdir_attr(remote_dir):
        remote_path = f"{remote_dir}/{entry.filename}"
        local_path = local_dir / entry.filename
        if stat.S_ISDIR(entry.st_mode):
            _sftp_download_dir(sftp, remote_path, local_path)
        else:
            sftp.get(remote_path, str(local_path))


def pull_results_from_remote(
    target: str,
    user: str,
    password: str,
    remote_repo: str,
    remote_out_dir: str,
    local_out_dir: Path,
    tux_user: str = "oaa721",
    tux_host: str = "tuxworld.usask.ca",
) -> bool:
    """Pull results from remote host back to local outputs directory using SFTP."""
    target_host, _remote_root, remote_repo_path = _resolve_remote_target(target, user, remote_repo)
    remote_path = f"{remote_repo_path}/{remote_out_dir}"
    local_out_dir.mkdir(parents=True, exist_ok=True)

    if paramiko is None:
        print("[ERR] Cannot pull results: paramiko is not installed. Install with: pip install paramiko")
        return False

    tux_client = paramiko.SSHClient()
    target_client = paramiko.SSHClient()
    tux_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    target_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        tux_client.connect(
            hostname=tux_host,
            username=tux_user,
            password=password,
            look_for_keys=False,
            allow_agent=False,
            timeout=90,
        )
        chan = tux_client.get_transport().open_channel("direct-tcpip", (target_host, 22), ("127.0.0.1", 0))
        target_client.connect(
            hostname=target_host,
            username=user,
            password=password,
            sock=chan,
            look_for_keys=False,
            allow_agent=False,
            timeout=90,
        )

        sftp = target_client.open_sftp()
        try:
            _sftp_download_dir(sftp, remote_path, local_out_dir)
        finally:
            sftp.close()

        print(f"[OK] Results pulled from {target} to {local_out_dir}")
        return True
    except Exception as e:
        print(f"[ERR] Could not pull results: {e}")
        return False
    finally:
        try:
            target_client.close()
        except Exception:
            pass
        try:
            tux_client.close()
        except Exception:
            pass
