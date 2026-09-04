from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import MultipleLocator

HERE = Path(__file__).resolve().parent
ANALYSIS_DIR = HERE.parent
if str(ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(ANALYSIS_DIR))

from graph_generation.plotting import _pick


SERIES = {
    "population_stability": [("dead_pct", "Deaths"), ("evacuated_pct", "Evacuated"), ("stranded_pct", "Stranded"), ("in_shelter_pct", "In Shelter"), ("in_healthcare_pct", "In Healthcare")],
    "psychology": [("mean_threat", "Average threat"), ("mean_coping", "Average coping"), ("mean_self_efficacy", "Average self-efficacy"), ("mean_response_efficacy", "Average response efficacy")],
    "shelter_load": [("shelter_1_util_pct", "Shelter 1 utilization"), ("shelter_1_backlog_pct", "Shelter 1 backlog"), ("shelter_2_util_pct", "Shelter 2 utilization"), ("shelter_2_backlog_pct", "Shelter 2 backlog")],
    "healthcare_load": [("hc_util_pct", "Total utilization"), ("hc_backlog_pct", "Total backlog"), ("hc_util_flood_pct", "Flood utilization"), ("hc_util_mold_pct", "Mold utilization"), ("hc_util_vector_pct", "Vectorborne utilization"), ("hc_util_infectious_pct", "Infectious utilization")],
    "impact_expenses": [("evacuation_expense_total", "Evacuation"), ("house_repair_expense_total", "House repair"), ("business_repair_expense_total", "Business repair"), ("healthcare_expense_flood_total", "Healthcare: flood"), ("healthcare_expense_mold_total", "Healthcare: mold"), ("healthcare_expense_vectorborne_total", "Healthcare: vectorborne"), ("healthcare_expense_infectious_total", "Healthcare: infectious")],
    "finance": [("biz_wealth_total", "Business"), ("gov_wealth", "Government"), ("shelter_wealth", "Shelter"), ("hc_wealth", "Healthcare"), ("person_wealth_total_scaled", "Person")],
    "qol_age": [("qol_children_pct", "Children (0-14)"), ("qol_adults_pct", "Adults (15-64)"), ("qol_seniors_pct", "Seniors (65+)")],
    "qol_ethnicity": [("qol_white_pct", "White"), ("qol_black_pct", "Black"), ("qol_hispanic_pct", "Hispanic"), ("qol_other_pct", "Other")],
    "qol_wealth": [("qol_low_income_pct", "Lower Income"), ("qol_middle_income_pct", "Middle Income"), ("qol_upper_middle_pct", "Upper-Middle Income"), ("qol_upper_pct", "Upper Income")],
    "qol_worldview": [("qol_hierarchist_pct", "Hierarchist"), ("qol_egalitarian_pct", "Egalitarian"), ("qol_individualist_pct", "Individualist"), ("qol_fatalist_pct", "Fatalist")],
}

