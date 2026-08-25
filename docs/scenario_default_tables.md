# Scenario Default Reference

This is the human-readable companion to
[`config/defaults.py`](../config/defaults.py). Parameter names in the tables
are the actual dictionary keys passed to `Model`; descriptions explain their
role in the current code. Change the Python dictionaries first, then update
this document. Values in runner files or model code that are not part of the
shared dictionaries are listed separately below.

## How Defaults Are Assembled

`MODEL_DEFAULTS` is a flat compatibility view composed from the Uvalde
population preset and the domain dictionaries below. `run/support/common.py`
adds run timeline values, source-file paths, Uvalde service funding/capacity,
and scenario-specific overrides before constructing a model. A caller's
explicit keyword arguments take precedence. Scenario selection changes which
systems run; it does not create a separate numeric parameter set.

## Run and Population Defaults

| Source key | Default | Meaning |
| --- | ---: | --- |
| `N_persons` | 500 | Number of person agents. |
| `baseline_days` | 7 | Baseline phase duration, in days. |
| `pre_flood_days` | 3 | Warning/pre-flood phase duration, in days. |
| `flood_days` | 7 | Active flood phase duration, in days. |
| `post_flood_days` | 22 | Post-flood recovery phase duration, in days. |
| `replications` | 10 | Batch replications when a runner is not overridden. |
| `seed_base` | 42 | Base used to derive reproducible replication seeds. |
| `male_share_pct` | 51.1 | Uvalde population preset. |
| `female_share_pct` | 48.9 | Uvalde population preset. |
| `age_0_14_pct` | 22.0 | Uvalde population preset. |
| `age_15_64_pct` | 60.8 | Uvalde population preset. |
| `age_65_100_pct` | 17.2 | Uvalde population preset. |
| `ethnicity_white_pct` | 17.5 | Uvalde population preset. |
| `ethnicity_black_pct` | 1.2 | Uvalde population preset. |
| `ethnicity_hispanic_pct` | 78.3 | Uvalde population preset. |
| `ethnicity_other_pct` | 3.0 | Uvalde population preset. |
| `perc_education_people` | 0.73 | Share used for education-related behavior. |
| `worldview_hierarchist_pct` | 25.0 | Worldview composition share. |
| `worldview_egalitarian_pct` | 25.0 | Worldview composition share. |
| `worldview_individualist_pct` | 25.0 | Worldview composition share. |
| `worldview_fatalist_pct` | 25.0 | Worldview composition share. |

## Service Defaults

Capacity limits are percentages of `N_persons`; the model converts them to
agent counts.

| Source key | Default | Meaning |
| --- | ---: | --- |
| `shelter_cap_limit` | 7.0 | Shelter capacity percentage. |
| `healthcare_cap_limit` | 7.0 | Healthcare capacity percentage. |
| `shelter_funding` | 50000 | Initial shelter funding. |
| `healthcare_funding` | 100000 | Initial healthcare funding. |

## Flood Defaults

| Source key | Default | Meaning |
| --- | ---: | --- |
| `flood_critical_facility_clearance_m` | 25.0 m | Clearance used when selecting critical facilities. |
| `flood_depth_multiplier` | 2.5 | Multiplier applied to source flood depth. |
| `flood_onset_speed` | 1.0 | Flood rise speed multiplier. |
| `flood_recession_speed` | 1.0 | Flood fall speed multiplier. |
| `house_flood_thresh_mult` | 0.90 | House flood threshold multiplier. |
| `biz_flood_thresh_mult` | 0.90 | Business flood threshold multiplier. |
| `school_flood_thresh_mult` | 0.90 | School flood threshold multiplier. |
| `pre_evac_T_gate` | 0.19 | Gate for pre-evacuation decisions. |
| `evac_trigger_depth_m` | 0.20 m | Depth that triggers evacuation pressure. |
| `home_unsafe_depth_m` | 0.30 m | Depth at which a home is unsafe. |
| `warning_pre_flood_base` | 0.35 | Baseline official warning strength. |
| `stranded_depth_tolerance_mult` | 0.05 | Relative tolerance before route stranding. |
| `injury_risk_scale` | 1.5 | Flood injury-risk multiplier. |
| `hours_before_rescue` | 6 | Rescue delay in hours. |
| `flood_wave_enabled` | true | Enables directional flood-wave handling. |
| `flood_wave_direction` | southwest_to_northeast | Direction of the wave. |
| `flood_wave_rise_hours` | 0.0 | Additional wave-rise duration. |
| `flood_wave_fall_hours` | 0.0 | Additional wave-fall duration. |

