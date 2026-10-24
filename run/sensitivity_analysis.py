from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
_VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
if (
    os.environ.get("FLOODDISEASE_ABM_BOOTSTRAPPED") != "1"
    and _VENV_PYTHON.exists()
    and Path(sys.executable).resolve() != _VENV_PYTHON.resolve()
):
    os.environ["FLOODDISEASE_ABM_BOOTSTRAPPED"] = "1"
    os.execv(str(_VENV_PYTHON), [str(_VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]])

sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
from scipy.stats import qmc, rankdata

from config.defaults import MODEL_DEFAULTS, RUN_DEFAULTS, SERVICE_DEFAULTS
from run.support.common import (
    build_common_model_kwargs,
    build_progress_snapshot,
    resolve_data_dir,
)

try:
    from model._model import Model

    MODEL_IMPORT_ERROR = None
except ImportError as exc:
    Model = None
    MODEL_IMPORT_ERROR = str(exc)


OUTCOMES = (
    "dead_pct_final",
    "injured_ever_pct_final",
    "infectious_ever_pct_final",
    "mold_ever_pct_final",
    "vector_ever_pct_final",
    "compound_burden_peak_pct",
    "compound_burden_auc_pct_hours",
    "healthcare_backlog_peak_pct",
    "shelter_backlog_peak_pct",
    "qol_mean_time_average_pct",
    "qol_children_time_average_pct",
    "inequity_gap_time_average_pct",
)

# These are provisional screening bounds, not empirical confidence intervals.
# Review the corresponding range rationale before using them in a manuscript.
PARAMETER_SPECS = {
    "flood_depth_multiplier": {
        "low": 1.25, "high": 5.0, "default": 2.5, "integer": False,
        "kind": "direct",
    },
    "flood_wave_duration_hours": {
        "low": 24.0, "high": 96.0, "default": None, "integer": True,
        "kind": "wave_duration",
    },
    "stranded_depth_tolerance_mult": {
        "low": 0.01, "high": 0.10, "default": 0.05, "integer": False,
        "kind": "direct",
    },
    "injury_risk_scale": {
        "low": 0.25, "high": 3.0, "default": 1.5, "integer": False,
        "kind": "direct",
    },
    "hours_before_rescue": {
        "low": 0.0, "high": 24.0, "default": 6, "integer": True,
        "kind": "direct",
    },
    "warning_pre_flood_base": {
        "low": 0.0, "high": 1.0, "default": 0.35, "integer": False,
        "kind": "direct",
    },
    "infectious_transmission_scale": {
        "low": 0.5, "high": 2.0, "default": 1.0, "integer": False,
        "kind": "transmission_scale",
    },
    "infectious_gamma": {
        "low": 0.00835, "high": 0.0334, "default": 0.0167, "integer": False,
        "kind": "direct",
    },
    "infectious_seed_share": {
        "low": 0.0, "high": 0.02, "default": 0.01, "integer": False,
        "kind": "direct",
    },
    "house_mold_rate": {
        "low": 0.15, "high": 0.60, "default": 0.30, "integer": False,
        "kind": "direct",
    },
    "vector_exposure_hazard": {
        "low": 0.025, "high": 0.10, "default": 0.05, "integer": False,
        "kind": "direct",
    },
    "service_capacity_scale": {
        "low": 0.5, "high": 2.0, "default": 1.0, "integer": False,
        "kind": "service_capacity_scale",
    },
    "mold_base_onset_probability": {
        "low": 0.0015, "high": 0.006, "default": 0.003, "integer": False,
        "kind": "direct",
    },
    "damp_half_life_h": {
        "low": 10.0, "high": 40.0, "default": 20.0, "integer": False,
        "kind": "direct",
    },
    "stagnant_area_fraction": {
        "low": 0.0025, "high": 0.01, "default": 0.005, "integer": False,
        "kind": "direct",
    },
    "stagnant_half_life_h": {
        "low": 48.0, "high": 192.0, "default": 96.0, "integer": False,
        "kind": "direct",
    },
    "infectious_seed_delay_hours": {
        "low": 24.0, "high": 96.0, "default": 48, "integer": True,
        "kind": "seed_delay",
    },
    "mold_high_sensitivity_share": {
        "low": 0.10, "high": 0.40, "default": 0.20, "integer": False,
        "kind": "direct",
    },
    "mold_sensitivity_multiplier": {
        "low": 1.2, "high": 4.8, "default": 2.4, "integer": False,
        "kind": "direct",
    },
    "vector_shelter_protection": {
        "low": 0.325, "high": 0.90, "default": 0.65, "integer": False,
        "kind": "direct",
    },
    "vector_recovery_rate_per_hour": {
        "low": 1 / 336, "high": 1 / 84, "default": 1 / 168, "integer": False,
        "kind": "direct",
    },
    "mold_recovery_rate_per_hour": {
        "low": 1 / 168, "high": 1 / 42, "default": 1 / 84, "integer": False,
        "kind": "direct",
    },
    "business_mold_rate": {
        "low": 0.25, "high": 1.0, "default": 0.50, "integer": False,
        "kind": "direct",
    },
    "sales_revenue_multiplier": {
        "low": 1.9, "high": 7.6, "default": 3.8, "integer": False,
        "kind": "direct",
    },
    "decision_w_depth": {
        "low": 0.2, "high": 0.6, "default": 0.4, "integer": False,
        "kind": "direct",
    },
    "decision_w_disease": {
        "low": 0.1, "high": 0.3, "default": 0.2, "integer": False,
        "kind": "direct",
    },
}

