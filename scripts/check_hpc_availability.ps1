$Target = "all"
if ($args.Count -gt 0 -and $args[0] -in @("richardson", "hundsdorfer")) {
    $Target = $args[0]
}

$ErrorActionPreference = "Continue"

$sshKey = Join-Path $env:USERPROFILE ".ssh\id_ed25519_usask_hpc"
$jumpHost = "oaa721@tuxworld.usask.ca"
$remoteCheck = @'
hostname
date
uptime
nproc
echo CPU_TOPOLOGY
if command -v lscpu >/dev/null 2>&1; then lscpu | grep -E '^(CPU\(s\)|On-line CPU|Thread\(s\) per core|Core\(s\) per socket|Socket\(s\)|NUMA node\(s\))'; else echo Lscpu_UNAVAILABLE; fi
free -h
echo USER_PROCESSES
ps -u oaa721 -o pid,etime,pcpu,pmem,stat,comm --sort=-pcpu | head -10
echo SCHEDULER
if command -v squeue >/dev/null 2>&1; then squeue -u oaa721; elif command -v qstat >/dev/null 2>&1; then qstat -u oaa721; else echo SCHEDULER_UNAVAILABLE; fi
echo SENSITIVITY_SESSION
if tmux has-session -t sens_richardson_20261023T204821Z 2>/dev/null; then echo SESSION_ACTIVE; else echo SESSION_ABSENT; fi
echo SENSITIVITY_PROGRESS
if [ -f /scratch/oaa721/floodDisease_abm/outputs/sensitivity_analysis/compound_both_5000p_20261023T204821Z/_progress.json ]; then cat /scratch/oaa721/floodDisease_abm/outputs/sensitivity_analysis/compound_both_5000p_20261023T204821Z/_progress.json; else echo NO_PROGRESS_FILE; fi
echo PYTHON_ENVIRONMENTS
for py in python3 python3.12 python3.11 python3.10; do
    if command -v "$py" >/dev/null 2>&1; then
        echo "== $py =="
        "$py" --version
        "$py" -c "import ensurepip" >/dev/null 2>&1 && echo ENSUREPIP_AVAILABLE || echo ENSUREPIP_MISSING
        "$py" -m pip --version 2>&1 || true
    fi
done
if command -v virtualenv >/dev/null 2>&1; then
    virtualenv --version
else
    echo VIRTUALENV_UNAVAILABLE
fi
echo PROJECT_VENV
if [ -x .venv/bin/python ]; then
    .venv/bin/python --version
    .venv/bin/python -m pip --version 2>&1 || true
else
    echo PROJECT_VENV_MISSING
fi
if type module >/dev/null 2>&1; then
    module avail python 2>&1 | head -30
else
    echo MODULE_COMMAND_UNAVAILABLE
fi
echo VENV_SETUP_CAPABILITIES
python3 -m venv --without-pip --help >/dev/null 2>&1 && echo VENV_WITHOUT_PIP_SUPPORTED || echo VENV_WITHOUT_PIP_UNAVAILABLE
python3 -m pip --help 2>&1 | grep -q -- --python && echo PIP_TARGET_INTERPRETER_SUPPORTED || echo PIP_TARGET_INTERPRETER_UNAVAILABLE
'@
$remoteCheck = $remoteCheck -replace "`r`n", "`n"

$targetHosts = if ($Target -eq "all") { @("richardson", "hundsdorfer") } else { @($Target) }
foreach ($targetHost in $targetHosts) {
    Write-Host "`n=== $targetHost ==="
    & ssh `
        -i $sshKey `
        -o IdentitiesOnly=yes `
        -o BatchMode=no `
        -o ConnectTimeout=15 `
        -o ConnectionAttempts=1 `
        -J $jumpHost `
        "oaa721@$targetHost" `
        $remoteCheck

    if ($LASTEXITCODE -ne 0) {
        Write-Host "SSH check failed for $targetHost (exit code $LASTEXITCODE)."
    }
}
