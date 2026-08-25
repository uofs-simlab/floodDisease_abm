param(
    [string]$TuxUser = "oaa721",
    [string]$TuxHost = "tuxworld.usask.ca",
    [ValidateSet("hundsdorfer", "richardson", "gottlieb")]
    [string]$Target = "hundsdorfer",
    [string]$TargetUser = "oaa721",
    [string]$TargetHost = "",
    [string]$RemoteRepo = "",
    [string]$SessionName = "flood_batch",
    [string]$SshKey = (Join-Path $env:USERPROFILE ".ssh\id_ed25519_usask_hpc"),
    [string]$BatchArgs = "--persons 300 --replications 30 --workers 0 --out-dir outputs/scenario_runs_hpc --seed-base 42",
    [ValidateSet("compare", "baseline", "infectious_disease", "flood_only", "flood_mold", "flood_vectorborne", "flood_mold_vectorborne", "flood_infectious", "full_compound")]
    [string]$Runner = "compare",
    [switch]$KillExistingSession
)

$ErrorActionPreference = "Stop"

function ConvertTo-BashSingleQuoted {
    param([string]$Value)
    return "'" + ($Value -replace "'", '''"''"''') + "'"
}

$targetLower = $Target.ToLowerInvariant()
if ([string]::IsNullOrWhiteSpace($TargetHost)) {
    switch ($targetLower) {
        "hundsdorfer" { $TargetHost = "hundsdorfer" }
        "richardson" { $TargetHost = "richardson" }
        "gottlieb" { $TargetHost = "gottlieb" }
    }
}

if ([string]::IsNullOrWhiteSpace($RemoteRepo)) {
    switch ($targetLower) {
        "hundsdorfer" { $RemoteRepo = "/scratch/$TargetUser/floodDisease_abm" }
        "richardson" { $RemoteRepo = "/scratch/$TargetUser/floodDisease_abm" }
        "gottlieb" { $RemoteRepo = "/scratch-gladwell/$TargetUser/floodDisease_abm" }
    }
}

$proxyJump = "${TuxUser}@${TuxHost}"
$proxyCommand = "ssh -i `"$SshKey`" -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=20 -W %h:%p $proxyJump"
$sshOptions = @("-i", $SshKey, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20")
$runScript = if ($Runner -eq "baseline") {
    "scripts/run_lab_baseline.sh"
} elseif ($Runner -eq "infectious_disease") {
    "scripts/run_lab_infectious_disease.sh"
} elseif ($Runner -eq "flood_only") {
    "scripts/run_lab_flood_only.sh"
} elseif ($Runner -eq "flood_mold") {
    "scripts/run_lab_flood_mold.sh"
} elseif ($Runner -eq "flood_vectorborne") {
    "scripts/run_lab_flood_vectorborne.sh"
} elseif ($Runner -eq "flood_infectious") {
    "scripts/run_lab_flood_infectious.sh"
} elseif ($Runner -eq "flood_mold_vectorborne") {
    "scripts/run_lab_flood_mold_vectorborne.sh"
} elseif ($Runner -eq "full_compound") {
    "scripts/run_lab_full_compound.sh"
} else {
    "scripts/run_lab_batch.sh"
}
$remoteScript = @"
set -euo pipefail
if [ ! -d "$RemoteRepo" ]; then
    echo "[ERR] Remote repository directory does not exist: $RemoteRepo" >&2
    exit 1
fi
cd "$RemoteRepo"
if [ ! -f .venv/bin/activate ]; then
    bash scripts/setup_lab_env.sh
fi
if ! .venv/bin/python -m pip check >/dev/null 2>&1; then
    echo "[ENV] Existing .venv has broken or missing declared dependencies - reinstalling requirements."
    bash scripts/setup_lab_env.sh
else
    echo "[ENV] Existing .venv satisfies declared requirements (pip check)."
fi
source scripts/activate_project_env.sh
"@

if ($KillExistingSession) {
    $remoteScript += "`ntmux kill-session -t `"$SessionName`" 2>/dev/null || true`n"
}

$tmuxCommand = 'set +e; echo ''[RUN] Starting ' + $runScript + '''; bash ' + $runScript + ' ' + $BatchArgs + ' > outputs/logs/' + $SessionName + '.launcher.log 2>&1; status=$?; printf ''%s\n'' "$status" > outputs/logs/' + $SessionName + '.status.tmp; mv -f outputs/logs/' + $SessionName + '.status.tmp outputs/logs/' + $SessionName + '.status; tmux kill-session -t ' + $SessionName + ' 2>/dev/null || true; exit "$status"'
$tmuxCommandBytes = [System.Text.Encoding]::UTF8.GetBytes($tmuxCommand)
$tmuxCommandBase64 = [Convert]::ToBase64String($tmuxCommandBytes)
$remoteScript += @"
mkdir -p outputs/logs
rm -f "outputs/logs/${SessionName}.status"
tmux new-session -d -s "$SessionName"
tmux send-keys -t "$SessionName" "echo $tmuxCommandBase64 | base64 -d | bash" C-m
if tmux has-session -t "$SessionName" 2>/dev/null; then
    echo "[RUN] Session active: $SessionName"
fi
"@

$remoteScript = $remoteScript -replace "`r`n", "`n"
$remoteScriptBytes = [System.Text.Encoding]::UTF8.GetBytes($remoteScript)
$remoteScriptBase64 = [Convert]::ToBase64String($remoteScriptBytes)
$remoteCommand = "echo $remoteScriptBase64 | base64 -d | bash"
$remoteCommandLiteral = ConvertTo-BashSingleQuoted $remoteCommand

Write-Host "[RUN] Target     : $targetLower"
Write-Host "[RUN] Remote repo: ${TargetUser}@${TargetHost}:$RemoteRepo"
Write-Host "[RUN] Session    : $SessionName"
Write-Host "[RUN] Runner     : $Runner"
Write-Host "[RUN] Args       : $BatchArgs"

ssh @sshOptions -t -o "ProxyCommand=$proxyCommand" "${TargetUser}@${TargetHost}" "bash -lc $remoteCommandLiteral"
