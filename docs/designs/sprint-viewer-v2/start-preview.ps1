param([ValidateRange(1024, 65535)][int]$Port = 8794)

$ErrorActionPreference = 'Stop'
$docsRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
$previewPython = Join-Path $repoRoot '.venv/Scripts/python.exe'
$previewUrl = "http://127.0.0.1:$Port/designs/sprint-viewer-v2/index.html"

if (-not (Test-Path -LiteralPath $previewPython)) {
    throw "Project Python was not found at $previewPython. Run the project setup first, or open index.html directly in a browser."
}

$existingListener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if (-not $existingListener) {
    $serverArguments = @('-m', 'http.server', "$Port", '--bind', '127.0.0.1', '--directory', ('"{0}"' -f $docsRoot))
    $serverProcess = Start-Process -FilePath $previewPython -ArgumentList $serverArguments -WindowStyle Hidden -PassThru
    Write-Output "Started preview server (PID $($serverProcess.Id))."
}

$ready = $false
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    try {
        $response = Invoke-WebRequest -Uri $previewUrl -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -eq 200 -and $response.Content.Contains('id="suggestion-list"')) {
            $ready = $true
            break
        }
    } catch {
        if ($existingListener) { throw "Port $Port is in use but the sprint preview is unavailable. Try -Port 8795." }
    }
    Start-Sleep -Milliseconds 250
}
if (-not $ready) { throw "The preview did not become ready at $previewUrl. Try another port." }

Write-Output "Preview is ready: $previewUrl#overview"
Write-Output 'The server runs in the background and serves only the docs folder on this computer.'
