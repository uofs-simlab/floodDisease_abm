"""
Flood-Disease ABM – Solara front-end
Compatible with
  • mesa      3.2.0
  • mesa-geo  0.9.1
  • solara    ≥1.28
Launch:
  • Terminal →  solara run serverrun.py
  • Spyder   →  press ▶ (runs fallback block at bottom)
"""

# -------------------------------------------------------------------- #
# 0 · Imports & path setup                                             #
# -------------------------------------------------------------------- #
import time, socket, webbrowser, threading
from contextlib import closing
import json
import os, subprocess
from pathlib import Path
import shlex
import sys, warnings, psutil, solara
from mesa.visualization import SolaraViz, make_plot_component as _mesa_make_plot_component
from mesa_geo.visualization import make_geospace_component
from shapely.geometry import Point
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from config.defaults import (
    MAP_POPULATION_PRESETS,
    RUN_DEFAULTS,
    SERVICE_DEFAULTS,
    MODEL_DEFAULTS,
    SCENARIO_CODE_BY_LABEL,
    SCENARIO_LABEL_BY_CODE,
    SCENARIO_NAME_BY_CODE,
    infectious_start_hour,
    scenario_flags,
)

HERE  = Path(__file__).resolve().parent        # …/run
ROOT  = HERE.parent
sys.path.append(str(ROOT))


def _open_browser(url: str) -> None:
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
    ]
    for browser in candidates:
        if Path(browser).exists():
            subprocess.Popen([browser, url])
            return
    webbrowser.open_new(url)

STARTUP_MAP_NAME = os.environ.get("FLOODDISEASE_ABM_MAP", "uvalde").strip().lower()
UVALDE_DATA_DIR = ROOT / "space" / "Uvalde_TX_map_data"
UVALDE_POPULATION_PRESET = MAP_POPULATION_PRESETS["uvalde"]
UVALDE_MAP_VIEW = {"view": (29.21, -99.775), "zoom": 14}
UVALDE_UI_CONTROL_PROFILE = {
    "population": {"min": RUN_DEFAULTS["N_persons"], "max": 30000, "step": 100},
    "capacity": {
        "shelter_cap_min": 0.0,
        "shelter_cap_max": 10.0,
        "shelter_cap_step": 0.5,
        "healthcare_cap_min": 0.0,
        "healthcare_cap_max": 10.0,
        "healthcare_cap_step": 0.5,
        "shelter_funding_min": 10000,
        "shelter_funding_max": 150000,
        "shelter_funding_step": 2500,
        "healthcare_funding_min": 25000,
        "healthcare_funding_max": 300000,
        "healthcare_funding_step": 5000,
    },
}


def _resolve_data_dir(map_name: str | None = None) -> Path:
    _ = map_name
    return UVALDE_DATA_DIR.resolve()


def _map_view_config(map_name: str | None = None) -> dict:
    _ = map_name
    return dict(UVALDE_MAP_VIEW)


def _map_ui_control_profile(map_name: str | None = None) -> dict:
    _ = map_name
    return json.loads(json.dumps(UVALDE_UI_CONTROL_PROFILE))


def _startup_population_defaults() -> dict:
    preset = UVALDE_POPULATION_PRESET
    groups = {
        "gender": ("male_share_pct", "female_share_pct"),
        "age": ("age_0_14_pct", "age_15_64_pct", "age_65_100_pct"),
        "ethnicity": (
            "ethnicity_white_pct",
            "ethnicity_black_pct",
            "ethnicity_hispanic_pct",
            "ethnicity_other_pct",
        ),
        "worldview": (
            "worldview_hierarchist_pct",
            "worldview_egalitarian_pct",
            "worldview_individualist_pct",
            "worldview_fatalist_pct",
        ),
    }
    return {
        group_name: {key: float(preset[key]) for key in keys}
        for group_name, keys in groups.items()
    }


def _startup_person_count() -> int:
    return int(RUN_DEFAULTS["N_persons"])


def _apply_population_preset(map_name: str) -> None:
    _ = map_name
    preset = UVALDE_POPULATION_PRESET

    model_params["N_persons"] = int(RUN_DEFAULTS["N_persons"])
    model_params["perc_education_people"] = float(preset["perc_education_people"])

    for group_name in ["gender", "age", "ethnicity", "worldview"]:
        group_values = preset.get(group_name, {})
        for key, value in group_values.items():
            model_params[key] = float(value)

    if "_population_mix_state" in globals():
        state = json.loads(json.dumps(_population_mix_state.value))
        for group_name in ["gender", "age", "ethnicity", "worldview"]:
            state[group_name].update(preset.get(group_name, {}))
        _population_mix_state.value = state

    if "_settings_state" in globals():
        state = json.loads(json.dumps(_settings_state.value))
        state["scenario"]["N_persons"] = int(RUN_DEFAULTS["N_persons"])
        _settings_state.value = _apply_scenario_rules_to_settings(state)


def _apply_startup_map_to_model_params() -> None:
    data_dir = _resolve_data_dir(STARTUP_MAP_NAME)
    model_params["map_name"] = "uvalde"
    _apply_population_preset("uvalde")

    gpkg = data_dir / "processed" / "abm_places.gpkg"
    house_override = data_dir / "processed" / "houses_augmented.geojson"
    school_override = data_dir / "processed" / "schools_campuses.geojson"
    uvalde_flood = data_dir / "uvalde_twdb_scenario5_1in100_flood.geojson"
    if not gpkg.exists():
        raise FileNotFoundError(f"Required Uvalde place dataset is missing: {gpkg}")
    if not uvalde_flood.exists():
        raise FileNotFoundError(f"Required Uvalde flood dataset is missing: {uvalde_flood}")

    model_params["houses_file"] = str(house_override if house_override.exists() else gpkg)
    model_params["businesses_file"] = str(gpkg)
    model_params["schools_file"] = str(school_override if school_override.exists() else gpkg)
    model_params["shelter_file"] = str(gpkg)
    model_params["healthcare_file"] = str(gpkg)
    model_params["government_file"] = str(gpkg)
    model_params["flood_file"] = str(uvalde_flood)

from agents._person import Person
from agents._shelter import Shelter
from agents._healthcare import Healthcare
from agents._house import House
from agents._school import School
from agents._government import Government
from agents._business import Business
from model._model import Model
from space._space import FloodInundationArea, StagnantPoolArea


warnings.filterwarnings("ignore", category=FutureWarning, module="seaborn")


def _format_metric_label(raw: str) -> str:
    metric_aliases = {
        "work_attendance_workhours_pct": "Work",
        "school_attendance_scheduled_pct": "School",
        "leisure_attendance_pct": "Leisure",
        "shopping_attendance_pct": "Shopping",
        "school_open_now_pct": "School Open",
        "person_wealth_total_scaled": "Person Wealth",
        "qol_children_pct": "Children",
        "qol_adults_pct": "Adults",
        "qol_seniors_pct": "Seniors",
        "qol_mean_pct": "Overall",
        "qol_low_income_pct": "Low Income",
        "qol_middle_income_pct": "Middle Income",
        "qol_upper_middle_pct": "Upper Middle",
        "qol_upper_pct": "Upper",
        "qol_hierarchist_pct": "Hierarchist",
        "qol_egalitarian_pct": "Egalitarian",
        "qol_individualist_pct": "Individualist",
        "qol_fatalist_pct": "Fatalist",
        "qol_white_pct": "White",
        "qol_black_pct": "Black",
        "qol_hispanic_pct": "Hispanic",
        "qol_other_pct": "Other",
        "hc_util_pct": "Utilization",
        "hc_backlog_pct": "Backlog",
        "hc_1_util_pct": "Healthcare 1 utilization",
        "hc_1_backlog_pct": "Healthcare 1 backlog",
        "hc_2_util_pct": "Healthcare 2 utilization",
        "hc_2_backlog_pct": "Healthcare 2 backlog",
        "hc_3_util_pct": "Healthcare 3 utilization",
        "hc_3_backlog_pct": "Healthcare 3 backlog",
        "hc_4_util_pct": "Healthcare 4 utilization",
        "hc_4_backlog_pct": "Healthcare 4 backlog",
        "shelter_util_pct": "Utilization",
        "shelter_backlog_pct": "Backlog",
        "shelter_1_util_pct": "Shelter 1 utilization",
        "shelter_1_backlog_pct": "Shelter 1 backlog",
        "shelter_2_util_pct": "Shelter 2 utilization",
        "shelter_2_backlog_pct": "Shelter 2 backlog",
        "affected_flood_pct": "Flood",
        "affected_evacuated_pct": "Evacuated",
        "affected_mold_pct": "Mold",
        "affected_vectorborne_pct": "Vectorborne",
        "affected_infectious_pct": "Ever Infected",
        "affected_stranded_unique_pct": "Stranded",
        "affected_sheltered_unique_pct": "Sheltered",
        "affected_healthcare_unique_pct": "In Healthcare",
        "affected_injured_unique_pct": "Injured",
        "inf_prev_pct": "Active Infections",
        "evacuation_expense_total": "Evacuation",
        "house_repair_expense_total": "House Repair",
        "business_repair_expense_total": "Business Repair",
        "healthcare_expense_flood_total": "Healthcare (Flood)",
        "healthcare_expense_mold_total": "Healthcare (Mold)",
        "healthcare_expense_vectorborne_total": "Healthcare (Vectorborne)",
        "healthcare_expense_infectious_total": "Healthcare (Infectious)",
        "healthcare_expense_total": "Healthcare",
    }
    text = str(raw or "")
    if text in metric_aliases:
        return metric_aliases[text]
    text = text.replace("_pct", "")
    text = text.replace("_", " ").strip()
    replacements = {
        "hc": "Healthcare",
        "biz": "Business",
        "gov": "Government",
        "qol": "QoL",
    }
    words = []
    for token in text.split():
        key = token.lower()
        words.append(replacements.get(key, token.capitalize()))
    return " ".join(words)


def make_plot_component(measure, post_process=None, backend="matplotlib", y_label=None, **plot_drawing_kwargs):
    keys = []
    if isinstance(measure, str):
        keys = [measure]
    elif isinstance(measure, dict):
        keys = list(measure.keys())
    elif isinstance(measure, (list, tuple)):
        keys = list(measure)

    likely_percent_series = bool(keys) and all("pct" in str(k).lower() for k in keys)

    def _post(ax):
        legend = ax.get_legend()
        if legend is not None:
            for t in legend.get_texts():
                t.set_text(_format_metric_label(t.get_text()))
        ax.set_xlabel("Hours")
        if y_label is not None:
            ax.set_ylabel(str(y_label))
        elif likely_percent_series:
            ax.set_ylabel("Population Percentage")
        if callable(post_process):
            post_process(ax)

    # Use default matplotlib color cycle (as in batchrun plots) for clearer, distinct series.
    measure_for_plot = keys if isinstance(measure, dict) else measure

    return _mesa_make_plot_component(
        measure_for_plot,
        post_process=_post,
        backend=backend,
        **plot_drawing_kwargs,
    )


