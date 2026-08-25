# -*- coding: utf-8 -*-
# Person agent implementation for the flood-disease ABM.
# Mesa-Geo 0.9.x / Mesa 3.x compatible.

# ----------------------------- Utilities -----------------------------

# Allow forward references in type hints.
from __future__ import annotations

# Standard library
import uuid, random, math
from dataclasses import dataclass
from typing import Optional, Dict, Any, Literal

# Third-party libraries
import numpy as np
from shapely.geometry import Point
from mesa_geo import GeoAgent                # Mesa-Geo base class for spatial agents

from agents import _personAssign as psn_agnt

from agents._house import House
from agents._school import School
from agents._business import Business


# ----------------------------- Utilities -----------------------------
def _clip01(x: float) -> float:
    """
    Clamp a number into the closed interval [0, 1].
    """
    return max(0.0, min(1.0, float(x)))

def _jitter_mul(base: float, rel: float) -> float:
    """Apply bounded multiplicative jitter around a base value."""
    r = max(0.0, float(rel or 0.0))
    if r <= 0.0:
        return float(base)
    return float(base) * random.uniform(max(0.0, 1.0 - r), 1.0 + r)

def _sigmoid(z: float) -> float:
    """
    Numerically stable logistic function: maps any real number to (0, 1).
    """
    if z >= 0:
        ez = math.exp(-z)
        return 1.0 / (1.0 + ez)
    else:
        ez = math.exp(z)
        return ez / (1.0 + ez)

def _worldview_gain(worldview: str) -> float:
    """
        Small worldview-based multiplier used in the threat calculation.
    """
    return {
        "hierarchist": 1.05,
        "egalitarian": 1.00,
        "individualist": 0.95,
        "fatalist": 1.10,
    }.get(worldview, 1.0)

@dataclass
class DecisionParams:
    """
    Tunable parameters for the decision kernel.
    """

    # Threat components (T)
    w_depth: float      = 0.40  # weight on water depth at/near home (strongest driver)
    w_imminence: float  = 0.15  # weight on how soon the flood hits (ramps up in pre-flood)
    w_official: float   = 0.12  # weight on official warning credibility × agent trust
    w_social: float     = 0.08  # weight on social signal (neighbors evacuating)
    w_memory: float     = 0.05  # weight on personal flood memory/experience
    w_disease: float    = 0.20  # weight on active disease pressure (mold/vector/infectious)

    # Coping components (C)
    a_self: float       = 0.40  # confidence in one’s own ability to act
    a_resp: float       = 0.30  # belief that the action (e.g., evacuating) is effective
    a_soc: float        = 0.20  # social support buffer (bonding/bridging/linking)
    a_cost: float       = 0.30  # penalty for costs (money, time, discomfort, risk)

    # Pre-flood decisions: evacuate vs prepare
    beta0: float        = -1.4  # baseline log-odds of evacuating with no threat/coping
    betaT: float        = 1.7   # how strongly threat pushes toward evacuating
    betaC: float        = 1.0   # how strongly coping pushes toward evacuating

    beta0_prep: float   = -1.0  # baseline log-odds of preparing (pack, sandbag, etc.)
    betaT_prep: float   = 1.5   # threat sensitivity for preparation
    betaC_prep: float   = 0.5   # coping sensitivity for preparation

    # Post-flood decision: return home
    gamma0: float       = -1.5  # baseline log-odds of returning with poor conditions
    gammaH: float       = 2.5   # sensitivity to home habitability (strong driver to return)
    gammaC: float       = 1.0   # coping still matters (resources to manage the return)

