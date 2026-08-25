# Business agent for the flood-disease ABM.
import uuid, random, math
from mesa_geo import GeoAgent

class Business(GeoAgent):
    """Commercial entity that tracks flood status, cleanup, revenue, and wages."""

    def __init__(self, model=None, geometry=None, crs=None, unique_id=None, **kwargs):
        try:
            super().__init__(model=model, geometry=geometry, crs=crs, unique_id=unique_id)
        except TypeError:
            super().__init__(model, geometry, crs)
        self.name: str = str(uuid.uuid4())
        self.wealth: float = 0.0
        self.type: str | None = None
        self.employees: list = []

        # Flooding and status.
        self.resilience: float = float(max(5.0, min(50.0, random.uniform(15, 25))))
        self.flooded: bool = False
        self.ever_flooded: bool = False
        self.time_flooded: int = 0
        self.last_depth: float = 0.0
        self._peak_depth: float = 0.0

        # Hysteresis margins around the flood threshold.
        self._flood_on_margin: float = float(model.structure_flood_on_margin)
        self._flood_off_margin: float = float(model.structure_flood_off_margin)

        # Cleanup phase after water recedes.
        self._cleanup_hours_left: int = 0
        self._repair_budget_remaining: float = 0.0
        self.hours_closed_flood: int = 0        # kept for your existing metrics
        self.hours_closed_cleanup: int = 0      # optional extra (not used by your summary)

        # Post-flood damp and mold dynamics.
        self.damp_active: bool = False
        self.damp_hours: float = 0.0
        self.damp_level: float = 0.0
        self.mold_index: float = 0.0
        self.mold_intensity: float = 0.0
        self.mold_duration_target_h: float = 0.0
        self._pending_mold_start: bool = False
        self._flood_clear_hour: int | None = None
        self._mold_susceptible: bool = False

        # Operations and accounting.
        self.total_sales: float = 0.0
        self.total_net_revenue: float = 0.0
        self.total_wages_paid: float = 0.0
        self.repair_cost_accum: float = 0.0

        # Cache a stable interior point for repeated depth queries.
        try:
            self._rp = geometry.representative_point()
        except Exception:
            self._rp = None

    def is_open(self) -> bool:
        return (not self.flooded) and (self._cleanup_hours_left <= 0)

    def receive_net_revenue(self, net_amount: float, gross_amount: float | None = None):
        try:
            net = float(net_amount)
        except Exception:
            return
        if net <= 0:
            return

        self.wealth += net
        self.total_net_revenue += net
        if gross_amount is not None:
            try:
                g = float(gross_amount)
                if g > 0:
                    self.total_sales += g
            except Exception:
                pass

        self._emit("biz_revenue", net=net, gross=gross_amount)

    def pay_wage(self, amount: float):
        try:
            amt = float(amount)
        except Exception:
            return
        if amt <= 0:
            return
        self.wealth -= amt
        self.total_wages_paid += amt
        self._emit("biz_wage", wage=amt)

    def _hourly_ops_spend(self):
        if not self.is_open():
            return
        # Spend a small random amount to another open business if available.
        if random.random() < 0.05:
            spend = random.uniform(2.0, 20.0)
            if self.wealth > spend:
                self.wealth -= spend
                # choose recipient
                Bs = getattr(self.model.space, "businesses", [])
                if Bs:
                    recipients = [b for b in Bs if (b is not self) and b.is_open()]
                    if not recipients:
                        recipients = [b for b in Bs if (b is not self)]
                    if recipients and hasattr(self.model, "business_revenue"):
                        rec = random.choice(recipients)
                        self.model.business_revenue(rec, spend)
                        self._emit("biz_ops_spend", amount=spend, recipient=getattr(rec, "name", None))

    # --------- Core dynamics ---------
    def step(self):
        # Sample local flood depth.
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
    
        # Track previous state for transition events.
        was_flooded = self.flooded
        was_cleanup = (self._cleanup_hours_left > 0)
        was_open = self.is_open()
    
        # Flood hysteresis around the threshold.
        mult = float(self.model.biz_flood_thresh_mult)
        thresh = max(0.05, (self.resilience / 10.0) * mult)  # meters
        if self.flooded:
            if depth < self._flood_off_margin * thresh:
                # Water receded enough to enter cleanup.
                flooded_hours = self.time_flooded
                peak_depth = self._peak_depth
                self.flooded = False
                self.time_flooded = 0  # reset like House/School agents
    
                # Cleanup time depends on peak depth and resilience.
                cleanup_h = (
                    float(self.model.structure_cleanup_base_hours)
                    + self._peak_depth * float(self.model.structure_cleanup_depth_hours)
                    + max(0.0, (25.0 - self.resilience) / float(self.model.structure_cleanup_resilience_divisor))
                )
                self._cleanup_hours_left = int(min(self.model.structure_cleanup_max_hours, max(1, math.ceil(cleanup_h))))

                # Mold-enabled scenarios carry dedicated business repair spend.
                if self.model.enable_mold:
                    intensity = max(0.0, min(1.0, random.random()))
                    repair_scale = (
                        1.0 + float(self.model.structure_repair_intensity_scale) * intensity
                    ) * random.uniform(
                        float(self.model.structure_repair_variation_min),
                        float(self.model.structure_repair_variation_max),
                    )
                    repair_mult = max(0.0, float(self.model.business_repair_cost_multiplier))
                    repair_cost = max(
                        0.0,
                        (
                            float(self.model.structure_repair_base_cost)
                            + float(self.model.structure_repair_depth_cost) * self._peak_depth
                        ) * repair_scale * repair_mult,
                    )
                    self._repair_budget_remaining += repair_cost
                    self._emit("biz_repair_cost_budget", amount=repair_cost, intensity=intensity, peak_depth=self._peak_depth)
                self._emit(
                    "business_cleanup_start",
                    peak_depth=self._peak_depth,
                    cleanup_hours=self._cleanup_hours_left
                )
                self._peak_depth = 0.0
            else:
                self.time_flooded += 1
                self.hours_closed_flood += 1
                self._peak_depth = max(self._peak_depth, depth)
        else:
            if depth > self._flood_on_margin * thresh:
                # Newly flooded.
                self.flooded = True
                self.ever_flooded = True
                self.time_flooded = 1
                self.hours_closed_flood += 1
                self._peak_depth = depth

        if self.model.enable_mold:
            if was_flooded and (not self.flooded):
                self._pending_mold_start = True
                self._flood_clear_hour = None
                height_limit = float(self.model.home_unsafe_depth_m)
                duration_limit = float(self.model.damp_metric_hours)
                structurally_eligible = peak_depth >= height_limit or flooded_hours >= duration_limit
                mold_rate = max(0.0, min(1.0, float(self.model.business_mold_rate)))
                self._mold_susceptible = structurally_eligible and random.random() < mold_rate
                self.damp_active = False
                self.damp_hours = 0.0
                self.damp_level = 0.0

            if self._pending_mold_start:
                if not self.flooded:
                    if self._flood_clear_hour is None:
                        self._flood_clear_hour = int(self.model.hours)
                    elif int(self.model.hours) - int(self._flood_clear_hour) >= 24:
                        self._pending_mold_start = False
                        if self._mold_susceptible:
                            if self.ever_flooded:
                                self.damp_active = True
                                self.damp_hours = 0.0
                                self.damp_level = 1.0
                                self.mold_intensity = max(0.0, min(1.0, random.random()))
                                self.mold_duration_target_h = (
                                    float(self.model.structure_mold_duration_base_hours)
                                    + float(self.model.structure_mold_duration_intensity_hours) * self.mold_intensity
                                )
                            else:
                                self.damp_active = False
                                self.damp_hours = 0.0
                                self.damp_level = 0.0
                        else:
                            self.damp_active = False
                            self.damp_hours = 0.0
                            self.damp_level = 0.0
            if self.flooded:
                self._pending_mold_start = False
                self._flood_clear_hour = None
                self._mold_susceptible = False
                self.damp_active = False
                self.damp_hours = 0.0
                self.damp_level = 0.0

            if self.damp_active:
                base_hl = float(self.model.damp_half_life_h)
                resilience_effect = float(self.model.damp_resilience_effect)
                eff_hl = max(6.0, base_hl / (1.0 + resilience_effect * (self.resilience / 50.0)))
                self.damp_level *= 0.5 ** (1.0 / eff_hl)
                self.damp_hours += 1.0

                if self.damp_hours <= float(self.mold_duration_target_h):
                    wetness = self.damp_level
                    ramp = max(0.10, min(1.0, self.damp_hours / 72.0))
                    growth = (0.006 + 0.055 * self.mold_intensity) * (0.5 + wetness) * ramp
                    self.mold_index = max(0.0, min(1.0, self.mold_index + growth))
                else:
                    self.mold_index = max(0.0, self.mold_index - 0.04)

                done_thr = float(self.model.damp_done_threshold)
                if self.damp_level <= done_thr and self.damp_hours >= float(self.mold_duration_target_h) and self.mold_index <= 0.02:
                    self.damp_active = False
                    self.damp_level = 0.0
        else:
            self.damp_active = False
            self.damp_hours = 0.0
            self.damp_level = 0.0
            self.mold_index = 0.0
            self.mold_intensity = 0.0
            self.mold_duration_target_h = 0.0
            self._pending_mold_start = False
            self._flood_clear_hour = None
            self._mold_susceptible = False
    
        # --- 3) Cleanup countdown (if applicable)
        if (not self.flooded) and (self._cleanup_hours_left > 0):
            # Spend repair budget gradually during cleanup to avoid one-hour expense spikes.
            if self._repair_budget_remaining > 0.0:
                hours_left = max(1, int(self._cleanup_hours_left))
                base_hourly = self._repair_budget_remaining / hours_left
                hourly = min(self._repair_budget_remaining, max(0.0, base_hourly * random.uniform(0.80, 1.20)))
                if hourly > 0.0:
                    self.wealth -= hourly
                    self.repair_cost_accum += hourly
                    self._repair_budget_remaining -= hourly
                    self._emit("biz_repair_cost", amount=hourly, remaining=self._repair_budget_remaining)
            self._cleanup_hours_left -= 1
            self.hours_closed_cleanup += 1
            if self._cleanup_hours_left <= 0:
                # Reopen now that cleanup is finished
                if self._repair_budget_remaining > 0.0:
                    leftover = float(self._repair_budget_remaining)
                    self.wealth -= leftover
                    self.repair_cost_accum += leftover
                    self._emit("biz_repair_cost", amount=leftover, remaining=0.0)
                    self._repair_budget_remaining = 0.0
                self._emit("business_reopened")

        # Ongoing fixed losses while not operational (flooded or cleanup).
        if self.flooded or self._cleanup_hours_left > 0:
            burn_rate = max(0.0, float(self.model.business_closed_hourly_burn_rate))
            base = max(0.0, float(self.wealth))
            burn = base * burn_rate
            if burn > 0.0:
                self.wealth -= burn
                self._emit("biz_closed_hourly_burn", amount=burn, rate=burn_rate)

            if self.model.enable_mold and self.mold_index > 0.0:
                mold_rate = max(0.0, float(self.model.business_mold_ops_penalty_rate))
                mold_penalty = max(0.0, float(self.wealth)) * mold_rate * self.mold_index
                if mold_penalty > 0.0:
                    self.wealth -= mold_penalty
                    self._emit("biz_mold_ops_penalty", amount=mold_penalty, mold_index=self.mold_index)
    
        # --- 4) Transition events
        if (not was_flooded) and self.flooded:
            self._emit("business_flooded", depth=self.last_depth, resilience_m=self.resilience / 10.0)
    
        if was_open and not self.is_open():
            # Closed this hour (either flooded now or entered cleanup)
            penalty_rate = max(0.0, float(self.model.business_close_penalty_rate))
            penalty_min = max(0.0, float(self.model.business_close_penalty_min))
            penalty = max(penalty_min, max(0.0, self.wealth) * penalty_rate)
            if penalty > 0.0:
                self.wealth -= penalty
                self._emit("biz_close_penalty", amount=penalty, rate=penalty_rate)
            self._emit("business_closed", reason=("flood" if self.flooded else "cleanup"), penalty=penalty)
    
        # --- 5) Light ops when open (small spend to keep economy circulating)
        self._hourly_ops_spend()


    # --------- Emit helper ----------
    def _emit(self, name: str, **payload):
        coll = getattr(self.model, "collect", None)
        if coll and hasattr(coll, "emit_event"):
            coll.emit_event(name, {"business": self.name, **payload})