def _fill_nan_lines_with_zero(ax):
    for line in ax.get_lines():
        y = line.get_ydata()
        if y is None:
            continue
        try:
            line.set_ydata(np.nan_to_num(np.asarray(y, dtype=float), nan=0.0))
        except Exception:
            continue


def _finance_plot_post_process(ax):
    legend = ax.get_legend()
    if legend is not None:
        alias = {
            "Business Wealth Total": "Business",
            "Government Wealth": "Government",
            "Shelter Wealth": "Shelter",
            "Healthcare Wealth": "Healthcare",
            "Person Wealth": "Person",
        }
        for t in legend.get_texts():
            raw = str(t.get_text())
            t.set_text(alias.get(raw, raw.replace(" Wealth Total", "").replace(" Wealth", "")))
    ax.set_ylabel("Wealth")


def _impact_expenses_post_process(ax):
    legend = ax.get_legend()
    if legend is None:
        return
    for t in legend.get_texts():
        text = str(t.get_text())
        t.set_text(text.replace(" Total", ""))

# --------------------------------------------------------------------------
# Console utility
# --------------------------------------------------------------------------

def clear_console():
    os.system('cls' if os.name == 'nt' else 'clear')

# -------------------------------------------------------------------- #
# 1 · Utility: resource usage                                          #
# -------------------------------------------------------------------- #
def _resource_usage():
    p = psutil.Process()
    return p.memory_info().rss / 1024**2, p.cpu_percent(interval=None)

# -------------------------------------------------------------------- #
# 2 · Agent portrayal                                                  #
# -------------------------------------------------------------------- #
def agent_portrayal(agent):
    p = {}

    # ---- default (so polygons show even if we miss a type)
    p["color"] = "Green"

    # ---- flood polygon
    if isinstance(agent, FloodInundationArea):
        p["color"] = "#00FFFF"         # cyan
        try:
            now = int(getattr(agent.model, "hours", 0) or 0)
            center = agent.geometry.representative_point()
            depth = float(agent.depth_at(center, hours=now) or 0.0)
            max_depth = max(0.01, float(getattr(agent.model, "flood_depth_default_m", 0.60) or 0.60))
            intensity = max(0.0, min(1.0, depth / max_depth))
            p["fillOpacity"] = 0.08 + 0.55 * intensity
            p["opacity"] = 0.25 + 0.65 * intensity
        except Exception:
            p["fillOpacity"] = 0.20
        return p
    
    # ---- vectorborne hotspots (post-flood polygons)
    if isinstance(agent, StagnantPoolArea):
        p["color"] = "Magenta"
        p["fillOpacity"] = 0.25
        return p


    # ---- people (point)
    if isinstance(agent, Person):
        physically_flood_blocked = False
        if hasattr(agent, "_is_flood_blocked"):
            try:
                physically_flood_blocked = bool(agent._is_flood_blocked(agent.geometry))
            except Exception:
                physically_flood_blocked = False
        else:
            try:
                depth_here = float(agent.model.space.get_flood_height_at_position(agent.geometry))
                resilience = float(getattr(agent, "flood_resilience", 10.0) or 10.0) / 10.0
                physically_flood_blocked = depth_here > resilience
            except Exception:
                physically_flood_blocked = False

        if not getattr(agent, "alive", True):
            p["color"] = "Black"
        elif str(getattr(agent, "inf_state", "S") or "S") == "I":
            p["color"] = "Magenta"
        elif (
            getattr(agent, "stranded", False)
            and not getattr(agent, "evacuated", False)
            and not getattr(agent, "in_shelter", False)
            and physically_flood_blocked
        ):
            p["color"] = "Red"
        elif getattr(agent, "injured", False):
            p["color"] = "Orange"
        else:
            p["color"] = "Green"
        p["marker_type"] = "CircleMarker"
        p["radius"] = 1
        p["stroke"] = True
        p["fill"] = True
        p["weight"] = 2
        p["opacity"] = 1.0
        p["fillOpacity"] = 2.0
        return p

    # ---- static polygons
    if isinstance(agent, Business):
        p["color"] = "Purple"
        p["fillOpacity"] = 0.25
        p["weight"] = 0.5
    elif isinstance(agent, House):
        p["color"] = "Brown"
        p["fillOpacity"] = 0.25
        p["weight"] = 0.35
    elif isinstance(agent, School):
        p["color"] = "Yellow"
        p["fillOpacity"] = 0.25
    elif isinstance(agent, Shelter):
        p["color"] = "Blue"
        p["fillOpacity"] = 0.25
    elif isinstance(agent, Healthcare):
        p["color"] = "Orange"
        p["fillOpacity"] = 0.25
    elif isinstance(agent, Government):
        p["color"] = "#66CC66"  # light green
        p["fillOpacity"] = 0.25

    if isinstance(getattr(agent, "geometry", None), Point):
        p["marker_type"] = "CircleMarker"
        p["radius"] = 2
        p["stroke"] = True
        p["fill"] = True
        p["fillColor"] = p.get("color", "Green")
        p["weight"] = 1
        p["opacity"] = 0.9
        p["fillOpacity"] = max(float(p.get("fillOpacity", 0.25) or 0.25), 0.6)

    return p


# -------------------------------------------------------------------- #
# 3 · Legend component                                                 #
# -------------------------------------------------------------------- #
LEGEND_MD = """
**Legend**

| Symbol | Persons         | Symbol | Entities        |
| :---   | :---            | :---   | :---            |
| <span style="background:Green;display:inline-block;width:12px;height:12px;"></span> | Safe      | <span style="background:Purple;display:inline-block;width:12px;height:12px;"></span> | Business        |
| <span style="background:Magenta;display:inline-block;width:12px;height:12px;"></span> | Infected  | <span style="background:Yellow;display:inline-block;width:12px;height:12px;"></span> | School        |
| <span style="background:Red;display:inline-block;width:12px;height:12px;"></span> | Stranded  | <span style="background:Brown;display:inline-block;width:12px;height:12px;"></span> | House           |
| <span style="background:Orange;display:inline-block;width:12px;height:12px;"></span> | Injured   | <span style="background:Orange;display:inline-block;width:12px;height:12px;"></span> | Healthcare      |
| <span style="background:Black;display:inline-block;width:12px;height:12px;"></span> | Deceased   | <span style="background:Blue;display:inline-block;width:12px;height:12px;"></span> | Shelter         |
| <span style="background:Cyan;display:inline-block;width:12px;height:12px;"></span> | Flood Extent | <span style="background:Green;display:inline-block;width:12px;height:12px;"></span> | Government |
| <span style="background:Magenta;display:inline-block;width:12px;height:12px;"></span> | Vectorborne hotspots |  |  |
"""

@solara.component
def ColorLegend(model):
    with solara.Card(title="Map legend", margin=0, style={"background": "rgba(255,255,255,0.96)"}):
        solara.Markdown(LEGEND_MD, style={
            "fontSize": "14px",
            "lineHeight": "1.35",
        })


def _clip_pct(x: float) -> float:
    try:
        return max(0.0, min(100.0, float(x)))
    except Exception:
        return 0.0


def _rebalance_group(values: dict[str, float], changed_key: str, new_value: float) -> dict[str, float]:
    values = {k: _clip_pct(v) for k, v in values.items()}
    # Sliders use step=1, so rebalance in integer points to avoid float jitter loops.
    values[changed_key] = float(round(_clip_pct(new_value)))
    other_keys = [k for k in values if k != changed_key]

    if not other_keys:
        return values

    remaining = max(0.0, 100.0 - values[changed_key])
    other_total = sum(values[k] for k in other_keys)
    if other_total <= 0.0:
        even = remaining / len(other_keys)
        for k in other_keys:
            values[k] = even
    else:
        scale = remaining / other_total
        for k in other_keys:
            values[k] = values[k] * scale

    rounded = {}
    keys = list(values.keys())
    running = 0
    for k in keys[:-1]:
        rounded[k] = float(int(round(values[k])))
        running += rounded[k]
    rounded[keys[-1]] = float(max(0, min(100, int(round(100.0 - running)))))
    return rounded


_LINKED_POPULATION_DEFAULTS = _startup_population_defaults()
_population_mix_state = solara.reactive(json.loads(json.dumps(_LINKED_POPULATION_DEFAULTS)))

# -------------------------------------------------------------------- #
# 4 · UI controls (sliders + file paths)                               #
# -------------------------------------------------------------------- #
DATA = _resolve_data_dir(STARTUP_MAP_NAME)   # ← ABSOLUTE PATH

