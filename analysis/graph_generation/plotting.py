from __future__ import annotations

from pathlib import Path
from matplotlib.ticker import FuncFormatter
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def prepare_generation(run_dir: Path, scenario: str, out_subdir: str) -> tuple[Path, Path, pd.DataFrame, pd.DataFrame]:
    """Load a scenario's exports and prepare the shared plotting inputs."""
    run_dir = Path(run_dir).resolve()
    scenario_dir = run_dir / scenario
    if not scenario_dir.exists():
        scenario_dir = run_dir
    out_dir = run_dir / out_subdir
    out_dir.mkdir(parents=True, exist_ok=True)

    quantiles_path = scenario_dir / "timeseries_quantiles.csv"
    all_replications_path = scenario_dir / "timeseries_all_replications.csv"
    if not quantiles_path.exists() and not all_replications_path.exists():
        raise FileNotFoundError(f"No timeseries files found under {scenario_dir}")

    df_all = pd.read_csv(all_replications_path) if all_replications_path.exists() else pd.DataFrame()
    df_q = pd.read_csv(quantiles_path) if quantiles_path.exists() else (
        df_all.groupby("hours", as_index=False).mean(numeric_only=True).copy()
    )

    if not df_all.empty and "hours" in df_all.columns and "replication" in df_all.columns:
        has_quantile_band = any(str(column).endswith(("_q25", "_q75")) for column in df_q.columns)
        if not has_quantile_band:
            metrics = [
                column for column in df_all.columns
                if column not in {"hours", "replication", "seed", "out_dir"}
                and pd.api.types.is_numeric_dtype(df_all[column])
            ]
            if metrics:
                grouped = df_all.groupby("hours", as_index=False)[metrics]
                q25 = grouped.quantile(0.25, numeric_only=True).rename(columns={m: f"{m}_q25" for m in metrics})
                q75 = grouped.quantile(0.75, numeric_only=True).rename(columns={m: f"{m}_q75" for m in metrics})
                df_q = df_q.merge(q25, on="hours", how="left").merge(q75, on="hours", how="left")

    df_q = _inject_active_hour_series(df_q, df_all)
    aliases = [
        ("affected_vectorborne_pct", "affected_stagnant_pct", df_all),
        ("affected_vectorborne_pct", "affected_stagnant_pct", df_q),
        ("healthcare_expense_vectorborne_total", "healthcare_expense_stagnant_total", df_q),
    ]
    for target, source, frame in aliases:
        if target not in frame.columns and source in frame.columns:
            frame[target] = pd.to_numeric(frame[source], errors="coerce")
    return scenario_dir, out_dir, df_all, df_q


def write_manifest(out_dir: Path, manifest_name: str, file_stem: str | None = None) -> Path:
    """Remove stale scenario PNGs and write the current output manifest."""
    if file_stem:
        for stale in out_dir.glob(f"{file_stem}_*.png"):
            stale.unlink()
    files = sorted(path.name for path in out_dir.glob("*.png"))
    manifest = out_dir / manifest_name
    manifest.write_text("\n".join(files) + "\n", encoding="utf-8")
    return manifest


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
        }
    )


def _style_axes(ax, y_as_currency: bool = False) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#d4dbe3")
    ax.spines["bottom"].set_color("#d4dbe3")
    if y_as_currency:
        ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:,.0f}"))


def _pick(df: pd.DataFrame, base: str, prefer_quantile: bool = True) -> str | None:
    candidates = [base]
    if base == "person_wealth_total_scaled":
        candidates.extend(["person_wealth_total", "person_wealth_mean", "person_income_mean"])
    elif base == "person_wealth_total":
        candidates.extend(["person_wealth_mean", "person_income_mean"])
    elif base == "person_wealth_mean":
        candidates.append("person_income_mean")
    suffixes = ("_median", "_mean", "") if prefer_quantile else ("", "_mean", "_median")
    for candidate in candidates:
        for suffix in suffixes:
            name = f"{candidate}{suffix}"
            if name in df.columns:
                return name
    return None