## Infectious Disease Defaults

| Source key | Default | Meaning |
| --- | ---: | --- |
| `infectious_seed_share` | 0.01 | Share seeded as infected. |
| `infectious_beta_base` | 0.008 | Base hourly transmission probability. |
| `infectious_gamma` | 0.0167 | Hourly recovery probability. |
| `infectious_waning` | 0.0 | Hourly loss-of-immunity probability. |
| `infectious_contact_intensity` | 0.02 | Contact/transmission intensity. |
| `infectious_severity_scale` | 1.20 | Disease severity multiplier. |
| `infectious_mortality_hazard` | 0.03 | Hourly mortality hazard before modifiers. |
| `infectious_course_hours` | 50 | Disease-course duration control. |
| `infectious_peak_hours` | 55 | Peak infectiousness timing control. |
| `injury_hospital_recovery_boost` | 3.0 | Recovery boost for injured hospitalized people. |
| `infectious_threat_coupling` | 0.0 | Coupling from infectious threat to behavior. |
| `infectious_seed_start_hour` | 200 | Infection-only seed start before scenario derivation. |

## Mold, Vectorborne, and Economic Defaults

| Group | Source key | Default | Meaning |
| --- | --- | ---: | --- |
| Mold | `damp_half_life_h` | 20.0 h | Dampness half-life. |
| Mold | `damp_resilience_effect` | 0.8 | Resilience reduction of dampness effects. |
| Mold | `damp_done_threshold` | 0.15 | Dampness completion threshold. |
| Mold | `damp_metric_hours` | 30.0 h | Dampness metric window. |
| Mold | `school_repair_cost_multiplier` | 0.5 | School mold repair-cost multiplier. |
| Mold | `school_mold_attendance_penalty_rate` | 0.15 | School attendance penalty rate. |
| Mold | `mold_symptom_threshold` | 0.15 | Dampness level for symptoms. |
| Mold | `mold_functional_capacity` | 0.70 | Functional capacity during mold effects. |
| Mold | `mold_hospital_seek_prob` | 0.01 | Probability of seeking care. |
| Mold | `mold_healthcare_cost_multiplier` | 0.252 | Mold-care cost multiplier. |
| Mold | `house_mold_rate` | 0.30 | House mold rate. |
| Mold | `business_mold_rate` | 0.50 | Business mold rate. |
| Vectorborne | `stagnant_half_life_h` | 96.0 h | Stagnant-water hazard half-life. |
| Vectorborne | `stagnant_influence_m` | 125.0 m | Exposure influence radius. |
| Vectorborne | `stagnant_max_spots_per_wave` | 7 | Maximum retained spots per wave. |
| Vectorborne | `stagnant_max_source_polygons` | 20 | Maximum source polygons. |
| Vectorborne | `stagnant_area_fraction` | 0.005 | Area fraction used for stagnant water. |
| Vectorborne | `vector_control_intensity` | 0.0 | Vector-control intervention intensity. |
| Vectorborne | `stagnant_keep_fraction` | 0.60 | Fraction of stagnant pools retained. |
| Vectorborne | `vector_hospital_seek_prob` | 0.02 | Probability of seeking vectorborne care. |
| Vectorborne | `vector_exposure_hazard` | 0.05 | Exposure-to-infection hazard. |
| Vectorborne | `vector_functional_capacity` | 0.75 | Functional capacity during vector illness. |
| Vectorborne | `healthcare_max_stay_hours` | 100 | Maximum vector-care stay control. |
| Vectorborne | `vector_healthcare_cost_multiplier` | 0.351 | Vector-care cost multiplier. |
| Vectorborne | `stagnant_lifetime_min_h` | 72.0 h | Minimum stagnant-pool lifetime. |
| Vectorborne | `stagnant_lifetime_max_h` | 120.0 h | Maximum stagnant-pool lifetime. |
| Vectorborne | `stagnant_shrink_min` | 3.0 | Minimum pool shrink control. |
| Vectorborne | `stagnant_shrink_max` | 12.0 | Maximum pool shrink control. |
| Vectorborne | `stagnant_min_area` | 80.0 | Minimum retained pool area. |
| Vectorborne | `stagnant_simplify_tolerance` | 2.0 | Geometry simplification tolerance. |
| Economy | `sales_tax_rate` | 0.05 | Sales tax rate. |
| Economy | `corporate_tax_rate` | 0.16 | Corporate tax rate. |
| Economy | `income_tax_rate` | 0.12 | Income tax rate. |
| Economy | `sales_revenue_multiplier` | 3.80 | Sales revenue multiplier. |
| Economy | `business_revenue_staffing_floor` | 0.20 | Minimum staffing-based revenue fraction. |
| Economy | `business_revenue_staffing_elasticity` | 1.6 | Revenue response to staffing. |
| Economy | `person_initial_cash_multiplier` | 1.0 | Initial person cash multiplier. |
| Economy | `person_initial_cash_weeks_min` | 0.5 | Minimum initial cash weeks. |
| Economy | `person_initial_cash_weeks_max` | 1.5 | Maximum initial cash weeks. |
| Economy | `person_wealth_reference_population` | 300.0 | Population reference for wealth scaling. |
| Economy | `evacuation_cost_scale` | 0.25 | Person evacuation cost scale. |
| Economy | `preparation_cost_scale` | 0.25 | Preparation cost scale. |
| Economy | `business_wage_cost_share` | 0.20 | Business wage-cost share. |
| Economy | `patient_healthcare_cost_multiplier` | 0.02 | General patient-care cost multiplier. |
| Economy | `business_repair_cost_multiplier` | 0.75 | Business repair-cost multiplier. |
| Economy | `house_repair_cost_scale` | 0.10 | House repair-cost scale. |
| Economy | `house_repair_attempt_scale` | 0.25 | House repair-attempt scale. |
| Economy | `business_initial_wealth_factor` | 2.80 | Initial business wealth factor. |
| Economy | `government_initial_wealth_factor` | 3.0 | Initial government wealth factor. |
| Economy | `business_close_penalty_rate` | 0.5 | Closure penalty rate. |
| Economy | `business_close_penalty_min` | 3000.0 | Minimum closure penalty. |
| Economy | `business_closed_hourly_burn_rate` | 0.50 | Hourly closed-business burn. |
| Economy | `business_mold_ops_penalty_rate` | 0.05 | Mold operations penalty. |
| Economy | `person_income_growth_scale` | 0.50 | Person income-growth scale. |
| Economy | `business_annual_output_per_person` | 22000.0 | Annual business output per person. |
| Economy | `school_annual_output_per_person` | 1200.0 | Annual school output per person. |
| Economy | `shelter_annual_output_per_person` | 4200.0 | Annual shelter output per person. |
| Economy | `healthcare_annual_output_per_person` | 4200.0 | Annual healthcare output per person. |
| Economy | `government_annual_output_per_person` | 7000.0 | Annual government output per person. |
| Economy | `gdp_allocation_days` | 14 | GDP allocation window. |
| Economy | `house_repair_base_cost` | 125.0 | Base house repair cost. |
| Economy | `repair_cost_variation` | 0.20 | Repair-cost variation. |
| Economy | `shelter_operating_cost_per_person_max` | 50.0 | Maximum shelter operating cost per person. |

