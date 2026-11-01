# Restores a dump made by backup.ps1. This REPLACES the data in the target database.
#   Local:       .\ops\restore.ps1 -File <path to .dump>
#   Production:  .\ops\restore.ps1 -File <path> -Url $env:DATABASE_OWNER_URL
param([Parameter(Mandatory = $true)][string]$File, [string]$Url = "")

$ErrorActionPreference = "Stop"
if (-not (Test-Path $File)) { throw "No file at $File" }
$answer = Read-Host "This replaces all data in the target database. Type RESTORE to continue"
if ($answer -ne "RESTORE") { Write-Host "Cancelled."; exit 1 }

if ($Url) {
    & pg_restore --clean --if-exists --no-owner --dbname=($Url -replace '^postgresql\+psycopg://', 'postgresql://') $File
} else {
    $compose = Join-Path $PSScriptRoot "..\docker-compose.yml"
    docker compose -f $compose cp $File db:/tmp/restore.dump
    if ($LASTEXITCODE -eq 0) { docker compose -f $compose exec -T db pg_restore -U seosys_owner --clean --if-exists -d seosys /tmp/restore.dump }
}
if ($LASTEXITCODE -ne 0) { throw "Restore failed." }
Write-Host "Restored from $File. Run 'python -m alembic upgrade head' if the dump is from an older version."
