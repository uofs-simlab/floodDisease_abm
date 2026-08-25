# Flood-Disease ABM

This repository contains an agent-based model of flood and disease interactions at the household and community level. It uses Mesa for agent-based simulation and Mesa-Geo for spatial behavior. The current codebase includes separate scenario modes for baseline, flood-only, infectious disease, flood+mold, flood+vectorborne, flood+infectious disease, flood+mold+vectorborne, and compound runs.

---

## Project Layout

- **agents/**
  - `_person.py` – Person agent logic, including movement, health progression, and flood/disease decisions.
  - `_personAssign.py` – Builds the synthetic population and assigns people to houses, businesses, and schools.
  - Other agent classes live alongside these files.

- **model/**
  - `_model.py` – Core model logic, scenario configuration, hazard timing, and run coordination.

- **space/**
  - `_space.py` – GIS study area, hazard loading, stagnant pools, and agent relocation.

- **run/**
  - Scenario entry points for batch runs, shared support, and the interactive Solara server.

- **config/**
  - Shared scenario mappings, timeline defaults, population presets, and service defaults.

- **space/Uvalde_TX_map_data/**
  - Spatial data package for the active study area.

- **space/build/** and **space/cache/**
  - Local map-build artifacts and cached data kept with the spatial resources.

- **dataCollection/**
  - Data collection and export helpers.

- **analysis/**
  - Graph-generation scripts for the available scenario outputs.

- **.runtime/**
  - Local serverrun PID, lock, and log files. This directory is generated and ignored by Git.

### Naming conventions

- `model.shelters` and `model.healthcares` are the complete facility collections.
- `model.shelter` and `model.healthcare` are the primary facilities selected for service logic.
- `StudyArea` keeps the corresponding spatial collections under `shelter` and `healthcare` for compatibility with the GIS layer names.
- `agents._shelter.Shelter` is the single canonical shelter implementation; `from agents import Shelter` is only its public compatibility export.

---

## How to Run

1. Install dependencies:
   ```bash
  .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

2. Run a scenario script from the project root. For example:
   ```bash
  python full_compound.py --persons 300 --replications 10 --map uvalde
   ```

3. To launch the interactive server directly from the project root:
  ```powershell
  .\.venv\Scripts\solara.exe run .\run\serverrun.py
  ```

4. To launch the interactive server with the helper script and a chosen study area:
  ```powershell
  .\start_serverrun.ps1 -Map uvalde
  ```

5. To stop a server run:
  ```powershell
  .\stop_serverrun.ps1
  ```

6. The canonical Texas map name is `uvalde`. Do not use alternate aliases such as `uvalde_tx`.

### Uncertainty Monte Carlo runs

Batch runners always perform uncertainty sampling. They keep the Uvalde population, map, demographics, and scenario structure fixed while sampling calibrated behavioral, hazard, disease, service-capacity, and funding parameters independently for each seeded replication:

```powershell
python run\flood_vectorborne.py --persons 300 --replications 50 --seed-base 42
```

The sampled groups include flood severity and timing, evacuation and warning behavior, rescue delay, home safety, shelter and healthcare capacity, service funding, mold probability, vectorborne seeking/exposure/persistence, and infectious transmission/recovery. Triangular draws are used for bounded expert ranges, lognormal draws for positive funding amounts, and discrete draws for rescue delay. The exact sampled values are exported with each replication summary, while `summary_stats.csv` reports the mean, standard deviation, 5th/95th percentiles, quartiles, and 95% confidence interval for the replication mean.

Serverrun remains the deterministic interactive configuration surface: its explicit settings are passed directly to the model rather than sampled by the batch layer. The same batch seed base reproduces the same sampled parameter sets and outcomes.

## Configuration Notes

- Scenario behavior is controlled by `scenario_mode` and the hazard toggles in `model/_model.py`.
- Person assignment and demographic mixes are built in `agents/_personAssign.py`.
- Person movement, evacuation, sheltering, and post-flood return logic live in `agents/_person.py`.
- School mold behavior is generated from flood exposure, drying, building resilience, and repair state. Remaining school-specific controls describe consequences rather than mold initiation:
  - `school_repair_cost_multiplier`
  - `school_mold_attendance_penalty_rate`
- Flood scenario outputs now include `school_molded_pct` (percent of schools with active mold).

## Dependencies

Install the libraries listed in `requirements.txt`. The project depends on Mesa, Mesa-Geo, NumPy, Shapely, pandas, and the supporting analysis stack used by the scenario scripts.

## Outputs

Run outputs are written under `outputs/`, grouped by scenario and run id. The supported scenario folders include baseline, flood-only, infectious-disease, flood-mold, flood-vectorborne, flood-infectious, flood-mold-vectorborne, and full-compound runs.

## Further Reading

See [docs/ORCHESTRATION.md](docs/ORCHESTRATION.md), [docs/ORCHESTRATION_QUICK_REF.md](docs/ORCHESTRATION_QUICK_REF.md), and [docs/scenario_default_tables.md](docs/scenario_default_tables.md) for scenario execution, batch-run guidance, and shared defaults.

## License

This project is licensed under the MIT License. See `license.txt` for details.

---
