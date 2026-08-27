from __future__ import annotations

import argparse
from pathlib import Path
import warnings
    # ("hc_util_flood_pct", "Healthcare Utilization (Flood)")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import numpy as np
import pandas as pd
from pandas.errors import PerformanceWarning

warnings.filterwarnings("ignore", category=PerformanceWarning, message="DataFrame is highly fragmented.*")


def _apply_plot_theme() -> None:
    plt.style.use("seaborn-v0_8-whitegrid")
    plt.rcParams.update(
        {
            "figure.facecolor": "#ffffff",
            "axes.facecolor": "#fbfcfd",
            "axes.edgecolor": "#d4dbe3",
            "axes.titleweight": "semibold",
            "axes.titlesize": 18,
            "axes.labelsize": 13,
            "xtick.labelsize": 11,
            "ytick.labelsize": 11,
            "legend.frameon": True,
            "legend.framealpha": 0.92,
            "legend.facecolor": "#ffffff",
            "legend.edgecolor": "#d4dbe3",
            "grid.alpha": 0.0,
            "grid.color": "#97a7ba",
            "lines.linewidth": 2.6,
            "axes.prop_cycle": plt.cycler(
                color=["#2E86AB", "#D95F02", "#1B9E77", "#E7298A", "#7570B3", "#66A61E", "#A6761D", "#666666"]
            ),
        }
    )


def _style_axes(ax, y_as_currency: bool = False) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#d4dbe3")
    ax.spines["bottom"].set_color("#d4dbe3")
    if y_as_currency:
        ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:,.0f}"))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate baseline-only diagnostics graphs.")
    p.add_argument("--run-dir", required=True, help="Path to scenario run root (contains baseline/).")
    p.add_argument("--scenario", default="baseline", help="Scenario folder name, default baseline.")
    p.add_argument("--out-subdir", default="baseline_graphs", help="Output subdirectory name under run-dir.")
    return p.parse_args()


def _pick(df: pd.DataFrame, base: str, prefer_quantile: bool = True) -> str | None:
    base_candidates = [base]
    if base == "person_wealth_total_scaled":
        base_candidates.extend(["person_wealth_total", "person_wealth_mean", "person_income_mean"])
    if base == "person_wealth_total":
        base_candidates.extend(["person_wealth_mean", "person_income_mean"])
    if base == "person_wealth_mean":
        base_candidates.append("person_income_mean")

    if prefer_quantile:
        for b in base_candidates:
            for c in (f"{b}_median", f"{b}_mean", b):
                if c in df.columns:
                    return c
    else:
        for b in base_candidates:
            if b in df.columns:
                return b
            for c in (f"{b}_mean", f"{b}_median"):
                if c in df.columns:
                    return c
    return None