FIGURES: dict[str, dict[str, Any]] = {
    "baseline_population_composition": {"scenario": "baseline", "kind": "composition", "filename": "01_baseline_population_composition", "title": "Population Composition", "xlabel": "", "ylabel": "Percentage of Population"},
    "baseline_routine_profile_by_hour": {"scenario": "baseline", "kind": "routine", "filename": "02_baseline_routine_profile_by_hour", "title": "Routine Profile by Hour - Baseline Scenario", "xlabel": "Hour of day", "ylabel": "Participation Rate (%)"},
    "compound_routine_profile_by_hour": {"scenario": "full_compound", "kind": "routine", "filename": "03_compound_routine_profile_by_hour", "title": "Routine Profile by Hour - Compound Scenario", "xlabel": "Hour of day", "ylabel": "Participation Rate (%)"},
    "baseline_psychology": {"scenario": "baseline", "kind": "lines", "series": SERIES["psychology"], "statistic": "mean", "filename": "04_baseline_psychology", "title": "Decision Psychology - Baseline Scenario", "xlabel": "Day", "ylabel": "Index"},
    "compound_psychology": {"scenario": "full_compound", "kind": "lines", "series": SERIES["psychology"], "statistic": "mean", "filename": "05_compound_psychology", "title": "Decision Psychology - Compound Scenario", "xlabel": "Day", "ylabel": "Index"},
    "flood_population_stability": {"scenario": "flood_only", "kind": "lines", "series": SERIES["population_stability"], "filename": "06_flood_population_stability", "title": "Population Stability - Flood Only Scenario", "xlabel": "Day", "ylabel": "Percentage of population"},
    "flood_mold_population_stability": {"scenario": "flood_mold", "source": "flood_mold/flood_mold_5000x30", "kind": "lines", "series": SERIES["population_stability"], "filename": "07_flood_mold_population_stability", "title": "Population Stability - Flood and Mold Scenario", "xlabel": "Day", "ylabel": "Percentage of population"},
    "infectious_population_stability": {"scenario": "infectious_disease", "kind": "lines", "series": [("dead_pct", "Deaths"), ("inf_prev_pct", "Active infections"), ("in_healthcare_pct", "In Healthcare")], "filename": "08_infectious_population_stability", "title": "Population Stability - Infectious Disease Scenario", "xlabel": "Day", "ylabel": "Percentage of population"},
    "compound_population_stability": {"scenario": "full_compound", "kind": "lines", "series": SERIES["population_stability"], "filename": "09_compound_population_stability", "title": "Population Stability - Compound Scenario", "xlabel": "Day", "ylabel": "Percentage of population"},
    "compound_structural_impact": {"scenario": "full_compound", "kind": "structural", "filename": "10_compound_structural_impact", "title": "Structural Impact - Compound Scenario", "xlabel": "Day", "ylabel": "Percentage of entities"},
    "compound_shelter_load": {"scenario": "full_compound", "kind": "lines", "series": SERIES["shelter_load"], "filename": "11_compound_shelter_load", "title": "Shelter Load - Compound Scenario", "xlabel": "Day", "ylabel": "Percentage of Capacity"},
    "compound_healthcare_load": {"scenario": "full_compound", "kind": "lines", "series": SERIES["healthcare_load"], "filename": "12_compound_healthcare_load", "title": "Healthcare Load - Compound Scenario", "xlabel": "Day", "ylabel": "Percentage of Capacity"},
    "compound_affected_populations": {"scenario": "full_compound", "kind": "bars", "filename": "13_compound_affected_populations", "title": "Affected Populations - Compound Scenario", "xlabel": "Population outcome", "ylabel": "Percent of population", "metrics": [("evacuated_pct", "Evacuated", "peak"), ("affected_injured_unique_pct", "Injured", "final"), ("affected_sheltered_unique_pct", "Sheltered", "final"), ("affected_healthcare_unique_pct", "Healthcare", "final"), ("affected_mold_pct", "Mold", "final"), ("affected_vectorborne_pct", "Vectorborne", "final"), ("affected_infectious_pct", "Infectious", "final"), ("dead_pct", "Deaths", "final")]},
    "compound_impact_expenses": {"scenario": "full_compound", "kind": "lines", "series": SERIES["impact_expenses"], "filename": "14_compound_impact_expenses", "title": "Cumulative Expenses - Compound Scenario", "xlabel": "Day", "ylabel": "Population Cumulative Expenditure"},
    "compound_finance": {"scenario": "full_compound", "kind": "lines", "series": SERIES["finance"], "filename": "15_compound_finance", "title": "Agent Wealth Over Time - Compound Scenario", "xlabel": "Day", "ylabel": "Agent Wealth"},
    "compound_qol_age": {"scenario": "full_compound", "kind": "lines", "series": SERIES["qol_age"], "filename": "16_compound_qol_age", "title": "Quality of Life by Age - Compound Scenario", "xlabel": "Day", "ylabel": "Mean Quality of Life Score"},
    "compound_qol_ethnicity": {"scenario": "full_compound", "kind": "lines", "series": SERIES["qol_ethnicity"], "colors": ["#0072B2", "#D55E00", "#CC79A7", "#7B3294"], "filename": "17_compound_qol_ethnicity", "title": "Quality of Life by Ethnicity - Compound Scenario", "xlabel": "Day", "ylabel": "Mean Quality of Life Score"},
    "compound_qol_wealth": {"scenario": "full_compound", "kind": "lines", "series": SERIES["qol_wealth"], "filename": "18_compound_qol_wealth", "title": "Quality of Life by Wealth - Compound Scenario", "xlabel": "Day", "ylabel": "Mean Quality of Life Score"},
    "compound_qol_worldview": {"scenario": "full_compound", "kind": "lines", "series": SERIES["qol_worldview"], "colors": ["#1B9E77", "#D95F02", "#7570B3", "#E7298A"], "filename": "19_compound_qol_worldview", "title": "Quality of Life by Worldview - Compound Scenario", "xlabel": "Day", "ylabel": "Mean Quality of Life Score"},
}


