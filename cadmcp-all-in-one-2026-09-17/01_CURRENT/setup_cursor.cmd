@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 scripts\setup_cursor.py %*
) else (
  python scripts\setup_cursor.py %*
)
exit /b %errorlevel%
