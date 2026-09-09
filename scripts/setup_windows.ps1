[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$RegenerateSecrets,
    [string]$Python312
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($env:OS -ne "Windows_NT") {
    throw "This bootstrap script is intended for Windows."
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$venvPath = Join-Path $repoRoot ".venv"
$pythonPath = Join-Path $venvPath "Scripts\python.exe"
$envPath = Join-Path $repoRoot ".env"
$envExamplePath = Join-Path $repoRoot ".env.example"
$lockPath = Join-Path $repoRoot "requirements\dev-py312-windows.lock"
$dataDirectory = Join-Path $repoRoot "data"
$logDirectory = Join-Path $repoRoot "logs"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList
    )

    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE`: $FilePath $($ArgumentList -join ' ')"
    }
}

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

function Set-DotEnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value
    )

    $content = if (Test-Path -LiteralPath $Path) {
        [System.IO.File]::ReadAllText($Path)
    } else {
        ""
    }
    $pattern = "(?m)^\s*" + [regex]::Escape($Name) + "=.*$"
    $replacement = "$Name=$Value"
    if ([regex]::IsMatch($content, $pattern)) {
        $content = [regex]::Replace(
            $content,
            $pattern,
            [System.Text.RegularExpressions.MatchEvaluator]{ param($match) $replacement },
            1
        )
    } else {
        if ($content.Length -gt 0 -and -not $content.EndsWith("`n")) {
            $content += [Environment]::NewLine
        }
        $content += $replacement + [Environment]::NewLine
    }
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $content, $utf8NoBom)
}

function Test-FernetKey {
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$Value
    )

    $previous = $env:SCRUM_PORTAL_SETUP_FERNET
    try {
        $env:SCRUM_PORTAL_SETUP_FERNET = $Value
        & $Python -c "import os; from cryptography.fernet import Fernet; Fernet(os.environ['SCRUM_PORTAL_SETUP_FERNET'].encode('ascii'))" *> $null
        return $LASTEXITCODE -eq 0
    } finally {
        $env:SCRUM_PORTAL_SETUP_FERNET = $previous
    }
}

