# Baseline Orchestration Guide

## Overview

The baseline runner now supports **full end-to-end orchestration** that automatically:

1. **Syncs** code to remote HPC (Gottlieb, Richardson, or Hundsdorfer)
2. **Launches** a remote batch run using the runner configuration
3. **Polls** remote progress automatically
4. **Downloads** all results back to local machine when complete
5. **Generates** diagnostic baseline graphs when the baseline runner completes successfully

No manual intervention needed—run once and get results automatically.

---

## Quick Start

### Local Run (No Orchestration)
```bash
python run/baseline.py --persons 350 --replications 12
```
Results go to: `outputs/baseline/baseline_350x12/`

### Remote Orchestrated Run (Full Pipeline)
```bash
python run/baseline.py --persons 350 --replications 12 --remote
```

That's it! The script will:
- ✅ Sync code to Gottlieb
- ✅ Launch 12 remote workers
- ✅ Poll remote progress until completion
- ✅ Auto-download when done
- ✅ Generate graphs automatically

Results go to: `outputs/baseline/baseline_350x12/` (local) + graphs in `baseline_graphs/` subdirectory

---

## CLI Arguments

### Basic Configuration
```
--persons N                    Number of agents (default: 300)
--replications N               Replication count (default: 10)
--seed-base N                  Base random seed (default: 42)
```

### Output Control
```
--out-dir PATH                 Custom output directory (default: outputs/baseline/baseline_<persons>x<replications>)
--keep-rep-folders             Keep replication folders (default: delete after aggregation)
```

### Orchestration Control
```
--remote                       Enable remote orchestration pipeline
--remote-target TARGET         HPC target: gottlieb, richardson, hundsdorfer (default: gottlieb)
--remote-user USER            HPC username (default: oaa721)
--remote-password PASS        HPC password supplied at runtime or through FLOODDISEASE_ABM_REMOTE_PASSWORD
--remote-repo NAME            Remote repo name (default: floodDisease_abm)
```

### Performance Control
```
--workers N                    Parallel local workers (default: 1)
--heartbeat-seconds N          Progress heartbeat interval (default: 60)
```

---

## Example Commands

### Standard Baseline (300×10, Gottlieb)
```bash
python run/baseline.py --persons 350 --replications 12 --remote
```

### Larger Run (700×12 replications, Richardson)
```bash
python run/baseline.py --persons 700 --replications 12 --remote \
  --remote-target richardson \
  --out-dir outputs/baseline/large_run
```

### Local Run Only (No Remote)
```bash
python run/baseline.py --persons 350 --replications 12 --workers 8
```

---

## Output Structure

After orchestration completes, outputs are organized as:
```
outputs/baseline/baseline_350x12/
├── timeseries_all_replications.csv     # Hourly time series for all reps
├── timeseries_quantiles.csv             # Quantiles (Q25, median, Q75) of hourly metrics
├── summary_by_replication.csv           # Summary stats per replication
├── summary_stats.csv                    # Aggregated stats (mean ± std)
├── baseline_graphs/                     # Generated diagnostic graphs
│   ├── wealth_trajectory.png
│   ├── quality_of_life.png
│   ├── infection_rate.png
│   ├── disease_severity.png
│   ├── hospitalizations.png
│   ├── business_operations.png
│   ├── healthcare_capacity.png
│   ├── housing_damage.png
│   ├── shelter_occupancy.png
│   ├── school_closures.png
│   ├── government_spending.png
│   ├── economic_recovery.png
│   ├── population_health.png
│   ├── infrastructure_status.png
│   ├── social_indicators.png
│   ├── behavioral_responses.png
│   ├── system_resilience.png
│   ├── recovery_timeline.png
│   └── comparative_analysis.png
└── _progress.json                       # Final progress snapshot (100% complete)
```

---

## Orchestration Pipeline Behavior

### Step 1: Sync & Launch (1-2 minutes)
- PowerShell script syncs code via SSH to Gottlieb
- Sets up Python environment if needed
- Launches 12 remote workers in tmux session

