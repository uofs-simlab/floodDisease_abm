param(
    [string]$RunDir   = "scenario_runs_hpc_1500",
    [string]$LocalDir = "",
    [string[]]$Scenarios = @("baseline", "infectious_disease", "flood_only", "flood_infectious", "full_compound")
)

$TuxHost      = "oaa721@tuxworld.usask.ca"
$GottliebHost = "oaa721@gottlieb"
$RemoteBase   = "/scratch-gladwell/oaa721/floodDisease_abm/dataCollection/$RunDir"

function ConvertTo-BashSingleQuoted {
    param([string]$Value)
    return "'" + ($Value -replace "'", '''"''"''') + "'"
}

if ($LocalDir -eq "") { $LocalDir = "dataCollection/$RunDir" }

$LocalAbs = Join-Path (Split-Path $PSScriptRoot -Parent) $LocalDir
New-Item -ItemType Directory -Force -Path $LocalAbs | Out-Null

Write-Host "[PULL] Remote : ${GottliebHost}:${RemoteBase}"
Write-Host "[PULL] Local  : $LocalAbs"

$TmpTar = "/tmp/results_${RunDir}.tar.gz"

$ScenarioArg = ($Scenarios -join " ")
$RemoteCmd = @'
set -euo pipefail
cd /scratch-gladwell/oaa721/floodDisease_abm/dataCollection/__RUN_DIR__
files=()
if [ -f scenario_comparison_aggregated.csv ]; then files+=(scenario_comparison_aggregated.csv); fi
if [ -f scenario_comparison_by_replication.csv ]; then files+=(scenario_comparison_by_replication.csv); fi
for sc in __SCENARIOS__; do
    if [ -d "$sc" ]; then
        for f in timeseries_quantiles.csv timeseries_all_replications.csv summary_by_replication.csv summary_stats.csv; do
            if [ -f "$sc/$f" ]; then
                files+=("$sc/$f")
            fi
        done
    fi
done
if [ "${#files[@]}" -eq 0 ]; then
    echo "No matching files found in run dir: __RUN_DIR__" >&2
    exit 1
fi
tar -czf __TMP_TAR__ "${files[@]}"
echo TAR_OK
'@
$RemoteCmd = $RemoteCmd.Replace("__RUN_DIR__", $RunDir)
$RemoteCmd = $RemoteCmd.Replace("__SCENARIOS__", $ScenarioArg)
$RemoteCmd = $RemoteCmd.Replace("__TMP_TAR__", $TmpTar)
$RemoteCmd = $RemoteCmd -replace "`r`n", "`n"
$RemoteCmdLiteral = ConvertTo-BashSingleQuoted $RemoteCmd

Write-Host "[PULL] Step 1/3 - Creating tar on Gottlieb..."
$tarResult = ssh -J $TuxHost $GottliebHost "bash -lc $RemoteCmdLiteral"
if ($LASTEXITCODE -ne 0 -or ($tarResult -notmatch "TAR_OK")) {
    Write-Error "[PULL] Failed to create tar. Output: $tarResult"; exit 1
}
Write-Host "[PULL] Tar created: $TmpTar"

$LocalTar = Join-Path $env:TEMP "results_${RunDir}.tar.gz"
Write-Host "[PULL] Step 2/3 - Downloading via tux..."
scp -o "ProxyJump=$TuxHost" "${GottliebHost}:${TmpTar}" "$LocalTar"
if ($LASTEXITCODE -ne 0) { Write-Error "[PULL] scp failed."; exit 1 }
$sizeMB = [math]::Round((Get-Item $LocalTar).Length / 1MB, 1)
Write-Host "[PULL] Downloaded $sizeMB MB"

Write-Host "[PULL] Step 3/3 - Extracting to $LocalAbs..."
tar -xzf "$LocalTar" -C "$LocalAbs"
if ($LASTEXITCODE -ne 0) { Write-Error "[PULL] Extraction failed."; exit 1 }

Remove-Item $LocalTar -Force
ssh -J $TuxHost $GottliebHost "rm -f $TmpTar" 2>$null

Write-Host "[PULL] Done. Results in: $LocalAbs"
Get-ChildItem -Recurse $LocalAbs -File | ForEach-Object { Write-Host "  $($_.FullName.Replace($LocalAbs,[string]::Empty))" }
