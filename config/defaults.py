"""Single source of truth for shared scenario and run defaults."""

from __future__ import annotations

from copy import deepcopy

# These are the interactive Serverrun defaults and are shared by batchrun.
RUN_DEFAULTS = {
    "N_persons": 500,
    "baseline_days": 7,
    "pre_flood_days": 3,
    "flood_days": 7,
    "post_flood_days": 22,
    "replications": 10,
    "seed_base": 42,
}

MAP_POPULATION_PRESETS = {
    "uvalde": {
        "male_share_pct": 51.1,
        "female_share_pct": 48.9,
        "age_0_14_pct": 22.0,
        "age_15_64_pct": 60.8,
        "age_65_100_pct": 17.2,
        "ethnicity_white_pct": 17.5,
        "ethnicity_black_pct": 1.2,
        "ethnicity_hispanic_pct": 78.3,
        "ethnicity_other_pct": 3.0,
        "perc_education_people": 0.73,
        "worldview_hierarchist_pct": 25.0,
        "worldview_egalitarian_pct": 25.0,
        "worldview_individualist_pct": 25.0,
        "worldview_fatalist_pct": 25.0,
    },
}

SERVICE_DEFAULTS = {
    "shelter_cap_limit": 7.0,
    "healthcare_cap_limit": 7.0,
    "shelter_funding": 50_000,
    "healthcare_funding": 100_000,
}

# Deterministic model defaults shared by Serverrun and batch runs. Batch
# uncertainty ranges remain in run/support/common.py.
FLOOD_DEFAULTS = {
    "flood_critical_facility_clearance_m": 25.0,
    "flood_depth_multiplier": 2.5,
    "flood_onset_speed": 1.0,
    "flood_recession_speed": 1.0,
    "house_flood_thresh_mult": 0.90,
    "biz_flood_thresh_mult": 0.90,
    "school_flood_thresh_mult": 0.90,
    "pre_evac_T_gate": 0.19,
    "evac_trigger_depth_m": 0.20,
    "home_unsafe_depth_m": 0.3,
    "warning_pre_flood_base": 0.35,
    "stranded_depth_tolerance_mult": 0.05,
    "injury_risk_scale": 1.5,
    "hours_before_rescue": 6,
    "flood_wave_enabled": True,
    "flood_wave_direction": "southwest_to_northeast",
    "flood_wave_rise_hours": 0.0,
    "flood_wave_fall_hours": 0.0,
}

INFECTIOUS_DEFAULTS = {
    "infectious_seed_share": 0.01,
    "infectious_beta_base": 0.008,
    "infectious_gamma": 0.0167,
    "infectious_waning": 0.0,
    "infectious_contact_intensity": 0.02,
    "infectious_severity_scale": 1.20,
    "infectious_mortality_hazard": 0.03,
    "infectious_course_hours": 50,
    "infectious_peak_hours": 55,
    "injury_hospital_recovery_boost": 3.0,
    "infectious_threat_coupling": 0.0,
    "infectious_seed_start_hour": 200,
}

MOLD_DEFAULTS = {
    "damp_half_life_h": 20.0,
    "damp_resilience_effect": 0.8,
    "damp_done_threshold": 0.15,
    "damp_metric_hours": 30.0,
    "school_repair_cost_multiplier": 0.5,
    "school_mold_attendance_penalty_rate": 0.15,
    "mold_symptom_threshold": 0.15,
    "mold_functional_capacity": 0.70,
    "mold_hospital_seek_prob": 0.01,
    "mold_healthcare_cost_multiplier": 0.252,
    "house_mold_rate": 0.30,
    "business_mold_rate": 0.50,
}

VECTORBORNE_DEFAULTS = {
    "stagnant_half_life_h": 96.0,
    "stagnant_influence_m": 125.0,
    "stagnant_max_spots_per_wave": 7,
    "stagnant_max_source_polygons": 20,
    "stagnant_area_fraction": 0.005,
    "vector_control_intensity": 0.0,
    "stagnant_keep_fraction": 0.60,
    "vector_hospital_seek_prob": 0.02,
    "vector_exposure_hazard": 0.05,
    "vector_functional_capacity": 0.75,
    "healthcare_max_stay_hours": 100,
    "vector_healthcare_cost_multiplier": 0.351,
    "stagnant_lifetime_min_h": 72.0,
    "stagnant_lifetime_max_h": 120.0,
    "stagnant_shrink_min": 3.0,
    "stagnant_shrink_max": 12.0,
    "stagnant_min_area": 80.0,
    "stagnant_simplify_tolerance": 2.0,
}

