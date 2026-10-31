from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
import numpy as np
import pandas as pd


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

OUTCOME_LABELS = {
    "dead_pct_final": "Deaths",
    "injured_ever_pct_final": "Ever injured",
    "infectious_ever_pct_final": "Ever infectious",
    "mold_ever_pct_final": "Ever mold symptoms",
    "vector_ever_pct_final": "Ever vector symptoms",
    "compound_burden_peak_pct": "Peak compound burden",
    "compound_burden_auc_pct_hours": "Compound burden AUC",
    "healthcare_backlog_peak_pct": "Peak healthcare backlog",
    "shelter_backlog_peak_pct": "Peak shelter backlog",
    "qol_mean_time_average_pct": "Mean QoL",
    "qol_children_time_average_pct": "Children's QoL",
    "inequity_gap_time_average_pct": "Low-minus-high income disease gap",
}

PARAMETER_LABELS = {
    "flood_depth_multiplier": "Flood depth",
    "flood_wave_duration_hours": "Flood wave duration",
    "stranded_depth_tolerance_mult": "Stranding tolerance",
    "injury_risk_scale": "Injury risk",
    "hours_before_rescue": "Rescue delay",
    "warning_pre_flood_base": "Warning strength",
    "infectious_transmission_scale": "Infectious transmission",
    "infectious_gamma": "Infectious recovery",
    "infectious_seed_share": "Initial infection share",
    "house_mold_rate": "House mold rate",
    "vector_exposure_hazard": "Vector exposure",
    "service_capacity_scale": "Service capacity",
}


def _paths(run_dir: Path) -> dict[str, Path]:
    return {
        "run": run_dir / "run_results.csv",
        "morris": run_dir / "morris_indices.csv",
        "ranking": run_dir / "morris_parameter_ranking.csv",
        "prcc": run_dir / "prcc_indices.csv",
        "variability": run_dir / "within_point_variability.csv",
        "config": run_dir / "analysis_config.json",
    }


def _check_inputs(paths: dict[str, Path]) -> None:
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Missing sensitivity output file(s): " + ", ".join(missing)
        )


def _read_tables(paths: dict[str, Path]) -> dict[str, pd.DataFrame]:
    return {
        "run": pd.read_csv(paths["run"]),
        "morris": pd.read_csv(paths["morris"]),
        "ranking": pd.read_csv(paths["ranking"]),
        "prcc": pd.read_csv(paths["prcc"]),
        "variability": pd.read_csv(paths["variability"]),
    }


def _save_ranking_plot(ranking: pd.DataFrame, out: Path) -> None:
    ordered = ranking.sort_values("mean_normalized_mu_star", ascending=True)
    fig, ax = plt.subplots(figsize=(10, 6.5), constrained_layout=True)
    bars = ax.barh(
        [PARAMETER_LABELS.get(name, name.replace("_", " ")) for name in ordered["parameter"]],
        ordered["mean_normalized_mu_star"],
        color="#4472C4",
    )
    ax.bar_label(bars, fmt="%.2f", padding=3, fontsize=9)
    ax.set_xlabel("Mean normalized Morris μ* across 12 outcomes")
    ax.set_title("Global Morris screening ranking")
    ax.grid(axis="x", alpha=0.25)
    ax.set_axisbelow(True)
    fig.savefig(out, dpi=180)
    plt.close(fig)


def _save_morris_heatmap(
    morris: pd.DataFrame,
    run: pd.DataFrame,
    out: Path,
) -> None:
    outcome_sd = (
        run[run["method"] == "morris"]
        .groupby("sample_id")[list(OUTCOMES)]
        .mean()
        .std(ddof=1)
        .replace(0.0, np.nan)
    )
    matrix = morris.pivot(index="outcome", columns="parameter", values="mu_star")
    normalized = matrix.copy()
    for outcome in normalized.index:
        normalized.loc[outcome] = normalized.loc[outcome] / outcome_sd.get(outcome, np.nan)

    parameter_order = [
        name for name in PARAMETER_LABELS
        if name in normalized.columns
    ]
    outcome_order = [outcome for outcome in OUTCOMES if outcome in normalized.index]
    normalized = normalized.loc[outcome_order, parameter_order]

    fig, ax = plt.subplots(figsize=(14, 8), constrained_layout=True)
    image = ax.imshow(normalized.to_numpy(), aspect="auto", cmap="YlOrRd")
    ax.set_xticks(np.arange(len(parameter_order)))
    ax.set_xticklabels(
        [PARAMETER_LABELS[name] for name in parameter_order],
        rotation=45,
        ha="right",
    )
    ax.set_yticks(np.arange(len(outcome_order)))
    ax.set_yticklabels([OUTCOME_LABELS[outcome] for outcome in outcome_order])
    for row in range(len(outcome_order)):
        for col in range(len(parameter_order)):
            value = normalized.iloc[row, col]
            if np.isfinite(value):
                ax.text(col, row, f"{value:.1f}", ha="center", va="center", fontsize=7)
    colorbar = fig.colorbar(image, ax=ax, shrink=0.85)
    colorbar.set_label("Morris μ* / SD of outcome across Morris design means")
    ax.set_title("Outcome-specific Morris influence (range-normalized)")
    fig.savefig(out, dpi=180)
    plt.close(fig)