## Behavior, Decisions, Care, and Structure

| Group | Source key | Default | Meaning |
| --- | --- | ---: | --- |
| Behavior | `during_route_max_depth_m` | 0.3 m | Maximum route depth tolerated. |
| Behavior | `decision_interval_hours` | 6 | Main decision cadence. |
| Behavior | `return_decision_interval_hours` | 6 | Return-home decision cadence. |
| Behavior | `social_evac_signal_scale` | 0.35 | Social signal contribution to evacuation. |
| Behavior | `home_depth_tol_m` | 0.20 m | Home depth tolerance. |
| Behavior | `work_depth_tol_m` | 0.25 m | Work depth tolerance. |
| Behavior | `school_depth_tol_m` | 0.20 m | School depth tolerance. |
| Behavior | `public_space_depth_tol_m` | 0.15 m | Public-space depth tolerance. |
| Behavior | `entity_inside_depth_share` | 1.00 | Share of entity depth used indoors. |
| Behavior | `home_habit_thresh` | 0.50 | Home-habit threshold. |
| Behavior | `person_resilience_min` | 5.0 | Minimum person resilience. |
| Behavior | `person_resilience_max` | 15.0 | Maximum person resilience. |
| Behavior | `random_move_radius_m` | 400 | Random movement radius. |
| Behavior | `min_ethnicity_group_size` | 3 | Minimum group size for ethnicity effects. |
| Decision | `decision_w_depth` | 0.40 | Depth weight. |
| Decision | `decision_w_imminence` | 0.15 | Imminence weight. |
| Decision | `decision_w_official` | 0.12 | Official-warning weight. |
| Decision | `decision_w_social` | 0.08 | Social-signal weight. |
| Decision | `decision_w_memory` | 0.05 | Memory weight. |
| Decision | `decision_w_disease` | 0.20 | Disease-threat weight. |
| Decision | `decision_a_self` | 0.40 | Self-efficacy coefficient. |
| Decision | `decision_a_response` | 0.30 | Response-efficacy coefficient. |
| Decision | `decision_a_social` | 0.20 | Social-efficacy coefficient. |
| Decision | `decision_a_cost` | 0.30 | Cost coefficient. |
| Decision | `decision_beta0` | -1.4 | Evacuation intercept. |
| Decision | `decision_beta_threat` | 1.7 | Evacuation threat coefficient. |
| Decision | `decision_beta_coping` | 1.0 | Evacuation coping coefficient. |
| Decision | `decision_beta0_prepare` | -1.0 | Preparation intercept. |
| Decision | `decision_beta_threat_prepare` | 1.5 | Preparation threat coefficient. |
| Decision | `decision_beta_coping_prepare` | 0.5 | Preparation coping coefficient. |
| Decision | `decision_gamma0` | -1.5 | Return intercept. |
| Decision | `decision_gamma_habitability` | 2.5 | Return habitability coefficient. |
| Decision | `decision_gamma_coping` | 1.0 | Return coping coefficient. |
| Healthcare | `healthcare_transfer_speed_mps` | 8.0 | Healthcare transport speed. |
| Healthcare | `healthcare_turnaround_minutes` | 20.0 | Healthcare turnaround time. |
| Healthcare | `healthcare_base_admit_cost` | 120.0 | Base admission cost. |
| Healthcare | `healthcare_km_cost` | 2.0 | Healthcare distance cost. |
| Healthcare | `healthcare_hazard_radius_m` | 300.0 | Healthcare hazard radius. |
| Healthcare | `healthcare_max_wait_hours_cap` | 12.0 | Maximum healthcare wait cap. |
| Healthcare | `healthcare_hospital_recovery_boost` | 2.5 | Hospital recovery boost. |
| Healthcare | `healthcare_self_present_fee` | 40.0 | Self-presentation fee. |
| Healthcare | `hc_ready_discharge_wait_hours` | 72 | Discharge wait before placement. |
| Healthcare | `shelter_rescue_speed_mps` | 8.33 | Shelter rescue speed. |
| Healthcare | `shelter_turnaround_minutes` | 20.0 | Shelter turnaround time. |
| Healthcare | `shelter_km_cost` | 1.0 | Shelter distance cost. |
| Healthcare | `shelter_base_pickup_cost` | 10.0 | Base pickup cost. |
| Healthcare | `shelter_max_wait_hours_cap` | 12.0 | Maximum shelter wait cap. |
| Structure | `structure_flood_on_margin` | 1.00 | Hysteresis flood-on margin. |
| Structure | `structure_flood_off_margin` | 0.90 | Hysteresis flood-off margin. |
| Structure | `structure_cleanup_base_hours` | 2.0 | Base cleanup duration. |
| Structure | `structure_cleanup_depth_hours` | 6.0 | Depth contribution to cleanup. |
| Structure | `structure_cleanup_resilience_divisor` | 10.0 | Resilience divisor for cleanup. |
| Structure | `structure_cleanup_max_hours` | 72 | Cleanup duration cap. |
| Structure | `structure_repair_base_cost` | 60.0 | Base structure repair cost. |
| Structure | `structure_repair_depth_cost` | 180.0 | Depth-dependent repair cost. |
| Structure | `structure_repair_intensity_scale` | 1.5 | Repair intensity scale. |
| Structure | `structure_repair_variation_min` | 0.70 | Minimum repair variation. |
| Structure | `structure_repair_variation_max` | 1.45 | Maximum repair variation. |
| Structure | `structure_mold_duration_base_hours` | 168.0 | Base mold duration. |
| Structure | `structure_mold_duration_intensity_hours` | 84.0 | Mold-duration intensity contribution. |