CORE_PARAMETERS = (
    "flood_depth_multiplier",
    "flood_wave_duration_hours",
    "stranded_depth_tolerance_mult",
    "injury_risk_scale",
    "hours_before_rescue",
    "warning_pre_flood_base",
    "infectious_transmission_scale",
    "infectious_gamma",
    "infectious_seed_share",
    "house_mold_rate",
    "vector_exposure_hazard",
    "service_capacity_scale",
)

EXTENDED_PARAMETERS = tuple(
    name for name in PARAMETER_SPECS if name not in CORE_PARAMETERS
)


def _parameter_names(selection: str) -> list[str]:
    selection = selection.strip()
    if selection == "core":
        return list(CORE_PARAMETERS)
    if selection in {"extended", "full"}:
        return list(PARAMETER_SPECS)

    names = [name.strip() for name in selection.split(",") if name.strip()]
    if not names:
        raise ValueError("Provide `core`, `full`, or a comma-separated parameter list.")
    unknown = [name for name in names if name not in PARAMETER_SPECS]
    if unknown:
        raise ValueError(f"Unknown sensitivity parameter(s): {', '.join(unknown)}")
    if len(set(names)) != len(names):
        raise ValueError("Parameter names must not be repeated.")
    return names


def _flood_wave_default_hours(args) -> int:
    duration = max(1, int(args.flood_days) * 24 - 1)
    return max(1, round(duration * 0.35))


def _parameter_default(name: str, args) -> float:
    spec = PARAMETER_SPECS[name]
    if spec["default"] is not None:
        return float(spec["default"])
    if name == "flood_wave_duration_hours":
        return float(_flood_wave_default_hours(args))
    raise ValueError(f"No default is defined for sensitivity parameter {name!r}.")


def _actual_value(name: str, unit_value: float) -> float | int:
    spec = PARAMETER_SPECS[name]
    value = float(spec["low"]) + float(unit_value) * (
        float(spec["high"]) - float(spec["low"])
    )
    if bool(spec["integer"]):
        return int(round(value))
    return value


def _make_design_row(
    sample_id: str,
    method: str,
    names: list[str],
    unit_values: np.ndarray,
    trajectory_id: int | None = None,
    step_index: int | None = None,
) -> dict:
    row = {
        "sample_id": sample_id,
        "method": method,
        "trajectory_id": trajectory_id,
        "step_index": step_index,
    }
    for index, name in enumerate(names):
        row[f"unit_{name}"] = float(unit_values[index])
        row[name] = _actual_value(name, float(unit_values[index]))
    return row


def generate_morris_design(
    names: list[str],
    trajectories: int,
    levels: int,
    seed: int,
) -> tuple[pd.DataFrame, pd.DataFrame, float]:
    if levels < 4 or levels % 2 != 0:
        raise ValueError("Morris levels must be an even integer of at least 4.")
    if trajectories < 1:
        raise ValueError("Morris trajectories must be at least 1.")

    rng = np.random.default_rng(seed)
    delta = levels / (2.0 * (levels - 1))
    half_levels = levels // 2
    design_rows = []
    transition_rows = []
    sample_number = 0

    for trajectory_id in range(trajectories):
        signs = rng.choice(np.array([-1.0, 1.0]), size=len(names))
        start = np.empty(len(names), dtype=float)
        for index, sign in enumerate(signs):
            if sign > 0:
                level_index = int(rng.integers(0, half_levels))
            else:
                level_index = int(rng.integers(half_levels, levels))
            start[index] = level_index / (levels - 1)

        order = rng.permutation(len(names))
        current = start.copy()
        current_id = f"M{sample_number:05d}"
        design_rows.append(
            _make_design_row(
                current_id, "morris", names, current, trajectory_id, 0
            )
        )
        sample_number += 1

        for step_index, parameter_index in enumerate(order, start=1):
            previous = current.copy()
            previous_id = current_id
            current[parameter_index] += signs[parameter_index] * delta
            if not 0.0 <= current[parameter_index] <= 1.0:
                raise RuntimeError("Generated Morris step left the unit hypercube.")

            current_id = f"M{sample_number:05d}"
            design_rows.append(
                _make_design_row(
                    current_id,
                    "morris",
                    names,
                    current,
                    trajectory_id,
                    step_index,
                )
            )
            transition_rows.append(
                {
                    "trajectory_id": trajectory_id,
                    "step_index": step_index,
                    "from_sample_id": previous_id,
                    "to_sample_id": current_id,
                    "parameter": names[parameter_index],
                    "delta_unit": float(current[parameter_index] - previous[parameter_index]),
                }
            )
            sample_number += 1

    return pd.DataFrame(design_rows), pd.DataFrame(transition_rows), delta


def generate_lhs_design(
    names: list[str],
    samples: int,
    seed: int,
) -> pd.DataFrame:
    if samples < len(names) + 2:
        raise ValueError(
            f"LHS needs at least {len(names) + 2} points for PRCC with {len(names)} parameters."
        )
    sampler = qmc.LatinHypercube(d=len(names), seed=seed)
    unit_design = sampler.random(n=samples)
    return pd.DataFrame(
        [
            _make_design_row(
                f"L{sample_index:05d}",
                "lhs",
                names,
                unit_design[sample_index],
            )
            for sample_index in range(samples)
        ]
    )