def _save_morris_sigma_plot(morris: pd.DataFrame, run: pd.DataFrame, out: Path) -> None:
    outcomes = [
        "injured_ever_pct_final",
        "infectious_ever_pct_final",
        "mold_ever_pct_final",
        "vector_ever_pct_final",
        "healthcare_backlog_peak_pct",
        "qol_mean_time_average_pct",
    ]
    outcome_sd = (
        run[run["method"] == "morris"]
        .groupby("sample_id")[list(OUTCOMES)]
        .mean()
        .std(ddof=1)
        .replace(0.0, np.nan)
    )
    colors = plt.get_cmap("tab20").colors
    params = list(PARAMETER_LABELS)
    color_for = {name: colors[index % len(colors)] for index, name in enumerate(params)}

    fig, axes = plt.subplots(2, 3, figsize=(15, 9), constrained_layout=True)
    for ax, outcome in zip(axes.flat, outcomes):
        data = morris[morris["outcome"] == outcome].copy()
        scale = outcome_sd.get(outcome, np.nan)
        data["mu_star_scaled"] = data["mu_star"] / scale
        data["sigma_scaled"] = data["sigma"] / scale
        data = data.sort_values("mu_star_scaled", ascending=False)
        labeled = set(data.head(3)["parameter"])
        for row in data.itertuples():
            emphasize = row.parameter in labeled
            ax.scatter(
                row.mu_star_scaled,
                row.sigma_scaled,
                color=color_for.get(row.parameter, "gray") if emphasize else "#B8B8B8",
                s=48 if emphasize else 24,
            )
            if emphasize:
                ax.annotate(
                    PARAMETER_LABELS.get(row.parameter, row.parameter),
                    (row.mu_star_scaled, row.sigma_scaled),
                    xytext=(3, 3),
                    textcoords="offset points",
                    fontsize=7,
                )
        ax.set_title(OUTCOME_LABELS[outcome])
        ax.set_xlabel("μ* / outcome SD")
        ax.set_ylabel("σ / outcome SD")
        ax.grid(alpha=0.2)
        ax.set_axisbelow(True)
    fig.suptitle("Morris influence and context-dependence diagnostics")
    fig.savefig(out, dpi=180)
    plt.close(fig)


def _save_prcc_heatmap(
    prcc: pd.DataFrame,
    out: Path,
    exclude_outcomes: tuple[str, ...] = (),
) -> pd.DataFrame:
    table = prcc.copy()
    table["significant_ci"] = (
        (table["prcc_ci_low"] > 0.0) | (table["prcc_ci_high"] < 0.0)
    )
    parameters = [
        name for name in PARAMETER_LABELS
        if name in table["parameter"].unique()
    ]
    pivot = table.pivot(index="outcome", columns="parameter", values="prcc")
    low = table.pivot(index="outcome", columns="parameter", values="prcc_ci_low")
    high = table.pivot(index="outcome", columns="parameter", values="prcc_ci_high")
    outcome_order = [
        outcome for outcome in OUTCOMES
        if outcome in pivot.index and outcome not in exclude_outcomes
    ]
    pivot = pivot.reindex(outcome_order)[parameters]
    low = low.reindex(pivot.index)[parameters]
    high = high.reindex(pivot.index)[parameters]

    fig, ax = plt.subplots(figsize=(11, 8), constrained_layout=True)
    image = ax.imshow(
        pivot.to_numpy(),
        aspect="auto",
        cmap="RdBu_r",
        norm=TwoSlopeNorm(vmin=-1.0, vcenter=0.0, vmax=1.0),
    )
    ax.set_xticks(np.arange(len(parameters)))
    ax.set_xticklabels([PARAMETER_LABELS[name] for name in parameters], rotation=35, ha="right")
    ax.set_yticks(np.arange(len(pivot.index)))
    ax.set_yticklabels([OUTCOME_LABELS.get(outcome, outcome) for outcome in pivot.index])
    for row, outcome in enumerate(pivot.index):
        for col, parameter in enumerate(parameters):
            value = pivot.loc[outcome, parameter]
            lo = low.loc[outcome, parameter]
            hi = high.loc[outcome, parameter]
            if np.isfinite(value):
                star = "*" if lo > 0 or hi < 0 else ""
                ax.text(col, row, f"{value:.2f}{star}", ha="center", va="center", fontsize=7)
    colorbar = fig.colorbar(image, ax=ax, shrink=0.85)
    colorbar.set_label("Partial rank correlation coefficient")
    ax.set_title("LHS PRCCs (* unadjusted bootstrap 95% interval excludes zero)")
    fig.savefig(out, dpi=180)
    plt.close(fig)
    return table