def _plot_lines(df: pd.DataFrame, series: list[tuple[str, str]], title: str, ylabel: str, out: Path) -> None:
    _apply_plot_theme()
    fig, ax = plt.subplots(figsize=(12, 5))
    x = df["hours"] if "hours" in df.columns else np.arange(len(df))
    handles = []
    labels = []
    for base, label in series:
        c = _pick(df, base)
        if c is not None:
            y = df[c]
        else:
            # If the column is missing, plot zeros
            y = np.zeros(len(x))
        q25_col = f"{base}_q25"
        q75_col = f"{base}_q75"
        if q25_col in df.columns and q75_col in df.columns:
            ax.fill_between(x, df[q25_col], df[q75_col], alpha=0.12)
        stability_colors = {"Deaths": "black", "Evacuated": "green", "Stranded": "red", "In Shelter": "blue", "In Healthcare": "orange"}
        h, = ax.plot(x, y, linewidth=2, label=label, color=stability_colors.get(label))
        handles.append(h)
        labels.append(label)
    if not handles:
        plt.close(fig)
        return
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.set_xlabel("Hour")
    ax.grid(False)
    _style_axes(ax, y_as_currency=("currency" in str(ylabel).lower() or "wealth" in str(ylabel).lower()))
    ax.legend(handles=handles, labels=labels, fontsize=9)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def _plot_lines_indexed(df: pd.DataFrame, series: list[tuple[str, str]], title: str, ylabel: str, out: Path) -> None:
    _apply_plot_theme()
    fig, ax = plt.subplots(figsize=(12, 5))
    x = df["hours"] if "hours" in df.columns else np.arange(len(df))
    handles = []
    labels = []
    for base, label in series:
        c = _pick(df, base)
        if c is not None:
            y = pd.Series(df[c], dtype=float)
        else:
            y = pd.Series(np.zeros(len(x)), dtype=float)

        base_value = float(y.iloc[0]) if len(y) else 0.0
        denom = base_value if abs(base_value) > 1e-9 else 1.0
        y_index = 100.0 * (y / denom)

        band_bases = [base]
        if base == "person_wealth_total_scaled":
            band_bases.extend(["person_wealth_total", "person_wealth_mean", "person_income_mean"])
        if base == "person_wealth_total":
            band_bases.extend(["person_wealth_mean", "person_income_mean"])
        if base == "person_wealth_mean":
            band_bases.append("person_income_mean")
        for bb in band_bases:
            q25_col = f"{bb}_q25"
            q75_col = f"{bb}_q75"
            if q25_col in df.columns and q75_col in df.columns:
                q25 = 100.0 * (pd.Series(df[q25_col], dtype=float) / denom)
                q75 = 100.0 * (pd.Series(df[q75_col], dtype=float) / denom)
                ax.fill_between(x, q25, q75, alpha=0.12)
                break

        h, = ax.plot(x, y_index, linewidth=2, label=label)
        handles.append(h)
        labels.append(label)

    if not handles:
        plt.close(fig)
        return
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.set_xlabel("Hour")
    ax.grid(False)
    _style_axes(ax)
    ax.legend(handles=handles, labels=labels, fontsize=9)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def _plot_rep_band(df_all: pd.DataFrame, metric: str, title: str, ylabel: str, out: Path) -> None:
    if "hours" not in df_all.columns or metric not in df_all.columns or "replication" not in df_all.columns:
        return
    grp = df_all.groupby("hours")[metric]
    agg = grp.agg([
        ("q10", lambda x: float(np.nanquantile(x, 0.10))),
        ("q50", lambda x: float(np.nanquantile(x, 0.50))),
        ("q90", lambda x: float(np.nanquantile(x, 0.90))),
    ]).reset_index()

    _apply_plot_theme()
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(agg["hours"], agg["q50"], linewidth=2, label="median")
    ax.fill_between(agg["hours"], agg["q10"], agg["q90"], alpha=0.2, label="p10-p90")
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.set_xlabel("Hour")
    ax.grid(False)
    _style_axes(ax)
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def _plot_endstate_bars(df_all: pd.DataFrame, metric_specs: list[tuple[str, str] | tuple[str, str, str]], title: str, out: Path) -> None:
    if df_all.empty or not metric_specs:
        return
    if "replication" in df_all.columns and "hours" in df_all.columns:
        final_rows = df_all.sort_values("hours").groupby("replication", as_index=False).tail(1).set_index("replication")
    else:
        final_rows = df_all.tail(1).copy().assign(replication=0).set_index("replication")

    peak_rows = None
    if "replication" in df_all.columns and "hours" in df_all.columns:
        numeric_cols = [c for c in df_all.columns if c not in {"replication", "hours", "seed", "out_dir"}]
        peak_rows = df_all.groupby("replication", as_index=True)[numeric_cols].max(numeric_only=True)

    labels, medians, err_low, err_high = [], [], [], []
    for spec in metric_specs:
        if len(spec) == 2:
            metric, label = spec
            agg_mode = "final"
        else:
            metric, label, agg_mode = spec

        source = peak_rows if (agg_mode == "peak" and peak_rows is not None) else final_rows
        if source is None or metric not in source.columns:
            continue
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

    _apply_plot_theme()
    x = np.arange(len(labels))
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.bar(x, medians, yerr=[err_low, err_high], capsize=5, color="#4C78A8", alpha=0.88)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.set_title(title)
    ax.set_ylabel("Percent")
    ax.set_ylim(bottom=0.0)
    ax.grid(False)
    _style_axes(ax)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def _inject_active_hour_series(df_q: pd.DataFrame, df_all: pd.DataFrame) -> pd.DataFrame:
    if df_q.empty or df_all.empty or "hours" not in df_q.columns or "hours" not in df_all.columns:
        return df_q

    hour_of_day = (df_all["hours"] % 24).astype(int)
    work_mask = ((hour_of_day >= 8) & (hour_of_day < 12)) | ((hour_of_day >= 14) & (hour_of_day < 18))
    # Students attend 6 hours total on split windows (includes hour 16).
    school_mask = ((hour_of_day >= 8) & (hour_of_day < 11)) | ((hour_of_day >= 14) & (hour_of_day < 17))

    work_source = None
    if "work_attendance_workhours_pct" in df_all.columns:
        work_source = "work_attendance_workhours_pct"
    elif "work_attendance_scheduled_pct" in df_all.columns:
        work_source = "work_attendance_scheduled_pct"
    elif "work_attendance_pct" in df_all.columns:
        work_source = "work_attendance_pct"

    if work_source is not None:
        work_hr = (
            df_all.loc[work_mask, ["hours", work_source]]
            .groupby("hours", as_index=False)
            .mean(numeric_only=True)
            .rename(columns={work_source: "work_attendance_schoolday_mean"})
        )
        df_q = df_q.merge(work_hr, on="hours", how="left")

    if "attendance_rate_pct" in df_all.columns:
        sch_hr = (
            df_all.loc[school_mask, ["hours", "attendance_rate_pct"]]
            .groupby("hours", as_index=False)
            .mean(numeric_only=True)
            .rename(columns={"attendance_rate_pct": "school_attendance_schoolday_mean"})
        )
        df_q = df_q.merge(sch_hr, on="hours", how="left")

    if "school_attendance_scheduled_pct" in df_all.columns:
        sch_sched = (
            df_all.loc[school_mask, ["hours", "school_attendance_scheduled_pct"]]
            .groupby("hours", as_index=False)
            .mean(numeric_only=True)
            .rename(columns={"school_attendance_scheduled_pct": "school_attendance_schoolday_mean"})
        )
        df_q = df_q.drop(columns=["school_attendance_schoolday_mean"], errors="ignore").merge(sch_sched, on="hours", how="left")

    return df_q


