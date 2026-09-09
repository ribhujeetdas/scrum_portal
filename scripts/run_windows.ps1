[CmdletBinding()]
param(
    [switch]$ProductionStyle
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
$envPath = Join-Path $repoRoot ".env"
$logDirectory = Join-Path $repoRoot "logs"

function Get-DotEnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    $content = [System.IO.File]::ReadAllText($Path)
    $pattern = "(?m)^\s*" + [regex]::Escape($Name) + "=(.*)$"
    $match = [regex]::Match($content, $pattern)
    if (-not $match.Success) {
        return $null
    }
    return $match.Groups[1].Value.Trim()
}

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "The virtual environment is missing. Run .\scripts\setup_windows.ps1 first."
}
if (-not (Test-Path -LiteralPath $envPath)) {
    throw ".env is missing. Run .\scripts\setup_windows.ps1 first."
}

$mode = if ($env:SPRINT_VIEWER_MODE) {
    $env:SPRINT_VIEWER_MODE
} else {
    Get-DotEnvValue -Path $envPath -Name "SPRINT_VIEWER_MODE"
}
$snapshotUsers = if ($env:SPRINT_VIEWER_SNAPSHOT_USER_IDS) {
    $env:SPRINT_VIEWER_SNAPSHOT_USER_IDS
} else {
    Get-DotEnvValue -Path $envPath -Name "SPRINT_VIEWER_SNAPSHOT_USER_IDS"
}
$needsWorker = $mode -eq "snapshot" -or -not [string]::IsNullOrWhiteSpace($snapshotUsers)
$worker = $null
$webExitCode = 0

Push-Location $repoRoot
try {
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
