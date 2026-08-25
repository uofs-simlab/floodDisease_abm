# Flood-Disease ABM

This repository contains an agent-based model of interactions among flooding,
infectious disease, mold, vectorborne disease, households, services, and the
local economy. The model uses Mesa and Mesa-Geo and currently runs against one
study area: Uvalde, Texas.

## Repository Layout

- `agents/`: person, household, business, government, school, shelter, and
  healthcare agents.
- `model/`: core model, flood processes, and disease processes.
- `space/`: GIS study-area loading and agent placement.
- `space/Uvalde_TX_map_data/`: active Uvalde spatial data and data-prep scripts.
- `run/`: batch scenario runners and the Solara interactive application.
- `config/`: shared defaults, scenario settings, and population presets.
- `dataCollection/`: model data collection and export helpers.
- `analysis/`: scenario graph-generation and paper-graph scripts.
- `docs/`: scenario defaults and execution notes.

Generated outputs, local environments, caches, and runtime logs are ignored by
Git. The checked-in spatial package contains the processed files used by the
model. Large raw download archives are intentionally kept out of the
repository.

## Setup

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Linux or macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

The repository includes `scripts/setup_lab_env.sh` as a convenience for
creating the environment on Linux or macOS.

## Interactive Application

The interactive Solara application uses the Uvalde study area and the checked-
in processed spatial data. From the project root, start it with:

```powershell
.\start_serverrun.ps1
```

The script starts the application at `http://127.0.0.1:8766`, opens the local
browser, and writes runtime logs under `.runtime/`. Stop it with:

```powershell
.\stop_serverrun.ps1
```

To start Solara directly without the helper script:

```powershell
.\.venv\Scripts\python.exe -m solara run run/serverrun.py
```

There is no map-selection workflow in the current application. Uvalde is the
only active runtime study area.

## Batch Scenarios

Run commands from the project root. The canonical entry points are in `run/`:

```powershell
python run\baseline.py --persons 300 --replications 10
python run\flood_only.py --persons 300 --replications 10
python run\infectious_disease.py --persons 300 --replications 10
python run\flood_mold.py --persons 300 --replications 10
python run\flood_vectorborne.py --persons 300 --replications 10
python run\flood_infectious.py --persons 300 --replications 10
python run\flood_mold_vectorborne.py --persons 300 --replications 10
python run\full_compound.py --persons 300 --replications 10
```

Use `--help` on a runner to see its available controls. Common options include
`--persons`, `--replications`, `--workers`, `--seed-base`, `--out-dir`, and
`--keep-rep-folders`. The runners use the Uvalde data by default; `--map
uvalde` remains accepted for compatibility, but there are no alternate maps.

The PowerShell helper `run_all_scenarios.ps1` runs the configured scenario set.
Outputs are written under `outputs/` and grouped by scenario and run size.
Those generated results are not committed to Git.

## Analysis

The scripts in `analysis/` generate graphs from scenario outputs. The paper
graph workflow and its configuration example are in
`analysis/graph_generation_for_paper/`.

## Spatial Data

The active flood layer is the checked-in Uvalde file
`space/Uvalde_TX_map_data/uvalde_twdb_scenario5_1in100_flood.geojson`.
Supporting spatial layers are in the same directory, including the processed
`abm_places.gpkg` and augmented house and school layers. See
`space/Uvalde_TX_map_data/README.md` for data provenance and optional
rebuilding steps.

## Documentation

- `docs/scenario_default_tables.md`: current shared and scenario defaults.
- `docs/ORCHESTRATION.md`: current local batch and optional remote-run notes.
- `space/Uvalde_TX_map_data/README.md`: Uvalde spatial data provenance.

## License

This project is licensed under the MIT License. See `license.txt` for details.