def _plot_lines(df: pd.DataFrame, series: list[tuple[str, str]], title: str, ylabel: str, out: Path) -> None:
    _apply_plot_theme()
    fig, ax = plt.subplots(figsize=(12, 5))
    x = df["hours"] if "hours" in df.columns else np.arange(len(df))
    handles = []
    for base, label in series:
        column = _pick(df, base)
        y = df[column] if column else np.zeros(len(x))
        stability_colors = {"Deaths": "black", "Evacuated": "green", "Stranded": "red", "In Shelter": "blue", "In Healthcare": "orange"}
        h, = ax.plot(x, y, linewidth=2, label=label, color=stability_colors.get(label))
        handles.append(h)
        q25, q75 = f"{base}_q25", f"{base}_q75"
        if q25 in df.columns and q75 in df.columns:
            ax.fill_between(x, df[q25], df[q75], alpha=0.12)
    if not handles:
        plt.close(fig)
        return
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.set_xlabel("Hour")
    ax.grid(False)
    _style_axes(ax, y_as_currency=("currency" in ylabel.lower() or "wealth" in ylabel.lower()))
    ax.legend(handles=handles, fontsize=9)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def _inject_active_hour_series(df_q: pd.DataFrame, df_all: pd.DataFrame) -> pd.DataFrame:
    if df_q.empty or df_all.empty or "hours" not in df_q.columns or "hours" not in df_all.columns:
        return df_q
    hour = (df_all["hours"] % 24).astype(int)
    work = ((hour >= 8) & (hour < 12)) | ((hour >= 14) & (hour < 18))
    school = ((hour >= 8) & (hour < 11)) | ((hour >= 14) & (hour < 17))
    work_source = next((c for c in ("work_attendance_workhours_pct", "work_attendance_scheduled_pct", "work_attendance_pct") if c in df_all.columns), None)
    if work_source:
        values = df_all.loc[work, ["hours", work_source]].groupby("hours", as_index=False).mean(numeric_only=True)
        df_q = df_q.merge(values.rename(columns={work_source: "work_attendance_schoolday_mean"}), on="hours", how="left")
    if "school_attendance_scheduled_pct" in df_all.columns:
        values = df_all.loc[school, ["hours", "school_attendance_scheduled_pct"]].groupby("hours", as_index=False).mean(numeric_only=True)
        df_q = df_q.drop(columns=["school_attendance_schoolday_mean"], errors="ignore").merge(values.rename(columns={"school_attendance_scheduled_pct": "school_attendance_schoolday_mean"}), on="hours", how="left")
    elif "attendance_rate_pct" in df_all.columns:
        values = df_all.loc[school, ["hours", "attendance_rate_pct"]].groupby("hours", as_index=False).mean(numeric_only=True)
        df_q = df_q.merge(values.rename(columns={"attendance_rate_pct": "school_attendance_schoolday_mean"}), on="hours", how="left")
    return df_q


def _plot_hour_of_day_profile(df_all: pd.DataFrame, out: Path, title: str = "Routine Profile by Hour of Day") -> None:
    if df_all.empty or "hours" not in df_all.columns:
        return
    tmp = df_all.copy()
    hour = (tmp["hours"] % 24).astype(int)
    work = ((hour >= 8) & (hour < 12)) | ((hour >= 14) & (hour < 18))
    school = ((hour >= 8) & (hour < 11)) | ((hour >= 14) & (hour < 17))
    columns = []
    if "work_attendance_pct" in tmp:
        tmp["work_attendance_profile_pct"] = np.where(work, tmp["work_attendance_pct"], 0.0)
        columns.append(("work_attendance_profile_pct", "Work Attendance"))
    school_source = "school_attendance_scheduled_pct" if "school_attendance_scheduled_pct" in tmp else "attendance_rate_pct" if "attendance_rate_pct" in tmp else None
    if school_source:
        tmp["school_attendance_profile_pct"] = np.where(school, pd.to_numeric(tmp[school_source], errors="coerce").fillna(0.0), 0.0)
        columns.append(("school_attendance_profile_pct", "School Attendance"))
    columns.extend((c, label) for c, label in (("leisure_attendance_pct", "Leisure"), ("shopping_attendance_pct", "Shopping")) if c in tmp)
    if not columns:
        return
    tmp["hour_of_day"] = hour
    metrics = [c for c, _ in columns]
    med = tmp.groupby("hour_of_day", as_index=False)[metrics].median(numeric_only=True)
    _apply_plot_theme()
    fig, ax = plt.subplots(figsize=(12, 5))
    for column, label in columns:
        ax.plot(med["hour_of_day"], med[column], linewidth=2, label=label)
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


def _plot_static_bars(df_all: pd.DataFrame, out: Path) -> None:
    if df_all.empty:
        return
    row = df_all.iloc[0]
    fields = [("male_pct", "Male"), ("female_pct", "Female"), ("ethnicity_white_pct", "Ethnicity White"), ("ethnicity_black_pct", "Ethnicity Black"), ("ethnicity_hispanic_pct", "Ethnicity Hispanic"), ("ethnicity_other_pct", "Ethnicity Other"), ("age_0_14_pct", "Age 0-14"), ("age_15_64_pct", "Age 15-64"), ("age_65_100_pct", "Age 65+"), ("wealth_lower_pct", "Wealth Lower"), ("wealth_middle_pct", "Wealth Middle"), ("wealth_upper_middle_pct", "Wealth Upper-Middle"), ("wealth_upper_pct", "Wealth Upper")]
    labels = [label for column, label in fields if column in df_all.columns]
    values = [float(row[column]) for column, _ in fields if column in df_all.columns]
    if not labels:
        return
    _apply_plot_theme()
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.bar(np.arange(len(labels)), values)
    ax.set_title("Population Composition")
    ax.set_ylabel("Percent")
    ax.set_xticks(np.arange(len(labels)))
    ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.grid(False)
    _style_axes(ax)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