def _save_lhs_marginal_plot(
    run: pd.DataFrame,
    config: dict,
    out: Path,
) -> None:
    choices = [
        ("flood_depth_multiplier", "injured_ever_pct_final"),
        ("warning_pre_flood_base", "qol_mean_time_average_pct"),
        ("vector_exposure_hazard", "vector_ever_pct_final"),
        ("injury_risk_scale", "injured_ever_pct_final"),
        ("infectious_transmission_scale", "infectious_ever_pct_final"),
        ("house_mold_rate", "mold_ever_pct_final"),
    ]
    lhs = run[run["method"] == "lhs"]
    by_sample = lhs.groupby("sample_id", as_index=False).agg(
        **{
            parameter: (parameter, "mean")
            for parameter, _outcome in choices
        },
        **{
            outcome: (outcome, "mean")
            for _parameter, outcome in choices
        },
    )
    baseline = run[run["method"] == "baseline"]
    baseline_means = baseline[list(OUTCOMES)].mean()
    param_default = {
        parameter: float(config["parameters"][parameter]["default"])
        for parameter, _outcome in choices
    }

    fig, axes = plt.subplots(2, 3, figsize=(15, 9), constrained_layout=True)
    for ax, (parameter, outcome) in zip(axes.flat, choices):
        x = by_sample[parameter].to_numpy(dtype=float)
        y = by_sample[outcome].to_numpy(dtype=float)
        ax.scatter(x, y, alpha=0.45, s=18, color="#4472C4")
        bins = pd.qcut(pd.Series(x), q=10, duplicates="drop")
        summary = pd.DataFrame({"x": x, "y": y, "bin": bins}).groupby(
            "bin", observed=True
        ).agg(x=("x", "mean"), y=("y", "mean"), sd=("y", "std"), n=("y", "size"))
        sem = summary["sd"].fillna(0.0) / np.sqrt(summary["n"])
        ax.errorbar(
            summary["x"],
            summary["y"],
            yerr=sem,
            color="#C00000",
            marker="o",
            capsize=2,
            linewidth=1.2,
            label="Quantile-bin mean ± SE",
        )
        ax.axvline(param_default[parameter], color="black", linestyle="--", linewidth=1)
        ax.axhline(
            baseline_means[outcome],
            color="#666666",
            linestyle=":",
            linewidth=1,
            label="Baseline point mean",
        )
        ax.set_title(
            f"{PARAMETER_LABELS[parameter]} vs {OUTCOME_LABELS[outcome]}"
        )
        ax.set_xlabel(PARAMETER_LABELS[parameter])
        ax.set_ylabel(OUTCOME_LABELS[outcome])
        ax.grid(alpha=0.2)
        ax.set_axisbelow(True)
        ax.legend(fontsize=7, loc="best")
    fig.suptitle(
        "Marginal LHS trends (descriptive; other parameters vary simultaneously)"
    )
    fig.savefig(out, dpi=180)
    plt.close(fig)


