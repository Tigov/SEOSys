# Runs the back-end test suite against the seosys_test database in Docker (run start.ps1 once first).
$ErrorActionPreference = "Stop"
$python = Join-Path $env:LOCALAPPDATA "ProjectSEOSys\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Run start.ps1 once first to create the Python environment." }
docker info *> $null
if ($LASTEXITCODE -ne 0) { throw "Docker Desktop is not running. Start it, then run this again." }
docker compose -f (Join-Path $PSScriptRoot "docker-compose.yml") up -d --wait
Set-Location (Join-Path $PSScriptRoot "backend")
& $python -m pytest @args
exit $LASTEXITCODE
