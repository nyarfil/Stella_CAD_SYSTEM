@echo off
setlocal
cd /d "%~dp0"
set PYTHONPATH=%~dp0
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" scripts\setup_req2cad.py %*
) else (
  where py >nul 2>nul
  if not errorlevel 1 (py -3 scripts\setup_req2cad.py %*) else (python scripts\setup_req2cad.py %*)
)
exit /b %errorlevel%
