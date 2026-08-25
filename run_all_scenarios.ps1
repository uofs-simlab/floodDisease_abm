[CmdletBinding()]
param(
    [int]$Persons = 500,
    [int]$Replications = 30,
    [int]$Workers = 4,
    [uint32]$SeedBase = 2684470948,
    [switch]$KeepRepFolders,
    [ValidateSet("gottlieb", "richardson", "hundsdorfer")]
    [string]$RemoteTarget = "gottlieb",
    [string]$RemoteUser = "oaa721",
    [string]$RemotePassword = $env:FLOODDISEASE_ABM_REMOTE_PASSWORD,
    [string]$SshKey = (Join-Path $env:USERPROFILE ".ssh\id_ed25519_usask_hpc"),
    [string]$RemoteRepo = "",
    [int]$PollSeconds = 60
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function ConvertTo-BashSingleQuoted {
    param([string]$Value)
    return "'" + ($Value -replace "'", '''"''"''') + "'"
}

function Ensure-SshAgentKey {
    param([string]$KeyPath)
    try { Start-Service ssh-agent -ErrorAction SilentlyContinue } catch {}
    $loaded = ssh-add -l 2>$null
    if ($LASTEXITCODE -ne 0 -or $loaded -notmatch [regex]::Escape((ssh-keygen -lf "$KeyPath.pub" | ForEach-Object { ($_ -split '\s+')[1] }))) {
        Write-Host "SSH key is not loaded in ssh-agent. Loading it now; enter its passphrase if prompted." -ForegroundColor Yellow
        ssh-add $KeyPath
        if ($LASTEXITCODE -ne 0) { throw "Could not load SSH key into ssh-agent: $KeyPath" }
    }
}

function Test-SshConnection {
    param(
        [string]$KeyPath,
        [string]$TargetHost,
        [string]$TargetUser,
        [string]$ProxyUser = "oaa721",
        [string]$ProxyHost = "tuxworld.usask.ca"
    )

    $proxy = "ssh -i `"$KeyPath`" -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=20 -W %h:%p ${ProxyUser}@${ProxyHost}"
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $result = @(& ssh -i $KeyPath -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=20 -o "ProxyCommand=$proxy" "${TargetUser}@${TargetHost}" "hostname; whoami" 2>&1 | ForEach-Object { $_.ToString() })
    $sshExitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorActionPreference
    if ($sshExitCode -ne 0) {
        $fingerprint = (ssh-keygen -lf "$KeyPath.pub" | ForEach-Object { ($_ -split '\s+')[1] })
        $details = ($result | Out-String).Trim()
        throw "SSH preflight failed for ${TargetUser}@${TargetHost} through ${ProxyHost}. Configured key fingerprint: $fingerprint. Register this public key on the target if authentication is rejected. Details: $details"
    }
    Write-Host "SSH preflight succeeded: $($result -join ' | ')" -ForegroundColor Green
}

$launcher = Join-Path $root "scripts\run_remote_batch_via_tux.ps1"
if (-not (Test-Path $launcher)) {
    throw "Remote launcher was not found at $launcher."
}
Ensure-SshAgentKey $SshKey

$runners = @(
    @{ Name = "baseline"; Script = "run\baseline.py"; SupportsRemote = $true },
    @{ Name = "flood_only"; Script = "run\flood_only.py"; SupportsRemote = $true },
    @{ Name = "flood_mold"; Script = "run\flood_mold.py"; SupportsRemote = $true },
    @{ Name = "flood_vectorborne"; Script = "run\flood_vectorborne.py"; SupportsRemote = $true },
    @{ Name = "flood_mold_vectorborne"; Script = "run\flood_mold_vectorborne.py"; SupportsRemote = $true },
    @{ Name = "infectious_disease"; Script = "run\infectious_disease.py"; SupportsRemote = $true },
    @{ Name = "flood_infectious"; Script = "run\flood_infectious.py"; SupportsRemote = $true },
    @{ Name = "full_compound"; Script = "run\full_compound.py"; SupportsRemote = $true }
)

Write-Host "ABM batch suite" -ForegroundColor Cyan
Write-Host "Persons: $Persons | Replications: $Replications | Workers: $Workers | Seed base: $SeedBase"
Write-Host "Remote target: $RemoteTarget"
Write-Host "SSH transport: existing Tuxworld jump-host launcher"
Test-SshConnection -KeyPath $SshKey -TargetHost $RemoteTarget -TargetUser $RemoteUser

$sessionNames = @()
$remoteRepoDisplay = if (-not [string]::IsNullOrWhiteSpace($RemoteRepo)) {
    $RemoteRepo
} elseif ($RemoteTarget -eq "gottlieb") {
    "/scratch-gladwell/$RemoteUser/floodDisease_abm"
} else {
    "/scratch/$RemoteUser/floodDisease_abm"
}
$remoteRunnerPath = "${RemoteUser}@${RemoteTarget}:$remoteRepoDisplay/scripts/run_lab_flood_infectious.sh"
Write-Host "Synchronizing local workspace to $RemoteTarget..." -ForegroundColor Cyan
$syncScript = Join-Path $root "scripts\sync_remote_via_tux.ps1"
$syncArgs = @(
    "-Target", $RemoteTarget,
    "-TargetUser", $RemoteUser,
    "-RemoteRepo", $remoteRepoDisplay,
    "-SshKey", $SshKey
)
& powershell -NoProfile -ExecutionPolicy Bypass -File $syncScript @syncArgs
if ($LASTEXITCODE -ne 0) { throw "Workspace synchronization failed; no scenarios were submitted." }

$sshOptions = @("-n", "-i", $SshKey, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20")
$proxyCommand = "ssh -i `"$SshKey`" -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=20 -W %h:%p ${RemoteUser}@tuxworld.usask.ca"
$scpOptions = @("-i", $SshKey, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "ProxyCommand=$proxyCommand")
scp @scpOptions (Join-Path $root "scripts\run_lab_flood_infectious.sh") $remoteRunnerPath | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not upload the flood-infectious remote runner." }
ssh @sshOptions -o "ProxyCommand=$proxyCommand" "${RemoteUser}@${RemoteTarget}" "chmod +x '$remoteRepoDisplay/scripts/run_lab_flood_infectious.sh'" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not mark the flood-infectious remote runner executable." }

$cleanupCommand = 'cd ' + (ConvertTo-BashSingleQuoted $remoteRepoDisplay) + '; for session in $(tmux ls -F ''#S'' 2>/dev/null | grep -E ''^(baseline|flood_only|flood_mold|flood_vectorborne|flood_mold_vectorborne|infectious_disease|flood_infectious|full_compound)_[0-9]+x[0-9]+_' + [regex]::Escape($RemoteTarget) + '$'' || true); do status_file=outputs/logs/${session}.status; status=$(cat "$status_file" 2>/dev/null || true); case "$status" in 0|[1-9]*) tmux kill-session -t "$session" 2>/dev/null || true;; esac; done'
$cleanupBytes = [System.Text.Encoding]::UTF8.GetBytes($cleanupCommand)
$cleanupBase64 = [Convert]::ToBase64String($cleanupBytes)
$cleanupRemote = ConvertTo-BashSingleQuoted ("echo $cleanupBase64 | base64 -d | bash")
Write-Host "Cleaning up previously completed tmux sessions..." -ForegroundColor Cyan
ssh @sshOptions -o "ProxyCommand=$proxyCommand" "${RemoteUser}@${RemoteTarget}" "bash -lc $cleanupRemote" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not clean up completed remote tmux sessions." }

foreach ($runner in $runners) {
    $started = Get-Date
    Write-Host "[$started] Starting $($runner.Name)" -ForegroundColor Yellow

    $outputNames = @{
        flood_only = "floodonly"
    }
    $outputName = if ($outputNames.ContainsKey($runner.Name)) { $outputNames[$runner.Name] } else { $runner.Name }
    $scenarioOutDir = "outputs/$($runner.Name)/${outputName}_${Persons}x${Replications}"
    $batchArgs = "--persons $Persons --replications $Replications --seed-base $SeedBase --out-dir $scenarioOutDir"
    if ($runner.SupportsRemote) { $batchArgs += " --workers $Workers" }
    if ($KeepRepFolders) { $batchArgs += " --keep-rep-folders" }
    $launcherArgs = @(
        "-Target", $RemoteTarget,
        "-TargetUser", $RemoteUser,
        "-Runner", $runner.Name,
        "-BatchArgs", $batchArgs,
        "-SessionName", "$($runner.Name)_${Persons}x${Replications}_$RemoteTarget",
        "-KillExistingSession",
        "-SshKey", $SshKey
    )
    if (-not [string]::IsNullOrWhiteSpace($RemoteRepo)) {
        $launcherArgs += @("-RemoteRepo", $RemoteRepo)
    }
    & powershell -NoProfile -ExecutionPolicy Bypass -File $launcher @launcherArgs
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "$($runner.Name) failed with exit code $exitCode. Earlier scenarios completed; inspect outputs/logs before rerunning."
    }
    $sessionNames += "$($runner.Name)_${Persons}x${Replications}_$RemoteTarget"
    Write-Host "[$(Get-Date)] Submitted $($runner.Name)" -ForegroundColor Green
}

Write-Host "All scenarios submitted. Waiting for remote simulations to finish..." -ForegroundColor Cyan
$graphScripts = @{
    baseline = "analysis/generate_baseline_graphs.py"
    flood_only = "analysis/generate_floodonly_graphs.py"
    flood_mold = "analysis/generate_flood_mold_graphs.py"
    flood_vectorborne = "analysis/generate_flood_vectorborne_graphs.py"
    flood_mold_vectorborne = "analysis/generate_flood_mold_vectorborne_graphs.py"
    infectious_disease = "analysis/generate_infectious_disease_graphs.py"
    flood_infectious = "analysis/generate_flood_infectious_graphs.py"
    full_compound = "analysis/generate_full_compound_graphs.py"
}
$graphOutputDirs = @{
    baseline = "baseline_graphs"
    flood_only = "floodonly_graphs"
    flood_mold = "flood_mold_graphs"
    flood_vectorborne = "flood_vectorborne_graphs"
    flood_mold_vectorborne = "flood_mold_vectorborne_graphs"
    infectious_disease = "infectious_disease_graphs"
    flood_infectious = "flood_infectious_graphs"
    full_compound = "full_compound_graphs"
}
$completedScenarios = @{}
function Complete-Scenario {
    param([string]$ScenarioName)
    if ($completedScenarios.ContainsKey($ScenarioName)) { return }
    $sessionName = "${ScenarioName}_${Persons}x${Replications}_$RemoteTarget"
    $outputName = if ($outputNames.ContainsKey($ScenarioName)) { $outputNames[$ScenarioName] } else { $ScenarioName }
    $scenarioDir = "outputs/$ScenarioName/${outputName}_${Persons}x${Replications}"
    $remoteTar = "/tmp/floodDisease_${ScenarioName}_${Persons}x${Replications}.tar.gz"
    $remoteScript = "set -euo pipefail; cd '$remoteRepoDisplay'; tar -czf '$remoteTar' '$scenarioDir'; echo TAR_OK" 
    $remoteLiteral = "'" + ($remoteScript -replace "'", '''"''"''') + "'"
    $tarResult = ssh @sshOptions -o "ProxyCommand=$proxyCommand" "${RemoteUser}@${RemoteTarget}" "bash -lc $remoteLiteral"
    if ($LASTEXITCODE -ne 0 -or ($tarResult -notmatch "TAR_OK")) { throw "Could not package completed scenario $ScenarioName." }
    $localTar = Join-Path $env:TEMP "floodDisease_${ScenarioName}_${Persons}x${Replications}.tar.gz"
    scp @scpOptions "${RemoteUser}@${RemoteTarget}:$remoteTar" $localTar
    if ($LASTEXITCODE -ne 0) { throw "Could not download completed scenario $ScenarioName." }
    tar -xzf $localTar -C $root
    if ($LASTEXITCODE -ne 0) { throw "Could not extract completed scenario $ScenarioName." }
    Remove-Item $localTar -Force
    ssh @sshOptions -o "ProxyCommand=$proxyCommand" "${RemoteUser}@${RemoteTarget}" "rm -f '$remoteTar'" | Out-Null
    $runDir = Join-Path $root "outputs/$ScenarioName/${outputName}_${Persons}x${Replications}"
    $summary = Join-Path $runDir "summary_stats.csv"
    if (-not (Test-Path $summary)) { throw "Completed scenario $ScenarioName has no summary_stats.csv: $summary" }
    Write-Host "[$(Get-Date)] Downloaded $ScenarioName; generating graphs..." -ForegroundColor Cyan
    & python (Join-Path $root $graphScripts[$ScenarioName]) --run-dir $runDir --scenario $ScenarioName --out-subdir $graphOutputDirs[$ScenarioName]
    if ($LASTEXITCODE -ne 0) { throw "Graph generation failed for $ScenarioName." }
    $cleanupScript = "set -euo pipefail; rm -rf " + (ConvertTo-BashSingleQuoted $scenarioDir) + "; rm -f " + (ConvertTo-BashSingleQuoted "outputs/logs/$sessionName.launcher.log") + " " + (ConvertTo-BashSingleQuoted "outputs/logs/$sessionName.status") + " " + (ConvertTo-BashSingleQuoted "outputs/logs/$sessionName.status.tmp")
    $cleanupLiteral = ConvertTo-BashSingleQuoted $cleanupScript
    ssh @sshOptions -o "ProxyCommand=$proxyCommand" "${RemoteUser}@${RemoteTarget}" "bash -lc $cleanupLiteral" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Remote cleanup failed for $ScenarioName after local graph generation." }
    $completedScenarios[$ScenarioName] = $true
    Write-Host "[$(Get-Date)] $ScenarioName complete and graphed." -ForegroundColor Green
}
do {
    Start-Sleep -Seconds $PollSeconds
    $active = @()
    $states = @()
    foreach ($session in $sessionNames) {
        $statusPath = "$remoteRepoDisplay/outputs/logs/$session.status"
        $scenarioLabel = $session -replace '_\d+x\d+_.*$', ''
        $outputName = if ($scenarioLabel -eq "flood_only") { "floodonly" } else { $scenarioLabel }
        $progressDir = "$remoteRepoDisplay/outputs/$scenarioLabel/${outputName}_${Persons}x${Replications}"
        $checkCommand = 'status=$(cat ' + (ConvertTo-BashSingleQuoted $statusPath) + ' 2>/dev/null || true); case "$status" in 0) echo DONE;; "") if tmux has-session -t ' + (ConvertTo-BashSingleQuoted $session) + ' 2>/dev/null; then progress=$(find ' + (ConvertTo-BashSingleQuoted $progressDir) + ' -maxdepth 1 -name ' + (ConvertTo-BashSingleQuoted 'rep_*_progress.json') + ' -type f -printf ''%T@ %p\n'' 2>/dev/null | sort -nr | head -n 1 | cut -d'' '' -f2-); if test -n "$progress" && test -s "$progress"; then printf ''RUNNING ''; tr -d ''\n'' < "$progress"; printf ''\n''; else echo RUNNING; fi; else echo WAITING; fi;; [1-9]*) echo FAILED;; *) echo UNKNOWN;; esac'
        $checkBytes = [System.Text.Encoding]::UTF8.GetBytes($checkCommand)
        $checkBase64 = [Convert]::ToBase64String($checkBytes)
        $checkRemoteCommand = "echo $checkBase64 | base64 -d | bash"
        $checkRemoteLiteral = ConvertTo-BashSingleQuoted $checkRemoteCommand
        $check = ssh @sshOptions -o "ProxyCommand=$proxyCommand" "${RemoteUser}@${RemoteTarget}" "bash -lc $checkRemoteLiteral"
        $state = if ($LASTEXITCODE -eq 0 -and $check) { ($check | Select-Object -Last 1).Trim() } else { "UNKNOWN" }
        if ($state -eq "DONE") {
            Complete-Scenario $scenarioLabel
        } elseif ($state -eq "FAILED") {
            throw "$scenarioLabel failed remotely. Inspect outputs/logs/$session.launcher.log on $RemoteTarget."
        }
        $states += "$scenarioLabel=$state"
        if (-not $completedScenarios.ContainsKey($scenarioLabel)) { $active += $session }
    }
    Write-Host "[$(Get-Date)] Scenario status"
    foreach ($state in $states) {
        Write-Host "  $state"
    }
} while ($active.Count -gt 0)

Write-Host "All scenarios completed, downloaded, and graphed successfully." -ForegroundColor Green
