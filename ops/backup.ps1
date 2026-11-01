# Backs up the SEOSys database to a compressed dump file.
#   Local:       .\ops\backup.ps1                       (uses the Postgres in docker-compose.yml)
#   Production:  .\ops\backup.ps1 -Url $env:DATABASE_OWNER_URL -Out D:\backups
param([string]$Url = "", [string]$Out = (Join-Path $env:LOCALAPPDATA "ProjectSEOSys\backups"))

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$file = Join-Path $Out ("seosys-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".dump")

if ($Url) {
    & pg_dump --format=custom --no-owner --file=$file ($Url -replace '^postgresql\+psycopg://', 'postgresql://')
} else {
    # Dump inside the container and copy the file out: PowerShell 5.1 would mangle binary output through a pipe.
    $compose = Join-Path $PSScriptRoot "..\docker-compose.yml"
    docker compose -f $compose exec -T db pg_dump -U seosys_owner --format=custom --file=/tmp/seosys.dump seosys
    if ($LASTEXITCODE -eq 0) { docker compose -f $compose cp db:/tmp/seosys.dump $file }
}
if ($LASTEXITCODE -ne 0) { throw "Backup failed." }
Write-Host "Backup written to $file"
