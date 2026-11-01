# Starts SEOSys on Windows.
#   Portal + API        : http://localhost:8000   (API docs at /docs in development)
#   Email inbox (local) : http://localhost:8025
#   Demo client website : http://127.0.0.1:8001
# Press Ctrl+C to stop. Postgres and Mailpit keep running in Docker (docker compose stop to stop them).
#
# The virtual environment and demo-site state live in %LOCALAPPDATA%\ProjectSEOSys so OneDrive
# does not try to sync thousands of library files.
param([switch]$Reset)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$data = Join-Path $env:LOCALAPPDATA "ProjectSEOSys"
$venv = Join-Path $data ".venv"
$python = Join-Path $venv "Scripts\python.exe"
New-Item -ItemType Directory -Force -Path $data | Out-Null

# Load settings from .env
$envFile = Join-Path $root ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | Where-Object { $_ -match '^\s*[A-Z_0-9]+\s*=' } | ForEach-Object {
        $name, $value = $_ -split '=', 2
        if ($value.Trim()) { Set-Item -Path "Env:$($name.Trim())" -Value $value.Trim() }
    }
}
if (-not $env:DEMO_SITE_STATE) { $env:DEMO_SITE_STATE = Join-Path $data "site_state.json" }

# Postgres and Mailpit run in Docker.
docker info *> $null
if ($LASTEXITCODE -ne 0) { throw "Docker Desktop is not running. Start it, wait for 'Engine running', then run this again." }
docker compose -f (Join-Path $root "docker-compose.yml") up -d --wait
if ($LASTEXITCODE -ne 0) { throw "The local database or mail service did not start. See: docker compose logs" }

if (-not (Test-Path $python)) {
    Write-Host "Creating Python environment in $venv ..."
    if (Get-Command py -ErrorAction SilentlyContinue) { py -3 -m venv $venv } else { python -m venv $venv }
}
& $python -c "import sys; assert sys.version_info >= (3, 12), 'Python 3.12 or newer is required'"
Write-Host "Installing Python packages (first run takes a minute) ..."
& $python -m pip install --disable-pip-version-check -q -r (Join-Path $root "backend\requirements.txt")

Set-Location (Join-Path $root "backend")
if ($Reset) {
    & $python -m alembic downgrade base
    Remove-Item -Force -ErrorAction SilentlyContinue $env:DEMO_SITE_STATE
    Write-Host "Cleared local data."
}
& $python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw "Database migration failed." }
& $python -m seo_platform seed --demo
if ($LASTEXITCODE -ne 0) { throw "Seeding local data failed." }

$demo = Start-Process -FilePath $python -ArgumentList "-m", "uvicorn", "demo_site.app:app", "--port", "8001" -NoNewWindow -PassThru
$api = Start-Process -FilePath $python -ArgumentList "-m", "uvicorn", "seo_platform.api:app", "--port", "8000", "--proxy-headers" -NoNewWindow -PassThru
try {
    Start-Sleep -Seconds 3
    Start-Process "http://localhost:8000"
    Write-Host "`nRunning. Portal: http://localhost:8000  Email inbox: http://localhost:8025  Press Ctrl+C to stop.`n"
    Wait-Process -Id $api.Id
}
finally {
    foreach ($p in @($api, $demo)) { if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } }
}
