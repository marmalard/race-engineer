@echo off
REM One-click launcher - starts Streamlit + telemetry watcher, opens the browser.
REM Closing this window stops Streamlit; the watcher keeps running (use
REM stop-race-engineer.bat or the Toolbox Stop button to stop it).
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    echo .venv not found. Run "uv sync" in the repo root first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" scripts\launch.py