def build_common_kwargs(args) -> dict:
    run_args = SimpleNamespace(
        persons=args.persons,
        baseline_days=args.baseline_days,
        pre_flood_days=args.pre_flood_days,
        flood_days=args.flood_days,
        post_flood_days=args.post_flood_days,
        map="uvalde",
        house_mold_rate=MODEL_DEFAULTS["house_mold_rate"],
        business_mold_rate=MODEL_DEFAULTS["business_mold_rate"],
        gov_baseline_grant_every_hours=None,
    )
    return build_common_model_kwargs(
        run_args,
        resolve_data_dir(ROOT, "uvalde"),
        extra_kwargs={
            "scenario_mode": "compound",
            "enable_infectious": 1,
            "enable_stagnant": 1,
            "enable_mold": 1,
        },
    )


def apply_parameter_values(base_kwargs: dict, values: dict, args) -> dict:
    kwargs = dict(base_kwargs)
    for name, raw_value in values.items():
        value = raw_value
        kind = PARAMETER_SPECS[name]["kind"]
        if bool(PARAMETER_SPECS[name]["integer"]):
            value = int(round(float(value)))

        if kind == "wave_duration":
            kwargs["flood_wave_rise_hours"] = int(value)
            kwargs["flood_wave_fall_hours"] = int(value)
        elif kind == "transmission_scale":
            kwargs["infectious_beta_base"] = (
                MODEL_DEFAULTS["infectious_beta_base"] * float(value)
            )
        elif kind == "service_capacity_scale":
            scale = float(value)
            kwargs["shelter_cap_limit"] = SERVICE_DEFAULTS["shelter_cap_limit"] * scale
            kwargs["healthcare_cap_limit"] = SERVICE_DEFAULTS["healthcare_cap_limit"] * scale
        elif kind == "seed_delay":
            flood_end_hour = (
                int(args.baseline_days)
                + int(args.pre_flood_days)
                + int(args.flood_days)
            ) * 24
            kwargs["infectious_seed_start_hour"] = flood_end_hour + int(value)
        else:
            kwargs[name] = value
    return kwargs


def _auc(hours: np.ndarray, values: np.ndarray) -> float:
    finite = np.isfinite(hours) & np.isfinite(values)
    x = hours[finite]
    y = values[finite]
    if len(x) < 2:
        return 0.0
    return float(np.trapezoid(y, x))


def extract_outcomes(data: pd.DataFrame) -> dict[str, float]:
    required = {
        "hours",
        "dead_pct",
        "affected_injured_unique_pct",
        "affected_infectious_pct",
        "affected_mold_pct",
        "affected_vectorborne_pct",
        "compound_burden_pct",
        "hc_backlog_pct",
        "shelter_backlog_pct",
        "qol_mean_pct",
        "qol_children_pct",
        "inequity_gap_low_vs_high_pct",
    }
    missing = sorted(required.difference(data.columns))
    if missing:
        raise KeyError(f"Missing required model reporter(s): {', '.join(missing)}")
    if data.empty:
        raise ValueError("The model returned an empty time series.")

    hours = data["hours"].to_numpy(dtype=float)

    def values(column: str) -> np.ndarray:
        return data[column].fillna(0.0).to_numpy(dtype=float)

    def peak(column: str) -> float:
        return float(np.max(values(column)))

    def final(column: str) -> float:
        return float(values(column)[-1])

    def time_average(column: str) -> float:
        y = values(column)
        duration = float(hours[-1] - hours[0])
        return _auc(hours, y) / duration if duration > 0.0 else float(y[-1])

    return {
        "dead_pct_final": final("dead_pct"),
        "injured_ever_pct_final": final("affected_injured_unique_pct"),
        "infectious_ever_pct_final": final("affected_infectious_pct"),
        "mold_ever_pct_final": final("affected_mold_pct"),
        "vector_ever_pct_final": final("affected_vectorborne_pct"),
        "compound_burden_peak_pct": peak("compound_burden_pct"),
        "compound_burden_auc_pct_hours": _auc(hours, values("compound_burden_pct")),
        "healthcare_backlog_peak_pct": peak("hc_backlog_pct"),
        "shelter_backlog_peak_pct": peak("shelter_backlog_pct"),
        "qol_mean_time_average_pct": time_average("qol_mean_pct"),
        "qol_children_time_average_pct": time_average("qol_children_pct"),
        "inequity_gap_time_average_pct": time_average("inequity_gap_low_vs_high_pct"),
    }


def _run_simulation(task: dict) -> dict:
    if Model is None:
        raise RuntimeError(f"Cannot import model: {MODEL_IMPORT_ERROR}")

    kwargs = apply_parameter_values(
        task["base_kwargs"], task["parameter_values"], task["timeline"]
    )
    kwargs.update(
        {
            "random_seed": int(task["seed"]),
            "replication": int(task["replication"]),
            "run_id": (
                f"sens_{task['method']}_{task['sample_id']}_"
                f"rep{int(task['replication']):03d}_seed{int(task['seed'])}"
            ),
            "progress_file": None,
            "auto_export_on_finish": False,
        }
    )
    model = Model(**kwargs)
    while model.running:
        model.step()

    data = model.datacollector.get_model_vars_dataframe().reset_index(drop=True)
    result = {
        "method": task["method"],
        "sample_id": task["sample_id"],
        "trajectory_id": task.get("trajectory_id"),
        "step_index": task.get("step_index"),
        "replication": int(task["replication"]),
        "random_seed": int(task["seed"]),
    }
    result.update(task["parameter_values"])
    result.update(extract_outcomes(data))
    return result


