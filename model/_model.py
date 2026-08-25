"""Core model for the flood-disease ABM."""

from __future__ import annotations

import random
from pathlib import Path

import numpy as np

from shapely.geometry import Point
from mesa import Model

from space._space import StudyArea
from model._flood import FloodManager, RiverFloodModule
from model._disease import DiseaseManager, InfectiousModule, VectorborneModule, MoldModule

from agents import _personAssign as psn_agnt
from agents._person import DecisionParams
from dataCollection._dataCollect import data_collection, export_person_panel, export_summary, export_timeseries
from config.defaults import MODEL_DEFAULTS, RUN_DEFAULTS, SERVICE_DEFAULTS, SCENARIO_FLAGS, SCENARIO_NAME_BY_CODE
import logging
import time


logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
MAP_NAME = "uvalde"
DATA = ROOT / "space" / "Uvalde_TX_map_data"

def _as_bool(x, default=False):
    if x is None:
        return default
    if isinstance(x, (int, float)):
        return bool(int(x))
    if isinstance(x, str):
        return x.strip().lower() in ("1", "true", "yes", "on")
    return bool(x)


def resolve_scenario_configuration(scenario_mode, defaults=None):
    """Resolve a scenario name or code into the active hazard flags."""
    defaults = defaults or {}

    if isinstance(scenario_mode, (int, float)):
        scenario = SCENARIO_NAME_BY_CODE.get(int(scenario_mode), "compound")
    else:
        raw = str(scenario_mode or "compound").strip().lower()
        aliases = {
            "baseline_only": "baseline",
            "flood": "flood_only",
            "flood_plus_mold": "flood_mold",
            "flood_plus_infectious": "flood_infectious",
            "flood_infectious": "flood_infectious",
            "flood_plus_vectorborne": "flood_vectorborne",
            "flood_vectorborne": "flood_vectorborne",
            "flood_mold": "flood_mold",
            "flood_vectorborne": "flood_vectorborne",
            "flood_mold_and_vectorborne": "flood_mold_vectorborne",
            "flood_plus_mold_plus_vectorborne": "flood_mold_vectorborne",
            "flood_mold_vectorborne": "flood_mold_vectorborne",
            "disease": "infectious_disease",
            "disease_only": "infectious_disease",
            "infectious": "infectious_disease",
            "both": "compound",
            "compound_hazard": "compound",
            "custom": "compound",
        }
        scenario = aliases.get(raw, raw)
        if scenario not in set(SCENARIO_NAME_BY_CODE.values()):
            scenario = "compound"

    # Named scenarios are the scientific contract for which processes exist.
    # Do not let stale UI or legacy kwargs override those flags; otherwise an
    # infectious-only run can silently retain flood behavior.
    cfg = {"scenario_mode": scenario, **SCENARIO_FLAGS[scenario]}

    # Scientific restriction: flood-triggered pathways cannot operate without flood.
    if not cfg["enable_flood"]:
        cfg["enable_stagnant"] = False
        cfg["enable_mold"] = False

    if scenario == "compound" and not any([
        cfg["enable_infectious"],
        cfg["enable_stagnant"],
        cfg["enable_mold"],
    ]):
        cfg["enable_infectious"] = True

    cfg["enable_disease_system"] = any([
        cfg["enable_infectious"],
        cfg["enable_stagnant"],
        cfg["enable_mold"],
    ])
    return cfg


