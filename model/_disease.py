
from __future__ import annotations
import logging
import math, random

logger = logging.getLogger(__name__)


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))

class DiseaseModuleBase:
    name = "base"
    def step(self, model): pass
    def apply_to_person(self, model, p): pass
    def metrics(self, model): return {}

class DiseaseManager:
    """Container for disease modules with shared step and person-application hooks."""
    def __init__(self, modules):
        self.modules = modules or []

    def step(self, model):
        for m in self.modules:
            try:
                m.step(model)
            except Exception:
                logger.exception("Disease module %s failed at hour %s", getattr(m, "name", type(m).__name__), getattr(model, "hours", None))
                if bool(getattr(model, "strict_module_errors", False)):
                    raise

    def apply_to_person(self, model, p):
        for m in self.modules:
            try:
                m.apply_to_person(model, p)
            except Exception:
                logger.exception("Disease module %s failed for person %s at hour %s", getattr(m, "name", type(m).__name__), getattr(p, "unique_id", None), getattr(model, "hours", None))
                if bool(getattr(model, "strict_module_errors", False)):
                    raise

    def metrics(self, model):
        out = {}
        for m in self.modules:
            try:
                out.update(m.metrics(model))
            except Exception:
                logger.exception("Disease metrics for module %s failed at hour %s", getattr(m, "name", type(m).__name__), getattr(model, "hours", None))
                if bool(getattr(model, "strict_module_errors", False)):
                    raise
        return out

# Infectious disease (crowding/contact-driven SIR-like process)
def _priority_reduction(model, p) -> float:
    """Return a smaller exposure multiplier for higher-need groups when targeting is enabled."""
    intensity = max(0.0, min(1.0, float(model.targeted_protection_intensity)))
    if intensity <= 0.0:
        return 1.0

    high_need = (
        p.age < 5 or
        p.age >= 65 or
        p.wealth_class == "Lower_Class" or
        float(p.vulnerability) >= 0.70
    )
    if high_need:
        return max(0.35, 1.0 - 0.55 * intensity)
    return max(0.60, 1.0 - 0.20 * intensity)


