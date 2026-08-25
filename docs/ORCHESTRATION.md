# Batch Execution Notes

The primary reproducible execution path is local batch simulation. Each
scenario runner creates the requested replications, writes results under
`outputs/`, and shares the run controls documented below. The scenario
parameters themselves are catalogued in
[`scenario_default_tables.md`](scenario_default_tables.md), which is keyed to
the dictionaries and functions in `config/defaults.py`.

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
defaults. The root-level `run_all_scenarios.ps1` is a separate remote HPC
workflow, not a local equivalent of the commands above; see the next section.

## Remote HPC Workflow

The scenario runners retain optional remote flags, and
`run_all_scenarios.ps1` submits all eight scenarios through the lab's
SSH/Tuxworld jump-host workflow, waits for completion, downloads results, and
generates graphs. This is not required for local reproduction and depends on
external SSH credentials, network access, the configured key, and the target
machine's software environment.

The PowerShell suite defaults are independent of `config/defaults.py`:

```text
-Persons 500
-Replications 30
-Workers 4
-SeedBase 2684470948
-RemoteTarget gottlieb
```

Example runner-level remote invocation:

```powershell
python run\baseline.py --persons 300 --replications 10 --remote --gottlieb
```

Equivalent target selection is available through `--remote-target` with
`gottlieb`, `richardson`, or `hundsdorfer`. To use the all-scenario suite,
invoke `run_all_scenarios.ps1` with the desired PowerShell parameters. Remote
credentials must be supplied through the runner's runtime options or
environment as appropriate; never commit them to source control. Inspect the
current runner help and `run/support/common.py` before relying on remote
behavior, since remote execution is infrastructure-dependent.

## Results

Scenario results are stored under `outputs/<scenario>/`. Typical aggregated
files include time-series data and summary CSV files. Generated outputs are
ignored by Git and are not part of the source release.
