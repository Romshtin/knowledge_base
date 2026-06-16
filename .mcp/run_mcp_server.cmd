@echo off
set PYTHONIOENCODING=utf-8
set HF_HUB_OFFLINE=1
set TRANSFORMERS_OFFLINE=1
"%~dp0.venv\Scripts\python.exe" "%~dp0server.py"