def _theme(dpi: int) -> None:
    plt.style.use("seaborn-v0_8-whitegrid")
    plt.rcParams.update({"figure.dpi": dpi, "savefig.dpi": dpi, "font.family": "DejaVu Sans", "axes.titlesize": 10.5, "axes.titleweight": "semibold", "axes.labelsize": 11, "xtick.labelsize": 9, "ytick.labelsize": 9, "legend.fontsize": 8, "legend.frameon": False, "grid.alpha": 0.18, "axes.spines.top": False, "axes.spines.right": False})


def _x_values(df: pd.DataFrame, unit: str) -> tuple[pd.Series, str]:
    x = pd.to_numeric(df.get("hours", pd.Series(range(len(df)))), errors="coerce")
    return (x / 24.0, "Day") if unit == "day" else (x, "Hour")


def _plot_lines(df: pd.DataFrame, spec: dict[str, Any], out: Path, unit: str, tick: float) -> bool:
    x, default_xlabel = _x_values(df, unit)
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    plotted = 0
    for base, label in spec["series"]:
        column = f"{base}_mean" if spec.get("statistic") == "mean" and f"{base}_mean" in df.columns else _pick(df, base)
        if column is None:
            continue
        y = pd.to_numeric(df[column], errors="coerce")
        stability_colors = {"Deaths": "black", "Evacuated": "green", "Stranded": "red", "In Shelter": "blue", "In Healthcare": "orange"}
        series_index = next(index for index, item in enumerate(spec["series"]) if item[0] == base)
        color = spec.get("colors", [])[series_index] if series_index < len(spec.get("colors", [])) else stability_colors.get(label)
        line, = ax.plot(x, y, linewidth=1.8, label=label, color=color)
        q25, q75 = f"{base}_q25", f"{base}_q75"
        if q25 in df.columns and q75 in df.columns:
            ax.fill_between(x, df[q25], df[q75], color=line.get_color(), alpha=0.24, linewidth=0)
        plotted += 1
    if not plotted:
        plt.close(fig)
        return False
    ax.set(title=spec["title"], xlabel=spec.get("xlabel") or default_xlabel, ylabel=spec["ylabel"])
    ax.xaxis.set_major_locator(MultipleLocator(tick))
    ax.set_xlim(left=0)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return True


def _plot_structural_impact(df: pd.DataFrame, spec: dict[str, Any], out: Path, unit: str, tick: float) -> bool:
    if df.empty:
        return False
    series = [
        ("house_flooded_pct", "Houses flooded", "#0072B2", "-"),
        ("house_molded_pct", "Houses with mold", "#D55E00", "--"),
        ("biz_flooded_pct", "Businesses flooded", "#E69F00", "-"),
        ("biz_molded_pct", "Businesses with mold", "#009E73", "--"),
        ("school_flooded_pct", "Schools flooded", "#CC79A7", "-"),
        ("school_molded_pct", "Schools with mold", "#332288", "--"),
    ]
    x, default_xlabel = _x_values(df, unit)
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    plotted = 0
    for base, label, color, linestyle in series:
        column = _pick(df, base)
        if column is None:
            continue
        y = pd.to_numeric(df[column], errors="coerce")
        if base in {"house_molded_pct", "biz_molded_pct"} and float(y.fillna(0).max()) <= 0:
            continue
        ax.plot(x, y, color=color, linewidth=1.9, linestyle=linestyle, label=label)
        q25, q75 = f"{base}_q25", f"{base}_q75"
        if q25 in df.columns and q75 in df.columns:
            ax.fill_between(x, df[q25], df[q75], color=color, alpha=0.12, linewidth=0)
        plotted += 1
    if not plotted:
        plt.close(fig)
        return False
    ax.set(title=spec["title"], xlabel=spec.get("xlabel") or default_xlabel, ylabel=spec["ylabel"])
    ax.xaxis.set_major_locator(MultipleLocator(tick))
    ax.set_xlim(left=0)
    ax.legend(fontsize=7, loc="upper right")
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return True


