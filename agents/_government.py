# Government agent for the flood-disease ABM.

import uuid
from mesa_geo import GeoAgent

class Government(GeoAgent):
    """Collects revenue indirectly and redistributes funds through grants."""

    def __init__(self, model=None, geometry=None, crs=None, unique_id=None, **kwargs):
        try:
            super().__init__(model=model, geometry=geometry, crs=crs, unique_id=unique_id)
        except TypeError:
            super().__init__(model, geometry, crs)
        self.name = str(uuid.uuid4())
        self.wealth: float = 0.0

        # Analytics counters updated by the tax helpers.
        self.total_sales_tax: float = 0.0
        self.total_income_withholding: float = 0.0
        self.total_corporate_tax: float = 0.0
        self.total_transfers: float = 0.0

        # Policy knobs.
        self.baseline_every_hours: int = 24
        self.baseline_share = {
            "shelter":    0.03,
            "healthcare": 0.03,
            "school":     0.01
        }
        self.grants_by_reason = {}
        
        # Event triggers.
        self.shelter_load_hi: float = 0.80
        self.shelter_cash_min: float = 5_000.0
        self.healthcare_load_hi: float = 0.85
        self.healthcare_cash_min: float = 5_000.0

        # Cap to avoid runaway grants.
        self.max_grant_per_tick: float = 50_000.0

        # Cadence bookkeeping.
        self._last_baseline_hour: int | None = None

    # --------- core primitive ----------
    def grant(self, target, amount: float, reason: str = "baseline"):
        try:
            amount = float(amount)
        except Exception:
            return
        if amount <= 0 or target is None or not hasattr(target, "wealth"):
            return
        # Transfer funds; debt is allowed.
        self.wealth -= amount
        target.wealth += amount

        # Recipient bookkeeping.
        if hasattr(target, "total_grants_received"):
            target.total_grants_received += amount
            target.last_grant_amount = amount
            target.last_grant_hour = self.model.hours

        self.total_transfers += amount

        # Audit trail.
        if hasattr(self.model, "log_transaction"):
            self.model.log_transaction({
                "t": self.model.hours,
                "type": "gov_grant",
                "to": getattr(target, "name", type(target).__name__),
                "amount": amount,
                "reason": reason
            })
        
        self._emit("gov_grant",
               to=getattr(target, "name", type(target).__name__),
               amount=amount,
               reason=reason,
               gov_wealth_after=self.wealth)
        
        self.grants_by_reason[reason] = self.grants_by_reason.get(reason, 0.0) + amount

    # --------- policy runner ----------
    def step(self):
        h = self.model.hours

        # Baseline support.
        if (self._last_baseline_hour is None) or (h - self._last_baseline_hour >= self.baseline_every_hours):
            self._last_baseline_hour = h
            self._baseline_grants()

        # Responsive top-ups.
        self._event_grants()

    # --------- policy details ----------
    def _baseline_grants(self):
        shelter_gdp    = self.model.shelter_gdp
        healthcare_gdp = self.model.healthcare_gdp
        school_gdp     = self.model.school_gdp
        schools        = getattr(self.model.space, "schools", None) or []
        shelter_share = float(self.model.gov_baseline_share_shelter)
        healthcare_share = float(self.model.gov_baseline_share_healthcare)
        school_share = float(self.model.gov_baseline_share_school)
    
        shelters = list(self.model.shelters)
        if not shelters and self.model.shelter is not None:
            shelters = [self.model.shelter]
        if shelters:
            amt = min(self.max_grant_per_tick, shelter_share * shelter_gdp)
            if amt > 0:
                per_shelter = amt / len(shelters)
                for shelter in shelters:
                    self.grant(shelter, per_shelter, reason="baseline_shelter")
    
        healthcares = list(self.model.healthcares)
        if not healthcares and self.model.healthcare is not None:
            healthcares = [self.model.healthcare]
        if healthcares:
            amt = min(self.max_grant_per_tick, healthcare_share * healthcare_gdp)
            if amt > 0:
                per_healthcare = amt / len(healthcares)
                for healthcare in healthcares:
                    self.grant(healthcare, per_healthcare, reason="baseline_healthcare")
    
        if schools:
            total = min(self.max_grant_per_tick, school_share * school_gdp)
            if total > 0:
                per = total / len(schools)
                for s in schools:
                    self.grant(s, per, reason="baseline_school")


    def _event_grants(self):
        # Shelter stress.
        shelters = list(self.model.shelters)
        if not shelters and self.model.shelter is not None:
            shelters = [self.model.shelter]
        for shelter in shelters:
            if hasattr(shelter, "capacity_limit") and hasattr(shelter, "sheltered_agents"):
                cap = max(1, int(shelter.capacity_limit))
                load = min(1.0, len(shelter.sheltered_agents) / cap)
                pending = len(shelter._pending_rescues)
                low_cash = shelter.wealth < self.shelter_cash_min

                if (load > self.shelter_load_hi) or (pending > cap) or low_cash:
                    # Scale the grant by load, queue pressure, and cash gap.
                    need = (
                        max(0.0, load - self.shelter_load_hi) * 0.5 +
                        max(0, pending - cap) / cap * 0.3 +
                        max(0.0, (self.shelter_cash_min - shelter.wealth) / max(self.shelter_cash_min, 1.0)) * 0.2
                    )
                    shelter_scale = float(self.model.gov_event_shelter_grant_scale)
                    amt = min(self.max_grant_per_tick, shelter_scale * need)
                    if amt > 0:
                        self.grant(shelter, amt, reason="event_shelter_stress")

        # Healthcare stress.
        healthcares = list(self.model.healthcares)
        if not healthcares and self.model.healthcare is not None:
            healthcares = [self.model.healthcare]
        for healthcare in healthcares:
            if hasattr(healthcare, "capacity_limit") and hasattr(healthcare, "hospitalized_agents"):
                cap = max(1, int(healthcare.capacity_limit))
                load = len(healthcare.hospitalized_agents) / cap
                low_cash = healthcare.wealth < self.healthcare_cash_min

                if (load > self.healthcare_load_hi) or low_cash:
                    need = (
                        max(0.0, load - self.healthcare_load_hi) * 0.6 +
                        max(0.0, (self.healthcare_cash_min - healthcare.wealth) / max(self.healthcare_cash_min, 1.0)) * 0.4
                    )
                    healthcare_scale = float(self.model.gov_event_healthcare_grant_scale)
                    amt = min(self.max_grant_per_tick, healthcare_scale * need)
                    if amt > 0:
                        self.grant(healthcare, amt, reason="event_healthcare_stress")


    def _emit(self, name: str, **payload):
        coll = getattr(self.model, "collect", None)
        if coll and hasattr(coll, "emit_event"):
            coll.emit_event(name, {"government": self.name, **payload})