ECONOMIC_DEFAULTS = {
    "sales_tax_rate": 0.05,
    "corporate_tax_rate": 0.16,
    "income_tax_rate": 0.12,
    "sales_revenue_multiplier": 3.80,
    "business_revenue_staffing_floor": 0.20,
    "business_revenue_staffing_elasticity": 1.6,
    "person_initial_cash_multiplier": 1.0,
    "person_initial_cash_weeks_min": 0.5,
    "person_initial_cash_weeks_max": 1.5,
    "person_wealth_reference_population": 300.0,
    "evacuation_cost_scale": 0.25,
    "preparation_cost_scale": 0.25,
    "business_wage_cost_share": 0.20,
    "patient_healthcare_cost_multiplier": 0.02,
    "business_repair_cost_multiplier": 0.75,
    "house_repair_cost_scale": 0.10,
    "house_repair_attempt_scale": 0.25,
    "business_initial_wealth_factor": 2.80,
    "government_initial_wealth_factor": 3.0,
    "business_close_penalty_rate": 0.5,
    "business_close_penalty_min": 3000.0,
    "business_closed_hourly_burn_rate": 0.50,
    "business_mold_ops_penalty_rate": 0.05,
    "person_income_growth_scale": 0.50,
    "business_annual_output_per_person": 22000.0,
    "school_annual_output_per_person": 1200.0,
    "shelter_annual_output_per_person": 4200.0,
    "healthcare_annual_output_per_person": 4200.0,
    "government_annual_output_per_person": 7000.0,
    "gdp_allocation_days": 14,
    "house_repair_base_cost": 125.0,
    "repair_cost_variation": 0.20,
    "shelter_operating_cost_per_person_max": 50.0,
}

BEHAVIOR_DEFAULTS = {
    "during_route_max_depth_m": 0.3,
    "decision_interval_hours": 6,
    "return_decision_interval_hours": 6,
    "social_evac_signal_scale": 0.35,
    "home_depth_tol_m": 0.20,
    "work_depth_tol_m": 0.25,
    "school_depth_tol_m": 0.20,
    "public_space_depth_tol_m": 0.15,
    "entity_inside_depth_share": 1.00,
    "home_habit_thresh": 0.50,
    "person_resilience_min": 5.0,
    "person_resilience_max": 15.0,
    "random_move_radius_m": 400,
    "min_ethnicity_group_size": 3,
}

# Person decision model. These weights and coefficients control evacuation,
# preparation, staying, and post-flood return decisions.
DECISION_DEFAULTS = {
    "decision_w_depth": 0.40,
    "decision_w_imminence": 0.15,
    "decision_w_official": 0.12,
    "decision_w_social": 0.08,
    "decision_w_memory": 0.05,
    "decision_w_disease": 0.20,
    "decision_a_self": 0.40,
    "decision_a_response": 0.30,
    "decision_a_social": 0.20,
    "decision_a_cost": 0.30,
    "decision_beta0": -1.4,
    "decision_beta_threat": 1.7,
    "decision_beta_coping": 1.0,
    "decision_beta0_prepare": -1.0,
    "decision_beta_threat_prepare": 1.5,
    "decision_beta_coping_prepare": 0.5,
    "decision_gamma0": -1.5,
    "decision_gamma_habitability": 2.5,
    "decision_gamma_coping": 1.0,
}

# Healthcare and shelter transport, queue, and patient billing controls.
HEALTHCARE_DEFAULTS = {
    "healthcare_transfer_speed_mps": 8.0,
    "healthcare_turnaround_minutes": 20.0,
    "healthcare_base_admit_cost": 120.0,
    "healthcare_km_cost": 2.0,
    "healthcare_hazard_radius_m": 300.0,
    "healthcare_max_wait_hours_cap": 12.0,
    "healthcare_hospital_recovery_boost": 2.5,
    "healthcare_self_present_fee": 40.0,
    "hc_ready_discharge_wait_hours": 72,
    "shelter_rescue_speed_mps": 8.33,
    "shelter_turnaround_minutes": 20.0,
    "shelter_km_cost": 1.0,
    "shelter_base_pickup_cost": 10.0,
    "shelter_max_wait_hours_cap": 12.0,
}

# Shared structure flood hysteresis and cleanup/repair mechanics.
STRUCTURE_DAMAGE_DEFAULTS = {
    "structure_flood_on_margin": 1.00,
    "structure_flood_off_margin": 0.90,
    "structure_cleanup_base_hours": 2.0,
    "structure_cleanup_depth_hours": 6.0,
    "structure_cleanup_resilience_divisor": 10.0,
    "structure_cleanup_max_hours": 72,
    "structure_repair_base_cost": 60.0,
    "structure_repair_depth_cost": 180.0,
    "structure_repair_intensity_scale": 1.5,
    "structure_repair_variation_min": 0.70,
    "structure_repair_variation_max": 1.45,
    "structure_mold_duration_base_hours": 168.0,
    "structure_mold_duration_intensity_hours": 84.0,
}

# Technical flood geometry controls; these affect retained geometry and speed,
# rather than the scientific behavior of person agents.
FLOOD_GEOMETRY_DEFAULTS = {
    "flood_clip_padding_m": 250.0,
    "flood_simplify_tolerance_m": 10.0,
    "flood_max_visual_polygons": 20,
    "flood_depth_default_m": 0.60,
    "flood_depth_variation_m": 0.15,
}