## Geometry, Policy, and Stochasticity

| Group | Source key | Default | Meaning |
| --- | --- | ---: | --- |
| Geometry | `flood_clip_padding_m` | 250.0 m | Flood geometry clip padding. |
| Geometry | `flood_simplify_tolerance_m` | 10.0 m | Flood geometry simplification. |
| Geometry | `flood_max_visual_polygons` | 20 | Maximum visual flood polygons. |
| Geometry | `flood_depth_default_m` | 0.60 m | Fallback flood depth. |
| Geometry | `flood_depth_variation_m` | 0.15 m | Flood-depth variation. |
| Policy | `wash_intensity` | 0.0 | Wash intervention intensity. |
| Policy | `shelter_distancing_intensity` | 0.0 | Shelter distancing intervention. |
| Policy | `healthcare_surge_factor` | 0.0 | Healthcare surge intervention. |
| Policy | `repair_subsidy_intensity` | 0.0 | Repair subsidy intervention. |
| Policy | `risk_communication_intensity` | 0.0 | Risk-communication intervention. |
| Policy | `targeted_protection_intensity` | 0.0 | Targeted protection intervention. |
| Policy | `gov_baseline_grant_every_hours` | 24 | Government grant cadence. |
| Policy | `psych_efficacy_hazard_gain_self` | 0.30 | Self-efficacy hazard gain. |
| Policy | `psych_efficacy_hazard_gain_response` | 0.35 | Response-efficacy hazard gain. |
| Policy | `psych_efficacy_adapt_rate` | 0.10 | Efficacy adaptation rate. |
| Policy | `psych_efficacy_decay_rate` | 0.04 | Efficacy decay rate. |
| Policy | `psych_symptom_pressure` | 0.70 | Symptom pressure on behavior. |
| Policy | `institutional_procurement_pass_through` | 0.35 | Procurement pass-through. |
| Policy | `gov_baseline_share_shelter` | 0.01 | Baseline grant share for shelter. |
| Policy | `gov_baseline_share_healthcare` | 0.03 | Baseline grant share for healthcare. |
| Policy | `gov_baseline_share_school` | 0.01 | Baseline grant share for schools. |
| Policy | `gov_event_shelter_grant_scale` | 100.0 | Event shelter grant scale. |
| Policy | `gov_event_healthcare_grant_scale` | 250.0 | Event healthcare grant scale. |
| Stochasticity | `stochasticity_level` | 0.05 | Overall stochastic variation level. |
| Stochasticity | `decision_jitter_rel` | 0.05 | Relative decision jitter. |
| Stochasticity | `threshold_jitter_rel` | 0.03 | Relative threshold jitter. |
| Stochasticity | `health_jitter_rel` | 0.05 | Relative health jitter. |
| Stochasticity | `mobility_jitter_rel` | 0.04 | Relative mobility jitter. |
| Stochasticity | `survivability_duration_scale` | 1 | Survivability duration scale. |
| Stochasticity | `stranded_mortality_rate_scale` | 0.001 | Stranded mortality rate scale. |
| Stochasticity | `stranded_mortality_hazard_threshold` | 1 | Stranded mortality hazard threshold. |
| Stochasticity | `stranded_mortality_prob_cap` | 0.001 | Cap on stranded mortality probability. |