model_params = {
            "in_healthcare_pct": "darkorange",
            "affected_healthcare_unique_pct": "orangered",
    "N_persons": RUN_DEFAULTS["N_persons"],
    "shelter_cap_limit": SERVICE_DEFAULTS["shelter_cap_limit"],
    "healthcare_cap_limit": SERVICE_DEFAULTS["healthcare_cap_limit"],
    "baseline_days": RUN_DEFAULTS["baseline_days"],
    "pre_flood_days": RUN_DEFAULTS["pre_flood_days"],
    "flood_days": RUN_DEFAULTS["flood_days"],
    "post_flood_days": RUN_DEFAULTS["post_flood_days"],
    "shelter_funding": SERVICE_DEFAULTS["shelter_funding"],
    "healthcare_funding": SERVICE_DEFAULTS["healthcare_funding"],

    "flood_depth_multiplier": MODEL_DEFAULTS["flood_depth_multiplier"],
    "flood_critical_facility_clearance_m": MODEL_DEFAULTS["flood_critical_facility_clearance_m"],
    "flood_onset_speed": MODEL_DEFAULTS["flood_onset_speed"],
    "flood_recession_speed": MODEL_DEFAULTS["flood_recession_speed"],
    "house_flood_thresh_mult": MODEL_DEFAULTS["house_flood_thresh_mult"],
    "biz_flood_thresh_mult": MODEL_DEFAULTS["biz_flood_thresh_mult"],
    "school_flood_thresh_mult": MODEL_DEFAULTS["school_flood_thresh_mult"],
    "house_mold_rate": MODEL_DEFAULTS["house_mold_rate"],
    "business_mold_rate": MODEL_DEFAULTS["business_mold_rate"],
    "stranded_depth_tolerance_mult": MODEL_DEFAULTS["stranded_depth_tolerance_mult"],
    "injury_risk_scale": MODEL_DEFAULTS["injury_risk_scale"],
    "pre_evac_T_gate": MODEL_DEFAULTS["pre_evac_T_gate"],
    "evac_trigger_depth_m": MODEL_DEFAULTS["evac_trigger_depth_m"],
    "home_unsafe_depth_m": MODEL_DEFAULTS["home_unsafe_depth_m"],
    "hours_before_rescue": MODEL_DEFAULTS["hours_before_rescue"],
    "warning_pre_flood_base": MODEL_DEFAULTS["warning_pre_flood_base"],
    "scenario_mode_code": 0,

    # --- linked population mix values (driven by the live panel below) ---
    "male_share_pct": _LINKED_POPULATION_DEFAULTS["gender"]["male_share_pct"],
    "female_share_pct": _LINKED_POPULATION_DEFAULTS["gender"]["female_share_pct"],
    "age_0_14_pct": _LINKED_POPULATION_DEFAULTS["age"]["age_0_14_pct"],
    "age_15_64_pct": _LINKED_POPULATION_DEFAULTS["age"]["age_15_64_pct"],
    "age_65_100_pct": _LINKED_POPULATION_DEFAULTS["age"]["age_65_100_pct"],
    "ethnicity_white_pct": _LINKED_POPULATION_DEFAULTS["ethnicity"]["ethnicity_white_pct"],
    "ethnicity_black_pct": _LINKED_POPULATION_DEFAULTS["ethnicity"]["ethnicity_black_pct"],
    "ethnicity_hispanic_pct": _LINKED_POPULATION_DEFAULTS["ethnicity"]["ethnicity_hispanic_pct"],
    "ethnicity_other_pct": _LINKED_POPULATION_DEFAULTS["ethnicity"]["ethnicity_other_pct"],
    "worldview_hierarchist_pct": _LINKED_POPULATION_DEFAULTS["worldview"]["worldview_hierarchist_pct"],
    "worldview_egalitarian_pct": _LINKED_POPULATION_DEFAULTS["worldview"]["worldview_egalitarian_pct"],
    "worldview_individualist_pct": _LINKED_POPULATION_DEFAULTS["worldview"]["worldview_individualist_pct"],
    "worldview_fatalist_pct": _LINKED_POPULATION_DEFAULTS["worldview"]["worldview_fatalist_pct"],
    "perc_education_people": float(UVALDE_POPULATION_PRESET.get("perc_education_people", 0.89)),

    # --- disease switches ---
    "enable_infectious": 1,
    "enable_stagnant": 1,
    "enable_mold": 1,
    "infectious_seed_start_hour": MODEL_DEFAULTS["infectious_seed_start_hour"],
    "infectious_seed_share": MODEL_DEFAULTS["infectious_seed_share"],
    "infectious_beta_base": MODEL_DEFAULTS["infectious_beta_base"],
    "infectious_gamma": MODEL_DEFAULTS["infectious_gamma"],
    "infectious_waning": MODEL_DEFAULTS["infectious_waning"],
    "infectious_contact_intensity": MODEL_DEFAULTS["infectious_contact_intensity"],
    "infectious_mortality_hazard": MODEL_DEFAULTS["infectious_mortality_hazard"],

    # --- policy levers (opt-in; zero preserves baseline behavior) ---
    "wash_intensity": MODEL_DEFAULTS["wash_intensity"],
    "shelter_distancing_intensity": MODEL_DEFAULTS["shelter_distancing_intensity"],
    "healthcare_surge_factor": MODEL_DEFAULTS["healthcare_surge_factor"],
    "repair_subsidy_intensity": MODEL_DEFAULTS["repair_subsidy_intensity"],
    "house_repair_cost_scale": MODEL_DEFAULTS["house_repair_cost_scale"],
    "risk_communication_intensity": MODEL_DEFAULTS["risk_communication_intensity"],
    "targeted_protection_intensity": MODEL_DEFAULTS["targeted_protection_intensity"],
    "gov_baseline_grant_every_hours": MODEL_DEFAULTS["gov_baseline_grant_every_hours"],

    "damp_half_life_h": MODEL_DEFAULTS["damp_half_life_h"],
    "damp_resilience_effect": MODEL_DEFAULTS["damp_resilience_effect"],
    "damp_done_threshold": MODEL_DEFAULTS["damp_done_threshold"],
    "damp_metric_hours": MODEL_DEFAULTS["damp_metric_hours"],
    "school_repair_cost_multiplier": MODEL_DEFAULTS["school_repair_cost_multiplier"],
    "school_mold_attendance_penalty_rate": MODEL_DEFAULTS["school_mold_attendance_penalty_rate"],
    "mold_symptom_threshold": MODEL_DEFAULTS["mold_symptom_threshold"],
    "mold_hospital_seek_prob": MODEL_DEFAULTS["mold_hospital_seek_prob"],
    "mold_healthcare_cost_multiplier": MODEL_DEFAULTS["mold_healthcare_cost_multiplier"],

    # --- stagnant-pool physics & vector control ---
    "stagnant_half_life_h": MODEL_DEFAULTS["stagnant_half_life_h"],
    "stagnant_influence_m": MODEL_DEFAULTS["stagnant_influence_m"],
    "stagnant_max_spots_per_wave": MODEL_DEFAULTS["stagnant_max_spots_per_wave"],
    "stagnant_area_fraction": MODEL_DEFAULTS["stagnant_area_fraction"],
    "vector_control_intensity": MODEL_DEFAULTS["vector_control_intensity"],
    "stagnant_keep_fraction": MODEL_DEFAULTS["stagnant_keep_fraction"],
    "vector_hospital_seek_prob": MODEL_DEFAULTS["vector_hospital_seek_prob"],
    "vector_exposure_hazard": MODEL_DEFAULTS["vector_exposure_hazard"],
    "healthcare_max_stay_hours": MODEL_DEFAULTS["healthcare_max_stay_hours"],
    "vector_healthcare_cost_multiplier": MODEL_DEFAULTS["vector_healthcare_cost_multiplier"],
    "map_name": STARTUP_MAP_NAME,

    # ---------------- fixed file & CRS parameters ---------------------
    "houses_file":      str(DATA / "processed" / "abm_places.gpkg"),
    "businesses_file":  str(DATA / "processed" / "abm_places.gpkg"),
    "schools_file":     str(DATA / "processed" / "abm_places.gpkg"),
    "shelter_file":     str(DATA / "processed" / "abm_places.gpkg"),
    "healthcare_file":  str(DATA / "processed" / "abm_places.gpkg"),
    "government_file":  str(DATA / "processed" / "abm_places.gpkg"),
    "flood_file":       str(DATA / "uvalde_twdb_scenario5_1in100_flood.geojson"),
    "model_crs":        "EPSG:3857",
    "auto_export_on_finish": True,
    "output_root":      str((ROOT / "outputs" / "serverrun").resolve()),
}

_SCENARIO_CODE_BY_LABEL = SCENARIO_CODE_BY_LABEL
_SCENARIO_LABEL_BY_CODE = SCENARIO_LABEL_BY_CODE
_SCENARIO_NAME_BY_CODE = SCENARIO_NAME_BY_CODE
_DISEASE_FLAG_KEYS = [
    "enable_infectious",
    "enable_stagnant",
    "enable_mold",
]


def _apply_scenario_rules_to_settings(state, activate_compound_default=False):
    new_state = json.loads(json.dumps(state))
    disease = new_state["disease"]
    scenario_code = int(new_state["scenario"]["scenario_mode_code"])
    scenario_name = _SCENARIO_NAME_BY_CODE.get(scenario_code, "compound")

    for key, enabled in scenario_flags(scenario_name).items():
        if key in _DISEASE_FLAG_KEYS:
            disease[key] = int(enabled)
    if activate_compound_default and scenario_name in {"flood_infectious", "compound"}:
        scenario = new_state["scenario"]
        disease["infectious_seed_start_hour"] = infectious_start_hour(
            scenario_name,
            scenario["baseline_days"],
            scenario["pre_flood_days"],
            scenario["flood_days"],
        )

    return new_state

_SETTINGS_DEFAULTS = {
    "scenario": {
        "scenario_mode_code": model_params["scenario_mode_code"],
        "N_persons": model_params["N_persons"],
        "baseline_days": model_params["baseline_days"],
        "pre_flood_days": model_params["pre_flood_days"],
        "flood_days": model_params["flood_days"],
        "post_flood_days": model_params["post_flood_days"],
    },
    "capacity": {
        "shelter_cap_limit": model_params["shelter_cap_limit"],
        "healthcare_cap_limit": model_params["healthcare_cap_limit"],
        "shelter_funding": model_params["shelter_funding"],
        "healthcare_funding": model_params["healthcare_funding"],
    },
    "flood": {
        "flood_depth_multiplier": model_params["flood_depth_multiplier"],
        "flood_onset_speed": model_params["flood_onset_speed"],
        "flood_recession_speed": model_params["flood_recession_speed"],
        "house_flood_thresh_mult": model_params["house_flood_thresh_mult"],
        "biz_flood_thresh_mult": model_params["biz_flood_thresh_mult"],
        "school_flood_thresh_mult": model_params["school_flood_thresh_mult"],
        "house_mold_rate": model_params["house_mold_rate"],
        "business_mold_rate": model_params["business_mold_rate"],
        "evac_trigger_depth_m": model_params["evac_trigger_depth_m"],
        "home_unsafe_depth_m": model_params["home_unsafe_depth_m"],
        "hours_before_rescue": model_params["hours_before_rescue"],
        "warning_pre_flood_base": model_params["warning_pre_flood_base"],
        "stranded_depth_tolerance_mult": model_params["stranded_depth_tolerance_mult"],
        "injury_risk_scale": model_params["injury_risk_scale"],
    },
    "disease": {
        "enable_infectious": model_params["enable_infectious"],
        "enable_stagnant": model_params["enable_stagnant"],
        "enable_mold": model_params["enable_mold"],
        "infectious_seed_start_hour": model_params["infectious_seed_start_hour"],
        "infectious_seed_share": model_params["infectious_seed_share"],
        "infectious_beta_base": model_params["infectious_beta_base"],
        "infectious_gamma": model_params["infectious_gamma"],
        "infectious_waning": model_params["infectious_waning"],
        "infectious_contact_intensity": model_params["infectious_contact_intensity"],
        "infectious_mortality_hazard": model_params["infectious_mortality_hazard"],
        "damp_half_life_h": model_params["damp_half_life_h"],
        "damp_resilience_effect": model_params["damp_resilience_effect"],
        "damp_done_threshold": model_params["damp_done_threshold"],
        "damp_metric_hours": model_params["damp_metric_hours"],
        "school_repair_cost_multiplier": model_params["school_repair_cost_multiplier"],
        "school_mold_attendance_penalty_rate": model_params["school_mold_attendance_penalty_rate"],
        "house_repair_cost_scale": model_params["house_repair_cost_scale"],
        "mold_symptom_threshold": model_params["mold_symptom_threshold"],
        "mold_hospital_seek_prob": model_params["mold_hospital_seek_prob"],
        "mold_healthcare_cost_multiplier": model_params["mold_healthcare_cost_multiplier"],
        "stagnant_half_life_h": model_params["stagnant_half_life_h"],
        "stagnant_influence_m": model_params["stagnant_influence_m"],
        "stagnant_keep_fraction": model_params["stagnant_keep_fraction"],
        "vector_hospital_seek_prob": model_params["vector_hospital_seek_prob"],
        "vector_exposure_hazard": model_params["vector_exposure_hazard"],
        "healthcare_max_stay_hours": model_params["healthcare_max_stay_hours"],
        "vector_healthcare_cost_multiplier": model_params["vector_healthcare_cost_multiplier"],
    },
    "policy": {
        "wash_intensity": model_params["wash_intensity"],
        "shelter_distancing_intensity": model_params["shelter_distancing_intensity"],
        "healthcare_surge_factor": model_params["healthcare_surge_factor"],
        "repair_subsidy_intensity": model_params["repair_subsidy_intensity"],
        "risk_communication_intensity": model_params["risk_communication_intensity"],
        "targeted_protection_intensity": model_params["targeted_protection_intensity"],
        "vector_control_intensity": model_params["vector_control_intensity"],
        "gov_baseline_grant_every_hours": model_params["gov_baseline_grant_every_hours"],
    },
}
_settings_state = solara.reactive(json.loads(json.dumps(_SETTINGS_DEFAULTS)))
_settings_state.value = _apply_scenario_rules_to_settings(_settings_state.value, activate_compound_default=True)
_apply_startup_map_to_model_params()
_last_model_hours_seen = solara.reactive(None)
_pending_pre_run_rebuild = solara.reactive(False)
_last_settings_change_ts = solara.reactive(0.0)
_last_pre_run_rebuild_ts = solara.reactive(0.0)
_PRE_RUN_REBUILD_IDLE_SECONDS = 0.75
_PRE_RUN_REBUILD_MIN_INTERVAL_SECONDS = 1.0

