# Batch Execution Notes

The repository's primary execution path is local batch simulation. Each
scenario runner creates the requested replications, writes its results under
`outputs/`, and supports common controls for population size, replication
count, workers, random seed, output directory, and replication-folder cleanup.

## Local Execution

Run from the repository root:

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

The current model uses the single checked-in Uvalde study area. The runners
accept `--map uvalde` for compatibility, but there are no alternate maps.

Useful common options:

```text
--persons N              Number of person agents
--replications N         Number of simulation replications
--workers N              Parallel worker processes; 0 enables auto-detection
--seed-base N            Base seed for reproducible runs
--out-dir PATH           Override the default output directory
--keep-rep-folders       Keep per-replication folders after aggregation
```

Use `python run\<scenario>.py --help` for scenario-specific arguments and
defaults. `run_all_scenarios.ps1` is available for the configured all-scenario
batch workflow.

## Optional Remote Execution

The scenario runners retain an optional remote execution path for the lab's
HPC workflow. It is not required for local reproduction and depends on
external SSH credentials, network access, and the target machine's software
environment.

Example:

```powershell
python run\baseline.py --persons 300 --replications 10 --remote --gottlieb
```

Equivalent target selection is available through `--remote-target` with
`gottlieb`, `richardson`, or `hundsdorfer`. Remote credentials must be supplied
through the runner's runtime options or environment as appropriate; never
commit them to source control. Inspect the current runner help and
`run/support/common.py` before relying on remote behavior, since remote
execution is infrastructure-dependent.

## Results

Scenario results are stored under `outputs/<scenario>/`. Typical aggregated
files include time-series data and summary CSV files. Generated outputs are
ignored by Git and are not part of the source release.
