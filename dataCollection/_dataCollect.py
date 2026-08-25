# dataCollection/_dataCollect.py
from __future__ import annotations
import pandas as pd
from pathlib import Path
import numpy as np, json
import types

# ---- Mesa DataCollector shim (percent-first, paper-ready) ------------

def data_collection(model):
    try:
        from mesa.datacollection import DataCollector
    except Exception:
        class _NoopDC:
            def collect(self, m=None): pass
            def get_model_vars_dataframe(self):
                return pd.DataFrame()
        model.datacollector = _NoopDC()
        return

    # ---- helpers
    def people(m):   return m.people
    def space(m):    return m.space
    def bizs(m):     return space(m).businesses
    def houses(m):   return space(m).houses
    def schools(m):  return space(m).schools
    def sh(m):       return getattr(m, "shelter", None)
    def hc(m):       return getattr(m, "healthcare", None)
    def shs(m):
        services = list(getattr(m, "shelters", []) or [])
        if not services and sh(m) is not None:
            services = [sh(m)]
        return services
    def hcs(m):
        services = list(getattr(m, "healthcares", []) or [])
        if not services and hc(m) is not None:
            services = [hc(m)]
        return services
    def gov(m):      return m.government

    def shelter_capacity(m):
        return sum(max(0, int(getattr(s, "capacity_limit", 0) or 0)) for s in shs(m))

    def shelter_load(m):
        return sum(len(getattr(s, "sheltered_agents", []) or []) for s in shs(m))

    def shelter_pending(m):
        return sum(len(getattr(s, "_pending_rescues", {}) or {}) for s in shs(m))

    def healthcare_capacity(m):
        return sum(max(0, int(getattr(h, "capacity_limit", 0) or 0)) for h in hcs(m))

    def healthcare_load(m):
        return sum(len(getattr(h, "hospitalized_agents", []) or []) for h in hcs(m))

    def healthcare_pending(m):
        return sum(len(getattr(h, "_pending_admissions", {}) or {}) for h in hcs(m))

    def service_at(services, index):
        return services[index] if index < len(services) else None

    def service_load_pct(services, index, load_attr):
        service = service_at(services, index)
        if service is None:
            return 0.0
        capacity = max(1, int(getattr(service, "capacity_limit", 0) or 0))
        load = len(getattr(service, load_attr, []) or [])
        return pct(load, capacity)

    def service_backlog_pct(services, index, load_attr, pending_attr, now_h):
        service = service_at(services, index)
        if service is None:
            return 0.0
        capacity = max(1, int(getattr(service, "capacity_limit", 0) or 0))
        return pct(_service_backlog([service], load_attr, pending_attr, now_h), capacity)

    def count_flag(flag):
        return lambda m: sum(1 for p in people(m) if getattr(p, flag, False))

    def mean_attr(attr):
        return lambda m: (
            sum(float(getattr(p, attr, 0.0) or 0.0) for p in people(m)) / max(1, len(people(m)))
        ) if people(m) else 0.0

    def safe_div(n, d):
        try:
            d = float(d)
            return float(n) / d if d else 0.0
        except Exception:
            return 0.0

    def pct(n, d):
        return 100.0 * safe_div(n, d)

    def _dc_state(m):
        st = getattr(m, "_dc_state", None)
        if st is None:
            st = {}
            setattr(m, "_dc_state", st)
        return st

    def delta_reporter(key, getter):
        def _report(m):
            st = _dc_state(m)
            cur = float(getter(m) or 0.0)
            prev = float(st.get(key, cur))
            st[key] = cur
            return cur - prev
        return _report

    def baseline_index_reporter(key, getter):
        def _report(m):
            st = _dc_state(m)
            cur = float(getter(m) or 0.0)
            base_key = f"base::{key}"
            if base_key not in st:
                st[base_key] = max(1e-9, cur)
                return 100.0
            base = float(st.get(base_key, 1e-9))
            return 100.0 * safe_div(cur, base)
        return _report

    # precompute commonly used denominators each step
    def pop(m):       return len(people(m))
    def n_biz(m):     return len(bizs(m))
    def n_house(m):   return len(houses(m))
    def n_school(m):  return len(schools(m))

    def any_ill(p):
        return bool(
            getattr(p, "injured", False) or
            getattr(p, "ill_respiratory", False) or
            getattr(p, "ill_vector", False) or
            getattr(p, "symp_mold", False) or
            getattr(p, "symp_vector", False) or
            getattr(p, "inf_state", "S") == "I"
        )

    def any_disease(p):
        return bool(
            getattr(p, "ill_respiratory", False) or
            getattr(p, "ill_vector", False) or
            getattr(p, "symp_mold", False) or
            getattr(p, "symp_vector", False) or
            getattr(p, "inf_state", "S") == "I"
        )

    def subgroup_disease_pct(m, predicate):
        group = [p for p in people(m) if predicate(p)]
        if not group:
            return 0.0
        return 100.0 * (sum(1 for p in group if any_ill(p)) / max(1, len(group)))

    def action_match(p, actions):
        act = str(getattr(p, "last_action", "") or "")
        actions = set(actions)
        if act in actions:
            return True
        if "Evacuate" in actions and bool(getattr(p, "evacuated", False)):
            return True
        return False

    def action_pct(m, actions):
        group = people(m)
        if not group:
            return 0.0
        return 100.0 * (sum(1 for p in group if action_match(p, actions)) / max(1, len(group)))

    def subgroup_action_pct(m, predicate, actions):
        group = [p for p in people(m) if predicate(p)]
        if not group:
            return 0.0
        return 100.0 * (sum(1 for p in group if action_match(p, actions)) / max(1, len(group)))
    
    def mod_enabled(m, name):
        # name in {"infectious","vectorborne","mold"}
        key = f"enable_{'vectorborne' if name=='vectorborne' else name}"
        if name == "vectorborne":
            return bool(getattr(m, key, getattr(m, "enable_stagnant", False)))
        return bool(getattr(m, key, False))

    def module_incidence(m, name):
        # reads .incidence on the disease module if present, else 0
        d = getattr(m, "disease", None)
        mods = getattr(d, "modules", []) if d else []
        for mm in mods:
            if getattr(mm, "name", "") == name:
                return int(getattr(mm, "incidence", 0) or 0)
        return 0

    def _in_entity(p, entity):
        if not entity or not hasattr(entity, "geometry"):
            return False
        try:
            return bool(entity.geometry.contains(getattr(p, "geometry", None)))
        except Exception:
            return False

    def _in_hospital(m, p):
        return any(p in (getattr(h, "hospitalized_agents", []) or []) for h in hcs(m))

    def _is_mold_case(p):
        return bool(getattr(p, "symp_mold", False) or getattr(p, "ill_respiratory", False))

    def _is_vector_case(p):
        return bool(getattr(p, "symp_vector", False) or getattr(p, "ill_vector", False))

    def _is_infectious_case(p):
        return str(getattr(p, "inf_state", "S") or "S") == "I"

    def _is_flood_case(p):
        return bool(getattr(p, "injured", False))

    def _is_flood_only_case(p):
        return bool(_is_flood_case(p) and not (_is_mold_case(p) or _is_vector_case(p) or _is_infectious_case(p)))

    def _is_mold_only_case(p):
        return bool(_is_mold_case(p) and not (_is_flood_case(p) or _is_vector_case(p) or _is_infectious_case(p)))

    def _is_vector_only_case(p):
        return bool(_is_vector_case(p) and not (_is_flood_case(p) or _is_mold_case(p) or _is_infectious_case(p)))

    def _is_infectious_only_case(p):
        return bool(_is_infectious_case(p) and not (_is_flood_case(p) or _is_mold_case(p) or _is_vector_case(p)))

    def _is_compound_case(p):
        tags = 0
        tags += int(_is_flood_case(p))
        tags += int(_is_mold_case(p))
        tags += int(_is_vector_case(p))
        tags += int(_is_infectious_case(p))
        return tags >= 2

    def _hc_hospitalized_by(m, predicate):
        return sum(
            1
            for h in hcs(m)
            for p in (getattr(h, "hospitalized_agents", []) or [])
            if predicate(p)
        )

    def _hc_pending_by(m, predicate):
        return sum(
            1
            for h in hcs(m)
            for p in (getattr(h, "_pending_admissions", {}) or {}).keys()
            if predicate(p)
        )

    def _due_pending_count(pending_map, now_h, predicate=None):
        pending = (pending_map or {})
        now_i = int(now_h or 0)
        count = 0
        for p, eta in pending.items():
            try:
                eta_i = int(eta)
            except Exception:
                continue
            if eta_i > now_i:
                continue
            if predicate is not None and not predicate(p):
                continue
            count += 1
        return count

    def _shelter_due_pending(m):
        return sum(
            _due_pending_count(
                getattr(s, "_pending_rescues", {}) or {},
                getattr(m, "hours", 0),
            )
            for s in shs(m)
        )

    def _hc_due_pending(m, predicate=None):
        return sum(
            _due_pending_count(
                getattr(h, "_pending_admissions", {}) or {},
                getattr(m, "hours", 0),
                predicate=predicate,
            )
            for h in hcs(m)
        )

    def _service_backlog(services, load_attr, pending_attr, now_h):
        """Count overdue requests at each facility that has no open capacity."""
        backlog = 0
        for service in services:
            capacity = max(0, int(getattr(service, "capacity_limit", 0) or 0))
            load = len(getattr(service, load_attr, []) or [])
            if capacity > 0 and load >= capacity:
                backlog += _due_pending_count(
                    getattr(service, pending_attr, {}) or {},
                    now_h,
                )
        return backlog


    def _person_flag_cached(m, p, flag_name, compute):
        if m is None or p is None:
            return bool(compute())
        st = _dc_state(m)
        now_h = int(getattr(m, "hours", 0) or 0)
        if st.get("person_flag_cache_hour") != now_h:
            st["person_flag_cache_hour"] = now_h
            st["person_flag_cache"] = {}
        cache = st.setdefault("person_flag_cache", {})
        pid = str(getattr(p, "name", id(p)))
        cache_key = (pid, flag_name)
        if cache_key not in cache:
            cache[cache_key] = bool(compute())
        return bool(cache[cache_key])


    def _at_work(p, m=None):
        m = m or getattr(p, "model", None)
        return _person_flag_cached(
            m,
            p,
            "at_work",
            lambda: bool(getattr(p, "employed", False) and _in_entity(p, getattr(p, "workplace", None))),
        )

    def _at_school(p, m=None):
        m = m or getattr(p, "model", None)
        return _person_flag_cached(
            m,
            p,
            "at_school",
            lambda: bool(getattr(p, "student", False) and _in_entity(p, getattr(p, "schoolplace", None))),
        )

    def _at_home(p, m=None):
        m = m or getattr(p, "model", None)
        return _person_flag_cached(
            m,
            p,
            "at_home",
            lambda: _in_entity(p, getattr(p, "household", None)),
        )

    def _in_work_session(m):
        h = int(getattr(m, "hours", 0)) % 24
        return (8 <= h < 12) or (14 <= h < 18)

    def _in_school_session(m):
        h = int(getattr(m, "hours", 0)) % 24
        return (8 <= h < 11) or (14 <= h < 17)

    def _near_any_business(p, m, radius_m=None):
        businesses = bizs(m)
        pt = getattr(p, "geometry", None)
        if pt is None or not businesses:
            return False

        if radius_m is None:
            radius_m = getattr(m, "shopping_vicinity_m", 25.0)
        try:
            radius_m = max(0.0, float(radius_m or 0.0))
        except Exception:
            radius_m = 25.0

        for biz in businesses:
            geom = getattr(biz, "geometry", None)
            if geom is None:
                continue
            try:
                if geom.intersects(pt):
                    return True
                if radius_m > 0.0 and geom.distance(pt) <= radius_m:
                    return True
            except Exception:
                continue
        return False

    def _at_shopping(p, m):
        # At or near a business, but not while the agent is working, schooling, or at home.
        return _person_flag_cached(
            m,
            p,
            "at_shopping",
            lambda: (
                False if not getattr(p, "alive", True)
                else False if getattr(p, "stranded", False) or getattr(p, "injured", False)
                else False if getattr(p, "evacuated", False)
                else False if getattr(p, "in_shelter", False) or _in_hospital(m, p)
                else False if _at_work(p, m) or _at_school(p, m) or _at_home(p, m)
                else _near_any_business(p, m)
            ),
        )

    def _at_leisure(p, m):
        # Leisure is the alive, uninjured, unsheltered remainder after work/school/home/business contact.
        return _person_flag_cached(
            m,
            p,
            "at_leisure",
            lambda: (
                False if not getattr(p, "alive", True)
                else False if getattr(p, "stranded", False) or getattr(p, "injured", False)
                else False if getattr(p, "evacuated", False)
                else False if getattr(p, "in_shelter", False) or _in_hospital(m, p)
                else False if _at_work(p, m) or _at_school(p, m) or _at_home(p, m)
                else not _near_any_business(p, m)
            ),
        )

    def _person_state(m, p, hospitalized_set):
        if not bool(getattr(p, "alive", True)):
            return "dead"
        if p in hospitalized_set:
            return "healthcare"
        if bool(getattr(p, "in_shelter", False)):
            return "shelter"
        if bool(getattr(p, "stranded", False)):
            return "stranded"
        if bool(getattr(p, "evacuated", False)):
            return "evacuated"
        return "normal"

    def _exclusive_state_counts(m):
        counts = {
            "dead": 0,
            "healthcare": 0,
            "shelter": 0,
            "stranded": 0,
            "evacuated": 0,
            "normal": 0,
        }
        hospitalized = {
            p
            for h in hcs(m)
            for p in (getattr(h, "hospitalized_agents", []) or [])
        }
        for p in people(m):
            counts[_person_state(m, p, hospitalized)] += 1
        return counts

    def _exclusive_state_counts_cached(m):
        st = _dc_state(m)
        now_h = int(getattr(m, "hours", 0) or 0)
        if st.get("exclusive_state_counts_hour") != now_h:
            st["exclusive_state_counts_hour"] = now_h
            st["exclusive_state_counts"] = _exclusive_state_counts(m)
        return st.get("exclusive_state_counts", {
            "dead": 0,
            "healthcare": 0,
            "shelter": 0,
            "stranded": 0,
            "evacuated": 0,
            "normal": 0,
        })

    def _exclusive_state_sum_pct(m):
        counts = _exclusive_state_counts_cached(m)
        total = int(sum(int(v) for v in counts.values()))
        return pct(total, pop(m))

    def _activity_counts_cached(m):
        st = _dc_state(m)
        now_h = int(getattr(m, "hours", 0) or 0)
        if st.get("activity_counts_hour") == now_h:
            return st.get("activity_counts", {})

        hospitalized = {
            p
            for h in hcs(m)
            for p in (getattr(h, "hospitalized_agents", []) or [])
        }
        counts = {
            "workforce_total": 0,
            "work_attending": 0,
            "student_total": 0,
            "school_present": 0,
            "leisure": 0,
            "shopping": 0,
            "normal_activity": 0,
            "staffed_workplaces": set(),
        }

        for p in people(m):
            if not getattr(p, "alive", True):
                continue

            employed = bool(getattr(p, "employed", False))
            student = bool(getattr(p, "student", False))
            at_work = _at_work(p, m)
            at_school = _at_school(p, m)
            at_home = _at_home(p, m)
            at_shopping = _at_shopping(p, m)
            at_leisure = _at_leisure(p, m)

            if employed:
                counts["workforce_total"] += 1
                if at_work:
                    counts["work_attending"] += 1
                    workplace = getattr(p, "workplace", None)
                    if workplace is not None:
                        counts["staffed_workplaces"].add(workplace)

            if student:
                counts["student_total"] += 1
                if at_school:
                    counts["school_present"] += 1

            if at_leisure:
                counts["leisure"] += 1
            if at_shopping:
                counts["shopping"] += 1

            if (
                not getattr(p, "evacuated", False)
                and not getattr(p, "stranded", False)
                and p not in hospitalized
                and not bool(getattr(p, "in_shelter", False))
                and not bool(getattr(p, "injured", False))
                and not bool(getattr(p, "inf_resting", False))
                and str(getattr(p, "inf_state", "S") or "S") != "I"
                and float(getattr(p, "activity_capacity", lambda: 1.0)() or 1.0) >= 0.75
                and (at_work or at_school or at_leisure or at_shopping or at_home)
            ):
                counts["normal_activity"] += 1

        st["activity_counts_hour"] = now_h
        st["activity_counts"] = counts
        return counts

    def _exclusive_overlap_conflict_cnt(m):
        conflicts = 0
        hospitalized = {
            p
            for h in hcs(m)
            for p in (getattr(h, "hospitalized_agents", []) or [])
        }
        for p in people(m):
            alive = bool(getattr(p, "alive", True))
            flags = 0
            flags += int(p in hospitalized)
            flags += int(bool(getattr(p, "in_shelter", False)))
            flags += int(bool(getattr(p, "stranded", False)))
            flags += int(bool(getattr(p, "evacuated", False)))
            if flags > 1:
                conflicts += 1
            if (not alive) and flags > 0:
                conflicts += 1
        return conflicts

    def _income_baseline(m, p):
        st = _dc_state(m)
        key = "income_baseline_by_agent"
        if key not in st:
            st[key] = {}
        by_agent = st[key]
        pid = str(getattr(p, "name", id(p)))
        cur = float(getattr(p, "income", 0.0) or 0.0)
        if pid not in by_agent:
            by_agent[pid] = cur
        return float(by_agent.get(pid, 0.0))

    def _income_ratio(m, p):
        cur = float(getattr(p, "income", 0.0) or 0.0)
        base = _income_baseline(m, p)
        if base <= 1e-9:
            return 1.0 if cur >= 0.0 else 0.0
        return _clip01(cur / base)

    def _clip01(x):
        return max(0.0, min(1.0, float(x)))

    def person_qol(m, p):
        if not getattr(p, "alive", True):
            return 0.0

        in_shelter = bool(getattr(p, "in_shelter", False))
        in_hospital = _in_hospital(m, p)
        stranded = bool(getattr(p, "stranded", False))
        evacuated = bool(getattr(p, "evacuated", False))
        injured = bool(getattr(p, "injured", False))

        at_work = _at_work(p, m)
        at_school = _at_school(p, m)
        at_home = _at_home(p, m)

        if stranded:
            activity_base = 0.0
        elif at_work or at_school or at_home:
            activity_base = 1.0
        elif in_shelter or in_hospital:
            activity_base = 0.35
        else:
            activity_base = 0.75

        activity = activity_base * _clip01(float(getattr(p, "activity_capacity", lambda: 1.0)()))
        health = _clip01(float(getattr(p, "health_capacity", lambda: 1.0)()))

        safety = 1.0
        if in_shelter:
            safety = min(safety, 0.75)
        if in_hospital:
            safety = min(safety, 0.65)
        if stranded:
            safety = 0.0

        if getattr(p, "household", None) and hasattr(p.household, "habitability"):
            housing = _clip01(float(p.household.habitability()))
        else:
            housing = 1.0

        # QoL should react to event pressure (hazard/illness/displacement), not to
        # slow baseline cash drift from routine spending over long horizons.
        phase = str(getattr(m, "disaster_period", "") or "")
        flood_pressure = bool(
            phase in {"pre_flood", "during_flood", "post_flood"}
            or bool(getattr(getattr(p, "household", None), "flooded", False))
            or float(getattr(getattr(p, "household", None), "last_depth", 0.0) or 0.0) > 0.0
        )
        health_pressure = bool(injured or any_ill(p) or in_hospital)
        displacement_pressure = bool(stranded or in_shelter or evacuated)
        debt = max(0.0, float(getattr(p, "healthcare_debt_accum", 0.0) or 0.0))
        debt_ratio = safe_div(debt, max(1e-9, _income_baseline(m, p)))
        debt_pressure = debt_ratio > 0.0
        if flood_pressure or health_pressure or displacement_pressure or debt_pressure:
            finance = _income_ratio(m, p) / (1.0 + debt_ratio)
        else:
            finance = 1.0

        qol = (
            0.35 * activity
            + 0.25 * health
            + 0.20 * safety
            + 0.10 * housing
            + 0.10 * finance
        )
        return _clip01(qol)

    def qol_mean_pct(m, predicate=None):
        group = [p for p in people(m) if getattr(p, "alive", True)]
        if predicate is not None:
            group = [p for p in group if predicate(p)]
        if not group:
            return 0.0
        return 100.0 * safe_div(sum(person_qol(m, p) for p in group), len(group))

    def income_mean(m, predicate=None):
        group = [p for p in people(m) if getattr(p, "alive", True)]
        if predicate is not None:
            group = [p for p in group if predicate(p)]
        if not group:
            return 0.0
        return safe_div(
            sum(float(getattr(p, "income", 0.0) or 0.0) for p in group),
            len(group),
        )


    # ---- DataCollector: prioritized, percent-first metrics ----------
    model.datacollector = DataCollector(
        model_reporters={

            # ---------- time/phase ----------
            "hours": lambda m: m.hours,
            "day":   lambda m: int(m.hours // 24),
            "phase": lambda m: m.disaster_period,
            "event_phase": lambda m: m.event_phase,
            "scenario": lambda m: m.scenario_mode,
            "run_id": lambda m: m.run_id,
            "replication": lambda m: int(m.replication),
            "random_seed": lambda m: int(m.random_seed),
            "flood_enabled": lambda m: int(bool(m.enable_flood)),
            "disease_enabled": lambda m: int(bool(m.enable_disease_system)),
            "infectious_enabled": lambda m: int(bool(m.enable_infectious)),
            "vectorborne_enabled": lambda m: int(bool(m.enable_vectorborne)),
            "mold_enabled": lambda m: int(bool(m.enable_mold)),
            "policy_wash": lambda m: float(m.wash_intensity),
            "policy_distancing": lambda m: float(m.shelter_distancing_intensity),
            "policy_hc_surge": lambda m: float(m.healthcare_surge_factor),
            "policy_repair": lambda m: float(m.repair_subsidy_intensity),
            "policy_risk_comm": lambda m: float(m.risk_communication_intensity),
            "policy_targeted": lambda m: float(m.targeted_protection_intensity),
            "policy_grant_cadence_h": lambda m: float(m.gov_baseline_grant_every_hours),
            "config_male_pct": lambda m: float(m.male_share_pct),
            "config_female_pct": lambda m: float(m.female_share_pct),
            "config_age_0_14_pct": lambda m: float(m.age_0_14_pct),
            "config_age_15_64_pct": lambda m: float(m.age_15_64_pct),
            "config_age_65_100_pct": lambda m: float(m.age_65_100_pct),
            "config_worldview_hierarchist_pct": lambda m: float(m.worldview_hierarchist_pct),
            "config_worldview_egalitarian_pct": lambda m: float(m.worldview_egalitarian_pct),
            "config_worldview_individualist_pct": lambda m: float(m.worldview_individualist_pct),
            "config_worldview_fatalist_pct": lambda m: float(m.worldview_fatalist_pct),

            # ---------- core persons (counts + % of population) ----------
            "pop":            lambda m: pop(m),
            "alive_cnt":      lambda m: pop(m) - _exclusive_state_counts_cached(m)["dead"],
            "injured_cnt":    lambda m: sum(
                                1 for p in people(m)
                                if bool(getattr(p, "injured", False)) or _in_hospital(m, p)
                            ),
            "stranded_cnt":   lambda m: _exclusive_state_counts_cached(m)["stranded"] + _exclusive_state_counts_cached(m)["shelter"],
            "in_shelter_cnt": lambda m: _exclusive_state_counts_cached(m)["shelter"],
            "in_healthcare_cnt": lambda m: _exclusive_state_counts_cached(m)["healthcare"],
            "evacuated_cnt":  lambda m: _exclusive_state_counts_cached(m)["evacuated"],

            "alive_pct":      lambda m: pct(pop(m) - _exclusive_state_counts_cached(m)["dead"], pop(m)),
            "injured_pct":    lambda m: pct(
                                sum(1 for p in people(m) if bool(getattr(p, "injured", False)) or _in_hospital(m, p)),
                                pop(m),
                            ),
            "stranded_pct":   lambda m: pct(_exclusive_state_counts_cached(m)["stranded"] + _exclusive_state_counts_cached(m)["shelter"], pop(m)),
            "in_shelter_pct": lambda m: pct(_exclusive_state_counts_cached(m)["shelter"], pop(m)),
            "in_healthcare_pct": lambda m: pct(_exclusive_state_counts_cached(m)["healthcare"], pop(m)),
            "evacuated_pct":  lambda m: pct(_exclusive_state_counts_cached(m)["evacuated"], pop(m)),
            "dead_cnt":       lambda m: _exclusive_state_counts_cached(m)["dead"],
            "dead_pct":       lambda m: pct(_exclusive_state_counts_cached(m)["dead"], pop(m)),
            "exclusive_state_sum_pct": lambda m: _exclusive_state_sum_pct(m),
            "exclusive_overlap_conflict_cnt": lambda m: _exclusive_overlap_conflict_cnt(m),
            "male_pct":       lambda m: pct(sum(1 for p in people(m) if getattr(p, "gender", "") == "Male"), pop(m)),
            "female_pct":     lambda m: pct(sum(1 for p in people(m) if getattr(p, "gender", "") == "Female"), pop(m)),
            "ethnicity_white_pct":      lambda m: pct(sum(1 for p in people(m) if getattr(p, "ethnicity", "") == "White"), pop(m)),
            "ethnicity_black_pct":      lambda m: pct(sum(1 for p in people(m) if getattr(p, "ethnicity", "") == "Black"), pop(m)),
            "ethnicity_hispanic_pct":   lambda m: pct(sum(1 for p in people(m) if getattr(p, "ethnicity", "") == "Hispanic"), pop(m)),
            "ethnicity_other_pct":      lambda m: pct(sum(1 for p in people(m) if getattr(p, "ethnicity", "") == "Other"), pop(m)),
            "wealth_lower_pct":         lambda m: pct(sum(1 for p in people(m) if getattr(p, "wealth_class", "") == "Lower_Class"), pop(m)),
            "wealth_middle_pct":        lambda m: pct(sum(1 for p in people(m) if getattr(p, "wealth_class", "") == "Middle_Class"), pop(m)),
            "wealth_upper_middle_pct":  lambda m: pct(sum(1 for p in people(m) if getattr(p, "wealth_class", "") == "Upper_Middle_Class"), pop(m)),
            "wealth_upper_pct":         lambda m: pct(sum(1 for p in people(m) if getattr(p, "wealth_class", "") == "Upper_Class"), pop(m)),
            "age_0_14_pct":   lambda m: pct(sum(1 for p in people(m) if 0 <= int(getattr(p, "age", 0) or 0) <= 14), pop(m)),
            "age_15_64_pct":  lambda m: pct(sum(1 for p in people(m) if 15 <= int(getattr(p, "age", 0) or 0) <= 64), pop(m)),
            "age_65_100_pct": lambda m: pct(sum(1 for p in people(m) if int(getattr(p, "age", 0) or 0) >= 65), pop(m)),
            "worldview_hierarchist_pct": lambda m: pct(sum(1 for p in people(m) if getattr(p, "worldview", "") == "hierarchist"), pop(m)),
            "worldview_egalitarian_pct": lambda m: pct(sum(1 for p in people(m) if getattr(p, "worldview", "") == "egalitarian"), pop(m)),
            "worldview_individualist_pct": lambda m: pct(sum(1 for p in people(m) if getattr(p, "worldview", "") == "individualist"), pop(m)),
            "worldview_fatalist_pct": lambda m: pct(sum(1 for p in people(m) if getattr(p, "worldview", "") == "fatalist"), pop(m)),
            
            # ------------- disease prevalence (% of population) -------------
            "inf_prev_pct":    lambda m: (
                0.0 if not mod_enabled(m, "infectious") else
                100.0 * (sum(1 for p in getattr(m,"people",[]) if getattr(p,"inf_state","S")=="I") / max(1,len(getattr(m,"people",[]))))
            ),
            "vector_symp_pct": lambda m: (
                0.0 if not mod_enabled(m, "vectorborne") else
                100.0 * (sum(1 for p in getattr(m,"people",[]) if getattr(p,"ill_vector",False) or getattr(p,"symp_vector",False)) / max(1,len(getattr(m,"people",[]))))
            ),
            "mold_symp_pct":   lambda m: (
                0.0 if not mod_enabled(m, "mold") else
                100.0 * (sum(1 for p in getattr(m,"people",[]) if getattr(p,"ill_respiratory",False) or getattr(p,"symp_mold",False)) / max(1,len(getattr(m,"people",[]))))
            ),
            "compound_burden_pct": lambda m: (
                0.0 if not bool(getattr(m, "enable_disease_system", False)) else
                100.0 * (sum(1 for p in getattr(m, "people", []) if any_disease(p)) / max(1, len(getattr(m, "people", []))))
            ),
            
            # ------------- hourly incidence & damp diagnostics -------------
            "vector_incidence_hr": lambda m: module_incidence(m, "vectorborne") if mod_enabled(m, "vectorborne") else np.nan,
            "mold_incidence_hr":   lambda m: module_incidence(m, "mold")        if mod_enabled(m, "mold")        else np.nan,
            
            "house_damp_active_pct": lambda m: 100.0 * (
                sum(1 for h in (getattr(getattr(m,"space",None),"houses",[]) or []) if getattr(h,"damp_active",False))
                / max(1,len(getattr(getattr(m,"space",None),"houses",[]) or []))
            ),

            # ------------- exposures & housing burdens -------------
            "near_vectorborne_pct":  lambda m: 100.0 * (
                sum(1 for p in getattr(m,"people",[])
                    if getattr(getattr(m,"space",None),"get_stagnant_hazard_at_position", lambda *_:0.0)(getattr(p,"geometry",None)) > 0.05
                ) / max(1,len(getattr(m,"people",[])))
            ),

            "house_mold_mean":    lambda m: (
                float(np.mean([float(getattr(h,"mold_index",0.0) or 0.0) for h in (getattr(getattr(m,"space",None),"houses",[]) or [])])) 
                if (getattr(getattr(m,"space",None),"houses",[]) or []) else 0.0
            ),
            "house_molded_pct":   lambda m: 100.0 * (
                sum(1 for h in (getattr(getattr(m, "space", None), "houses", []) or []) if float(getattr(h, "mold_index", 0.0) or 0.0) > 0.05)
                / max(1, len(getattr(getattr(m, "space", None), "houses", []) or []))
            ),
            "house_damp_geH_pct": lambda m: 100.0 * (
                sum(1 for h in (getattr(getattr(m,"space",None),"houses",[]) or [])
                    if getattr(h,"damp_active",False) and float(getattr(h,"damp_hours",0.0) or 0.0) >= float(getattr(m,"damp_metric_hours",48.0))
                ) / max(1,len(getattr(getattr(m,"space",None),"houses",[]) or []))
            ),
            "repair_cost_total":  lambda m: float(sum(float(getattr(h,"repair_cost_accum",0.0) or 0.0) for h in (getattr(getattr(m,"space",None),"houses",[]) or []))),
            "house_repair_expense_total": lambda m: float(sum(float(getattr(h, "repair_cost_accum", 0.0) or 0.0) for h in houses(m))),
            "business_repair_expense_total": lambda m: float(sum(float(getattr(b, "repair_cost_accum", 0.0) or 0.0) for b in bizs(m))),
            "evacuation_expense_total": lambda m: float(sum(float(getattr(p, "evacuation_expense_accum", 0.0) or 0.0) for p in people(m))),
            "healthcare_expense_flood_total": lambda m: float(sum(float(getattr(p, "healthcare_expense_flood_accum", 0.0) or 0.0) for p in people(m))),
            "healthcare_expense_mold_total": lambda m: float(sum(float(getattr(p, "healthcare_expense_mold_accum", 0.0) or 0.0) for p in people(m))),
            "healthcare_expense_vectorborne_total": lambda m: float(sum(float(getattr(p, "healthcare_expense_vectorborne_accum", 0.0) or 0.0) for p in people(m))),
            "healthcare_expense_infectious_total": lambda m: float(sum(float(getattr(p, "healthcare_expense_infectious_accum", 0.0) or 0.0) for p in people(m))),
            "healthcare_debt_total": lambda m: float(sum(float(getattr(p, "healthcare_debt_accum", 0.0) or 0.0) for p in people(m))),
            "healthcare_debt_flood_total": lambda m: float(sum(float(getattr(p, "healthcare_debt_flood_accum", 0.0) or 0.0) for p in people(m))),
            "healthcare_debt_mold_total": lambda m: float(sum(float(getattr(p, "healthcare_debt_mold_accum", 0.0) or 0.0) for p in people(m))),
            "healthcare_debt_vectorborne_total": lambda m: float(sum(float(getattr(p, "healthcare_debt_vectorborne_accum", 0.0) or 0.0) for p in people(m))),
            "healthcare_debt_infectious_total": lambda m: float(sum(float(getattr(p, "healthcare_debt_infectious_accum", 0.0) or 0.0) for p in people(m))),
            "affected_evacuated_pct": lambda m: pct(sum(1 for p in people(m) if bool(getattr(p, "ever_affected_evacuated", False))), pop(m)),
            "affected_flood_pct": lambda m: pct(sum(1 for p in people(m) if bool(getattr(p, "ever_affected_flood", False))), pop(m)),
            "affected_mold_pct": lambda m: pct(sum(1 for p in people(m) if bool(getattr(p, "ever_affected_mold", False))), pop(m)),
            "affected_vectorborne_pct": lambda m: pct(sum(1 for p in people(m) if bool(getattr(p, "ever_affected_vectorborne", False))), pop(m)),
            "affected_infectious_pct": lambda m: pct(sum(1 for p in people(m) if bool(getattr(p, "ever_affected_infectious", False))), pop(m)),
            "affected_hc_flood_pct": lambda m: pct(sum(1 for p in people(m) if bool(getattr(p, "ever_hc_flood", False))), pop(m)),
            "affected_hc_mold_pct": lambda m: pct(sum(1 for p in people(m) if bool(getattr(p, "ever_hc_mold", False))), pop(m)),
            "affected_hc_vectorborne_pct": lambda m: pct(sum(1 for p in people(m) if bool(getattr(p, "ever_hc_vectorborne", False))), pop(m)),
            "affected_hc_infectious_pct": lambda m: pct(sum(1 for p in people(m) if bool(getattr(p, "ever_hc_infectious", False))), pop(m)),
            "affected_hc_compound_pct": lambda m: pct(sum(1 for p in people(m) if bool(getattr(p, "ever_hc_compound", False))), pop(m)),
            "affected_stranded_unique_pct": lambda m: pct(sum(1 for p in people(m) if bool(getattr(p, "ever_affected_stranded", False))), pop(m)),
            "affected_sheltered_unique_pct": lambda m: pct(sum(1 for p in people(m) if bool(getattr(p, "ever_affected_sheltered", False))), pop(m)),
            "affected_injured_unique_pct": lambda m: pct(sum(1 for p in people(m) if bool(getattr(p, "ever_affected_injured", False))), pop(m)),
            "affected_healthcare_unique_pct": lambda m: pct(sum(1 for p in people(m) if bool(getattr(p, "ever_affected_hospitalized", False))), pop(m)),
            "sick_hours_total_sum": lambda m: float(sum(float(getattr(p, "sick_hours_total", 0.0) or 0.0) for p in getattr(m, "people", []))),
            "sick_hours_respiratory_sum": lambda m: float(sum(float(getattr(p, "sick_hours_respiratory", 0.0) or 0.0) for p in getattr(m, "people", []))),
            "sick_hours_vector_sum": lambda m: float(sum(float(getattr(p, "sick_hours_vector", 0.0) or 0.0) for p in getattr(m, "people", []))),

            # ---------- PMT/TPB means ----------
            "mean_threat":  mean_attr("last_threat"),
            "mean_coping":  mean_attr("last_coping"),
            "mean_self_efficacy": mean_attr("self_efficacy"),
            "mean_response_efficacy": mean_attr("response_efficacy"),
            "mean_authority_trust": mean_attr("trust_in_authorities"),

            # ---------- decision outputs and behavior-disease links ----------
            "decision_evac_pct": lambda m: action_pct(m, {"Evacuate"}),
            "decision_prepare_pct": lambda m: action_pct(m, {"PrepareHome"}),
            "decision_delay_return_pct": lambda m: action_pct(m, {"DelayReturn"}),
            "decision_shelter_in_place_pct": lambda m: action_pct(m, {"ShelterInPlace"}),
            "disease_among_evacuated_pct": lambda m: subgroup_disease_pct(m, lambda p: bool(getattr(p, "evacuated", False) or getattr(p, "last_action", "") == "Evacuate")),
            "disease_among_sheltered_pct": lambda m: subgroup_disease_pct(m, lambda p: bool(getattr(p, "in_shelter", False))),
            "disease_after_delay_return_pct": lambda m: subgroup_disease_pct(m, lambda p: getattr(p, "last_action", "") == "DelayReturn"),
            "evac_high_trust_pct": lambda m: subgroup_action_pct(m, lambda p: float(getattr(p, "trust_in_authorities", 0.0) or 0.0) >= 0.5, {"Evacuate"}),
            "evac_low_trust_pct": lambda m: subgroup_action_pct(m, lambda p: float(getattr(p, "trust_in_authorities", 0.0) or 0.0) < 0.5, {"Evacuate"}),
            "evac_fatalist_pct": lambda m: subgroup_action_pct(m, lambda p: getattr(p, "worldview", "") == "fatalist", {"Evacuate"}),
            "evac_individualist_pct": lambda m: subgroup_action_pct(m, lambda p: getattr(p, "worldview", "") == "individualist", {"Evacuate"}),

            # ---------- service capacity & stress (levels + %) ----------
            "shelter_cap":         lambda m: shelter_capacity(m),
            "shelter_load":        lambda m: shelter_load(m),
            "shelter_util_pct":    lambda m: pct(shelter_load(m), max(1, shelter_capacity(m))),
            "shelter_backlog_pct": lambda m: pct(
                                        _service_backlog(
                                            shs(m),
                                            "sheltered_agents",
                                            "_pending_rescues",
                                            getattr(m, "hours", 0),
                                        ),
                                        max(1, shelter_capacity(m))
                                    ),
            "shelter_pending_cnt": lambda m: shelter_pending(m),
            "shelter_1_util_pct": lambda m: service_load_pct(shs(m), 0, "sheltered_agents"),
            "shelter_1_backlog_pct": lambda m: service_backlog_pct(shs(m), 0, "sheltered_agents", "_pending_rescues", getattr(m, "hours", 0)),
            "shelter_2_util_pct": lambda m: service_load_pct(shs(m), 1, "sheltered_agents"),
            "shelter_2_backlog_pct": lambda m: service_backlog_pct(shs(m), 1, "sheltered_agents", "_pending_rescues", getattr(m, "hours", 0)),
            "shelter_wealth":      lambda m: sum(float(getattr(s, "wealth", 0.0) or 0.0) for s in shs(m)),
            "shelter_grants_total":lambda m: sum(float(getattr(s, "total_grants_received", 0.0) or 0.0) for s in shs(m)),
            "shelter_procurement_spend_total": lambda m: sum(float(getattr(s, "procurement_spend_total", 0.0) or 0.0) for s in shs(m)),
            "shelter_operating_cost_total": lambda m: sum(float(getattr(s, "operating_cost_total", 0.0) or 0.0) for s in shs(m)),
            "shelter_wealth_per_cap": lambda m: safe_div(sum(float(getattr(s, "wealth", 0.0) or 0.0) for s in shs(m)), max(1, shelter_capacity(m))),

            "hc_cap":              lambda m: healthcare_capacity(m),
            "hc_load":             lambda m: healthcare_load(m),
            "hc_util_pct":         lambda m: pct(healthcare_load(m), max(1, healthcare_capacity(m))),
            "hc_peak_load":        lambda m: sum(int(getattr(h, "peak_load", 0) or 0) for h in hcs(m)),
            "hc_peak_util_pct":    lambda m: pct(
                                        sum(int(getattr(h, "peak_load", 0) or 0) for h in hcs(m)),
                                        max(1, healthcare_capacity(m)),
                                    ),
            "hc_backlog_pct":      lambda m: pct(
                                        _service_backlog(
                                            hcs(m),
                                            "hospitalized_agents",
                                            "_pending_admissions",
                                            getattr(m, "hours", 0),
                                        ),
                                        max(1, healthcare_capacity(m))
                                    ),
            "hc_pending_cnt":      lambda m: healthcare_pending(m),
            "hc_1_util_pct":      lambda m: service_load_pct(hcs(m), 0, "hospitalized_agents"),
            "hc_1_backlog_pct":   lambda m: service_backlog_pct(hcs(m), 0, "hospitalized_agents", "_pending_admissions", getattr(m, "hours", 0)),
            "hc_2_util_pct":      lambda m: service_load_pct(hcs(m), 1, "hospitalized_agents"),
            "hc_2_backlog_pct":   lambda m: service_backlog_pct(hcs(m), 1, "hospitalized_agents", "_pending_admissions", getattr(m, "hours", 0)),
            "hc_3_util_pct":      lambda m: service_load_pct(hcs(m), 2, "hospitalized_agents"),
            "hc_3_backlog_pct":   lambda m: service_backlog_pct(hcs(m), 2, "hospitalized_agents", "_pending_admissions", getattr(m, "hours", 0)),
            "hc_4_util_pct":      lambda m: service_load_pct(hcs(m), 3, "hospitalized_agents"),
            "hc_4_backlog_pct":   lambda m: service_backlog_pct(hcs(m), 3, "hospitalized_agents", "_pending_admissions", getattr(m, "hours", 0)),
            "hc_load_flood":       lambda m: _hc_hospitalized_by(m, _is_flood_only_case),
            "hc_util_flood_pct":   lambda m: pct(_hc_hospitalized_by(m, _is_flood_only_case), max(1, healthcare_capacity(m))),
            "hc_load_mold":        lambda m: _hc_hospitalized_by(m, _is_mold_only_case),
            "hc_util_mold_pct":    lambda m: pct(_hc_hospitalized_by(m, _is_mold_only_case), max(1, healthcare_capacity(m))),
            "hc_load_vector":      lambda m: _hc_hospitalized_by(m, _is_vector_only_case),
            "hc_util_vector_pct":  lambda m: pct(_hc_hospitalized_by(m, _is_vector_only_case), max(1, healthcare_capacity(m))),
            "hc_load_infectious":      lambda m: _hc_hospitalized_by(m, _is_infectious_only_case),
            "hc_util_infectious_pct":  lambda m: pct(_hc_hospitalized_by(m, _is_infectious_only_case), max(1, healthcare_capacity(m))),
            "hc_load_compound":      lambda m: _hc_hospitalized_by(m, _is_compound_case),
            "hc_util_compound_pct":  lambda m: pct(_hc_hospitalized_by(m, _is_compound_case), max(1, healthcare_capacity(m))),
            "hc_wealth":           lambda m: sum(float(getattr(h, "wealth", 0.0) or 0.0) for h in hcs(m)),
            "hc_grants_total":     lambda m: sum(float(getattr(h, "total_grants_received", 0.0) or 0.0) for h in hcs(m)),
            "hc_patient_revenue_total": lambda m: sum(float(getattr(h, "patient_revenue_total", 0.0) or 0.0) for h in hcs(m)),
            "hc_bad_debt_total":   lambda m: sum(float(getattr(h, "bad_debt_total", 0.0) or 0.0) for h in hcs(m)),
            "hc_ops_spend_total":  lambda m: sum(float(getattr(h, "ops_spend_total", 0.0) or 0.0) for h in hcs(m)),
            "hc_supplies_spend_total": lambda m: sum(float(getattr(h, "supplies_spend_total", 0.0) or 0.0) for h in hcs(m)),
            "hc_wealth_per_cap":   lambda m: safe_div(sum(float(getattr(h, "wealth", 0.0) or 0.0) for h in hcs(m)), max(1, healthcare_capacity(m))),

            # ---------- businesses (system health) ----------
            "biz_total":          lambda m: n_biz(m),
            "biz_open_cnt":       lambda m: sum(1 for b in bizs(m) if hasattr(b, "is_open") and b.is_open()),
            "biz_flooded_cnt":    lambda m: sum(1 for b in bizs(m) if getattr(b, "flooded", False)),
            "biz_ever_flooded_cnt": lambda m: sum(1 for b in bizs(m) if getattr(b, "ever_flooded", False)),
            "biz_open_pct":       lambda m: pct(sum(1 for b in bizs(m) if hasattr(b,"is_open") and b.is_open()), n_biz(m)),
            "biz_flooded_pct":    lambda m: pct(sum(1 for b in bizs(m) if getattr(b,"flooded",False)), n_biz(m)),
            "biz_ever_flooded_pct": lambda m: pct(sum(1 for b in bizs(m) if getattr(b, "ever_flooded", False)), n_biz(m)),
            "biz_molded_pct":     lambda m: pct(sum(1 for b in bizs(m) if float(getattr(b, "mold_index", 0.0) or 0.0) > 0.05), n_biz(m)),
            "biz_staffed_pct":    lambda m: pct(len(_activity_counts_cached(m)["staffed_workplaces"]), n_biz(m)),
            "workforce_total":      lambda m: _activity_counts_cached(m)["workforce_total"],
            "work_attending_cnt":   lambda m: _activity_counts_cached(m)["work_attending"],
            "work_attendance_pct":  lambda m: pct(
                                        _activity_counts_cached(m)["work_attending"],
                                        max(1, _activity_counts_cached(m)["workforce_total"])
                                    ),
            "work_attendance_workhours_pct":  lambda m: (
                                        pct(
                                            _activity_counts_cached(m)["work_attending"],
                                            max(1, _activity_counts_cached(m)["workforce_total"])
                                        ) if _in_work_session(m) else 0.0
                                    ),
            "work_attendance_scheduled_pct": lambda m: (
                                        pct(
                                            _activity_counts_cached(m)["work_attending"],
                                            max(1, _activity_counts_cached(m)["workforce_total"])
                                        ) if _in_work_session(m) else 0.0
                                    ),

            # normalized economics (relative to scenario GDP & per capita)
            "biz_sales_vs_gdp_pct":    lambda m: 100.0 * safe_div(sum(float(getattr(b,"total_sales",0.0) or 0.0) for b in bizs(m)), float(getattr(m,"business_gdp",1.0) or 1.0)),
            "biz_netrev_vs_gdp_pct":   lambda m: 100.0 * safe_div(sum(float(getattr(b,"total_net_revenue",0.0) or 0.0) for b in bizs(m)), float(getattr(m,"business_gdp",1.0) or 1.0)),
            "biz_wages_vs_gdp_pct":    lambda m: 100.0 * safe_div(sum(float(getattr(b,"total_wages_paid",0.0) or 0.0) for b in bizs(m)), float(getattr(m,"business_gdp",1.0) or 1.0)),
            "biz_wealth_total":         lambda m: float(sum(float(getattr(b, "wealth", 0.0) or 0.0) for b in bizs(m))),
            "biz_wealth_vs_gdp_pct":    lambda m: 100.0 * safe_div(sum(float(getattr(b, "wealth", 0.0) or 0.0) for b in bizs(m)), float(getattr(m, "business_gdp", 1.0) or 1.0)),
            "person_wealth_total":      lambda m: float(sum(float(getattr(p, "income", 0.0) or 0.0) for p in people(m))),
            "person_wealth_total_scaled": lambda m: float(
                                        sum(float(getattr(p, "income", 0.0) or 0.0) for p in people(m))
                                        * safe_div(
                                            float(getattr(m, "person_wealth_reference_population", 300.0) or 300.0),
                                            max(1.0, float(getattr(m, "num_persons", 0) or len(people(m)) or 1.0)),
                                        )
                                    ),
            "person_wealth_mean":       lambda m: income_mean(m),
            "person_income_mean":       lambda m: income_mean(m),
            "person_income_median":     lambda m: float(np.median([float(getattr(p, "income", 0.0) or 0.0) for p in people(m)])) if people(m) else 0.0,
            "income_mean_children":     lambda m: income_mean(m, lambda p: int(getattr(p, "age", 0) or 0) < 15),
            "income_mean_adults":       lambda m: income_mean(m, lambda p: 15 <= int(getattr(p, "age", 0) or 0) < 65),
            "income_mean_seniors":      lambda m: income_mean(m, lambda p: int(getattr(p, "age", 0) or 0) >= 65),
            "income_mean_female":       lambda m: income_mean(m, lambda p: getattr(p, "gender", "") == "Female"),
            "income_mean_male":         lambda m: income_mean(m, lambda p: getattr(p, "gender", "") == "Male"),
            "income_mean_low_income":   lambda m: income_mean(m, lambda p: getattr(p, "wealth_class", "") == "Lower_Class"),
            "income_mean_middle_income":lambda m: income_mean(m, lambda p: getattr(p, "wealth_class", "") == "Middle_Class"),
            "income_mean_upper_middle": lambda m: income_mean(m, lambda p: getattr(p, "wealth_class", "") == "Upper_Middle_Class"),
            "income_mean_upper":        lambda m: income_mean(m, lambda p: getattr(p, "wealth_class", "") == "Upper_Class"),
            "income_mean_white":        lambda m: income_mean(m, lambda p: getattr(p, "ethnicity", "") == "White"),
            "income_mean_black":        lambda m: income_mean(m, lambda p: getattr(p, "ethnicity", "") == "Black"),
            "income_mean_hispanic":     lambda m: income_mean(m, lambda p: getattr(p, "ethnicity", "") == "Hispanic"),
            "income_mean_other":        lambda m: income_mean(m, lambda p: getattr(p, "ethnicity", "") == "Other"),
            "income_mean_hierarchist":  lambda m: income_mean(m, lambda p: getattr(p, "worldview", "") == "hierarchist"),
            "income_mean_egalitarian":  lambda m: income_mean(m, lambda p: getattr(p, "worldview", "") == "egalitarian"),
            "income_mean_individualist":lambda m: income_mean(m, lambda p: getattr(p, "worldview", "") == "individualist"),
            "income_mean_fatalist":     lambda m: income_mean(m, lambda p: getattr(p, "worldview", "") == "fatalist"),

            # ---------- housing ----------
            "house_total":            lambda m: n_house(m),
            "house_hab_cnt":          lambda m: sum(1 for h in houses(m) if hasattr(h, "is_habitable_now") and h.is_habitable_now()),
            "house_flooded_cnt":      lambda m: sum(1 for h in houses(m) if getattr(h, "flooded", False)),
            "house_ever_flooded_cnt": lambda m: sum(1 for h in houses(m) if getattr(h, "ever_flooded", False)),
            "house_hab_pct":          lambda m: pct(sum(1 for h in houses(m) if hasattr(h,"is_habitable_now") and h.is_habitable_now()), n_house(m)),
            "house_flooded_pct":      lambda m: pct(sum(1 for h in houses(m) if getattr(h,"flooded",False)), n_house(m)),
            "house_ever_flooded_pct": lambda m: pct(sum(1 for h in houses(m) if getattr(h, "ever_flooded", False)), n_house(m)),
            "house_mean_depth_m":     lambda m: safe_div(sum(float(getattr(h,"last_depth",0.0) or 0.0) for h in houses(m)), n_house(m)),
            "house_mean_habitability":lambda m: safe_div(
                                            sum((float(h.habitability()) if hasattr(h,"habitability") else (0.0 if getattr(h,"flooded",False) else 1.0)) for h in houses(m)),
                                            n_house(m)
                                        ),

            # ---------- schools / education access ----------
            "school_total":              lambda m: n_school(m),
            "school_flooded_cnt":        lambda m: sum(1 for s in schools(m) if getattr(s, "flooded", False)),
            "school_open_now_cnt":       lambda m: sum(1 for s in schools(m) if hasattr(s, "is_open_now") and s.is_open_now()),
            "school_flooded_pct":        lambda m: pct(sum(1 for s in schools(m) if getattr(s,"flooded",False)), n_school(m)),
            "school_open_now_pct":       lambda m: pct(sum(1 for s in schools(m) if hasattr(s,"is_open_now") and s.is_open_now()), n_school(m)),
            "school_enrolled_total":     lambda m: _activity_counts_cached(m)["student_total"],
            "school_present_total":      lambda m: _activity_counts_cached(m)["school_present"],
            "attendance_rate_pct":       lambda m: pct(
                                                _activity_counts_cached(m)["school_present"],
                                                max(1, _activity_counts_cached(m)["student_total"])
                                            ),
            "school_attendance_scheduled_pct": lambda m: (
                                                pct(
                                                    _activity_counts_cached(m)["school_present"],
                                                    max(1, _activity_counts_cached(m)["student_total"])
                                                ) if _in_school_session(m) else 0.0
                                            ),
            "school_hours_open_sum":     lambda m: sum(int(getattr(s,"hours_open",0) or 0) for s in schools(m)),
            "student_hours_lost_sum":    lambda m: sum(int(getattr(s,"student_hours_lost",0) or 0) for s in schools(m)),
            "attendance_hours_sum":      lambda m: sum(int(getattr(s,"total_attendance_hours",0) or 0) for s in schools(m)),
            "school_molded_pct":         lambda m: 100.0 * (
                                            sum(1 for s in schools(m) if float(getattr(s, "mold_index", 0.0) or 0.0) > 0.05)
                                            / max(1, len(schools(m)))
                                        ),
            "normal_activity_pct":       lambda m: pct(
                                                _activity_counts_cached(m)["normal_activity"],
                                                max(1, sum(1 for p in people(m) if getattr(p, "alive", True)))
                                            ),
            # ---------- leisure and shopping attendance ----------
            "leisure_attendance_pct": lambda m: pct(
                _activity_counts_cached(m)["leisure"],
                max(1, sum(1 for p in people(m) if getattr(p, "alive", True)))
            ),
            "shopping_attendance_pct": lambda m: pct(
                _activity_counts_cached(m)["shopping"],
                max(1, sum(1 for p in people(m) if getattr(p, "alive", True)))
            ),

            # ---------- quality of life (0..100) ----------
            "qol_mean_pct":              lambda m: qol_mean_pct(m),
            "qol_children_pct":          lambda m: qol_mean_pct(m, lambda p: int(getattr(p, "age", 0) or 0) < 15),
            "qol_adults_pct":            lambda m: qol_mean_pct(m, lambda p: 15 <= int(getattr(p, "age", 0) or 0) < 65),
            "qol_seniors_pct":           lambda m: qol_mean_pct(m, lambda p: int(getattr(p, "age", 0) or 0) >= 65),
            "qol_low_income_pct":        lambda m: qol_mean_pct(m, lambda p: getattr(p, "wealth_class", "") == "Lower_Class"),
            "qol_middle_income_pct":     lambda m: qol_mean_pct(m, lambda p: getattr(p, "wealth_class", "") == "Middle_Class"),
            "qol_upper_middle_pct":      lambda m: qol_mean_pct(m, lambda p: getattr(p, "wealth_class", "") == "Upper_Middle_Class"),
            "qol_upper_pct":             lambda m: qol_mean_pct(m, lambda p: getattr(p, "wealth_class", "") == "Upper_Class"),
            "qol_high_income_pct":       lambda m: qol_mean_pct(m, lambda p: getattr(p, "wealth_class", "") in ("Upper_Class", "Upper_Middle_Class")),
            "qol_white_pct":             lambda m: qol_mean_pct(m, lambda p: getattr(p, "ethnicity", "") == "White"),
            "qol_black_pct":             lambda m: qol_mean_pct(m, lambda p: getattr(p, "ethnicity", "") == "Black"),
            "qol_hispanic_pct":          lambda m: qol_mean_pct(m, lambda p: getattr(p, "ethnicity", "") == "Hispanic"),
            "qol_other_pct":             lambda m: qol_mean_pct(m, lambda p: getattr(p, "ethnicity", "") == "Other"),
            "qol_hierarchist_pct":       lambda m: qol_mean_pct(m, lambda p: getattr(p, "worldview", "") == "hierarchist"),
            "qol_egalitarian_pct":       lambda m: qol_mean_pct(m, lambda p: getattr(p, "worldview", "") == "egalitarian"),
            "qol_individualist_pct":     lambda m: qol_mean_pct(m, lambda p: getattr(p, "worldview", "") == "individualist"),
            "qol_fatalist_pct":          lambda m: qol_mean_pct(m, lambda p: getattr(p, "worldview", "") == "fatalist"),

            # ---------- government finance (per-capita) ----------
            "gov_wealth":                lambda m: float(getattr(gov(m), "wealth", 0.0) or 0.0),
            "gov_wealth_vs_gdp_pct":     lambda m: 100.0 * safe_div(float(getattr(gov(m), "wealth", 0.0) or 0.0), float(getattr(m, "government_gdp", 1.0) or 1.0)),
            "gov_sales_tax_total":       lambda m: float(getattr(gov(m), "total_sales_tax", 0.0) or 0.0),
            "gov_income_withhold_total": lambda m: float(getattr(gov(m), "total_income_withholding", 0.0) or 0.0),
            "gov_corp_tax_total":        lambda m: float(getattr(gov(m), "total_corporate_tax", 0.0) or 0.0),
            "gov_grants_total":          lambda m: float(getattr(gov(m), "total_transfers", 0.0) or 0.0),
            "gov_balance_per_capita":    lambda m: safe_div(float(getattr(gov(m), "wealth", 0.0) or 0.0), max(1, pop(m))),
            "taxes_per_capita":          lambda m: safe_div(
                                                float(getattr(gov(m),"total_sales_tax",0.0) or 0.0)
                                              + float(getattr(gov(m),"total_income_withholding",0.0) or 0.0)
                                              + float(getattr(gov(m),"total_corporate_tax",0.0) or 0.0),
                                                max(1, pop(m))
                                            ),
            "grants_per_capita":         lambda m: safe_div(float(getattr(gov(m),"total_transfers",0.0) or 0.0), max(1, pop(m))),
            "taxes_per_capita_hr":       delta_reporter(
                                                "taxes_per_capita_hr",
                                                lambda m: safe_div(
                                                    float(getattr(gov(m), "total_sales_tax", 0.0) or 0.0)
                                                    + float(getattr(gov(m), "total_income_withholding", 0.0) or 0.0)
                                                    + float(getattr(gov(m), "total_corporate_tax", 0.0) or 0.0),
                                                    max(1, pop(m))
                                                )
                                            ),
            "grants_per_capita_hr":      delta_reporter(
                                                "grants_per_capita_hr",
                                                lambda m: safe_div(float(getattr(gov(m), "total_transfers", 0.0) or 0.0), max(1, pop(m)))
                                            ),

            # ---------- hazard & exposure ----------
            "hazard_max_depth_m":       lambda m: (
                max(((fa.depth_at(getattr(fa.geometry,"representative_point",lambda: None)(), hours=getattr(m,"hours",0)) or 0.0)
                    if hasattr(fa,"depth_at") else 0.0) for fa in (getattr(space(m),"flood_areas",[]) or []))
                if (getattr(space(m),"flood_areas",[]) or []) else 0.0
            ),
            "hazard_flooded_area":      lambda m: sum(getattr(getattr(fa,"geometry",None),"area",0.0) for fa in (getattr(space(m),"flood_areas",[]) or [])),
            "home_depth_mean_m":        lambda m: (
                sum(float(getattr(p,"last_forecast_depth_seen",0.0) or 0.0) for p in people(m)) / max(1, pop(m))
            ) if people(m) else 0.0,
            # "hours_to_deadline":        lambda m: (
            #     max(0.0, float(getattr(m,"last_evacuation_time",0.0) or 0.0) - float(getattr(m,"hours",0.0) or 0.0))
            #     if float(getattr(m,"hours",0.0) or 0.0) <= float(getattr(m,"last_evacuation_time",0.0) or 0.0) else 0.0
            # ),

            # ---------- vulnerability bands (shares) ----------
            "vuln_low_pct":   lambda m: pct(sum(1 for p in people(m) if 0.0 <= float(getattr(p,"vulnerability",0.0) or 0.0) < 0.4), pop(m)),
            "vuln_mid_pct":   lambda m: pct(sum(1 for p in people(m) if 0.4 <= float(getattr(p,"vulnerability",0.0) or 0.0) < 0.7), pop(m)),
            "vuln_high_pct":  lambda m: pct(sum(1 for p in people(m) if 0.7 <= float(getattr(p,"vulnerability",0.0) or 0.0) <= 1.01), pop(m)),
            "children_disease_pct": lambda m: subgroup_disease_pct(m, lambda p: getattr(p, "age", 0) < 15),
            "seniors_disease_pct":  lambda m: subgroup_disease_pct(m, lambda p: getattr(p, "age", 0) >= 65),
            "low_income_disease_pct": lambda m: subgroup_disease_pct(m, lambda p: getattr(p, "wealth_class", "") == "Lower_Class"),
            "high_income_disease_pct": lambda m: subgroup_disease_pct(m, lambda p: getattr(p, "wealth_class", "") in ("Upper_Class", "Upper_Middle_Class")),
            "high_vuln_disease_pct": lambda m: subgroup_disease_pct(m, lambda p: float(getattr(p, "vulnerability", 0.0) or 0.0) >= 0.70),
            "inequity_gap_low_vs_high_pct": lambda m: subgroup_disease_pct(m, lambda p: getattr(p, "wealth_class", "") == "Lower_Class") - subgroup_disease_pct(m, lambda p: getattr(p, "wealth_class", "") in ("Upper_Class", "Upper_Middle_Class")),
        }
    )

    # Guard against occasional reporter desynchronization: if one reporter errors
    # mid-collect, Mesa can leave model_vars columns with unequal lengths.
    # Padding shorter series prevents plotting/dataframe crashes.
    def _safe_get_model_vars_dataframe(self):
        model_vars = getattr(self, "model_vars", None)
        if not model_vars:
            return pd.DataFrame()

        lengths = [len(v) for v in model_vars.values() if hasattr(v, "__len__")]
        if not lengths:
            return pd.DataFrame(model_vars)

        max_len = max(lengths)
        aligned = {}
        for key, values in list(model_vars.items()):
            if not hasattr(values, "__len__"):
                aligned[key] = [values] * max_len
                continue
            cur_len = len(values)
            seq = list(values)
            if cur_len < max_len:
                seq = seq + ([np.nan] * (max_len - cur_len))
            aligned[key] = seq

        return pd.DataFrame(aligned)

    model.datacollector.get_model_vars_dataframe = types.MethodType(
        _safe_get_model_vars_dataframe,
        model.datacollector,
    )

# ----------------------------------------------------------------------
# Post-run exports for paper tables/figures (timeseries + summary KPIs)
# ----------------------------------------------------------------------

def export_timeseries(model, out_dir=None):
    """Write the full time series to CSV."""
    
    df = model.datacollector.get_model_vars_dataframe().reset_index(drop=True)
    out = Path(out_dir or (Path(__file__).resolve().parent / "timeseries")).resolve()
    out.mkdir(parents=True, exist_ok=True)

    # Only write disease and other non-routine timeseries if not baseline
    scenario = getattr(model, "scenario_mode", None) or getattr(model, "scenario", None) or "baseline"
    if scenario == "baseline":
        # Only write core routine timeseries (skip disease, etc.)
        routine_cols = [col for col in df.columns if not ("disease" in col or "infect" in col or "evac" in col or "flood" in col)]
        df_routine = df[routine_cols]
        df_routine.to_csv(out / "timeseries.csv", index=False)
        return df_routine, out
    else:
        df.to_csv(out / "timeseries.csv", index=False)
        return df, out


def export_person_panel(model, out_dir=None):
    """
    Export a person-level analysis panel for linking behavior, personality,
    vulnerability, and later disease outcomes.
    """
    people = getattr(model, "people", []) or []
    rows = []

    for p in people:
        has_any_disease = bool(
            getattr(p, "ill_respiratory", False) or
            getattr(p, "ill_vector", False) or
            getattr(p, "symp_mold", False) or
            getattr(p, "symp_vector", False) or
            getattr(p, "inf_state", "S") == "I"
        )
        disease_count = int(sum([
            bool(getattr(p, "ill_respiratory", False) or getattr(p, "symp_mold", False)),
            bool(getattr(p, "ill_vector", False) or getattr(p, "symp_vector", False)),
            getattr(p, "inf_state", "S") == "I",
        ]))

        rows.append({
            "scenario": getattr(model, "scenario_mode", "compound"),
            "run_id": getattr(model, "run_id", getattr(model, "scenario_mode", "compound")),
            "replication": int(getattr(model, "replication", 0) or 0),
            "random_seed": int(getattr(model, "random_seed", 0) or 0),
            "event_phase": getattr(model, "event_phase", None),
            "flood_enabled": bool(getattr(model, "enable_flood", True)),
            "disease_enabled": bool(getattr(model, "enable_disease_system", False)),
            "infectious_enabled": bool(getattr(model, "enable_infectious", False)),
            "vectorborne_enabled": bool(getattr(model, "enable_vectorborne", getattr(model, "enable_stagnant", False))),
            "mold_enabled": bool(getattr(model, "enable_mold", False)),
            "agent_id": getattr(p, "name", None),
            "alive": bool(getattr(p, "alive", True)),
            "death_cause": getattr(p, "death_cause", None),
            "age": int(getattr(p, "age", 0) or 0),
            "gender": getattr(p, "gender", None),
            "education": float(getattr(p, "education", 0.0) or 0.0),
            "wealth_class": getattr(p, "wealth_class", None),
            "income": float(getattr(p, "income", 0.0) or 0.0),
            "vulnerability": float(getattr(p, "vulnerability", 0.0) or 0.0),
            "health_vulnerability": float(getattr(p, "health_vulnerability", 0.0) or 0.0),
            "worldview": getattr(p, "worldview", None),
            "trust_in_authorities": float(getattr(p, "trust_in_authorities", 0.0) or 0.0),
            "social_trust": float(getattr(p, "social_trust", 0.0) or 0.0),
            "media_trust": float(getattr(p, "media_trust", 0.0) or 0.0),
            "self_efficacy": float(getattr(p, "self_efficacy", 0.0) or 0.0),
            "response_efficacy": float(getattr(p, "response_efficacy", 0.0) or 0.0),
            "intention": float(getattr(p, "intention", 0.0) or 0.0),
            "last_action": getattr(p, "last_action", "Routine"),
            "last_decision_phase": getattr(p, "last_decision_phase", "baseline"),
            "last_threat": float(getattr(p, "last_threat", 0.0) or 0.0),
            "last_coping": float(getattr(p, "last_coping", 0.0) or 0.0),
            "evacuated": bool(getattr(p, "evacuated", False)),
            "in_shelter": bool(getattr(p, "in_shelter", False)),
            "stranded": bool(getattr(p, "stranded", False)),
            "injured": bool(getattr(p, "injured", False)),
            "ill_respiratory": bool(getattr(p, "ill_respiratory", False)),
            "ill_vector": bool(getattr(p, "ill_vector", False)),
            "symp_mold": bool(getattr(p, "symp_mold", False)),
            "symp_vector": bool(getattr(p, "symp_vector", False)),
            "inf_state": getattr(p, "inf_state", "S"),
            "has_any_disease": has_any_disease,
            "disease_count": disease_count,
            "sick_hours_total": int(getattr(p, "sick_hours_total", 0) or 0),
            "sick_hours_respiratory": int(getattr(p, "sick_hours_respiratory", 0) or 0),
            "sick_hours_vector": int(getattr(p, "sick_hours_vector", 0) or 0),
        })

    df = pd.DataFrame(rows)
    out = Path(out_dir or (Path(__file__).resolve().parent / "timeseries")).resolve()
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "person_panel.csv", index=False)

    if not df.empty:
        action_summary = (
            df.groupby("last_action", dropna=False)
              .agg(
                  n_agents=("agent_id", "count"),
                  disease_pct=("has_any_disease", lambda s: 100.0 * float(np.mean(s.astype(float)))),
                  mean_threat=("last_threat", "mean"),
                  mean_coping=("last_coping", "mean"),
                  evac_pct=("evacuated", lambda s: 100.0 * float(np.mean(s.astype(float)))),
              )
              .reset_index()
        )
        action_summary.to_csv(out / "disease_by_action.csv", index=False)

        worldview_summary = (
            df.groupby("worldview", dropna=False)
              .agg(
                  n_agents=("agent_id", "count"),
                  disease_pct=("has_any_disease", lambda s: 100.0 * float(np.mean(s.astype(float)))),
                  evac_pct=("evacuated", lambda s: 100.0 * float(np.mean(s.astype(float)))),
                  mean_trust=("trust_in_authorities", "mean"),
                  mean_self_efficacy=("self_efficacy", "mean"),
              )
              .reset_index()
        )
        worldview_summary.to_csv(out / "disease_by_worldview.csv", index=False)

    return df, out