def _plot_composition(df: pd.DataFrame, spec: dict[str, Any], out: Path) -> bool:
    fields = [
        ("male_pct", "Male"),
        ("female_pct", "Female"),
        ("ethnicity_white_pct", "White"),
        ("ethnicity_black_pct", "Black"),
        ("ethnicity_hispanic_pct", "Hispanic"),
        ("ethnicity_other_pct", "Other"),
        ("age_0_14_pct", "Age 0-14"),
        ("age_15_64_pct", "Age 15-64"),
        ("age_65_100_pct", "Age 65+"),
        ("wealth_lower_pct", "Lower Income"),
        ("wealth_middle_pct", "Middle Income"),
        ("wealth_upper_middle_pct", "Upper-Middle Income"),
        ("wealth_upper_pct", "Upper Income"),
        ("worldview_hierarchist_pct", "Hierarchist"),
        ("worldview_egalitarian_pct", "Egalitarian"),
        ("worldview_individualist_pct", "Individualist"),
        ("worldview_fatalist_pct", "Fatalist"),
    ]
    row = df.iloc[0] if not df.empty else pd.Series(dtype=float)
    fields = [(column, label) for column, label in fields if column in row]
    if not fields:
        return False
    family_colors = {
        "sex": "#4C78A8",
        "ethnicity": "#F58518",
        "age": "#54A24B",
        "wealth": "#E45756",
        "worldview": "#B279A2",
    }

    def family_for(column: str) -> str:
        if column in {"male_pct", "female_pct"}:
            return "sex"
        return next((family for family in family_colors if column.startswith(f"{family}_")), "other")

    colors = [family_colors.get(family_for(column), "#999999") for column, _ in fields]
    fig, ax = plt.subplots(figsize=(10.5, 4.8))
    values = [float(row[column]) for column, _ in fields]
    bars = ax.bar(range(len(fields)), values, color=colors)
    ax.set(title=spec["title"], ylabel=spec["ylabel"])
    ax.set_xticks(range(len(fields)), [label for _, label in fields], rotation=35, ha="right")
    ax.tick_params(axis="y", labelleft=False)
    ax.set_ylim(top=max(values) * 1.14 if values else 1.0)
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, value, f"{value:.0f}", ha="center", va="bottom", fontsize=8, fontweight="semibold")
    ax.grid(axis="y", alpha=0.18)
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return True


def _plot_routine(df: pd.DataFrame, spec: dict[str, Any], out: Path) -> bool:
    if df.empty or "hours" not in df:
        return False
    tmp = df.copy()
    hour = pd.to_numeric(tmp["hours"], errors="coerce") % 24
    work = ((hour >= 8) & (hour < 12)) | ((hour >= 14) & (hour < 18))
    school = ((hour >= 8) & (hour < 11)) | ((hour >= 14) & (hour < 17))
    source = [("work_attendance_pct", "Workforce participation", work), ("school_attendance_scheduled_pct", "Student attendance", school), ("leisure_attendance_pct", "Leisure participation", None), ("shopping_attendance_pct", "Shopping participation", None)]
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    plotted = 0
    for column, label, mask in source:
        if column not in tmp:
            continue
        values = pd.to_numeric(tmp[column], errors="coerce")
        if mask is not None:
            values = values.where(mask, 0.0)
        grouped = pd.DataFrame({"hour": hour, "value": values}).groupby("hour", as_index=False)["value"].median()
        ax.plot(grouped["hour"], grouped["value"], linewidth=1.8, label=label)
        plotted += 1
    if not plotted:
        plt.close(fig)
        return False
    ax.set(title=spec["title"], xlabel=spec["xlabel"], ylabel=spec["ylabel"])
    ax.set_xticks(range(0, 24, 2))
    ax.legend()
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return True


def _plot_bars(df: pd.DataFrame, spec: dict[str, Any], out: Path) -> bool:
    if df.empty:
        return False
    if "replication" in df and "hours" in df:
        final = df.sort_values("hours").groupby("replication").tail(1).set_index("replication")
        peak = df.groupby("replication").max(numeric_only=True)
    else:
        final = df.tail(1)
        peak = final
    labels, values, lows, highs = [], [], [], []
    for metric, label, mode in spec["metrics"]:
        source = peak if mode == "peak" else final
        if metric not in source:
            continue
        values_series = pd.to_numeric(source[metric], errors="coerce").dropna()
        if values_series.empty:
            continue
        q25, q50, q75 = values_series.quantile([0.25, 0.5, 0.75])
        labels.append(label)
        values.append(q50)
        lows.append(q50 - q25)
        highs.append(q75 - q50)
    if not labels:
        return False
    ordered = sorted(zip(labels, values), key=lambda item: item[1])
    labels = [label for label, _ in ordered]
    values = [value for _, value in ordered]
    fig, ax = plt.subplots(figsize=(7.2, 4.8))
    y_positions = np.arange(len(labels))
    dot_color = "#2E86AB"
    value_color = "#D95F02"
    ax.scatter(values, y_positions, color=dot_color, s=52, zorder=3)
    for y_position, value in zip(y_positions, values):
        ax.annotate(f"{value:.1f}", (value, y_position), xytext=(0, 8), textcoords="offset points", ha="center", va="bottom", fontsize=8, color=value_color, fontweight="semibold")
    ax.set(title=spec["title"], xlabel="Percentage of population")
    ax.set_yticks(y_positions, labels)
    ax.set_xlim(left=0)
    ax.grid(axis="y", alpha=0.18)
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return True