# ----------------------------- Person Agent -----------------------------
class Person(GeoAgent):
    """
    Person agents represent individual household members who respond to flood and disease conditions.

    The parent model supplies the active phase and timing; this class handles the person-level decision kernel.
    """

    def __init__(self, model=None, geometry=None, crs=None, unique_id=None, **kwargs):
        try:
            super().__init__(model=model, geometry=geometry, crs=crs, unique_id=unique_id)
        except TypeError:
            super().__init__(model, geometry, crs)
        self.name: str = str(uuid.uuid4())  # stable human-readable id for logs/exports
    
        # Demographics and identity
        self.age: int = 30
        self.gender: Literal["Male", "Female"] = "Male"
        self.ethnicity: Literal["White", "Black", "Hispanic", "Other"] = "Other"
        self.education: float = 0.5  # [0,1] normalized education proxy for decision/vulnerability models
        self.wealth_class: Literal["Upper_Class", "Upper_Middle_Class", "Middle_Class", "Lower_Class"] = "Middle_Class"
        self.income: float = 0.0  # earnings flow (units consistent with model economy)
    
        # Place attachments (home/work/school)
        self.household = None     # House agent (provides geometry/flood exposure/habitability)
        self.workplace = None     # Business agent (employment, wages)
        self.schoolplace = None   # School agent (attendance, lost-hours tracking)
    
        # Roles
        self.working_class: bool = False
        self.employed: bool = False
        self.student: bool = False
    
        # Social capital and trust
        self.bonding_count: float = _clip01(random.random())
        self.bridging_count: float = _clip01(random.random())
        self.linking_count: float  = _clip01(random.random())
        self.social_trust: float   = _clip01(float(random.choice([0, 1])))
        self.media_trust: float    = _clip01(float(random.choice([0, 1])))
        self.trust_in_authorities: float = _clip01(float(random.choice([0, 1])))
    
        # Decision-theory variables
        self.worldview: Literal["hierarchist", "egalitarian", "individualist", "fatalist"] = random.choice(
            ["hierarchist", "egalitarian", "individualist", "fatalist"]
        )
        self.self_efficacy: float     = _clip01(random.random())
        self.response_efficacy: float = _clip01(random.random())
        self.self_efficacy_baseline: float = self.self_efficacy
        self.response_efficacy_baseline: float = self.response_efficacy
        self.intention: float         = _clip01(random.random())
    
        # Vulnerability blend
        self.vulnerability_social: float   = 0.5
        self.vulnerability_physical: float = 0.5
        self.vulnerability: float          = 0.6 * self.vulnerability_social + 0.4 * self.vulnerability_physical

        # Agent-specific stochasticity multipliers sampled once per run.
        dec_rel = float(self.model.decision_jitter_rel)
        thr_rel = float(self.model.threshold_jitter_rel)
        hlt_rel = float(self.model.health_jitter_rel)
        mob_rel = float(self.model.mobility_jitter_rel)
        self._jit_decision = _jitter_mul(1.0, dec_rel)
        self._jit_threshold = _jitter_mul(1.0, thr_rel)
        self._jit_health = _jitter_mul(1.0, hlt_rel)
        self._jit_mobility = _jitter_mul(1.0, mob_rel)
    
        # Exposure proxies
        self.is_high_risk_area: int = 0
        self.flood_memory: float    = 0.5
    
        # Mobility and transport
        self.has_vehicle: Optional[bool] = None
        self.walk_speed_mps: float  = 1.2 * self._jit_mobility
        self.drive_speed_mps: float = 6.0 * self._jit_mobility
        # Flood resilience is sampled in the legacy 5..15 range and used as a depth tolerance.
        self.flood_resilience: float = random.uniform(
            float(self.model.person_resilience_min),
            float(self.model.person_resilience_max),
        )
    
        # Health baseline
        self.health_vulnerability: float = _clip01(0.5)  # comorbidity proxy
        self.alive: bool = True
    
        # Evacuation and sheltering state
        self.evacuated: bool = False
        self.in_shelter: bool = False
        self.stranded: bool = False
    
        # Time bookkeeping
        self.current_hour: int = 0  # increments each step; can diverge from model.hours if needed
        self.time_of_day: int = 0   # 0..23 local cycle for diurnal routines
        self._in_map: bool = True   # internal: whether agent is currently placed in geospace
    
        # Phase markers used for analytics
        self.preflood_prepared: bool = False
        self.duringflood_coped: bool = False
        self.postflood_adapt_planned: bool = False
        self.last_action: str = "Routine"
        self.last_decision_phase: str = "baseline"
        self.next_decision_hour: int = 0
        self.last_decision_eval_hour: int = -1
        self.decision_phase_offset: int = random.randint(0, max(0, int(self.model.decision_interval_hours) - 1))
        self.return_phase_offset: int = random.randint(0, max(0, int(self.model.return_decision_interval_hours) - 1))
    
        # Hazard-driven timers and states
        self.injured: bool = False
        self.time_stranded: int = 0
        self.time_injured: int = 0
        self.time_in_shelter: int = 0
        self.injury_duration: int = random.randint(12, 60)  # hours to likely injury if stranded in hazard
        self.survivability_duration: int = self.injury_duration + random.randint(70, 120)  # beyond this, death risk ↑
        self.survivability_duration = int(round(self.survivability_duration * float(self.model.survivability_duration_scale) * self._jit_health))
        self.recovery_rate: float = random.uniform(0.01, 0.05) * self._jit_health  # per-hour improvement when safe
    
        # Illness categories
        self.ill_respiratory: bool = False     # damp/mold-related respiratory illness
        self.ill_vector: bool = False          # vector-borne (e.g., mosquitoes)
        self.symp_mold: bool = False
        self.symp_vector: bool = False
        self.ill_respiratory_hours: int = 0
        self.ill_vector_hours: int = 0
    
        self.sick_hours_total: int = 0
        self.sick_hours_respiratory: int = 0
        self.sick_hours_vector: int = 0
        self.inf_severity: float = 0.0
        self.inf_peak_severity: float = 0.0
        self.inf_state: str = "S"
        self.inf_hours: int = 0
        self.inf_critical_hours: int = 0
        self.inf_rest_hours: int = 0
        self.inf_hospital_hours: int = 0
        self.inf_resting: bool = False
        self.medical_needs_hospitalization: bool = False
        self.death_cause: str | None = None

        # Economic impact ledgers
        self.evacuation_expense_accum: float = 0.0
        self.house_repair_expense_accum: float = 0.0
        self.healthcare_expense_flood_accum: float = 0.0
        self.healthcare_expense_mold_accum: float = 0.0
        self.healthcare_expense_vectorborne_accum: float = 0.0
        self.healthcare_expense_infectious_accum: float = 0.0
        self.healthcare_debt_accum: float = 0.0
        self.healthcare_debt_flood_accum: float = 0.0
        self.healthcare_debt_mold_accum: float = 0.0
        self.healthcare_debt_vectorborne_accum: float = 0.0
        self.healthcare_debt_infectious_accum: float = 0.0
        self.expense_variability_factor: float = random.uniform(0.75, 1.35)
        self.productivity_mult: float = 1.0

        # Cumulative impact flags for population-share graphs
        self.ever_affected_evacuated: bool = False
        self.ever_affected_flood: bool = False
        self.ever_affected_mold: bool = False
        self.ever_affected_vectorborne: bool = False
        self.ever_affected_infectious: bool = False
        self.ever_affected_stranded: bool = False
        self.ever_affected_sheltered: bool = False
        self.ever_affected_injured: bool = False
        self.ever_affected_hospitalized: bool = False
        self.ever_hc_flood: bool = False
        self.ever_hc_mold: bool = False
        self.ever_hc_vectorborne: bool = False
        self.ever_hc_infectious: bool = False
        self.ever_hc_compound: bool = False
    
        # Infectious disease state (optional SIR)
    def health_capacity(self) -> float:
        """Return functional capacity attributable to the person's health state."""
        cap = 1.0
        if self.injured:
            cap *= 0.6
        if self.ill_respiratory:
            cap *= float(getattr(self.model, "mold_functional_capacity", 0.85))
        if self.ill_vector:
            cap *= float(getattr(self.model, "vector_functional_capacity", 0.90))
        if getattr(self, "inf_state", "S") == "I":
            inf_severity = float(getattr(self, "inf_severity", 0.0) or 0.0)
            cap *= max(0.20, 1.0 - 1.10 * inf_severity)
            if bool(getattr(self, "inf_resting", False)):
                cap *= 0.35

        return max(0.0, min(1.0, cap))

    def activity_capacity(self) -> float:
        """Return a [0,1] activity multiplier from health and current constraints."""
        cap = self.health_capacity()
    
        # Context constraints: evacuation sheltering or being stranded
        if self.in_shelter or self.stranded:
            cap *= 0.5
    
        # Clamp to [0,1] to avoid drift due to multiple factors
        return max(0.0, min(1.0, cap))

    # --------------------------- Public Step Loop ----------------------------
    def step(self):
        """
        One hourly tick — minimal, publication-friendly state updates.
    
          1) Early exits & state checks
          2) Routine (if applicable)
          3) Decide & act (unified kernel)
          4) Health & experience updates
          5) Advance time & optional logging
        """
        # --- 1) early exits / status guards --------------------------------
        if not self.alive:
            self._remove_from_map()
            self.current_hour += 1
            return

        # Keep displacement states strictly one-hot at all times.
        self._enforce_location_state_invariants()

        # Retired/disabled pathways should not leak across scenarios.
        if not self.model.enable_stagnant:
            self.symp_vector = False
            self.ill_vector = False
            self.ill_vector_hours = 0
        # update clock
        self.time_of_day = self.current_hour % 24

        # If already evacuated, remain off-map until post-flood
        if self.evacuated and self.model.disaster_period != "post_flood":
            self._remove_from_map()
            self.current_hour += 1
            return

        # Housekeeping tied to flood safety of places (only for in-area agents).
        self._evict_if_place_now_unsafe()
    
        # --- 2) daily routine (only if not evacuated/sheltered/hospitalized) ---
        hc = self.model.healthcare
        hospitalized = hc and (self in getattr(hc, "hospitalized_agents", []))
        if (not self.evacuated) and (not self.in_shelter) and (not hospitalized):
            if self.injured:
                # Injured agents should seek care immediately and not keep normal roaming/work/school.
                self.productivity_mult = 0.0
                if self._is_flood_blocked(self.geometry):
                    self._stranded_behavior()
                else:
                    already_pending = bool(hc and (self in getattr(hc, "_pending_admissions", {})))
                    if hc and (not already_pending):
                        hc.request_admission_self(self)
                        self._emit("healthcare_self_request")
                self._rest_at_home()
            elif bool(getattr(self, "inf_resting", False)):
                self.productivity_mult = 0.0
                self._rest_at_home()
            else:
                # Pass effective capacity so routine can scale work/school/commute
                cap = self.activity_capacity()
                # Mirror into `productivity_mult` only if the rest of your code reads it.
                self.productivity_mult = cap
                self._daily_routine(capacity=cap)  # update your routine signature if needed
    
        # --- 3) unified decision: build context → decide → act ---------------
        ctx = self._build_context()            # derives inputs from model & self
        action_record = self._decide_and_act(ctx) 
        self._emit("decision", **action_record)  # structured event for analytics
    
        # --- 4) health progression & experience ------------------------------
        # Progress injury/illness timers & transitions (includes recovery)
        self._update_health_progression()
    
        # Exposure memory: gently increase with encountered flood depth
        self._update_flood_memory()
    
        # Bounded social capital evolution
        self._update_social_capital_bounded()

        # Let efficacy signals rise under active hazards and relax back toward baseline when quiet.
        self._update_psychology_signals(ctx)
    
        # ---- sickness accounting (paper-friendly) ---------------------------
        # Increment per-category sick hours; total counts any symptomatic hour.
        symptomatic = False
        if self.injured:
            symptomatic = True  # injuries are functionally limiting
            # This is the single elapsed-injury clock for field and hospital care.
            self.time_injured = int(self.time_injured) + 1
        if self.ill_respiratory:
            symptomatic = True
            self.sick_hours_respiratory = int(self.sick_hours_respiratory) + 1
        if self.ill_vector:
            symptomatic = True
            self.sick_hours_vector = int(self.sick_hours_vector) + 1
        if str(getattr(self, "inf_state", "S") or "S") == "I":
            symptomatic = True
        if symptomatic:
            self.sick_hours_total = int(self.sick_hours_total) + 1
    
        # Optional: gentle decay of total sick-hours when asymptomatic,
        # so long runs don’t overcount tail noise (purely cosmetic for plots).
        if not symptomatic and self.sick_hours_total > 0:
            self.sick_hours_total = max(0, self.sick_hours_total - 1)

        # ---- cumulative impact flags for scenario-level affected-population metrics ---------
        if self.evacuated:
            self.ever_affected_evacuated = True
        home = self.household
        if (
            self.evacuated
            or self.stranded
            or self.injured
            or bool(getattr(home, "flooded", False))
            or float(getattr(home, "last_depth", 0.0) or 0.0) > 0.0
        ):
            self.ever_affected_flood = True
        if self.stranded:
            self.ever_affected_stranded = True
        if self.in_shelter:
            self.ever_affected_sheltered = True
            self.ever_affected_stranded = True
        if self.injured:
            self.ever_affected_injured = True
        if bool(getattr(self, "symp_mold", False) or self.ill_respiratory):
            self.ever_affected_mold = True
        if bool(getattr(self, "symp_vector", False) or self.ill_vector):
            self.ever_affected_vectorborne = True
        if str(getattr(self, "inf_state", "S") or "S") == "I":
            self.ever_affected_infectious = True
    
        # ---- care seeking heuristics (lightweight, calibrated) --------------
        # Injury → strong care seeking
        if self.injured and random.random() < 0.05:
            self.model.receive_healthcare(self)
    
        # Illnesses with smaller but non-zero propensity to seek care
        # (Tunables for sensitivity analysis)
        if self.ill_respiratory and random.random() < 0.008:
            self.model.receive_healthcare(self)
        # --- 5) advance time & log -------------------------------------------
        self._enforce_location_state_invariants()
        self.current_hour += 1

    # -------------------- Core Decision Kernel --------------------
    def _decide_and_act(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """
        Phase-aware decision kernel.
        - baseline: no emergency decisions; agents just follow routine.
        - pre_flood / during_flood / post_flood: compute PMT signals and act.
        Returns a compact record for optional analytics.
        """
        phase = self.model.disaster_period
        scenario_mode = str(self.model.scenario_mode)

        # Baseline has no modeled hazard or emergency decision pathway.
        if scenario_mode == "baseline":
            self.last_threat, self.last_coping = 0.0, 0.0
            self.last_action = "Routine"
            self.last_decision_phase = "baseline"
            return {"phase": "baseline", "action": "Routine", "T": 0.0, "C": 0.0}

        # Perceptions evolve hourly for reporting and are the exact values used
        # whenever this person reaches a decision tick.
        params = self.model.decision_params
        T = self._compute_threat(ctx, params)
        C = self._compute_coping(ctx, params)
        self.last_threat, self.last_coping = T, C

        # Infectious-only runs report disease-driven perceptions, but retain
        # their routine-only behavior rather than entering flood evacuation logic.
        if scenario_mode == "infectious_disease":
            self.last_action = "Routine"
            self.last_decision_phase = "baseline"
            return {"phase": "baseline", "action": "Routine", "T": T, "C": C}

        # If already evacuated, stay off-map until post-flood return decisions begin.
        if self.evacuated and phase != "post_flood":
            self.last_action = "EvacuatedOutOfArea"
            self.last_decision_phase = str(phase or "baseline")
            return {"phase": str(phase or "baseline"), "action": "EvacuatedOutOfArea", "T": T, "C": C}

        # Sheltered people remain sheltered until discharge/transfer.
        if self.in_shelter and phase != "post_flood":
            self.last_action = "InShelter"
            self.last_decision_phase = str(phase or "baseline")
            return {"phase": str(phase or "baseline"), "action": "InShelter", "T": T, "C": C}

        # Decision cadence: evaluate emergency decisions at fixed intervals (no auto-evac).
        if phase in ("pre_flood", "during_flood", "post_flood"):
            if phase == "post_flood":
                interval_h = max(1, int(self.model.return_decision_interval_hours))
                phase_offset = self.return_phase_offset % interval_h
            else:
                interval_h = max(1, int(self.model.decision_interval_hours))
                phase_offset = self.decision_phase_offset % interval_h
            if self.last_decision_phase != str(phase):
                # Stagger first decision timing on phase change to avoid synchronized spikes.
                self.next_decision_hour = int(self.current_hour) + phase_offset
            if self.current_hour < self.next_decision_hour:
                self.last_action = "WaitNextDecisionTick"
                self.last_decision_phase = str(phase)
                return {"phase": str(phase), "action": "WaitNextDecisionTick", "T": T, "C": C}
            self.last_decision_eval_hour = int(self.current_hour)
            self.next_decision_hour = int(self.current_hour) + interval_h
    
        # --- Baseline: no protective decisions, just routine life -----------
        if phase == "baseline":
            # keep analytics sane (means = 0, not NaN)
            self.last_threat, self.last_coping = 0.0, 0.0
            self.last_action = "Routine"
            self.last_decision_phase = "baseline"
            return {"phase": "baseline", "action": "Routine", "T": 0.0, "C": 0.0}
    
        # --- Emergency phases use PMT/TPB signals ---------------------------
        if phase == "pre_flood":
            record = self._pre_flood_decision_and_action(T, C, ctx, params)
        elif phase == "during_flood":
            record = self._during_flood_decision_and_action(T, C, ctx, params)
        else:
            # treat anything else (e.g., post_flood) as recovery/return logic
            record = self._post_flood_decision_and_action(T, C, ctx, params)
    
        # expose theory drivers for analysis and persist the latest action for paper metrics
        record.update(self._theory_metrics(ctx, params))
        self.last_action = str(record.get("action", "Routine"))
        self.last_decision_phase = str(record.get("phase", phase or "baseline"))
        return record

    def _compute_threat(self, ctx: Dict[str, Any], p: DecisionParams) -> float:
        """Normalized Threat in [0,1] from hazard + signals (PMT)."""
        depth_home = ctx["depth_home"]                 # [0,1] e.g. depth/2m
        imminence  = ctx["imminence"]                  # [0,1]
        warn_off   = ctx["warning_official"] * _clip01(self.trust_in_authorities)
        social_sig = ctx["neighbors_evacuated_frac"] * _clip01(self.social_trust)
        memory     = _clip01(self.flood_memory)
    
        raw = (p.w_depth * depth_home +
               p.w_imminence * imminence +
               p.w_official * warn_off +
               p.w_social * social_sig +
             p.w_memory * memory +
             p.w_disease * _clip01(ctx["disease_pressure"]))
    
        # worldview can amplify/attenuate perceived threat
        return _clip01(raw * _worldview_gain(self.worldview))
    
    def _social_support(self) -> float:
        """Aggregate bonding/bridging/linking into [0,1] social support."""
        b  = _clip01(self.bonding_count)
        br = _clip01(self.bridging_count)
        l  = _clip01(self.linking_count)
        return _clip01(0.5*b + 0.3*br + 0.2*l)
    
    def _compute_costs(self, ctx: Dict[str, Any]) -> float:
        """
        Perceived cost of protective action (evac/shelter), normalized to [0,1].
        Includes monetary/time/disutility/health-related activity limits + household coordination.
        """
        evac_money = ctx["evac_money_norm"]      # 0..1 (scaled $)
        time_cost  = ctx["travel_time_norm"]     # 0..1 (scaled hours)
        disutil    = ctx["shelter_disutility"]   # 0..1 (comfort/crowding)
        travel_hr  = ctx["travel_health_risk"]   # 0..1 (exposure en route)
    
        base = evac_money + time_cost + disutil + travel_hr
    
        # Health limits increase effective cost of acting now:
        # activity_capacity ∈ [0,1]; lower capacity → higher cost increment.
        cap = self.activity_capacity()
        health_penalty = (1.0 - cap) * 0.3  # tunable weight (adds up to 0.3 max)
    
        # SES / education ease costs; vulnerability raises them
        wealth_benefit = 0.10 if self.wealth_class in ("Upper_Middle_Class", "Upper_Class") else 0.0
        edu_benefit    = 0.05 if float(self.education) >= 0.7 else 0.0
        vuln_penalty   = 0.10 * _clip01(self.vulnerability)
    
        # Household size increases perceived coordination/logistics cost
        hh_size = self._get_household_size()
        hh_cost = 0.05 * (hh_size - 1)  # 0 for singles; +0.05 per additional member
    
        return _clip01(base + health_penalty - wealth_benefit - edu_benefit + vuln_penalty + hh_cost)
    
    def _compute_coping(self, ctx: Dict[str, Any], p: DecisionParams) -> float:
        """
        Normalized Coping in [0,1] from efficacy beliefs & social support, net of costs.
        """
        se  = _clip01(self.self_efficacy)
        re  = _clip01(self.response_efficacy)
        soc = self._social_support()
        co  = self._compute_costs(ctx)

        targeted = float(self.model.targeted_protection_intensity)
        if targeted > 0.0 and (
            self.age < 5 or self.age >= 65 or
            self.wealth_class == "Lower_Class" or
            self.vulnerability >= 0.70
        ):
            soc = _clip01(soc + 0.20 * targeted)
            re = _clip01(re + 0.15 * targeted)
    
        raw = p.a_self*se + p.a_resp*re + p.a_soc*soc - p.a_cost*co
        return _clip01(raw)

    # -------------------- Phase Policies + Actions --------------------
    def _pre_flood_decision_and_action(
        self, T: float, C: float, ctx: Dict[str, Any], p: DecisionParams
    ) -> Dict[str, Any]:
        """
        PRE-FLOOD (official warning window):
        Decide whether to EVACUATE (leave area) vs PREPARE-TO-EVACUATE vs STAY.
        Notes:
          • Evacuation here is *leaving the area* (not contingent on shelter beds).
          • Prepare-To-Evacuate = concrete readiness to leave quickly (pack, fuel, coordinate).
          • We allow either a behavioral gate (T) or a simple physical trigger (depth).
        Inputs (ctx):
          route_exists, route_safe : bool — feasible & safe path out?
          home_depth_m             : float — water depth at home (m)
        Tunables (model):
          pre_evac_T_gate          : float — min Threat to consider evac
          evac_trigger_depth_m     : float — depth threshold that triggers evac consideration
        """
        route_ok  = bool(ctx["route_exists"] and ctx["route_safe"])
        threat_gate = float(self.model.pre_evac_T_gate)
        depth_trigger = float(self.model.evac_trigger_depth_m)
        evacuation_considered = (
            T >= threat_gate or
            float(ctx["home_depth_m"]) >= depth_trigger
        )
        p_evac = _clip01(_sigmoid(p.beta0 + p.betaT * T + p.betaC * C) * self._jit_decision)

        if evacuation_considered and route_ok and random.random() < p_evac:
            self._prepare_to_evacuate()
            self._evacuate(ctx);  act = "Evacuate"
        else:
            p_prep = _sigmoid(p.beta0_prep + p.betaT_prep * T + p.betaC_prep * C)
            p_prep = _clip01(p_prep * self._jit_decision)
            if random.random() < p_prep:
                # choose which preparation makes more sense under constraints
                self._prepare_home();         act = "PrepareHome"
            else:
                self._stay_and_monitor();     act = "Stay"
    
        return {"phase": "pre", "action": act, "T": T, "C": C, "route_ok": route_ok}
    
    
    def _during_flood_decision_and_action(
        self, T: float, C: float, ctx: Dict[str, Any], p: DecisionParams
    ) -> Dict[str, Any]:
        """
        DURING-FLOOD (hazard realized):
        Choose between EVACUATE (if possible & safe), SHELTER-IN-PLACE (if movement is unsafe),
        or COPING actions (sandbagging, neighbor aid, etc.).
        Rules of thumb:
          • If home is unsafe and routes are safe and coping is sufficient → evacuate.
          • If home is unsafe and routes are unsafe → shelter in place.
          • Otherwise, do coping actions (risk reduction without moving).
        """
        route_ok = bool(ctx["route_exists"] and ctx["route_safe"])
        home_unsafe = bool(
            ctx["home_unsafe_now"] or
            (ctx["home_depth_m"] >= float(self.model.home_unsafe_depth_m))
        )
        threat_gate = float(self.model.pre_evac_T_gate)
        evacuation_considered = home_unsafe or T >= threat_gate
    
        p_evac_during = _clip01(_sigmoid(p.beta0 + p.betaT * T + p.betaC * C) * self._jit_decision)

        if evacuation_considered and route_ok and random.random() < p_evac_during:
            self._evacuate(ctx);       act = "Evacuate"
        elif home_unsafe and not route_ok:
            self._shelter_in_place();  act = "ShelterInPlace"
        else:
            self._coping_action();     act = "CopingAction"
    
        return {
            "phase": "during",
            "action": act,
            "T": T,
            "C": C,
            "route_ok": route_ok,
            "home_unsafe": home_unsafe,
            "p_evac_during": p_evac_during,
        }
    
    def _post_flood_decision_and_action(
        self, T: float, C: float, ctx: Dict[str, Any], p: DecisionParams
    ) -> Dict[str, Any]:
        """
        POST-FLOOD (recovery):
        Decide whether to RETURN or DELAY RETURN.
        • Driven mainly by habitability and residual coping (resources/logistics).
        """
        habit = _clip01(ctx["home_habitability"])
        p_return = _clip01(_sigmoid(p.gamma0 + p.gammaH * habit + p.gammaC * C) * self._jit_decision)
    
        if random.random() < p_return:
            self._return_home();  act = "Return"
        else:
            self._delay_return(); act = "DelayReturn"
    
        return {"phase": "post", "action": act, "C": C, "habitability": habit}

    def _prepare_to_evacuate(self) -> None:
        """
        Concrete readiness to leave quickly while staying home for now:
          - Pack essentials & meds; secure documents/valuables upstairs.
          - Check fuel/vehicle or arrange a ride; pick a meetup point.
          - Exchange contact/alerts with neighbors; monitor updates.
        Side effects kept light (flags → support later analytics).
        """
        self.preflood_prepared = True
        # Optional: small boosts to effective coping or response efficacy
        self.response_efficacy = _clip01(self.response_efficacy + 0.02)

    # -------------------- Context Builder --------------------
    def _build_context(self) -> Dict[str, Any]:
        """
        Assemble decision inputs used by the kernel.
        Keep each input either physically meaningful (meters) or normalized [0,1].
        This stays intentionally small for paper clarity.
        """
        m = self.model
    
        # --- Flood depth at home (meters + normalized) --------------------
        def _depth_m_and_norm(pt_or_agent):
            """Return (meters, normalized 0..1 by a 2 m cap)."""
            if not hasattr(m, "space") or not hasattr(m.space, "get_flood_height_at_position"):
                return 0.0, 0.0
            pt = pt_or_agent.geometry if hasattr(pt_or_agent, "geometry") else pt_or_agent
            d_m = float(m.space.get_flood_height_at_position(pt))  # meters
            d_n = _clip01(d_m / 2.0)                               # normalize by 2 m
            return d_m, d_n
    
        home_depth_m = 0.0                  # meters (for thresholds/plots)
        depth_home_norm = 0.0               # 0..1 (for decisions)
        home_flooded = False
        home_habit = 0.8                    # 0..1 habitability proxy
    
        if self.household is not None:
            home_depth_m, depth_home_norm = _depth_m_and_norm(self.household)
            home_flooded = bool(getattr(self.household, "flooded", False))
            # If a damage module exists, prefer it; else a simple fallback.
            if hasattr(m, "damage") and hasattr(m.damage, "habitability"):
                try:
                    home_habit = _clip01(m.damage.habitability(self.household))
                except Exception:
                    home_habit = 0.3 if home_flooded else 0.8
            else:
                home_habit = 0.3 if home_flooded else 0.8
        else:
            home_depth_m, depth_home_norm = _depth_m_and_norm(self.geometry)
    
        # --- Imminence of event (0 baseline → 1 at end of warning window) ----
        flood_active = bool(getattr(m, "enable_flood", True))
        imminence = 0.0
        if flood_active and all(hasattr(m, k) for k in ("hours", "evacuation_time", "last_evacuation_time")):
            start_h = float(m.evacuation_time)          # start of pre_flood
            end_h   = float(m.last_evacuation_time)     # end of pre_flood
            now_h   = float(m.hours)
    
            if now_h < start_h:
                imminence = 0.0                         # baseline
            elif now_h <= end_h:
                window = max(1.0, end_h - start_h)
                remaining = max(0.0, end_h - now_h)
                imminence = _clip01(1.0 - remaining / window)   # ramps 0→1 across pre_flood
            elif m.disaster_period == "during_flood":
                imminence = 1.0
            else:
                imminence = 0.2                         # post_flood (low, nonzero)
        elif flood_active:
            imminence = 0.0 if m.disaster_period in ("baseline", "pre_flood") \
                        else 1.0 if m.disaster_period == "during_flood" else 0.2
    
        # --- Official warning strength (0..1), fallback tied to imminence ----
        warning_official = 0.0
        risk_comm = float(m.risk_communication_intensity)
        if flood_active and hasattr(m, "warnings") and hasattr(m.warnings, "at"):
            try:
                warning_official = _clip01(m.warnings.at(self))
            except Exception:
                warning_official = 0.0
        elif flood_active:
            if m.disaster_period in ("baseline", "pre_flood"):
                base_warn = float(m.warning_pre_flood_base)
                warning_official = _clip01(base_warn * (1.0 + 0.80 * risk_comm) * imminence)
            elif m.disaster_period == "during_flood":
                warning_official = _clip01(0.25 + 0.30 * risk_comm)
    
        # --- Social signal: neighbors evacuated fraction (0..1) --------------
        if hasattr(m, "social") and hasattr(m.social, "neighbor_frac_evacuated"):
            try:
                neighbors_evacuated_frac = _clip01(m.social.neighbor_frac_evacuated(self))
            except Exception:
                neighbors_evacuated_frac = 0.0
        else:
            P = m.people
            neighbors_evacuated_frac = _clip01(sum(1 for q in P if getattr(q, "evacuated", False)) / max(1, len(P)))
        neighbors_evacuated_frac = _clip01(
            neighbors_evacuated_frac * float(m.social_evac_signal_scale)
        )
    
        # --- Route feasibility proxies (replace with roads later) -------------
        radius = self._hourly_radius_m()        # >0 implies some mobility possible
        route_exists = True
        route_safe = bool(radius > 0.0)
        if getattr(m, "disaster_period", None) == "during_flood":
            route_safe = bool(route_safe and (home_depth_m <= float(getattr(m, "during_route_max_depth_m", 0.30))))
    
        # --- Cost terms (normalized 0..1) ------------------------------------
        # Monetary: simple ratio against income (replace with proper basket later)
        if self.income > 0:
            evac_money_norm = _clip01(300.0 / float(self.income))   # TODO: calibrate
        else:
            evac_money_norm = 0.5

        travel_time_norm = 0.7 * (1.0 - imminence) + 0.3 * imminence

        shelter_disutility = 0.2
        sh = getattr(m, "shelter", None)
        if sh is not None:
            cap = max(1, int(getattr(sh, "capacity_limit", 0) or 1))
            load = len(getattr(sh, "sheltered_agents", []) or [])
            util = min(1.0, max(0.0, load / cap))
            distancing = float(m.shelter_distancing_intensity)
            shelter_disutility = _clip01(0.15 + 0.40 * util * (1.0 - 0.60 * distancing))

        travel_health_risk = _clip01(0.50 * depth_home_norm + 0.20 * self.health_vulnerability)

        # Disease pressure contributes to perceived threat outside pure flood context.
        disease_pressure = 0.0
        if bool(getattr(m, "enable_infectious", False)):
            inf_coupling = _clip01(float(m.infectious_threat_coupling))
            if inf_coupling > 0.0:
                inf_signal = 1.0 if str(getattr(self, "inf_state", "S") or "S") == "I" else 0.0
                disease_pressure = max(disease_pressure, _clip01(inf_signal * inf_coupling))
        if bool(getattr(m, "enable_stagnant", False)):
            try:
                stagnant = float(getattr(m.space, "get_stagnant_hazard_at_position", lambda *_: 0.0)(self.geometry) or 0.0)
            except Exception:
                stagnant = 0.0
            disease_pressure = max(disease_pressure, _clip01(stagnant), 1.0 if bool(getattr(self, "symp_vector", False) or self.ill_vector) else 0.0)
        if bool(getattr(m, "enable_mold", False)):
            mold_signal = 1.0 if bool(getattr(self, "symp_mold", False) or self.ill_respiratory) else 0.0
            if self.household is not None:
                mold_signal = max(
                    mold_signal,
                    _clip01(self.household.mold_index),
                    _clip01(self.household.damp_level),
                )
            disease_pressure = max(disease_pressure, mold_signal)
    
        # --- Return compact context ------------------------------------------
        return {
            "depth_home": depth_home_norm,      # normalized 0..1 (decision input)
            "home_depth_m": home_depth_m,       # meters (for thresholds/plots)
            "imminence": imminence,             # 0..1 (position within warning window)
            "warning_official": warning_official,
            "neighbors_evacuated_frac": neighbors_evacuated_frac,
            "route_exists": route_exists,
            "route_safe": route_safe,
            "evac_money_norm": evac_money_norm,
            "travel_time_norm": travel_time_norm,
            "shelter_disutility": shelter_disutility,
            "travel_health_risk": travel_health_risk,
            "disease_pressure": _clip01(disease_pressure),
            "home_unsafe_now": home_flooded,    # boolean (structural flag)
            "home_habitability": home_habit,    # 0..1 (post-flood return driver)
        }
   
    # -------------------- Action Primitives --------------------
    def _enforce_location_state_invariants(self) -> None:
        """
        Ensure displacement states are mutually exclusive:
          - evacuated => not stranded, not in_shelter, off-map
          - in_shelter => not evacuated, not stranded
          - stranded => not evacuated, not in_shelter
        """
        if self.evacuated:
            self.in_shelter = False
            self.stranded = False
            self._remove_from_map()
            return

        if self.in_shelter:
            self.evacuated = False
            self.stranded = False
            return

        if self.stranded:
            self.evacuated = False
            self.in_shelter = False
            # Stranded is valid only while physically flood-blocked.
            if not self._is_flood_blocked(self.geometry):
                self.stranded = False

    def _evacuate(self, ctx: Dict[str, Any]):
        """
        Leave the flood area. This *does not* require shelter admission.
        Effects:
          • State flips: evacuated=True; removed from map
          • Optional: one-off evac cost (packing, fuel, lodging)
          • Optional: route some spend to an open business (econ side-effect)
          • Timestamp t_departed for analytics
        """
        # (Optional) simple evacuation cost; allow debt if income is low
        evac_scale = max(0.0, float(self.model.evacuation_cost_scale))
        factor = max(0.4, self.expense_variability_factor)
        evac_cost = random.uniform(50, 500) * evac_scale * factor
        self.income = (self.income or 0.0) - evac_cost
        self.evacuation_expense_accum += float(evac_cost)
    
        # Spend with a non-flooded business; gov collects tax via model.business_revenue
        businesses = getattr(self.model.space, "businesses", [])
        open_biz = [b for b in businesses if not getattr(b, "flooded", False)]
        if open_biz:
            biz = random.choice(open_biz)
            self.model.business_revenue(biz, evac_cost)
    
        # State transitions
        self.evacuated = True
        self.in_shelter = False
        self.stranded = False
        self.t_departed = self.current_hour

        # Defensive cleanup if this person was still tracked in shelter list.
        shelter = self.model.shelter
        if shelter is not None and self in shelter.sheltered_agents:
            shelter.sheltered_agents.remove(self)
    
        # Remove agent from map so they don’t interact with hazard
        self._remove_from_map()
    
        # Optional event hook
        self._emit("evacuate", T=self.last_threat, C=self.last_coping, route_ok=ctx["route_safe"])
    
    
    def _prepare_to_evacuate(self) -> None:
        """
        Evacuation preparation that happens as part of the evacuation decision.
        This covers packing, fueling, booking, and other leave-readiness steps.
        """
        self.preflood_prepared = True
        prep_scale = max(0.0, float(self.model.preparation_cost_scale))
        self.income = (self.income or 0.0) - (random.uniform(10, 80) * prep_scale)
        self.response_efficacy = _clip01(self.response_efficacy + 0.06)
        self.self_efficacy = _clip01(self.self_efficacy + 0.04)
        self._emit("prepare_evacuation")


    def _prepare_home(self):
        """
        Pre-flood preparation to shelter safely (sandbags, moving items up, water/food).
        """
        self.preflood_prepared = True
        prep_scale = max(0.0, float(self.model.preparation_cost_scale))
        self.income = (self.income or 0.0) - (random.uniform(20, 120) * prep_scale)
        self.response_efficacy = _clip01(self.response_efficacy + 0.04)
        self.self_efficacy = _clip01(self.self_efficacy + 0.06)
        self._emit("prepare_home")
    
    
    def _stay_and_monitor(self):
        """
        Do nothing but remain attentive to warnings (baseline control action).
        Useful for action-share analytics without side-effects.
        """
        self._emit("stay")
    
    def _shelter_in_place(self):
        """
        Stay put because movement is unsafe (route unsafe or home already compromised).
        Effects:
          • Marks the person as stranded (enables rescue logic/timers)
          • Requests rescue from Shelter (if available)
        """
        self._emit("shelter_in_place")
        # Only classify as stranded if current position is actually flood-blocked.
        self._stranded_behavior()
    
    def _coping_action(self):
        """
        During-flood minor mitigation/action:
          • Move valuables to higher floor, check on neighbor, small within-cell relocation, etc.
          • Recorded only as a flag for analytics; avoid complex side-effects here.
        """
        self.duringflood_coped = True
        self._emit("coping_action")
    
    def _return_home(self):
        """
        Return is allowed only in post-flood phase.
        Effects:
          • Clears evacuated/shelter state
          • Removes from shelter registry defensively
          • Re-adds to map; tries to place at home if depth below tolerance
        """
        if self.model.disaster_period != "post_flood":
            return
    
        self.evacuated = False
        self.in_shelter = False
        self.stranded = False
    
        shelter = self.model.shelter
        if shelter is not None and self in shelter.sheltered_agents:
            shelter.sheltered_agents.remove(self)
    
        self._add_back_to_map()
    
        # Place at home only if safe; otherwise a safe nearby position
        if self.household is not None and hasattr(self.household, "geometry"):
            self._place_in_entity_if_safe(
                self.household,
                float(self.model.home_depth_tol_m)
            )
    
        self._emit("return_home")
    
    def _delay_return(self):
        """
        Post-flood: intentionally remain away (e.g., repairs pending, utilities down).
        No side-effects here; costs/disutility can be added in an economics module.
        """
        self._emit("delay_return")  

    # -------------------- Routine & Movement --------------------
    def _daily_routine(self, capacity: float = 1.0):
        """
        Simulate one day's routine, adjusted for flood conditions.
    
        Logic:
                    - If stranded → continue the normal random movement attempt.
          - Very low activity capacity → remain home if possible.
          - Otherwise follow a coarse schedule based on time_of_day.
        """
        if self.stranded:
            self._random_movement()
            return

        if float(capacity) <= 0.35:
            self._rest_at_home()
            return
    
        tod = self.time_of_day
        if 0 <= tod < 8:
            self._rest_at_home()
        elif 8 <= tod < 11:
            if self.employed:
                self._work_at_business()
            elif self.student:
                self._go_to_school()
            else:
                self._random_movement()
        elif 11 <= tod < 12:
            if self.employed:
                self._work_at_business()
            else:
                self._random_movement()
        elif 12 <= tod < 14:
            self._random_movement()
        elif 14 <= tod < 18:
            if self.employed:
                self._work_at_business()
            elif self.student and tod < 17:
                self._go_to_school()
            else:
                self._random_movement()
        else:
            self._random_movement()
     
    def _rest_at_home(self):
        """
        Stay at home if possible.
        - If already inside home and water is safe → remain there.
        - At midnight (hour 0), re-randomize position inside polygon.
        - If away or house unsafe → try to return home safely, else move randomly.
        """
        tol = float(self.model.home_depth_tol_m)
        if self.household is None:
            self._random_movement()
            return

        if hasattr(self.household, "is_habitable_now") and not self.household.is_habitable_now():
            self._random_movement()
            return
    
        if self.household.geometry.contains(self.geometry):
            if self._entity_depth(self.household) <= tol:
                if self.time_of_day == 0:  # midnight reposition
                    pos = self._random_point_in_polygon(self.household.geometry)
                    self.model.space.move_agent(self, pos)
                return
    
        # Otherwise, attempt safe return to home
        self._place_in_entity_if_safe(self.household, tol)
    
    def _work_at_business(self):
        """
        Try to attend workplace and earn wages.
        - Must arrive safely at business location.
        - Earn wage, reduce business wealth, transfer tax to government.
        """
        if self.workplace is None:
            self._random_movement()
            return
    
        arrived = self._place_in_entity_if_safe(self.workplace, float(self.model.work_depth_tol_m))
        if not arrived:
            return
    
        # Wage accrual
        hourly_wage = self._hourly_wage()
        self.income = (self.income or 0.0) + hourly_wage
    
        # Employer pays wages
        wage_cost_share = max(0.0, min(1.0, float(self.model.business_wage_cost_share)))
        self.workplace.pay_wage(hourly_wage * wage_cost_share)
    
        # Income tax withheld → government
        income_tax_rate = self.model.income_tax_rate
        withheld = hourly_wage * income_tax_rate
        self.income -= withheld
        self.model.government.wealth += withheld
        self.model.government.total_income_withholding += withheld
    
        self._emit(
            "wage_paid",
            business_id=self.workplace.name,
            wage=hourly_wage,
            income_tax_withheld=withheld,
        )
    
    def _go_to_school(self):
        """
        Try to attend school if assigned.
        - If no schoolplace, fallback to random movement.
        """
        if self.schoolplace is None:
            self._random_movement()
            return
        self._place_in_entity_if_safe(self.schoolplace, float(self.model.school_depth_tol_m))
    
    def _random_movement(self):
        """
        Move randomly around an anchor point.
        - Radius is based on mobility speed (walking/driving) with flood penalty.
        - One random destination is attempted per movement step.
        - The destination's flood conditions determine whether the agent is stranded.
        """
        base_r = self._hourly_radius_m()
        cap = float(self.model.random_move_radius_m)
        r = min(base_r, max(0.0, cap))
        if r <= 0:
            self._stranded_behavior()
            return
    
        anchor = self._anchor_point_for_random_move()
        cx, cy = anchor.x, anchor.y
    
        angle = random.uniform(0, 2 * np.pi)
        rho = r * math.sqrt(random.random())
        dx, dy = rho * math.cos(angle), rho * math.sin(angle)
        candidate = Point(cx + dx, cy + dy)
        destination_blocked = self._is_flood_blocked(candidate)

        self.model.space.move_agent(self, candidate)
        if destination_blocked:
            self._stranded_behavior()
        else:
            self._maybe_shop_if_in_business(candidate)
            self.stranded = False
    
    def _anchor_point_for_random_move(self):
        """
        Anchor movement around:
          - Home (if mode == 'home').
          - Work/school during day, else home (if mode == 'context').
          - Current position (fallback).
        """
        tod = self.time_of_day
        if 8 <= tod < 18:
            if self.employed and self.workplace:
                return self.workplace.geometry.representative_point()
            if self.student and self.schoolplace:
                return self.schoolplace.geometry.representative_point()
        if self.household:
            return self.household.geometry.representative_point()
        return self.geometry
    
    def _stranded_behavior(self):
        """
        Mark agent as stranded and request rescue.
        - Rescue must be handled by the Shelter system.
        """
        # Do not classify as stranded outside flood-blocked conditions.
        if not self._is_flood_blocked(self.geometry):
            self.stranded = False
            self._emit("movement_blocked_nonflood")
            return

        self.evacuated = False
        self.in_shelter = False
        self.stranded = True
        self.model.notify_shelter(self)
        self._emit("movement_stranded")
        self._emit("shelter_rescue_requested")

    # -------------------- Money & Bookkeeping --------------------
    def _hourly_wage(self) -> float:
        # If the model defines effective_wage, let it apply productivity, etc.
        base = psn_agnt.hourly_wage_for(self)
        if hasattr(self.model, "effective_wage"):
            return self.model.effective_wage(self, base)
        return base

    # -------------------- Movement Helpers --------------------
    def _has_vehicle(self) -> bool:
        return psn_agnt.assign_vehicle(self.model, self)

    def _flood_resilience_threshold_m(self) -> float:
        """Movement threshold in meters derived from legacy resilience scale."""
        base = max(0.0, self.flood_resilience / 10.0)
        mult = max(0.01, float(self.model.stranded_depth_tolerance_mult))
        return base * mult

    def _intersects_active_flood(self, pt: Optional[Point] = None) -> bool:
        """True when the point intersects any currently active flood polygon."""
        if not self.model.enable_flood:
            return False
        point = pt or self.geometry
        if point is None:
            return False
        prepared = getattr(self.model.space, "_active_flood_prepared", None)
        if prepared is None:
            return False
        try:
            return bool(prepared.intersects(point))
        except Exception:
            return False

    def _is_flood_blocked(self, pt: Optional[Point] = None) -> bool:
        """
        Canonical stranded gate:
        blocked iff (intersects flood map) and (local depth exceeds person resilience).
        """
        point = pt or self.geometry
        if point is None:
            return False
        if not self._intersects_active_flood(point):
            return False
        depth_here = float(self.model.space.get_flood_height_at_position(point))
        return depth_here > self._flood_resilience_threshold_m()

    # -------------------- Mobility --------------------
    def _get_household_size(self) -> int:
        """
        Return the number of residents in this person's household.
        Defaults to 1 if no household is assigned.
        """
        if self.household is not None and hasattr(self.household, "residents"):
            return max(1, len(self.household.residents))
        return 1

    def _hourly_radius_m(self) -> float:
        """
        Maximum distance this agent can travel in one hour,
        considering:
          - Walking vs driving speeds
          - Age penalty for older pedestrians
          - Household size penalty (group coordination overhead)
          - Flood depth penalty (slows walking or vehicles)
          - Global penalty during flood
        Returns distance in meters.
        """
        speed = self.drive_speed_mps if self._has_vehicle() else self.walk_speed_mps
    
        # Age penalty for pedestrians
        if not self._has_vehicle():
            if self.age >= 70:
                speed *= 0.8
            elif self.age >= 55:
                speed *= 0.9
    
        # Household size penalty: each additional member adds ~5% coordination overhead
        hh_size = self._get_household_size()
        if hh_size > 1:
            speed *= 1.0 / (1.0 + 0.05 * (hh_size - 1))
    
        # Flood penalty at current location
        depth_here = float(self.model.space.get_flood_height_at_position(self.geometry))
        if depth_here >= 0.2 and not self._has_vehicle():
            speed *= 0.5
        if depth_here >= 0.4 and self._has_vehicle():
            speed *= 0.5
    
        # Global flood-period penalty
        flood_penalty = 0.8 if (self.model.enable_flood and self.model.disaster_period == "during_flood") else 1.0
    
        return 3600.0 * speed * flood_penalty  # meters per hour
    
    @staticmethod
    def _random_point_in_polygon(poly):
        """Sample a random point inside a polygon (fallback = centroid)."""
        minx, miny, maxx, maxy = poly.bounds
        for _ in range(200):
            p = Point(random.uniform(minx, maxx), random.uniform(miny, maxy))
            if poly.contains(p):
                return p
        return poly.representative_point()
    
    # -------------------- Experience Updates --------------------
    def _update_flood_memory(self):
        """
        Update flood memory based on current depth.
        Memory ∈ [0,1], slowly shifts toward recent depth experience.
        """
        d_raw = float(self.model.space.get_flood_height_at_position(self.geometry))
        alpha = 0.2
        self.flood_memory = _clip01((1 - alpha) * self.flood_memory + alpha * _clip01(d_raw / 2.0))
    
    def _update_social_capital_bounded(self):
        """
        (Optional) Simulate small bounded changes in social capital.
        Only needed if modeling social dynamics beyond static values.
        """
        jitter = 0.01
        self.bonding_count  = _clip01(self.bonding_count  + random.uniform(-jitter, jitter))
        self.bridging_count = _clip01(self.bridging_count + random.uniform(-jitter, jitter))
        self.linking_count  = _clip01(self.linking_count  + random.uniform(-jitter, jitter))

    def _hazard_pressure(self, ctx: Dict[str, Any]) -> float:
        """
        Aggregate current multi-hazard pressure in [0,1].
        Flood and disease pressures combine so concurrent hazards produce higher signal.
        """
        phase = str(self.model.disaster_period)

        flood_signal = 0.0
        if self.model.enable_flood:
            flood_signal = max(
                float(ctx["depth_home"]),
                float(ctx["imminence"]),
                float(ctx["warning_official"]),
                float(ctx["neighbors_evacuated_frac"]),
            )
            if phase == "pre_flood":
                flood_signal = max(flood_signal, 0.20)
            elif phase == "during_flood":
                flood_signal = max(flood_signal, 0.55)

        disease_signal = 0.0
        disease_enabled = any([
            self.model.enable_infectious,
            self.model.enable_stagnant,
            self.model.enable_mold,
        ])
        if disease_enabled:
            symptomatic = bool(
                self.injured or self.ill_respiratory or self.ill_vector
                or getattr(self, "inf_state", "S") == "I"
            )
            symptom_pressure = _clip01(float(self.model.psych_symptom_pressure))
            if symptomatic:
                disease_signal = max(disease_signal, symptom_pressure)

            if self.model.enable_stagnant:
                stagnant = 0.0
                try:
                    stagnant = float(
                        getattr(self.model.space, "get_stagnant_hazard_at_position", lambda *_: 0.0)(self.geometry)
                    )
                except Exception:
                    stagnant = 0.0
                disease_signal = max(disease_signal, _clip01(stagnant))

            if self.model.enable_mold and self.household is not None:
                mold_idx = _clip01(float(getattr(self.household, "mold_index", 0.0) or 0.0))
                damp_lvl = _clip01(float(getattr(self.household, "damp_level", 0.0) or 0.0))
                disease_signal = max(disease_signal, max(mold_idx, damp_lvl))

        # Probabilistic OR keeps pressure bounded but rewards concurrent hazards.
        combined = 1.0 - ((1.0 - _clip01(flood_signal)) * (1.0 - _clip01(disease_signal)))
        return _clip01(combined)

    def _update_psychology_signals(self, ctx: Dict[str, Any]) -> None:
        """
        Efficacy signals adapt to current hazard pressure and gradually relax to personal baseline.
        """
        pressure = self._hazard_pressure(ctx)

        self_gain = max(0.0, float(self.model.psych_efficacy_hazard_gain_self))
        resp_gain = max(0.0, float(self.model.psych_efficacy_hazard_gain_response))
        adapt_rate = max(0.0, min(1.0, float(self.model.psych_efficacy_adapt_rate)))
        decay_rate = max(0.0, min(1.0, float(self.model.psych_efficacy_decay_rate)))

        target_self = _clip01(float(self.self_efficacy_baseline) + self_gain * pressure)
        target_resp = _clip01(float(self.response_efficacy_baseline) + resp_gain * pressure)

        cur_self = _clip01(float(self.self_efficacy))
        cur_resp = _clip01(float(self.response_efficacy))

        rate_self = adapt_rate if target_self > cur_self else decay_rate
        rate_resp = adapt_rate if target_resp > cur_resp else decay_rate

        self.self_efficacy = _clip01(cur_self + rate_self * (target_self - cur_self))
        self.response_efficacy = _clip01(cur_resp + rate_resp * (target_resp - cur_resp))
    
    # -------------------- Map Membership --------------------
    def _remove_from_map(self):
        """Remove agent from spatial index (used when evacuated)."""
        if self._in_map:
            self.model.space.remove_agent(self)
            self._in_map = False
    
    
    def _add_back_to_map(self):
        """Re-add agent to spatial index (used when returning)."""
        if not self._in_map:
            self.model.space.add_agents([self])
            self._in_map = True
            
    # -------------------- Economic Side Effects --------------------
    def _maybe_shop_if_in_business(self, point: Point):
        """
        If agent is inside a business polygon:
          - If business is open → transact (spend).
          - If business is closed/flooded → count as lost sale (missed revenue).
        """
        for biz in self.model.space.businesses:
            if biz.geometry.contains(point):
                if not biz.is_open() or biz.flooded:
                    # Closed → lost sale opportunity
                    self._lost_sale(biz)
                    return
                else:
                    # Open → make a purchase
                    self._transact_with_business(biz)
                    return
    
    def _transact_with_business(self, business):
        """
        Make a purchase:
          - Household income decreases
          - Business revenue increases (after sales tax)
          - Government collects sales tax
        """
        base_spend = random.uniform(0.5, 1.5) * self._hourly_wage()
        spend = min(base_spend, max(0.0, (self.income or 0.0)))
        if spend <= 0:
            return
    
        sales_tax_rate = self.model.sales_tax_rate
        tax = spend * sales_tax_rate
    
        # Household income reduced
        self.income -= spend
    
        # Government collects tax
        self.model.government.wealth += tax
        self.model.government.total_sales_tax += tax
    
        # Business revenue (net of tax)
        self.model.business_revenue(business, spend - tax)
    
        self._emit("business_purchase",
                   business=business.name,
                   spend=spend, tax=tax, type="retail")
        self._emit("tax_withheld", kind="sales", amount=tax)
    
    
    def _lost_sale(self, business):
        """
        Record a lost sale:
          - Business loses potential revenue (proxy for economic loss).
          - No tax collected (government misses revenue too).
        """
        lost_amount = random.uniform(0.5, 1.5) * self._hourly_wage()
    
        # Treat as opportunity cost (wealth down even without cash inflow)
        business.wealth -= lost_amount
    
        self._emit("lost_sale",
                   business=business.name,
                   amount=lost_amount,
                   reason="closed_or_flooded")

     # -------------------- Theory metrics (for analysis only) --------------------
    def _theory_metrics(self, ctx, params):
        """
        Collect the psychological theory components (for analysis/logging).
        These don’t affect actions directly — just allow us to analyze why agents acted.
        """

        # Protection Motivation Theory (PMT) threat components
        threat_inputs = {
            "depth_home": ctx["depth_home"],   # water depth at home (normalized)
            "imminence": ctx["imminence"],     # how close the flood is in time
            "official_x_trust": ctx["warning_official"] * self.trust_in_authorities,
            "social_signal": ctx["neighbors_evacuated_frac"] * self.social_trust,
            "memory": self.flood_memory,       # past flood experience
            "worldview_gain": _worldview_gain(self.worldview)  # worldview scaling
        }

        # PMT coping components
        coping_inputs = {
            "self_efficacy": _clip01(self.self_efficacy),
            "response_efficacy": _clip01(self.response_efficacy),
            "social_support": self._social_support(),  # bonding, bridging, linking
            "costs": self._compute_costs(ctx),         # time/money/discomfort
        }

        # Social Capital Theory (SCT) snapshot
        sct = {
            "bonding": _clip01(self.bonding_count),
            "bridging": _clip01(self.bridging_count),
            "linking": _clip01(self.linking_count),
            "support": coping_inputs["social_support"],
        }

        # Cultural Theory of Risk (CRT)
        crt = {"worldview": self.worldview, "gain": threat_inputs["worldview_gain"]}

        # Theory of Planned Behavior (TPB)
        return {"threat": threat_inputs, "coping": coping_inputs, "social": sct, "cultural": crt}

    def _update_health_progression(self):
        """
        Tracks injury, recovery, and mortality risk as the flood unfolds.
        - If stranded in hazard → risk of injury and eventual death.
        - If safe and injured → chance to recover.
        - Keeps timers for stranded, injured, and shelter time.
        """
        depth_here = float(self.model.space.get_flood_height_at_position(self.geometry))

        # Case: stranded in hazard
        if self.stranded:
            self.time_stranded += 1
            self.model.notify_shelter(self)

            # Some stranded agents can self-release once local water falls or after waiting.
            if depth_here < (0.12 * self._jit_threshold) and random.random() < _clip01(0.30 * self._jit_decision):
                self.stranded = False
                self._emit("self_unstranded", reason="depth_receded")
            elif self.time_stranded >= int(max(1, round(6 * self._jit_threshold))) and random.random() < _clip01(0.05 * self._jit_decision):
                self.stranded = False
                self._emit("self_unstranded", reason="self_escape")

            # Injury risk grows with water depth and vulnerability
            hazard = _clip01(depth_here / 1.0)  # normalize to 1 at 1m
            p_injury = (0.02 + 0.20 * hazard * _clip01(self.vulnerability)) * self._jit_health
            p_injury *= max(0.0, float(self.model.injury_risk_scale))
            p_injury = _clip01(p_injury)
            if not self.injured and random.random() < p_injury:
                self.injured = True
                self._emit("health_injury_onset")

            # Mortality if stranded too long under hazard (probabilistic, not an abrupt cliff).
            hazard_gate = float(self.model.stranded_mortality_hazard_threshold) * self._jit_threshold
            if self.stranded and self.time_stranded > self.survivability_duration and hazard > hazard_gate:
                overtime_h = max(0, int(self.time_stranded - self.survivability_duration))
                p_death = 0.01 + 0.06 * hazard + 0.04 * min(1.0, overtime_h / 24.0)
                p_death *= float(self.model.stranded_mortality_rate_scale)
                p_cap = _clip01(float(self.model.stranded_mortality_prob_cap))
                p_death = _clip01(min(p_cap, p_death * self._jit_health))
                if random.random() < p_death:
                    self.alive = False
                    self.death_cause = "stranded_flood"
                    self.injured = False
                    self.stranded = False
                    self._remove_from_map()
                    self._emit("death")
                    return

        else:
            # Recovery chance if safe and injured
            if self.injured and depth_here < (0.05 * self._jit_threshold):
                if random.random() < self.recovery_rate:
                    self.injured = False
                    self.time_injured = 0
                    self._emit("health_recovery")

        # If sheltered → track time in shelter
        if self.in_shelter:
            self.time_in_shelter += 1

        # Injured and flood-blocked should be treated as stranded and rescued.
        if self.injured and (not self.in_shelter) and self.alive and self._is_flood_blocked(self.geometry):
            self._stranded_behavior()

        # Injured and not sheltered/hospitalized → self-present to healthcare.
        if self.injured and (not self.in_shelter) and self.alive and (not self._is_flood_blocked(self.geometry)):
            hc = self.model.healthcare
            already_in = self in hc.hospitalized_agents
            already_pending = self in hc._pending_admissions
            if not already_in and not already_pending:
                hc.request_admission_self(self)
                self._emit("healthcare_self_request")

    def _self_checkin_healthcare(self):
        """
        Explicit self-checkin to healthcare (if capacity exists).
        Deducts ride cost, routes through a business, then admits to hospital.
        """
        hc = self.model.healthcare
        if len(hc.hospitalized_agents) >= hc.capacity_limit:
            return  # no capacity

        # Ride/service cost → economic effect
        ride_cost = random.uniform(20, 120)
        self.income -= ride_cost

        open_biz = [b for b in self.model.space.businesses if not b.flooded]
        if open_biz:
            self.model.business_revenue(random.choice(open_biz), ride_cost)

        self.model.receive_healthcare(self)
        self._emit("healthcare_admitted")

    # -------------------- Entity safety helpers --------------------
    def _entity_safe_depth_tol(self, entity, fallback: float) -> float:
        """
        Return safe water depth for being inside an entity.
        Uses entity.resilience if defined, else fallback tolerance.
        """
        share = float(self.model.entity_inside_depth_share)  # 1.00 = same threshold as structure flooding
        if hasattr(entity, "resilience"):
            return max(0.0, share * (float(entity.resilience) / 10.0))
        return float(fallback)

    def _entity_depth(self, entity) -> float:
        """
        Get water depth at an entity.
        Prefer entity.last_depth if stored, else query model.space.
        """
        if entity is None:
            return 0.0
        if hasattr(entity, "last_depth"):
            return float(entity.last_depth)
        pt = getattr(entity, "_rp", None) or entity.geometry.representative_point()
        return float(self.model.space.get_flood_height_at_position(pt))

    def _place_in_entity_if_safe(self, entity, fallback_tol_m: float) -> bool:
        """
        Move agent into entity only if entity is open/habitable and depth is safe.
        Otherwise fall back to random movement.
        """
        if entity is None:
            self._random_movement()
            return False

        # Entity-specific safety checks
        if hasattr(entity, "is_open") and not entity.is_open():         # business
            self._random_movement(); return False
        if hasattr(entity, "is_open_now") and not entity.is_open_now(): # school
            self._random_movement(); return False
        if hasattr(entity, "is_habitable_now"):                         # house
            if not entity.is_habitable_now(self.model.home_habit_thresh):
                self._random_movement(); return False

        tol = self._entity_safe_depth_tol(entity, fallback_tol_m)
        if self._entity_depth(entity) <= tol:
            pos = self._random_point_in_polygon(entity.geometry)
            self.model.space.move_agent(self, pos)
            return True

        self._random_movement()
        return False

    def _evict_if_place_now_unsafe(self):
        """
        If currently inside an entity, but water exceeds its safe tolerance → leave.
        """
        if self._is_flood_blocked(self.geometry):
            self._random_movement()
            return

        depth_here = float(self.model.space.get_flood_height_at_position(self.geometry))
        tol = float(self.model.public_space_depth_tol_m)  # default tolerance

        if self.household and self.household.geometry.contains(self.geometry):
            tol = self._entity_safe_depth_tol(self.household, float(self.model.home_depth_tol_m))
        elif self.workplace and self.workplace.geometry.contains(self.geometry):
            tol = self._entity_safe_depth_tol(self.workplace, float(self.model.work_depth_tol_m))
        elif self.schoolplace and self.schoolplace.geometry.contains(self.geometry):
            tol = self._entity_safe_depth_tol(self.schoolplace, float(self.model.school_depth_tol_m))

        if depth_here > tol:
            self._random_movement()  # may strand if no safe spot

    # -------------------- Event emitter --------------------
    def _emit(self, name: str, **payload):
        """Send structured event to collector/logging system when available."""
        coll = getattr(self.model, "collect", None)
        if coll and hasattr(coll, "emit_event"):
            coll.emit_event(name, {"agent": self.name, **payload})