@echo off
rem Double-click to start Indexora locally. Add  -Reset  to start from a clean slate.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