def _write_progress(
    out_dir: Path,
    completed: int,
    total: int,
    started_at: float,
    phase: str,
) -> None:
    payload = build_progress_snapshot(completed, total, started_at)
    payload["phase"] = phase
    progress_path = out_dir / "_progress.json"
    temporary_path = progress_path.with_suffix(".json.tmp")
    temporary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary_path.replace(progress_path)


def run_design(
    design: pd.DataFrame,
    names: list[str],
    base_kwargs: dict,
    seeds: list[int],
    timeline,
    workers: int,
    out_dir: Path,
    phase: str,
    completed_before: int,
    total_runs: int,
    started_at: float,
) -> tuple[pd.DataFrame, int]:
    tasks = []
    for row in design.to_dict(orient="records"):
        parameter_values = {name: row[name] for name in names}
        for replication, seed in enumerate(seeds):
            tasks.append(
                {
                    "method": phase,
                    "sample_id": row["sample_id"],
                    "trajectory_id": row.get("trajectory_id"),
                    "step_index": row.get("step_index"),
                    "parameter_values": parameter_values,
                    "base_kwargs": base_kwargs,
                    "timeline": timeline,
                    "replication": replication,
                    "seed": seed,
                }
            )

    results = []
    completed = completed_before
    if workers <= 1:
        for task in tasks:
            results.append(_run_simulation(task))
            completed += 1
            _write_progress(out_dir, completed, total_runs, started_at, phase)
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            future_to_task = {
                executor.submit(_run_simulation, task): task for task in tasks
            }
            for future in as_completed(future_to_task):
                task = future_to_task[future]
                try:
                    result = future.result()
                except Exception as exc:
                    raise RuntimeError(
                        f"Simulation failed for {phase} sample "
                        f"{task['sample_id']} replication {task['replication']} "
                        f"(seed {task['seed']}): {type(exc).__name__}: {exc}"
                    ) from exc
                results.append(result)
                completed += 1
                _write_progress(out_dir, completed, total_runs, started_at, phase)
                if completed % max(1, workers) == 0 or completed == total_runs:
                    print(
                        f"[{phase}] completed {completed}/{total_runs}; "
                        f"sample={task['sample_id']} seed={task['seed']}"
                    )

    frame = pd.DataFrame(results)
    frame.to_csv(out_dir / f"run_results_{phase}.csv", index=False)
    return frame, completed


def _mean_by_sample(results: pd.DataFrame) -> pd.DataFrame:
    return results.groupby("sample_id", as_index=True)[list(OUTCOMES)].mean()


