param(
    [int]$Port = 8766,
    [string]$BindHost = "127.0.0.1",
    [switch]$NoOpen,
    [ValidateSet("uvalde")]
    [string]$Map = "uvalde"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$PythonExe = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    Write-Error "Python venv not found at $PythonExe. Recreate .venv first."
}

$RuntimeDir = Join-Path $Root ".runtime"
New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null
$PidFile = Join-Path $RuntimeDir "serverrun_ui.pid"
$LegacyPidFile = Join-Path $Root ".serverrun_ui.pid"
$StdOutLog = Join-Path $RuntimeDir "serverrun_ui.out.log"
$StdErrLog = Join-Path $RuntimeDir "serverrun_ui.err.log"
$LockFile = Join-Path $RuntimeDir "serverrun.lock"
$LockStream = $null
try {
    $LockStream = [System.IO.File]::Open(
        $LockFile,
        [System.IO.FileMode]::OpenOrCreate,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
} catch {
    Write-Error "Another serverrun start or stop operation is already in progress."
}

function Test-PortOpen {
    param([string]$BindAddress, [int]$Port)
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $iar = $client.BeginConnect($BindAddress, $Port, $null, $null)
        $ok = $iar.AsyncWaitHandle.WaitOne(200)
        if (-not $ok) { $client.Close(); return $false }
        $client.EndConnect($iar)
        $client.Close()
        return $true
    } catch {
        return $false
    }
}

function Test-ServerRunProcess {
    param([System.Diagnostics.Process]$Process)
    if (-not $Process) { return $false }
    try {
        $commandLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $($Process.Id)").CommandLine
        return $commandLine -match "-m\s+solara" -and (
            $commandLine -match "run\\serverrun.py" -or
            $commandLine -match "run/serverrun.py" -or
            $commandLine -match "run\.serverrun:page"
        )
    } catch {
        return $false
    }
}

function Stop-ExistingServerRun {
    # 1) Stop process recorded in pid file
    foreach ($candidatePidFile in @($PidFile, $LegacyPidFile)) {
        if (-not (Test-Path $candidatePidFile)) { continue }
        try {
            $oldPid = [int](Get-Content $candidatePidFile -Raw).Trim()
            $proc = Get-Process -Id $oldPid -ErrorAction SilentlyContinue
            if ($proc -and (Test-ServerRunProcess -Process $proc)) {
                Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
                Start-Sleep -Milliseconds 400
            }
        } catch {
            # ignore malformed/stale pid file
        }
        Remove-Item $candidatePidFile -Force -ErrorAction SilentlyContinue
    }

    # 2) Defensive cleanup: any solara process running this app
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
            try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } catch {}
        }
}

Stop-ExistingServerRun

$env:FLOODDISEASE_ABM_MAP = $Map
$env:FLOOD_APP_PORT = "$Port"

$pythonArgs = @("-m", "solara", "run", "run/serverrun.py", "--host", $BindHost, "--port", "$Port", "--no-open")
$proc = Start-Process -FilePath $PythonExe -ArgumentList $pythonArgs -WorkingDirectory $Root -PassThru -WindowStyle Hidden -RedirectStandardOutput $StdOutLog -RedirectStandardError $StdErrLog

$proc.Id | Set-Content $PidFile

$url = "http://$BindHost`:$Port"

$started = $false
for ($i = 0; $i -lt 1800; $i++) {
    Start-Sleep -Milliseconds 100
    if (Test-PortOpen -BindAddress $BindHost -Port $Port) {
        $started = $true
        break
    }
    if ($proc.HasExited) { break }
}

if (-not $started) {
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    if ($LockStream) { $LockStream.Dispose() }
    Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
    Write-Host "Server did not start. Showing stderr log tail:" -ForegroundColor Yellow
    if (Test-Path $StdErrLog) {
        Get-Content $StdErrLog -Tail 80
    } else {
        Write-Host "No stderr log found at $StdErrLog"
    }
    exit 1
}

if ($LockStream) { $LockStream.Dispose() }
Remove-Item $LockFile -Force -ErrorAction SilentlyContinue

Write-Host "Serverrun started at $url" -ForegroundColor Green
Write-Host "PID: $($proc.Id)"
Write-Host "Logs: $StdOutLog and $StdErrLog"

if (-not $NoOpen) {
    Start-Process -FilePath "explorer.exe" -ArgumentList $url | Out-Null
}