# -------------------------------------------------------------------- #
# 5 · Plot helpers – identical logical grouping to the old server      #
# -------------------------------------------------------------------- #

# ---------- Legacy helper (still works with Mesa DataCollector) ------
def plot(lines: dict):
    # lines = { "<DataCollector series name>": "<css_color>" }
    return make_plot_component(lines)

# Small cache keyed by absolute path so each new run gets its own cache
_PANEL_CACHE = {}

def _get_panel_df_for_model(model):
    """Read this run's step_panel.csv via the model's collector path; memoized by mtime."""
    try:
        path = getattr(getattr(model, "collect", None), "_step_panel_path", None)
    except Exception:
        path = None
    if not path:
        path = (ROOT / "outputs" / "serverrun" / "step_panel.csv")
    path = Path(path).resolve()

    cache = _PANEL_CACHE.get(str(path))
    try:
        st = path.stat()
    except FileNotFoundError:
        _PANEL_CACHE[str(path)] = {"mtime_ns": None, "df": pd.DataFrame()}
        return _PANEL_CACHE[str(path)]["df"]

    if (not cache) or cache["mtime_ns"] != st.st_mtime_ns:
        try:
            df = pd.read_csv(path)
        except Exception:
            df = cache["df"] if cache else pd.DataFrame()
        _PANEL_CACHE[str(path)] = {"mtime_ns": st.st_mtime_ns, "df": df}
    return _PANEL_CACHE[str(path)]["df"]

def _line(ax, df, xcol, ycol, label):
    if xcol in df.columns and ycol in df.columns:
        ax.plot(df[xcol], df[ycol], label=label)

def _maybe_text(ax, ok, msg="Waiting for data…"):
    if not ok:
        ax.text(0.5, 0.5, msg, ha="center", va="center", transform=ax.transAxes)

# ---------- Keep two simple legacy plots (Mesa DataCollector) --------

# Population states — % of population
dc_persons_pct_plot = make_plot_component({
    "stranded_pct":   "red",
    "injured_pct":    "orange",
    "in_shelter_pct": "blue",
    "evacuated_pct":  "green",
})

# Capacity stress — % of capacity
dc_capacity_util_plot = make_plot_component({
    "shelter_util_pct": "blue",
    "hc_util_pct":      "orange",
})

# Capacity backlog — % of capacity (optional but insightful)
dc_capacity_backlog_plot = make_plot_component({
    "shelter_backlog_pct": "lightblue",
    "hc_backlog_pct":      "gold",
})

# Businesses — system health (% of units)
dc_business_pct_plot = make_plot_component({
    "biz_open_pct":    "green",
    "biz_flooded_pct": "grey",
    "biz_ever_flooded_pct": "darkgrey",
})

# Housing — habitability & flooding (% of units)
dc_housing_pct_plot = make_plot_component({
    "house_hab_pct":     "green",
    "house_flooded_pct": "grey",
    "house_ever_flooded_pct": "darkgrey",
})

# Economy levels and activity (avoid cumulative-only curves)
dc_economy_vs_gdp_plot = make_plot_component({
    "biz_wealth_vs_gdp_pct": "teal",
    "biz_open_pct":          "green",
    "person_income_index_pct": "navy",
})

# Fiscal per-capita (stock + hourly flows)
dc_fiscal_percap_plot = make_plot_component({
    "gov_balance_per_capita": "black",
    "taxes_per_capita_hr":    "teal",
    "grants_per_capita_hr":   "magenta",
})

# Schools — access rates (%)
dc_schools_pct_plot = make_plot_component({
    "attendance_rate_pct": "blue",
    "school_open_now_pct": "green",
    "school_flooded_pct":  "orange",
})

# Schools — cumulative burdens (absolute totals; separate panel)
dc_schools_cum_plot = make_plot_component({
    "student_hours_lost_sum": "red",
    "attendance_hours_sum":   "navy",
})

# Exposure (separate physical units)
dc_exposure_depth_plot = make_plot_component({
    "home_depth_mean_m": "navy",
})
# dc_exposure_window_plot = make_plot_component({
#     "hours_to_deadline": "black",
# })

# Disease prevalence (% of population)
dc_disease_prev_plot = make_plot_component({
    "inf_prev_pct":     "crimson",
    "vector_symp_pct":  "darkgreen",
    "mold_symp_pct":    "slateblue",
})

# Exposure & housing burden
dc_exposure_disease_plot = make_plot_component({
    "near_vectorborne_pct":  "olive",
    "house_mold_mean":    "indigo",
    "house_damp_geH_pct": "brown",
})

# Hourly incidence (appears only if module enabled; NaN otherwise)
dc_disease_incidence_plot = make_plot_component({
    "vector_incidence_hr": "darkgreen",
    "mold_incidence_hr":   "slateblue",
})

# Compound and equity burden
dc_compound_equity_plot = make_plot_component({
    "compound_burden_pct": "firebrick",
    "low_income_disease_pct": "purple",
    "high_vuln_disease_pct": "black",
    "inequity_gap_low_vs_high_pct": "teal",
})

# Damp diagnostic
dc_damp_diag_plot = make_plot_component({
    "house_damp_active_pct": "sienna",
})

dc_hazard_debug_plot = make_plot_component({
    "hazard_max_depth_m":  "firebrick",
    "hazard_flooded_area": "steelblue",
})

# Additional plots, all backed by DataCollector reporters
dc_evac_timing_plot = make_plot_component({
    "decision_evac_pct": "purple",
    "evacuated_pct": "green",
})

dc_response_choices_plot = make_plot_component({
    "decision_prepare_pct": "teal",
    "decision_shelter_in_place_pct": "orange",
    "decision_delay_return_pct": "slateblue",
})

dc_healthcare_backpressure_plot = make_plot_component({
    "hc_util_pct": "orange",
    "hc_backlog_pct": "firebrick",
})

dc_fiscal_pressure_plot = make_plot_component({
    "gov_balance_per_capita": "black",
    "taxes_per_capita_hr": "teal",
    "grants_per_capita_hr": "magenta",
})

dc_government_treasury_plot = make_plot_component({
    "gov_wealth": "black",
    "gov_wealth_vs_gdp_pct": "gray",
    "taxes_per_capita_hr": "teal",
    "grants_per_capita_hr": "magenta",
})

dc_recovery_progress_plot = make_plot_component({
    "house_hab_pct": "green",
    "school_open_now_pct": "blue",
    "biz_open_pct": "purple",
})

dc_normal_activity_plot = make_plot_component({
    "attendance_rate_pct": "blue",
    "work_attendance_pct": "green",
    "biz_staffed_pct": "purple",
    "normal_activity_pct": "black",
})

dc_qol_plot = make_plot_component({
    "qol_mean_pct": "black",
    "qol_low_income_pct": "purple",
    "qol_seniors_pct": "orange",
    "qol_adults_pct": "gold",
    "qol_children_pct": "teal",
})

dc_qol_worldview_plot = make_plot_component({
    "qol_hierarchist_pct": "blue",
    "qol_egalitarian_pct": "magenta",
    "qol_individualist_pct": "darkcyan",
    "qol_fatalist_pct": "red",
})

dc_qol_ethnicity_plot = make_plot_component({
    "qol_white_pct": "slategray",
    "qol_black_pct": "black",
    "qol_hispanic_pct": "brown",
    "qol_other_pct": "purple",
})

dc_qol_age_plot = make_plot_component({
    "qol_children_pct": "teal",
    "qol_adults_pct": "gold",
    "qol_seniors_pct": "orange",
})

dc_qol_wealth_plot = make_plot_component({
    "qol_low_income_pct": "purple",
    "qol_middle_income_pct": "steelblue",
    "qol_upper_middle_pct": "seagreen",
    "qol_upper_pct": "black",
})

dc_population_stability_plot = make_plot_component({
    "dead_pct": "black",
    "evacuated_pct": "forestgreen",
    "stranded_pct": "red",
    "in_shelter_pct": "blue",
    "in_healthcare_pct": "orange",
})

dc_population_stability_infectious_plot = make_plot_component({
    "dead_pct": "black",
    "inf_prev_pct": "crimson",
    "in_healthcare_pct": "orange",
})

dc_population_stability_compound_plot = make_plot_component({
    "dead_pct": "black",
    "evacuated_pct": "forestgreen",
    "stranded_pct": "red",
    "in_shelter_pct": "blue",
    "in_healthcare_pct": "orange",
    "inf_prev_pct": "crimson",
})

dc_attendance_dynamics_plot = make_plot_component({
    "work_attendance_workhours_pct": "green",
    "school_attendance_scheduled_pct": "blue",
}, post_process=_fill_nan_lines_with_zero)

