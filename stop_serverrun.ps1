$ErrorActionPreference = "SilentlyContinue"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$RuntimeDir = Join-Path $Root ".runtime"
$PidFile = Join-Path $RuntimeDir "serverrun_ui.pid"
$LegacyPidFile = Join-Path $Root ".serverrun_ui.pid"

foreach ($candidatePidFile in @($PidFile, $LegacyPidFile)) {
if (Test-Path $candidatePidFile) {
    try {
        $pid = [int](Get-Content $candidatePidFile -Raw).Trim()
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $pid"
        if ($process -and $process.CommandLine -match "-m\s+solara" -and ($process.CommandLine -match "run\\serverrun.py" -or $process.CommandLine -match "run/serverrun.py" -or $process.CommandLine -match "run\.serverrun:page")) {
            Stop-Process -Id $pid -Force
            Write-Host "Stopped serverrun PID $pid"
        }
    } catch {}
    Remove-Item $candidatePidFile -Force -ErrorAction SilentlyContinue
}
}

Get-CimInstance Win32_Process |
    Where-Object {
        $_.Name -match "python(.exe)?" -and
        $_.CommandLine -match "-m\s+solara" -and
        (
            $_.CommandLine -match "run\\serverrun.py" -or
            $_.CommandLine -match "run/serverrun.py" -or
            $_.CommandLine -match "run\.serverrun:page"
        )
    } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped serverrun PID $($_.ProcessId)"
    }
