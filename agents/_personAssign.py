"""Helper functions that assign demographics, resources, and locations to person agents."""

import random
from shapely.geometry import Point
import mesa_geo as mg

# Shared population distribution knobs.
ANNUAL_INCOME_BANDS = {
    "Upper_Class":        (250_000, 500_000),
    "Upper_Middle_Class": (100_000, 250_000),
    "Middle_Class":       (50_000, 100_000),
    "Lower_Class":        (15_000, 50_000),
}

VEHICLE_BASE_PROB = {
    "Upper_Class":        0.90,
    "Upper_Middle_Class": 0.85,
    "Middle_Class":       0.70,
    "Lower_Class":        0.50,
}


def _clamp_pct(x, default=0.0):
    try:
        return max(0.0, min(100.0, float(x)))
    except Exception:
        return float(default)


def _clip01_gauss(mean, std_dev):
    return max(0.0, min(1.0, random.gauss(mean, std_dev)))


def _normalize_pct_map(pct_map):
    clean = {k: max(0.0, float(v or 0.0)) for k, v in pct_map.items()}
    total = sum(clean.values())
    if total <= 0.0:
        n = max(1, len(clean))
        return {k: 100.0 / n for k in clean}
    scale = 100.0 / total
    return {k: v * scale for k, v in clean.items()}


def _build_label_pool(total, pct_map, rng=random):
    pct_map = _normalize_pct_map(pct_map)
    raw = {k: (pct_map[k] / 100.0) * total for k in pct_map}
    counts = {k: int(v) for k, v in raw.items()}
    remainder = int(total - sum(counts.values()))
    ranked = sorted(raw.keys(), key=lambda k: (raw[k] - counts[k]), reverse=True)
    for label in ranked[:remainder]:
        counts[label] += 1

    pool = []
    for label, count in counts.items():
        pool.extend([label] * max(0, int(count)))
    rng.shuffle(pool)
    return pool, counts


