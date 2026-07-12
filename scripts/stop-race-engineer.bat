@echo off
REM Clean shutdown - stops the telemetry watcher, live coach, and Streamlit.
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    echo .venv not found. Run "uv sync" in the repo root first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" scripts\stop_all.py