def compute_morris_indices(
    results: pd.DataFrame,
    transitions: pd.DataFrame,
    outcomes: tuple[str, ...],
    bootstrap_samples: int,
    seed: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    means = _mean_by_sample(results)
    effects: dict[tuple[str, str], list[tuple[int, float]]] = {}
    for transition in transitions.to_dict(orient="records"):
        parameter = str(transition["parameter"])
        dx = float(transition["delta_unit"])
        for outcome in outcomes:
            effect = (
                float(means.loc[transition["to_sample_id"], outcome])
                - float(means.loc[transition["from_sample_id"], outcome])
            ) / dx
            effects.setdefault((parameter, outcome), []).append(
                (int(transition["trajectory_id"]), effect)
            )

    rng = np.random.default_rng(seed)
    index_rows = []
    for (parameter, outcome), trajectory_effects in effects.items():
        values = np.asarray([value for _, value in trajectory_effects], dtype=float)
        if len(values) == 0:
            continue
        bootstrap_mu_star = []
        if bootstrap_samples > 0:
            samples = rng.choice(
                values,
                size=(bootstrap_samples, len(values)),
                replace=True,
            )
            bootstrap_mu_star = np.mean(np.abs(samples), axis=1)
        index_rows.append(
            {
                "parameter": parameter,
                "outcome": outcome,
                "mu": float(np.mean(values)),
                "mu_star": float(np.mean(np.abs(values))),
                "sigma": float(np.std(values, ddof=1)) if len(values) > 1 else 0.0,
                "n_trajectories": int(len(values)),
                "mu_star_ci_low": (
                    float(np.quantile(bootstrap_mu_star, 0.025))
                    if len(bootstrap_mu_star) else np.nan
                ),
                "mu_star_ci_high": (
                    float(np.quantile(bootstrap_mu_star, 0.975))
                    if len(bootstrap_mu_star) else np.nan
                ),
            }
        )

    index_frame = pd.DataFrame(index_rows)
    outcome_scales = means[list(outcomes)].std(axis=0, ddof=1).replace(0.0, np.nan)
    ranking = (
        index_frame.assign(
            normalized_mu_star=lambda frame: frame.apply(
                lambda row: row["mu_star"] / outcome_scales.get(row["outcome"], np.nan),
                axis=1,
            )
        )
        .groupby("parameter", as_index=False)["normalized_mu_star"]
        .mean()
        .rename(columns={"normalized_mu_star": "mean_normalized_mu_star"})
        .sort_values("mean_normalized_mu_star", ascending=False)
        .reset_index(drop=True)
    )
    return index_frame, ranking


def _partial_rank_correlation(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    if x.ndim != 2:
        return np.asarray([], dtype=float)
    if len(y) != x.shape[0] or x.shape[0] <= x.shape[1] + 2:
        return np.full(x.shape[1], np.nan)
    ranked = np.column_stack(
        [rankdata(x[:, index], method="average") for index in range(x.shape[1])]
        + [rankdata(y, method="average")]
    )
    if np.any(np.std(ranked, axis=0) == 0.0):
        return np.full(x.shape[1], np.nan)
    correlation = np.corrcoef(ranked, rowvar=False)
    if not np.all(np.isfinite(correlation)):
        return np.full(x.shape[1], np.nan)
    precision = np.linalg.pinv(correlation)
    denominator = np.sqrt(precision[-1, -1] * np.diag(precision)[:-1])
    if np.any(denominator <= 0.0):
        return np.full(x.shape[1], np.nan)
    return np.clip(-precision[:-1, -1] / denominator, -1.0, 1.0)


def compute_prcc(
    results: pd.DataFrame,
    design: pd.DataFrame,
    names: list[str],
    outcomes: tuple[str, ...],
    bootstrap_samples: int,
    seed: int,
) -> pd.DataFrame:
    means = _mean_by_sample(results)
    samples = design.set_index("sample_id").loc[means.index]
    x = samples[names].to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    rows = []
    for outcome in outcomes:
        y = means[outcome].to_numpy(dtype=float)
        coefficients = _partial_rank_correlation(x, y)
        bootstraps = [[] for _ in names]
        for _ in range(bootstrap_samples):
            indices = rng.integers(0, len(y), size=len(y))
            values = _partial_rank_correlation(x[indices], y[indices])
            for parameter_index, value in enumerate(values):
                if np.isfinite(value):
                    bootstraps[parameter_index].append(float(value))
        for parameter_index, name in enumerate(names):
            values = np.asarray(bootstraps[parameter_index], dtype=float)
            rows.append(
                {
                    "parameter": name,
                    "outcome": outcome,
                    "prcc": float(coefficients[parameter_index]),
                    "prcc_ci_low": (
                        float(np.quantile(values, 0.025)) if len(values) else np.nan
                    ),
                    "prcc_ci_high": (
                        float(np.quantile(values, 0.975)) if len(values) else np.nan
                    ),
                    "n_parameter_points": int(len(y)),
                }
            )
    return pd.DataFrame(rows)


def summarize_seed_variability(results: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (method, sample_id), group in results.groupby(
        ["method", "sample_id"], dropna=False, sort=False
    ):
        row = {
            "method": method,
            "sample_id": sample_id,
            "n_seed_replicates": int(len(group)),
        }
        for outcome in OUTCOMES:
            values = group[outcome].to_numpy(dtype=float)
            mean = float(np.mean(values))
            sd = float(np.std(values, ddof=1)) if len(values) > 1 else np.nan
            row[f"{outcome}_mean"] = mean
            row[f"{outcome}_sd_across_seeds"] = sd
            row[f"{outcome}_sem_across_seeds"] = (
                float(sd / np.sqrt(len(values))) if np.isfinite(sd) else np.nan
            )
        rows.append(row)
    return pd.DataFrame(rows)


def _build_base_kwargs(args) -> dict:
    common = SimpleNamespace(
        persons=args.persons,
        baseline_days=args.baseline_days,
        pre_flood_days=args.pre_flood_days,
        flood_days=args.flood_days,
        post_flood_days=args.post_flood_days,
        map="uvalde",
        house_mold_rate=MODEL_DEFAULTS["house_mold_rate"],
        business_mold_rate=MODEL_DEFAULTS["business_mold_rate"],
        gov_baseline_grant_every_hours=None,
    )
    return build_common_model_kwargs(
        common,
        resolve_data_dir(ROOT, "uvalde"),
        extra_kwargs={
            "scenario_mode": "compound",
            "enable_infectious": 1,
            "enable_stagnant": 1,
            "enable_mold": 1,
        },
    )


def _make_seeds(seed_base: int, replications: int) -> list[int]:
    sequence = np.random.SeedSequence(seed_base)
    children = sequence.spawn(replications)
    return [
        int(child.generate_state(1, dtype=np.uint32)[0])
        for child in children
    ]


def _write_config(out_dir: Path, args, names: list[str], seeds: list[int]) -> None:
    config = {
        "scenario": "compound",
        "persons": int(args.persons),
        "timeline_days": {
            "baseline": int(args.baseline_days),
            "warning": int(args.pre_flood_days),
            "flood": int(args.flood_days),
            "recovery": int(args.post_flood_days),
        },
        "method": args.method,
        "design_options": {
            "morris_trajectories": int(args.morris_trajectories),
            "morris_levels": int(args.morris_levels),
            "lhs_samples": int(args.lhs_samples),
            "top_k": int(args.top_k),
            "bootstrap_samples": int(args.bootstrap_samples),
        },
        "outcomes": list(OUTCOMES),
        "parameters": {
            name: {
                "low": PARAMETER_SPECS[name]["low"],
                "high": PARAMETER_SPECS[name]["high"],
                "default": _parameter_default(name, args),
                "kind": PARAMETER_SPECS[name]["kind"],
            }
            for name in names
        },
        "replications_per_point": int(args.replications_per_point),
        "seed_base": int(args.seed_base),
        "seeds": seeds,
        "provisional_ranges_notice": (
            "Screening ranges are provisional stress bounds and are not empirical "
            "confidence intervals."
        ),
    }
    (out_dir / "analysis_config.json").write_text(
        json.dumps(config, indent=2), encoding="utf-8"
    )


def _prepare_output_dir(path: Path) -> Path:
    out_dir = path.resolve()
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def generate_default_design(names: list[str], args) -> pd.DataFrame:
    unit_values = []
    for name in names:
        spec = PARAMETER_SPECS[name]
        low = float(spec["low"])
        high = float(spec["high"])
        default = _parameter_default(name, args)
        if not low <= default <= high:
            raise ValueError(
                f"Default for {name} ({default}) is outside its screening range "
                f"[{low}, {high}]."
            )
        unit_values.append((default - low) / (high - low))
    return pd.DataFrame(
        [
            _make_design_row(
                "BASE00000",
                "baseline",
                names,
                np.asarray(unit_values, dtype=float),
            )
        ]
    )


def _run_local_analysis(args, out_dir: Path) -> int:
    names = _parameter_names(args.parameters)
    seeds = _make_seeds(args.seed_base, args.replications_per_point)
    base_kwargs = _build_base_kwargs(args)
    timeline = SimpleNamespace(
        baseline_days=args.baseline_days,
        pre_flood_days=args.pre_flood_days,
        flood_days=args.flood_days,
    )
    out_dir = _prepare_output_dir(out_dir)
    _write_config(out_dir, args, names, seeds)
    baseline_design = generate_default_design(names, args)
    baseline_design.to_csv(out_dir / "design_baseline.csv", index=False)

    if args.method in {"morris", "both"}:
        morris_design, transitions, _ = generate_morris_design(
            names,
            args.morris_trajectories,
            args.morris_levels,
            args.seed_base + 1,
        )
        morris_design.to_csv(out_dir / "design_morris.csv", index=False)
        transitions.to_csv(out_dir / "morris_transitions.csv", index=False)
        if args.plan_only:
            planned_points = len(baseline_design) + len(morris_design)
            if args.method == "both":
                planned_points += args.lhs_samples
            print(
                f"{args.method} plan: {planned_points} parameter points, "
                f"{planned_points * len(seeds)} model runs. "
                "The LHS points in `both` are generated after Morris ranking."
            )
            return 0

    if args.method == "lhs":
        lhs_names = names
        if args.lhs_samples < len(lhs_names) + 2:
            raise ValueError(
                f"LHS samples must be at least {len(lhs_names) + 2} "
                f"for PRCC with {len(lhs_names)} parameters."
            )
        lhs_design = generate_lhs_design(
            lhs_names, args.lhs_samples, args.seed_base + 3
        )
        lhs_design.to_csv(out_dir / "design_lhs.csv", index=False)
        if args.plan_only:
            planned_points = len(baseline_design) + len(lhs_design)
            print(
                f"LHS plan: {planned_points} parameter points, "
                f"{planned_points * len(seeds)} model runs."
            )
            return 0
    else:
        lhs_names = []
        lhs_design = pd.DataFrame()

    if Model is None:
        raise RuntimeError(f"Cannot import model: {MODEL_IMPORT_ERROR}")

    morris_points = len(morris_design) if args.method in {"morris", "both"} else 0
    lhs_points = args.lhs_samples if args.method in {"lhs", "both"} else 0
    total_runs = (
        len(baseline_design) + morris_points + lhs_points
    ) * len(seeds)
    started_at = time.time()
    _write_progress(out_dir, 0, total_runs, started_at, "baseline")
    all_results = []
    baseline_results, completed = run_design(
        baseline_design,
        names,
        base_kwargs,
        seeds,
        timeline,
        args.workers,
        out_dir,
        "baseline",
        0,
        total_runs,
        started_at,
    )
    all_results.append(baseline_results)

    if args.method in {"morris", "both"}:
        morris_results, completed = run_design(
            morris_design,
            names,
            base_kwargs,
            seeds,
            timeline,
            args.workers,
            out_dir,
            "morris",
            completed,
            total_runs,
            started_at,
        )
        all_results.append(morris_results)
        indices, ranking = compute_morris_indices(
            morris_results,
            transitions,
            OUTCOMES,
            args.bootstrap_samples,
            args.seed_base + 2,
        )
        indices.to_csv(out_dir / "morris_indices.csv", index=False)
        ranking.to_csv(out_dir / "morris_parameter_ranking.csv", index=False)

        if args.method == "both":
            lhs_names = ranking["parameter"].head(args.top_k).tolist()
            if not lhs_names:
                raise ValueError(
                    "Morris screening did not produce parameters for LHS/PRCC."
                )
            print(
                "Refining top parameters with LHS/PRCC: "
                + ", ".join(lhs_names)
            )
            if args.lhs_samples < len(lhs_names) + 2:
                raise ValueError(
                    f"LHS samples must be at least {len(lhs_names) + 2} "
                    f"for PRCC with {len(lhs_names)} parameters."
                )
            lhs_design = generate_lhs_design(
                lhs_names, args.lhs_samples, args.seed_base + 3
            )
            lhs_design.to_csv(out_dir / "design_lhs.csv", index=False)

    if args.method in {"lhs", "both"}:
        lhs_results, completed = run_design(
            lhs_design,
            lhs_names,
            base_kwargs,
            seeds,
            timeline,
            args.workers,
            out_dir,
            "lhs",
            completed,
            total_runs,
            started_at,
        )
        all_results.append(lhs_results)
        prcc = compute_prcc(
            lhs_results,
            lhs_design,
            lhs_names,
            OUTCOMES,
            args.bootstrap_samples,
            args.seed_base + 4,
        )
        prcc.to_csv(out_dir / "prcc_indices.csv", index=False)

    combined = pd.concat(all_results, ignore_index=True)
    combined.to_csv(out_dir / "run_results.csv", index=False)
    summarize_seed_variability(combined).to_csv(
        out_dir / "within_point_variability.csv", index=False
    )
    _write_progress(out_dir, completed, total_runs, started_at, "complete")
    print(f"Sensitivity analysis complete: {out_dir}")
    return 0


def _remote_batch_arguments(args, remote_out_dir: str) -> str:
    values = [
        "--method", args.method,
        "--persons", str(args.persons),
        "--baseline-days", str(args.baseline_days),
        "--pre-flood-days", str(args.pre_flood_days),
        "--flood-days", str(args.flood_days),
        "--post-flood-days", str(args.post_flood_days),
        "--parameters", args.parameters,
        "--morris-trajectories", str(args.morris_trajectories),
        "--morris-levels", str(args.morris_levels),
        "--lhs-samples", str(args.lhs_samples),
        "--top-k", str(args.top_k),
        "--replications-per-point", str(args.replications_per_point),
        "--bootstrap-samples", str(args.bootstrap_samples),
        "--seed-base", str(args.seed_base),
        "--workers", str(args.remote_workers),
        "--out-dir", remote_out_dir,
    ]
    return shlex.join(values)


def _remote_repo_path(target: str, user: str, repository: str) -> str:
    if repository.startswith("/"):
        return repository.rstrip("/")
    root = "/scratch-gladwell" if target == "gottlieb" else "/scratch"
    return f"{root}/{user}/{repository}"


def _orchestrate_remote(args) -> int:
    if not args.remote_user:
        raise ValueError(
            "Set --remote-user or FLOODDISEASE_ABM_REMOTE_USER for remote execution."
        )

    experiment_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    experiment_name = f"compound_{args.method}_{args.persons}p_{experiment_id}"
    remote_out_dir = f"outputs/sensitivity_analysis/{experiment_name}"
    local_out_dir = (
        Path(args.out_dir).resolve()
        if args.out_dir
        else (ROOT / remote_out_dir).resolve()
    )
    remote_repo = _remote_repo_path(
        args.remote_target, args.remote_user, args.remote_repo
    )
    sync_script = ROOT / "scripts" / "sync_remote_via_tux.ps1"
    launch_script = ROOT / "scripts" / "run_remote_batch_via_tux.ps1"
    pull_script = ROOT / "scripts" / "pull_sensitivity_results_via_tux.ps1"

    if not sync_script.exists() or not launch_script.exists() or not pull_script.exists():
        raise FileNotFoundError("A required key-based remote helper script is missing.")

    print(f"[REMOTE] Syncing sensitivity runner to {args.remote_target} via SSH key...")
    sync_command = [
        "powershell",
        "-NoProfile",
        "-File",
        str(sync_script),
        "-LocalRepo",
        str(ROOT),
        "-Target",
        args.remote_target,
        "-TargetUser",
        args.remote_user,
        "-TuxUser",
        args.tux_user,
        "-TuxHost",
        args.tux_host,
        "-RemoteRepo",
        remote_repo,
        "-VerifyPython",
    ]
    if args.remote_ssh_key:
        sync_command.extend(["-SshKey", args.remote_ssh_key])
    sync_result = subprocess.run(sync_command, check=False)
    if sync_result.returncode != 0:
        raise RuntimeError(
            f"Remote repository sync failed with exit code {sync_result.returncode}. "
            "See the sync helper's message above for the network, DNS, or SSH-authentication cause."
        )

    batch_args = _remote_batch_arguments(args, remote_out_dir)
    session_name = f"sens_{args.remote_target}_{experiment_id}"
    launch_command = [
        "powershell",
        "-NoProfile",
        "-File",
        str(launch_script),
        "-Target",
        args.remote_target,
        "-TargetUser",
        args.remote_user,
        "-TuxUser",
        args.tux_user,
        "-TuxHost",
        args.tux_host,
        "-RemoteRepo",
        remote_repo,
        "-SessionName",
        session_name,
        "-Runner",
        "sensitivity_analysis",
        "-BatchArgs",
        batch_args,
    ]
    if args.remote_ssh_key:
        launch_command.extend(["-SshKey", args.remote_ssh_key])
    launch_result = subprocess.run(launch_command, check=False)
    if launch_result.returncode != 0:
        raise RuntimeError(
            f"Key-based remote launch failed with exit code {launch_result.returncode}."
        )

    pull_command = [
        "powershell",
        "-NoProfile",
        "-File",
        str(pull_script),
        "-Target",
        args.remote_target,
        "-TargetUser",
        args.remote_user,
        "-TuxUser",
        args.tux_user,
        "-TuxHost",
        args.tux_host,
        "-RemoteRepo",
        remote_repo,
        "-RemoteOutDir",
        remote_out_dir,
        "-LocalOutDir",
        str(local_out_dir),
        "-SessionName",
        session_name,
        "-PollSeconds",
        str(args.remote_poll_seconds),
        "-MaxPolls",
        str(args.remote_max_polls),
    ]
    if args.remote_ssh_key:
        pull_command.extend(["-SshKey", args.remote_ssh_key])
    pull_result = subprocess.run(pull_command, check=False)
    if pull_result.returncode != 0:
        raise RuntimeError(
            f"Remote monitoring/result transfer failed with exit code {pull_result.returncode}."
        )

    if not (local_out_dir / "run_results.csv").exists():
        raise FileNotFoundError(
            f"Remote pull did not include run_results.csv under {local_out_dir}."
        )
    print(f"[REMOTE] Results pulled to {local_out_dir}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run Morris screening and optional LHS/PRCC sensitivity analysis "
            "for the compound Flood-Disease ABM scenario."
        )
    )
    parser.add_argument("--method", choices=("morris", "lhs", "both"), default="both")
    parser.add_argument(
        "--parameters",
        default="core",
        help="Use `core`, `extended` (all defined inputs), or a comma-separated list.",
    )
    parser.add_argument("--persons", type=int, default=5000)
    parser.add_argument("--baseline-days", type=int, default=RUN_DEFAULTS["baseline_days"])
    parser.add_argument("--pre-flood-days", type=int, default=RUN_DEFAULTS["pre_flood_days"])
    parser.add_argument("--flood-days", type=int, default=RUN_DEFAULTS["flood_days"])
    parser.add_argument("--post-flood-days", type=int, default=RUN_DEFAULTS["post_flood_days"])
    parser.add_argument("--morris-trajectories", type=int, default=8)
    parser.add_argument("--morris-levels", type=int, default=4)
    parser.add_argument("--lhs-samples", type=int, default=96)
    parser.add_argument("--top-k", type=int, default=6)
    parser.add_argument("--replications-per-point", type=int, default=3)
    parser.add_argument("--bootstrap-samples", type=int, default=200)
    parser.add_argument("--seed-base", type=int, default=1500154)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--out-dir", type=str, default=None)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--remote", action="store_true")
    parser.add_argument("--gottlieb", action="store_true")
    parser.add_argument("--richardson", action="store_true")
    parser.add_argument("--hundsdorfer", action="store_true")
    parser.add_argument(
        "--remote-target",
        choices=("gottlieb", "richardson", "hundsdorfer"),
        default="gottlieb",
    )
    parser.add_argument(
        "--remote-user",
        default=os.environ.get("FLOODDISEASE_ABM_REMOTE_USER", "oaa721"),
    )
    parser.add_argument(
        "--tux-user",
        default=os.environ.get("FLOODDISEASE_ABM_TUX_USER", "oaa721"),
        help="Tux jump-host account; defaults to the account used by existing lab scripts.",
    )
    parser.add_argument(
        "--tux-host",
        default=os.environ.get("FLOODDISEASE_ABM_TUX_HOST", "tuxworld.usask.ca"),
    )
    parser.add_argument(
        "--remote-ssh-key",
        default=os.environ.get("FLOODDISEASE_ABM_SSH_KEY"),
        help="Optional SSH key path; defaults to the key path used by the lab PowerShell scripts.",
    )
    parser.add_argument("--remote-repo", default="floodDisease_abm")
    parser.add_argument("--remote-workers", type=int, default=12)
    parser.add_argument("--remote-poll-seconds", type=int, default=300)
    parser.add_argument("--remote-max-polls", type=int, default=240)
    return parser


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    try:
        names = _parameter_names(args.parameters)
        if args.persons <= 0:
            raise ValueError("--persons must be positive.")
        if args.replications_per_point <= 0:
            raise ValueError("--replications-per-point must be positive.")
        if args.workers < 0 or args.remote_workers <= 0:
            raise ValueError("Worker counts must be positive, or --workers may be zero.")
        if args.method == "both" and (args.top_k <= 0 or args.top_k > len(names)):
            raise ValueError("--top-k must be between 1 and the selected parameter count.")
        if args.method == "both" and args.lhs_samples < args.top_k + 2:
            raise ValueError("--lhs-samples must be at least --top-k plus two.")
        if args.gottlieb:
            args.remote = True
            args.remote_target = "gottlieb"
        elif args.richardson:
            args.remote = True
            args.remote_target = "richardson"
        elif args.hundsdorfer:
            args.remote = True
            args.remote_target = "hundsdorfer"

        if args.plan_only and args.remote:
            raise ValueError("--plan-only is local; omit --remote.")

        if args.remote:
            return _orchestrate_remote(args)

        if args.workers == 0:
            args.workers = max(1, os.cpu_count() or 1)
        experiment_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = (
            Path(args.out_dir)
            if args.out_dir
            else ROOT / "outputs" / "sensitivity_analysis" / f"compound_{args.method}_{experiment_id}"
        )
        return _run_local_analysis(args, out_dir)
    except Exception as exc:
        print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