def _save_variability_plot(
    run: pd.DataFrame,
    variability: pd.DataFrame,
    out: Path,
) -> pd.DataFrame:
    lhs_means = run[run["method"] == "lhs"].groupby("sample_id")[list(OUTCOMES)].mean()
    lhs_variability = variability[variability["method"] == "lhs"]
    rows = []
    for outcome in OUTCOMES:
        between = float(lhs_means[outcome].std(ddof=1))
        within_col = f"{outcome}_sd_across_seeds"
        within = float(lhs_variability[within_col].mean())
        rows.append(
            {
                "outcome": outcome,
                "between_parameter_point_sd": between,
                "mean_within_point_seed_sd": within,
                "within_to_between_sd_ratio": within / between if between > 0 else np.nan,
            }
        )
    data = pd.DataFrame(rows).sort_values("within_to_between_sd_ratio")
    y = np.arange(len(data))
    fig, ax = plt.subplots(figsize=(11, 7), constrained_layout=True)
    ax.barh(y, data["within_to_between_sd_ratio"], color="#70AD47")
    ax.axvline(1.0, color="#C00000", linestyle="--", label="Equal SDs")
    ax.set_yticks(y)
    ax.set_yticklabels([OUTCOME_LABELS[o] for o in data["outcome"]])
    ax.set_xlabel("Mean within-point seed SD / SD across LHS-point means")
    ax.set_title("Seed variability relative to spread across LHS parameter points")
    ax.grid(axis="x", alpha=0.2)
    ax.set_axisbelow(True)
    ax.legend()
    fig.savefig(out, dpi=180)
    plt.close(fig)
    return data