def _plot_hour_of_day_profile(df_all: pd.DataFrame, out: Path, title: str = "Routine Profile by Hour of Day") -> None:
    if df_all.empty or "hours" not in df_all.columns:
        return

    tmp = df_all.copy()
    hour_of_day = (tmp["hours"] % 24).astype(int)
    work_in_session = ((hour_of_day >= 8) & (hour_of_day < 12)) | ((hour_of_day >= 14) & (hour_of_day < 18))
    school_in_session = ((hour_of_day >= 8) & (hour_of_day < 11)) | ((hour_of_day >= 14) & (hour_of_day < 17))

    profile_columns: list[tuple[str, str]] = []

    # Work and school should be zero outside scheduled windows for the routine profile.
    if "work_attendance_pct" in tmp.columns:
        tmp["work_attendance_profile_pct"] = np.where(work_in_session, tmp["work_attendance_pct"], 0.0)
        profile_columns.append(("work_attendance_profile_pct", "Work Attendance"))

    school_source = None
    if "school_attendance_scheduled_pct" in tmp.columns:
        school_source = "school_attendance_scheduled_pct"
    elif "attendance_rate_pct" in tmp.columns:
        school_source = "attendance_rate_pct"

    if school_source is not None:
        school_vals = pd.to_numeric(tmp[school_source], errors="coerce").fillna(0.0)
        tmp["school_attendance_profile_pct"] = np.where(school_in_session, school_vals, 0.0)
        profile_columns.append(("school_attendance_profile_pct", "School Attendance"))

    for col, label in (
        ("leisure_attendance_pct", "Leisure"),
        ("shopping_attendance_pct", "Shopping"),
    ):
        if col in tmp.columns:
            profile_columns.append((col, label))

    if not profile_columns:
        return

    metric_cols = [m for m, _ in profile_columns]
    tmp = tmp[["hours"] + metric_cols].copy()
    tmp["hour_of_day"] = tmp["hours"] % 24

    prof_p50 = tmp.groupby("hour_of_day", as_index=False)[metric_cols].quantile(0.50, numeric_only=True)
    prof_q25 = tmp.groupby("hour_of_day", as_index=False)[metric_cols].quantile(0.25, numeric_only=True)
    prof_q75 = tmp.groupby("hour_of_day", as_index=False)[metric_cols].quantile(0.75, numeric_only=True)

    prof = prof_p50.merge(prof_q25, on="hour_of_day", how="left", suffixes=("", "_q25"))
    prof = prof.merge(prof_q75, on="hour_of_day", how="left", suffixes=("", "_q75"))

    _apply_plot_theme()
    fig, ax = plt.subplots(figsize=(12, 5))
    for m, label in profile_columns:
        y = prof[m]
        q25_col = f"{m}_q25"
        q75_col = f"{m}_q75"
        if q25_col in prof.columns and q75_col in prof.columns:
            ax.fill_between(prof["hour_of_day"], prof[q25_col], prof[q75_col], alpha=0.12)
        ax.plot(prof["hour_of_day"], y, linewidth=2, label=label)
    ax.set_title(title)
    ax.set_xlabel("Hour of day")
    ax.set_ylabel("Percent")
    ax.set_xticks(range(0, 24, 2))
    ax.grid(False)
    _style_axes(ax)
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def _plot_phase_decision_sanity(df_all: pd.DataFrame, out: Path) -> None:
    if df_all.empty or "phase" not in df_all.columns:
        return
    metrics = [m for m in ["decision_evac_pct", "decision_prepare_pct", "decision_shelter_in_place_pct", "evacuated_pct", "stranded_pct"] if m in df_all.columns]
    if not metrics:
        return

    grp = df_all.groupby("phase", as_index=False)[metrics].mean(numeric_only=True)
    phases = grp["phase"].astype(str).tolist()
    x = np.arange(len(phases))

    _apply_plot_theme()
    fig, ax = plt.subplots(figsize=(12, 5))
    width = 0.13
    offsets = np.linspace(-width * (len(metrics) - 1) / 2, width * (len(metrics) - 1) / 2, len(metrics))
    for i, m in enumerate(metrics):
        ax.bar(x + offsets[i], grp[m].to_numpy(), width=width, label=m.replace("_pct", "").replace("_", " ").title())
    ax.set_xticks(x)
    ax.set_xticklabels(phases)
    ax.set_ylabel("Percent")
    ax.set_title("Baseline Sanity Check by Phase")
    ax.grid(False)
    _style_axes(ax)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def _plot_static_bars(df_all: pd.DataFrame, out: Path) -> None:
    if df_all.empty:
        return
    row = df_all.iloc[0]

    labels = []
    vals = []
    for k, lbl in (
        ("male_pct", "Male"),
        ("female_pct", "Female"),
        ("ethnicity_white_pct", "Ethnicity White"),
        ("ethnicity_black_pct", "Ethnicity Black"),
        ("ethnicity_hispanic_pct", "Ethnicity Hispanic"),
        ("ethnicity_other_pct", "Ethnicity Other"),
        ("age_0_14_pct", "Age 0-14"),
        ("age_15_64_pct", "Age 15-64"),
        ("age_65_100_pct", "Age 65+"),
        ("wealth_lower_pct", "Wealth Lower"),
        ("wealth_middle_pct", "Wealth Middle"),
        ("wealth_upper_middle_pct", "Wealth Upper-Middle"),
        ("wealth_upper_pct", "Wealth Upper"),
        ("worldview_hierarchist_pct", "Hierarchist"),
        ("worldview_egalitarian_pct", "Egalitarian"),
        ("worldview_individualist_pct", "Individualist"),
        ("worldview_fatalist_pct", "Fatalist"),
    ):
        if k in df_all.columns:
            labels.append(lbl)
            vals.append(float(row[k]))

    if not labels:
        return

    _apply_plot_theme()
    fig, ax = plt.subplots(figsize=(12, 5))
    x = np.arange(len(labels))
    ax.bar(x, vals)
    ax.set_title("Baseline Population Composition")
    ax.set_ylabel("Percent")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=25, ha="right")
    ax.grid(False)
    _style_axes(ax)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


