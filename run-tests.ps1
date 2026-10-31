# Runs the back-end test suite (uses the same environment as start.ps1; run start.ps1 once first).
$ErrorActionPreference = "Stop"
$python = Join-Path $env:LOCALAPPDATA "ProjectSEOSys\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Run start.ps1 once first to create the Python environment." }
Set-Location (Join-Path $PSScriptRoot "backend")
& $python -m pytest
