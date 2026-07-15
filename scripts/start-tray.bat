@echo off
rem Race Engineer system tray - no console window (pythonw).
start "" "%~dp0..\.venv\Scripts\pythonw.exe" "%~dp0tray_app.py"
