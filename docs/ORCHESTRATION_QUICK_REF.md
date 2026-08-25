# Batch Run Quick Reference

Run commands from the project root. The active runtime study area is Uvalde,
Texas; no alternate maps are currently supported.

## Local Runs

```powershell
python run\baseline.py --persons 300 --replications 10
python run\flood_only.py --persons 300 --replications 10
python run\full_compound.py --persons 300 --replications 10
```

All scenario runners follow the same pattern. The available entry points are
`baseline`, `flood_only`, `infectious_disease`, `flood_mold`,
`flood_vectorborne`, `flood_infectious`, `flood_mold_vectorborne`, and
`full_compound`.

Common options:

```text
--persons N
--replications N
--workers N
--seed-base N
--out-dir PATH
--keep-rep-folders
```

Use `python run\<scenario>.py --help` for the complete interface. Results are
written under `outputs/` unless `--out-dir` is supplied.

## Optional Remote Runs

The runners also retain an optional SSH/HPC path. It is separate from the
normal local workflow and requires the user's own HPC access, SSH setup, and
remote environment:

```powershell
python run\baseline.py --persons 300 --replications 10 --remote --gottlieb
```

The `--gottlieb`, `--richardson`, and `--hundsdorfer` flags select the remote
target. Do not place passwords or private connection details in this
repository. Consult the runner's `--help` output and the implementation in
`run/support/common.py` before using remote execution.