dc_infrastructure_plot = make_plot_component({
    "house_hab_pct": "green",
    "biz_open_pct": "purple",
    "school_open_now_pct": "blue",
}, post_process=_fill_nan_lines_with_zero)

dc_structural_impact_timeline_plot = make_plot_component({
    "house_flooded_pct": "firebrick",
    "biz_flooded_pct": "darkorange",
    "school_flooded_pct": "rebeccapurple",
    "house_molded_pct": "seagreen",
    "biz_molded_pct": "teal",
    "school_molded_pct": "mediumpurple",
}, y_label="Structures Affected (%)")

dc_finance_wealth_plot = make_plot_component({
    "biz_wealth_total": "teal",
    "gov_wealth": "black",
    "shelter_wealth": "blue",
    "hc_wealth": "orange",
    "person_wealth_total_scaled": "navy",
}, post_process=_finance_plot_post_process)

dc_finance_wealth_infectious_plot = make_plot_component({
    "gov_wealth": "black",
    "hc_wealth": "orange",
    "person_wealth_total_scaled": "navy",
}, post_process=_finance_plot_post_process)

dc_impact_expenses_plot = make_plot_component({
    "evacuation_expense_total": "forestgreen",
    "house_repair_expense_total": "saddlebrown",
    "business_repair_expense_total": "purple",
    "healthcare_expense_flood_total": "steelblue",
    "healthcare_expense_mold_total": "firebrick",
    "healthcare_expense_vectorborne_total": "darkgreen",
    "healthcare_expense_infectious_total": "crimson",
}, post_process=_impact_expenses_post_process)

dc_impact_expenses_infectious_plot = make_plot_component({
    "healthcare_expense_infectious_total": "crimson",
}, post_process=_impact_expenses_post_process)

dc_routine_by_hour_plot = make_plot_component({
    "work_attendance_workhours_pct": "green",
    "school_attendance_scheduled_pct": "blue",
    "leisure_attendance_pct": "purple",
    "shopping_attendance_pct": "black",
}, post_process=_fill_nan_lines_with_zero)

dc_shelter_load_plot = make_plot_component({
    "shelter_1_util_pct": "navy",
    "shelter_1_backlog_pct": "cornflowerblue",
    "shelter_2_util_pct": "darkgreen",
    "shelter_2_backlog_pct": "yellowgreen",
})

dc_psychology_plot = make_plot_component({
    "mean_threat": "firebrick",
    "mean_coping": "teal",
    "mean_self_efficacy": "navy",
    "mean_response_efficacy": "purple",
})

dc_affected_population_plot = make_plot_component({
    "affected_evacuated_pct": "forestgreen",
    "affected_stranded_unique_pct": "red",
    "affected_sheltered_unique_pct": "blue",
    "affected_healthcare_unique_pct": "darkorange",
    "affected_injured_unique_pct": "orange",
    "dead_pct": "black",
    "affected_mold_pct": "slateblue",
    "affected_vectorborne_pct": "darkgreen",
    "affected_infectious_pct": "crimson",
})

dc_affected_population_baseline_plot = make_plot_component({
    "dead_pct": "black",
})

dc_affected_population_infectious_plot = make_plot_component({
    "in_healthcare_pct": "orange",
    "inf_prev_pct": "crimson",
    "dead_pct": "black",
})

dc_service_funding_queue_plot = make_plot_component({
    "shelter_util_pct": "blue",
    "hc_util_pct": "orange",
    "shelter_wealth_per_cap": "purple",
    "hc_wealth_per_cap": "black",
})

dc_vectorborne_exposure_plot = make_plot_component({
    "near_vectorborne_pct": "teal",
    "house_damp_geH_pct": "brown",
})


# ---------- Master list handed to SolaraViz --------------------------
ALL_PLOTS = [
    dc_persons_pct_plot,
    dc_capacity_util_plot,
    dc_capacity_backlog_plot,
    dc_business_pct_plot,
    dc_housing_pct_plot,
    dc_economy_vs_gdp_plot,
    dc_fiscal_percap_plot,
    dc_schools_pct_plot,
    dc_schools_cum_plot,
    dc_exposure_depth_plot,
    dc_disease_prev_plot,
    dc_exposure_disease_plot,
    dc_disease_incidence_plot,
    dc_compound_equity_plot,
    dc_damp_diag_plot,
    dc_evac_timing_plot,
    dc_response_choices_plot,
    dc_healthcare_backpressure_plot,
    dc_fiscal_pressure_plot,
    dc_government_treasury_plot,
    dc_recovery_progress_plot,
    dc_vectorborne_exposure_plot,
    dc_normal_activity_plot,
    dc_qol_plot,
    dc_qol_worldview_plot,
    dc_qol_ethnicity_plot,
    dc_service_funding_queue_plot,
]

_PLOT_COMPONENTS = {
    "Local flood depth": dc_exposure_depth_plot,
    "Evacuation timing": dc_evac_timing_plot,
    "Response choices": dc_response_choices_plot,
    "Population disruption and evacuation": dc_persons_pct_plot,
    "Shelter and healthcare stress": dc_capacity_util_plot,
    "Capacity backlog": dc_capacity_backlog_plot,
    "Healthcare load": dc_healthcare_backpressure_plot,
    "Housing recovery": dc_housing_pct_plot,
    "Business activity": dc_business_pct_plot,
    "Economic output vs GDP": dc_economy_vs_gdp_plot,
    "Public finance per capita": dc_fiscal_pressure_plot,
    "Government treasury": dc_government_treasury_plot,
    "Education activity": dc_schools_pct_plot,
    "Normal system activity": dc_normal_activity_plot,
    "Vectorborne exposure risk": dc_vectorborne_exposure_plot,
    "Active damp burden": dc_damp_diag_plot,
    "Disease exposure pathways": dc_exposure_disease_plot,
    "Disease prevalence": dc_disease_prev_plot,
    "Disease incidence over time": dc_disease_incidence_plot,
    "Recovery progress": dc_recovery_progress_plot,
    "Compound and equity burden": dc_compound_equity_plot,
    "Quality of life": dc_qol_plot,
    "Quality of life by worldview": dc_qol_worldview_plot,
    "Quality of life by ethnicity": dc_qol_ethnicity_plot,
    "Service funding and queue pressure": dc_service_funding_queue_plot,
    "Population stability": dc_population_stability_plot,
    "Attendance": dc_attendance_dynamics_plot,
    "Infrastructure": dc_infrastructure_plot,
    "Structural impact timeline": dc_structural_impact_timeline_plot,
    "Finance": dc_finance_wealth_plot,
    "Impact expenses": dc_impact_expenses_plot,
    "Quality of life by age": dc_qol_age_plot,
    "Quality of life by wealth": dc_qol_wealth_plot,
    "Routine by hour": dc_routine_by_hour_plot,
    "Shelter load": dc_shelter_load_plot,
    "Psychology": dc_psychology_plot,
    "Affected population": dc_affected_population_plot,
}
_BASELINE_CURATED_LABELS = [
    "Population stability",
    "Attendance",
    "Infrastructure",
    "Finance",
    "Routine by hour",
]

_FLOOD_CURATED_LABELS = [
    "Population stability",
    "Attendance",
    "Infrastructure",
    "Structural impact timeline",
    "Finance",
    "Impact expenses",
    "Routine by hour",
    "Healthcare load",
    "Shelter load",
    "Affected population",
    "Psychology",
    "Quality of life by age",
    "Quality of life by wealth",
    "Quality of life by worldview",
    "Quality of life by ethnicity",
]

_SCENARIO_CURATED_LABELS = {
    "baseline": list(_BASELINE_CURATED_LABELS),
    "infectious_disease": [
        "Population stability",
        "Attendance",
        "Finance",
        "Impact expenses",
        "Routine by hour",
        "Healthcare load",
        "Affected population",
        "Psychology",
        "Quality of life by age",
        "Quality of life by wealth",
        "Quality of life by worldview",
        "Quality of life by ethnicity",
    ],
    "flood_only": [label for label in _FLOOD_CURATED_LABELS if label not in {"Attendance", "Infrastructure"}],
    "flood_mold": [label for label in _FLOOD_CURATED_LABELS if label not in {"Attendance", "Infrastructure"}],
    "flood_vectorborne": list(_FLOOD_CURATED_LABELS),
    "flood_mold_vectorborne": list(_FLOOD_CURATED_LABELS),
    "flood_infectious": list(_FLOOD_CURATED_LABELS),
    "compound": list(_FLOOD_CURATED_LABELS),
}

_DEFAULT_VISIBLE_PLOTS = list(_BASELINE_CURATED_LABELS)
_visible_plot_state = solara.reactive(list(_DEFAULT_VISIBLE_PLOTS))
model_state = solara.reactive(None)


def _default_visible_plots_for_scenario(scenario_name: str):
    return list(_SCENARIO_CURATED_LABELS.get(scenario_name, _FLOOD_CURATED_LABELS))


def _plot_is_available(label, settings):
    scenario_name = _SCENARIO_NAME_BY_CODE.get(int(settings["scenario"]["scenario_mode_code"]), "compound")
    allowed = _SCENARIO_CURATED_LABELS.get(scenario_name, _FLOOD_CURATED_LABELS)
    return label in allowed


def _available_plot_labels(settings):
    scenario_name = _SCENARIO_NAME_BY_CODE.get(int(settings["scenario"]["scenario_mode_code"]), "compound")
    ordered = _SCENARIO_CURATED_LABELS.get(scenario_name, _FLOOD_CURATED_LABELS)
    return [label for label in ordered if label in _PLOT_COMPONENTS and _plot_is_available(label, settings)]

def _sync_population_mix_to_model_params(state=None):
    state = state or _population_mix_state.value
    for group_vals in state.values():
        for key, value in group_vals.items():
            model_params[key] = float(value)


def _sync_settings_to_model_params(state=None):
    state = _apply_scenario_rules_to_settings(state or _settings_state.value)
    for group_vals in state.values():
        for key, value in group_vals.items():
            model_params[key] = value


def _serverrun_model_kwargs() -> dict:
    """Build one interactive run from the configured model defaults."""
    kwargs = dict(model_params)
    kwargs["random_seed"] = int(np.random.default_rng().integers(0, 2**31 - 1))
    # Pass the resolved name explicitly. Model's legacy numeric scenario codes
    # differ from the Serverrun UI codes, so forwarding only the integer can
    # silently turn Flood vectorborne into Compound.
    scenario_code = int(model_params.get("scenario_mode_code", 0) or 0)
    scenario_name = _SCENARIO_NAME_BY_CODE.get(scenario_code, "compound")
    kwargs["scenario_mode"] = scenario_name
    flags = scenario_flags(scenario_name)
    kwargs["enable_flood"] = int(flags.get("enable_flood", False))
    kwargs["enable_infectious"] = int(flags.get("enable_infectious", False))
    kwargs["enable_stagnant"] = int(flags.get("enable_stagnant", False))
    kwargs["enable_mold"] = int(flags.get("enable_mold", False))
    kwargs["infectious_seed_start_hour"] = infectious_start_hour(
        scenario_name,
        kwargs["baseline_days"],
        kwargs["pre_flood_days"],
        kwargs["flood_days"],
    )
    return kwargs


