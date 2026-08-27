from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


SCENARIOS: List[str] = [
    "baseline",
    "infectious_only",
    "flood_only",
    "flood_plus_flood_disease",
    "full_compound",
]

LABELS: Dict[str, str] = {
    "baseline": "Baseline",
    "infectious_only": "Infectious Only",
    "flood_only": "Flood Only",
    "flood_plus_flood_disease": "Flood + Flood Disease",
    "full_compound": "Full Compound",
}

COLORS: Dict[str, str] = {
    "baseline": "#4e79a7",
    "infectious_only": "#f28e2b",
    "flood_only": "#59a14f",
    "flood_plus_flood_disease": "#e15759",
    "full_compound": "#b07aa1",
}

PHASES: List[Tuple[str, int, int, str]] = [
    ("baseline", 0, 14 * 24, "#cccccc"),
    ("pre_flood", 14 * 24, 24 * 24, "#bde0fe"),
    ("flood", 24 * 24, 31 * 24, "#ffd6a5"),
    ("post_flood", 31 * 24, 52 * 24, "#cdeac0"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate comprehensive diagnostics figures.")
    parser.add_argument(
        "--run-dir",
        default="dataCollection/scenario_runs_hpc_1500",
        help="Run directory with scenario outputs and aggregated csv files.",
    )
    parser.add_argument(
        "--out-subdir",
        default="diagnostics",
        help="Subfolder inside run-dir to store generated figures.",
    )
    return parser.parse_args()


def add_phase_bands(ax: plt.Axes, xmax: float) -> None:
    for _, x0, x1, color in PHASES:
        if x0 > xmax:
            break
        ax.axvspan(x0, min(x1, xmax), color=color, alpha=0.16)


def set_day_axis(ax: plt.Axes, max_h: float) -> None:
    max_day = int(max_h // 24)
    ticks = list(range(0, max_day + 1, 7))
    ax.set_xticks([t * 24 for t in ticks])
    ax.set_xticklabels([str(t) for t in ticks])
    ax.set_xlabel("Day")


def col(df: pd.DataFrame, base: str, agg: str = "median") -> str | None:
    name = f"{base}_{agg}"
    return name if name in df.columns else None


def safe_plot_series(
    ax: plt.Axes,
    df: pd.DataFrame,
    base: str,
    scenario: str,
    with_iqr: bool = True,
) -> bool:
    c_med = col(df, base, "median")
    c_q25 = col(df, base, "q25")
    c_q75 = col(df, base, "q75")
    if c_med is None:
        return False

    x = df["hours"]
    ax.plot(x, df[c_med], color=COLORS[scenario], linewidth=2, label=LABELS[scenario])
    if with_iqr and c_q25 is not None and c_q75 is not None:
        ax.fill_between(x, df[c_q25], df[c_q75], color=COLORS[scenario], alpha=0.15)
    return True


def save(fig: plt.Figure, out_dir: Path, name: str) -> None:
    path = out_dir / f"{name}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def load_data(base_dir: Path):
    quant = {}
    byrep_frames = []
    agg_frames = []
    for sc in SCENARIOS:
        sc_dir = base_dir / sc

        quant_fp = sc_dir / "timeseries_quantiles.csv"
        if quant_fp.exists():
            quant[sc] = pd.read_csv(quant_fp)

        byrep_fp = sc_dir / "summary_by_replication.csv"
        if byrep_fp.exists():
            df = pd.read_csv(byrep_fp)
            if "batch_scenario" not in df.columns:
                df["batch_scenario"] = sc
            byrep_frames.append(df)

        agg_fp = sc_dir / "summary_stats.csv"
        if agg_fp.exists():
            df = pd.read_csv(agg_fp)
            if "scenario" not in df.columns:
                df["scenario"] = sc
            agg_frames.append(df)

    byrep = pd.concat(byrep_frames, ignore_index=True) if byrep_frames else pd.DataFrame()
    agg = pd.concat(agg_frames, ignore_index=True) if agg_frames else pd.DataFrame()
    if "scenario" in agg.columns and not agg.empty:
        agg = agg.set_index("scenario")
    return quant, agg, byrep


def fig_state_accounting(quant: Dict[str, pd.DataFrame], out_dir: Path) -> None:
    sc = "full_compound"
    if sc not in quant:
        return
    df = quant[sc]

    fig, axes = plt.subplots(2, 2, figsize=(14, 9), sharex=True)
    metrics = [
        ("alive_pct", "Alive (%)"),
        ("dead_pct", "Deaths (%)"),
        ("evacuated_pct", "Evacuated (%)"),
        ("stranded_pct", "Stranded (%)"),
    ]

    for ax, (m, title) in zip(axes.ravel(), metrics):
        ok = safe_plot_series(ax, df, m, sc, with_iqr=True)
        if ok:
            add_phase_bands(ax, float(df["hours"].max()))
            ax.set_title(title)
            ax.grid(alpha=0.3)
            set_day_axis(ax, float(df["hours"].max()))

    fig.suptitle("State Accounting - Full Compound", fontsize=14)
    save(fig, out_dir, "diag_01_state_accounting")


def fig_decision_dynamics(quant: Dict[str, pd.DataFrame], out_dir: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(14, 9), sharex=True)
    metrics = [
        ("decision_evac_pct", "Evacuate Decision (%)"),
        ("decision_prepare_pct", "Prepare Home Decision (%)"),
        ("decision_delay_return_pct", "Delay Return Decision (%)"),
        ("decision_shelter_in_place_pct", "Shelter In Place Decision (%)"),
    ]
    for ax, (m, title) in zip(axes.ravel(), metrics):
        for sc in SCENARIOS:
            if sc not in quant:
                continue
            safe_plot_series(ax, quant[sc], m, sc, with_iqr=True)
        if len(ax.lines) > 0:
            add_phase_bands(ax, float(quant[SCENARIOS[0]]["hours"].max()))
            ax.set_title(title)
            ax.grid(alpha=0.3)
            set_day_axis(ax, float(quant[SCENARIOS[0]]["hours"].max()))
    axes[0, 0].legend(loc="upper left", fontsize=8)
    fig.suptitle("Decision Dynamics Across Scenarios", fontsize=14)
    save(fig, out_dir, "diag_02_decision_dynamics")


def fig_trust_and_decisions(quant: Dict[str, pd.DataFrame], out_dir: Path) -> None:
    sc = "full_compound"
    if sc not in quant:
        return
    df = quant[sc]

    fig, ax = plt.subplots(figsize=(13, 5))
    add_phase_bands(ax, float(df["hours"].max()))

    pairs = [
        ("evac_high_trust_pct", "Evac High Trust", "#1f77b4"),
        ("evac_low_trust_pct", "Evac Low Trust", "#d62728"),
        ("evac_fatalist_pct", "Evac Fatalist", "#9467bd"),
        ("evac_individualist_pct", "Evac Individualist", "#2ca02c"),
    ]
    for base, label, color in pairs:
        c_med = col(df, base, "median")
        if c_med is None:
            continue
        ax.plot(df["hours"], df[c_med], label=label, color=color, linewidth=2)

    ax.set_title("Evacuation Decisions by Trust and Worldview - Full Compound")
    ax.set_ylabel("% of subgroup deciding Evacuate")
    ax.grid(alpha=0.3)
    set_day_axis(ax, float(df["hours"].max()))
    ax.legend(fontsize=9)
    save(fig, out_dir, "diag_03_trust_worldview_evac")


def fig_queue_and_capacity(quant: Dict[str, pd.DataFrame], out_dir: Path) -> None:
    sc = "full_compound"
    if sc not in quant:
        return
    df = quant[sc]

    fig, axes = plt.subplots(2, 2, figsize=(14, 9), sharex=True)
    plots = [
        ("shelter_util_pct", "Shelter Utilization (%)", axes[0, 0]),
        ("shelter_backlog_pct", "Shelter Backlog (%)", axes[0, 1]),
        ("hc_util_pct", "Healthcare Utilization (%)", axes[1, 0]),
        ("hc_backlog_pct", "Healthcare Backlog (%)", axes[1, 1]),
    ]

    for base, title, ax in plots:
        if safe_plot_series(ax, df, base, sc, with_iqr=True):
            add_phase_bands(ax, float(df["hours"].max()))
            ax.set_title(title)
            ax.grid(alpha=0.3)
            set_day_axis(ax, float(df["hours"].max()))

    fig.suptitle("Service Capacity and Queue Stress - Full Compound", fontsize=14)
    save(fig, out_dir, "diag_04_service_capacity_queue")


def fig_displacement_consistency(quant: Dict[str, pd.DataFrame], out_dir: Path) -> None:
    sc = "full_compound"
    if sc not in quant:
        return
    df = quant[sc]

    fig, ax = plt.subplots(figsize=(13, 5))
    add_phase_bands(ax, float(df["hours"].max()))

    for base, label, color in [
        ("stranded_pct", "Stranded %", "#d62728"),
        ("evacuated_pct", "Evacuated %", "#1f77b4"),
        ("in_shelter_pct", "In Shelter %", "#2ca02c"),
    ]:
        c_med = col(df, base, "median")
        if c_med is None:
            continue
        ax.plot(df["hours"], df[c_med], label=label, color=color, linewidth=2)

    # Plot overlap proxy: stranded + evacuated
    c_s = col(df, "stranded_pct", "median")
    c_e = col(df, "evacuated_pct", "median")
    if c_s and c_e:
        ax.plot(df["hours"], df[c_s] + df[c_e], label="Stranded + Evacuated", color="black", linestyle="--", linewidth=1.8)

    ax.set_title("Displacement Consistency Check - Full Compound")
    ax.set_ylabel("Population (%)")
    ax.grid(alpha=0.3)
    set_day_axis(ax, float(df["hours"].max()))
    ax.legend(fontsize=9)
    save(fig, out_dir, "diag_05_displacement_consistency")


def fig_disease_prevalence(quant: Dict[str, pd.DataFrame], out_dir: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(14, 9), sharex=True)
    metrics = [
        ("compound_burden_pct", "Compound Burden (%)"),
        ("inf_prev_pct", "Infectious Prevalence (%)"),
        ("mold_symp_pct", "Mold Symptoms (%)"),
    ]

    for ax, (m, title) in zip(axes.ravel(), metrics):
        for sc in SCENARIOS:
            if sc not in quant:
                continue
            safe_plot_series(ax, quant[sc], m, sc, with_iqr=True)
        if len(ax.lines) > 0:
            add_phase_bands(ax, float(quant[SCENARIOS[0]]["hours"].max()))
            ax.set_title(title)
            ax.grid(alpha=0.3)
            set_day_axis(ax, float(quant[SCENARIOS[0]]["hours"].max()))
    axes[0, 0].legend(fontsize=8, loc="upper left")
    fig.suptitle("Disease Prevalence Dynamics", fontsize=14)
    save(fig, out_dir, "diag_06_disease_prevalence")


def fig_disease_incidence(quant: Dict[str, pd.DataFrame], out_dir: Path) -> None:
    sc = "full_compound"
    if sc not in quant:
        return
    df = quant[sc]
    fig, ax = plt.subplots(figsize=(13, 5))
    add_phase_bands(ax, float(df["hours"].max()))

    for base, label, color in [
        ("vector_incidence_hr", "Vector Incidence/hr", "#bcbd22"),
        ("mold_incidence_hr", "Mold Incidence/hr", "#9467bd"),
    ]:
        c_med = col(df, base, "median")
        if c_med is None:
            continue
        ax.plot(df["hours"], df[c_med], label=label, color=color, linewidth=2)

    ax.set_title("Disease Incidence Rates - Full Compound")
    ax.set_ylabel("New cases per hour")
    ax.grid(alpha=0.3)
    set_day_axis(ax, float(df["hours"].max()))
    ax.legend()
    save(fig, out_dir, "diag_07_disease_incidence")


def fig_hazard_coupling(quant: Dict[str, pd.DataFrame], out_dir: Path) -> None:
    sc = "full_compound"
    if sc not in quant:
        return
    df = quant[sc]
    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharex=True)

    # Hazard and displacement
    ax = axes[0]
    add_phase_bands(ax, float(df["hours"].max()))
    for base, label, color in [
        ("hazard_max_depth_m", "Max Flood Depth (m)", "#1f77b4"),
        ("house_damp_active_pct", "Houses Damp Active (%)", "#2ca02c"),
        ("near_vectorborne_pct", "Near Vectorborne (%)", "#ff7f0e"),
    ]:
        c_med = col(df, base, "median")
        if c_med:
            ax.plot(df["hours"], df[c_med], label=label, color=color, linewidth=2)
    ax.set_title("Hazard and Environmental Exposure")
    ax.grid(alpha=0.3)
    set_day_axis(ax, float(df["hours"].max()))
    ax.legend(fontsize=8)

    # Coupled disease
    ax = axes[1]
    add_phase_bands(ax, float(df["hours"].max()))
    for base, label, color in [
        ("vector_symp_pct", "Vector %", "#bcbd22"),
        ("mold_symp_pct", "Mold %", "#9467bd"),
    ]:
        c_med = col(df, base, "median")
        if c_med:
            ax.plot(df["hours"], df[c_med], label=label, color=color, linewidth=2)
    ax.set_title("Disease Pathways")
    ax.grid(alpha=0.3)
    set_day_axis(ax, float(df["hours"].max()))
    ax.legend(fontsize=8)

    fig.suptitle("Hazard to Disease Coupling - Full Compound", fontsize=14)
    save(fig, out_dir, "diag_08_hazard_disease_coupling")


def fig_subgroup_disease(quant: Dict[str, pd.DataFrame], out_dir: Path) -> None:
    sc = "full_compound"
    if sc not in quant:
        return
    df = quant[sc]
    fig, ax = plt.subplots(figsize=(13, 5))
    add_phase_bands(ax, float(df["hours"].max()))

    for base, label, color in [
        ("children_disease_pct", "Children Disease %", "#1f77b4"),
        ("seniors_disease_pct", "Seniors Disease %", "#ff7f0e"),
        ("low_income_disease_pct", "Low Income Disease %", "#d62728"),
        ("high_income_disease_pct", "High Income Disease %", "#2ca02c"),
        ("high_vuln_disease_pct", "High Vulnerability Disease %", "#9467bd"),
    ]:
        c_med = col(df, base, "median")
        if c_med:
            ax.plot(df["hours"], df[c_med], label=label, color=color, linewidth=2)

    ax.set_title("Disease Burden by Subgroup - Full Compound")
    ax.set_ylabel("% symptomatic")
    ax.grid(alpha=0.3)
    set_day_axis(ax, float(df["hours"].max()))
    ax.legend(fontsize=8)
    save(fig, out_dir, "diag_09_subgroup_disease")


def fig_economy_core(quant: Dict[str, pd.DataFrame], out_dir: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(14, 9), sharex=True)
    plots = [
        ("biz_open_pct", "Businesses Open (%)"),
        ("biz_flooded_pct", "Businesses Currently Flooded (%)"),
        ("biz_ever_flooded_pct", "Businesses Ever Flooded (%)"),
        ("work_attendance_pct", "Work Attendance (%)"),
        ("biz_staffed_pct", "Businesses Staffed (%)"),
    ]

    for ax, (base, title) in zip(axes.ravel(), plots):
        for sc in ["flood_only", "flood_plus_flood_disease", "full_compound"]:
            if sc not in quant:
                continue
            safe_plot_series(ax, quant[sc], base, sc, with_iqr=True)
        if len(ax.lines) > 0:
            add_phase_bands(ax, float(quant["full_compound"]["hours"].max()))
            ax.set_title(title)
            ax.grid(alpha=0.3)
            set_day_axis(ax, float(quant["full_compound"]["hours"].max()))
    axes[0, 0].legend(fontsize=8)
    fig.suptitle("Business and Workforce Mechanics", fontsize=14)
    save(fig, out_dir, "diag_10_business_workforce")


def fig_economic_ratios(quant: Dict[str, pd.DataFrame], out_dir: Path) -> None:
    sc = "full_compound"
    if sc not in quant:
        return
    df = quant[sc]

    fig, ax = plt.subplots(figsize=(13, 5))
    add_phase_bands(ax, float(df["hours"].max()))
    for base, label, color in [
        ("biz_sales_vs_gdp_pct", "Sales/GDP (%)", "#1f77b4"),
        ("biz_netrev_vs_gdp_pct", "NetRev/GDP (%)", "#2ca02c"),
        ("biz_wages_vs_gdp_pct", "Wages/GDP (%)", "#d62728"),
        ("person_income_index_pct", "Income Index (%)", "#9467bd"),
    ]:
        c_med = col(df, base, "median")
        if c_med:
            ax.plot(df["hours"], df[c_med], label=label, color=color, linewidth=2)

    ax.set_title("Economic Ratios Over Time - Full Compound")
    ax.set_ylabel("Percent")
    ax.grid(alpha=0.3)
    set_day_axis(ax, float(df["hours"].max()))
    ax.legend()
    save(fig, out_dir, "diag_11_economic_ratios")


def fig_school_recovery(quant: Dict[str, pd.DataFrame], out_dir: Path) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(16, 5), sharex=True)
    metrics = [
        ("school_open_now_pct", "Schools Open (%)"),
        ("attendance_rate_pct", "Attendance Rate (%)"),
        ("normal_activity_pct", "Normal Activity (%)"),
    ]

    for ax, (base, title) in zip(axes, metrics):
        for sc in ["baseline", "flood_only", "full_compound"]:
            if sc not in quant:
                continue
            safe_plot_series(ax, quant[sc], base, sc, with_iqr=True)
        if len(ax.lines) > 0:
            add_phase_bands(ax, float(quant["full_compound"]["hours"].max()))
            ax.set_title(title)
            ax.grid(alpha=0.3)
            set_day_axis(ax, float(quant["full_compound"]["hours"].max()))
    axes[0].legend(fontsize=8)
    fig.suptitle("School and Activity Recovery", fontsize=14)
    save(fig, out_dir, "diag_12_school_activity_recovery")


def fig_qol_deep(quant: Dict[str, pd.DataFrame], out_dir: Path) -> None:
    sc = "full_compound"
    if sc not in quant:
        return
    df = quant[sc]

    fig, ax = plt.subplots(figsize=(13, 5))
    add_phase_bands(ax, float(df["hours"].max()))
    groups = [
        ("qol_mean_pct", "QoL Overall", "black"),
        ("qol_children_pct", "QoL Children", "#1f77b4"),
        ("qol_seniors_pct", "QoL Seniors", "#ff7f0e"),
        ("qol_low_income_pct", "QoL Low Income", "#d62728"),
        ("qol_high_income_pct", "QoL High Income", "#2ca02c"),
        ("qol_other_pct", "QoL Other", "#9467bd"),
    ]
    for base, label, color in groups:
        c_med = col(df, base, "median")
        if c_med:
            ax.plot(df["hours"], df[c_med], label=label, color=color, linewidth=2)
    ax.set_title("Quality of Life by Group - Full Compound")
    ax.set_ylabel("QoL (%)")
    ax.set_ylim(0, 105)
    ax.grid(alpha=0.3)
    set_day_axis(ax, float(df["hours"].max()))
    ax.legend(fontsize=8)
    save(fig, out_dir, "diag_13_qol_groups")


def fig_inequity_and_gap(quant: Dict[str, pd.DataFrame], out_dir: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharex=True)

    for sc in ["baseline", "flood_only", "flood_plus_flood_disease", "full_compound"]:
        if sc not in quant:
            continue
        safe_plot_series(axes[0], quant[sc], "inequity_gap_low_vs_high_pct", sc, with_iqr=True)
        safe_plot_series(axes[1], quant[sc], "low_income_disease_pct", sc, with_iqr=False)
        c_hi = col(quant[sc], "high_income_disease_pct", "median")
        if c_hi:
            axes[1].plot(
                quant[sc]["hours"],
                quant[sc][c_hi],
                color=COLORS[sc],
                linestyle="--",
                linewidth=1.5,
                alpha=0.8,
            )

    for ax in axes:
        if len(ax.lines) > 0:
            add_phase_bands(ax, float(quant["full_compound"]["hours"].max()))
            set_day_axis(ax, float(quant["full_compound"]["hours"].max()))
            ax.grid(alpha=0.3)

    axes[0].set_title("Inequity Gap Over Time")
    axes[0].set_ylabel("Low-Income minus High-Income Disease (%)")
    axes[1].set_title("Income Group Disease Curves")
    axes[1].set_ylabel("Disease (%)")
    axes[0].legend(fontsize=8)

    fig.suptitle("Inequity Diagnostics", fontsize=14)
    save(fig, out_dir, "diag_14_inequity_diagnostics")


def fig_replication_distributions(byrep: pd.DataFrame, out_dir: Path) -> None:
    if byrep.empty or "batch_scenario" not in byrep.columns:
        return

    cols = [
        "peaks_compound_burden_pct_value",
        "peaks_stranded_pct_value",
        "peaks_shelter_util_pct_value",
        "peaks_hc_util_pct_value",
        "end_state_dead_pct",
        "end_state_inequity_gap_low_vs_high_pct",
        "end_state_biz_sales_vs_gdp_pct",
    ]
    cols = [c for c in cols if c in byrep.columns]
    if not cols:
        return

    n = len(cols)
    fig, axes = plt.subplots(1, n, figsize=(4 * n, 5))
    if n == 1:
        axes = [axes]

    scenarios = [s for s in SCENARIOS if s in set(byrep["batch_scenario"].dropna())]
    if not scenarios:
        scenarios = sorted(byrep["batch_scenario"].dropna().unique())

    for ax, c in zip(axes, cols):
        data = [byrep.loc[byrep["batch_scenario"] == s, c].dropna().values for s in scenarios]
        vp = ax.violinplot(data, showmedians=True, showextrema=True)
        for i, body in enumerate(vp["bodies"]):
            body.set_facecolor(COLORS.get(scenarios[i], "#999999"))
            body.set_alpha(0.6)
        ax.set_xticks(np.arange(1, len(scenarios) + 1))
        ax.set_xticklabels([LABELS.get(s, s) for s in scenarios], rotation=20, ha="right", fontsize=8)
        ax.set_title(c)
        ax.grid(axis="y", alpha=0.3)

    fig.suptitle("Replication Outcome Distributions", fontsize=14)
    save(fig, out_dir, "diag_15_replication_distributions")


def fig_replication_correlation(byrep: pd.DataFrame, out_dir: Path) -> None:
    if byrep.empty:
        return

    cols = [
        "peaks_compound_burden_pct_value",
        "peaks_stranded_pct_value",
        "peaks_shelter_util_pct_value",
        "peaks_hc_util_pct_value",
        "totals_sick_hours_total_sum",
        "end_state_dead_pct",
        "end_state_biz_sales_vs_gdp_pct",
        "end_state_inequity_gap_low_vs_high_pct",
    ]
    cols = [c for c in cols if c in byrep.columns]
    if len(cols) < 3:
        return

    corr = byrep[cols].corr(numeric_only=True)

    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(corr.values, vmin=-1, vmax=1, cmap="coolwarm")
    ax.set_xticks(np.arange(len(cols)))
    ax.set_yticks(np.arange(len(cols)))
    ax.set_xticklabels(cols, rotation=60, ha="right", fontsize=8)
    ax.set_yticklabels(cols, fontsize=8)
    ax.set_title("Replication Outcome Correlation Matrix")
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    save(fig, out_dir, "diag_16_replication_correlation")


def phase_summary_table(quant: Dict[str, pd.DataFrame], out_dir: Path) -> None:
    rows = []
    metrics = [
        "decision_evac_pct_median",
        "decision_prepare_pct_median",
        "stranded_pct_median",
        "evacuated_pct_median",
        "in_shelter_pct_median",
        "compound_burden_pct_median",
        "biz_open_pct_median",
        "work_attendance_pct_median",
        "attendance_rate_pct_median",
        "qol_mean_pct_median",
    ]

    for sc, df in quant.items():
        max_h = int(df["hours"].max())
        for pname, x0, x1, _ in PHASES:
            if x0 > max_h:
                continue
            sl = df[(df["hours"] >= x0) & (df["hours"] < x1)]
            if sl.empty:
                continue
            row = {"scenario": sc, "phase": pname}
            for m in metrics:
                if m in sl.columns:
                    row[m] = float(sl[m].mean())
            rows.append(row)

    if not rows:
        return

    out = pd.DataFrame(rows)
    out.to_csv(out_dir / "diag_phase_summary.csv", index=False)


def recovery_summary(quant: Dict[str, pd.DataFrame], out_dir: Path) -> None:
    rows = []
    for sc, df in quant.items():
        c_biz = col(df, "biz_open_pct", "median")
        c_work = col(df, "work_attendance_pct", "median")
        c_dis = col(df, "compound_burden_pct", "median")
        if not c_biz or not c_work or not c_dis:
            continue

        flood_peak_window = df[(df["hours"] >= 24 * 24) & (df["hours"] <= 31 * 24)]
        post_tail = df[(df["hours"] >= 45 * 24)]
        if flood_peak_window.empty or post_tail.empty:
            continue

        row = {
            "scenario": sc,
            "peak_compound_in_flood": float(flood_peak_window[c_dis].max()),
            "late_post_compound": float(post_tail[c_dis].mean()),
            "peak_biz_open_loss": float(100.0 - flood_peak_window[c_biz].min()),
            "late_post_biz_open": float(post_tail[c_biz].mean()),
            "late_post_work_attendance": float(post_tail[c_work].mean()),
        }
        rows.append(row)

    if rows:
        pd.DataFrame(rows).to_csv(out_dir / "diag_recovery_summary.csv", index=False)


def manifest(out_dir: Path) -> None:
    files = sorted(p.name for p in out_dir.glob("diag_*.png"))
    pd.DataFrame({"figure": files}).to_csv(out_dir / "diag_manifest.csv", index=False)


def main() -> None:
    args = parse_args()
    base_dir = Path(args.run_dir).resolve()
    out_dir = base_dir / args.out_subdir
    out_dir.mkdir(parents=True, exist_ok=True)

    quant, agg, byrep = load_data(base_dir)
    _ = agg  # kept for future expansions and compatibility

    # Plot suite
    fig_state_accounting(quant, out_dir)
    fig_decision_dynamics(quant, out_dir)
    fig_trust_and_decisions(quant, out_dir)
    fig_queue_and_capacity(quant, out_dir)
    fig_displacement_consistency(quant, out_dir)
    fig_disease_prevalence(quant, out_dir)
    fig_disease_incidence(quant, out_dir)
    fig_hazard_coupling(quant, out_dir)
    fig_subgroup_disease(quant, out_dir)
    fig_economy_core(quant, out_dir)
    fig_economic_ratios(quant, out_dir)
    fig_school_recovery(quant, out_dir)
    fig_qol_deep(quant, out_dir)
    fig_inequity_and_gap(quant, out_dir)
    fig_replication_distributions(byrep, out_dir)
    fig_replication_correlation(byrep, out_dir)

    # Tabular diagnostics
    phase_summary_table(quant, out_dir)
    recovery_summary(quant, out_dir)
    manifest(out_dir)

    print(f"Diagnostics written to: {out_dir}")


if __name__ == "__main__":
    main()
