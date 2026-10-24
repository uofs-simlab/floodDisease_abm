param(
    [ValidateSet("hundsdorfer", "richardson", "gottlieb")]
    [string]$Target = "gottlieb",
    [string]$TargetUser = "oaa721",
    [string]$RemoteRepo = "",
    [string]$RemoteOutDir = "",
    [string]$LocalOutDir = "",
    [string]$SessionName = "",
    [string]$SshKey = (Join-Path $env:USERPROFILE ".ssh\id_ed25519_usask_hpc"),
    [string]$TuxUser = "oaa721",
    [string]$TuxHost = "tuxworld.usask.ca",
    [int]$PollSeconds = 300,
    [int]$MaxPolls = 240
)

$ErrorActionPreference = "Stop"

function ConvertTo-BashSingleQuoted {
    param([string]$Value)
    return "'" + ($Value -replace "'", '''"''"''') + "'"
}

$targetLower = $Target.ToLowerInvariant()
$targetHost = switch ($targetLower) {
    "gottlieb" { "gottlieb" }
    "richardson" { "richardson" }
    "hundsdorfer" { "hundsdorfer" }
}

if ([string]::IsNullOrWhiteSpace($RemoteRepo)) {
    $scratchRoot = if ($targetLower -eq "gottlieb") { "/scratch-gladwell" } else { "/scratch" }
    $RemoteRepo = "$scratchRoot/$TargetUser/floodDisease_abm"
}
if (-not $RemoteRepo.StartsWith("/")) {
    throw "RemoteRepo must be absolute or omitted."
}
if (
    [string]::IsNullOrWhiteSpace($RemoteOutDir) -or
    $RemoteOutDir.StartsWith("/") -or
    $RemoteOutDir -notlike "outputs/sensitivity_analysis/*" -or
    ($RemoteOutDir -split "/") -contains ".."
) {
    throw "RemoteOutDir must be a relative path under outputs/sensitivity_analysis/."
}
if ($SessionName -notmatch "^[A-Za-z0-9_]+$") {
    throw "SessionName may contain only letters, numbers, and underscores."
}
if ($PollSeconds -lt 1 -or $MaxPolls -lt 1) {
    throw "PollSeconds and MaxPolls must be positive."
}

$proxyJump = "${TuxUser}@${TuxHost}"
$sshOptions = @(
    "-i", $SshKey,
    "-o", "IdentitiesOnly=yes",
    "-o", "ConnectTimeout=20",
    "-o", "ConnectionAttempts=1"
)

function Invoke-RemoteCommand {
    param([string]$Command)
    $commandLiteral = ConvertTo-BashSingleQuoted $Command
    $output = & ssh @sshOptions -J $proxyJump `
        "${TargetUser}@${targetHost}" "bash -lc $commandLiteral"
    if ($LASTEXITCODE -ne 0) {
        throw "Remote command failed with exit code $LASTEXITCODE."
    }
    return ($output -join "`n").Trim()
}

$progressFile = "$RemoteRepo/$RemoteOutDir/_progress.json"
$statusFile = "$RemoteRepo/outputs/logs/$SessionName.status"
$complete = $false
for ($poll = 0; $poll -lt $MaxPolls; $poll++) {
    $progressText = Invoke-RemoteCommand "if [ -f '$progressFile' ]; then cat '$progressFile'; fi"
    if (-not [string]::IsNullOrWhiteSpace($progressText)) {
        try {
            $progress = $progressText | ConvertFrom-Json
        }
        catch {
            throw "Could not parse the remote sensitivity progress file."
        }
        Write-Host (
            "[REMOTE] {0}: {1}/{2} ({3:N1}%)" -f
            $progress.phase,
            $progress.completed,
            $progress.total,
            $progress.percent
        )
        if ($progress.phase -eq "complete" -and [double]$progress.percent -ge 100.0) {
            $complete = $true
            break
        }
    }

    $statusText = Invoke-RemoteCommand "if [ -f '$statusFile' ]; then cat '$statusFile'; fi"
    if (-not [string]::IsNullOrWhiteSpace($statusText)) {
        $remoteExitCode = 0
        if ([int]::TryParse($statusText, [ref]$remoteExitCode) -and $remoteExitCode -ne 0) {
            throw "Remote runner exited with code $remoteExitCode. Check outputs/logs/$SessionName.launcher.log on the remote host."
        }
    }

    if ($poll + 1 -lt $MaxPolls) {
        Start-Sleep -Seconds $PollSeconds
    }
}
if (-not $complete) {
    throw "Remote sensitivity analysis did not report completion within the polling limit."
}

$remoteTar = "/tmp/sensitivity_$([System.Guid]::NewGuid().ToString('N')).tar.gz"
$remoteOutputPath = "$RemoteRepo/$RemoteOutDir"
Invoke-RemoteCommand "tar -czf '$remoteTar' -C '$remoteOutputPath' ."

if ([string]::IsNullOrWhiteSpace($LocalOutDir)) {
    throw "LocalOutDir is required."
}
New-Item -ItemType Directory -Force -Path $LocalOutDir | Out-Null
$localTar = Join-Path $env:TEMP ("sensitivity_" + [System.Guid]::NewGuid().ToString("N") + ".tar.gz")
$remoteTarSpec = "${TargetUser}@${targetHost}:$remoteTar"
try {
    & scp -q @sshOptions -J $proxyJump -- $remoteTarSpec $localTar
    if ($LASTEXITCODE -ne 0) {
        throw "Could not download the remote sensitivity results."
    }
    & tar -xzf $localTar -C $LocalOutDir
    if ($LASTEXITCODE -ne 0) {
        throw "Could not extract the downloaded sensitivity results."
    }
}
finally {
    if (Test-Path -LiteralPath $localTar) {
        Remove-Item -LiteralPath $localTar -Force
    }
    try {
        Invoke-RemoteCommand "rm -f '$remoteTar'" | Out-Null
    }
    catch {
        Write-Warning "Could not remove the temporary remote archive."
    }
}

if (-not (Test-Path -LiteralPath (Join-Path $LocalOutDir "run_results.csv"))) {
    throw "Downloaded output is missing run_results.csv."
}
Write-Host "[OK] Sensitivity results downloaded to $LocalOutDir"