## Scenario Selection and Derived Values

`SCENARIO_FLAGS` supplies these switches. A flag set to `false` disables the
corresponding process; numeric defaults remain shared across scenarios.

| Scenario | Flood | Infectious | Stagnant/vectorborne | Mold |
| --- | --- | --- | --- | --- |
| `baseline` | off | off | off | off |
| `flood_only` | on | off | off | off |
| `infectious_disease` | off | on | off | off |
| `flood_mold` | on | off | off | on |
| `flood_vectorborne` | on | off | on | off |
| `flood_mold_vectorborne` | on | off | on | on |
| `flood_infectious` | on | on | off | off |
| `compound` | on | on | on | on |

`infectious_start_hour()` derives the infectious seed time. For
`flood_infectious` and `compound` it is
`(baseline_days + pre_flood_days + flood_days + 2) * 24`; with current defaults
that is hour 464. For `infectious_disease` it is 200. Other scenarios use 0.
The scenario label/code maps and the `compound` fallback are also defined in
`config/defaults.py`.

## Values Outside `config/defaults.py`

These are runtime or interface defaults and should not be confused with model
calibration defaults:

| Location | Value | Meaning |
| --- | --- | --- |
| `run` argparse | `--workers 1` or runner-specific value | Parallel worker default; inspect the selected runner. |
| `run` argparse | `--heartbeat-seconds 60` | Progress heartbeat interval. |
| `run` argparse | `--map uvalde` | Compatibility argument; no alternate map exists. |
| `run/support/common.py` | `EPSG:3857` | Model CRS passed with Uvalde data. |
| `run/support/common.py` | Uvalde source paths | Required processed GPKG and active flood GeoJSON. |
| `run/serverrun.py` | port 8766, host 127.0.0.1 | Interactive server defaults. |
| `run/serverrun.py` | population UI max 30000, step 100 | Interactive control range, not a model default. |
| `run_all_scenarios.ps1` | 500 persons, 30 replications, 4 workers | Remote suite defaults. |
| `run_all_scenarios.ps1` | seed `2684470948` | Remote suite seed base. |
| `run_all_scenarios.ps1` | target `gottlieb` | Remote suite target default. |

Runner CLI options include `--persons`, `--house-mold-rate`,
`--business-mold-rate`, timeline overrides, `--replications`, `--workers`,
`--heartbeat-seconds`, `--seed-base`, `--map`, `--out-dir`,
`--keep-rep-folders`, and optional remote target flags. `full_compound.py`
also accepts `--gov-baseline-grant-every-hours`. Run a selected runner with
`--help` for its exact interface.

## Data and Interpretation Notes

All current runs resolve to the Uvalde data under
`space/Uvalde_TX_map_data/`. Flood depth is based on the checked-in TWDB
scenario layer and a conceptual rise/recession envelope, not a time-resolved
hydraulic simulation. Batch results are aggregated into summary and
time-series CSV files under `outputs/`; graph scripts consume those outputs.