# Keep the historical private helper names available while sharing the canonical
# implementations with the flood-family generators.
from .plotting import (
    _apply_plot_theme,
    _style_axes,
    _pick,
    _plot_lines,
    _inject_active_hour_series,
    _plot_hour_of_day_profile,
    _plot_static_bars,
    prepare_generation,
    write_manifest,
)


def generate_baseline_graphs(run_dir: Path, scenario: str = "baseline", out_subdir: str = "baseline_graphs") -> Path:
    run_dir = Path(run_dir).resolve()
    scenario_key = str(scenario or "baseline").strip().lower()
    _, out_dir, df_all, df_q = prepare_generation(run_dir, scenario, out_subdir)
    title_prefix = {
        "baseline": "Baseline",
        "infectious_disease": "Infectious Disease",
        "flood_only": "Flood Only",
    }.get(scenario_key, scenario_key.replace("_", " ").title())
    file_stem = scenario_key or "baseline"

    if scenario_key == "infectious_disease":
        population_series = [
            ("dead_pct", "Deaths"),
            ("inf_prev_pct", "Active Infections"),
            ("in_healthcare_pct", "In Healthcare"),
        ]
    elif scenario_key == "compound":
        population_series = [
            ("dead_pct", "Deaths"),
            ("evacuated_pct", "Evacuated"),
            ("stranded_pct", "Stranded"),
            ("in_shelter_pct", "In Shelter"),
            ("in_healthcare_pct", "In Healthcare"),
            ("inf_prev_pct", "Active Infections"),
        ]
    else:
        population_series = [
            ("dead_pct", "Deaths"),
            ("evacuated_pct", "Evacuated"),
            ("stranded_pct", "Stranded"),
            ("in_shelter_pct", "In Shelter"),
            ("in_healthcare_pct", "In Healthcare"),
        ]

    # 1) Population and displacement states (combined)
    _plot_lines(
        df_q,
        population_series,
        f"{title_prefix} Population Stability",
        "Percent",
        out_dir / f"{file_stem}_01_population_stability.png",
    )

    # 2) Attendance and institutions
    attendance_series = [
        ("work_attendance_schoolday_mean", "Work Attendance (Work Hours)"),
        ("school_attendance_schoolday_mean", "School Attendance (School Hours)"),
    ]
    _plot_lines(
        df_q,
        attendance_series,
        f"{title_prefix} Attendance Dynamics",
        "Percent",
        out_dir / f"{file_stem}_03_attendance.png",
    )
    infra_out = out_dir / f"{file_stem}_04_infrastructure.png"
    if scenario_key != "infectious_disease":
        _plot_lines(
            df_q,
            [("biz_open_pct", "Businesses Open"), ("school_open_now_pct", "Schools Open"), ("house_hab_pct", "Habitable Houses")],
            f"{title_prefix} Infrastructure Availability",
            "Percent",
            infra_out,
        )
    elif infra_out.exists():
        infra_out.unlink()

    # 2b) Aggregated impact costs and affected population shares
    impact_series = [
        ("evacuation_expense_total", "Evacuation Expense"),
        ("house_repair_expense_total", "House Repair Expense"),
        ("business_repair_expense_total", "Business Repair Expense"),
        ("healthcare_expense_flood_total", "Healthcare Expense (Flood)"),
        ("healthcare_expense_mold_total", "Healthcare Expense (Mold)"),
        ("healthcare_expense_vectorborne_total", "Healthcare Expense (Vectorborne)"),
        ("healthcare_expense_infectious_total", "Healthcare Expense (Infectious)"),
    ]
    if scenario_key == "infectious_disease":
        impact_series = [("healthcare_expense_infectious_total", "Healthcare Expense (Infectious)")]
    _plot_lines(
        df_q,
        impact_series,
        f"{title_prefix} Cumulative Impact Expenses",
        "Currency Units",
        out_dir / f"{file_stem}_05a_impact_expenses.png",
    )
    affected_specs = [
        ("evacuated_pct", "Evacuated", "peak"),
        ("affected_stranded_unique_pct", "Stranded", "final"),
        ("affected_sheltered_unique_pct", "Sheltered", "final"),
        ("affected_healthcare_unique_pct", "Healthcare (ever)", "final"),
        ("affected_injured_unique_pct", "Injured", "final"),
        ("dead_pct", "Deaths", "final"),
        ("affected_mold_pct", "Affected by Mold", "final"),
        ("affected_vectorborne_pct", "Affected by Vectorborne", "final"),
        ("affected_infectious_pct", "Affected by Infectious", "final"),
    ]
    if scenario_key == "infectious_disease":
        affected_specs = [
            ("in_healthcare_pct", "In Healthcare", "peak"),
            ("dead_pct", "Deaths", "final"),
            ("inf_prev_pct", "Active Infectious", "peak"),
        ]
    elif scenario_key == "baseline":
        affected_specs = [
            ("dead_pct", "Deaths", "final"),
        ]
    _plot_endstate_bars(
        df_all,
        affected_specs,
        f"{title_prefix} End-of-Simulation Affected Population Statistics",
        out_dir / f"{file_stem}_05b_affected_population_pct.png",
    )
    # Population-based: % of total population who ever visited healthcare for each cause.
    healthcare_cause_specs = [
        ("affected_hc_flood_pct", "Flood", "final"),
        ("affected_hc_mold_pct", "Mold", "final"),
        ("affected_hc_vectorborne_pct", "Vectorborne", "final"),
        ("affected_hc_infectious_pct", "Infectious", "final"),
        ("affected_hc_compound_pct", "Compound (2+ causes)", "final"),
    ]
    if scenario_key == "infectious_disease":
        healthcare_cause_specs = [
            ("affected_hc_infectious_pct", "Infectious", "final"),
            ("affected_hc_compound_pct", "Compound (2+ causes)", "final"),
        ]
    healthcare_cause_out = out_dir / f"{file_stem}_05c_healthcare_by_cause_pct.png"
    if scenario_key == "baseline":
        if healthcare_cause_out.exists():
            healthcare_cause_out.unlink()
    else:
        _plot_endstate_bars(
            df_all,
            healthcare_cause_specs,
            f"{title_prefix} % of Population Ever Hospitalised by Cause",
            healthcare_cause_out,
        )

    # 3) Economics and quality of life
    finance_series = [
        ("biz_wealth_total", "Business Wealth"),
        ("gov_wealth", "Government Wealth"),
        ("shelter_wealth", "Shelter Wealth"),
        ("hc_wealth", "Healthcare Wealth"),
        ("person_wealth_total_scaled", "Person Wealth"),
    ]
    if scenario_key == "infectious_disease":
        finance_series = [
            ("gov_wealth", "Government Wealth"),
            ("hc_wealth", "Healthcare Wealth"),
            ("person_wealth_total_scaled", "Person Wealth"),
        ]
    _plot_lines(
        df_q,
        finance_series,
        f"{title_prefix} Institutional Wealth",
        "Currency Units",
        out_dir / f"{file_stem}_06_finance.png",
    )
    # Separate QoL plots by group
    _plot_lines(
        df_q,
        [("qol_children_pct", "QoL Children"), ("qol_adults_pct", "QoL Adults"), ("qol_seniors_pct", "QoL Seniors")],
        f"{title_prefix} Quality of Life by Age Group",
        "Percent",
        out_dir / f"{file_stem}_07b_qol_age.png",
    )
    _plot_lines(
        df_q,
        [
            ("qol_low_income_pct", "QoL Lower Class"),
            ("qol_middle_income_pct", "QoL Middle Class"),
            ("qol_upper_middle_pct", "QoL Upper-Middle Class"),
            ("qol_upper_pct", "QoL Upper Class"),
        ],
        f"{title_prefix} Quality of Life by Wealth Group",
        "Percent",
        out_dir / f"{file_stem}_07c_qol_wealth.png",
    )
    _plot_lines(
        df_q,
        [
            ("qol_white_pct", "QoL White"),
            ("qol_black_pct", "QoL Black"),
            ("qol_hispanic_pct", "QoL Hispanic"),
            ("qol_other_pct", "QoL Other"),
        ],
        f"{title_prefix} Quality of Life by Ethnicity",
        "Percent",
        out_dir / f"{file_stem}_07d_qol_ethnicity.png",
    )
    _plot_lines(
        df_q,
        [
            ("qol_hierarchist_pct", "QoL Hierarchist"),
            ("qol_egalitarian_pct", "QoL Egalitarian"),
            ("qol_individualist_pct", "QoL Individualist"),
            ("qol_fatalist_pct", "QoL Fatalist"),
        ],
        f"{title_prefix} Quality of Life by Worldview",
        "Percent",
        out_dir / f"{file_stem}_07e_qol_worldview.png",
    )

    # 4) Health and healthcare load (should be near-flat in baseline)
    disease_series = [("compound_burden_pct", "Compound Burden"), ("inf_prev_pct", "Infectious"), ("vector_symp_pct", "Vector"), ("mold_symp_pct", "Mold")]
    if scenario_key == "infectious_disease":
        disease_series = [("inf_prev_pct", "Infectious")]
    disease_out = out_dir / f"{file_stem}_08_disease_prevalence.png"
    if scenario_key == "baseline":
        if disease_out.exists():
            disease_out.unlink()
    else:
        _plot_lines(
            df_q,
            disease_series,
            f"{title_prefix} Disease Burden",
            "Percent",
            disease_out,
        )
    hc_service_series = [
        ("hc_util_pct", "Total Healthcare Utilization"),
        ("hc_backlog_pct", "Total Healthcare Backlog"),
    ]
    sh_service_series = [
        ("shelter_1_util_pct", "Shelter 1 Utilization"),
        ("shelter_1_backlog_pct", "Shelter 1 Backlog"),
        ("shelter_2_util_pct", "Shelter 2 Utilization"),
        ("shelter_2_backlog_pct", "Shelter 2 Backlog"),
    ]

    _plot_lines(
        df_q,
        hc_service_series,
        f"{title_prefix} Healthcare Service Load",
        "Percent",
        out_dir / f"{file_stem}_09a_healthcare_load.png",
    )

    if scenario_key != "infectious_disease":
        _plot_lines(
            df_q,
            sh_service_series,
            f"{title_prefix} Shelter Service Load",
            "Percent",
            out_dir / f"{file_stem}_09b_shelter_load.png",
        )

    # Clean up old combined chart if it exists
    old_service_chart = out_dir / f"{file_stem}_09_service_load.png"
    if old_service_chart.exists():
        old_service_chart.unlink()

    # 5) Social and decision traces
    _plot_lines(
        df_q,
        [("mean_threat", "Mean Threat"), ("mean_coping", "Mean Coping"), ("mean_self_efficacy", "Self Efficacy"), ("mean_response_efficacy", "Response Efficacy")],
        f"{title_prefix} Decision Psychology Signals",
        "Index",
        out_dir / f"{file_stem}_10_psychology.png",
    )
    # 6) Static composition snapshot
    _plot_static_bars(df_all, out_dir / f"{file_stem}_14_population_composition.png")
    _plot_hour_of_day_profile(
        df_all,
        out_dir / f"{file_stem}_16_routine_profile_by_hour.png",
        title=f"{title_prefix} Routine Profile by Hour of Day",
    )

    # Remove retired outputs so reruns do not keep stale files in the manifest.
    for retired in [
        "baseline_02_displacement_states.png",
        "baseline_05_income.png",
        "baseline_05a_income_age_gender.png",
        "baseline_05b_income_groups.png",
        "baseline_02b_displacement_counts.png",
        "baseline_07a_qol_mean.png",
        "baseline_12_rep_band_work_attendance.png",
        "baseline_13_rep_band_qol.png",
        "baseline_15_rep_band_work_attendance_workhours.png",
        "baseline_17_phase_decision_sanity.png",
        "baseline_11_decision_actions.png",
    ]:
        retired_path = out_dir / retired
        if retired_path.exists():
            retired_path.unlink()

    if file_stem != "baseline":
        for stale in out_dir.glob("baseline_*.png"):
            try:
                stale.unlink()
            except OSError:
                pass
        stale_manifest = out_dir / "baseline_graph_manifest.txt"
        if stale_manifest.exists():
            stale_manifest.unlink()

    # Summary manifest
    manifest = write_manifest(out_dir, f"{file_stem}_graph_manifest.txt")

    files = list(out_dir.glob("*.png"))
    print(f"Saved {len(files)} {file_stem} graphs to {out_dir}")
    return out_dir


def main() -> None:
    args = parse_args()
    generate_baseline_graphs(args.run_dir, args.scenario, args.out_subdir)


if __name__ == "__main__":
    main()
