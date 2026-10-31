#!/usr/bin/env bash
# macOS/Linux equivalent of start.ps1
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/ProjectSEOSys"
mkdir -p "$DATA"
[ -f "$ROOT/.env" ] && set -a && . "$ROOT/.env" && set +a
export SEO_DB_PATH="${SEO_DB_PATH:-$DATA/seo_platform.db}" DEMO_SITE_STATE="${DEMO_SITE_STATE:-$DATA/site_state.json}"
[ -x "$DATA/.venv/bin/python" ] || python3 -m venv "$DATA/.venv"
PY="$DATA/.venv/bin/python"
"$PY" -m pip install -q -r "$ROOT/backend/requirements.txt"
cd "$ROOT/backend"
"$PY" -m uvicorn demo_site.app:app --port 8001 & DEMO=$!
trap 'kill $DEMO 2>/dev/null' EXIT
echo "Portal: http://localhost:8000   Demo site: http://127.0.0.1:8001"
"$PY" -m uvicorn seo_platform.api:app --port 8000
