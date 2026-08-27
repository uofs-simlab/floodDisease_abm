from __future__ import annotations

import argparse
from pathlib import Path
import sys
import warnings
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shutil
from pandas.errors import PerformanceWarning

warnings.filterwarnings("ignore", category=PerformanceWarning, message="DataFrame is highly fragmented.*")

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate flood-hazard diagnostics graphs (mirrors baseline).")
    p.add_argument("--run-dir", required=True, help="Path to scenario run root (contains flood_only, flood_mold, flood_vectorborne, or flood_mold_vectorborne/).")
    p.add_argument("--scenario", default="flood_only", help="Scenario folder name, e.g. flood_only, flood_mold, flood_vectorborne, or flood_mold_vectorborne.")
    p.add_argument("--out-subdir", default=None, help="Output subdirectory name under run-dir.")
    return p.parse_args()

# Import shared plotting helpers without making baseline the flood generator's dependency.
# Ensure this works when executed as a standalone file.
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from .plotting import (
    _pick,
    _plot_lines,
    _inject_active_hour_series,
    _plot_hour_of_day_profile,
    _plot_static_bars,
    prepare_generation,
    write_manifest,
)


def _plot_structural_impact_timeline(df_q: pd.DataFrame, out: Path, title_prefix: str) -> None:
    if df_q.empty or "hours" not in df_q.columns:
        return

    x = df_q["hours"]
    fig, ax_left = plt.subplots(figsize=(12, 5))

    left_series = [
        ("house_flooded_pct", "Houses Currently Flooded (%)", "#C0392B"),
        ("biz_flooded_pct", "Businesses Currently Flooded (%)", "#D35400"),
        ("house_molded_pct", "Houses with Mold (%)", "#117A65"),
        ("biz_molded_pct", "Businesses with Mold (%)", "#16A085"),
        ("school_flooded_pct", "Schools Flooded (%)", "#8E44AD"),
        ("school_molded_pct", "Schools with Mold (%)", "#9B59B6"),
    ]

    handles = []
    labels = []

    for base, label, color in left_series:
        col = _pick(df_q, base)
        if not col:
            continue
        y = pd.to_numeric(df_q[col], errors="coerce")
        if base in {"house_molded_pct", "biz_molded_pct"} and float(y.fillna(0.0).max()) <= 0.0:
            continue
        h, = ax_left.plot(x, y, color=color, linewidth=2, label=label)
        handles.append(h)
        labels.append(label)

        q25_col = f"{base}_q25"
        q75_col = f"{base}_q75"
        if q25_col in df_q.columns and q75_col in df_q.columns:
            q25 = pd.to_numeric(df_q[q25_col], errors="coerce")
            q75 = pd.to_numeric(df_q[q75_col], errors="coerce")
            ax_left.fill_between(x, q25, q75, color=color, alpha=0.12)

    ax_left.set_title(f"{title_prefix} Structural Impact Timeline")
    ax_left.set_xlabel("Hour")
    ax_left.set_ylabel("Impact (% of entities)")
    ax_left.grid(alpha=0.3)

    if handles:
        ax_left.legend(handles=handles, labels=labels, fontsize=9, loc="upper right")

    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def _plot_endstate_bars(df_all: pd.DataFrame, metric_specs: list[tuple[str, str] | tuple[str, str, str]], title: str, out: Path) -> None:
    if df_all.empty or not metric_specs:
        return
    if "replication" in df_all.columns and "hours" in df_all.columns:
        final_rows = df_all.sort_values("hours").groupby("replication", as_index=False).tail(1).set_index("replication")
    else:
        final_rows = df_all.tail(1).copy()
        final_rows = final_rows.assign(replication=0).set_index("replication")

    peak_rows = None
    peak_q90_rows = None
    if "replication" in df_all.columns and "hours" in df_all.columns:
        numeric_cols = [c for c in df_all.columns if c not in {"replication", "hours", "seed", "out_dir"}]
        peak_rows = df_all.groupby("replication", as_index=True)[numeric_cols].max(numeric_only=True)
        peak_q90_rows = df_all.groupby("replication", as_index=True)[numeric_cols].quantile(0.90, numeric_only=True)

    labels = []
    medians = []
    err_low = []
    err_high = []

    for spec in metric_specs:
        if len(spec) == 2:
            metric, label = spec
            agg_mode = "final"
        else:
            metric, label, agg_mode = spec

        source = final_rows
        series = pd.Series(dtype=float)
        if agg_mode == "peak" and peak_rows is not None:
            source = peak_rows
            if metric in source.columns:
                series = pd.to_numeric(source[metric], errors="coerce").dropna()
        elif agg_mode == "peak_q90" and peak_q90_rows is not None:
            source = peak_q90_rows
            if metric in source.columns:
                series = pd.to_numeric(source[metric], errors="coerce").dropna()
        elif agg_mode == "at_hc_peak" and "replication" in df_all.columns and "hc_util_pct" in df_all.columns:
            vals = []
            for _, grp in df_all.groupby("replication", as_index=False):
                if metric not in grp.columns:
                    continue
                hc = pd.to_numeric(grp["hc_util_pct"], errors="coerce")
                if hc.isna().all():
                    continue
                idx = hc.idxmax()
                v = pd.to_numeric(pd.Series([grp.loc[idx, metric]]), errors="coerce").iloc[0]
                if pd.notna(v):
                    vals.append(float(v))
            series = pd.Series(vals, dtype=float)
        else:
            if metric in source.columns:
                series = pd.to_numeric(source[metric], errors="coerce").dropna()

        if series.empty:
            continue
        q25 = float(series.quantile(0.25))
        q50 = float(series.quantile(0.50))
        q75 = float(series.quantile(0.75))
        labels.append(label)
        medians.append(q50)
        err_low.append(max(0.0, q50 - q25))
        err_high.append(max(0.0, q75 - q50))

    if not labels:
        return

    x = np.arange(len(labels))
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.bar(x, medians, yerr=[err_low, err_high], capsize=5, color="#4C78A8", alpha=0.88)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.set_title(title)
    ax.set_ylabel("Percent")
    ax.set_ylim(bottom=0.0)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def generate_flood_scenario_graphs(run_dir: Path, scenario: str, out_subdir: str | None = None) -> Path:
    scenario_key = str(scenario or "flood_only").strip().lower()
    scenario_meta = {
        "flood_only": {
            "title_prefix": "Flood-Only",
            "file_stem": "floodonly",
            "manifest": "floodonly_graph_manifest.txt",
            "out_subdir": "floodonly_graphs",
        },
        "flood_mold": {
            "title_prefix": "Flood-Mold",
            "file_stem": "flood_mold",
            "manifest": "flood_mold_graph_manifest.txt",
            "out_subdir": "flood_mold_graphs",
        },
        "flood_vectorborne": {
            "title_prefix": "Flood-Vectorborne",
            "file_stem": "flood_vectorborne",
            "manifest": "flood_vectorborne_graph_manifest.txt",
            "out_subdir": "flood_vectorborne_graphs",
        },
        "flood_mold_vectorborne": {
            "title_prefix": "Flood-Mold-Vectorborne",
            "file_stem": "flood_mold_vectorborne",
            "manifest": "flood_mold_vectorborne_graph_manifest.txt",
            "out_subdir": "flood_mold_vectorborne_graphs",
        },
        "full_compound": {
            "title_prefix": "Full Compound",
            "file_stem": "full_compound",
            "manifest": "full_compound_graph_manifest.txt",
            "out_subdir": "full_compound_graphs",
        },
        "flood_infectious": {
            "title_prefix": "Flood-Infectious",
            "file_stem": "flood_infectious",
            "manifest": "flood_infectious_graph_manifest.txt",
            "out_subdir": "flood_infectious_graphs",
        },
    }
    # Backward-compatibility aliases for older output folders / scripts.
    if scenario_key == "flood_mold":
        scenario_key = "flood_mold"
    if scenario_key == "flood_vectorborne":
        scenario_key = "flood_vectorborne"
    meta = scenario_meta.get(scenario_key, scenario_meta["flood_only"])

    run_dir = Path(run_dir).resolve()
    out_subdir = out_subdir or meta["out_subdir"]
    _, out_dir, df_all, df_q = prepare_generation(run_dir, scenario, out_subdir)

    # 1) Population and displacement states (combined)
    _plot_lines(
        df_q,
        [
            ("dead_pct", "Deaths"),
            ("evacuated_pct", "Evacuated"),
            ("stranded_pct", "Stranded"),
            ("in_shelter_pct", "In Shelter"),
            ("in_healthcare_pct", "In Healthcare"),
        ],
        f"{meta['title_prefix']} Population Stability & Displacement States",
        "Percent",
        out_dir / f"{meta['file_stem']}_01_population_stability.png",
    )

    # 2) Attendance and institutions
    _plot_lines(
        df_q,
        [("work_attendance_schoolday_mean", "Work Attendance (Work Hours)"), ("school_attendance_schoolday_mean", "School Attendance (School Hours)"), ("normal_activity_pct", "Normal Activity")],
        f"{meta['title_prefix']} Attendance Dynamics",
        "Percent",
        out_dir / f"{meta['file_stem']}_03_attendance.png",
    )
    _plot_structural_impact_timeline(
        df_q,
        out_dir / f"{meta['file_stem']}_02_structural_impact_timeline.png",
        meta["title_prefix"],
    )
    _plot_lines(
        df_q,
        [("biz_open_pct", "Businesses Open"), ("school_open_now_pct", "Schools Open"), ("house_hab_pct", "Habitable Houses")],
        f"{meta['title_prefix']} Infrastructure Availability",
        "Percent",
        out_dir / f"{meta['file_stem']}_04_infrastructure.png",
    )

    if scenario_key == "flood_only":
        if "healthcare_expense_vectorborne_total" not in df_q.columns and "healthcare_expense_stagnant_total" in df_q.columns:
            df_q["healthcare_expense_vectorborne_total"] = pd.to_numeric(df_q["healthcare_expense_stagnant_total"], errors="coerce").fillna(0.0)
        for c in (
            "healthcare_expense_flood_total",
            "healthcare_expense_mold_total",
            "healthcare_expense_vectorborne_total",
            "healthcare_expense_infectious_total",
        ):
            if c not in df_q.columns:
                df_q[c] = 0.0
        df_q["healthcare_expense_total"] = (
            pd.to_numeric(df_q["healthcare_expense_flood_total"], errors="coerce").fillna(0.0)
            + pd.to_numeric(df_q["healthcare_expense_mold_total"], errors="coerce").fillna(0.0)
            + pd.to_numeric(df_q["healthcare_expense_vectorborne_total"], errors="coerce").fillna(0.0)
            + pd.to_numeric(df_q["healthcare_expense_infectious_total"], errors="coerce").fillna(0.0)
        )
        impact_series = [
            ("evacuation_expense_total", "Evacuation Expense"),
            ("healthcare_expense_total", "Healthcare Expense (Total)"),
        ]
    else:
        vector_expense_label = "Healthcare Expense (Vectorborne)" if scenario_key in {"flood_vectorborne", "flood_mold_vectorborne"} else "Healthcare Expense (Vectorborne)"
        impact_series = [
            ("evacuation_expense_total", "Evacuation Expense"),
            ("house_repair_expense_total", "House Repair Expense"),
            ("business_repair_expense_total", "Business Repair Expense"),
            ("healthcare_expense_flood_total", "Healthcare Expense (Flood)"),
            ("healthcare_expense_mold_total", "Healthcare Expense (Mold)"),
            ("healthcare_expense_vectorborne_total", vector_expense_label),
            ("healthcare_expense_infectious_total", "Healthcare Expense (Infectious)"),
        ]
        filtered: list[tuple[str, str]] = []
        for key, label in impact_series:
            col = _pick(df_q, key)
            if not col:
                continue
            y = pd.to_numeric(df_q[col], errors="coerce").fillna(0.0)
            if float(y.max()) > 0.0:
                filtered.append((key, label))
        impact_series = filtered or [("evacuation_expense_total", "Evacuation Expense")]

    _plot_lines(
        df_q,
        impact_series,
        f"{meta['title_prefix']} Cumulative Impact Expenses",
        "Currency Units",
        out_dir / f"{meta['file_stem']}_05a_impact_expenses.png",
    )
    affected_metric_specs = [
        ("evacuated_pct", "Evacuated", "peak"),
        ("affected_stranded_unique_pct", "Stranded", "final"),
        ("affected_sheltered_unique_pct", "Sheltered", "final"),
        ("affected_healthcare_unique_pct", "Healthcare (ever)", "final"),
        ("affected_injured_unique_pct", "Injured", "final"),
        ("dead_pct", "Deaths", "final"),
    ]
    if scenario_key in {"flood_mold", "flood_mold_vectorborne", "full_compound"}:
        affected_metric_specs.extend([
            ("affected_mold_pct", "Affected by Mold", "final"),
        ])
    if scenario_key in {"flood_vectorborne", "flood_mold_vectorborne", "full_compound"}:
        affected_metric_specs.extend([
            ("affected_vectorborne_pct", "Affected by Vectorborne", "final"),
        ])
    if scenario_key == "full_compound":
        affected_metric_specs.extend([
            ("affected_infectious_pct", "Affected by Infectious", "final"),
        ])
    _plot_endstate_bars(
        df_all,
        affected_metric_specs,
        f"{meta['title_prefix']} End-of-Simulation Affected Population Statistics",
        out_dir / f"{meta['file_stem']}_05b_affected_population_pct.png",
    )
    # Population-based: % of total population who ever visited healthcare for each cause.
    # ever_hc_* flags are set at admission time; "final" reads the last sim hour (cumulative).
    healthcare_cause_specs = [
        ("affected_hc_flood_pct", "Flood", "final"),
        ("affected_hc_mold_pct", "Mold", "final"),
        ("affected_hc_vectorborne_pct", "Vectorborne", "final"),
        ("affected_hc_infectious_pct", "Infectious", "final"),
        ("affected_hc_compound_pct", "Compound (2+ causes)", "final"),
    ]
    if scenario_key == "flood_mold":
        healthcare_cause_specs = [
            ("affected_hc_flood_pct", "Flood", "final"),
            ("affected_hc_mold_pct", "Mold", "final"),
            ("affected_hc_compound_pct", "Compound (2+ causes)", "final"),
        ]
    elif scenario_key == "flood_vectorborne":
        healthcare_cause_specs = [
            ("affected_hc_flood_pct", "Flood", "final"),
            ("affected_hc_vectorborne_pct", "Vectorborne", "final"),
            ("affected_hc_compound_pct", "Compound (2+ causes)", "final"),
        ]
    elif scenario_key == "flood_only":
        healthcare_cause_specs = [
            ("affected_hc_flood_pct", "Flood", "final"),
        ]
    _plot_endstate_bars(
        df_all,
        healthcare_cause_specs,
        f"{meta['title_prefix']} % of Population Ever Hospitalised by Cause",
        out_dir / f"{meta['file_stem']}_05c_healthcare_by_cause_pct.png",
    )

    # 3) Economics and quality of life
    _plot_lines(
        df_q,
        [
            ("biz_wealth_total", "Business Wealth"),
            ("gov_wealth", "Government Wealth"),
            ("shelter_wealth", "Shelter Wealth"),
            ("hc_wealth", "Healthcare Wealth"),
            ("person_wealth_total_scaled", "Person Wealth"),
        ],
        f"{meta['title_prefix']} Institutional Wealth",
        "Currency Units",
        out_dir / f"{meta['file_stem']}_06_finance.png",
    )
    # Separate QoL plots by group
    _plot_lines(
        df_q,
        [("qol_children_pct", "QoL Children"), ("qol_adults_pct", "QoL Adults"), ("qol_seniors_pct", "QoL Seniors")],
        f"{meta['title_prefix']} Quality of Life by Age Group",
        "Percent",
        out_dir / f"{meta['file_stem']}_07b_qol_age.png",
    )
    _plot_lines(
        df_q,
        [
            ("qol_low_income_pct", "QoL Lower Class"),
            ("qol_middle_income_pct", "QoL Middle Class"),
            ("qol_upper_middle_pct", "QoL Upper-Middle Class"),
            ("qol_upper_pct", "QoL Upper Class"),
        ],
        f"{meta['title_prefix']} Quality of Life by Wealth Group",
        "Percent",
        out_dir / f"{meta['file_stem']}_07c_qol_wealth.png",
    )
    _plot_lines(
        df_q,
        [
            ("qol_white_pct", "QoL White"),
            ("qol_black_pct", "QoL Black"),
            ("qol_hispanic_pct", "QoL Hispanic"),
            ("qol_other_pct", "QoL Other"),
        ],
        f"{meta['title_prefix']} Quality of Life by Ethnicity",
        "Percent",
        out_dir / f"{meta['file_stem']}_07d_qol_ethnicity.png",
    )
    _plot_lines(
        df_q,
        [
            ("qol_hierarchist_pct", "QoL Hierarchist"),
            ("qol_egalitarian_pct", "QoL Egalitarian"),
            ("qol_individualist_pct", "QoL Individualist"),
            ("qol_fatalist_pct", "QoL Fatalist"),
        ],
        f"{meta['title_prefix']} Quality of Life by Worldview",
        "Percent",
        out_dir / f"{meta['file_stem']}_07e_qol_worldview.png",
    )

    # 4) Health and healthcare load
    disease_series = [
        ("compound_burden_pct", "Compound Burden"),
        ("inf_prev_pct", "Infectious"),
        ("vector_symp_pct", "Vector"),
        ("mold_symp_pct", "Mold"),
    ]
    if scenario_key == "flood_only":
        disease_series = []
    if scenario_key == "flood_vectorborne":
        disease_series = [
            ("compound_burden_pct", "Disease Burden"),
            ("vector_symp_pct", "Vectorborne"),
        ]
    if scenario_key == "flood_mold":
        disease_series = [
            ("compound_burden_pct", "Disease Burden"),
            ("mold_symp_pct", "Mold"),
        ]
    if scenario_key == "flood_mold_vectorborne":
        disease_series = [
            ("compound_burden_pct", "Disease Burden"),
            ("mold_symp_pct", "Mold"),
            ("vector_symp_pct", "Vectorborne"),
        ]
    if scenario_key == "full_compound":
        disease_series = [
            ("compound_burden_pct", "Disease Burden"),
            ("inf_prev_pct", "Infectious"),
            ("mold_symp_pct", "Mold"),
            ("vector_symp_pct", "Vectorborne"),
        ]
    disease_out = out_dir / f"{meta['file_stem']}_08_disease_prevalence.png"
    if not disease_series:
        if disease_out.exists():
            disease_out.unlink()
    else:
        _plot_lines(
            df_q,
            disease_series,
            f"{meta['title_prefix']} Disease Burden",
            "Percent",
            disease_out,
        )
    hc_service_series = [
        ("hc_util_pct", "Total Healthcare Utilization"),
        ("hc_backlog_pct", "Total Healthcare Backlog"),
    ]
    if scenario_key == "flood_mold":
        hc_service_series.extend([
            ("hc_util_mold_pct", "Healthcare Utilization (Mold)"),
        ])
    if scenario_key == "flood_vectorborne":
        hc_service_series.extend([
            ("hc_util_vector_pct", "Healthcare Utilization (Vectorborne)"),
        ])
    if scenario_key == "flood_mold_vectorborne":
        hc_service_series.extend([
            ("hc_util_mold_pct", "Healthcare Utilization (Mold)"),
            ("hc_util_vector_pct", "Healthcare Utilization (Vectorborne)"),
        ])
    if scenario_key == "full_compound":
        hc_service_series.extend([
            ("hc_util_mold_pct", "Healthcare Utilization (Mold)"),
            ("hc_util_vector_pct", "Healthcare Utilization (Vectorborne)"),
            ("hc_util_infectious_pct", "Healthcare Utilization (Infectious)"),
        ])
    _plot_lines(
        df_q,
        hc_service_series,
        f"{meta['title_prefix']} Healthcare Service Load",
        "Percent",
        out_dir / f"{meta['file_stem']}_09a_healthcare_load.png",
    )

    sh_service_series = [
        ("shelter_1_util_pct", "Shelter 1 Utilization"),
        ("shelter_1_backlog_pct", "Shelter 1 Backlog"),
        ("shelter_2_util_pct", "Shelter 2 Utilization"),
        ("shelter_2_backlog_pct", "Shelter 2 Backlog"),
    ]
    _plot_lines(
        df_q,
        sh_service_series,
        f"{meta['title_prefix']} Shelter Service Load",
        "Percent",
        out_dir / f"{meta['file_stem']}_09b_shelter_load.png",
    )

    # Clean up old combined chart if it exists
    old_service_chart = out_dir / f"{meta['file_stem']}_09_service_load.png"
    if old_service_chart.exists():
        old_service_chart.unlink()

    # 5) Social and decision traces
    _plot_lines(
        df_q,
        [("mean_threat", "Mean Threat"), ("mean_coping", "Mean Coping"), ("mean_self_efficacy", "Self Efficacy"), ("mean_response_efficacy", "Response Efficacy")],
        f"{meta['title_prefix']} Decision Psychology Signals",
        "Index",
        out_dir / f"{meta['file_stem']}_10_psychology.png",
    )
    # 6) Static composition snapshot
    _plot_static_bars(df_all, out_dir / f"{meta['file_stem']}_14_population_composition.png")
    _plot_hour_of_day_profile(
        df_all,
        out_dir / f"{meta['file_stem']}_16_routine_profile_by_hour.png",
        title=f"{meta['title_prefix']} Routine Profile by Hour of Day",
    )

    # Remove retired outputs so reruns do not keep stale files in the manifest.
    for retired in [
        "floodonly_02_displacement_states.png",
        "floodonly_05_income.png",
        "floodonly_05a_income_age_gender.png",
        "floodonly_05b_income_groups.png",
        "floodonly_02b_displacement_counts.png",
        "floodonly_07a_qol_mean.png",
        "floodonly_12_rep_band_work_attendance.png",
        "floodonly_13_rep_band_qol.png",
        "floodonly_15_rep_band_work_attendance_workhours.png",
        "floodonly_17_phase_decision_sanity.png",
        "floodonly_11_decision_actions.png",
        "floodonly_01b_state_uncertainty_bands.png",
    ]:
        retired_name = retired.replace("floodonly_", f"{meta['file_stem']}_")
        retired_path = out_dir / retired_name
        if retired_path.exists():
            retired_path.unlink()

    # Summary manifest
    write_manifest(out_dir, meta["manifest"])

    files = list(out_dir.glob("*.png"))
    print(f"Saved {len(files)} {scenario_key} graphs to {out_dir}")
    return out_dir


def main() -> None:
    args = parse_args()
    generate_flood_scenario_graphs(
        run_dir=Path(args.run_dir),
        scenario=args.scenario,
        out_subdir=args.out_subdir,
    )

if __name__ == "__main__":
    main()