def _find_scenario_dir(root: Path, scenario: str) -> Path:
    names = [scenario]
    if scenario == "flood_only":
        names.append("floodonly")
    candidates = [root / name for name in names]
    discovered = [path for path in root.rglob("*") if path.is_dir() and any(path.name == name or path.name.startswith(f"{name}_") for name in names)]
    candidates.extend(sorted(discovered, key=lambda path: path.name, reverse=True))
    for candidate in candidates:
        if (candidate / "timeseries_quantiles.csv").exists() or (candidate / "timeseries_all_replications.csv").exists():
            return candidate
    raise FileNotFoundError(f"Could not find exported timeseries for scenario '{scenario}' below {root}")


def _load_scenario(root: Path, scenario: str, source: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    folder = (root / source).resolve() if source else _find_scenario_dir(root, scenario)
    if not folder.is_dir() or not ((folder / "timeseries_quantiles.csv").exists() or (folder / "timeseries_all_replications.csv").exists()):
        raise FileNotFoundError(f"Could not find exported timeseries for source '{source or scenario}' below {root}")
    all_path = folder / "timeseries_all_replications.csv"
    quant_path = folder / "timeseries_quantiles.csv"
    df_all = pd.read_csv(all_path) if all_path.exists() else pd.DataFrame()
    df_q = pd.read_csv(quant_path) if quant_path.exists() else df_all.groupby("hours", as_index=False).mean(numeric_only=True)
    return df_all, df_q


def _load_config(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def generate(run_dir: Path, output_dir: Path, selected: list[str], config: dict[str, Any], dpi: int, unit: str, tick: float, image_format: str) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    specs = deepcopy(FIGURES)
    for key, overrides in config.get("figures", {}).items():
        if key in specs:
            specs[key].update(overrides)
    data: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
    written: list[Path] = []
    _theme(dpi)
    for key in selected:
        if key not in specs:
            raise KeyError(f"Unknown figure '{key}'. Use --list-figures to see available names.")
        spec = specs[key]
        scenario = spec["scenario"]
        data_key = spec.get("source", scenario)
        if data_key not in data:
            data[data_key] = _load_scenario(run_dir, scenario, spec.get("source"))
        df_all, df_q = data[data_key]
        out = output_dir / f"{spec['filename']}.{image_format}"
        kind = spec["kind"]
        if kind == "lines":
            made = _plot_lines(df_q, spec, out, unit, tick)
        elif kind == "structural":
            made = _plot_structural_impact(df_q, spec, out, unit, tick)
        elif kind == "composition":
            made = _plot_composition(df_all, spec, out)
        elif kind == "routine":
            made = _plot_routine(df_all, spec, out)
        else:
            made = _plot_bars(df_all, spec, out)
        if made:
            written.append(out)
    (output_dir / "paper_graph_manifest.txt").write_text("\n".join(path.name for path in written) + "\n", encoding="utf-8")
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the selected paper figures from scenario exports.")
    parser.add_argument("--run-dir", type=Path, default=Path("outputs"), help="Root containing scenario export folders.")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/paper_graphs"), help="Destination for paper-ready images.")
    parser.add_argument("--figures", default="all", help="Comma-separated figure names, or 'all'.")
    parser.add_argument("--config", type=Path, help="Optional JSON file overriding figure filenames, titles, labels, and series.")
    parser.add_argument("--dpi", type=int, default=300, help="Output resolution; default 300.")
    parser.add_argument("--time-unit", choices=("hour", "day"), default="day", help="X-axis unit for time-series figures.")
    parser.add_argument("--time-tick", type=float, default=3, help="Spacing between time-axis ticks in the selected unit; default is three days.")
    parser.add_argument("--format", choices=("png", "pdf", "svg"), default="png", dest="image_format")
    parser.add_argument("--list-figures", action="store_true", help="List figure names and exit.")
    args = parser.parse_args()
    if args.list_figures:
        print("\n".join(FIGURES))
        return
    selected = list(FIGURES) if args.figures.strip().lower() == "all" else [name.strip() for name in args.figures.split(",") if name.strip()]
    written = generate(args.run_dir.resolve(), args.output_dir.resolve(), selected, _load_config(args.config), args.dpi, args.time_unit, args.time_tick, args.image_format)
    print(f"Saved {len(written)} paper figures to {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()