class InfectiousModule(DiseaseModuleBase):
    """
    Contact-driven pathogen with household, workplace, school, and shelter mixing.
    States S, I, R are stored on p.inf_state.
    """
    name = "infectious"

    def __init__(self,
                 beta_base=0.008,
                 contact_intensity=1.0,
                 gamma=1/60,
                 waning=0.0,
                 seed_share=0.01):
        self.beta_base = beta_base
        self.contact_intensity = contact_intensity
        self.gamma = gamma
        self.waning = waning
        self.seed_share = seed_share
        self.max_inf_hours = 24 * 14
        self.course_hours = 24 * 7
        self.peak_hours = 24 * 3
        self.incidence = 0
        self._seeded = False

    def _initialize_case(self, model, p):
        age = int(p.age)
        age_burden = 0.16 if age >= 65 else (0.06 if age < 10 else 0.0)
        wealth_burden = 0.08 if p.wealth_class == "Lower_Class" else 0.0
        health_vulnerability = float(p.health_vulnerability)
        vulnerability = float(p.vulnerability)
        peak = 0.22 + 0.34 * health_vulnerability + 0.20 * vulnerability + age_burden + wealth_burden
        peak *= float(model.infectious_severity_scale)
        peak *= random.uniform(0.85, 1.15)
        p.inf_peak_severity = _clip01(peak)
        p.inf_severity = max(float(p.inf_severity or 0.0), min(0.20, p.inf_peak_severity * 0.30))
        p.inf_critical_hours = 0
        p.inf_rest_hours = 0
        p.inf_hospital_hours = 0
        p.inf_resting = False
        p.medical_needs_hospitalization = False

    def _severity_for_hour(self, model, p) -> float:
        course_hours = max(48, int(model.infectious_course_hours))
        peak_hours = max(12, min(course_hours - 1, int(model.infectious_peak_hours)))
        inf_hours = max(0, int(p.inf_hours or 0))
        if inf_hours <= peak_hours:
            course_factor = inf_hours / max(1, peak_hours)
        else:
            course_factor = max(0.0, 1.0 - ((inf_hours - peak_hours) / max(1, course_hours - peak_hours)))
        return _clip01(float(p.inf_peak_severity or 0.0) * course_factor)

    @staticmethod
    def _in_hospital(model, p) -> bool:
        hc = model.healthcare
        return bool(hc and p in (getattr(hc, "hospitalized_agents", []) or []))

    def step(self, model):
        self.incidence = 0
        if self._seeded:
            return

        # Seed timing is model-configurable.
        seed_start_hour = int(model.infectious_seed_start_hour)
        current_hour = int(model.hours)
        if current_hour < seed_start_hour:
            return

        people = [p for p in model.people if p.alive]
        if not people:
            return

        n_seed = min(len(people), max(1, int(round(len(people) * self.seed_share))))
        for p in random.sample(people, n_seed):
            if not hasattr(p, "inf_state") or getattr(p, "inf_state", "S") == "S":
                p.inf_state, p.inf_hours = "I", 0
                self._initialize_case(model, p)
        self._seeded = True

    def _shelter_util(self, model) -> float:
        sh = model.shelter
        if not sh:
            return 0.0
        cap = max(1, int(getattr(sh, "capacity_limit", 0) or 1))
        load = len(getattr(sh, "sheltered_agents", []) or [])
        return min(1.0, max(0.0, load / cap))

    @staticmethod
    def _share_infected(members) -> float:
        members = list(members or [])
        if not members:
            return 0.0
        infected = sum(1 for q in members if getattr(q, "inf_state", "S") == "I" and getattr(q, "alive", True))
        return min(1.0, max(0.0, infected / max(1, len(members))))

    def apply_to_person(self, model, p):
        if not p.alive:
            return

        if not hasattr(p, "inf_state"):
            p.inf_state, p.inf_hours = "S", 0
        if not hasattr(p, "inf_severity"):
            p.inf_severity = 0.0
        if not hasattr(p, "inf_peak_severity"):
            p.inf_peak_severity = 0.0
        if not hasattr(p, "inf_critical_hours"):
            p.inf_critical_hours = 0
        if not hasattr(p, "inf_rest_hours"):
            p.inf_rest_hours = 0
        if not hasattr(p, "inf_hospital_hours"):
            p.inf_hospital_hours = 0
        if not hasattr(p, "inf_resting"):
            p.inf_resting = False
        if not hasattr(p, "medical_needs_hospitalization"):
            p.medical_needs_hospitalization = False

        if p.inf_state == "I":
            p.inf_hours = int(p.inf_hours or 0) + 1
            p.inf_severity = self._severity_for_hour(model, p)

            p.inf_resting = p.inf_severity > 0.20
            p.inf_rest_hours = int(p.inf_rest_hours or 0) + int(p.inf_resting)

            if not self._in_hospital(model, p):
                vulnerability = 1.0 + float(p.health_vulnerability)
                vulnerability += 0.5 * float(p.vulnerability)
                care_probability = _clip01((p.inf_severity ** 2) * vulnerability)
                p.medical_needs_hospitalization = random.random() < care_probability
            else:
                p.medical_needs_hospitalization = False

            if p.medical_needs_hospitalization:
                model.receive_healthcare(p)

            mortality_hazard = max(
                0.0,
                float(model.infectious_mortality_hazard),
            )
            vulnerability = 1.0 + 0.75 * float(p.health_vulnerability)
            vulnerability += 0.35 * float(p.vulnerability)
            care_effect = 0.25 if self._in_hospital(model, p) else 1.0
            death_prob = mortality_hazard * (p.inf_severity ** 2) * vulnerability * care_effect
            if random.random() < _clip01(death_prob):
                p.alive = False
                p.death_cause = "infectious"
                p.inf_state = "D"
                p.inf_hours = 0
                p.inf_severity = 0.0
                p.inf_peak_severity = 0.0
                if hasattr(p, "_remove_from_map"):
                    try:
                        p._remove_from_map()
                    except Exception:
                        pass
                return

            if p.inf_hours >= self.max_inf_hours or random.random() < self.gamma:
                p.inf_state, p.inf_hours = "R", 0
                p.inf_severity = 0.0
                p.inf_peak_severity = 0.0
                p.inf_critical_hours = 0
                p.inf_rest_hours = 0
                p.inf_hospital_hours = 0
                p.inf_resting = False
                p.medical_needs_hospitalization = False

        if p.inf_state == "R" and self.waning > 0.0 and random.random() < self.waning:
            p.inf_state = "S"
            p.inf_severity = 0.0
            p.inf_peak_severity = 0.0

        if p.inf_state not in {"I", "R"}:
            p.inf_severity = 0.0
            p.inf_resting = False
            p.medical_needs_hospitalization = False

        # Before the explicit seeding event, keep everyone susceptible without spontaneous spread.
        if not self._seeded:
            return

        if p.inf_state == "S":
            util = self._shelter_util(model)
            distancing = max(0.25, 1.0 - 0.60 * float(model.shelter_distancing_intensity))

            hh_share = self._share_infected(getattr(getattr(p, "household", None), "residents", []))
            sh_share = self._share_infected(getattr(model.shelter, "sheltered_agents", [])) if p.in_shelter else 0.0
            work_share = self._share_infected(getattr(p.workplace, "employees", [])) if p.employed else 0.0
            school_share = self._share_infected(getattr(p.schoolplace, "students", [])) if p.student else 0.0

            contact_pressure = hh_share + work_share + school_share
            if p.in_shelter:
                contact_pressure += (1.0 + util) * sh_share * distancing

            susceptibility = 1.0 + 0.35 * float(p.health_vulnerability)
            susceptibility += 0.15 * float(p.vulnerability)
            susceptibility *= _priority_reduction(model, p)

            contact_intensity = max(
                0.0,
                float(model.infectious_contact_intensity),
            )
            beta = self.beta_base * contact_intensity * (1.0 + 4.5 * contact_pressure) * susceptibility

            beta = min(0.22, max(0.0, beta))
            if random.random() < beta:
                p.inf_state = "I"
                p.inf_hours = 0
                self._initialize_case(model, p)
                self.incidence += 1

        if p.medical_needs_hospitalization:
            model.receive_healthcare(p)


