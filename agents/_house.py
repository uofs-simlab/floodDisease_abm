# House agent for the flood-disease ABM.

import uuid, random
from mesa_geo import GeoAgent

class House(GeoAgent):
    """Residential unit that tracks flood status, residents, and habitability signals."""

    def __init__(self, model=None, geometry=None, crs=None, unique_id=None, **kwargs) -> None:
        try:
            super().__init__(model=model, geometry=geometry, crs=crs, unique_id=unique_id)
        except TypeError:
            super().__init__(model=model, geometry=geometry, crs=crs)
        self.name = str(uuid.uuid4())
        self.residents: list = []
        self.resilience: float = float(max(5.0, min(50.0, random.uniform(10, 30))))
        self._flood_on_margin: float  = 1.00
        self._flood_off_margin: float = 0.90
        self.flooded: bool = False
        self.ever_flooded: bool = False
        self.time_flooded: int = 0
        self.wealth: float = 0.0
        self.last_depth: float = 0.0
        self._peak_depth: float = 0.0

        # Damp and mold state.
        self.damp_active = False
        self.damp_hours  = 0.0
        self.damp_level  = 0.0
        self.mold_index  = 0.0
        self.mold_intensity = 0.0
        self.mold_duration_target_h = 0.0
        self.mold_repair_cost_mult = 1.0
        self._pending_mold_start = False
        self._flood_clear_hour: int | None = None
        self._mold_susceptible = False
        self.mold_health_target_ids: set[str] = set()
        self.remediated = False
        self.repair_cost_accum = 0.0

        # Flood history.
        self.was_flooded_last_step = False

        # Cache a stable interior point for repeated depth queries.
        try:
            self._rp = geometry.representative_point()
        except Exception:
            self._rp = None

    def step(self):
        prev = self.flooded

        # Local flood depth.
        depth = 0.0
        sp = self.model.space
        if sp and hasattr(sp, "get_flood_height_at_position"):
            try:
                in_flood_footprint = sp.intersects_active_flood(self.geometry)
                pt = self._rp or self.geometry.representative_point()
                depth = float(sp.get_flood_height_at_position(pt)) if in_flood_footprint else 0.0
            except Exception:
                depth = 0.0
        self.last_depth = depth

        # Flood on/off with hysteresis.
        base = (self.resilience / 10.0)
        mult = float(self.model.house_flood_thresh_mult)
        thresh = max(0.05, base * mult)

        if self.flooded:
            if depth < self._flood_off_margin * thresh:
                flooded_hours = self.time_flooded
                peak_depth = self._peak_depth
                self.flooded = False
                self.time_flooded = 0
                self._peak_depth = 0.0
            else:
                self.time_flooded += 1
                self._peak_depth = max(self._peak_depth, depth)
        else:
            if depth > self._flood_on_margin * thresh:
                self.flooded = True
                self.ever_flooded = True
                self.time_flooded += 1
                self._peak_depth = depth
            else:
                self.time_flooded = 0

        # emit only when the state flips
        if self.flooded != prev:
            self._emit(
                "house_flood_state",
                flooded=self.flooded,
                depth=self.last_depth,
                resilience=self.resilience,
            )

        if self.model.enable_mold:
            # Damp transitions and dynamics.
            # Start the mold clock once this house leaves flooding.
            if self.was_flooded_last_step and (not self.flooded):
                self._pending_mold_start = True
                self._flood_clear_hour = None
                height_limit = float(self.model.home_unsafe_depth_m)
                duration_limit = float(self.model.damp_metric_hours)
                structurally_eligible = peak_depth >= height_limit or flooded_hours >= duration_limit
                mold_rate = max(0.0, min(1.0, float(self.model.house_mold_rate)))
                self._mold_susceptible = structurally_eligible and random.random() < mold_rate
                self.damp_active = False
                self.damp_hours = 0.0
                self.damp_level = 0.0
                self.remediated = False

            if self._pending_mold_start:
                if not self.flooded:
                    if self._flood_clear_hour is None:
                        self._flood_clear_hour = int(self.model.hours)
                    elif int(self.model.hours) - int(self._flood_clear_hour) >= 24:
                        self._pending_mold_start = False
                        if self._mold_susceptible:
                            if not self.ever_flooded:
                                self.damp_active = False
                                self.damp_hours = 0.0
                                self.damp_level = 0.0
                                self.mold_health_target_ids = set()
                            else:
                                self.damp_active = True
                                self.damp_hours = 0.0
                                self.damp_level = 1.0
                                self.mold_intensity = max(0.0, min(1.0, random.random()))
                                self.mold_duration_target_h = 168.0 + 84.0 * self.mold_intensity
                                self.mold_repair_cost_mult = 1.0 + self.mold_intensity
                                residents = [p for p in self.residents if p.alive]
                                if residents:
                                    k = min(len(residents), random.choice([1, 2]))
                                    self.mold_health_target_ids = {str(p.name) for p in random.sample(residents, k)}
                                else:
                                    self.mold_health_target_ids = set()
                        else:
                            self.damp_active = False
                            self.damp_hours = 0.0
                            self.damp_level = 0.0
                            self.mold_health_target_ids = set()
                else:
                    self._flood_clear_hour = None

            # While flooded, do not allow drying or damp accumulation.
            if self.flooded:
                self._pending_mold_start = False
                self._flood_clear_hour = None
                self.damp_active = False
                self.damp_hours  = 0.0
                self.damp_level  = 0.0
                self._mold_susceptible = False
                self.mold_health_target_ids = set()

            # Drying when damp is active; speed scales with resilience.
            if self.damp_active:
                base_hl = float(self.model.damp_half_life_h)
                boost   = float(self.model.damp_resilience_effect)
                eff_hl  = max(6.0, base_hl / (1.0 + boost * (self.resilience / 50.0)))
                # Exponential decay per hour.
                self.damp_level *= 0.5 ** (1.0 / eff_hl)
                self.damp_hours += 1.0

                # Mold growth and persistence are sampled per post-flood episode.
                if self.damp_hours <= float(self.mold_duration_target_h):
                    wetness = self.damp_level
                    ramp = max(0.10, min(1.0, self.damp_hours / 72.0))
                    growth = (0.01 + 0.08 * self.mold_intensity) * (0.5 + wetness) * ramp
                    self.mold_index = max(0.0, min(1.0, self.mold_index + growth))
                else:
                    decay = 0.04 + 0.03 * float(self.model.repair_subsidy_intensity)
                    self.mold_index = max(0.0, self.mold_index - decay)

                # Stop damp once sufficiently dry.
                done_thr = float(self.model.damp_done_threshold)
                if self.damp_level <= done_thr and self.damp_hours >= float(self.mold_duration_target_h) and self.mold_index <= 0.02:
                    self.damp_active = False
                    self.damp_level = 0.0
                    self.mold_health_target_ids = set()

            # Optional remediation spend and policy-assisted repairs.
            repair_support = max(0.0, min(1.0, float(self.model.repair_subsidy_intensity)))
            attempt_prob = (0.05 + 0.10 * repair_support) * max(
                0.0,
                float(self.model.house_repair_attempt_scale),
            )
            if self.ever_flooded and self.mold_index > 0.30 and random.random() < attempt_prob:
                cost_scale = max(0.0, float(self.model.house_repair_cost_scale))
                base_cost = float(self.model.house_repair_base_cost)
                variation = float(self.model.repair_cost_variation)
                damage_scale = max(0.25, min(2.0, float(self.mold_index)))
                target_spend = base_cost * damage_scale * random.uniform(max(0.0, 1.0 - variation), 1.0 + variation) * self.mold_repair_cost_mult * (1.0 - 0.60 * repair_support) * cost_scale

                # Post-flood repairs are limited by household finances.
                payers = [p for p in self.residents if p.income > 0.0]
                total_available = sum(p.income for p in payers)
                realized_spend = min(max(0.0, target_spend), max(0.0, total_available))
                if realized_spend > 0.0 and total_available > 0.0:
                    for p in payers:
                        available = p.income
                        share = available / total_available
                        deduction = min(available, realized_spend * share)
                        p.income = available - deduction
                        if deduction > 0.0:
                            p.house_repair_expense_accum += float(deduction)

                self.repair_cost_accum += realized_spend
                completion = 0.0 if target_spend <= 0.0 else min(1.0, realized_spend / target_spend)
                self.mold_index = max(0.0, self.mold_index - ((0.05 + 0.10 * repair_support) * completion))
                self.remediated = self.mold_index < 0.15
                if realized_spend > 0.0 and hasattr(self.model, "business_revenue"):
                    open_biz = [b for b in getattr(self.model.space, "businesses", []) if not getattr(b, "flooded", False)]
                    if open_biz:
                        self.model.business_revenue(random.choice(open_biz), realized_spend)
        else:
            # In scenarios without mold, keep houses free of mold/damp damage and repair spend.
            self.damp_active = False
            self.damp_hours = 0.0
            self.damp_level = 0.0
            self.mold_index = 0.0
            self.mold_intensity = 0.0
            self.mold_duration_target_h = 0.0
            self.mold_repair_cost_mult = 1.0
            self._pending_mold_start = False
            self._flood_clear_hour = None
            self._mold_susceptible = False
            self.mold_health_target_ids = set()
            self.remediated = False

        # remember for next tick (for transition detection)
        self.was_flooded_last_step = bool(self.flooded)

        # Wealth roll-up
        self.wealth = sum(r.income for r in self.residents)

    # Continuous habitability in [0,1]
    def habitability(self) -> float:
        d = self.last_depth
        depth_term = max(0.0, 1.0 - (d / max(1e-6, self.resilience / 10.0)))
        flood_penalty = min(0.2, 0.01 * self.time_flooded)
        damp_penalty  = 0.25 * self.damp_level   # 0..0.25
        mold_penalty  = 0.35 * self.mold_index   # 0..0.35
        return max(0.0, min(1.0, depth_term - flood_penalty - damp_penalty - mold_penalty))

    # Optional helpers—safe to use from assignment utilities
    def add_resident(self, person):
        if person not in self.residents:
            self.residents.append(person)
            person.household = self

    def remove_resident(self, person):
        if person in self.residents:
            self.residents.remove(person)
            if person.household is self:
                person.household = None

    def is_habitable_now(self, thresh: float = 0.5) -> bool:
        try:
            return self.habitability() >= float(thresh)
        except Exception:
            return not self.flooded

    def _emit(self, name: str, **payload):
        coll = getattr(self.model, "collect", None)
        if coll and hasattr(coll, "emit_event"):
            coll.emit_event(name, {"house": self.name, **payload})