def _reset_ui_controls_to_defaults(rebuild_model: bool = False):
    _population_mix_state.value = json.loads(json.dumps(_LINKED_POPULATION_DEFAULTS))
    _settings_state.value = _apply_scenario_rules_to_settings(
        json.loads(json.dumps(_SETTINGS_DEFAULTS)),
        activate_compound_default=True,
    )
    _apply_startup_map_to_model_params()
    _sync_settings_to_model_params(_settings_state.value)
    _sync_population_mix_to_model_params(_population_mix_state.value)
    scenario_name = _SCENARIO_NAME_BY_CODE.get(int(_settings_state.value["scenario"]["scenario_mode_code"]), "compound")
    _visible_plot_state.value = [
        label for label in _default_visible_plots_for_scenario(scenario_name)
        if _plot_is_available(label, _settings_state.value)
    ]
    if rebuild_model:
        try:
            model_state.value = Model(**_serverrun_model_kwargs())
            _pending_pre_run_rebuild.value = False
            _last_pre_run_rebuild_ts.value = time.time()
        except Exception:
            pass


def _ensure_model_state():
    if model_state.value is None:
        _sync_settings_to_model_params(_settings_state.value)
        _sync_population_mix_to_model_params(_population_mix_state.value)
        model_state.value = Model(**_serverrun_model_kwargs())
    return model_state.value


@solara.component
def ModelSettingsPanel(model):
    settings = _settings_state.value
    population = _population_mix_state.value
    control_profile = _map_ui_control_profile(model_params.get("map_name", STARTUP_MAP_NAME))
    population_controls = control_profile["population"]
    capacity_controls = control_profile["capacity"]
    _sync_settings_to_model_params(settings)
    _sync_population_mix_to_model_params(population)

    # SolaraViz reset sets model hours back to zero; mirror that by restoring UI defaults.
    current_hours = int(getattr(model, "hours", 0) or 0)
    prev_hours = _last_model_hours_seen.value
    if prev_hours is None:
        _last_model_hours_seen.value = current_hours
    elif current_hours == 0 and int(prev_hours or 0) > 0:
        _reset_ui_controls_to_defaults(rebuild_model=True)
        _last_model_hours_seen.value = 0
        settings = _settings_state.value
        population = _population_mix_state.value
    elif current_hours != int(prev_hours or 0):
        _last_model_hours_seen.value = current_hours

    # Rebuild only once after slider activity settles while still pre-run.
    if current_hours == 0 and bool(_pending_pre_run_rebuild.value):
        now_ts = time.time()
        idle_for = now_ts - float(_last_settings_change_ts.value or 0.0)
        since_last_rebuild = now_ts - float(_last_pre_run_rebuild_ts.value or 0.0)
        if idle_for >= _PRE_RUN_REBUILD_IDLE_SECONDS and since_last_rebuild >= _PRE_RUN_REBUILD_MIN_INTERVAL_SECONDS:
            try:
                model_state.value = Model(**_serverrun_model_kwargs())
                _pending_pre_run_rebuild.value = False
                _last_pre_run_rebuild_ts.value = now_ts
            except Exception:
                pass

    def update_setting(group_name, key, value):
        new_state = json.loads(json.dumps(_settings_state.value))
        new_state[group_name][key] = value
        if group_name == "scenario" and key == "scenario_mode_code":
            new_state = _apply_scenario_rules_to_settings(new_state, activate_compound_default=True)
            selected_scenario_name = _SCENARIO_NAME_BY_CODE.get(int(new_state["scenario"]["scenario_mode_code"]), "compound")
            _visible_plot_state.value = [
                label for label in _default_visible_plots_for_scenario(selected_scenario_name)
                if _plot_is_available(label, new_state)
            ]
        else:
            new_state = _apply_scenario_rules_to_settings(new_state)
        _settings_state.value = new_state
        _sync_settings_to_model_params(new_state)
        _visible_plot_state.value = [label for label in _visible_plot_state.value if _plot_is_available(label, new_state)]
        if group_name == "scenario" and key in {"scenario_mode_code", "N_persons"}:
            try:
                model_state.value = Model(**_serverrun_model_kwargs())
                _pending_pre_run_rebuild.value = False
                _last_pre_run_rebuild_ts.value = time.time()
                return
            except Exception:
                pass
        try:
            if int(getattr(model_state.value, "hours", 0) or 0) == 0:
                _pending_pre_run_rebuild.value = True
                _last_settings_change_ts.value = time.time()
        except Exception:
            pass

    def update_group(group_name, key, value):
        current_state = _population_mix_state.value
        current_val = float(current_state[group_name][key])
        incoming = float(value)
        # Ignore no-op echo events from reactive updates to prevent slider ping-pong.
        if abs(current_val - incoming) < 0.5:
            return
        new_state = json.loads(json.dumps(_population_mix_state.value))
        new_state[group_name] = _rebalance_group(new_state[group_name], key, value)
        _population_mix_state.value = new_state
        _sync_population_mix_to_model_params(new_state)
        try:
            if int(getattr(model_state.value, "hours", 0) or 0) == 0:
                _pending_pre_run_rebuild.value = True
                _last_settings_change_ts.value = time.time()
        except Exception:
            pass

    current_scenario_label = _SCENARIO_LABEL_BY_CODE.get(
        int(settings["scenario"]["scenario_mode_code"]),
        "Compound: Flood and All Diseases",
    )
    current_scenario_name = _SCENARIO_NAME_BY_CODE.get(
        int(settings["scenario"]["scenario_mode_code"]),
        "compound",
    )

    with solara.Card(title="Model settings", margin=0, style={
        "width": "100%",
        "background": "rgba(255,255,255,0.97)",
    }):
        with solara.Columns([1, 1, 1], wrap=True, style={"alignItems": "stretch"}):
            with solara.Column(gap="10px"):
                with solara.Card(title="Scenario", margin=0):
                    solara.Markdown("Choose one scenario mode:")
                    solara.ToggleButtonsSingle(
                        value=current_scenario_label,
                        values=list(_SCENARIO_CODE_BY_LABEL.keys()),
                        on_value=lambda label: update_setting("scenario", "scenario_mode_code", _SCENARIO_CODE_BY_LABEL[label]),
                        dense=True,
                        mandatory=True,
                        style="flex-wrap: wrap; width: 100%;",
                    )

                with solara.Card(title="Population composition", margin=0):
                    solara.SliderInt(
                        "Population size",
                        value=int(settings["scenario"]["N_persons"]),
                        min=int(population_controls["min"]),
                        max=int(population_controls["max"]),
                        step=int(population_controls["step"]),
                        on_value=lambda v: update_setting("scenario", "N_persons", int(v)),
                    )
                    solara.Markdown("**Gender mix**")
                    solara.SliderFloat("Male population (%)", value=population["gender"]["male_share_pct"], min=0, max=100, step=1, on_value=lambda v: update_group("gender", "male_share_pct", v))
                    solara.SliderFloat("Female population (%)", value=population["gender"]["female_share_pct"], min=0, max=100, step=1, on_value=lambda v: update_group("gender", "female_share_pct", v))
                    solara.Text(f"Gender total: {round(sum(population['gender'].values()), 1)}%")
                    solara.Markdown("**Age mix**")
                    solara.SliderFloat("Age 0-14 %", value=population["age"]["age_0_14_pct"], min=0, max=100, step=1, on_value=lambda v: update_group("age", "age_0_14_pct", v))
                    solara.SliderFloat("Age 15-64 %", value=population["age"]["age_15_64_pct"], min=0, max=100, step=1, on_value=lambda v: update_group("age", "age_15_64_pct", v))
                    solara.SliderFloat("Age 65+ %", value=population["age"]["age_65_100_pct"], min=0, max=100, step=1, on_value=lambda v: update_group("age", "age_65_100_pct", v))
                    solara.Text(f"Age total: {round(sum(population['age'].values()), 1)}%")
                    solara.Markdown("**Ethnicity mix**")
                    solara.SliderFloat("White %", value=population["ethnicity"]["ethnicity_white_pct"], min=0, max=100, step=1, on_value=lambda v: update_group("ethnicity", "ethnicity_white_pct", v))
                    solara.SliderFloat("Black %", value=population["ethnicity"]["ethnicity_black_pct"], min=0, max=100, step=1, on_value=lambda v: update_group("ethnicity", "ethnicity_black_pct", v))
                    solara.SliderFloat("Hispanic %", value=population["ethnicity"]["ethnicity_hispanic_pct"], min=0, max=100, step=1, on_value=lambda v: update_group("ethnicity", "ethnicity_hispanic_pct", v))
                    solara.SliderFloat("Other %", value=population["ethnicity"]["ethnicity_other_pct"], min=0, max=100, step=1, on_value=lambda v: update_group("ethnicity", "ethnicity_other_pct", v))
                    solara.Text(f"Ethnicity total: {round(sum(population['ethnicity'].values()), 1)}%")
                    solara.Markdown("**Worldview mix**")
                    solara.SliderFloat("Hierarchist %", value=population["worldview"]["worldview_hierarchist_pct"], min=0, max=100, step=1, on_value=lambda v: update_group("worldview", "worldview_hierarchist_pct", v))
                    solara.SliderFloat("Egalitarian %", value=population["worldview"]["worldview_egalitarian_pct"], min=0, max=100, step=1, on_value=lambda v: update_group("worldview", "worldview_egalitarian_pct", v))
                    solara.SliderFloat("Individualist %", value=population["worldview"]["worldview_individualist_pct"], min=0, max=100, step=1, on_value=lambda v: update_group("worldview", "worldview_individualist_pct", v))
                    solara.SliderFloat("Fatalist %", value=population["worldview"]["worldview_fatalist_pct"], min=0, max=100, step=1, on_value=lambda v: update_group("worldview", "worldview_fatalist_pct", v))
                    solara.Text(f"Worldview total: {round(sum(population['worldview'].values()), 1)}%")

                with solara.Card(title="Capacity and services", margin=0):
                    if current_scenario_name == "baseline":
                        solara.Markdown("Capacity and service controls are disabled for this scenario.")
                    else:
                        solara.SliderFloat("Shelter capacity (% of population)", value=float(settings["capacity"]["shelter_cap_limit"]), min=float(capacity_controls["shelter_cap_min"]), max=float(capacity_controls["shelter_cap_max"]), step=float(capacity_controls["shelter_cap_step"]), on_value=lambda v: update_setting("capacity", "shelter_cap_limit", float(v)))
                        solara.SliderFloat("Healthcare capacity (% of population)", value=float(settings["capacity"]["healthcare_cap_limit"]), min=float(capacity_controls["healthcare_cap_min"]), max=float(capacity_controls["healthcare_cap_max"]), step=float(capacity_controls["healthcare_cap_step"]), on_value=lambda v: update_setting("capacity", "healthcare_cap_limit", float(v)))
                        solara.SliderInt("Shelter funding", value=int(settings["capacity"]["shelter_funding"]), min=int(capacity_controls["shelter_funding_min"]), max=int(capacity_controls["shelter_funding_max"]), step=int(capacity_controls["shelter_funding_step"]), on_value=lambda v: update_setting("capacity", "shelter_funding", int(v)))
                        solara.SliderInt("Healthcare funding", value=int(settings["capacity"]["healthcare_funding"]), min=int(capacity_controls["healthcare_funding_min"]), max=int(capacity_controls["healthcare_funding_max"]), step=int(capacity_controls["healthcare_funding_step"]), on_value=lambda v: update_setting("capacity", "healthcare_funding", int(v)))

                
            with solara.Column(gap="10px"):
                with solara.Card(title="Flood context", margin=0):
                    if current_scenario_name in {"baseline", "infectious_disease"}:
                        solara.Markdown("Flood context controls are disabled for this scenario.")
                    else:
                        solara.SliderInt("Baseline days", value=int(settings["scenario"]["baseline_days"]), min=0, max=90, step=1, on_value=lambda v: update_setting("scenario", "baseline_days", int(v)))
                        solara.SliderInt("Pre-flood warning days", value=int(settings["scenario"]["pre_flood_days"]), min=0, max=90, step=1, on_value=lambda v: update_setting("scenario", "pre_flood_days", int(v)))
                        solara.SliderInt("Flood days", value=int(settings["scenario"]["flood_days"]), min=3, max=30, step=1, on_value=lambda v: update_setting("scenario", "flood_days", int(v)))
                        solara.SliderInt("Post flood days", value=int(settings["scenario"]["post_flood_days"]), min=0, max=90, step=1, on_value=lambda v: update_setting("scenario", "post_flood_days", int(v)))
                        solara.SliderFloat("Flood depth", value=float(settings["flood"]["flood_depth_multiplier"]), min=0.1, max=6.0, step=0.1, on_value=lambda v: update_setting("flood", "flood_depth_multiplier", float(v)))
                        solara.SliderFloat("Flood onset speed", value=float(settings["flood"]["flood_onset_speed"]), min=0.5, max=2.0, step=0.05, on_value=lambda v: update_setting("flood", "flood_onset_speed", float(v)))
                        solara.SliderFloat("Flood recession speed", value=float(settings["flood"]["flood_recession_speed"]), min=0.5, max=2.0, step=0.05, on_value=lambda v: update_setting("flood", "flood_recession_speed", float(v)))
                        solara.Markdown("**Structures**")
                        solara.SliderFloat("House flood sensitivity", value=float(settings["flood"]["house_flood_thresh_mult"]), min=0.2, max=2.0, step=0.05, on_value=lambda v: update_setting("flood", "house_flood_thresh_mult", float(v)))
                        solara.SliderFloat("Business flood sensitivity", value=float(settings["flood"]["biz_flood_thresh_mult"]), min=0.2, max=2.0, step=0.05, on_value=lambda v: update_setting("flood", "biz_flood_thresh_mult", float(v)))
                        solara.SliderFloat("School flood sensitivity", value=float(settings["flood"]["school_flood_thresh_mult"]), min=0.2, max=2.0, step=0.05, on_value=lambda v: update_setting("flood", "school_flood_thresh_mult", float(v)))
                        solara.Markdown("**Person effects**")
                        solara.SliderFloat("Stranding tolerance", value=float(settings["flood"]["stranded_depth_tolerance_mult"]), min=0.25, max=1.5, step=0.05, on_value=lambda v: update_setting("flood", "stranded_depth_tolerance_mult", float(v)))
                        solara.SliderFloat("Injury risk", value=float(settings["flood"]["injury_risk_scale"]), min=0.25, max=3.0, step=0.05, on_value=lambda v: update_setting("flood", "injury_risk_scale", float(v)))
                        solara.SliderInt("Rescue latency in hours", value=int(settings["flood"]["hours_before_rescue"]), min=0, max=24, step=1, on_value=lambda v: update_setting("flood", "hours_before_rescue", int(v)))
                        solara.SliderFloat("Official warning strength", value=float(settings["flood"]["warning_pre_flood_base"]), min=0.0, max=1.0, step=0.05, on_value=lambda v: update_setting("flood", "warning_pre_flood_base", float(v)))
                        solara.SliderFloat("Water depth where evacuation becomes more likely", value=float(settings["flood"]["evac_trigger_depth_m"]), min=0.05, max=1.0, step=0.05, on_value=lambda v: update_setting("flood", "evac_trigger_depth_m", float(v)))
                        solara.SliderFloat("Home unsafe depth in meters", value=float(settings["flood"]["home_unsafe_depth_m"]), min=0.05, max=1.0, step=0.05, on_value=lambda v: update_setting("flood", "home_unsafe_depth_m", float(v)))

                with solara.Card(title="Mold context", margin=0):
                    mold_capable_scenario = current_scenario_name in {"flood_mold", "flood_mold_vectorborne", "compound"}
                    if not mold_capable_scenario:
                        solara.Markdown("Mold context controls are disabled for this scenario.")
                    else:
                        solara.Markdown("**Structure effects**")
                        solara.Markdown("Flood depth, dampness duration, drying, building resilience, household resources, and symptom severity generate mold outcomes.")
                        solara.SliderFloat("Molded houses (% of eligible flooded houses)", value=float(settings["flood"]["house_mold_rate"]) * 100.0, min=0.0, max=100.0, step=5.0, on_value=lambda v: update_setting("flood", "house_mold_rate", float(v) / 100.0))
                        solara.SliderFloat("Molded businesses (% of eligible flooded businesses)", value=float(settings["flood"]["business_mold_rate"]) * 100.0, min=0.0, max=100.0, step=5.0, on_value=lambda v: update_setting("flood", "business_mold_rate", float(v) / 100.0))
                        solara.Markdown("**Economic effects**")
                        solara.SliderFloat("Household mold remediation cost", value=float(settings["disease"]["house_repair_cost_scale"]), min=0.0, max=2.0, step=0.05, on_value=lambda v: update_setting("disease", "house_repair_cost_scale", float(v)))
                        solara.Markdown("Higher values increase household spending required to remediate mold; realized spending remains limited by household resources and actual mold damage.")

                with solara.Card(title="Vectorborne context", margin=0):
                    vector_capable_scenario = current_scenario_name in {"flood_vectorborne", "flood_mold_vectorborne", "compound"}
                    if not vector_capable_scenario:
                        solara.Markdown("Vectorborne context controls are disabled for this scenario.")
                    else:
                        solara.Markdown("**Hazard effects**")
                        solara.SliderInt("Stagnant pool half-life in hours", value=int(settings["disease"]["stagnant_half_life_h"]), min=24, max=240, step=12, on_value=lambda v: update_setting("disease", "stagnant_half_life_h", int(v)))
                        solara.SliderInt("Stagnant pool influence radius in meters", value=int(settings["disease"]["stagnant_influence_m"]), min=50, max=800, step=25, on_value=lambda v: update_setting("disease", "stagnant_influence_m", int(v)))
                        solara.SliderFloat("Floodwater pools retained (%)", value=float(settings["disease"]["stagnant_keep_fraction"]) * 100.0, min=0.0, max=100.0, step=5.0, on_value=lambda v: update_setting("disease", "stagnant_keep_fraction", float(v) / 100.0))
                        solara.Markdown("Exposure, illness severity, affordability, distance, and healthcare capacity generate vectorborne care outcomes.")

            with solara.Column(gap="10px"):
                # Use the top-level GraphSelectionPanel component here
                GraphSelectionPanel(model)
                
                