def export_summary(model, out_dir=None):
    """
    Compute publication-friendly summary KPIs:
      • Peaks and timing (stranded %, shelter/HC utilization)
      • Totals (student-hours lost, attendance-hours, taxes/grants)
      • End-state economics (sales/netrev vs GDP)
      • Areas-under-curve (AUC) for key % series (burden over time)
    """

    df = model.datacollector.get_model_vars_dataframe().reset_index(drop=True)
    if df.empty:
        return {}

    def peak_and_when(col):
        s = df[col].fillna(0.0)
        i = int(s.values.argmax()) if len(s) else 0
        return float(s.iloc[i]), int(df["hours"].iloc[i] if "hours" in df.columns else i)

    def auc(col):
        if "hours" not in df.columns or col not in df.columns:
            return 0.0
        x = df["hours"].astype(float).values
        y = df[col].fillna(0.0).astype(float).values
        if len(x) < 2:
            return float(np.sum(y))
        if hasattr(np, "trapezoid"):
            return float(np.trapezoid(y, x))
        return float(np.trapz(y, x))

    # Peaks (percentages)
    stranded_peak_pct, stranded_peak_hr = peak_and_when("stranded_pct")
    shelter_peak_pct, shelter_peak_hr   = peak_and_when("shelter_util_pct")
    hc_peak_pct, hc_peak_hr             = peak_and_when("hc_util_pct")
    compound_peak_pct, compound_peak_hr = peak_and_when("compound_burden_pct") if "compound_burden_pct" in df.columns else (0.0, 0)
    inequity_gap_peak_pct, inequity_gap_peak_hr = peak_and_when("inequity_gap_low_vs_high_pct") if "inequity_gap_low_vs_high_pct" in df.columns else (0.0, 0)
    biz_open_min_pct, biz_open_min_hr   = peak_and_when("biz_open_pct")  # peak of open% is *best*; for worst, invert AUC or report min separately
    # For worst moment of business openness:
    if "biz_open_pct" in df.columns:
        s = df["biz_open_pct"].fillna(0.0)
        j = int(s.values.argmin()) if len(s) else 0
        biz_open_worst_pct, biz_open_worst_hr = float(s.iloc[j]), int(df["hours"].iloc[j] if "hours" in df.columns else j)
    else:
        biz_open_worst_pct, biz_open_worst_hr = 0.0, 0

    # Totals
    student_hours_lost = float(df["student_hours_lost_sum"].iloc[-1]) if "student_hours_lost_sum" in df.columns else 0.0
    attendance_hours   = float(df["attendance_hours_sum"].iloc[-1])   if "attendance_hours_sum" in df.columns else 0.0
    taxes_total = float(df[["gov_sales_tax_total","gov_income_withhold_total","gov_corp_tax_total"]].fillna(0.0).iloc[-1].sum()) if set(["gov_sales_tax_total","gov_income_withhold_total","gov_corp_tax_total"]).issubset(df.columns) else 0.0
    grants_total = float(df["gov_grants_total"].iloc[-1]) if "gov_grants_total" in df.columns else 0.0
    total_sick_hours = float(df["sick_hours_total_sum"].iloc[-1]) if "sick_hours_total_sum" in df.columns else 0.0
    respiratory_sick_hours = float(df["sick_hours_respiratory_sum"].iloc[-1]) if "sick_hours_respiratory_sum" in df.columns else 0.0
    vector_sick_hours = float(df["sick_hours_vector_sum"].iloc[-1]) if "sick_hours_vector_sum" in df.columns else 0.0
    dead_pct_end = float(df["dead_pct"].iloc[-1]) if "dead_pct" in df.columns else 0.0

    # End-state economics (normalized)
    sales_vs_gdp  = float(df["biz_sales_vs_gdp_pct"].iloc[-1])  if "biz_sales_vs_gdp_pct"  in df.columns else 0.0
    netrev_vs_gdp = float(df["biz_netrev_vs_gdp_pct"].iloc[-1]) if "biz_netrev_vs_gdp_pct" in df.columns else 0.0
    wages_vs_gdp  = float(df["biz_wages_vs_gdp_pct"].iloc[-1])  if "biz_wages_vs_gdp_pct"  in df.columns else 0.0
    inequity_gap_end = float(df["inequity_gap_low_vs_high_pct"].iloc[-1]) if "inequity_gap_low_vs_high_pct" in df.columns else 0.0
    low_income_disease_end = float(df["low_income_disease_pct"].iloc[-1]) if "low_income_disease_pct" in df.columns else 0.0
    high_vuln_disease_end = float(df["high_vuln_disease_pct"].iloc[-1]) if "high_vuln_disease_pct" in df.columns else 0.0
    decision_evac_end = float(df["decision_evac_pct"].iloc[-1]) if "decision_evac_pct" in df.columns else 0.0
    decision_prepare_end = float(df["decision_prepare_pct"].iloc[-1]) if "decision_prepare_pct" in df.columns else 0.0
    decision_delay_return_end = float(df["decision_delay_return_pct"].iloc[-1]) if "decision_delay_return_pct" in df.columns else 0.0
    disease_among_evacuated_end = float(df["disease_among_evacuated_pct"].iloc[-1]) if "disease_among_evacuated_pct" in df.columns else 0.0
    disease_among_sheltered_end = float(df["disease_among_sheltered_pct"].iloc[-1]) if "disease_among_sheltered_pct" in df.columns else 0.0
    disease_after_delay_return_end = float(df["disease_after_delay_return_pct"].iloc[-1]) if "disease_after_delay_return_pct" in df.columns else 0.0
    male_pct_end = float(df["male_pct"].iloc[-1]) if "male_pct" in df.columns else 0.0
    female_pct_end = float(df["female_pct"].iloc[-1]) if "female_pct" in df.columns else 0.0
    age_0_14_pct_end = float(df["age_0_14_pct"].iloc[-1]) if "age_0_14_pct" in df.columns else 0.0
    age_15_64_pct_end = float(df["age_15_64_pct"].iloc[-1]) if "age_15_64_pct" in df.columns else 0.0
    age_65_100_pct_end = float(df["age_65_100_pct"].iloc[-1]) if "age_65_100_pct" in df.columns else 0.0
    worldview_hierarchist_pct_end = float(df["worldview_hierarchist_pct"].iloc[-1]) if "worldview_hierarchist_pct" in df.columns else 0.0
    worldview_egalitarian_pct_end = float(df["worldview_egalitarian_pct"].iloc[-1]) if "worldview_egalitarian_pct" in df.columns else 0.0
    worldview_individualist_pct_end = float(df["worldview_individualist_pct"].iloc[-1]) if "worldview_individualist_pct" in df.columns else 0.0
    worldview_fatalist_pct_end = float(df["worldview_fatalist_pct"].iloc[-1]) if "worldview_fatalist_pct" in df.columns else 0.0

    # Areas-under-curve (burden over time)
    auc_stranded_pct = auc("stranded_pct")
    auc_shelter_util = auc("shelter_util_pct")
    auc_hc_util      = auc("hc_util_pct")
    auc_compound_burden = auc("compound_burden_pct") if "compound_burden_pct" in df.columns else 0.0
    auc_inequity_gap = auc("inequity_gap_low_vs_high_pct") if "inequity_gap_low_vs_high_pct" in df.columns else 0.0

    summary = {
        "scenario": {
            "scenario_mode": getattr(model, "scenario_mode", "compound"),
            "run_id": getattr(model, "run_id", getattr(model, "scenario_mode", "compound")),
            "replication": int(getattr(model, "replication", 0) or 0),
            "random_seed": int(getattr(model, "random_seed", 0) or 0),
            "flood_enabled": bool(getattr(model, "enable_flood", True)),
            "disease_enabled": bool(getattr(model, "enable_disease_system", False)),
            "infectious_enabled": bool(getattr(model, "enable_infectious", False)),
            "vectorborne_enabled": bool(getattr(model, "enable_vectorborne", getattr(model, "enable_stagnant", False))),
            "mold_enabled": bool(getattr(model, "enable_mold", False)),
            "config_male_pct": float(getattr(model, "male_share_pct", 49.0) or 49.0),
            "config_female_pct": float(getattr(model, "female_share_pct", 51.0) or 51.0),
            "config_age_0_14_pct": float(getattr(model, "age_0_14_pct", 16.0) or 16.0),
            "config_age_15_64_pct": float(getattr(model, "age_15_64_pct", 65.0) or 65.0),
            "config_age_65_100_pct": float(getattr(model, "age_65_100_pct", 19.0) or 19.0),
            "config_worldview_hierarchist_pct": float(getattr(model, "worldview_hierarchist_pct", 25.0) or 25.0),
            "config_worldview_egalitarian_pct": float(getattr(model, "worldview_egalitarian_pct", 25.0) or 25.0),
            "config_worldview_individualist_pct": float(getattr(model, "worldview_individualist_pct", 25.0) or 25.0),
            "config_worldview_fatalist_pct": float(getattr(model, "worldview_fatalist_pct", 25.0) or 25.0),
        },
        "peaks": {
            "stranded_pct": {"value": stranded_peak_pct, "hour": stranded_peak_hr},
            "shelter_util_pct": {"value": shelter_peak_pct, "hour": shelter_peak_hr},
            "hc_util_pct": {"value": hc_peak_pct, "hour": hc_peak_hr},
            "compound_burden_pct": {"value": compound_peak_pct, "hour": compound_peak_hr},
            "inequity_gap_low_vs_high_pct": {"value": inequity_gap_peak_pct, "hour": inequity_gap_peak_hr},
            "biz_open_worst_pct": {"value": biz_open_worst_pct, "hour": biz_open_worst_hr},
        },
        "totals": {
            "student_hours_lost": student_hours_lost,
            "attendance_hours": attendance_hours,
            "gov_taxes_total": taxes_total,
            "gov_grants_total": grants_total,
            "sick_hours_total_sum": total_sick_hours,
            "sick_hours_respiratory_sum": respiratory_sick_hours,
            "sick_hours_vector_sum": vector_sick_hours,
        },
        "end_state": {
            "biz_sales_vs_gdp_pct": sales_vs_gdp,
            "biz_netrev_vs_gdp_pct": netrev_vs_gdp,
            "biz_wages_vs_gdp_pct": wages_vs_gdp,
            "dead_pct": dead_pct_end,
            "inequity_gap_low_vs_high_pct": inequity_gap_end,
            "low_income_disease_pct": low_income_disease_end,
            "high_vuln_disease_pct": high_vuln_disease_end,
            "decision_evac_pct": decision_evac_end,
            "decision_prepare_pct": decision_prepare_end,
            "decision_delay_return_pct": decision_delay_return_end,
            "disease_among_evacuated_pct": disease_among_evacuated_end,
            "disease_among_sheltered_pct": disease_among_sheltered_end,
            "disease_after_delay_return_pct": disease_after_delay_return_end,
            "male_pct": male_pct_end,
            "female_pct": female_pct_end,
            "age_0_14_pct": age_0_14_pct_end,
            "age_15_64_pct": age_15_64_pct_end,
            "age_65_100_pct": age_65_100_pct_end,
            "worldview_hierarchist_pct": worldview_hierarchist_pct_end,
            "worldview_egalitarian_pct": worldview_egalitarian_pct_end,
            "worldview_individualist_pct": worldview_individualist_pct_end,
            "worldview_fatalist_pct": worldview_fatalist_pct_end,
        },
        "auc": {
            "stranded_pct_hours": auc_stranded_pct,
            "shelter_util_pct_hours": auc_shelter_util,
            "hc_util_pct_hours": auc_hc_util,
            "compound_burden_pct_hours": auc_compound_burden,
            "inequity_gap_low_vs_high_pct_hours": auc_inequity_gap,
        },
    }

    out = Path(out_dir or (Path(__file__).resolve().parent / "timeseries")).resolve()
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    return summary
