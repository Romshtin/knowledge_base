@echo off
set PYTHONUNBUFFERED=1
"%~dp0.venv\Scripts\python.exe" -u "%~dp0server.py"