@solara.component
def GraphSelectionPanel(model):
    settings = _settings_state.value

    def update_setting(group_name, key, value):
        new_state = json.loads(json.dumps(_settings_state.value))
        new_state[group_name][key] = value
        new_state = _apply_scenario_rules_to_settings(new_state)
        _settings_state.value = new_state
        _sync_settings_to_model_params(new_state)
        _visible_plot_state.value = [label for label in _visible_plot_state.value if _plot_is_available(label, new_state)]
        try:
            if int(getattr(model_state.value, "hours", 0) or 0) == 0:
                _pending_pre_run_rebuild.value = True
                _last_settings_change_ts.value = time.time()
        except Exception:
            pass

    current_scenario_name = _SCENARIO_NAME_BY_CODE.get(
        int(settings["scenario"]["scenario_mode_code"]),
        "compound",
    )

    available_labels = _available_plot_labels(_settings_state.value)
    selected = [label for label in _visible_plot_state.value if label in available_labels]
    if selected != list(_visible_plot_state.value):
        _visible_plot_state.value = selected

    def toggle_plot(label, checked):
        current = list(_visible_plot_state.value)
        if checked and label not in current:
            current.append(label)
        elif not checked and label in current:
            current.remove(label)
        _visible_plot_state.value = current

    labels = available_labels

    with solara.Card(title="Infectious disease context", margin=0, style={"background": "rgba(255,255,255,0.96)", "padding": "6px"}):
        infectious_capable_scenario = current_scenario_name in {"infectious_disease", "flood_infectious", "compound"}
        if not infectious_capable_scenario:
            solara.Markdown("Infectious disease controls are disabled for this scenario.")
        else:
            solara.Markdown("**Timing**")
            timeline_hours = max(
                1,
                int(model_params.get("baseline_days", 7) or 7) * 24
                + int(model_params.get("pre_flood_days", 7) or 7) * 24
                + int(model_params.get("flood_days", 3) or 3) * 24
                + int(model_params.get("post_flood_days", 14) or 14) * 24,
            )
            flood_end_hour = (
                int(model_params.get("baseline_days", 7) or 7)
                + int(model_params.get("pre_flood_days", 7) or 7)
                + int(model_params.get("flood_days", 3) or 3)
            ) * 24
            if current_scenario_name in {"flood_infectious", "compound"}:
                post_flood_start_days = max(
                    0,
                    round((int(settings["disease"]["infectious_seed_start_hour"]) - flood_end_hour) / 24),
                )
                solara.SliderInt(
                    "Days after flood before infectious disease starts",
                    value=post_flood_start_days,
                    min=0,
                    max=int(model_params.get("post_flood_days", 14) or 14),
                    step=1,
                    on_value=lambda v: update_setting(
                        "disease", "infectious_seed_start_hour", flood_end_hour + int(v) * 24
                    ),
                )
            else:
                solara.SliderInt(
                    "Infectious disease start hour",
                    value=int(settings["disease"]["infectious_seed_start_hour"]),
                    min=0,
                    max=timeline_hours,
                    step=1,
                    on_value=lambda v: update_setting("disease", "infectious_seed_start_hour", int(v)),
                )
            solara.Markdown("**SIR controls**")
            solara.SliderFloat("Initially infected population (%)", value=float(settings["disease"]["infectious_seed_share"]) * 100.0, min=0.0, max=20.0, step=0.1, on_value=lambda v: update_setting("disease", "infectious_seed_share", float(v) / 100.0))
            solara.SliderFloat("Base transmission chance", value=float(settings["disease"]["infectious_beta_base"]), min=0.0, max=0.05, step=0.0005, on_value=lambda v: update_setting("disease", "infectious_beta_base", float(v)))
            solara.SliderFloat("Hourly recovery probability", value=float(settings["disease"]["infectious_gamma"]) * 100.0, min=0.0, max=20.0, step=0.1, on_value=lambda v: update_setting("disease", "infectious_gamma", float(v) / 100.0))
            solara.SliderFloat("Hourly loss-of-immunity probability", value=float(settings["disease"]["infectious_waning"]) * 100.0, min=0.0, max=5.0, step=0.05, on_value=lambda v: update_setting("disease", "infectious_waning", float(v) / 100.0))
            solara.Markdown("**Contact mechanism**")
            solara.SliderFloat("Effective contact intensity", value=float(settings["disease"]["infectious_contact_intensity"]), min=0.0, max=3.0, step=0.05, on_value=lambda v: update_setting("disease", "infectious_contact_intensity", float(v)))

    with solara.Card(title="Visible charts", margin=0, style={"background": "rgba(255,255,255,0.96)", "padding": "6px"}):
        if not labels:
            solara.Markdown("No charts are available for the current scenario.")
        else:
            with solara.Column(gap="4px", style={"padding": "0", "margin": "0", "width": "100%"}):
                for label in labels:
                    solara.Checkbox(
                        label=label,
                        value=(label in selected),
                        on_value=lambda checked, label=label: toggle_plot(label, checked),
                        style="font-size: 12px; margin: 0; padding: 4px 2px; width: 100%;",
                    )


