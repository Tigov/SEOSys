@echo off
rem Double-click to start SEOSys locally. Add  -Reset  to start from a clean slate.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