# Vectorborne (stagnant pools)
class VectorborneModule(DiseaseModuleBase):
    """
    Symptoms triggered by proximity to stagnant pools that decay over time.
    """
    name = "vectorborne"
    def __init__(self, base_prob=0.003, shelter_protect=0.65, recover_rate=1/168):
        self.base_prob = base_prob
        self.shelter_protect = shelter_protect
        self.recover_rate = recover_rate
        self.max_symp_hours = 24 * 14
        self.incidence = 0

    def step(self, model):
        self.incidence = 0

    def apply_to_person(self, model, p):
        if not p.alive:
            return
        if not hasattr(p, "symp_vector"):
            p.symp_vector = False
        if not hasattr(p, "ill_vector"):
            p.ill_vector = False
        if not hasattr(p, "ill_vector_hours"):
            p.ill_vector_hours = 0

        try:
            h = model.space.get_stagnant_hazard_at_position(getattr(p, "geometry", None))
        except Exception:
            h = 0.0
        if h > 0.0 and not p.symp_vector:
            exposure_hazard = max(
                0.0,
                float(model.vector_exposure_hazard),
            )
            susceptibility = 1.0 + 0.35 * float(p.health_vulnerability)
            susceptibility += 0.20 * float(p.vulnerability)
            shelter_factor = max(0.0, 1.0 - self.shelter_protect) if p.in_shelter else 1.0
            infection_probability = 1.0 - math.exp(-exposure_hazard * float(h) * susceptibility * shelter_factor)
            if random.random() < _clip01(infection_probability):
                p.symp_vector = True
                p.ill_vector = True
                p.ill_vector_hours = 0
                self.incidence += 1

        if p.symp_vector:
            p.ill_vector_hours = int(p.ill_vector_hours or 0) + 1

        if p.symp_vector and (
            p.ill_vector_hours >= self.max_symp_hours
            or random.random() < (self.recover_rate * (1.0 + 0.5 * float(model.vector_control_intensity)))
        ):
            p.symp_vector = False
            p.ill_vector = False
            p.ill_vector_hours = 0

        if p.symp_vector and random.random() < float(model.vector_hospital_seek_prob):
            model.receive_healthcare(p)


# Mold (post-flood damp housing)
class MoldModule(DiseaseModuleBase):
    """
    Respiratory symptoms tied to damp/moldy homes; affects return behavior.
    """
    name = "mold"
    def __init__(self, base_prob=0.003, sens_high_share=0.20, sens_mult=2.4, recover_rate=1/84):
        self.base_prob = base_prob
        self.sens_high_share = sens_high_share
        self.sens_mult = sens_mult
        self.recover_rate = recover_rate
        self.max_symp_hours = 24 * 14
        self.incidence = 0

    def step(self, model):
        self.incidence = 0

    def apply_to_person(self, model, p):
        if not p.alive:
            return
        if not hasattr(p, "symp_mold"):
            p.symp_mold = False
        if not hasattr(p, "mold_sensitive"):
            p.mold_sensitive = (random.random() < self.sens_high_share)
        if not hasattr(p, "ill_respiratory"):
            p.ill_respiratory = False
        if not hasattr(p, "ill_respiratory_hours"):
            p.ill_respiratory_hours = 0

        h = p.household
        at_home = bool(h and not p.in_shelter and not p.evacuated)
        if at_home and not p.symp_mold:
            damp_h = float(getattr(h, "damp_hours", 0) or 0.0)
            mold_i = float(getattr(h, "mold_index", 0.0) or 0.0)
            # House dynamics now determine when mold starts (24h after flood fully recedes)
            # and how long it persists. Disease onset follows active mold burden at home.
            symptom_threshold = float(model.mold_symptom_threshold)
            if damp_h >= 12 and mold_i > symptom_threshold:
                target_ids = set(getattr(h, "mold_health_target_ids", set()) or set())
                if target_ids and str(p.name) not in target_ids:
                    return
                prob = self.base_prob * (1 + 1.8 * mold_i)
                if p.mold_sensitive:
                    prob *= self.sens_mult
                prob *= max(0.25, 1.0 - 0.5 * float(model.repair_subsidy_intensity))
                prob *= _priority_reduction(model, p)
                if random.random() < prob:
                    p.symp_mold = True
                    p.ill_respiratory = True
                    p.ill_respiratory_hours = 0
                    self.incidence += 1

        if p.symp_mold:
            p.ill_respiratory_hours = int(p.ill_respiratory_hours or 0) + 1

        if p.symp_mold and (
            p.ill_respiratory_hours >= self.max_symp_hours
            or random.random() < (self.recover_rate * (1.0 + float(model.repair_subsidy_intensity)))
        ):
            p.symp_mold = False
            p.ill_respiratory = False
            p.ill_respiratory_hours = 0

        if p.symp_mold and random.random() < float(model.mold_hospital_seek_prob):
            model.receive_healthcare(p)