def build_main_publication_figure(
    screening_dir: Path,
    capacity_followup_dir: Path,
    output_path: Path,
) -> None:
    ranking_path = screening_dir / "morris_parameter_ranking.csv"
    prcc_path = capacity_followup_dir / "prcc_indices.csv"
    missing = [str(path) for path in (ranking_path, prcc_path) if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing figure input(s): " + ", ".join(missing))

    ranking = pd.read_csv(ranking_path).sort_values(
        "mean_normalized_mu_star", ascending=True
    )
    prcc = pd.read_csv(prcc_path)
    parameters = [
        "flood_depth_multiplier",
        "warning_pre_flood_base",
        "injury_risk_scale",
        "infectious_transmission_scale",
        "house_mold_rate",
        "vector_exposure_hazard",
        "service_capacity_scale",
    ]
    outcomes = [
        "dead_pct_final",
        "injured_ever_pct_final",
        "infectious_ever_pct_final",
        "mold_ever_pct_final",
        "vector_ever_pct_final",
        "compound_burden_auc_pct_hours",
        "healthcare_backlog_peak_pct",
        "shelter_backlog_peak_pct",
        "qol_mean_time_average_pct",
    ]
    prcc = prcc[prcc["parameter"].isin(parameters) & prcc["outcome"].isin(outcomes)]
    matrix = prcc.pivot(index="outcome", columns="parameter", values="prcc").reindex(
        index=outcomes, columns=parameters
    )
    low = prcc.pivot(index="outcome", columns="parameter", values="prcc_ci_low").reindex(
        index=outcomes, columns=parameters
    )
    high = prcc.pivot(index="outcome", columns="parameter", values="prcc_ci_high").reindex(
        index=outcomes, columns=parameters
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig, (rank_ax, heat_ax) = plt.subplots(
        1,
        2,
        figsize=(15.5, 8.2),
        gridspec_kw={"width_ratios": [0.85, 1.65]},
        constrained_layout=True,
    )

    rank_bars = rank_ax.barh(
        [PARAMETER_LABELS.get(p, p.replace("_", " ")) for p in ranking["parameter"]],
        ranking["mean_normalized_mu_star"],
        color="#4472C4",
    )
    rank_ax.bar_label(rank_bars, fmt="%.2f", padding=2, fontsize=8)
    rank_ax.set_xlabel("Mean normalized Morris μ*")
    rank_ax.set_title("(a) Global screening rank")
    rank_ax.grid(axis="x", alpha=0.2)
    rank_ax.set_axisbelow(True)
    rank_ax.tick_params(axis="y", labelsize=8)

    heat = heat_ax.imshow(
        matrix.to_numpy(),
        aspect="auto",
        cmap="RdBu_r",
        norm=TwoSlopeNorm(vmin=-1.0, vcenter=0.0, vmax=1.0),
    )
    heat_ax.set_xticks(np.arange(len(parameters)))
    heat_ax.set_xticklabels(
        [PARAMETER_LABELS[p] for p in parameters],
        rotation=45,
        ha="right",
        fontsize=8,
    )
    heat_ax.set_yticks(np.arange(len(outcomes)))
    heat_ax.set_yticklabels([OUTCOME_LABELS[o] for o in outcomes], fontsize=8)
    for row, outcome in enumerate(outcomes):
        for col, parameter in enumerate(parameters):
            estimate = matrix.loc[outcome, parameter]
            lower = low.loc[outcome, parameter]
            upper = high.loc[outcome, parameter]
            if np.isfinite(estimate):
                marker = "*" if lower > 0.0 or upper < 0.0 else ""
                heat_ax.text(
                    col,
                    row,
                    f"{estimate:.2f}{marker}",
                    ha="center",
                    va="center",
                    fontsize=7,
                )
    colorbar = fig.colorbar(heat, ax=heat_ax, shrink=0.82)
    colorbar.set_label("Partial rank correlation coefficient")
    heat_ax.set_title("(b) LHS/PRCC for selected outcomes")
    fig.suptitle(
        "Parameter sensitivity in the compound flood-disease scenario",
        fontsize=15,
    )
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def build_review(run_dir: Path) -> Path:
    paths = _paths(run_dir)
    _check_inputs(paths)
    tables = _read_tables(paths)
    config = pd.read_json(paths["config"], typ="series").to_dict()
    out_dir = run_dir / "review"
    out_dir.mkdir(parents=True, exist_ok=True)

    _save_ranking_plot(tables["ranking"], out_dir / "morris_global_ranking.png")
    _save_morris_heatmap(
        tables["morris"], tables["run"], out_dir / "morris_outcome_heatmap.png"
    )
    _save_morris_sigma_plot(
        tables["morris"], tables["run"], out_dir / "morris_sigma_diagnostics.png"
    )
    significant = _save_prcc_heatmap(
        tables["prcc"], out_dir / "lhs_prcc_heatmap.png"
    )
    _save_lhs_marginal_plot(
        tables["run"], config, out_dir / "lhs_marginal_trends.png"
    )
    variability = _save_variability_plot(
        tables["run"],
        tables["variability"],
        out_dir / "stochastic_vs_parameter_spread.png",
    )

    significant.to_csv(out_dir / "prcc_with_ci_flags.csv", index=False)
    variability.to_csv(out_dir / "stochastic_vs_parameter_spread.csv", index=False)
    _top_morris_table(tables["morris"]).to_csv(
        out_dir / "morris_top_parameters_by_outcome.csv", index=False
    )
    _baseline_table(tables["run"]).to_csv(
        out_dir / "baseline_outcome_summary.csv", index=False
    )
    return out_dir


def _top_morris_table(morris: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for outcome, group in morris.groupby("outcome", sort=False):
        for rank, item in enumerate(group.sort_values("mu_star", ascending=False).head(5).itertuples(), start=1):
            rows.append(
                {
                    "outcome": outcome,
                    "rank": rank,
                    "parameter": item.parameter,
                    "mu": item.mu,
                    "mu_star": item.mu_star,
                    "sigma": item.sigma,
                    "n_trajectories": item.n_trajectories,
                    "mu_star_ci_low": item.mu_star_ci_low,
                    "mu_star_ci_high": item.mu_star_ci_high,
                }
            )
    return pd.DataFrame(rows)


def _baseline_table(run: pd.DataFrame) -> pd.DataFrame:
    baseline = run[run["method"] == "baseline"]
    rows = []
    for outcome in OUTCOMES:
        values = baseline[outcome].to_numpy(dtype=float)
        rows.append(
            {
                "outcome": outcome,
                "mean": float(np.mean(values)),
                "sd_across_three_seeds": float(np.std(values, ddof=1)),
                "min": float(np.min(values)),
                "max": float(np.max(values)),
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate plots and summary tables for a completed sensitivity run."
    )
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=Path("outputs/sensitivity_analysis/compound_both_5000p_20261023T204821Z"),
    )
    parser.add_argument(
        "--publication-figure",
        action="store_true",
        help="Create a two-panel Morris-ranking and seven-parameter PRCC figure.",
    )
    parser.add_argument(
        "--capacity-followup-dir",
        type=Path,
        default=Path("outputs/sensitivity_analysis/compound_lhs_5000p_20261026T183952Z"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output PNG path for --publication-figure.",
    )
    args = parser.parse_args()
    if args.publication_figure:
        output = args.output or (args.run_dir / "review" / "main_sensitivity_figure.png")
        build_main_publication_figure(
            args.run_dir,
            args.capacity_followup_dir,
            output,
        )
        print(f"Publication figure written to {output}")
        return 0
    output = build_review(args.run_dir)
    print(f"Review plots and tables written to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