Push-Location $repoRoot
try {
    if (-not (Test-Path -LiteralPath $pythonPath)) {
        $bootstrapExecutable = $null
        $bootstrapArguments = @()
        if (-not [string]::IsNullOrWhiteSpace($Python312)) {
            if (-not (Test-Path -LiteralPath $Python312 -PathType Leaf)) {
                throw "The Python 3.12 executable does not exist: $Python312"
            }
            $bootstrapExecutable = (Resolve-Path -LiteralPath $Python312).Path
        } else {
            $pyLauncher = Get-Command "py.exe" -ErrorAction SilentlyContinue
            if ($pyLauncher) {
                $bootstrapExecutable = $pyLauncher.Source
                $bootstrapArguments = @("-3.12")
            } else {
                $pythonCommand = Get-Command "python.exe" -ErrorAction SilentlyContinue
                if ($pythonCommand) {
                    $bootstrapExecutable = $pythonCommand.Source
                }
            }
        }
        if (-not $bootstrapExecutable) {
            throw "Python was not found. Install 64-bit Python 3.12 or pass -Python312 with its full executable path."
        }
        $bootstrapVersion = (& $bootstrapExecutable @bootstrapArguments -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
        if ($LASTEXITCODE -ne 0 -or $bootstrapVersion -ne "3.12") {
            throw "Python 3.12 is required; found '$bootstrapVersion'. Install it or pass -Python312 with its full executable path."
        }
        Write-Host "Creating Python 3.12 virtual environment..."
        Invoke-Checked -FilePath $bootstrapExecutable -ArgumentList @($bootstrapArguments + @("-m", "venv", $venvPath))
    }

    $version = (& $pythonPath -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
    if ($LASTEXITCODE -ne 0 -or $version -ne "3.12") {
        throw "The virtual environment must use Python 3.12; found '$version'. Delete .venv and rerun this script."
    }

    Write-Host "Installing locked development dependencies..."
    Invoke-Checked -FilePath $pythonPath -ArgumentList @(
        "-m", "pip", "install", "--require-hashes", "-r", $lockPath
    )

    $createdEnv = -not (Test-Path -LiteralPath $envPath)
    if ($createdEnv) {
        Copy-Item -LiteralPath $envExamplePath -Destination $envPath
        Write-Host "Created .env from .env.example. Jira and Tableau values were left for manual configuration."
    }

    New-Item -ItemType Directory -Force -Path $dataDirectory, $logDirectory | Out-Null
    $databasePath = (Join-Path $dataDirectory "scrum_portal.db")
    $databaseUri = "sqlite:///" + ($databasePath -replace "\\", "/")
    $configuredDatabase = Get-DotEnvValue -Path $envPath -Name "DATABASE_URL"
    if ([string]::IsNullOrWhiteSpace($configuredDatabase) -or $configuredDatabase -eq "sqlite:///app.db") {
        Set-DotEnvValue -Path $envPath -Name "DATABASE_URL" -Value $databaseUri
    }

    if ($createdEnv) {
        Set-DotEnvValue -Path $envPath -Name "APP_ENV" -Value "development"
        Set-DotEnvValue -Path $envPath -Name "TRUSTED_HOSTS" -Value "localhost,127.0.0.1"
        Set-DotEnvValue -Path $envPath -Name "TRUSTED_PROXY_COUNT" -Value "0"
        Set-DotEnvValue -Path $envPath -Name "SESSION_COOKIE_SECURE" -Value "false"
        Set-DotEnvValue -Path $envPath -Name "REMEMBER_COOKIE_SECURE" -Value "false"
        Set-DotEnvValue -Path $envPath -Name "SPRINT_VIEWER_MODE" -Value "snapshot"
        Set-DotEnvValue -Path $envPath -Name "SPRINT_SNAPSHOT_ACCESS_POLICY" -Value "jira_revalidate"
        Set-DotEnvValue -Path $envPath -Name "LOG_TO_CONSOLE" -Value "true"
    }

    $secretKey = Get-DotEnvValue -Path $envPath -Name "SECRET_KEY"
    $secretIsPlaceholder = [string]::IsNullOrWhiteSpace($secretKey) -or
        $secretKey.Length -lt 32 -or
        $secretKey -match "^(change-me|replace-with|dev-secret)"
    if ($RegenerateSecrets -or $secretIsPlaceholder) {
        $secretKey = (& $pythonPath -c "import secrets; print(secrets.token_urlsafe(48))").Trim()
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to generate SECRET_KEY."
        }
        Set-DotEnvValue -Path $envPath -Name "SECRET_KEY" -Value $secretKey
        Write-Host "Generated SECRET_KEY."
    }

    $fernetKey = Get-DotEnvValue -Path $envPath -Name "FERNET_KEY"
    $fernetIsValid = $false
    if (-not [string]::IsNullOrWhiteSpace($fernetKey)) {
        $fernetIsValid = Test-FernetKey -Python $pythonPath -Value $fernetKey
    }
    if ($RegenerateSecrets -or -not $fernetIsValid) {
        $fernetKey = (& $pythonPath -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode('ascii'))").Trim()
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to generate FERNET_KEY."
        }
        Set-DotEnvValue -Path $envPath -Name "FERNET_KEY" -Value $fernetKey
        Write-Host "Generated FERNET_KEY."
    }

    Write-Host "Inspecting and preparing SQLite..."
    Invoke-Checked -FilePath $pythonPath -ArgumentList @("-m", "flask", "--app", "wsgi:app", "setup-db", "--check")
    Invoke-Checked -FilePath $pythonPath -ArgumentList @("-m", "flask", "--app", "wsgi:app", "setup-db", "--apply")
    Invoke-Checked -FilePath $pythonPath -ArgumentList @("-m", "flask", "--app", "wsgi:app", "check-db")

    Write-Host "Running smoke verification..."
    Invoke-Checked -FilePath $pythonPath -ArgumentList @("scripts\smoke_check.py")
    if (-not $SkipTests) {
        Write-Host "Running the test suite..."
        Invoke-Checked -FilePath $pythonPath -ArgumentList @("-m", "pytest", "-q")
    }

    Write-Host ""
    Write-Host "Windows setup completed successfully." -ForegroundColor Green
    Write-Host "Configure JIRA_BASE_URL, Jira custom fields, and optional Tableau values in .env."
    Write-Host "Users add their Jira PAT through signup or Settings; the script never writes a PAT."
    Write-Host "Start the application with: .\scripts\run_windows.ps1"
} finally {
    Pop-Location
}