POLICY_DEFAULTS = {
    "wash_intensity": 0.0,
    "shelter_distancing_intensity": 0.0,
    "healthcare_surge_factor": 0.0,
    "repair_subsidy_intensity": 0.0,
    "risk_communication_intensity": 0.0,
    "targeted_protection_intensity": 0.0,
    "gov_baseline_grant_every_hours": 24,
    "psych_efficacy_hazard_gain_self": 0.30,
    "psych_efficacy_hazard_gain_response": 0.35,
    "psych_efficacy_adapt_rate": 0.10,
    "psych_efficacy_decay_rate": 0.04,
    "psych_symptom_pressure": 0.70,
    "institutional_procurement_pass_through": 0.35,
    "gov_baseline_share_shelter": 0.01,
    "gov_baseline_share_healthcare": 0.03,
    "gov_baseline_share_school": 0.01,
    "gov_event_shelter_grant_scale": 100.0,
    "gov_event_healthcare_grant_scale": 250.0,
}

STOCHASTICITY_DEFAULTS = {
    "stochasticity_level": 0.05,
    "decision_jitter_rel": 0.05,
    "threshold_jitter_rel": 0.03,
    "health_jitter_rel": 0.05,
    "mobility_jitter_rel": 0.04,
    "survivability_duration_scale": 1,
    "stranded_mortality_rate_scale": 0.001,
    "stranded_mortality_hazard_threshold": 1,
    "stranded_mortality_prob_cap": 0.001,
}

# Flat compatibility view used when passing kwargs into Model.
MODEL_DEFAULTS = {
    **MAP_POPULATION_PRESETS["uvalde"],
    **FLOOD_DEFAULTS,
    **INFECTIOUS_DEFAULTS,
    **MOLD_DEFAULTS,
    **VECTORBORNE_DEFAULTS,
    **ECONOMIC_DEFAULTS,
    **BEHAVIOR_DEFAULTS,
    **DECISION_DEFAULTS,
    **HEALTHCARE_DEFAULTS,
    **STRUCTURE_DAMAGE_DEFAULTS,
    **FLOOD_GEOMETRY_DEFAULTS,
    **POLICY_DEFAULTS,
    **STOCHASTICITY_DEFAULTS,
}

SCENARIO_NAME_BY_CODE = {
    0: "baseline",
    1: "flood_only",
    2: "infectious_disease",
    3: "flood_mold",
    4: "flood_vectorborne",
    5: "flood_infectious",
    6: "compound",
}

SCENARIO_LABEL_BY_CODE = {
    0: "Baseline",
    1: "Flood",
    2: "Infectious Disease",
    3: "Flood Mold",
    4: "Flood Vectorborne",
    5: "Flood Infectious Disease",
    6: "Compound: Flood and All Diseases",
}
SCENARIO_CODE_BY_LABEL = {label: code for code, label in SCENARIO_LABEL_BY_CODE.items()}

SCENARIO_FLAGS = {
    "baseline": {"enable_flood": False, "enable_infectious": False, "enable_stagnant": False, "enable_mold": False},
    "flood_only": {"enable_flood": True, "enable_infectious": False, "enable_stagnant": False, "enable_mold": False},
    "infectious_disease": {"enable_flood": False, "enable_infectious": True, "enable_stagnant": False, "enable_mold": False},
    "flood_mold": {"enable_flood": True, "enable_infectious": False, "enable_stagnant": False, "enable_mold": True},
    "flood_vectorborne": {"enable_flood": True, "enable_infectious": False, "enable_stagnant": True, "enable_mold": False},
    "flood_mold_vectorborne": {"enable_flood": True, "enable_infectious": False, "enable_stagnant": True, "enable_mold": True},
    "flood_infectious": {"enable_flood": True, "enable_infectious": True, "enable_stagnant": False, "enable_mold": False},
    "compound": {"enable_flood": True, "enable_infectious": True, "enable_stagnant": True, "enable_mold": True},
}


def infectious_start_hour(scenario_name: str, baseline_days: int, pre_flood_days: int, flood_days: int) -> int:
    """Return the default infection start for the selected scenario."""
    if scenario_name in {"flood_infectious", "compound"}:
        return (int(baseline_days) + int(pre_flood_days) + int(flood_days) + 2) * 24
    if scenario_name == "infectious_disease":
        return int(INFECTIOUS_DEFAULTS["infectious_seed_start_hour"])
    return 0


def scenario_flags(scenario_name: str) -> dict:
    """Return a fresh copy so callers cannot mutate the shared table."""
    return dict(SCENARIO_FLAGS.get(scenario_name, SCENARIO_FLAGS["compound"]))


def copy_map_population(map_name: str = "uvalde") -> dict:
    return deepcopy(MAP_POPULATION_PRESETS[map_name])
