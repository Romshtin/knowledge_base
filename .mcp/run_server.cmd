@echo off
set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8
set HF_HUB_OFFLINE=1
set TRANSFORMERS_OFFLINE=1
"%~dp0.venv\Scripts\python.exe" -u "%~dp0server.py"
