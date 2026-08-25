# Healthcare agent for the flood-disease ABM.
import uuid, random, math
from typing import Dict
from mesa_geo import GeoAgent

class Healthcare(GeoAgent):
    """Hospital queue with capacity, transfer timing, costs, and care-related bookkeeping."""
    # Tunables.
    transfer_speed_mps: float = 8.0
    turnaround_minutes: float = 20.0
    base_admit_cost: float = 120.0
    km_cost: float = 2.0
    hazard_radius_m: float = 300.0
    max_wait_hours_cap: float = 12.0
    hospital_recovery_boost: float = 2.5
    self_present_fee: float = 40.0


    def __init__(self, model=None, geometry=None, crs=None, unique_id=None, **kwargs):
        try:
            super().__init__(model=model, geometry=geometry, crs=crs, unique_id=unique_id)
        except TypeError:
            super().__init__(model, geometry, crs)
        self.name = str(uuid.uuid4())
        self.transfer_speed_mps = float(model.healthcare_transfer_speed_mps)
        self.turnaround_minutes = float(model.healthcare_turnaround_minutes)
        self.base_admit_cost = float(model.healthcare_base_admit_cost)
        self.km_cost = float(model.healthcare_km_cost)
        self.hazard_radius_m = float(model.healthcare_hazard_radius_m)
        self.max_wait_hours_cap = float(model.healthcare_max_wait_hours_cap)
        self.hospital_recovery_boost = float(model.healthcare_hospital_recovery_boost)
        self.self_present_fee = float(model.healthcare_self_present_fee)
        self.wealth: float = 0.0
        self.capacity_limit: int = 0
        self.hospitalized_agents: list = []
        self._pending_admissions: Dict[object, int] = {}
        self._admitted_since: Dict[object, int] = {}
        # Patients who are ready for discharge but still waiting for placement.
        self._ready_for_discharge: set = set()
        self._ready_since: Dict[object, int] = {}
        # Grant bookkeeping.
        self.total_grants_received = 0.0
        self.last_grant_amount = 0.0
        self.last_grant_hour = None
        
        self.total_admitted = 0
        self.total_discharged = 0
        self.peak_load = 0
        self.total_queued_from_shelter = 0
        self.total_queued_self = 0
        self.total_self_present = 0
        self.ops_spend_total = 0.0          # admission ops costs (ambulance, etc.)
        self.supplies_spend_total = 0.0     # per-hour supplies during care
        self.patient_revenue_total = 0.0
        self.bad_debt_total = 0.0


    # Public API.

    def request_admission_from_shelter(self, shelter, person) -> None:
        """Queue a transfer from shelter to hospital."""
        if not getattr(person, "alive", True):
            return
        if bool(getattr(person, "evacuated", False)) and self.model.disaster_period != "post_flood":
            return
        if person in self.hospitalized_agents or person in self._pending_admissions:
            return

        s_pt = getattr(shelter, "geometry", None)
        if s_pt is None:
            return
        self._queue_eta(source_point=s_pt, requester="shelter", person=person)
        self.total_queued_from_shelter += 1
        self._emit("hc_admission_requested",
                   requester="shelter",
                   person=getattr(person, "name", None))


    def request_admission_self(self, person) -> None:
        """Queue a self-presenting patient for care and charge the out-of-pocket fee."""
        if not getattr(person, "alive", True) or not self._needs_admission(person):
            return
        if bool(getattr(person, "evacuated", False)) and self.model.disaster_period != "post_flood":
            return
        if person in self.hospitalized_agents or person in self._pending_admissions:
            return

        # Self-presenting patients pay the healthcare facility directly.
        spend = (
            self.self_present_fee
            * self._patient_cost_multiplier()
            * self._cause_cost_multiplier(person)
            * self._severity_bill_multiplier(person)
            * self._person_cost_variability(person)
        )
        collected, debt = self._collect_patient_payment(person, spend, self._active_cost_causes(person))
        self.total_self_present += 1
        self._emit("hc_self_present_fee",
                   person=getattr(person, "name", None),
                   fee=spend,
                   collected=collected,
                   debt=debt)


        p_pt = getattr(person, "geometry", None)
        if p_pt is None:
            return
        self._queue_eta(source_point=p_pt, requester="self", person=person)
        self.total_queued_self += 1
        self._emit("hc_admission_requested",
                   requester="self",
                   person=getattr(person, "name", None))


    # Internal helpers.

    def _local_hospital_hazard_depth(self) -> float:
        """Return the local flood depth near the hospital."""
        depth = 0.0
        sp = self.model.space
        if sp and hasattr(sp, "get_flood_height_at_position"):
            try:
                # Prefer a radius-aware API if your space provides one
                if hasattr(sp, "max_depth_within_radius"):
                    depth = float(sp.max_depth_within_radius(self.geometry, self.hazard_radius_m))
                else:
                    depth = float(sp.get_flood_height_at_position(self.geometry))
            except Exception:
                depth = 0.0
        return max(0.0, depth)

    def _queue_eta(self, source_point, requester: str, person):
        # Distance.
        dist_m = float(self.geometry.representative_point().distance(source_point))
        # Slow the transfer when the hospital campus is surrounded by floodwater.
        d_hosp = self._local_hospital_hazard_depth()
        depth_norm = max(0.0, min(1.0, d_hosp / 1.5))
        speed_mult = max(0.30, 1.0 - 0.6 * depth_norm)  # 1.0 → 0.4 as depth rises
        eff_speed = max(0.5, self.transfer_speed_mps * speed_mult)

        travel_h = (dist_m / (eff_speed * 3600.0))  # one-way
        # Shelter transfers are round trips; self-presenting patients are one-way.
        is_shelter = (requester == "shelter")
        travel_total_h = (2.0 * travel_h) if is_shelter else travel_h

        overhead_h = self.turnaround_minutes / 60.0
        base_time_h = travel_total_h + overhead_h

        # Funds friction: if operating funds are tight, the ETA stretches.
        req_cash = self.base_admit_cost + self.km_cost * (dist_m / 1000.0)
        if self.wealth <= 0:
            funds_factor = 1.6
        else:
            ratio = max(0.0, (req_cash - self.wealth) / max(req_cash, 1e-6))
            funds_factor = 1.0 + 0.6 * ratio

        # Mild queue pressure if demand exceeds capacity.
        cap = max(1, int(self.capacity_limit))
        queue_excess = max(0, len(self._pending_admissions) + len(self.hospitalized_agents) - cap)
        queue_factor = 1.0 + 0.25 * (queue_excess / cap)

        wait_h = min(self.max_wait_hours_cap, base_time_h * funds_factor * queue_factor)
        now_h = self.model.hours
        eta = now_h + max(1, math.ceil(wait_h))
        self._pending_admissions[person] = eta
        self._emit("hc_admission_queued",
           requester=requester,
           person=getattr(person, "name", None),
           eta_hour=eta,
           dist_m=dist_m,
           hosp_depth=d_hosp,
           effective_speed_mps=eff_speed)

    @staticmethod
    def _active_cost_causes(person) -> list[str]:
        causes: list[str] = []
        if person.injured:
            causes.append("flood")
        if bool(getattr(person, "symp_mold", False) or person.ill_respiratory):
            causes.append("mold")
        if bool(getattr(person, "symp_vector", False) or person.ill_vector):
            causes.append("vectorborne")
        if str(getattr(person, "inf_state", "S") or "S") == "I":
            causes.append("infectious")
        if not causes:
            causes.append("flood")
        return causes

    def _needs_admission(self, person) -> bool:
        if person.injured:
            return True
        if bool(
            getattr(person, "symp_mold", False)
            or person.ill_respiratory
            or getattr(person, "symp_vector", False)
            or person.ill_vector
        ):
            return True
        if bool(getattr(person, "medical_needs_hospitalization", False)):
            return True
        return bool(getattr(person, "medical_needs_hospitalization", False))

    @staticmethod
    def _allocate_patient_cost(person, amount: float, causes: list[str]):
        amt = max(0.0, float(amount or 0.0))
        if amt <= 0.0:
            return
        tags = list(causes or ["flood"])
        share = amt / max(1, len(tags))
        for c in tags:
            if c == "mold":
                person.healthcare_expense_mold_accum += share
                person.ever_hc_mold = True
            elif c == "vectorborne":
                person.healthcare_expense_vectorborne_accum += share
                person.ever_hc_vectorborne = True
            elif c == "infectious":
                person.healthcare_expense_infectious_accum += share
                person.ever_hc_infectious = True
            else:
                person.healthcare_expense_flood_accum += share
                person.ever_hc_flood = True
        active_tags = set(tags)
        if len(active_tags.intersection({"flood", "mold", "vectorborne", "infectious"})) >= 2:
            person.ever_hc_compound = True

    def _patient_cost_multiplier(self) -> float:
        # Global pricing policy: 50% lower patient-facing healthcare spend in all scenarios.
        return max(0.0, float(self.model.patient_healthcare_cost_multiplier))

    @staticmethod
    def _person_cost_variability(person) -> float:
        return max(0.4, person.expense_variability_factor)

    def _cause_cost_multiplier(self, person) -> float:
        mult = 1.0
        if bool(getattr(person, "symp_vector", False) or person.ill_vector):
            mult *= max(0.1, float(self.model.vector_healthcare_cost_multiplier))
        if bool(getattr(person, "symp_mold", False) or person.ill_respiratory):
            mult *= max(0.1, float(self.model.mold_healthcare_cost_multiplier))
        return mult

    @staticmethod
    def _severity_bill_multiplier(person) -> float:
        mult = 1.0
        if person.injured:
            mult *= 1.0 + min(0.50, 0.10 + 0.01 * float(person.time_injured))
        if str(getattr(person, "inf_state", "S") or "S") == "I":
            mult *= 1.0 + min(0.80, 0.25 + 0.75 * max(0.0, float(getattr(person, "inf_severity", 0.0) or 0.0)))
        if bool(getattr(person, "symp_mold", False) or person.ill_respiratory):
            mult *= 1.0 + min(0.35, 0.08 + 0.0025 * float(person.sick_hours_respiratory))
        if bool(getattr(person, "symp_vector", False) or person.ill_vector):
            mult *= 1.0 + min(0.30, 0.08 + 0.0025 * float(person.sick_hours_vector))
        if bool(getattr(person, "medical_needs_hospitalization", False)):
            mult *= 1.10
        return mult

    def _collect_patient_payment(self, person, amount: float, causes: list[str]) -> tuple[float, float]:
        charge = max(0.0, float(amount or 0.0))
        if charge <= 0.0:
            return 0.0, 0.0

        available_cash = max(0.0, person.income)
        affordability = min(1.0, available_cash / max(charge, 1e-6))

        severity_pressure = 0.0
        if person.injured:
            severity_pressure += min(0.25, 0.08 + 0.01 * float(person.time_injured))
        if str(getattr(person, "inf_state", "S") or "S") == "I":
            severity_pressure += min(0.35, 0.10 + 0.60 * max(0.0, float(getattr(person, "inf_severity", 0.0) or 0.0)))
        if bool(getattr(person, "symp_mold", False) or person.ill_respiratory):
            severity_pressure += min(0.20, 0.06 + 0.002 * float(person.sick_hours_respiratory))
        if bool(getattr(person, "symp_vector", False) or person.ill_vector):
            severity_pressure += min(0.18, 0.05 + 0.002 * float(person.sick_hours_vector))

        collection_fraction = 0.55 + 0.25 * affordability + random.uniform(-0.12, 0.12) - 0.20 * severity_pressure
        collection_fraction = max(0.20, min(1.0, collection_fraction))
        target_payment = charge * collection_fraction
        collected = min(available_cash, target_payment)
        debt = max(0.0, charge - collected)

        person.income = available_cash - collected
        self.wealth += collected
        self.patient_revenue_total += collected
        self.bad_debt_total += debt
        person.healthcare_debt_accum += debt
        if debt > 0.0:
            debt_share = debt / max(1, len(causes or ["flood"]))
            for c in (causes or ["flood"]):
                if c == "mold":
                    person.healthcare_debt_mold_accum += debt_share
                elif c == "vectorborne":
                    person.healthcare_debt_vectorborne_accum += debt_share
                elif c == "infectious":
                    person.healthcare_debt_infectious_accum += debt_share
                else:
                    person.healthcare_debt_flood_accum += debt_share
        self._allocate_patient_cost(person, charge, causes)

        return collected, debt

    @staticmethod
    def _has_non_infectious_active_condition(person) -> bool:
        return bool(
            getattr(person, "injured", False)
            or getattr(person, "symp_mold", False)
            or getattr(person, "ill_respiratory", False)
            or getattr(person, "symp_vector", False)
            or getattr(person, "ill_vector", False)
        )


    # -------------- Core loop --------------

    def admit(self, person):
        if bool(getattr(person, "evacuated", False)) and self.model.disaster_period != "post_flood":
            return False
        if len(self.hospitalized_agents) >= int(self.capacity_limit):
            return False
        if person not in self.hospitalized_agents:
            self.hospitalized_agents.append(person)
        self._admitted_since[person] = int(self.model.hours)
        self.peak_load = max(self.peak_load, len(self.hospitalized_agents))
    
        # NEW: ensure we don't think they're ready yet
        self._ready_for_discharge.discard(person)
        self._ready_since.pop(person, None)
    
        if getattr(person, "in_shelter", False) and hasattr(self.model, "shelter"):
            try:
                sh = self.model.shelter
                if hasattr(sh, "sheltered_agents") and person in sh.sheltered_agents:
                    sh.sheltered_agents.remove(person)
            except Exception:
                pass
        person.in_shelter = False
        person.stranded = False
        person.evacuated = False
        person.ever_affected_hospitalized = True
        person.ever_affected_injured = True
        if hasattr(person, "inf_hospital_hours"):
            person.inf_hospital_hours = 0
        if hasattr(person, "medical_needs_hospitalization"):
            person.medical_needs_hospitalization = False
    
        try:
            if hasattr(person, "_add_back_to_map") and not getattr(person, "_in_map", True):
                person._add_back_to_map()
            pos = self.geometry.representative_point()
            self.model.space.move_agent(person, pos)
        except Exception:
            pass
        
        self.total_admitted += 1
        self._emit("hc_admit", person=getattr(person, "name", None))
        return True



    def discharge(self, person):
        """Remove from hospital custody (no movement/placement here)."""
        if person in self.hospitalized_agents:
            self.hospitalized_agents.remove(person)
        self._admitted_since.pop(person, None)
        self._ready_for_discharge.discard(person)
        self._ready_since.pop(person, None)
        self.total_discharged += 1
        self._emit("hc_discharge", person=getattr(person, "name", None))

        return True


    def step(self):
        # Resolve pending admissions whose ETA has arrived and capacity allows
        now_h = self.model.hours
        for p, eta in list(self._pending_admissions.items()):
            if not p.alive:
                self._pending_admissions.pop(p, None)
                continue
            if p.evacuated and self.model.disaster_period != "post_flood":
                self._pending_admissions.pop(p, None)
                continue
            if eta <= now_h and len(self.hospitalized_agents) < int(self.capacity_limit):
                dist_m = float(self.geometry.representative_point().distance(getattr(p, "geometry", self.geometry)))
                ops_cost = self.base_admit_cost + self.km_cost * (dist_m / 1000.0)

                if self.admit(p):
                    self._pending_admissions.pop(p, None)
                    # Charge operating costs only after the admission succeeds.
                    self.wealth -= ops_cost
                    businesses = self.model.space.businesses
                    if businesses and hasattr(self.model, "business_revenue"):
                        biz = random.choice([b for b in businesses if not b.flooded] or businesses)
                        pass_through = float(self.model.institutional_procurement_pass_through)
                        self.model.business_revenue(biz, ops_cost * max(0.0, min(1.0, pass_through)))
                    self.ops_spend_total += float(ops_cost)
                    self._emit("hc_ops_spend",
                               person=getattr(p, "name", None),
                               ops_cost=ops_cost,
                               dist_m=dist_m)

                # if capacity filled, remaining will try in later steps

        # Care progression + billing
        businesses = self.model.space.businesses
        for p in list(self.hospitalized_agents):
            if not p.alive:
                self._ready_for_discharge.discard(p)
                self._ready_since.pop(p, None)
                self.discharge(p)
                continue

            # hourly bill: collected payments go to healthcare revenue, and unpaid balance becomes debt
            bill = (
                random.uniform(20, 80)
                * self._patient_cost_multiplier()
                * self._cause_cost_multiplier(p)
                * self._severity_bill_multiplier(p)
                * self._person_cost_variability(p)
            )
            collected, debt = self._collect_patient_payment(p, bill, self._active_cost_causes(p))
            self._emit("hc_bill",
                       person=getattr(p, "name", None),
                       bill=bill,
                       collected=collected,
                       debt=debt)
            # hospital spends a slice of collected revenue immediately on supplies (taxed)
            supplies = collected * random.uniform(0.10, 0.30)
            self.wealth -= supplies
            if businesses and hasattr(self.model, "business_revenue"):
                biz = random.choice([b for b in businesses if not b.flooded] or businesses)
                pass_through = float(self.model.institutional_procurement_pass_through)
                self.model.business_revenue(biz, supplies * max(0.0, min(1.0, pass_through)))
                self.supplies_spend_total += float(supplies)
                self._emit("hc_supplies_spend",
                           person=getattr(p, "name", None),
                           supplies=supplies)

            recovered = False
            admitted_hours = max(
                0,
                int(self.model.hours)
                - int(self._admitted_since.get(p, self.model.hours) or 0),
            )
            minimum_stay_complete = (
                int(self.model.hours)
                > int(self._admitted_since.get(p, -1))
            )

            # Acute-care occupancy must have a finite bound even when symptoms
            # or flood displacement do not resolve before the simulation ends.
            max_stay_hours = max(24, int(self.model.healthcare_max_stay_hours))
            if minimum_stay_complete and admitted_hours >= max_stay_hours:
                recovered = True
                self._emit("hc_max_stay_discharge", person=getattr(p, "name", None), stay_hours=admitted_hours)

            # Generic discharge gate for non-infectious admissions:
            # if all flood-/environmental conditions are resolved and no explicit
            # hospitalization requirement remains, the patient can be discharged.
            if (
                minimum_stay_complete
                and
                str(getattr(p, "inf_state", "S") or "S") != "I"
                and (not self._has_non_infectious_active_condition(p))
                and (not p.medical_needs_hospitalization)
            ):
                recovered = True

            # boosted recovery in hospital for injury cases
            boost = max(1.0, float(self.model.injury_hospital_recovery_boost))
            if minimum_stay_complete and p.injured and random.random() < max(0.02, p.recovery_rate * boost):
                p.injured = False
                p.time_injured = 0
                recovered = True

            if recovered:
                self._emit("hc_recovered", person=getattr(p, "name", None))

                if self._try_place_after_care(p):
                    self._emit("hc_discharge_placed", person=getattr(p, "name", None), destination="home_or_shelter")
                    self.discharge(p)
                else:
                    self._ready_for_discharge.add(p)
                    self._ready_since[p] = int(self.model.hours)
                    self._emit("hc_ready_for_discharge", person=getattr(p, "name", None))
                continue

            # otherwise they remain in care; only injury cases use the injury mortality cap here.
            if p.injured:
                if p.time_injured >= p.survivability_duration:
                    p.alive = False
                    p.death_cause = "injury_in_care"
                    p.injured = False
                    self.discharge(p)
                    self._emit("hc_death", person=getattr(p, "name", None))

                    self._ready_for_discharge.discard(p)
                    try:
                        if hasattr(p, "_remove_from_map"):
                            p._remove_from_map()
                    except Exception:
                        pass
                    
        # Try to place any patients who are medically ready (after care loop)
        for p in list(self._ready_for_discharge):
            if not p.alive:
                self._ready_for_discharge.discard(p)
                self._ready_since.pop(p, None)
                continue
            placed = self._try_place_after_care(p)
            if placed:
                self.discharge(p)
                continue

            ready_since = int(self._ready_since.get(p, now_h))
            wait_limit = max(1, int(self.model.hc_ready_discharge_wait_hours))
            if now_h - ready_since >= wait_limit and self._force_discharge_home(p):
                self._emit("hc_forced_discharge", person=getattr(p, "name", None), wait_hours=now_h - ready_since)
                self.discharge(p)
        
        
    def _move_home(self, person) -> bool:
        """Try to send person home; return True on success."""
        try:
            home = getattr(person, "household", None)
            if home and not getattr(home, "flooded", False):
                # ensure on-map
                if hasattr(person, "_add_back_to_map") and not getattr(person, "_in_map", True):
                    person._add_back_to_map()
                pos = home.geometry.representative_point()
                self.model.space.move_agent(person, pos)
                person.in_shelter = False
                person.evacuated = False
                person.stranded = False
                return True
        except Exception:
            pass
        return False
    
    
    def _try_place_after_care(self, person) -> bool:
        """
        Placement order: home -> shelter.
        Return True once the person has been released from hospital custody.
        """
        # 1) Home
        if self._move_home(person):
            return True

        # Infectious-only runs have no flood displacement; avoid lingering occupancy
        # once medically recovered by forcing a home return fallback immediately.
        if self.model.scenario_mode == "infectious_disease":
            return self._force_discharge_home(person)
    
        # 2) Shelter
        sh = self.model.shelter
        if sh and hasattr(sh, "has_capacity") and sh.has_capacity():
            # shelter.admit will set flags and move the person into the shelter polygon
            if hasattr(sh, "admit") and sh.admit(person):
                return True
    
        # 3) No placement possible: release the patient and let routine movement resume.
        try:
            if hasattr(person, "_add_back_to_map") and not getattr(person, "_in_map", True):
                person._add_back_to_map()
            self._random_discharge_motion(person)
        except Exception:
            pass
        return True

    def _force_discharge_home(self, person) -> bool:
        """Fallback discharge that resumes ordinary movement if home is unavailable."""
        try:
            home = getattr(person, "household", None)
            if home is None:
                if hasattr(person, "_add_back_to_map") and not getattr(person, "_in_map", True):
                    person._add_back_to_map()
                self._random_discharge_motion(person)
                return True
            if hasattr(person, "_add_back_to_map") and not getattr(person, "_in_map", True):
                person._add_back_to_map()
            if not getattr(home, "flooded", False):
                pos = home.geometry.representative_point()
                self.model.space.move_agent(person, pos)
                person.in_shelter = False
                person.evacuated = False
                person.stranded = False
                return True
            self._random_discharge_motion(person)
            return True
        except Exception:
            return False

    def _random_discharge_motion(self, person) -> None:
        """Release a recovered patient into ordinary movement when no safe placement exists."""
        try:
            if hasattr(person, "_random_movement"):
                person._random_movement()
                return
            if hasattr(person, "_add_back_to_map") and not getattr(person, "_in_map", True):
                person._add_back_to_map()
        except Exception:
            pass


    def _emit(self, name: str, **payload):
        coll = getattr(self.model, "collect", None)
        if coll and hasattr(coll, "emit_event"):
            coll.emit_event(name, {"healthcare": self.name, **payload})