### Step 2: Polling
- Checks remote `_progress.json` at the configured polling interval
- Displays: `Progress: 12/12 (100%) elapsed=7m:45s eta=0s`
- Continues checking until 100% complete (or max 20 hours)

### Step 3: Download
- SFTP pulls the result files to local `outputs/baseline/`
- Shows: `[OK] Results pulled from gottlieb to .../baseline_350x12/`

### Step 4: Graph Generation (1-3 minutes)
- Subprocess call to `analysis/generate_baseline_graphs.py`
- Generates 19 diagnostic graphs into `baseline_graphs/` subfolder
- Shows: `[OK] Graphs generated in .../baseline_graphs/`

---

## Credential Handling

Credentials are supplied at runtime to the Paramiko-based orchestration helpers. Do not embed passwords in source files or documentation.

SSH connection flow:
```
Local Machine
  → [SSH via Paramiko] → tuxworld.usask.ca (proxy jump)
     → [SSH via tuxworld] → gottlieb.usask.ca (target HPC)
```

---

## Monitoring Progress

### Real-time Monitoring
Watch the console output:
```
[ORCHESTRATION] Starting remote baseline pipeline...
[1/4] Syncing code and launching remote batch run on gottlieb...
[OK] Remote run launched
[2/4] Polling remote progress (every 5 min)...
[1] Progress: 0/12 (0.0%) elapsed=0m:2s eta=0s
[2] Progress: 3/12 (25.0%) elapsed=5m:12s eta=16m:36s
[3] Progress: 6/12 (50.0%) elapsed=10m:15s eta=10m:15s
[4] Progress: 12/12 (100.0%) elapsed=7m:45s eta=0s
[OK] Remote run completed!
[3/4] Downloading results from gottlieb...
[OK] Results pulled from gottlieb to .../baseline_350x12/
[4/4] Generating baseline graphs...
[OK] Graphs generated in .../baseline_graphs/
[OK] Orchestration complete! Results in .../baseline_350x12/
```

### Manual Remote Check
If you want to SSH into the remote system and check progress:
```bash
ssh -J oaa721@tuxworld.usask.ca oaa721@gottlieb.usask.ca
cd /scratch-gladwell/oaa721/floodDisease_abm
tail -f outputs/baseline/baseline_350x12/_progress.json
```

---

## Troubleshooting

### Issue: SSH Connection Fails
**Symptom:** `[ERR] Could not launch remote run: ...`

**Solution:**
1. Confirm that the configured private key exists and display its public key when registering it with HPC support:
  ```powershell
  $key = "$env:USERPROFILE\.ssh\id_ed25519_usask_hpc"
  Test-Path $key
  Get-Content "$key.pub"
  ```
2. Test the same key and Tuxworld proxy used by the batch launcher. Replace `gottlieb` with `richardson` or `hundsdorfer` when needed:
  ```powershell
  $key = "$env:USERPROFILE\.ssh\id_ed25519_usask_hpc"
  $proxy = "ssh -i `"$key`" -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=20 -W %h:%p oaa721@tuxworld.usask.ca"
  ssh -i $key -o IdentitiesOnly=yes -o BatchMode=yes `
    -o ProxyCommand=$proxy oaa721@gottlieb "hostname; whoami"
  ```
3. Expected output is the target hostname and `oaa721`. If the result is `Permission denied (publickey,password)`, Tuxworld is reachable but the key is not authorized on the target HPC. Register the public key shown in step 1 for `oaa721` on that target; rerunning the batch command cannot repair target-side `authorized_keys`.
4. Run the batch command only after the direct test succeeds. The launcher repeats this preflight automatically before synchronization.

### Issue: No Progress Updates
**Symptom:** Polling shows `Could not read progress (may still be running)...` for 20+ minutes

**Possible causes:**
1. Remote model is running; duration depends on population, replications, workers, and HPC load
2. Progress file not written to expected location yet
3. Remote tmux session crashed