@solara.component
def SelectedPlotsPanel(model):
    available_labels = _available_plot_labels(_settings_state.value)
    scenario_name = _SCENARIO_NAME_BY_CODE.get(
        int(_settings_state.value["scenario"]["scenario_mode_code"]),
        "compound",
    )
    selected = [label for label in _visible_plot_state.value if label in available_labels]
    if selected != list(_visible_plot_state.value):
        _visible_plot_state.value = selected
    rows = [selected[i:i + 3] for i in range(0, len(selected), 3)]

    with solara.Column(gap="10px", style={"width": "100%"}):
        if not available_labels:
            with solara.Card(title="Selected charts", margin=0, style={"background": "rgba(255,255,255,0.98)"}):
                solara.Markdown("No charts are available for this scenario.")
                return
        if not selected:
            with solara.Card(title="Selected charts", margin=0, style={"background": "rgba(255,255,255,0.98)"}):
                solara.Markdown("No charts selected. Use the Visible charts panel to add one or more charts.")
        for row_labels in rows:
            with solara.Columns([1, 1, 1], wrap=False, style={"alignItems": "stretch", "width": "100%"}):
                for label in row_labels:
                    with solara.Column(gap="8px"):
                        with solara.Card(title=label, margin=0, style={"background": "rgba(255,255,255,0.98)", "minHeight": "280px"}):
                            if scenario_name == "infectious_disease" and label == "Population stability":
                                dc_population_stability_infectious_plot(model)
                            elif scenario_name == "compound" and label == "Population stability":
                                dc_population_stability_compound_plot(model)
                            elif scenario_name == "infectious_disease" and label == "Finance":
                                dc_finance_wealth_infectious_plot(model)
                            elif scenario_name == "infectious_disease" and label == "Impact expenses":
                                dc_impact_expenses_infectious_plot(model)
                            elif scenario_name == "infectious_disease" and label == "Affected population":
                                dc_affected_population_infectious_plot(model)
                            elif scenario_name == "baseline" and label == "Affected population":
                                dc_affected_population_baseline_plot(model)
                            else:
                                _PLOT_COMPONENTS[label](model)
                for _ in range(3 - len(row_labels)):
                    with solara.Column(gap="8px"):
                        solara.Div(style={"minHeight": "1px"})


_sync_settings_to_model_params()
_sync_population_mix_to_model_params()

# -------------------------------------------------------------------- #
# 6 · GeoSpace                                                         #
# -------------------------------------------------------------------- #
_MAP_VIEW = _map_view_config(STARTUP_MAP_NAME)
_LIVE_GEOSPACE_COMPONENT = make_geospace_component(
    agent_portrayal,
    view=_MAP_VIEW["view"],
    tiles={"url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png"},
    zoom=_MAP_VIEW["zoom"],
    height="68vh",
)

@solara.component
def BigGeoSpace(model, render_token: int = 0):
    _ = render_token
    with solara.Div(style={"height": "150%", "width": "100%"}):
        _LIVE_GEOSPACE_COMPONENT(model)


@solara.component
def DashboardLayout(model):
    with solara.Column(gap="12px", style={"padding": "12px", "width": "200%",  "maxWidth": "85vw", "margin": "0 auto"}):
        with solara.Card(title="Flood–Disease simulation dashboard", margin=0, style={"background": "rgba(255,255,255,0.96)"}):
            pass
        with solara.Columns([3, 1], wrap=True, style={"alignItems": "stretch"}):
            with solara.Column(gap="12px"):
                with solara.Card(title="Simulation map", margin=0, style={"background": "rgba(255,255,255,0.98)"}):
                    BigGeoSpace(model, render_token=int(getattr(model, "hours", 0) or 0))
            with solara.Column(gap="12px"):
                ColorLegend(model)

        ModelSettingsPanel(model)

        SelectedPlotsPanel(model)

# -------------------------------------------------------------------- #
# 7 · Solara page                                                      #
# -------------------------------------------------------------------- #

@solara.component
def page():
    _ensure_model_state()
    return SolaraViz(
        model_state,
        components=[DashboardLayout],
        model_params=model_params,
        name="Flood-Disease ABM",
        use_threads=False,
    )
# -------------------------------------------------------------------- #
# 8 · Optional resource print                                          #
# -------------------------------------------------------------------- #
mem, cpu = _resource_usage()
print(f"[Resource check] Memory {mem:.1f} MiB · CPU {cpu:.1f}%")

# -------------------------------------------------------------------- #
# 9 · One-click launch (Spyder / python serverrun.py) — controlled run #
#     - kills previous child server (if any) before starting a fresh   #
#     - opens browser only once per kernel/session                     #
# -------------------------------------------------------------------- #
if __name__ == "__main__" and "solara" not in " ".join(sys.argv).lower():

    HOST = "127.0.0.1"
    DEFAULT_PORT = int(os.environ.get("FLOOD_APP_PORT", "8786"))
    RUNTIME_DIR = ROOT / ".runtime"
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    LOG  = RUNTIME_DIR / "solara_server.log"
    PIDF = RUNTIME_DIR / ".solara_server.pid"        # tracks child PID we spawned
    BROWSE_LOCK = RUNTIME_DIR / ".solara_browser.lock"  # avoid duplicate tabs
    APP_PAGE_REF = "run.serverrun:page"         # keep in sync with filename

    def port_open(h, p, timeout=0.3):
        s = socket.socket(); s.settimeout(timeout)
        try:
            s.connect((h, p)); s.close(); return True
        except OSError:
            return False

    def kill_previous_if_any():
        """Kill the previously started solara child (ours), if pid file exists."""
        if PIDF.exists():
            try:
                pid = int(PIDF.read_text().strip())
                proc = psutil.Process(pid)
                # only kill if it's still solara we started (best-effort check)
                cmdline = " ".join(proc.cmdline()).lower()
                if " -m solara " in cmdline or " solara " in cmdline:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except psutil.TimeoutExpired:
                        proc.kill()
                PIDF.unlink(missing_ok=True)
            except Exception:
                # stale/invalid pidfile – remove it
                try:
                    PIDF.unlink(missing_ok=True)
                except Exception:
                    pass

    def wait_for_port_state(open_state: bool, port: int, wait_s: float = 10.0):
        """Wait until port is open_state==True (open) or False (closed)."""
        deadline = time.time() + wait_s
        while time.time() < deadline:
            if port_open(HOST, port) == open_state:
                return True
            time.sleep(0.2)
        return False

    # Always kill any previous run we spawned, so code changes take effect
    kill_previous_if_any()
    # If default port is still occupied (e.g., other app), we won’t kill it; we’ll pick another port.

    # Choose a free port starting from DEFAULT_PORT
    port = DEFAULT_PORT
    for _ in range(50):
        if not port_open(HOST, port):
            break
        port += 1
    url = f"http://{HOST}:{port}/"

    # Start Solara in THIS env; prevent Solara from opening the browser itself
    env = os.environ.copy()
    env["SOLARA_OPEN_BROWSER"] = "0"   # Solara respects this; we control opening
    logf = open(LOG, "w", buffering=1)
    cmd = [sys.executable, "-m", "solara", "run", APP_PAGE_REF, "--host", HOST, "--port", str(port)]
    print("Starting:", " ".join(cmd))

    proc = subprocess.Popen(
        cmd,
        stdout=logf,
        stderr=subprocess.STDOUT,
        close_fds=True,
        cwd=str(ROOT),          # ensure `run.serverrun:page` imports
        env=env,
    )
    # Write PID so we can kill cleanly next time
    try:
        PIDF.write_text(str(proc.pid))
    except Exception:
        pass

    # Wait up to 40s for readiness, or early crash
    deadline = time.time() + 40
    started = False
    while time.time() < deadline:
        if proc.poll() is not None:
            break  # child exited
        if port_open(HOST, port):
            started = True
            break
        time.sleep(0.2)

    if started:
        print(f"Running at {url} | Logs: {LOG}")
        raise SystemExit(0)

    # Failure: show log tail and clean up
    try:
        logf.flush()
        with open(LOG, "r", errors="replace") as f:
            lines = f.readlines()[-120:]
    except Exception:
        lines = ["<could not read log>"]
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
        PIDF.unlink(missing_ok=True)

    print("Solara did not start; showing log tail:\n" + ("-" * 80))
    print("".join(lines))
    print("-" * 80)
    raise SystemExit(1)