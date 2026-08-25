# School agent for the flood-disease ABM.

import uuid, random
from mesa_geo import GeoAgent

class School(GeoAgent):
    """Education facility that tracks flooding, attendance, and lost student-hours."""

    def __init__(self, model=None, geometry=None, crs=None, unique_id=None, **kwargs):
        try:
            super().__init__(model=model, geometry=geometry, crs=crs, unique_id=unique_id)
        except TypeError:
            super().__init__(model, geometry, crs)
        self.name = str(uuid.uuid4())

        # Flood state.
        self.resilience: float = float(max(5.0, min(50.0, random.uniform(15, 25))))
        self._flood_on_margin: float = float(model.structure_flood_on_margin)
        self._flood_off_margin: float = float(model.structure_flood_off_margin)
        self.flooded: bool = False
        self.ever_flooded: bool = False
        self.time_flooded: int = 0
        self.last_depth: float = 0.0

        # Roster.
        self.students: list = []
        self.students_present: list = []

        # Hours and analytics.
        self.school_hours = tuple(list(range(8, 11)) + list(range(14, 17)))  # 6 hours: 08-10 and 14-16
        self.hours_open: int = 0
        self.hours_closed_flood: int = 0
        self.student_hours_lost: int = 0
        self.total_attendance_hours: int = 0

        # Grant bookkeeping.
        self.total_grants_received = 0.0
        self.last_grant_amount = 0.0
        self.last_grant_hour = None

        # Open/close transition tracker.
        self._was_open_last_step: bool = False

        # Cleanup and mold bookkeeping (parallels Business agent behavior)
        self._cleanup_hours_left: int = 0
        self._repair_budget_remaining: float = 0.0
        self.hours_closed_cleanup: int = 0
        self.repair_cost_accum: float = 0.0

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

        # Cache a stable interior point for repeated depth queries.
        try:
            self._rp = geometry.representative_point()
        except Exception:
            self._rp = None

    # Helpers used by assignment utilities.
    def enroll(self, person):
        if person not in self.students:
            self.students.append(person)
            person.schoolplace = self

    def withdraw(self, person):
        if person in self.students:
            self.students.remove(person)
            if getattr(person, "schoolplace", None) is self:
                person.schoolplace = None

    def _emit(self, name: str, **payload):
        coll = getattr(self.model, "collect", None)
        if coll and hasattr(coll, "emit_event"):
            coll.emit_event(name, {"school": self.name, **payload})

    def is_open_now(self) -> bool:
        """Open only during scheduled hours and when not flooded."""
        if self.flooded:
            return False
        hour = self.model.hours % 24
        return hour in self.school_hours

    def step(self):
        # Update flood state from local depth.
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

        prev_flooded = self.flooded
        mult = float(self.model.school_flood_thresh_mult)
        thresh = max(0.05, (self.resilience / 10.0) * mult)

        if self.flooded:
            if depth < self._flood_off_margin * thresh:
                self.flooded = False
                self.time_flooded = 0
            else:
                self.time_flooded += 1
        else:
            if depth > self._flood_on_margin * thresh:
                self.flooded = True
                self.time_flooded = self.time_flooded + 1
            else:
                self.time_flooded = 0

        if self.flooded != prev_flooded:
            if self.flooded:
                self.ever_flooded = True
            self._emit("school_flood_state", flooded=self.flooded, depth=self.last_depth, resilience=self.resilience)

        # When flood recedes, schedule cleanup and potential mold onset like businesses.
        if self.model.enable_mold:
            if prev_flooded and (not self.flooded):
                # Entered cleanup phase
                # Cleanup time depends on peak depth and resilience; approximate using same formula as Business.
                cleanup_h = (
                    float(self.model.structure_cleanup_base_hours)
                    + getattr(self, "_peak_depth", self.last_depth) * float(self.model.structure_cleanup_depth_hours)
                    + max(0.0, (25.0 - self.resilience) / float(self.model.structure_cleanup_resilience_divisor))
                )
                self._cleanup_hours_left = int(min(self.model.structure_cleanup_max_hours, max(1, int(cleanup_h or 1))))

                # School-specific repair budget (gov grants may top up later)
                intensity = max(0.0, min(1.0, random.random()))
                repair_scale = (
                    1.0 + float(self.model.structure_repair_intensity_scale) * intensity
                ) * random.uniform(
                    float(self.model.structure_repair_variation_min),
                    float(self.model.structure_repair_variation_max),
                )
                repair_mult = max(0.0, float(self.model.school_repair_cost_multiplier))
                repair_cost = max(
                    0.0,
                    (
                        float(self.model.structure_repair_base_cost)
                        + float(self.model.structure_repair_depth_cost) * getattr(self, "_peak_depth", self.last_depth)
                    ) * repair_scale * repair_mult,
                )
                self._repair_budget_remaining += repair_cost
                self._emit("school_repair_cost_budget", amount=repair_cost, intensity=intensity, peak_depth=getattr(self, "_peak_depth", self.last_depth))

                # Mold susceptibility decision occurs after flood clears across area
                self._pending_mold_start = True
                self._flood_clear_hour = None
                self._mold_susceptible = True

        # Mold lifecycle and damp dynamics (copy of business logic simplified)
        if self.model.enable_mold:
            if self._pending_mold_start:
                if not self.flooded:
                    if self._flood_clear_hour is None:
                        self._flood_clear_hour = int(self.model.hours)
                    elif int(self.model.hours) - int(self._flood_clear_hour) >= 24:
                        self._pending_mold_start = False
                        if self._mold_susceptible:
                            if getattr(self, "time_flooded", 0) > 0 or getattr(self, "ever_flooded", False):
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
                try:
                    self.damp_level *= 0.5 ** (1.0 / eff_hl)
                except Exception:
                    self.damp_level = max(0.0, float(self.damp_level or 0.0))
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

        # Attendance bookkeeping during school hours.
        self.students_present = []  # reset each hour
        hour_of_day = self.model.hours % 24
        in_session = hour_of_day in self.school_hours

        if in_session and not self.flooded:
            # Use covers when available so boundary points count as inside.
            covers = getattr(self.geometry, "covers", None)
            for s in self.students:
                try:
                    pt = getattr(s, "geometry", None)
                    if pt is None: 
                        continue
                    inside = covers(pt) if callable(covers) else self.geometry.contains(pt)
                    if inside:
                        self.students_present.append(s)
                except Exception:
                    pass

            # Apply mold-related attendance penalty if applicable.
            self.hours_open += 1
            present_count = len(self.students_present)
            if self.model.enable_mold and self.mold_index > 0.0:
                mold_rate = max(0.0, float(self.model.school_mold_attendance_penalty_rate))
                lost_frac = min(1.0, mold_rate * self.mold_index)
                lost = int(round(present_count * lost_frac))
                present_count = max(0, present_count - lost)
                if lost > 0:
                    self._emit("school_mold_ops_penalty", lost=lost, mold_index=self.mold_index)

            self.total_attendance_hours += present_count
            self._emit("school_attendance",
                       present=present_count,
                       enrolled=len(self.students),
                       depth=self.last_depth,
                       mold_index=self.mold_index)
        elif in_session and self.flooded:
            # Closed due to flood; count lost student-hours.
            self.hours_closed_flood += 1
            lost = len(self.students)
            self.student_hours_lost += lost
            self._emit("school_closed_flood", enrolled=len(self.students), depth=self.last_depth)

        # Cleanup countdown (if applicable)
        if (not self.flooded) and (self._cleanup_hours_left > 0):
            # Spend repair budget gradually during cleanup to avoid one-hour expense spikes.
            if self._repair_budget_remaining > 0.0:
                hours_left = max(1, int(self._cleanup_hours_left))
                base_hourly = self._repair_budget_remaining / hours_left
                hourly = min(self._repair_budget_remaining, max(0.0, base_hourly * random.uniform(0.80, 1.20)))
                if hourly > 0.0:
                    # Schools don't have private wealth; record repair expense and emit for aggregators.
                    self.repair_cost_accum += hourly
                    self._repair_budget_remaining -= hourly
                    self._emit("school_repair_cost", amount=hourly, remaining=self._repair_budget_remaining)
            self._cleanup_hours_left -= 1
            self.hours_closed_cleanup += 1
            if self._cleanup_hours_left <= 0:
                if self._repair_budget_remaining > 0.0:
                    leftover = float(self._repair_budget_remaining)
                    self.repair_cost_accum += leftover
                    self._emit("school_repair_cost", amount=leftover, remaining=0.0)
                    self._repair_budget_remaining = 0.0
                self._emit("school_reopened")

        # Open/close transition event.
        open_now = (in_session and not self.flooded)
        if open_now != self._was_open_last_step:
            self._emit("school_open" if open_now else "school_closed",
                       reason=("flood" if in_session and self.flooded else "off_hours" if not in_session else "normal"),
                       depth=self.last_depth)
        self._was_open_last_step = open_now