class Model(Model):
    # ------------------------------------------------------------------ #
    # 1. Init
    # ------------------------------------------------------------------ #
    
    def __init__(self, N_persons=RUN_DEFAULTS["N_persons"], shelter_cap_limit=SERVICE_DEFAULTS["shelter_cap_limit"], healthcare_cap_limit=SERVICE_DEFAULTS["healthcare_cap_limit"],
        shelter_funding=SERVICE_DEFAULTS["shelter_funding"], healthcare_funding=SERVICE_DEFAULTS["healthcare_funding"], baseline_days=RUN_DEFAULTS["baseline_days"],
        pre_flood_days=RUN_DEFAULTS["pre_flood_days"], flood_days=RUN_DEFAULTS["flood_days"],
        post_flood_days=RUN_DEFAULTS["post_flood_days"], houses_file=None, businesses_file=None, schools_file=None,
        shelter_file=None, healthcare_file=None, government_file=None, 
        flood_file=None, model_crs="EPSG:3857", **kwargs):

        super().__init__()

        # Bookkeeping.
        self.hours = 0
        self.crs = model_crs
        self.random_seed = int(kwargs.get("random_seed", random.randint(0, 2**31 - 1)))
        self.replication = int(kwargs.get("replication", 0) or 0)
        self.run_id = str(kwargs.get("run_id", f"run_seed{self.random_seed}_rep{self.replication}"))
        self.auto_export_on_finish = bool(kwargs.get("auto_export_on_finish", False))
        self.strict_module_errors = bool(kwargs.get("strict_module_errors", False))

        random.seed(self.random_seed)
        np.random.seed(self.random_seed)

        # Keep critical emergency facilities operational in the flood footprint.
        self.flood_critical_facility_clearance_m = max(
            0.0,
            float(kwargs.get("flood_critical_facility_clearance_m", MODEL_DEFAULTS["flood_critical_facility_clearance_m"]) or 0.0),
        )

        # Place agents consume these controls during StudyArea construction.
        for control in (
            "healthcare_transfer_speed_mps", "healthcare_turnaround_minutes",
            "healthcare_base_admit_cost", "healthcare_km_cost",
            "healthcare_hazard_radius_m", "healthcare_max_wait_hours_cap",
            "healthcare_hospital_recovery_boost", "healthcare_self_present_fee",
            "hc_ready_discharge_wait_hours",
            "shelter_rescue_speed_mps", "shelter_turnaround_minutes",
            "shelter_km_cost", "shelter_base_pickup_cost", "shelter_max_wait_hours_cap",
            "structure_flood_on_margin", "structure_flood_off_margin",
            "structure_cleanup_base_hours", "structure_cleanup_depth_hours",
            "structure_cleanup_resilience_divisor", "structure_cleanup_max_hours",
            "structure_repair_base_cost", "structure_repair_depth_cost",
            "structure_repair_intensity_scale", "structure_repair_variation_min",
            "structure_repair_variation_max", "structure_mold_duration_base_hours",
            "structure_mold_duration_intensity_hours", "flood_clip_padding_m",
            "flood_simplify_tolerance_m", "flood_max_visual_polygons",
            "flood_depth_default_m", "flood_depth_variation_m",
        ):
            setattr(self, control, kwargs.get(control, MODEL_DEFAULTS[control]))

        # Geospatial study area.
        self.space = StudyArea(
            self,
            houses_file,
            businesses_file,
            schools_file,
            shelter_file,
            healthcare_file,
            government_file,
            model_crs,
        )

        self.houses = self.space.houses
        self.businesses = self.space.businesses
        self.schools = self.space.schools
        self.shelters = self.space.shelter
        self.healthcares = self.space.healthcare
        self.governments = self.space.government
        
        self.random_move_radius_m = max(
            0.0,
            float(kwargs.get("random_move_radius_m", MODEL_DEFAULTS["random_move_radius_m"]) or MODEL_DEFAULTS["random_move_radius_m"]),
        )
        merged = DATA / "uvalde_twdb_scenario5_1in100_flood.geojson"
        if not merged.exists():
            raise FileNotFoundError(f"Required Uvalde flood dataset is missing: {merged}")
        self.flood_file = str(flood_file or merged)
        
        # Tax and revenue knobs.
        self.sales_tax_rate     = float(kwargs.get("sales_tax_rate", MODEL_DEFAULTS["sales_tax_rate"]) or MODEL_DEFAULTS["sales_tax_rate"])
        self.corporate_tax_rate = float(kwargs.get("corporate_tax_rate", MODEL_DEFAULTS["corporate_tax_rate"]) or MODEL_DEFAULTS["corporate_tax_rate"])
        self.income_tax_rate    = float(kwargs.get("income_tax_rate", MODEL_DEFAULTS["income_tax_rate"]) or MODEL_DEFAULTS["income_tax_rate"])
        self.sales_revenue_multiplier = float(kwargs.get("sales_revenue_multiplier", MODEL_DEFAULTS["sales_revenue_multiplier"]) or MODEL_DEFAULTS["sales_revenue_multiplier"])
        self.business_revenue_staffing_floor = max(0.0, min(1.0, float(kwargs.get("business_revenue_staffing_floor", MODEL_DEFAULTS["business_revenue_staffing_floor"]) or MODEL_DEFAULTS["business_revenue_staffing_floor"])))
        self.business_revenue_staffing_elasticity = max(0.1, float(kwargs.get("business_revenue_staffing_elasticity", MODEL_DEFAULTS["business_revenue_staffing_elasticity"]) or MODEL_DEFAULTS["business_revenue_staffing_elasticity"]))
        self.person_initial_cash_multiplier = max(0.0, float(kwargs.get("person_initial_cash_multiplier", MODEL_DEFAULTS["person_initial_cash_multiplier"]) or MODEL_DEFAULTS["person_initial_cash_multiplier"]))
        self.person_initial_cash_weeks_min = max(0.0, float(kwargs.get("person_initial_cash_weeks_min", MODEL_DEFAULTS["person_initial_cash_weeks_min"]) or MODEL_DEFAULTS["person_initial_cash_weeks_min"]))
        self.person_initial_cash_weeks_max = max(
            self.person_initial_cash_weeks_min,
            float(kwargs.get("person_initial_cash_weeks_max", MODEL_DEFAULTS["person_initial_cash_weeks_max"]) or MODEL_DEFAULTS["person_initial_cash_weeks_max"]),
        )
        self.person_wealth_reference_population = max(1.0, float(kwargs.get("person_wealth_reference_population", MODEL_DEFAULTS["person_wealth_reference_population"]) or MODEL_DEFAULTS["person_wealth_reference_population"]))
        self.evacuation_cost_scale = max(0.0, float(kwargs.get("evacuation_cost_scale", MODEL_DEFAULTS["evacuation_cost_scale"]) or MODEL_DEFAULTS["evacuation_cost_scale"]))
        self.preparation_cost_scale = max(0.0, float(kwargs.get("preparation_cost_scale", MODEL_DEFAULTS["preparation_cost_scale"]) or MODEL_DEFAULTS["preparation_cost_scale"]))
        self.business_wage_cost_share = max(0.0, min(1.0, float(kwargs.get("business_wage_cost_share", MODEL_DEFAULTS["business_wage_cost_share"]) or MODEL_DEFAULTS["business_wage_cost_share"])))
        self.patient_healthcare_cost_multiplier = max(0.0, float(kwargs.get("patient_healthcare_cost_multiplier", MODEL_DEFAULTS["patient_healthcare_cost_multiplier"]) or MODEL_DEFAULTS["patient_healthcare_cost_multiplier"]))
        self.business_repair_cost_multiplier = max(0.0, float(kwargs.get("business_repair_cost_multiplier", MODEL_DEFAULTS["business_repair_cost_multiplier"]) or MODEL_DEFAULTS["business_repair_cost_multiplier"]))
        self.house_repair_cost_scale = max(0.0, float(kwargs.get("house_repair_cost_scale", MODEL_DEFAULTS["house_repair_cost_scale"]) or MODEL_DEFAULTS["house_repair_cost_scale"]))
        self.house_repair_attempt_scale = max(0.0, float(kwargs.get("house_repair_attempt_scale", MODEL_DEFAULTS["house_repair_attempt_scale"]) or MODEL_DEFAULTS["house_repair_attempt_scale"]))
        self.business_initial_wealth_factor = max(0.0, float(kwargs.get("business_initial_wealth_factor", MODEL_DEFAULTS["business_initial_wealth_factor"]) or MODEL_DEFAULTS["business_initial_wealth_factor"]))
        self.government_initial_wealth_factor = max(0.0, float(kwargs.get("government_initial_wealth_factor", MODEL_DEFAULTS["government_initial_wealth_factor"]) or MODEL_DEFAULTS["government_initial_wealth_factor"]))
        self.business_close_penalty_rate = max(0.0, float(kwargs.get("business_close_penalty_rate", MODEL_DEFAULTS["business_close_penalty_rate"]) or MODEL_DEFAULTS["business_close_penalty_rate"]))
        self.business_close_penalty_min = max(0.0, float(kwargs.get("business_close_penalty_min", MODEL_DEFAULTS["business_close_penalty_min"]) or MODEL_DEFAULTS["business_close_penalty_min"]))
        self.business_closed_hourly_burn_rate = max(0.0, float(kwargs.get("business_closed_hourly_burn_rate", MODEL_DEFAULTS["business_closed_hourly_burn_rate"]) or MODEL_DEFAULTS["business_closed_hourly_burn_rate"]))
        self.business_mold_ops_penalty_rate = max(0.0, float(kwargs.get("business_mold_ops_penalty_rate", MODEL_DEFAULTS["business_mold_ops_penalty_rate"]) or MODEL_DEFAULTS["business_mold_ops_penalty_rate"]))
        self.person_income_growth_scale = max(0.0, float(kwargs.get("person_income_growth_scale", MODEL_DEFAULTS["person_income_growth_scale"]) or MODEL_DEFAULTS["person_income_growth_scale"]))
        self.house_repair_base_cost = max(0.0, float(kwargs.get("house_repair_base_cost", MODEL_DEFAULTS["house_repair_base_cost"]) or MODEL_DEFAULTS["house_repair_base_cost"]))
        self.repair_cost_variation = max(0.0, min(1.0, float(kwargs.get("repair_cost_variation", MODEL_DEFAULTS["repair_cost_variation"]) or MODEL_DEFAULTS["repair_cost_variation"])))
        self.shelter_operating_cost_per_person_max = max(0.0, float(kwargs.get("shelter_operating_cost_per_person_max", MODEL_DEFAULTS["shelter_operating_cost_per_person_max"]) or MODEL_DEFAULTS["shelter_operating_cost_per_person_max"]))

        # School repair & mold knobs (parallels business defaults)
        self.school_repair_cost_multiplier = max(0.0, float(kwargs.get("school_repair_cost_multiplier", MODEL_DEFAULTS["school_repair_cost_multiplier"]) or MODEL_DEFAULTS["school_repair_cost_multiplier"]))
        self.school_mold_attendance_penalty_rate = max(0.0, float(kwargs.get("school_mold_attendance_penalty_rate", MODEL_DEFAULTS["school_mold_attendance_penalty_rate"]) or MODEL_DEFAULTS["school_mold_attendance_penalty_rate"]))

        # Timeline.
        self.baseline_days  = baseline_days
        self.pre_flood_days = pre_flood_days
        self.flood_days     = flood_days
        self.post_flood_days= post_flood_days
        
        # Flood calibration knobs.
        self.flood_depth_multiplier = float(kwargs.get("flood_depth_multiplier", MODEL_DEFAULTS["flood_depth_multiplier"]))
        self.flood_onset_speed = max(0.1, float(kwargs.get("flood_onset_speed", MODEL_DEFAULTS["flood_onset_speed"]) or MODEL_DEFAULTS["flood_onset_speed"]))
        self.flood_recession_speed = max(0.1, float(kwargs.get("flood_recession_speed", MODEL_DEFAULTS["flood_recession_speed"]) or MODEL_DEFAULTS["flood_recession_speed"]))
        self.flood_wave_enabled = _as_bool(kwargs.get("flood_wave_enabled", MODEL_DEFAULTS["flood_wave_enabled"]), MODEL_DEFAULTS["flood_wave_enabled"])
        self.flood_wave_direction = str(kwargs.get("flood_wave_direction", MODEL_DEFAULTS["flood_wave_direction"]) or MODEL_DEFAULTS["flood_wave_direction"])
        self.flood_wave_rise_hours = max(1.0, float(kwargs.get("flood_wave_rise_hours", 0.0) or 0.0))
        self.flood_wave_fall_hours = max(1.0, float(kwargs.get("flood_wave_fall_hours", 0.0) or 0.0))
        self.house_flood_thresh_mult = float(kwargs.get("house_flood_thresh_mult", MODEL_DEFAULTS["house_flood_thresh_mult"]))
        self.biz_flood_thresh_mult   = float(kwargs.get("biz_flood_thresh_mult", MODEL_DEFAULTS["biz_flood_thresh_mult"]))
        self.school_flood_thresh_mult = float(kwargs.get("school_flood_thresh_mult", MODEL_DEFAULTS["school_flood_thresh_mult"]))

        
        # Dampness dynamics knobs.
        self.damp_half_life_h       = float(kwargs.get("damp_half_life_h", MODEL_DEFAULTS["damp_half_life_h"]))
        self.damp_resilience_effect = float(kwargs.get("damp_resilience_effect", MODEL_DEFAULTS["damp_resilience_effect"]))
        self.damp_done_threshold    = float(kwargs.get("damp_done_threshold", MODEL_DEFAULTS["damp_done_threshold"]))
        self.damp_metric_hours      = float(kwargs.get("damp_metric_hours", MODEL_DEFAULTS["damp_metric_hours"]))

    
        # Absolute hour cutoffs for each phase.
        self._baseline_end_h = int(self.baseline_days * 24)
        self._preflood_end_h = int(self._baseline_end_h + self.pre_flood_days * 24)
        self._during_end_h   = int(self._preflood_end_h + self.flood_days * 24)
        self._post_end_h     = int(self._during_end_h + self.post_flood_days * 24)
    
        # Evacuation window spans the entire pre-flood period.
        self.evacuation_time      = int(self._baseline_end_h)
        self.last_evacuation_time = int(self._preflood_end_h)
        
        # Decision tuning knobs.
        self.pre_evac_T_gate         = float(kwargs.get("pre_evac_T_gate", MODEL_DEFAULTS["pre_evac_T_gate"]))
        self.evac_trigger_depth_m    = float(kwargs.get("evac_trigger_depth_m", MODEL_DEFAULTS["evac_trigger_depth_m"]))
        self.home_unsafe_depth_m     = float(kwargs.get("home_unsafe_depth_m", MODEL_DEFAULTS["home_unsafe_depth_m"]))
        self.during_route_max_depth_m = max(0.0, float(kwargs.get("during_route_max_depth_m", MODEL_DEFAULTS["during_route_max_depth_m"]) or MODEL_DEFAULTS["during_route_max_depth_m"]))
        self.decision_interval_hours = max(1, int(kwargs.get("decision_interval_hours", MODEL_DEFAULTS["decision_interval_hours"]) or MODEL_DEFAULTS["decision_interval_hours"]))
        self.return_decision_interval_hours = max(1, int(kwargs.get("return_decision_interval_hours", MODEL_DEFAULTS["return_decision_interval_hours"]) or MODEL_DEFAULTS["return_decision_interval_hours"]))
        self.social_evac_signal_scale = max(0.0, float(kwargs.get("social_evac_signal_scale", MODEL_DEFAULTS["social_evac_signal_scale"]) or MODEL_DEFAULTS["social_evac_signal_scale"]))
        
        # Pre-flood warning baseline, scaled by communication intensity.
        self.warning_pre_flood_base  = float(kwargs.get("warning_pre_flood_base", MODEL_DEFAULTS["warning_pre_flood_base"]))

        # Safety and habitability defaults used throughout movement logic.
        self.home_depth_tol_m         = float(kwargs.get("home_depth_tol_m", MODEL_DEFAULTS["home_depth_tol_m"]))
        self.work_depth_tol_m         = float(kwargs.get("work_depth_tol_m", MODEL_DEFAULTS["work_depth_tol_m"]))
        self.school_depth_tol_m       = float(kwargs.get("school_depth_tol_m", MODEL_DEFAULTS["school_depth_tol_m"]))
        self.public_space_depth_tol_m = float(kwargs.get("public_space_depth_tol_m", MODEL_DEFAULTS["public_space_depth_tol_m"]))
        self.entity_inside_depth_share = float(kwargs.get("entity_inside_depth_share", MODEL_DEFAULTS["entity_inside_depth_share"]))
        self.home_habit_thresh        = float(kwargs.get("home_habit_thresh", MODEL_DEFAULTS["home_habit_thresh"]))
        self.person_resilience_min    = max(0.0, float(kwargs.get("person_resilience_min", MODEL_DEFAULTS["person_resilience_min"]) or MODEL_DEFAULTS["person_resilience_min"]))
        self.person_resilience_max    = max(self.person_resilience_min, float(kwargs.get("person_resilience_max", MODEL_DEFAULTS["person_resilience_max"]) or MODEL_DEFAULTS["person_resilience_max"]))
        self.stranded_depth_tolerance_mult = max(0.01, float(kwargs.get("stranded_depth_tolerance_mult", MODEL_DEFAULTS["stranded_depth_tolerance_mult"]) or MODEL_DEFAULTS["stranded_depth_tolerance_mult"]))
        self.injury_risk_scale = max(0.0, float(kwargs.get("injury_risk_scale", MODEL_DEFAULTS["injury_risk_scale"]) or MODEL_DEFAULTS["injury_risk_scale"]))
        self.house_mold_rate = max(0.0, min(1.0, float(kwargs.get("house_mold_rate", MODEL_DEFAULTS["house_mold_rate"]))))
        self.business_mold_rate = max(0.0, min(1.0, float(kwargs.get("business_mold_rate", MODEL_DEFAULTS["business_mold_rate"]))))

        # Policy levers for experiments.
        self.wash_intensity                = float(kwargs.get("wash_intensity", MODEL_DEFAULTS["wash_intensity"]))
        self.shelter_distancing_intensity  = float(kwargs.get("shelter_distancing_intensity", MODEL_DEFAULTS["shelter_distancing_intensity"]))
        self.healthcare_surge_factor       = float(kwargs.get("healthcare_surge_factor", MODEL_DEFAULTS["healthcare_surge_factor"]))
        self.repair_subsidy_intensity      = float(kwargs.get("repair_subsidy_intensity", MODEL_DEFAULTS["repair_subsidy_intensity"]))
        self.risk_communication_intensity  = float(kwargs.get("risk_communication_intensity", MODEL_DEFAULTS["risk_communication_intensity"]))
        self.targeted_protection_intensity = float(kwargs.get("targeted_protection_intensity", MODEL_DEFAULTS["targeted_protection_intensity"]))
        self.psych_efficacy_hazard_gain_self = max(0.0, float(kwargs.get("psych_efficacy_hazard_gain_self", MODEL_DEFAULTS["psych_efficacy_hazard_gain_self"]) or MODEL_DEFAULTS["psych_efficacy_hazard_gain_self"]))
        self.psych_efficacy_hazard_gain_response = max(0.0, float(kwargs.get("psych_efficacy_hazard_gain_response", MODEL_DEFAULTS["psych_efficacy_hazard_gain_response"]) or MODEL_DEFAULTS["psych_efficacy_hazard_gain_response"]))
        self.psych_efficacy_adapt_rate = max(0.0, min(1.0, float(kwargs.get("psych_efficacy_adapt_rate", MODEL_DEFAULTS["psych_efficacy_adapt_rate"]) or MODEL_DEFAULTS["psych_efficacy_adapt_rate"])))
        self.psych_efficacy_decay_rate = max(0.0, min(1.0, float(kwargs.get("psych_efficacy_decay_rate", MODEL_DEFAULTS["psych_efficacy_decay_rate"]) or MODEL_DEFAULTS["psych_efficacy_decay_rate"])))
        self.psych_symptom_pressure = max(0.0, min(1.0, float(kwargs.get("psych_symptom_pressure", MODEL_DEFAULTS["psych_symptom_pressure"]) or MODEL_DEFAULTS["psych_symptom_pressure"])))
        # Share of institutional operational/procurement spend that flows into business revenue.
        # 1.0 preserves prior behavior.
        self.institutional_procurement_pass_through = max(0.0, min(1.0, float(kwargs.get("institutional_procurement_pass_through", MODEL_DEFAULTS["institutional_procurement_pass_through"]) or MODEL_DEFAULTS["institutional_procurement_pass_through"])))
        self.stochasticity_level = max(0.0, min(0.25, float(kwargs.get("stochasticity_level", MODEL_DEFAULTS["stochasticity_level"]) or MODEL_DEFAULTS["stochasticity_level"])))
        self.decision_jitter_rel = max(0.0, min(0.25, float(kwargs.get("decision_jitter_rel", self.stochasticity_level))))
        self.threshold_jitter_rel = max(0.0, min(0.25, float(kwargs.get("threshold_jitter_rel", self.stochasticity_level))))
        self.health_jitter_rel = max(0.0, min(0.25, float(kwargs.get("health_jitter_rel", self.stochasticity_level))))
        self.mobility_jitter_rel = max(0.0, min(0.25, float(kwargs.get("mobility_jitter_rel", self.stochasticity_level))))
        self.decision_params = DecisionParams(
            w_depth=float(kwargs.get("decision_w_depth", MODEL_DEFAULTS["decision_w_depth"])),
            w_imminence=float(kwargs.get("decision_w_imminence", MODEL_DEFAULTS["decision_w_imminence"])),
            w_official=float(kwargs.get("decision_w_official", MODEL_DEFAULTS["decision_w_official"])),
            w_social=float(kwargs.get("decision_w_social", MODEL_DEFAULTS["decision_w_social"])),
            w_memory=float(kwargs.get("decision_w_memory", MODEL_DEFAULTS["decision_w_memory"])),
            w_disease=float(kwargs.get("decision_w_disease", MODEL_DEFAULTS["decision_w_disease"])),
            a_self=float(kwargs.get("decision_a_self", MODEL_DEFAULTS["decision_a_self"])),
            a_resp=float(kwargs.get("decision_a_response", MODEL_DEFAULTS["decision_a_response"])),
            a_soc=float(kwargs.get("decision_a_social", MODEL_DEFAULTS["decision_a_social"])),
            a_cost=float(kwargs.get("decision_a_cost", MODEL_DEFAULTS["decision_a_cost"])),
            beta0=float(kwargs.get("decision_beta0", MODEL_DEFAULTS["decision_beta0"])),
            betaT=float(kwargs.get("decision_beta_threat", MODEL_DEFAULTS["decision_beta_threat"])),
            betaC=float(kwargs.get("decision_beta_coping", MODEL_DEFAULTS["decision_beta_coping"])),
            beta0_prep=float(kwargs.get("decision_beta0_prepare", MODEL_DEFAULTS["decision_beta0_prepare"])),
            betaT_prep=float(kwargs.get("decision_beta_threat_prepare", MODEL_DEFAULTS["decision_beta_threat_prepare"])),
            betaC_prep=float(kwargs.get("decision_beta_coping_prepare", MODEL_DEFAULTS["decision_beta_coping_prepare"])),
            gamma0=float(kwargs.get("decision_gamma0", MODEL_DEFAULTS["decision_gamma0"])),
            gammaH=float(kwargs.get("decision_gamma_habitability", MODEL_DEFAULTS["decision_gamma_habitability"])),
            gammaC=float(kwargs.get("decision_gamma_coping", MODEL_DEFAULTS["decision_gamma_coping"])),
        )
        self.warning_pre_flood_base = min(1.0, self.warning_pre_flood_base * (1.0 + 0.80 * self.risk_communication_intensity))
        self.survivability_duration_scale = max(0.1, float(kwargs.get("survivability_duration_scale", MODEL_DEFAULTS["survivability_duration_scale"]) or MODEL_DEFAULTS["survivability_duration_scale"]))
        self.stranded_mortality_rate_scale = max(0.0, float(kwargs.get("stranded_mortality_rate_scale", MODEL_DEFAULTS["stranded_mortality_rate_scale"]) or MODEL_DEFAULTS["stranded_mortality_rate_scale"]))
        self.stranded_mortality_hazard_threshold = max(0.0, float(kwargs.get("stranded_mortality_hazard_threshold", MODEL_DEFAULTS["stranded_mortality_hazard_threshold"]) or MODEL_DEFAULTS["stranded_mortality_hazard_threshold"]))
        self.stranded_mortality_prob_cap = max(0.0, min(1.0, float(kwargs.get("stranded_mortality_prob_cap", MODEL_DEFAULTS["stranded_mortality_prob_cap"]) or MODEL_DEFAULTS["stranded_mortality_prob_cap"])))
    
        # A single inundation footprint is activated for the flood period.
        self.flood_start_hour = int(self.last_evacuation_time + 1)
        self.flood_end_hour = int(self._during_end_h)
        flood_duration_hours = max(1, self.flood_end_hour - self.flood_start_hour)
        if self.flood_wave_rise_hours <= 1.0:
            self.flood_wave_rise_hours = float(max(1, round(flood_duration_hours * 0.35)))
        if self.flood_wave_fall_hours <= 1.0:
            self.flood_wave_fall_hours = float(max(1, round(flood_duration_hours * 0.35)))
        self.flood_wave_peak_hour = int(self.flood_end_hour - self.flood_wave_fall_hours)
    
        self.total_days = self.baseline_days + self.pre_flood_days + self.flood_days + self.post_flood_days
        self.max_hours  = int(self._post_end_h)
    
        # Let the visualization stop when the run is finished.
        self.running = True
        self.progress_file = kwargs.get("progress_file")

        self.disaster_period: str | None = None
        self.event_phase: str | None = None
        
        self.hours_before_rescue = max(0, int(kwargs.get("hours_before_rescue", MODEL_DEFAULTS["hours_before_rescue"]) or MODEL_DEFAULTS["hours_before_rescue"]))
        self.hours_before_healthcare = 0
        self.gov_baseline_share_shelter = max(0.0, float(kwargs.get("gov_baseline_share_shelter", MODEL_DEFAULTS["gov_baseline_share_shelter"]) or MODEL_DEFAULTS["gov_baseline_share_shelter"]))
        self.gov_baseline_share_healthcare = max(0.0, float(kwargs.get("gov_baseline_share_healthcare", MODEL_DEFAULTS["gov_baseline_share_healthcare"]) or MODEL_DEFAULTS["gov_baseline_share_healthcare"]))
        self.gov_baseline_share_school = max(0.0, float(kwargs.get("gov_baseline_share_school", MODEL_DEFAULTS["gov_baseline_share_school"]) or MODEL_DEFAULTS["gov_baseline_share_school"]))
        self.gov_event_shelter_grant_scale = max(0.0, float(kwargs.get("gov_event_shelter_grant_scale", MODEL_DEFAULTS["gov_event_shelter_grant_scale"]) or MODEL_DEFAULTS["gov_event_shelter_grant_scale"]))
        self.gov_event_healthcare_grant_scale = max(0.0, float(kwargs.get("gov_event_healthcare_grant_scale", MODEL_DEFAULTS["gov_event_healthcare_grant_scale"]) or MODEL_DEFAULTS["gov_event_healthcare_grant_scale"]))

        # Population and capacity.
        self.num_persons = N_persons
        
        self.perc_education_people = float(kwargs.get("perc_education_people", MODEL_DEFAULTS.get("perc_education_people", 0.89)) or MODEL_DEFAULTS.get("perc_education_people", 0.89))

        # Population composition controls (normalized later).
        self.male_share_pct = float(kwargs.get("male_share_pct", MODEL_DEFAULTS["male_share_pct"]))
        self.female_share_pct = float(kwargs.get("female_share_pct", MODEL_DEFAULTS["female_share_pct"]))
        self.age_0_14_pct = float(kwargs.get("age_0_14_pct", MODEL_DEFAULTS["age_0_14_pct"]))
        self.age_15_64_pct = float(kwargs.get("age_15_64_pct", MODEL_DEFAULTS["age_15_64_pct"]))
        self.age_65_100_pct = float(kwargs.get("age_65_100_pct", MODEL_DEFAULTS["age_65_100_pct"]))
        self.ethnicity_white_pct = float(kwargs.get("ethnicity_white_pct", MODEL_DEFAULTS["ethnicity_white_pct"]))
        self.ethnicity_black_pct = float(kwargs.get("ethnicity_black_pct", MODEL_DEFAULTS["ethnicity_black_pct"]))
        self.ethnicity_hispanic_pct = float(kwargs.get("ethnicity_hispanic_pct", MODEL_DEFAULTS["ethnicity_hispanic_pct"]))
        self.ethnicity_other_pct = float(kwargs.get("ethnicity_other_pct", MODEL_DEFAULTS["ethnicity_other_pct"]))
        self.min_ethnicity_group_size = max(1, int(kwargs.get("min_ethnicity_group_size", MODEL_DEFAULTS["min_ethnicity_group_size"]) or MODEL_DEFAULTS["min_ethnicity_group_size"]))
        self.worldview_hierarchist_pct = float(kwargs.get("worldview_hierarchist_pct", MODEL_DEFAULTS["worldview_hierarchist_pct"]))
        self.worldview_egalitarian_pct = float(kwargs.get("worldview_egalitarian_pct", MODEL_DEFAULTS["worldview_egalitarian_pct"]))
        self.worldview_individualist_pct = float(kwargs.get("worldview_individualist_pct", MODEL_DEFAULTS["worldview_individualist_pct"]))
        self.worldview_fatalist_pct = float(kwargs.get("worldview_fatalist_pct", MODEL_DEFAULTS["worldview_fatalist_pct"]))
        
        self.num_houses = len(self.space.houses)
        self.num_businesses = len(self.space.businesses)
        self.num_schools = len(self.space.schools)

        self.shelter_cap_limit = shelter_cap_limit / 100 * N_persons
        self.healthcare_cap_limit = healthcare_cap_limit / 100 * N_persons
        
        # Scenario architecture and hazard switches.
        scenario_defaults = {
            "enable_flood": kwargs.get("enable_flood", 1),
            "enable_infectious": kwargs.get("enable_infectious", 0),
            "enable_vectorborne": kwargs.get("enable_vectorborne", kwargs.get("enable_stagnant", 1)),
            "enable_mold": kwargs.get("enable_mold", 1),
        }
        scenario_raw = kwargs.get("scenario_mode", kwargs.get("scenario_mode_code", 6))
        scenario_cfg = resolve_scenario_configuration(scenario_raw, scenario_defaults)

        self.scenario_mode = str(scenario_cfg["scenario_mode"])
        self.scenario_label = self.scenario_mode.replace("_", " ").title()

        output_root_kw = kwargs.get("output_root", None)
        if output_root_kw:
            self.output_root = Path(output_root_kw).resolve()
        else:
            self.output_root = (ROOT / "outputs" / "serverrun").resolve()
        self.serverrun_run_dir = (self.output_root / self.scenario_mode / self.run_id).resolve()
        self.enable_flood = bool(scenario_cfg["enable_flood"])
        self.enable_infectious = bool(scenario_cfg["enable_infectious"])
        self.enable_stagnant = bool(scenario_cfg["enable_stagnant"])
        self.enable_vectorborne = self.enable_stagnant
        self.enable_mold = bool(scenario_cfg["enable_mold"])
        self.enable_disease_system = bool(scenario_cfg["enable_disease_system"])
        # Numeric parameters are scenario-invariant. Scenario selection only
        # controls which processes are enabled, so results remain comparable.
        self.infectious_mortality_hazard = max(0.0, float(kwargs.get("infectious_mortality_hazard", MODEL_DEFAULTS["infectious_mortality_hazard"]) or MODEL_DEFAULTS["infectious_mortality_hazard"]))
        self.infectious_course_hours = max(48, int(kwargs.get("infectious_course_hours", MODEL_DEFAULTS["infectious_course_hours"]) or MODEL_DEFAULTS["infectious_course_hours"]))
        self.infectious_peak_hours = max(12, int(kwargs.get("infectious_peak_hours", MODEL_DEFAULTS["infectious_peak_hours"]) or MODEL_DEFAULTS["infectious_peak_hours"]))
        self.infectious_beta_base = max(0.0, float(kwargs.get("infectious_beta_base", MODEL_DEFAULTS["infectious_beta_base"]) or MODEL_DEFAULTS["infectious_beta_base"]))
        self.infectious_contact_intensity = max(0.0, float(kwargs.get("infectious_contact_intensity", MODEL_DEFAULTS["infectious_contact_intensity"]) or MODEL_DEFAULTS["infectious_contact_intensity"]))
        self.infectious_severity_scale = max(0.0, float(kwargs.get("infectious_severity_scale", MODEL_DEFAULTS["infectious_severity_scale"]) or MODEL_DEFAULTS["infectious_severity_scale"]))
        self.infectious_gamma = max(0.0, min(1.0, float(kwargs.get("infectious_gamma", MODEL_DEFAULTS["infectious_gamma"]) or MODEL_DEFAULTS["infectious_gamma"])))
        self.infectious_waning = max(0.0, min(1.0, float(kwargs.get("infectious_waning", MODEL_DEFAULTS["infectious_waning"]) or MODEL_DEFAULTS["infectious_waning"])))
        self.infectious_seed_share = max(0.0, min(1.0, float(kwargs.get("infectious_seed_share", MODEL_DEFAULTS["infectious_seed_share"]) or MODEL_DEFAULTS["infectious_seed_share"])))
        self.infectious_seed_start_hour = max(0, int(kwargs.get("infectious_seed_start_hour", MODEL_DEFAULTS["infectious_seed_start_hour"]) or MODEL_DEFAULTS["infectious_seed_start_hour"]))
        self.vector_hospital_seek_prob = max(0.0, min(1.0, float(kwargs.get("vector_hospital_seek_prob", MODEL_DEFAULTS["vector_hospital_seek_prob"]) or MODEL_DEFAULTS["vector_hospital_seek_prob"])))
        self.healthcare_max_stay_hours = max(24, int(kwargs.get("healthcare_max_stay_hours", MODEL_DEFAULTS["healthcare_max_stay_hours"]) or MODEL_DEFAULTS["healthcare_max_stay_hours"]))
        self.mold_hospital_seek_prob = max(0.0, min(1.0, float(kwargs.get("mold_hospital_seek_prob", MODEL_DEFAULTS["mold_hospital_seek_prob"]) or MODEL_DEFAULTS["mold_hospital_seek_prob"])))
        self.vector_healthcare_cost_multiplier = max(0.1, float(kwargs.get("vector_healthcare_cost_multiplier", MODEL_DEFAULTS["vector_healthcare_cost_multiplier"]) or MODEL_DEFAULTS["vector_healthcare_cost_multiplier"]))
        self.mold_healthcare_cost_multiplier = max(0.1, float(kwargs.get("mold_healthcare_cost_multiplier", MODEL_DEFAULTS["mold_healthcare_cost_multiplier"]) or MODEL_DEFAULTS["mold_healthcare_cost_multiplier"]))
        self.mold_symptom_threshold = max(0.0, min(1.0, float(kwargs.get("mold_symptom_threshold", MODEL_DEFAULTS["mold_symptom_threshold"]) or MODEL_DEFAULTS["mold_symptom_threshold"])))
        self.mold_functional_capacity = max(0.0, min(1.0, float(kwargs.get("mold_functional_capacity", MODEL_DEFAULTS["mold_functional_capacity"]) or MODEL_DEFAULTS["mold_functional_capacity"])))
        self.vector_functional_capacity = max(0.0, min(1.0, float(kwargs.get("vector_functional_capacity", MODEL_DEFAULTS["vector_functional_capacity"]) or MODEL_DEFAULTS["vector_functional_capacity"])))
        self.injury_hospital_recovery_boost = max(1.0, float(kwargs.get("injury_hospital_recovery_boost", MODEL_DEFAULTS["injury_hospital_recovery_boost"]) or MODEL_DEFAULTS["injury_hospital_recovery_boost"]))

        # Stagnant-pool hazard physics and policy.
        self.stagnant_half_life_h = float(kwargs.get("stagnant_half_life_h", MODEL_DEFAULTS["stagnant_half_life_h"]))
        self.stagnant_influence_m = float(kwargs.get("stagnant_influence_m", MODEL_DEFAULTS["stagnant_influence_m"]))
        self.stagnant_lifetime_min_h = float(kwargs.get("stagnant_lifetime_min_h", MODEL_DEFAULTS["stagnant_lifetime_min_h"]))
        self.stagnant_lifetime_max_h = float(kwargs.get("stagnant_lifetime_max_h", MODEL_DEFAULTS["stagnant_lifetime_max_h"]))
        self.vector_control_intensity = float(kwargs.get("vector_control_intensity", MODEL_DEFAULTS["vector_control_intensity"]))  # 0..1
        self.vector_exposure_hazard = max(0.0, float(kwargs.get("vector_exposure_hazard", MODEL_DEFAULTS["vector_exposure_hazard"]) or MODEL_DEFAULTS["vector_exposure_hazard"]))
        # Keep infectious disease effects from silently altering flood evacuation behavior unless explicitly requested.
        self.infectious_threat_coupling = max(0.0, min(1.0, float(kwargs.get("infectious_threat_coupling", MODEL_DEFAULTS["infectious_threat_coupling"]) or MODEL_DEFAULTS["infectious_threat_coupling"])))
        
        # Random selection controls for stagnant pools.
        self.stagnant_seed = kwargs.get("stagnant_seed", self.random_seed ^ 0x9E3779B9)
        self.stagnant_keep_fraction = max(0.0, min(1.0, float(kwargs.get("stagnant_keep_fraction", MODEL_DEFAULTS["stagnant_keep_fraction"]) or MODEL_DEFAULTS["stagnant_keep_fraction"])))
        self.stagnant_shrink_min = max(0.0, float(kwargs.get("stagnant_shrink_min", MODEL_DEFAULTS["stagnant_shrink_min"]) or MODEL_DEFAULTS["stagnant_shrink_min"]))
        self.stagnant_shrink_max = max(self.stagnant_shrink_min, float(kwargs.get("stagnant_shrink_max", MODEL_DEFAULTS["stagnant_shrink_max"]) or MODEL_DEFAULTS["stagnant_shrink_max"]))
        self.stagnant_min_area = max(0.0, float(kwargs.get("stagnant_min_area", MODEL_DEFAULTS["stagnant_min_area"]) or MODEL_DEFAULTS["stagnant_min_area"]))
        self.stagnant_area_fraction = max(0.0, min(1.0, float(kwargs.get("stagnant_area_fraction", MODEL_DEFAULTS["stagnant_area_fraction"]) or MODEL_DEFAULTS["stagnant_area_fraction"])))
        self.stagnant_simplify_tolerance = max(0.0, float(kwargs.get("stagnant_simplify_tolerance", MODEL_DEFAULTS["stagnant_simplify_tolerance"]) or MODEL_DEFAULTS["stagnant_simplify_tolerance"]))
        self.stagnant_max_spots_per_wave = max(1, int(kwargs.get("stagnant_max_spots_per_wave", MODEL_DEFAULTS["stagnant_max_spots_per_wave"]) or MODEL_DEFAULTS["stagnant_max_spots_per_wave"]))
        self.stagnant_max_source_polygons = max(1, int(kwargs.get("stagnant_max_source_polygons", MODEL_DEFAULTS["stagnant_max_source_polygons"]) or MODEL_DEFAULTS["stagnant_max_source_polygons"]))

        # GDP allocation.
        self._allocate_gdp()

        # Institutional agents are registered by StudyArea.
        self.gov_baseline_grant_every_hours = int(kwargs.get("gov_baseline_grant_every_hours", MODEL_DEFAULTS["gov_baseline_grant_every_hours"]))

        self.government = self.space.government[0]
        self.government.wealth = self.government_gdp * max(0.0, float(self.government_initial_wealth_factor))
        self.government.baseline_every_hours = max(1, int(self.gov_baseline_grant_every_hours))

        self.shelter = self.shelters[0] if self.shelters else None
        shelter_caps = self._split_service_capacity(self.shelter_cap_limit, len(self.shelters))
        for shelter, capacity in zip(self.shelters, shelter_caps):
            shelter.capacity_limit = capacity
            shelter.wealth = shelter_funding if shelter_funding is not None else self.shelter_gdp

        self.healthcare = self.healthcares[0] if self.healthcares else None
        effective_healthcare_capacity = self.healthcare_cap_limit * (1.0 + max(0.0, self.healthcare_surge_factor))
        healthcare_caps = self._split_service_capacity(effective_healthcare_capacity, len(self.healthcares))
        for healthcare, capacity in zip(self.healthcares, healthcare_caps):
            healthcare.capacity_limit = capacity
            healthcare.wealth = healthcare_funding if healthcare_funding is not None else self.healthcare_gdp

        # Businesses and schools.
        self._init_businesses()
        self._init_schools()
        # Houses need no extra setup beyond assigned resilience.

        # Disease modules.
        mods = []
        if self.enable_infectious:
            mods.append(
                InfectiousModule(
                    beta_base=self.infectious_beta_base,
                    contact_intensity=self.infectious_contact_intensity,
                    gamma=self.infectious_gamma,
                    waning=self.infectious_waning,
                    seed_share=self.infectious_seed_share,
                )
            )
        if self.enable_stagnant:
            mods.append(VectorborneModule())
        if self.enable_mold:
            mods.append(MoldModule())
        self.disease = DiseaseManager(mods)
        self.flood = FloodManager([RiverFloodModule()])
        
        # Optional wage hook that scales wage by productivity.
        def effective_wage(person, base):
            mult = float(getattr(person, "productivity_mult", 1.0) or 1.0)
            income_scale = max(0.0, float(self.person_income_growth_scale))
            return base * max(0.0, mult) * income_scale
        self.effective_wage = effective_wage   
        
        # Create person agents.
        psn_agnt.create_person_agents(self)

        # Initialize data collection.
        data_collection(self)
        
        
    # ------------------------------------------------------------------ #
    # 2. Step
    # ------------------------------------------------------------------ #
    def step(self):
        # Stop cleanly when the run reaches the configured end.
        if self.hours >= self.max_hours:
            self.running = False
            return
    
        try:
            h = self.hours
    
            # Keep non-flood scenarios in baseline for the full run.
            if not self.enable_flood:
                self.event_phase = "baseline"
                self.disaster_period = "baseline"
            # Phase labels for flood-enabled scenarios.
            elif h < self._baseline_end_h:
                self.event_phase = "baseline"
                self.disaster_period = "baseline"
            elif h < self._preflood_end_h:
                self.event_phase = "warning"
                self.disaster_period = "pre_flood"
            elif h < self._during_end_h:
                self.event_phase = "event"
                self.disaster_period = "during_flood"
            else:
                self.event_phase = "recovery"
                self.disaster_period = "post_flood"
    
            # Flood system pass.
            if self.enable_flood:
                self.flood.step(self)
    
            # Step place-based agents.
            for a in self.space.houses:     a.step()
            for b in self.space.businesses: b.step()
            for s in self.space.schools:    s.step()
            for shelter in self.shelters:
                shelter.step()
            for healthcare in self.healthcares:
                healthcare.step()
            if self.government: self.government.step()
            # Disease system pass reads the latest service-state values.
            self.disease.step(self)

            # Apply disease to persons once per hour.
            for p in self.people:
                # disease first → actions can react (e.g., care-seeking)
                self.disease.apply_to_person(self, p)
                p.step()

            # Canonicalize flags into exclusive person states.
            self._enforce_exclusive_person_states()

            # Collect outputs.
            self.datacollector.collect(self)

            if self.progress_file:
                from pathlib import Path
                import json
                progress_path = Path(self.progress_file)
                progress_path.parent.mkdir(parents=True, exist_ok=True)
                progress_payload = (
                    f"replication={int(self.replication) + 1} "
                    f"hour={int(self.hours)} max_hours={int(self.max_hours)}"
                )
                temporary_path = progress_path.with_suffix(progress_path.suffix + ".tmp")
                temporary_path.write_text(progress_payload, encoding="utf-8")
                temporary_path.replace(progress_path)

        except Exception:
            import traceback
            error_text = traceback.format_exc()
            try:
                self.output_root.mkdir(parents=True, exist_ok=True)
                with (self.output_root / "model_errors.log").open("a", encoding="utf-8") as error_log:
                    error_log.write(f"\n--- model step failed at hour {h} ---\n{error_text}")
            except Exception:
                pass
            logger.exception("Model step failed at hour %s", h)
            raise
        finally:
            self.hours += 1
            if self.hours >= self.max_hours:
                self.running = False
            if not self.running:
                try:
                    if self.auto_export_on_finish:
                        out_dir = self.serverrun_run_dir
                        out_dir.mkdir(parents=True, exist_ok=True)
                        df = self.datacollector.get_model_vars_dataframe().reset_index(drop=True)
                        df.to_csv(out_dir / "serverrun_results.csv", index=False)
                        export_timeseries(self, out_dir)
                        export_person_panel(self, out_dir)
                        export_summary(self, out_dir)
                except Exception as e:
                    print("Could not save results:", e)

    # ------------------------------------------------------------------ #
    # 3. Flood map helpers
    # ------------------------------------------------------------------ #
    def add_flood_maps(self, flood_file: str):
        self.space._load_flood_maps_from_file(self, flood_file, self.crs)

    def remove_flood_maps(self, flood_file: str):
        # Compute effective half-life first.
        eff_hl = float(self.stagnant_half_life_h)
        if self.vector_control_intensity > 0.0:
            factor = max(0.5, 1.0 - 0.6 * float(self.vector_control_intensity))
            eff_hl = max(24.0, eff_hl * factor)
    
        # Spawn stagnant pools with the adjusted half-life.
        if self.enable_stagnant:
            try:
                # Temporarily set the model knob so the loader reads the adjusted value.
                prev = self.stagnant_half_life_h
                self.stagnant_half_life_h = eff_hl
                self.space.add_stagnant_from_flood_file(self, flood_file, self.crs, spawn_hour=self.hours)
                self.stagnant_half_life_h = prev
            except Exception:
                logger.exception("Could not spawn stagnant pools at flood end (hour %s)", self.hours)
                self.stagnant_half_life_h = prev
    
        # Then remove flood polygons.
        self.space.remove_flood_maps(flood_file)



    # ------------------------------------------------------------------ #
    # 4 · GDP & INITIAL WEALTH
    # ------------------------------------------------------------------ #
    def _allocate_gdp(self):
        days = float(MODEL_DEFAULTS["gdp_allocation_days"])
        self.business_gdp   = (self.num_persons * MODEL_DEFAULTS["business_annual_output_per_person"]) / 365 * days
        self.school_gdp     = (self.num_persons * MODEL_DEFAULTS["school_annual_output_per_person"]) / 365 * days
        self.shelter_gdp    = (self.num_persons * MODEL_DEFAULTS["shelter_annual_output_per_person"]) / 365 * days
        self.healthcare_gdp = (self.num_persons * MODEL_DEFAULTS["healthcare_annual_output_per_person"]) / 365 * days
        self.government_gdp = (self.num_persons * MODEL_DEFAULTS["government_annual_output_per_person"]) / 365 * days
        self.persons_gdp    = 0
        self.total_gdp = (
            self.business_gdp
            + self.school_gdp
            + self.shelter_gdp
            + self.healthcare_gdp
            + self.government_gdp
        )

    def _init_businesses(self):
        if self.num_businesses <= 0:
            return
        avg = (self.business_gdp / self.num_businesses) * max(0.0, float(self.business_initial_wealth_factor))
        for b in self.space.businesses:
            b.wealth = avg
    
    def _init_schools(self):
        if self.num_schools <= 0:
            return
        avg = self.school_gdp / self.num_schools
        for s in self.space.schools:
            s.wealth = avg

    # ------------------------------------------------------------------ #
    # 5 · SUPPORT FUNCTIONS
    # ------------------------------------------------------------------ #
    def notify_shelter(self, agent):
        """
        Ask the shelter to schedule a rescue for a stranded person.
        Actual pickup + admission is handled inside Shelter.step()
        when ETA arrives and capacity allows.
        """
        if not agent.alive:
            return
        if not agent.stranded:
            return
        # throttle: only after some stranded time, if you want to keep it
        if agent.time_stranded < self.hours_before_rescue:
            return
    
        shelter = self._nearest_available_shelter(agent)
        if shelter:
            shelter.request_rescue(agent)
   

    def receive_healthcare(self, patient):
        hc = self._nearest_available_healthcare(patient)
        if not hc:
            return

        # Evacuated people are out of area until post-flood return logic.
        if patient.evacuated and self.disaster_period != "post_flood":
            return
    
        # If they're currently in shelter, use the shelter→hospital queue.
        if patient.in_shelter:
            shelter = self.shelter or self._nearest_available_shelter(patient)
            if shelter is not None:
                hc.request_admission_from_shelter(shelter, patient)
            return
    
        # Otherwise let the patient self-present (handles fee + ETA).
        hc.request_admission_self(patient)

    def _nearest_available_shelter(self, agent):
        shelters = self.shelters
        if not shelters:
            return None
        pt = agent.geometry
        if pt is None:
            return shelters[0]
        open_shelters = [s for s in shelters if s.has_capacity()]
        candidates = open_shelters or shelters
        return min(candidates, key=lambda shelter: shelter.geometry.distance(pt))

    @staticmethod
    def _split_service_capacity(total_capacity: float, facility_count: int) -> list[int]:
        """Split a population-wide capacity target across service sites."""
        count = max(0, int(facility_count))
        if count == 0:
            return []
        total = max(0, int(round(float(total_capacity))))
        base, remainder = divmod(total, count)
        return [base + int(index < remainder) for index in range(count)]

    def _nearest_available_healthcare(self, agent):
        healthcares = self.healthcares
        if not healthcares:
            return None
        pt = agent.geometry
        if pt is None:
            return healthcares[0]
        open_hc = [h for h in healthcares if len(h.hospitalized_agents) < int(h.capacity_limit)]
        candidates = open_hc or healthcares
        return min(candidates, key=lambda healthcare: healthcare.geometry.distance(pt))

    @staticmethod
    def _rand_point(poly) -> Point:
        minx, miny, maxx, maxy = poly.bounds
        while True:
            p = Point(random.uniform(minx, maxx), random.uniform(miny, maxy))
            if poly.contains(p):
                return p


    def _enforce_exclusive_person_states(self):
        """Keep person status flags mutually exclusive.

        Priority for alive agents: healthcare > shelter > stranded > evacuated > normal.
        Dead agents are removed from all living-state flags.
        """
        people = self.people
        if not people:
            return

        hc_agents = set(self.healthcare.hospitalized_agents) if self.healthcare else set()
        sh_agents = set(self.shelter.sheltered_agents) if self.shelter else set()
        phase = self.disaster_period

        hc_obj = self.healthcare
        sh_obj = self.shelter

        def remove_from_service_state(person):
            if hc_obj is not None:
                if person in hc_obj.hospitalized_agents:
                    hc_obj.hospitalized_agents.remove(person)
                hc_obj._pending_admissions.pop(person, None)
            if sh_obj is not None:
                if person in sh_obj.sheltered_agents:
                    sh_obj.sheltered_agents.remove(person)
                sh_obj._pending_rescues.pop(person, None)

        for p in people:
            if not p.alive:
                p.stranded = False
                p.in_shelter = False
                p.evacuated = False
                remove_from_service_state(p)
                continue

            # Hard lock: evacuated agents remain out-of-area until post-flood.
            if p.evacuated and phase != "post_flood":
                p.in_shelter = False
                p.stranded = False
                remove_from_service_state(p)
                try:
                    p._remove_from_map()
                except Exception:
                    pass
                continue

            in_hc = p in hc_agents
            in_sh = (p in sh_agents) or p.in_shelter
            is_stranded = p.stranded
            is_evacuated = p.evacuated

            if in_hc:
                p.in_shelter = False
                p.stranded = False
                p.evacuated = False
                if sh_obj is not None and p in sh_obj.sheltered_agents:
                    sh_obj.sheltered_agents.remove(p)
                if sh_obj is not None:
                    sh_obj._pending_rescues.pop(p, None)
            elif in_sh:
                p.in_shelter = True
                p.stranded = False
                p.evacuated = False
                if hc_obj is not None and p in hc_obj.hospitalized_agents:
                    hc_obj.hospitalized_agents.remove(p)
                if hc_obj is not None:
                    hc_obj._pending_admissions.pop(p, None)
            elif is_stranded:
                p.in_shelter = False
                p.stranded = True
                p.evacuated = False
                remove_from_service_state(p)
            elif is_evacuated:
                p.in_shelter = False
                p.stranded = False
                p.evacuated = True
                remove_from_service_state(p)
            else:
                p.in_shelter = False
                p.stranded = False
                p.evacuated = False
                remove_from_service_state(p)


    def business_revenue(self, business, gross_amount: float):
        if gross_amount <= 0:
            return
        if not business.is_open():
            return

        # Tie realized business revenue to current staffing so post-flood understaffed
        # businesses cannot accrue near-full sales.
        staffing_ratio = 1.0
        emps = list(business.employees)
        if emps:
            active = [
                p for p in emps
            if p.alive
            and p.employed
            and p.workplace is business
            ]
            if active:
                present = 0
                for p in active:
                    try:
                        if business.geometry.contains(p.geometry):
                            present += 1
                    except Exception:
                        continue
                staffing_ratio = max(0.0, min(1.0, present / max(1, len(active))))

        revenue_mult = max(0.0, float(self.sales_revenue_multiplier))
        floor = max(0.0, min(1.0, float(self.business_revenue_staffing_floor)))
        elas = max(0.1, float(self.business_revenue_staffing_elasticity))
        staffing_scale = floor + (1.0 - floor) * (staffing_ratio ** elas)
        revenue_mult *= max(0.0, staffing_scale)

        gross_effective = gross_amount * revenue_mult
        if gross_effective <= 0:
            return
        corp_tax_rate = self.corporate_tax_rate
        corp_tax = gross_effective * corp_tax_rate
    
        # gov collects immediately
        if self.government:
            self.government.wealth += corp_tax
            # optional analytics
            self.government.total_corporate_tax += corp_tax
    
        net = gross_effective - corp_tax
        business.receive_net_revenue(net, gross_effective)

    def log_transaction(self, payload: dict):
        logger.info("transaction: %s", payload)