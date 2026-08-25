# Baseline Orchestration - Quick Reference

## Start Here

```bash
# Local run
python run/baseline.py --persons 350 --replications 12

# Remote orchestrated
python run/baseline.py --persons 350 --replications 12 --remote
```

## What --remote Does

Automatically:
1. **Syncs** code to Gottlieb HPC
2. **Launches** remote batch (12 workers)
3. **Polls** progress until completion
4. **Downloads** results when complete
5. **Generates** 19 diagnostic graphs

Zero user intervention needed after starting.

## Output Locations

| Mode | Results | Graphs |
|------|---------|--------|
| Local | `outputs/baseline/baseline_350x12/` | ❌ (use --remote) |
| Remote | `outputs/baseline/baseline_350x12/` | ✅ `baseline_graphs/` |

## Key Options

| Option | Default | Example |
|--------|---------|---------|
| `--persons` | 300 | `--persons 350` |
| `--replications` | 10 | `--replications 12` |
| `--remote-target` | gottlieb | `--remote-target richardson` |
| `--out-dir` | auto | `--out-dir outputs/baseline/custom_run` |

## Remote Access

Remote orchestration uses the configured SSH/Paramiko connection through the selected HPC target. Supply credentials at runtime; do not commit credentials to documentation or source control.

## Expected Output

```
[ORCHESTRATION] Starting remote baseline pipeline...
[1/4] Syncing code and launching remote batch run on gottlieb...
[OK] Remote run launched
[2/4] Polling remote progress (every 5 min)...
[1] Progress: 3/12 (25.0%) elapsed=5m:12s eta=16m:36s
[2] Progress: 6/12 (50.0%) elapsed=10m:15s eta=10m:15s
[3] Progress: 12/12 (100.0%) elapsed=7m:45s eta=0s
[OK] Remote run completed!
[3/4] Downloading results from gottlieb...
[OK] Results pulled from gottlieb to .../baseline_350x12/
[4/4] Generating baseline graphs...
[OK] Graphs generated in .../baseline_graphs/
[OK] Orchestration complete!
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| SSH fails | Check: `ping tuxworld.usask.ca` |
| No progress | Wait 10+ min (polling only every 5 min) |
| Download hangs | Ctrl+C and retry |
| Graphs fail | Check: `python analysis/generate_baseline_graphs.py --help` |

## Full Documentation

See [ORCHESTRATION.md](ORCHESTRATION.md) for detailed guide, examples, and troubleshooting.

## Common Commands

```bash
# Standard baseline run to Gottlieb
python run/baseline.py --persons 300 --replications 10 --remote --remote-password "$env:FLOODDISEASE_ABM_REMOTE_PASSWORD"

# To Richardson instead
python run/baseline.py --persons 350 --replications 12 --remote --remote-target richardson

# Local only (no remote, no graphs)
python run/baseline.py --persons 350 --replications 12

# Local with parallel workers
python run/baseline.py --persons 350 --replications 12 --workers 8
```

## Pipeline Timing

- Sync + Launch: 1-2 min
- Remote Run: depends on population, replications, workers, and HPC load
- Polling Loops: ~5 min (2-3 checks)
- Download: 2-5 min
- Graphs: 1-3 min

**Total: ~20-30 min**

---

For full details, see [ORCHESTRATION.md](ORCHESTRATION.md)
