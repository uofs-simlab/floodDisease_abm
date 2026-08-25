# Shelter agent for the flood-disease ABM.

import uuid, random, math
from mesa_geo import GeoAgent

class Shelter(GeoAgent):
    """Capacity-limited shelter that manages rescues, admissions, and procurement."""

    def __init__(self, model=None, geometry=None, crs=None, unique_id=None, **kwargs):
        try:
            super().__init__(model=model, geometry=geometry, crs=crs, unique_id=unique_id)
        except TypeError:
            super().__init__(model, geometry, crs)
        self.name = str(uuid.uuid4())
        self.wealth: float = 0.0
        self.capacity_limit: int = 0
        self.sheltered_agents: list = []
        self.total_admitted = 0
        self.total_discharged = 0
        self.total_transfers_to_hc = 0
        self.procurement_spend_total = 0.0
        self.operating_cost_total = 0.0
        #
        self.total_grants_received = 0.0
        self.last_grant_amount = 0.0
        self.last_grant_hour = None

        # Rescue scheduling.
        # person -> ETA hour (model.hours) when pickup completes.
        self._pending_rescues: dict = {}

        # Tunable rescue knobs.
        self.rescue_speed_mps: float = float(model.shelter_rescue_speed_mps)
        self.turnaround_minutes: float = float(model.shelter_turnaround_minutes)
        self.km_cost: float = float(model.shelter_km_cost)
        self.base_pickup_cost: float = float(model.shelter_base_pickup_cost)
        self.max_wait_hours_cap: float = float(model.shelter_max_wait_hours_cap)

    def has_capacity(self) -> bool:
        return len(self.sheltered_agents) < int(self.capacity_limit)

    def request_rescue(self, person) -> None:
        """
        Queue a rescue request for a stranded person.
        Wait time depends on distance, available funds, and local flooding around the stranded person.
        """
        if not getattr(person, "alive", True):
            return
        if bool(getattr(person, "evacuated", False)) and self.model.disaster_period != "post_flood":
            return
        if person in self._pending_rescues or person in self.sheltered_agents:
            return
    
        # Distance (CRS units; assume meters).
        try:
            p_pt = person.geometry
        except Exception:
            return
        s_pt = self.geometry.representative_point() if hasattr(self.geometry, "representative_point") else self.geometry
        dist_m = float(s_pt.distance(p_pt))
    
        # Local flood hazard at the stranded person's location.
        depth = 0.0
        if hasattr(self.model, "space") and hasattr(self.model.space, "get_flood_height_at_position"):
            try:
                depth = float(self.model.space.get_flood_height_at_position(p_pt))
            except Exception:
                depth = 0.0
    
        # Reduce travel speed as flood depth rises.
        depth_norm = max(0.0, min(1.0, depth / 1.5))
        speed_multiplier = max(0.25, 1.0 - 0.6 * depth_norm)  # 1.0 -> 0.4 as depth rises to 1.5 m
        effective_speed_mps = max(0.5, self.rescue_speed_mps * speed_multiplier)  # keep >0
    
        # Round-trip travel time plus loading and triage overhead.
        travel_hours = (2.0 * dist_m) / (effective_speed_mps * 3600.0)
        overhead_hours = self.turnaround_minutes / 60.0
    
        # Add a local pickup delay when the person's site is heavily flooded.
        local_hazard_delay_h = 0.5 * depth_norm
    
        bare_time_h = travel_hours + overhead_hours + local_hazard_delay_h
    
        # Slow the ETA when shelter funds are tight.
        req_cash = self.base_pickup_cost + self.km_cost * (dist_m / 1000.0)
        if self.wealth <= 0:
            funds_factor = 1.5
        else:
            ratio = max(0.0, (req_cash - self.wealth) / max(req_cash, 1e-6))
            funds_factor = 1.0 + 0.5 * ratio
    
        # Add queue pressure if pending demand exceeds capacity.
        cap = max(1, int(self.capacity_limit))
        queue_excess = max(0, len(self._pending_rescues) - cap)
        queue_factor = 1.0 + 0.25 * (queue_excess / cap)  # gentle scaling
    
        wait_h = min(self.max_wait_hours_cap, bare_time_h * funds_factor * queue_factor)
    
        now_h = self.model.hours
        eta = now_h + max(1, math.ceil(wait_h))
        self._pending_rescues[person] = eta
        
        self._emit("shelter_rescue_queued",
           person=getattr(person, "name", None),
           eta_hour=eta, dist_m=dist_m, depth=depth,
           effective_speed_mps=effective_speed_mps,
           est_wait_h=bare_time_h)



    def admit(self, person):
        """Admit a person if capacity allows and move them into the shelter."""
        if bool(getattr(person, "evacuated", False)) and self.model.disaster_period != "post_flood":
            return False
        if not self.has_capacity():
            return False
        if person not in self.sheltered_agents:
            self.sheltered_agents.append(person)
    
        person.in_shelter = True
        person.time_in_shelter = 0
        # Sheltering is not evacuation.
        person.evacuated = False
        person.stranded = False
        # Optional analytics timestamp.
        if hasattr(person, "t_arrived_shelter"):
            person.t_arrived_shelter = self.model.hours
    
        # Keep them on the map and move them into the shelter polygon.
        try:
            if hasattr(person, "_add_back_to_map") and not getattr(person, "_in_map", True):
                person._add_back_to_map()
            pos = self.geometry.representative_point()
            self.model.space.move_agent(person, pos)
        except Exception:
            pass
    
        self.total_admitted += 1
        self._emit("shelter_admit", person=getattr(person, "name", None))

        return True


    def discharge(self, person):
        """Discharge a person from shelter and optionally return them home."""
        if person in self.sheltered_agents:
            self.sheltered_agents.remove(person)
        person.in_shelter = False
        # This is not an evacuation.
        person.evacuated = False
    
        # Ensure they remain in the simulation.
        try:
            if hasattr(person, "_add_back_to_map") and not getattr(person, "_in_map", True):
                person._add_back_to_map()
        except Exception:
            pass
    
        # Return home only when it is currently habitable; otherwise they remain
        # in the general population and the person's routine chooses another path.
        try:
            household = getattr(person, "household", None)
            home_ok = bool(household and (
                household.is_habitable_now() if hasattr(household, "is_habitable_now")
                else not getattr(household, "flooded", False)
            ))
            if home_ok:
                pos = person.household.geometry.representative_point()
                self.model.space.move_agent(person, pos)
        except Exception:
            pass
        
        self.total_discharged += 1
        self._emit("shelter_discharge", person=getattr(person, "name", None))

        return True


    def _procure_to_business(self, gross_amount: float):
        """Spend money at an open business and let the model handle taxes."""
        if gross_amount <= 0:
            return
        businesses = getattr(self.model.space, "businesses", [])
        if not businesses:
            return
        # Choose only non-flooded businesses.
        open_biz = [b for b in businesses if not getattr(b, "flooded", False)]
        if not open_biz:
            return
        biz = random.choice(open_biz)
        # Shelter pays the bill.
        self.wealth -= gross_amount
        
        self.procurement_spend_total += float(gross_amount)
        self._emit("shelter_procurement",
                   amount=gross_amount,
                   business=getattr(biz, "name", getattr(biz, "unique_id", None)))

        # Business receives net revenue after corporate tax.
        if hasattr(self.model, "business_revenue"):
            pass_through = float(self.model.institutional_procurement_pass_through)
            self.model.business_revenue(biz, gross_amount * max(0.0, min(1.0, pass_through)))
            
    def _emit(self, name: str, **payload):
        coll = getattr(self.model, "collect", None)
        if coll and hasattr(coll, "emit_event"):
            coll.emit_event(name, {"shelter": self.name, **payload})

    def step(self):
        # Process the rescue queue.
        now = self.model.hours
        for person, eta in list(self._pending_rescues.items()):
            if (not getattr(person, "alive", True)) or (not getattr(person, "stranded", False)):
                # No longer applicable.
                del self._pending_rescues[person]
                continue
            if now >= eta and self.has_capacity():
                # Pickup complete.
                admitted = self.admit(person)
                del self._pending_rescues[person]
                # Charge a small per-pickup variable cost on completion.
                if admitted:
                    dist_m = float(self.geometry.representative_point().distance(person.geometry))
                    pickup_cost = self.base_pickup_cost + self.km_cost * (dist_m / 1000.0)
                    # spend with an open business (procurement)
                    self._emit("shelter_rescue_complete",
                    person=getattr(person, "name", None),
                    pickup_cost=pickup_cost)
                    
                    self._procure_to_business(pickup_cost)

        # Operating costs during flood and recovery.
        if self.model.disaster_period in ("during_flood", "post_flood"):
            n = len(self.sheltered_agents)
            if n:
                cost_max = float(self.model.shelter_operating_cost_per_person_max)
                per_person_cost = random.uniform(0, max(0.0, cost_max))
                total_cost = per_person_cost * n
                # Spend part of the cost at open suppliers.
                supplier_fraction = random.uniform(0.0, 0.10)
                self._procure_to_business(total_cost * supplier_fraction)
                # The remainder is internal burn.
                self.wealth -= total_cost * (1.0 - supplier_fraction)
                
                self.operating_cost_total += float(total_cost)
                self._emit("shelter_operating_cost", sheltered=n, total_cost=total_cost)

        # Care loop: move injured people to healthcare and discharge stable people later.
        hc = self.model.healthcare
        hours_before_hc = self.model.hours_before_healthcare

        for p in list(self.sheltered_agents):
            # Transfer to healthcare when capacity is available.
            if getattr(p, "injured", False) and hc:
                if getattr(p, "time_injured", 0) >= hours_before_hc:
                    # Only count/emit when this person isn't already queued or admitted
                    if (p not in getattr(hc, "hospitalized_agents", [])) and \
                       (p not in getattr(hc, "_pending_admissions", {})):
                        if hasattr(hc, "request_admission_from_shelter"):
                            hc.request_admission_from_shelter(self, p)
                            self.total_transfers_to_hc += 1
                            self._emit("shelter_transfer_requested",
                                       person=getattr(p, "name", None))



            household = getattr(p, "household", None)
            home_ok = bool(household and (
                household.is_habitable_now() if hasattr(household, "is_habitable_now")
                else not getattr(household, "flooded", False)
            ))
            # Discharge after recovery, or after the finite shelter stay even
            # when the home remains unavailable.
            flood_end_hour = int(self.model._during_end_h)
            if (getattr(p, "time_in_shelter", 0) >= 12 and home_ok) or (
                self.model.hours >= flood_end_hour + 48
            ):
                self.discharge(p)
