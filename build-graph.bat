@echo off
rem Double-click to build the code-review graph. Run "build-graph.bat -Install" to also register it with your editor.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-graph.ps1" %*
echo.
pause
