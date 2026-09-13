[CmdletBinding()]
param(
    [switch]$ProductionStyle,
    [switch]$SkipPreflight,
    [switch]$SprintViewerV2
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$setupPath = Join-Path $PSScriptRoot "setup_windows.ps1"
$pythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
$envPath = Join-Path $repoRoot ".env"
$logDirectory = Join-Path $repoRoot "logs"

# Both child processes inherit these overrides. Persist the same settings in
# .env when starting the web and worker manually or through a service manager.
if ($SprintViewerV2) {
    $env:SPRINT_VIEWER_MODE = "snapshot"
    $env:SPRINT_VIEWER_V2_ENABLED = "true"
}

if (-not $SkipPreflight) {
    Write-Host "Verifying dependencies and applying database migrations..."
    & $setupPath -SkipTests
}
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "The virtual environment is missing. Run .\scripts\setup_windows.ps1 first, or omit -SkipPreflight."
}
if (-not (Test-Path -LiteralPath $envPath)) {
    throw ".env is missing. Run .\scripts\setup_windows.ps1 first, or omit -SkipPreflight."
}

$worker = $null
$webExitCode = 0

Push-Location $repoRoot
try {
    $viewerConfigJson = & $pythonPath -c "import json; from app.config import Config; print(json.dumps({'mode': Config.SPRINT_VIEWER_MODE, 'v2': Config.SPRINT_VIEWER_V2_ENABLED, 'users': bool(Config.SPRINT_VIEWER_SNAPSHOT_USER_IDS.strip())}))"
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to read Sprint Viewer configuration."
    }
    $viewerConfig = $viewerConfigJson | ConvertFrom-Json
    $needsWorker = $viewerConfig.mode -eq "snapshot"
    if ($viewerConfig.v2 -and $needsWorker) {
        Write-Host "Sprint Viewer v2 enabled: /automation/sprint-viewer"
        if ($viewerConfig.users) {
            Write-Host "The snapshot user allowlist is active; only listed user IDs see v2."
        }
    } else {
        Write-Host "The original Sprint Viewer UI is selected. To use v2, launch with -SprintViewerV2."
    }
    if ($needsWorker) {
        New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
        $workerStdout = Join-Path $logDirectory "worker-dev.stdout.log"
        $workerStderr = Join-Path $logDirectory "worker-dev.stderr.log"
        Write-Host "Starting the Sprint Viewer worker in the background..."
        $worker = Start-Process `
            -FilePath $pythonPath `
            -ArgumentList @("-m", "workers.sprint_import_worker") `
            -WorkingDirectory $repoRoot `
            -WindowStyle Hidden `
            -RedirectStandardOutput $workerStdout `
            -RedirectStandardError $workerStderr `
            -PassThru
        Start-Sleep -Seconds 1
        if ($worker.HasExited) {
            throw "The Sprint Viewer worker stopped during startup. Check $workerStderr."
        }
        Write-Host "Worker started with process ID $($worker.Id)."
    } else {
        Write-Host "Sprint Viewer is in direct mode; no background worker is required."
    }

    if ($ProductionStyle) {
        Write-Host "Starting Waitress at http://127.0.0.1:8080 ..."
        & $pythonPath -m waitress --listen=127.0.0.1:8080 --threads=8 wsgi:app
    } else {
        Write-Host "Starting the development server at http://127.0.0.1:5000 ..."
        & $pythonPath wsgi.py
    }
    $webExitCode = $LASTEXITCODE
} finally {
    if ($worker -and -not $worker.HasExited) {
        Write-Host "Stopping Sprint Viewer worker process $($worker.Id)..."
        Stop-Process -Id $worker.Id
        Wait-Process -Id $worker.Id -ErrorAction SilentlyContinue
    }
    Pop-Location
}

exit $webExitCode