**Solution:**
1. Wait at least 10 minutes before concluding there's an issue
2. Manually SSH in and check: `ls -la outputs/baseline/baseline_350x12/`
3. Check tmux: `tmux ls` (on remote)

### Issue: SCP Download Hangs
**Symptom:** Stuck at `[3/4] Downloading results...` for >10 minutes

**Solution:**
1. Ctrl+C to cancel
2. Check available disk space: `df -h` (local) and remote `/scratch-gladwell/oaa721/` 
3. Retry the orchestration (it will overwrite incomplete files)

### Issue: Graph Generation Fails
**Symptom:** `[WARN] Graph generation had issues: ...`

**Solution:**
1. Verify the script exists: `ls analysis/generate_baseline_graphs.py`
2. Check if required packages (matplotlib, seaborn) are installed
3. Manually run graphs after run completes:
   ```bash
   python analysis/generate_baseline_graphs.py \
     --run-dir outputs/baseline/baseline_350x12 \
     --scenario baseline \
     --out-subdir baseline_graphs
   ```

---

## Future Scenarios

The orchestration utilities in `run/support/common.py` are shared by the scenario runners in `run/`:

```bash
# Example pattern for a new scenario runner:
python run/<scenario>.py --persons 350 --replications 12 --remote

# Example pattern for another scenario runner:
python run/<scenario>.py --persons 350 --replications 12 --remote
```

All scenario runners share the same SSH/SFTP/polling infrastructure from `run/support/common.py`.

---

## Technical Details

### Architecture
- **`run/support/common.py`**: Shared batch, aggregation, progress, and remote operation utilities
  - `check_remote_progress()` - SSH poll _progress.json
  - `pull_results_from_remote()` - SCP download results
  - `build_progress_snapshot()` - Format progress JSON

- **`run/baseline.py`**: Orchestration orchestrator
  - `orchestrate_remote_baseline()` - 4-step pipeline
  - `main()` - Checks `--remote` flag, routes to orchestration or local

- **`scripts/run_remote_batch_via_tux.ps1`**: PowerShell launcher (pre-existing)
  - Handles SSH sync and tmux session launch
  - Supports multiple HPC targets

### Exit Codes
- `0` - Success (orchestration completed)
- `1` - Failure (SSH, SCP, or orchestration error)

### Performance
- **Sync**: 1-2 min (git pull + env setup)
- **Remote Run**: depends on population, replications, workers, and HPC load
- **Polling**: 5-min intervals, auto-detects completion
- **Download**: 2-5 min (SCP pull ~1 GB data)
- **Graphs**: 1-3 min (19 plots, matplotlib rendering)

**Total time: ~20-30 minutes for end-to-end pipeline**

---

## FAQ

**Q: Can I run multiple orchestrations in parallel?**
A: Yes, each run creates its own unique output folder (`baseline_<persons>x<replications>`). Run multiple commands in separate terminals.

**Q: What if the remote run fails?**
A: The polling loop will time out after 20 hours. Check remote tmux session and logs, then retry.

**Q: Can I cancel an orchestration?**
A: Yes (Ctrl+C). The remote run will continue on Gottlieb. Restart the orchestration later and it will resume polling.

**Q: How do I view the baseline graphs?**
A: Open `outputs/baseline/baseline_350x12/baseline_graphs/wealth_trajectory.png` in any image viewer, or load the CSV files in Excel/Python.

**Q: Can I modify the multiplier without rerunning?**
A: Re-run with the desired model configuration and output directory.

---

## Summary

The orchestration system provides **fully automated end-to-end execution**: sync → run → poll → pull → graph. Perfect for:
- ✅ Overnight batch runs
- ✅ CI/CD pipelines
- ✅ Multiple HPC targets (Gottlieb, Richardson, Hundsdorfer)
- ✅ Minimal user intervention
- ✅ Reproducible baseline comparisons

Start with: `python run/baseline.py --persons 350 --replications 12 --remote`
