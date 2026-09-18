@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup.cmd --geometry or setup_req2cad.cmd first.
  exit /b 2
)
if not defined CADMCP_REQ2CAD_ROOT set "CADMCP_REQ2CAD_ROOT=%~dp0workspace\knowledge\req2cad"
".venv\Scripts\python.exe" -m cadmcp_brain.req2cad --root "%CADMCP_REQ2CAD_ROOT%" %*
exit /b %errorlevel%