def _build_label_pool_with_min_count(total, pct_map, rng=random, min_positive_count=0):
    pct_map = _normalize_pct_map(pct_map)
    pool, counts = _build_label_pool(total, pct_map, rng=rng)

    positive_labels = [label for label, pct in pct_map.items() if float(pct or 0.0) > 0.0]
    if not positive_labels:
        return pool, counts

    target_min = max(0, int(min_positive_count or 0))
    if target_min <= 0:
        return pool, counts

    max_feasible_min = max(0, total // max(1, len(positive_labels)))
    target_min = min(target_min, max_feasible_min)
    if target_min <= 0:
        return pool, counts

    donor_labels = sorted(positive_labels, key=lambda label: counts.get(label, 0), reverse=True)
    for label in positive_labels:
        while counts.get(label, 0) < target_min:
            donor = next(
                (name for name in donor_labels if name != label and counts.get(name, 0) > target_min),
                None,
            )
            if donor is None:
                break
            counts[donor] -= 1
            counts[label] = counts.get(label, 0) + 1

    pool = []
    for label, count in counts.items():
        pool.extend([label] * max(0, int(count)))
    rng.shuffle(pool)
    return pool, counts


def configure_population_mix(model):
    """Normalize configured demographic shares so each mix sums to 100."""
    male = _clamp_pct(model.male_share_pct, 49.0)
    female = _clamp_pct(model.female_share_pct, 51.0)
    gender_mix = _normalize_pct_map({
        "Male": male,
        "Female": female,
    })
    model.gender_mix = gender_mix
    model.male_share_pct = gender_mix["Male"]
    model.female_share_pct = gender_mix["Female"]

    age_mix = _normalize_pct_map({
        "0_14": _clamp_pct(model.age_0_14_pct, 16.0),
        "15_64": _clamp_pct(model.age_15_64_pct, 65.0),
        "65_100": _clamp_pct(model.age_65_100_pct, 19.0),
    })
    model.age_mix = age_mix
    model.age_0_14_pct = age_mix["0_14"]
    model.age_15_64_pct = age_mix["15_64"]
    model.age_65_100_pct = age_mix["65_100"]

    worldview_mix = _normalize_pct_map({
        "hierarchist": _clamp_pct(model.worldview_hierarchist_pct, 25.0),
        "egalitarian": _clamp_pct(model.worldview_egalitarian_pct, 25.0),
        "individualist": _clamp_pct(model.worldview_individualist_pct, 25.0),
        "fatalist": _clamp_pct(model.worldview_fatalist_pct, 25.0),
    })
    model.worldview_mix = worldview_mix
    model.worldview_hierarchist_pct = worldview_mix["hierarchist"]
    model.worldview_egalitarian_pct = worldview_mix["egalitarian"]
    model.worldview_individualist_pct = worldview_mix["individualist"]
    model.worldview_fatalist_pct = worldview_mix["fatalist"]

    ethnicity_mix = _normalize_pct_map({
        "White": _clamp_pct(model.ethnicity_white_pct, 83.0),
        "Black": _clamp_pct(model.ethnicity_black_pct, 6.0),
        "Hispanic": _clamp_pct(model.ethnicity_hispanic_pct, 10.0),
        "Other": _clamp_pct(model.ethnicity_other_pct, 1.0),
    })
    model.ethnicity_mix = ethnicity_mix
    model.ethnicity_white_pct = ethnicity_mix["White"]
    model.ethnicity_black_pct = ethnicity_mix["Black"]
    model.ethnicity_hispanic_pct = ethnicity_mix["Hispanic"]
    model.ethnicity_other_pct = ethnicity_mix["Other"]

def hourly_wage_for(person, rng=random):
    lo, hi = ANNUAL_INCOME_BANDS.get(person.wealth_class, (40_000, 80_000))
    annual = rng.uniform(lo, hi)
    return annual / (365.0 * 24.0)

def assign_vehicle(model, person, rng=random):
    """Set vehicle ownership once, based on wealth class and age."""
    if person.has_vehicle is not None:
        return person.has_vehicle
    base = VEHICLE_BASE_PROB.get(person.wealth_class, 0.70)
    if person.age >= 75:
        base -= 0.10
    base = max(0.10, min(0.95, base))
    person.has_vehicle = (rng.random() < base)
    return person.has_vehicle

def create_person_agents(model):
    """
    Create person agents, assign demographics and resources, then attach them to places.
    """
    from ._person import Person

    n = model.num_persons
    configure_population_mix(model)

    # Build wealth and ethnicity pools.
    model.num_upper_class_persons         = int(0.024 * n)
    model.num_upper_middle_class_persons  = int(0.204 * n)
    model.num_middle_class_persons        = int(0.446 * n)
    model.num_lower_class_persons         = n - (
        model.num_upper_class_persons
        + model.num_upper_middle_class_persons
        + model.num_middle_class_persons
    )

    model.wealth_classes = (
        ["Upper_Class"] * model.num_upper_class_persons
        + ["Upper_Middle_Class"] * model.num_upper_middle_class_persons
        + ["Middle_Class"] * model.num_middle_class_persons
        + ["Lower_Class"] * model.num_lower_class_persons
    )
    random.shuffle(model.wealth_classes)

    ethnicity_groups, ethnicity_counts = _build_label_pool_with_min_count(
        n,
        model.ethnicity_mix,
        rng=random,
        min_positive_count=model.min_ethnicity_group_size,
    )
    model.num_white_persons = int(ethnicity_counts.get("White", 0))
    model.num_black_persons = int(ethnicity_counts.get("Black", 0))
    model.num_hispanic_persons = int(ethnicity_counts.get("Hispanic", 0))
    model.num_other_ethnicity_persons = int(ethnicity_counts.get("Other", 0))

    # Counters and buckets.
    model.num_working_class_persons = 0
    model.num_age_0_14_persons = 0
    model.num_age_15_64_persons = 0
    model.num_age_65_100_persons = 0
    model.num_male_persons = 0
    model.num_female_persons = 0
    model.num_worldview_counts = {k: 0 for k in ["hierarchist", "egalitarian", "individualist", "fatalist"]}
    model.persons_by_wealth_class = {wc: [] for wc in {"Upper_Class","Upper_Middle_Class","Middle_Class","Lower_Class"}}

    gender_pool, _ = _build_label_pool(n, model.gender_mix)
    age_pool, _ = _build_label_pool(n, model.age_mix)
    worldview_pool, _ = _build_label_pool(n, model.worldview_mix)

    # Create people with a valid initial point.
    ac = mg.AgentCreator(Person, model=model, crs=model.space.crs)
    center = _fallback_center(model)
    persons = []
    for i in range(n):
        person = ac.create_agent(center)
        # Keep GeoSpace IDs globally unique.
        person.unique_id = f"person_{i}"
        persons.append(person)
    model.space.add_agents(persons)
    model.people = persons

    # Initialize model totals.
    model.persons_gdp = getattr(model, "persons_gdp", 0.0)
    model.total_gdp   = getattr(model, "total_gdp", 0.0)

    # Assign attributes to the created people.
    for i, person in enumerate(persons):
        assign_age(model, age_pool[i], person)
        assign_wealth_and_starting_cash(model, i, person)
        person.ethnicity = ethnicity_groups[i]
        assign_education(model, person)
        assign_gender(model, person, gender_pool[i])
        assign_worldview(model, person, worldview_pool[i])
        assign_working_class(model, person)
        assign_vulnerability(model, person)
    
        # Vehicle ownership is assigned once.
        assign_vehicle(model, person)
    
        model.persons_by_wealth_class[person.wealth_class].append(person)
        model.persons_gdp += person.income
        model.total_gdp   += person.income

    # Attach people to houses, businesses, and schools.
    assign_persons_to_houses(model)

    # Refresh physical vulnerability now that households are assigned.
    for p in model.people:
        if p.household:
            p.vulnerability_physical = float(1.0 - p.household.habitability())
            alpha = float(getattr(model, "vuln_social_weight", 0.6))
            p.vulnerability = alpha * p.vulnerability_social + (1.0 - alpha) * p.vulnerability_physical
        assign_endogenous_person_traits(p)

    assign_persons_to_businesses(model)
    assign_persons_to_schools(model)

# Helpers
def _fallback_center(model):
    tb = model.space.total_bounds
    if tb is None:
        return Point(0, 0)
    return Point((tb[0] + tb[2]) / 2, (tb[1] + tb[3]) / 2)


def assign_endogenous_person_traits(person):
    """Tie existing person traits to demographics and household context."""
    age = int(person.age)
    age_risk = 0.85 if age < 5 or age >= 75 else (0.60 if age < 15 or age >= 65 else 0.25)
    wealth_risk = {
        "Lower_Class": 0.85,
        "Middle_Class": 0.55,
        "Upper_Middle_Class": 0.30,
        "Upper_Class": 0.15,
    }.get(person.wealth_class, 0.55)
    education = max(0.0, min(1.0, float(person.education)))
    social_risk = max(0.0, min(1.0, float(person.vulnerability_social)))
    physical_risk = max(0.0, min(1.0, float(person.vulnerability_physical)))

    health_center = max(0.05, min(0.95, 0.35 * age_risk + 0.25 * wealth_risk + 0.15 * (1.0 - education) + 0.15 * social_risk + 0.10 * physical_risk))
    person.health_vulnerability = max(0.02, min(0.98, random.betavariate(max(1.0, health_center * 10.0), max(1.0, (1.0 - health_center) * 10.0))))

    mobility_center = max(0.55, min(1.10, 1.0 - 0.22 * age_risk - 0.12 * physical_risk))
    person.flood_resilience = max(1.0, min(20.0, 10.0 * random.uniform(mobility_center - 0.08, mobility_center + 0.08)))

    worldview = str(person.worldview)
    trust_center = max(0.10, min(0.90, 0.50 + (0.10 if worldview == "hierarchist" else -0.05 if worldview == "fatalist" else 0.0) + 0.08 * education - 0.08 * social_risk))
    for attribute, mean, std_dev in (
        ("social_trust", trust_center, 0.10),
        ("media_trust", 0.45 + 0.10 * education, 0.12),
        ("trust_in_authorities", trust_center, 0.12),
        ("self_efficacy", 0.45 + 0.20 * education - 0.15 * wealth_risk, 0.10),
        ("response_efficacy", 0.45 + 0.15 * education - 0.10 * physical_risk, 0.10),
    ):
        setattr(person, attribute, _clip01_gauss(mean, std_dev))
    person.self_efficacy_baseline = person.self_efficacy
    person.response_efficacy_baseline = person.response_efficacy


def assign_working_class(model, agent):
    if 18 <= agent.age <= 64:
        agent.working_class = True
        model.num_working_class_persons += 1

def assign_education(model, person):
    # Education in [0,1].
    if person.age >= 18:
        if random.uniform(0, 1) <= model.perc_education_people:
            person.education = 1.0  # high education
        else:
            person.education = random.uniform(0.5, 0.9)   # partial education
    else:
        # Scale with age for under-18.
        person.education = (0.4 / 18.0) * person.age

def assign_gender(model, person, gender=None):
    gender = gender or ("Male" if random.uniform(0, 1) <= 0.49 else "Female")
    person.gender = gender
    if gender == "Male":
        model.num_male_persons += 1
    else:
        model.num_female_persons += 1


def assign_worldview(model, person, worldview=None):
    worldview = worldview or random.choice(["hierarchist", "egalitarian", "individualist", "fatalist"])
    person.worldview = worldview
    model.num_worldview_counts[worldview] = int(model.num_worldview_counts.get(worldview, 0)) + 1


def assign_age(model, age_group, person):
    # Age groups follow the configured age mix.
    if age_group == "0_14":
        person.age = random.randint(0, 14)
        model.num_age_0_14_persons += 1
    elif age_group == "65_100":
        person.age = random.randint(65, 100)
        model.num_age_65_100_persons += 1
    else:
        person.age = random.randint(15, 64)
        model.num_age_15_64_persons += 1

def assign_wealth_and_starting_cash(model, i, person):
    person.wealth_class = model.wealth_classes[i]
    lo, hi = ANNUAL_INCOME_BANDS.get(person.wealth_class, (40_000, 80_000))
    annual = random.uniform(lo, hi)
    seed_mult = float(model.person_initial_cash_multiplier)
    weeks_min = float(model.person_initial_cash_weeks_min)
    weeks_max = float(model.person_initial_cash_weeks_max)
    if weeks_max < weeks_min:
        weeks_max = weeks_min
    person.income = (annual / 52.0) * random.uniform(weeks_min, weeks_max) * max(0.0, seed_mult)

def assign_vulnerability(model, agent):
    """
    Compute social vulnerability from bounded components, then blend it with physical vulnerability.
    """
    # Component risks.
    # Age (U-shaped risk)
    if agent.age < 5:           age_r = 0.90
    elif agent.age < 15:        age_r = 0.60
    elif agent.age < 65:        age_r = 0.25
    elif agent.age < 75:        age_r = 0.60
    else:                       age_r = 0.85

    # Education: higher education reduces risk.
    edu = float(agent.education)  # [0,1]
    edu_r = 1.0 - (edu ** 0.8)                            # gentle curve

    # Gender gap stays small.
    gen_r = 0.52 if agent.gender == "Male" else 0.58

    # Ethnicity is a modest proxy for access barriers.
    eth = agent.ethnicity
    eth_r = {"White": 0.50, "Black": 0.60, "Hispanic": 0.58, "Other": 0.55}.get(eth, 0.55)

    # Wealth class is the main driver.
    wc = agent.wealth_class
    w_r = {
        "Upper_Class":        0.15,
        "Upper_Middle_Class": 0.30,
        "Middle_Class":       0.55,
        "Lower_Class":        0.85,
    }.get(wc, 0.55)

    # Weighted geometric mean for social vulnerability.
    weights = getattr(model, "vuln_weights", {
        "age": 0.20, "education": 0.20, "gender": 0.10, "ethnicity": 0.15, "wealth": 0.35
    })
    comps = {"age": age_r, "education": edu_r, "gender": gen_r, "ethnicity": eth_r, "wealth": w_r}

    v_social = 1.0
    for k, v in comps.items():
        w = float(weights.get(k, 0.0))
        v_social *= max(1e-6, v) ** w        # weights sum to 1 → already a mean

    agent.vulnerability_social = float(v_social)

    # Physical vulnerability derives from house habitability when available.
    default_phys = getattr(model, "default_physical_vulnerability", 0.5)
    if agent.household:
        agent.vulnerability_physical = float(1.0 - agent.household.habitability())
    else:
        agent.vulnerability_physical = float(default_phys)

    # Blend social and physical vulnerability.
    alpha = float(getattr(model, "vuln_social_weight", 0.6))
    agent.vulnerability = alpha * agent.vulnerability_social + (1.0 - alpha) * agent.vulnerability_physical

    # Diagnostics used by exports.
    agent.svi_mean = agent.vulnerability_social  # for clarity in CSVs
    agent.svi_geom = agent.vulnerability_social  # geom == mean here by construction

def assign_persons_to_houses(model):
    houses = model.space.houses
    num_houses = len(houses)
    if num_houses == 0:
        return

    for _, persons in model.persons_by_wealth_class.items():
        persons_copy = persons[:]
        random.shuffle(persons_copy)
        houses_shuffled = random.sample(houses, num_houses)

        q, r = divmod(len(persons_copy), num_houses)
        sizes = [q + 1 if i < r else q for i in range(num_houses)]

        adults_available = [p for p in persons_copy if p.age >= 18]

        for house, k in zip(houses_shuffled, sizes):
            # Anchor one adult if possible.
            if k > 0 and adults_available:
                adult = None
                while adults_available and adult is None:
                    candidate = adults_available.pop()
                    if candidate in persons_copy:
                        adult = candidate

                if adult is not None:
                    persons_copy.remove(adult)
                    house.residents.append(adult)
                    adult.household = house
                    model.space.move_agent(adult, _random_point_in_polygon(house.geometry))
                    k -= 1

            for _ in range(k):
                if not persons_copy:
                    break
                resident = persons_copy.pop()
                house.residents.append(resident)
                resident.household = house
                model.space.move_agent(resident, _random_point_in_polygon(house.geometry))

        # Assign any leftovers to random houses.
        while persons_copy:
            resident = persons_copy.pop()
            house = random.choice(houses)
            house.residents.append(resident)
            resident.household = house
            model.space.move_agent(resident, _random_point_in_polygon(house.geometry))

def assign_persons_to_businesses(model):
    if not model.space.businesses:
        print("No businesses available for assignment.")
        return

    for _, persons in model.persons_by_wealth_class.items():
        for person in persons:
            if person.working_class and not person.employed:
                business = random.choice(model.space.businesses)
                business.employees.append(person)
                person.employed = True
                person.workplace = business

def assign_persons_to_schools(model):
    if not model.space.schools:
        print("No schools available for assignment.")
        return

    for _, persons in model.persons_by_wealth_class.items():
        for person in persons:
            if 5 <= person.age < 18 and not person.schoolplace:
                school = random.choice(model.space.schools)
                school.students.append(person)
                person.student = True
                person.schoolplace = school

# Geometry helper
def _random_point_in_polygon(poly):
    minx, miny, maxx, maxy = poly.bounds
    for _ in range(200):
        p = Point(random.uniform(minx, maxx), random.uniform(miny, maxy))
        if poly.contains(p):
            return p
    return poly.representative_point()