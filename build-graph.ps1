# Builds (or rebuilds) the code-review graph for this repo, prints its stats and opens the interactive map.
#   .\build-graph.ps1            full build + stats + HTML map
#   .\build-graph.ps1 -Install   also register the graph's MCP server with your editor
# Uses code-review-graph from PATH if you have it; otherwise installs it into this project's Python
# environment in %LOCALAPPDATA%\ProjectSEOSys (the same one start.ps1 uses).
param([switch]$Install)
$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot
Set-Location $repo

$crg = (Get-Command code-review-graph -ErrorAction SilentlyContinue).Source
if (-not $crg) {
    $venv = Join-Path $env:LOCALAPPDATA "ProjectSEOSys\.venv"
    $python = Join-Path $venv "Scripts\python.exe"
    if (-not (Test-Path $python)) {
        Write-Host "Creating Python environment in $venv ..."
        if (Get-Command py -ErrorAction SilentlyContinue) { py -3 -m venv $venv } else { python -m venv $venv }
    }
    $crg = Join-Path $venv "Scripts\code-review-graph.exe"
    if (-not (Test-Path $crg)) {
        Write-Host "Installing code-review-graph into $venv ..."
        & $python -m pip install --disable-pip-version-check -q code-review-graph
    }
}

Write-Host "Building the code-review graph for $repo ..."
& $crg build --repo $repo
if ($LASTEXITCODE -ne 0) { throw "code-review-graph build failed (exit $LASTEXITCODE)" }
& $crg status --repo $repo
if ($Install) { & $crg install --repo $repo }
& $crg visualize --repo $repo
$html = Join-Path $repo ".code-review-graph\graph.html"
if (Test-Path $html) { Start-Process $html; Write-Host "Opened $html" }
Write-Host "`nDone. Check this graph first when reading code (see CONTRIBUTING.md). After edits run:  code-review-graph update"
