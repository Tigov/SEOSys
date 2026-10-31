# Starts the SEO platform proof of concept on Windows.
#   Demo client website : http://127.0.0.1:8001
#   Platform + portal   : http://localhost:8000   (API docs at /docs)
# Press Ctrl+C to stop both.
#
# The virtual environment, database and demo-site state live in %LOCALAPPDATA%\ProjectSEOSys
# so OneDrive does not try to sync thousands of library files or lock the database.
param([switch]$Reset)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$data = Join-Path $env:LOCALAPPDATA "ProjectSEOSys"
$venv = Join-Path $data ".venv"
$python = Join-Path $venv "Scripts\python.exe"
New-Item -ItemType Directory -Force -Path $data | Out-Null

# Load optional settings from .env
$envFile = Join-Path $root ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | Where-Object { $_ -match '^\s*[A-Z_]+\s*=' } | ForEach-Object {
        $name, $value = $_ -split '=', 2
        if ($value.Trim()) { Set-Item -Path "Env:$($name.Trim())" -Value $value.Trim() }
    }
}
if (-not $env:SEO_DB_PATH) { $env:SEO_DB_PATH = Join-Path $data "seo_platform.db" }
if (-not $env:DEMO_SITE_STATE) { $env:DEMO_SITE_STATE = Join-Path $data "site_state.json" }

if ($Reset) {
    Remove-Item -Force -ErrorAction SilentlyContinue $env:SEO_DB_PATH, $env:DEMO_SITE_STATE
    Write-Host "Cleared local data."
}

if (-not (Test-Path $python)) {
    Write-Host "Creating Python environment in $venv ..."
    if (Get-Command py -ErrorAction SilentlyContinue) { py -3 -m venv $venv } else { python -m venv $venv }
}
& $python -c "import sys; assert sys.version_info >= (3, 10), 'Python 3.10 or newer is required'"
Write-Host "Installing Python packages (first run takes a minute) ..."
& $python -m pip install --disable-pip-version-check -q -r (Join-Path $root "backend\requirements.txt")

Set-Location (Join-Path $root "backend")
$demo = Start-Process -FilePath $python -ArgumentList "-m", "uvicorn", "demo_site.app:app", "--port", "8001" -NoNewWindow -PassThru
$api = Start-Process -FilePath $python -ArgumentList "-m", "uvicorn", "seo_platform.api:app", "--port", "8000" -NoNewWindow -PassThru
try {
    Start-Sleep -Seconds 3
    Start-Process "http://localhost:8000"
    Write-Host "`nRunning. Portal: http://localhost:8000  Demo site: http://127.0.0.1:8001  Press Ctrl+C to stop.`n"
    Wait-Process -Id $api.Id
}
finally {
    foreach ($p in @($api, $demo)) { if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } }
}
